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


def available_reports(links, today):
    reports = []
    for link in links:
        day = report_day(link["text"], today)
        url = urljoin(ORIGIN, link["href"])
        if day and public_url(url) and re.fullmatch(r"/\d+/", urlparse(url).path) and not urlparse(url).query:
            reports.append((day, url))
    if not reports:
        raise ValueError("No completed daily report found")
    return sorted(set(reports), reverse=True)


def latest_report(links, today):
    return available_reports(links, today)[0]


def history_reports(links, today):
    return [(day,url) for day,url in available_reports(links,today)
            if day >= today-timedelta(days=90)][:90]


def ordered_backfill(reports, checkpoint, today):
    # Never-attempted dates first; failed/partial dates cannot starve older days.
    # Dates are still newest-first inside each group.
    return sorted(reports,key=lambda item:(str(item[0]) in checkpoint,-item[0].toordinal()))


def backfill_due(checkpoint, day, today):
    previous=checkpoint.get(str(day),{})
    return previous.get('attempted_on') != str(today)


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


def parse_tables(tables, model, day, source_url, allow_partial=False):
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
    if not rows or (not allow_partial and seen != set(model["numbers"])):
        raise ValueError("Missing machines; refusing to save an incomplete table")
    return sorted(rows, key=lambda row: row["number"])


def collection_result(rows, model):
    missing = sorted(set(model['numbers']) - {row['number'] for row in rows})
    incomplete = sorted({r['number'] for r in rows if not valid_measurement(r)})
    result = {'status': 'partial' if missing or incomplete else 'complete', 'rows': len(rows),
              'expected_rows': len(model['numbers']), 'missing_numbers': missing}
    if incomplete:
        result['incomplete_numeric_numbers'] = incomplete
    return result


def valid_measurement(row):
    return (all(type(row.get(k)) is int for k in ('number','games','bb','rb','difference'))
            and min(row['games'],row['bb'],row['rb']) >= 0
            and row['bb']+row['rb'] <= row['games'])


def history_coverage(config, records, today, window=90):
    """Count numeric completeness against dated layouts, not inferred source uptime."""
    index = {}
    for row in records:
        key=(row.get('date'),row.get('model_id'),row.get('number'))
        index.setdefault(key,[]).append(row)
    days=[]
    for offset in range(1,window+1):
        day=str(today-timedelta(days=offset))
        expected=verified=0
        incomplete=[]
        for model in layout_on(config,day):
            expected+=len(model['numbers'])
            valid=0
            for number in model['numbers']:
                rows=index.get((day,model['model_id'],number),[])
                valid+=int(len(rows)==1 and valid_measurement(rows[0]))
            verified+=valid
            if valid != len(model['numbers']): incomplete.append(model['model_id'])
        status='complete' if expected and verified==expected else 'partial' if verified else 'missing'
        days.append({'date':day,'status':status,'expected_rows':expected,
                     'verified_rows':verified,'incomplete_models':incomplete})
    return {'as_of_date':str(today),'window_days':window,
            **{status+'_days':sum(d['status']==status for d in days) for status in ('complete','partial','missing')},
            'days':days,'note':'Numeric completeness against configured layouts only; missing does not imply closure or no source report.'}


def backfill_models(config, day, existing):
    """Only complete, numeric cached model-days may skip collection."""
    needed = []
    for model in layout_on(config, day):
        cached = [r for r in existing if r['date'] == str(day)
                  and r['model_id'] == model['model_id']]
        valid = {r['number'] for r in cached if valid_measurement(r)}
        if valid != set(model['numbers']) or len(cached) != len(model['numbers']):
            needed.append(model)
    return needed


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


async def follow_public_link(page, url):
    """Click a visible, already-rendered link; never fabricate referrers."""
    anchors = page.locator('a[href]:visible')
    hrefs = await anchors.evaluate_all('xs => xs.map(a => a.href)')
    if url not in hrefs:
        raise ValueError('Expected public navigation link is not visible')
    async with page.expect_navigation(wait_until='domcontentloaded', timeout=60000) as navigation:
        await anchors.nth(hrefs.index(url)).click()
    return await navigation.value


async def collect_history_models(models, reader, records, outcome, persist=None):
    """Isolate a model's parse/layout error; access blocks/timeouts still escape."""
    for model in models:
        model_id = model['model_id']
        try:
            rows = await reader(model)
            if rows is None:
                item = {'status': 'unavailable', 'reason': 'Model link not found'}
            else:
                records.extend(rows)
                item = collection_result(rows, model)
        except ValueError as error:
            item = {'status': 'error', 'reason': str(error)}
        outcome['models'][model_id] = item
        if item['status'] != 'complete':
            outcome['status'] = 'partial'
        if persist:
            persist()


