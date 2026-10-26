"""Collect source availability, not machine results or predictions.

Machine identity is (date, model_id, number), never number alone.
Existing data is preserved; each availability check also gets its own snapshot.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE = Path(__file__).resolve().parent
SOURCES = {
    "min-repo": "https://min-repo.com/tag/%E6%A5%BD%E5%9C%92%E4%B8%8A%E6%96%B0%E5%B1%8B%E5%BA%97/",
    "ana-slo": "https://ana-slo.com/%E3%83%9B%E3%83%BC%E3%83%AB%E3%83%87%E3%83%BC%E3%82%BF/%E9%9D%99%E5%B2%A1%E7%9C%8C/%E6%A5%BD%E5%9C%92%E4%B8%8A%E6%96%B0%E5%B1%8B%E5%BA%97-%E3%83%87%E3%83%BC%E3%82%BF%E4%B8%80%E8%A6%A7/",
    "d-delta": "https://www.d-deltanet.com/pc/D0101.do?pmc=22021009",
}


def layout_on(config, day):
    """Return installations on an ISO date; until is exclusive."""
    day = date.fromisoformat(str(day)).isoformat()
    active, seen = [], set()
    for model in config["models"]:
        for period in model["installations"]:
            if period["from"] and day < period["from"]:
                continue
            if period["until"] and day >= period["until"]:
                continue
            numbers = period["numbers"]
            if len(numbers) != len(set(numbers)) or seen.intersection(numbers):
                raise ValueError("Duplicate machine number in active layout")
            seen.update(numbers)
            active.append({
                "model_id": model["id"], "name": model["name"],
                "numbers": list(numbers), "valid_from": period["from"],
                "valid_until": period["until"],
            })
    return active


def model_for_number(config, day, number):
    """Resolve historical records using their date, not today's layout."""
    return next((m["model_id"] for m in layout_on(config, day)
                 if number in m["numbers"]), None)


def check_sources(checked_at):
    statuses = {}
    for name, url in SOURCES.items():
        try:
            response = requests.get(url, timeout=25,
                                    headers={"User-Agent": "Mozilla/5.0"})
            statuses[name] = {"ok": response.ok, "status": response.status_code,
                              "checked_at": checked_at}
        except requests.RequestException as exc:
            statuses[name] = {"ok": False, "error": str(exc),
                              "checked_at": checked_at}
    return statuses


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def collect(data_path=BASE / "data.json", config_path=BASE / "machines.json",
            history_root=BASE / "history" / "source-checks", now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("An aware datetime is required")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    day = now.astimezone(ZoneInfo(config["timezone"])).date().isoformat()
    out = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else {}
    if not isinstance(out, dict):
        raise ValueError("data.json must be an object; refusing to overwrite it")
    checked_at = now.astimezone(timezone.utc).isoformat()
    layout = {"date": day, "timezone": config["timezone"],
              "models": layout_on(config, day)}
    sources = check_sources(checked_at)
    snapshot = {"updated_at": checked_at, "sources": sources, "layout": layout,
                "collection_stage": "machine_results" if out.get("machine_records") else "source_checks_only",
                "machine_results_available": bool(out.get("machine_records"))}
    stamp = now.astimezone(timezone.utc).strftime("%H%M%S-%fZ")
    snapshot_path = history_root / day / (stamp + ".json")
    if snapshot_path.exists():
        raise FileExistsError("Refusing to replace an existing snapshot")
    write_json(snapshot_path, snapshot)
    out.update(snapshot)
    write_json(data_path, out)
    print(f"Saved source checks: {snapshot_path.relative_to(history_root)}; "
          f"layout date: {day}. Availability check only; see machine_collection for results.")
    return out


if __name__ == "__main__":
    collect()
