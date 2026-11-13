"""Prospective five-point penalty trial for special days on the 39-machine layout."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from collect_sources import layout_on, write_json
from evaluate_special_days import special_days
from forecast_engine import save_snapshot, snapshot_id, valid_record
from morning_window import in_morning_window
from myj_rank_research import metrics, read
from statistics import mean

VERSION = 'myj6-special-penalty-v1'
PENALTY = 5
NUMBERS = set(range(2201, 2240))


def run(base, config, records, now, snapshot=None):
    local = now.astimezone(ZoneInfo(config['timezone']))
    day = local.date()
    labels = special_days(day)
    root = base / 'history' / 'special-day-trial' / VERSION
    path = root / 'forecasts' / (str(day) + '.json')
    if snapshot and labels and snapshot['date'] == str(day) and in_morning_window(local) and not path.exists():
        model = snapshot['models'].get('myj6', {})
        numbers = next((set(m['numbers']) for m in layout_on(config, day) if m['model_id'] == 'myj6'), set())
        created = model.get('created_at', snapshot.get('created_at'))
        selected = model.get('selection', {}).get('strategy')
        ranked = model.get('rankings', {}).get(selected, [])
        if (created == now.isoformat() and model.get('status') == 'ready' and numbers == NUMBERS and len(ranked) >= 10
                and model.get('latest_source_date') == str(day - timedelta(days=1))):
            rest = [{**r, 'score': round(r['score'] - PENALTY, 2)}
                    if r['latest_difference'] >= 2000 else r for r in ranked[3:]]
            candidate = sorted(rest, key=lambda r: (-r['score'], r['number']))[:7]
            save_snapshot(path, {'version': VERSION, 'date': str(day), 'created_at': local.isoformat(),
                                 'live_snapshot_id': snapshot['snapshot_id'], 'special_days': labels,
                                 'numbers': sorted(numbers), 'baseline': ranked[3:10], 'candidate': candidate})

    actual_by_date = {}
    for row in records:
        if row['model_id'] == 'myj6' and valid_record(row):
            actual_by_date.setdefault(row['date'], {})[row['number']] = row
    results, pending = {}, []
    samples = {'baseline': [], 'candidate': []}
    for file in sorted((root / 'forecasts').glob('*.json')):
        saved = read(file)
        if saved['snapshot_id'] != snapshot_id(saved):
            raise ValueError('Special-day trial snapshot integrity mismatch')
        target = saved['date']
        if target > str(day) or (target == str(day) and (local.hour, local.minute) < (23, 30)):
            pending.append(target)
            continue
        archive = base / 'history' / 'machines' / target / 'myj6.json'
        actual = {r['number']: r for r in read(archive) if valid_record(r)} if archive.exists() else {}
        actual.update(actual_by_date.get(target, {}))
        if not NUMBERS <= actual.keys():
            pending.append(target)
            continue
        average = mean(actual[n]['difference'] for n in NUMBERS)
        result = {'special_days': saved['special_days'], 'all_machine_mean': average}
        for method, rows in samples.items():
            values = [(actual[r['number']]['difference'], average) for r in saved[method]]
            rows.extend(values)
            result[method] = metrics(values)
        results[target] = result
    write_json(root / 'status.json', {'version': VERSION, 'as_of': str(day), 'evaluated_days': len(results),
                                      'pending_days': pending, 'days': results,
                                      'ranks_4_to_10': {method: metrics(rows) for method, rows in samples.items()}})