async def scrape(config, today, results, existing=(), persist=None):
    from playwright.async_api import async_playwright, TimeoutError as BrowserTimeout
    policy = robots_policy()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        page.set_default_timeout(45000)
        failures = []
        errors, site_responses = [], []
        console_errors = []
        page.on('console', lambda message: console_errors.append(message.text[:500])
                if message.type == 'error' else None)
        page.on('pageerror', lambda error: errors.append(str(error)[:400]))
        page.on('response', lambda response: site_responses.append({
            'url': response.url.split('?')[0], 'status': response.status})
            if urlparse(response.url).netloc == 'min-repo.com'
            and response.request.resource_type in ('document', 'xhr', 'fetch') else None)
        page.on('requestfailed', lambda request: failures.append({
            'url': request.url.split('?')[0], 'error': request.failure}))

        async def visit(url, condition, from_link=False):
            if not public_url(url) or not policy.can_fetch(AGENT, url):
                raise PermissionError("URL or robots policy does not allow collection")
            response = (await follow_public_link(page, url) if from_link else
                        await page.goto(url, wait_until="domcontentloaded", timeout=60000))
            if not public_url(page.url):
                raise PermissionError('Navigation left the approved source; stopped')
            if response and response.status >= 400:
                raise PermissionError(f"HTTP {response.status}; no retry or bypass")
            raw_document = await response.text() if response else ''
            document_info = {'bytes': len(raw_document.encode()),
                             'script_count': raw_document.lower().count('<script'),
                             'ajax_bootstrap': 'w_scd_n' in raw_document,
                             'content_type': response.headers.get('content-type') if response else None}
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
                                         'request_failures': failures[-5:],
                                         'javascript_errors': errors[-5:],
                                         'console_errors': console_errors[-5:],
                                         'document': document_info,
                                         'site_responses': site_responses[-10:]}
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
            reports = history_reports(await links(), today)
            if not reports:
                raise ValueError('No report within the last ninety calendar days')
            results['history_window']={'days':90,'discovered_report_days':len(reports),
                'earliest_discovered':str(reports[-1][0]),'latest_discovered':str(reports[0][0]),
                'note':'Discovered reports are not proof of complete machine results'}
            day, report = reports[0]
            results["report_date"] = str(day)
            results['report_url'] = report
            report_ready = "() => Array.from(document.querySelectorAll('a')).some(a => a.search.includes('kishu='))"
            await visit(report, report_ready, from_link=True)
            heading = await page.locator("h1").inner_text()
            if STORE not in heading or report_day(heading.replace(STORE, "").strip(), today) != day:
                raise ValueError("Report store/date mismatch")
            model_links = {normalized(link["text"]): link["href"] for link in await links() if "kishu=" in link["href"]}
            for model in ([] if results.get('backfill_only') else layout_on(config, day)):
                model_id = model["model_id"]
                url = model_links.get(normalized(ALIASES.get(model_id, model["name"])))
                if not url:
                    results["models"][model_id] = {"status": "unavailable", "reason": "Model link not found"}
                    continue
                try:
                    if page.url != report:
                        await visit(report, report_ready, from_link=True)
                    await visit(url, "() => Array.from(document.querySelectorAll('table')).some(t => {const r=t.querySelector('tr');return r && r.textContent.includes('台番') && r.textContent.includes('BB') && r.textContent.includes('RB');})", from_link=True)
                    title = await page.locator("h1").inner_text()
                    if STORE not in title or report_day(title.replace(STORE, "").strip(), today) != day:
                        raise ValueError("Machine page store/date mismatch")
                    tables = await page.locator("table").evaluate_all("ts => ts.map(t => Array.from(t.querySelectorAll('tr')).map(r => Array.from(r.querySelectorAll('th,td')).map(c => c.textContent.trim())))")
                    rows = parse_tables(tables, model, day, url, allow_partial=True)
                    results["records"].extend(rows)
                    results["models"][model_id] = collection_result(rows, model)
                    if persist:
                        persist()
                except PermissionError:
                    raise  # no alternate routes or retries after access restrictions
                except (ValueError, BrowserTimeout) as error:
                    results["models"][model_id] = {"status": "error", "reason": str(error)}
            # At most two older report-days per run, all missing models together.
            # Follow only public rendered links and preserve every cached fact.
            results['backfill'] = {}
            checkpoint=results.setdefault('checkpoint',{})
            attempted_days = 0
            for past_day, past_report in ordered_backfill(reports[1:],checkpoint,today):
                needed = backfill_models(config, past_day, existing)
                if not needed:
                    results['backfill'][str(past_day)] = {'status': 'cached'}
                    continue
                if not backfill_due(checkpoint,past_day,today):
                    results['backfill'][str(past_day)] = {'status':'cooldown'}
                    continue
                if attempted_days >= 2:
                    results['backfill'][str(past_day)] = {'status': 'deferred'}
                    continue
                attempted_days += 1
                checkpoint[str(past_day)]={'status':'attempting','attempted_on':str(today)}
                try:
                    await visit(SOURCES['min-repo'], "() => document.querySelector('h1') && Array.from(document.querySelectorAll('a')).some(a => /\\/\\d+\\/$/.test(a.pathname))")
                    await visit(past_report, report_ready, from_link=True)
                    heading = await page.locator('h1').inner_text()
                    if STORE not in heading or report_day(heading.replace(STORE, '').strip(), today) != past_day:
                        raise ValueError('Backfill store/date mismatch')
                    model_links = {normalized(link['text']): link['href'] for link in await links()}
                    outcome = {'status': 'complete', 'models': {}}
                    results['backfill'][str(past_day)] = outcome
                    async def read_historical_model(model):
                        model_id = model['model_id']
                        url = model_links.get(normalized(ALIASES.get(model_id, model['name'])))
                        if not url:
                            return None
                        if page.url != past_report:
                            await visit(past_report, report_ready, from_link=True)
                        await visit(url, "() => Array.from(document.querySelectorAll('table')).some(t => {const r=t.querySelector('tr');return r && r.textContent.includes('台番') && r.textContent.includes('BB') && r.textContent.includes('RB');})", from_link=True)
                        heading = await page.locator('h1').inner_text()
                        if STORE not in heading or report_day(heading.replace(STORE, '').strip(), today) != past_day:
                            raise ValueError('Historical machine page store/date mismatch')
                        tables = await page.locator('table').evaluate_all("ts => ts.map(t => Array.from(t.querySelectorAll('tr')).map(r => Array.from(r.querySelectorAll('th,td')).map(c => c.textContent.trim())))")
                        return parse_tables(tables, model, past_day, url, allow_partial=True)
                    await collect_history_models(needed,read_historical_model,results['records'],outcome,persist)
                    checkpoint[str(past_day)]={'status':outcome['status'],'attempted_on':str(today)}
                    if persist:
                        persist()
                except PermissionError:
                    raise
                except (ValueError, BrowserTimeout) as error:
                    results['backfill'][str(past_day)] = {'status': 'error', 'reason': str(error)}
                    checkpoint[str(past_day)]={'status':'error','attempted_on':str(today),'reason':str(error)}
                    # Ordinary parse/time-out failure is not an access block.
                    # Continue only within the two-day budget; PermissionError stops above.
        finally:
            await browser.close()


