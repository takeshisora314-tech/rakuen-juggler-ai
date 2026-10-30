"""Retrospective fixed-balanced ranking groups; never a prospective track record."""
import hashlib
import json
from datetime import date, timedelta
from forecast_engine import make_forecast, record_index, valid_record, VERSION


def summarize(rows):
    if not rows:
        return None
    count = sum(len(r['outcomes']) for r in rows)
    total = sum(sum(x['difference'] for x in r['outcomes']) for r in rows)
    positive = sum(sum(x['difference'] > 0 for x in r['outcomes']) for r in rows)
    return {'days': len(rows), 'count': count, 'positive_count': positive,
            'positive_rate': positive / count, 'total_difference': total,
            'mean_difference': total / count,
            'low_play_count': sum(sum(x['games'] < 3000 for x in r['outcomes']) for r in rows),
            'mean_daily_lift': sum(sum(x['difference'] for x in r['outcomes']) /
                                   len(r['outcomes']) - r['baseline'] for r in rows) / len(rows)}


def build_report(config, records, as_of, days=90):
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError('days must be 1..90')
    end = date.fromisoformat(as_of)
    index = record_index(records)
    groups = {}
    details = []
    for offset in range(days, 0, -1):
        day = str(end - timedelta(days=offset))
        forecast = make_forecast(config, records, day, evaluations=(), created_at=day+'T05:00:00+09:00')
        for model_id, model in forecast['models'].items():
            result = groups.setdefault(model_id, {'primary': [], 'backup': []})
            if model['status'] != 'ready':
                continue
            rankings = model['rankings']['balanced']
            actual = [index.get((day, model_id, r['number'])) for r in rankings]
            # Same complete outcome pool as the original evaluation protocol.
            if any(r is None or not valid_record(r) for r in actual):
                continue
            baseline = sum(r['difference'] for r in actual) / len(actual)
            detail = {'date': day, 'model_id': model_id, 'groups': {}}
            for label, candidates in [('primary', rankings[:3]), ('backup', rankings[3:10])]:
                if not candidates:
                    continue
                outcomes = [index[(day, model_id, r['number'])] for r in candidates]
                result[label].append({'outcomes': outcomes, 'baseline': baseline})
                detail['groups'][label] = [{'number': r['number'], 'difference': r['difference'],
                                            'games': r['games']} for r in outcomes]
            details.append(detail)
    fingerprint = lambda obj: hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'kind': 'retrospective_candidate_groups', 'version': VERSION,
            'strategy': 'balanced', 'as_of': as_of, 'days': days,
            'data_sha256': fingerprint(records), 'config_sha256': fingerprint(config),
            'record_count': len(records),
            'limitations': ['Past stored data; historical publication availability is not reconstructed.',
                            'Backup group contains up to seven eligible machines, possibly fewer.',
                            'Daily final differences are not personal profit or setting accuracy.',
                            'No strategy tuning or prospective archive changes.'],
            'models': {m: {g: summarize(rs) for g, rs in gs.items()} for m, gs in groups.items()},
            'daily': details}


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    report = build_report(json.loads((base/'machines.json').read_text()),
                          json.loads((base/'data.json').read_text())['machine_records'], args.as_of)
    output = Path(args.output).resolve()
    research = (base/'history'/'research').resolve()
    if not output.is_relative_to(research):
        raise ValueError('Output must be in history/research')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report['models'], ensure_ascii=False, indent=2))
