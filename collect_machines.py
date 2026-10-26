"""Read public rendered tables with stock Chromium; never bypass challenges."""
import asyncio
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import requests
from collect_sources import BASE, SOURCES, layout_on, write_json

ORIGIN = "https://min-repo.com"
STORE = "楽園上新屋店"
AGENT = "RakuenJugglerAI"
ALIASES = {"funky2": "ファンキージャグラー2KT", "girls": "ジャグラーガールズSS"}
HEADERS = ["台番", "差枚", "G数", "出率", "BB", "RB", "合成", "BB率", "RB率"]
CHALLENGE = re.compile(r"verify (?:you are|that you are) human|checking your browser|unusual traffic|access denied|ロボットでは|人間であること|captcha", re.I)


def normalized(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def report_day(label, today):
    match = re.fullmatch(r"(?:(\d{4})/)?(\d{1,2})/(\d{1,2})\([月火水木金土日]\)", label.strip())
    if not match:
        return None
    year, month, day = match.groups()
    try:
        value = date(int(year or today.year), int(month), int(day))
        if not year and value > today:
            value = value.replace(year=value.year - 1)
        return value if value < today else None
    except ValueError:
        return None


def public_url(url):
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == "min-repo.com" and not parsed.fragment


def latest_report(links, today):
    reports = []
    for link in links:
        day = report_day(link["text"], today)
        url = urljoin(ORIGIN, link["href"])
        if day and public_url(url) and re.fullmatch(r"/\d+/", urlparse(url).path) and not urlparse(url).query:
            reports.append((day, url))
    if not reports:
        raise ValueError("No completed daily report found")
    return max(reports)


def integer(value, nonnegative=False):
    value = unicodedata.normalize("NFKC", value).replace(",", "").replace("−", "-").strip()
    if value in ("", "-", "―", "—"):
        return None
    if not re.fullmatch(r"[+-]?\d+", value):
        raise ValueError("Invalid integer in source table")
    number = int(value)
    if nonnegative and number < 0:
        raise ValueError("Negative game/bonus count")
    return number


def parse_tables(tables, model, day, source_url):
    matching = [t for t in tables if t and [normalized(x) for x in t[0]] == HEADERS]
    if len(matching) != 1:
        raise ValueError("Expected one BB/RB machine table")
    rows, seen = [], set()
    for cells in matching[0][1:]:
        if [normalized(x) for x in cells] == HEADERS:
            continue  # repeated header inside long tables
        if cells and cells[0] in ("平均", "合計"):
            continue
        if len(cells) != len(HEADERS):
            raise ValueError("Unexpected source columns")
        number = integer(cells[0], True)
        if number not in model["numbers"] or number in seen:
            raise ValueError("Duplicate number or installation layout mismatch")
        seen.add(number)
        games, bb, rb = [integer(cells[i], True) for i in (2, 4, 5)]
        if games is not None and bb is not None and rb is not None and bb + rb > games:
            raise ValueError("Bonus count exceeds game count")
        rows.append({"date": str(day), "model_id": model["model_id"],
                     "number": number, "games": games, "bb": bb, "rb": rb,
                     "difference": integer(cells[1]), "source": "min-repo",
                     "source_url": source_url})
    if seen != set(model["numbers"]):
        raise ValueError("Missing machines; refusing to save an incomplete table")
    return sorted(rows, key=lambda row: row["number"])


def merge_records(existing, incoming):
    merged = {}
    for record in [*existing, *incoming]:
        key = (record["date"], record["model_id"], record["number"])
        previous = merged.get(key, {})
        # Missing values never erase a previously collected numeric fact.
        merged[key] = {**previous, **{k: v for k, v in record.items() if v is not None or k not in previous}}
    return [merged[key] for key in sorted(merged)]


def robots_policy():
    response = requests.get(ORIGIN + "/robots.txt", timeout=25, headers={"User-Agent": AGENT})
    policy = RobotFileParser()
    if response.status_code == 404:
        policy.parse([])
    else:
        response.raise_for_status()
        policy.parse(response.text.splitlines())
    return policy


async def scrape(config, today, results):
    from playwright.async_api import async_playwright, TimeoutError as BrowserTimeout
    policy = robots_policy()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        page.set_default_timeout(45000)
        failures = []
        page.on('requestfailed', lambda request: failures.append({
            'url': request.url.split('?')[0], 'error': request.failure}))

        async def visit(url, condition):
            if not public_url(url) or not policy.can_fetch(AGENT, url):
                raise PermissionError("URL or robots policy does not allow collection")
            response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if response and response.status >= 400:
                raise PermissionError(f"HTTP {response.status}; no retry or bypass")
            text = await page.locator("body").inner_text()
            if CHALLENGE.search(text):
                raise PermissionError("Verification/access restriction; collection stopped")
            try:
                await page.wait_for_function(condition, timeout=45000)
            except BrowserTimeout:
                # A blank document is not evidence of bot detection. One ordinary
                # reload is allowed; never loop, change identity, or solve checks.
                if not (await page.locator('body').inner_text()).strip():
                    response = await page.reload(wait_until='domcontentloaded', timeout=60000)
                    if response and response.status >= 400:
                        raise PermissionError(f'HTTP {response.status}; collection stopped')
                    text = await page.locator('body').inner_text()
                    if CHALLENGE.search(text):
                        raise PermissionError('Verification/access restriction; collection stopped')
                    try:
                        await page.wait_for_function(condition, timeout=45000)
                        if CHALLENGE.search(await page.locator('body').inner_text()):
                            raise PermissionError('Verification/access restriction; collection stopped')
                        return await asyncio.sleep(max(1, policy.crawl_delay(AGENT) or 0))
                    except BrowserTimeout:
                        pass
                results['diagnostic'] = {'url': page.url, 'title': await page.title(),
                                         'body_excerpt': (await page.locator('body').inner_text())[:600],
                                         'request_failures': failures[-5:]}
                raise
            text = await page.locator("body").inner_text()
            if CHALLENGE.search(text):
                raise PermissionError("Verification/access restriction; collection stopped")
            await asyncio.sleep(max(1, policy.crawl_delay(AGENT) or 0))

        def links():
            return page.locator("a[href]").evaluate_all("xs => xs.map(a => ({text:a.textContent.trim(),href:a.href}))")

        try:
            await visit(SOURCES["min-repo"], "() => document.querySelector('h1') && Array.from(document.querySelectorAll('a')).some(a => /\\/\\d+\\/$/.test(a.pathname))")
            if (await page.locator("h1").inner_text()).strip() != STORE:
                raise ValueError("Wrong store index")
            day, report = latest_report(await links(), today)
            results["report_date"] = str(day)
            results['report_url'] = report
            await visit(report, "() => Array.from(document.querySelectorAll('a')).some(a => a.search.includes('kishu='))")
            heading = await page.locator("h1").inner_text()
            if STORE not in heading or report_day(heading.replace(STORE, "").strip(), today) != day:
                raise ValueError("Report store/date mismatch")
            model_links = {normalized(link["text"]): link["href"] for link in await links() if "kishu=" in link["href"]}
            for model in layout_on(config, day):
                model_id = model["model_id"]
                url = model_links.get(normalized(ALIASES.get(model_id, model["name"])))
                if not url:
                    results["models"][model_id] = {"status": "unavailable", "reason": "Model link not found"}
                    continue
                try:
                    await visit(url, "() => Array.from(document.querySelectorAll('table')).some(t => {const r=t.querySelector('tr');return r && r.textContent.includes('台番') && r.textContent.includes('BB') && r.textContent.includes('RB');})")
                    title = await page.locator("h1").inner_text()
                    if STORE not in title or report_day(title.replace(STORE, "").strip(), today) != day:
                        raise ValueError("Machine page store/date mismatch")
                    tables = await page.locator("table").evaluate_all("ts => ts.map(t => Array.from(t.querySelectorAll('tr')).map(r => Array.from(r.querySelectorAll('th,td')).map(c => c.textContent.trim())))")
                    rows = parse_tables(tables, model, day, url)
                    results["records"].extend(rows)
                    results["models"][model_id] = {"status": "complete", "rows": len(rows)}
                except PermissionError:
                    raise  # no alternate routes or retries after access restrictions
                except (ValueError, BrowserTimeout) as error:
                    results["models"][model_id] = {"status": "error", "reason": str(error)}
        finally:
            await browser.close()


def run(base=BASE):
    data_path = base / "data.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Refusing to overwrite invalid data.json")
    config = json.loads((base / "machines.json").read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(config["timezone"])).date()
    result = {"attempted_at": now.isoformat(), "records": [], "models": {}}
    try:
        asyncio.run(scrape(config, today, result))
        result["status"] = "complete" if result["models"] and all(m["status"] == "complete" for m in result["models"].values()) else "partial"
    except Exception as error:
        result["status"] = "blocked" if isinstance(error, PermissionError) else "error"
        result["reason"] = str(error)
    incoming = result.pop("records")
    for model_id in {r["model_id"] for r in incoming}:
        rows = [r for r in incoming if r["model_id"] == model_id]
        path = base / "history" / "machines" / rows[0]["date"] / (model_id + ".json")
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        write_json(path, merge_records(old, rows))
    data["machine_records"] = merge_records(data.get("machine_records", []), incoming)
    # The UI payload holds 90 days; older files remain in history, never deleted.
    cutoff = str(today - timedelta(days=90))
    data["machine_records"] = [r for r in data["machine_records"] if r["date"] >= cutoff]
    data["machine_collection"] = result
    data["machine_results_available"] = bool(data["machine_records"])
    data["collection_stage"] = "machine_results" if data["machine_records"] else "source_checks_only"
    write_json(data_path, data)
    print(json.dumps({**result, "new_records": len(incoming)}, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