def save_collection_progress(base, result, today, incoming):
    """Atomically persist verified model rows; never serialize the live buffer."""
    data_path = base/'data.json'
    data = json.loads(data_path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Refusing to overwrite invalid data.json')
    for day, model_id in {(r['date'], r['model_id']) for r in incoming}:
        rows = [r for r in incoming if r['model_id'] == model_id and r['date'] == day]
        path = base/'history'/'machines'/day/(model_id+'.json')
        old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        write_json(path, merge_records(old, rows))
    data['machine_records'] = merge_records(data.get('machine_records', []), incoming)
    cutoff = str(today-timedelta(days=90))
    data['machine_records'] = [r for r in data['machine_records'] if r['date'] >= cutoff]
    data['backfill_checkpoint'] = result.get('checkpoint', {})
    state = {'status':'in_progress', **{k:v for k,v in result.items() if k not in ('records','checkpoint')}}
    data['history_backfill' if result.get('backfill_only') else 'machine_collection'] = state
    data['machine_results_available'] = bool(data['machine_records'])
    data['collection_stage'] = 'machine_results' if data['machine_records'] else 'source_checks_only'
    config=json.loads((base/'machines.json').read_text(encoding='utf-8'))
    data['history_coverage']=history_coverage(config,data['machine_records'],today)
    write_json(data_path, data)


def run(base=BASE, backfill_only=False):
    data_path = base / "data.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Refusing to overwrite invalid data.json")
    config = json.loads((base / "machines.json").read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo(config["timezone"]))
    today = local.date()
    result = {"attempted_at": now.isoformat(), "records": [], "models": {},
              'backfill_only':backfill_only,
              'checkpoint':dict(data.get('backfill_checkpoint',{}))}
    saved_count = 0
    def persist():
        nonlocal saved_count
        result['progress_saves'] = result.get('progress_saves',0)+1
        result['progress_record_count'] = len(result['records'])
        save_collection_progress(base,result,today,result['records'][saved_count:])
        saved_count = len(result['records'])
    try:
        # After 23:00 JST, an already published same-day report is completed play.
        report_cutoff = today + timedelta(days=1) if local.hour >= 23 else today
        asyncio.run(scrape(config, report_cutoff, result, data.get('machine_records', []),persist))
        statuses=list(result.get('backfill',{}).values()) if backfill_only else list(result['models'].values())
        result['status']='complete' if statuses and all(m['status'] in ('complete','cached') for m in statuses) else 'partial'
    except Exception as error:
        result["status"] = "blocked" if isinstance(error, PermissionError) else "error"
        result["reason"] = str(error)
    persist()
    incoming = result.pop('records')
    result.pop('checkpoint',None)
    print(json.dumps({**result, "new_records": len(incoming)}, ensure_ascii=False))
    return result


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--backfill-only',action='store_true')
    run(backfill_only=parser.parse_args().backfill_only)

