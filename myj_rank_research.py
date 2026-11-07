"""Independent My Juggler research. The public forecast never reads these files."""
import argparse
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

from collect_sources import BASE, layout_on, write_json
from forecast_engine import (
    POLICY, WEIGHTS, make_forecast, record_index, save_snapshot, snapshot_id, valid_record,
)

MODELS = ('myj5', 'myj6')
METHODS = ('baseline', 'penalty', 'low_play')
VERSION = 'myj-rank-v1'
PENALTY_POINTS = 10
LOW_PLAY_MAX_GAMES = 1000


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def rankings(snapshot, config, records):
    """Hold the public top three fixed and test two independent changes below them."""
    day = date.fromisoformat(snapshot['date'])
    previous = str(day - timedelta(days=1))
    cutoff = str(day - timedelta(days=14))
    result = {}
    for installed in layout_on(config, day):
        model = installed['model_id']
        if model not in MODELS:
            continue
        published = snapshot['models'].get(model, {})
        strategy = published.get('selection', {}).get('strategy')
        baseline = published.get('rankings', {}).get(strategy, [])
        if len(baseline) < 3 or published.get('latest_source_date') != previous:
            continue
        numbers = set(installed['numbers'])
        history = [r for r in records if r['model_id'] == model and r['number'] in numbers
                   and cutoff <= r['date'] < str(day)]
        days = sorted({r['date'] for r in history}, reverse=True)[:7]
        usable = [r for r in history if r['date'] in days and valid_record(r)]
        by_number = defaultdict(list)
        for row in sorted(usable, key=lambda r: r['date'], reverse=True):
            by_number[row['number']].append(row)
        if any(not by_number[n] or by_number[n][0]['date'] != previous for n in numbers):
            continue

        fixed = baseline[:3]
        rest = baseline[3:]
        penalty = [
            {**row, 'score': round(row['score'] - PENALTY_POINTS, 2)}
            if by_number[row['number']][0]['difference'] >= 2000 else row for row in rest
        ]
        pool_rate = sum(r['rb'] for r in usable) / sum(r['games'] for r in usable)
        extras = []
        for number in sorted(numbers - {r['number'] for r in baseline}):
            latest, *older = by_number[number]
            if not 0 < latest['games'] <= LOW_PLAY_MAX_GAMES or latest['difference'] >= 0:
                continue
            trusted = [r for r in older if r['games'] >= POLICY['min_daily_games']]
            games = sum(r['games'] for r in trusted)
            if len(trusted) < POLICY['min_history_days'] or games < POLICY['min_total_games']:
                continue
            dip = min(1, max(0, -sum(r['difference'] for r in trusted[:3]) / 4000))
            rate = (sum(r['rb'] for r in trusted) + 5000 * pool_rate) / (games + 5000)
            rb = min(1, max(0, 0.5 + 2 * (rate / pool_rate - 1))) if pool_rate else 0
            support = min(1, games / 30000)
            score = round(100 * sum(w * value for w, value in zip(WEIGHTS[strategy], (dip, rb, support))), 2)
            extras.append({'number': number, 'score': score})

        def ordered(rows):
            return sorted(rows, key=lambda r: (-r['score'], r['number']))

        result[model] = {
            'numbers': installed['numbers'],
            'baseline': baseline[:10],
            'penalty': (fixed + ordered(penalty))[:10],
            'low_play': (fixed + ordered(rest + extras))[:10],
            'extra_numbers': [r['number'] for r in extras],
        }
    return result


def metrics(rows):
    return {'count': len(rows),
            'positive_rate': mean(difference > 0 for difference, _ in rows) if rows else None,
            'mean_difference': mean(difference for difference, _ in rows) if rows else None,
            'lift_vs_all': mean(difference - average for difference, average in rows) if rows else None}


