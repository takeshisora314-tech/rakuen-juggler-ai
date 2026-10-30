"""Read-only chronological replay and separate verified morning-snapshot results."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from forecast_engine import (VERSION, WEIGHTS, comparison_metrics_valid, evaluate,
                             make_forecast, record_index, snapshot_id)
from collect_sources import write_json


def summarize(evaluations, model_ids, kind, start, end):
    dates = {}
    for entry in evaluations:
        if entry.get('kind') != kind or entry.get('version') != VERSION:
            continue
        day = entry.get('date')
        try:
            if date.fromisoformat(day).isoformat() != day or not start <= day < end:
                continue
        except (ValueError, TypeError):
            continue
        dates.setdefault(day, []).append(entry)
    unique = [entries[0] for _, entries in sorted(dates.items()) if len(entries) == 1]
    result = {'kind': kind, 'ambiguous_dates_excluded': sum(len(v) != 1 for v in dates.values()),
              'models': {}}
    for model_id in model_ids:
        statuses = Counter()
        paired = []
        for entry in unique:
            model = entry.get('models', {}).get(model_id)
            if model is None:
                statuses['inactive'] += 1
                continue
            status = model.get('status', 'invalid')
            strategies = model.get('strategies', {})
            valid = (status == 'complete' and isinstance(strategies, dict)
                     and all(comparison_metrics_valid(strategies.get(s)) for s in WEIGHTS))
            statuses[status if status != 'complete' or valid else 'invalid_metrics'] += 1
            if valid:
                paired.append((entry['date'], strategies))
        summary = {'status_counts': dict(statuses), 'paired_days': len(paired),
                   'first_date': paired[0][0] if paired else None,
                   'last_date': paired[-1][0] if paired else None,
                   'strategies': {}}
        for strategy in WEIGHTS:
            if not paired:
                continue  # Absence of evidence is not a zero-percent result.
            metrics = [strategies[strategy] for _, strategies in paired]
            count = sum(m['count'] for m in metrics)
            positive = sum(m['positive_count'] for m in metrics)
            summary['strategies'][strategy] = {
                'count': count, 'positive_count': positive, 'positive_rate': positive / count,
                'mean_difference': round(mean(m['mean_difference'] for m in metrics), 2),
                'lift_vs_eligible_mean': round(mean(m['lift_vs_eligible_mean'] for m in metrics), 2),
                'low_play_count': sum(m['low_play_count'] for m in metrics)}
        result['models'][model_id] = summary
    return result


def build_report(config, records, as_of, days=90, snapshots=()):
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError('Window must be 1 to 90 calendar days')
    end = date.fromisoformat(as_of)
    start = end - timedelta(days=days)
    record_index(records)
    replay = []
    for offset in range(days):
        day = str(start + timedelta(days=offset))
        # make_forecast restricts training to dates strictly before this target.
        forecast = make_forecast(config, records, day, (), day + 'T05:00:00+09:00')
        forecast['kind'] = 'retrospective'
        replay.append(evaluate(forecast, records))
    prospective = []
    for snapshot in snapshots:
        if (snapshot.get('kind') != 'prospective' or snapshot.get('version') != VERSION
                or snapshot.get('snapshot_id') != snapshot_id(snapshot)):
            raise ValueError('Unverified morning forecast snapshot')
        created = datetime.fromisoformat(snapshot['created_at'])
        if created.tzinfo is None:
            raise ValueError('Morning snapshot must have timezone')
        local = created.astimezone(ZoneInfo(config['timezone']))
        # Legacy snapshots may predate the current 05:00 start. Require the
        # same business date and the 07:00 deadline without rewriting history.
        if str(local.date()) != snapshot['date'] or local.hour >= 7:
            raise ValueError('Snapshot was not created before its morning deadline')
        if str(start) <= snapshot['date'] < as_of:
            prospective.append(evaluate(snapshot, records))
    model_ids = [m['id'] for m in config['models']]
    digest = hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    config_digest = hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'schema_version': 1, 'policy_version': VERSION, 'as_of_date': as_of,
            'window_start': str(start), 'window_end_exclusive': as_of, 'calendar_days': days,
            'input_records_sha256': digest, 'config_sha256': config_digest, 'record_count': len(records),
            'prospective': summarize(prospective, model_ids, 'prospective', str(start), as_of),
            'retrospective': summarize(replay, model_ids, 'retrospective', str(start), as_of),
            'note': 'Retrospective results are not pre-published predictions and never select a strategy. Positive difference is not proof of setting 4-6. Repeated machines and days are not independent trials.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=Path(__file__).parent)
    parser.add_argument('--data', type=Path)
    parser.add_argument('--as-of', required=True, help='Exclusive end date in Japan, YYYY-MM-DD')
    parser.add_argument('--days', type=int, default=90)
    parser.add_argument('--output', type=Path, help='Explicit report destination; inputs remain unchanged')
    args = parser.parse_args()
    data_path = args.data or args.base / 'data.json'
    if args.output:
        output = args.output.resolve()
        protected = [args.base / 'machines.json', data_path]
        archives = [args.base / 'history/forecasts', args.base / 'history/evaluations']
        if (output in [p.resolve() for p in protected]
                or any(p.resolve() == output or p.resolve() in output.parents for p in archives)):
            parser.error('Report output must not overwrite source data or forecast/evaluation archives')
    config = json.loads((args.base / 'machines.json').read_text())
    data = json.loads(data_path.read_text())
    snapshots = [json.loads(p.read_text()) for p in sorted((args.base / 'history/forecasts').glob('*.json'))]
    report = build_report(config, data.get('machine_records', []), args.as_of, args.days, snapshots)
    if args.output:
        write_json(args.output, report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