def summarize(snapshots, index, config, now):
    snapshots = tuple(snapshots)
    results = {}
    for model in MODELS:
        by_rank = {method: defaultdict(list) for method in METHODS}
        bands = {method: [] for method in METHODS}
        missing_days = []
        paired_days = []
        additional = []
        extra_count = 0
        settled_days = 0
        for snapshot in snapshots:
            day = snapshot['date']
            if day > str(now.date()) or (day == str(now.date()) and (now.hour, now.minute) < (23, 30)):
                continue
            saved = snapshot['models'].get(model)
            if not saved:
                continue
            numbers = saved.get('numbers')
            if numbers is None:
                numbers = next(m['numbers'] for m in layout_on(config, day) if m['model_id'] == model)
            actual = {n: index.get((day, model, n), {}) for n in numbers}
            if not all(valid_record(row) for row in actual.values()):
                missing_days.append(day)
                continue
            settled_days += 1
            average = mean(row['difference'] for row in actual.values())
            for method in METHODS:
                for rank, row in enumerate(saved.get(method, []), 1):
                    by_rank[method][rank].append((actual[row['number']]['difference'], average))
            if all(len(saved.get(method, [])) >= 10 for method in METHODS):
                paired_days.append(day)
                for method in METHODS:
                    bands[method].extend((actual[r['number']]['difference'], average)
                                         for r in saved[method][3:10])
            extras = set(saved.get('extra_numbers', []))
            extra_count += len(extras)
            additional.extend((actual[r['number']]['difference'], average)
                              for r in saved.get('low_play', [])[3:10] if r['number'] in extras)
        results[model] = {
            'settled_days': settled_days, 'missing_result_days': missing_days,
            'by_rank': {m: {r: metrics(by_rank[m][r]) for r in range(1, 11)} for m in METHODS},
            'paired_4_to_10_days': paired_days,
            'paired_4_to_10': {m: metrics(bands[m]) for m in METHODS},
            'low_play_eligible_additions': extra_count,
            'low_play_added_in_top10': metrics(additional),
        }
    return results


def archived_baselines(base):
    for path in sorted((base / 'history' / 'forecasts').glob('*.json')):
        snapshot = read(path)
        if snapshot.get('kind') != 'prospective' or snapshot_id(snapshot) != snapshot.get('snapshot_id'):
            continue
        models = {}
        for model in MODELS:
            forecast = snapshot['models'].get(model, {})
            selected = forecast.get('selection', {}).get('strategy')
            rows = (forecast.get('rankings', {}).get(selected)
                    or forecast.get('strategies', {}).get(selected, []))
            if rows:
                models[model] = {'baseline': rows[:10]}
        yield {'date': snapshot['date'], 'models': models}


def archived_records(base):
    for path in sorted((base / 'history' / 'machines').glob('*/*.json')):
        if path.stem in MODELS:
            yield from read(path)


def run(base, config, records, now, new_snapshot=None):
    local = now.astimezone(ZoneInfo(config['timezone']))
    root = base / 'history' / 'myj-rank-research' / VERSION
    if new_snapshot is not None:
        variants = rankings(new_snapshot, config, records)
        path = root / 'forecasts' / (new_snapshot['date'] + '.json')
        if variants and not path.exists():
            save_snapshot(path, {
                'date': new_snapshot['date'], 'created_at': new_snapshot['created_at'],
                'version': VERSION, 'live_snapshot_id': new_snapshot['snapshot_id'], 'models': variants,
            })
    frozen = []
    for path in sorted((root / 'forecasts').glob('*.json')):
        snapshot = read(path)
        if snapshot_id(snapshot) != snapshot.get('snapshot_id'):
            raise ValueError('Research forecast integrity mismatch')
        frozen.append(snapshot)
    index = record_index(archived_records(base))
    index.update(record_index(r for r in records if r['model_id'] in MODELS))
    status = {'version': VERSION, 'as_of': str(local.date()),
              'archived_baseline': summarize(archived_baselines(base), index, config, local),
              'prospective_variants': summarize(frozen, index, config, local)}
    write_json(root / 'status.json', status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', required=True, type=date.fromisoformat, help='JST date; evaluate prior days')
    args = parser.parse_args()
    config = read(BASE / 'machines.json')
    config['models'] = [model for model in config['models'] if model['id'] in MODELS]
    records = list(archived_records(BASE))
    now = datetime.combine(args.as_of, datetime.min.time(), ZoneInfo(config['timezone']))
    index = record_index(records)
    dates = sorted({r['date'] for r in records if r['date'] < str(args.as_of)})
    replay = [{'date': day, 'models': rankings(make_forecast(config, records, day), config, records)}
              for day in dates]
    print(json.dumps({'version': VERSION, 'as_of': str(args.as_of),
                      'archived_baseline': summarize(archived_baselines(BASE), index, config, now),
                      'retrospective': summarize(replay, index, config, now)}, indent=2))


if __name__ == '__main__':
    main()
