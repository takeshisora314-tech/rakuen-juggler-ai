"""Paired retrospective comparison. Never selects a live strategy or edits forecasts."""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from statistics import mean
from forecast_engine import make_forecast, record_index, valid_record, VERSION, WEIGHTS
from evaluate_candidates import summarize


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def summarize_period(rows):
    result = {}
    for strategy in WEIGHTS:
        groups = {}
        for group in ('primary', 'backup'):
            usable = [r for r in rows if r['outcomes'][strategy][group]]
            metrics = summarize([{'outcomes': r['outcomes'][strategy][group],
                                  'baseline': r['baseline']} for r in usable])
            if metrics is not None:
                deltas = [mean(x['difference'] for x in r['outcomes'][strategy][group]) -
                          mean(x['difference'] for x in r['outcomes']['balanced'][group]) for r in usable]
                metrics['paired_mean_gain_vs_balanced'] = mean(deltas)
                metrics['days_better_than_balanced'] = sum(d > 0 for d in deltas)
                metrics['days_tied_with_balanced'] = sum(d == 0 for d in deltas)
            groups[group] = metrics
        result[strategy] = groups
    return result


def build_report(config, records, as_of, days=90):
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError('days must be 1..90')
    end = date.fromisoformat(as_of)
    index = record_index(records)
    split = str(end - timedelta(days=30))
    models = {}
    for offset in range(days, 0, -1):
        day = str(end - timedelta(days=offset))
        forecast = make_forecast(config, records, day, (), day+'T05:00:00+09:00')
        for model_id, model in forecast['models'].items():
            info = models.setdefault(model_id, {'daily': [], 'excluded': {}})
            reason = model['status']
            if reason != 'ready':
                info['excluded'][reason] = info['excluded'].get(reason, 0) + 1
                continue
            numbers = model['eligible_numbers']
            actual = {n: index.get((day, model_id, n)) for n in numbers}
            if any(r is None or not valid_record(r) for r in actual.values()):
                info['excluded']['incomplete_outcomes'] = info['excluded'].get('incomplete_outcomes', 0) + 1
                continue
            row = {'date': day, 'baseline': mean(r['difference'] for r in actual.values()), 'outcomes': {}}
            for strategy in WEIGHTS:
                ranked = model['rankings'][strategy]
                row['outcomes'][strategy] = {
                    group: [{k: actual[r['number']][k] for k in ('number','games','difference')}
                            for r in candidates]
                    for group, candidates in (('primary', ranked[:3]), ('backup', ranked[3:10]))}
            info['daily'].append(row)
    for info in models.values():
        rows = info['daily']
        info['evaluated_dates'] = [r['date'] for r in rows]
        info['periods'] = {'all': summarize_period(rows),
                           'earlier': summarize_period([r for r in rows if r['date'] < split]),
                           'recent_30': summarize_period([r for r in rows if r['date'] >= split])}
    return {'kind': 'retrospective_paired_strategies', 'version': VERSION,
            'as_of': as_of, 'days': days, 'recent_period_from': split,
            'record_count': len(records), 'data_sha256': fingerprint(records),
            'config_sha256': fingerprint(config), 'changes_live_strategy': False,
            'limitations': ['All strategies use identical eligible machines and complete outcome dates.',
                            'Daily rankings use only earlier dates; historical publication time is unknown.',
                            'Recent 30 days are a chronological diagnostic, not an untouched holdout.',
                            'Past replay cannot satisfy the 30 prospective day switching requirement.',
                            'Final machine difference is not personal profit or setting accuracy.'],
            'models': models}


def audit_missing(config, records, as_of):
    from collect_machines import history_coverage
    from collect_sources import layout_on
    index = record_index(records)
    coverage = history_coverage(config, records, date.fromisoformat(as_of))
    missing = []
    for day in coverage['days']:
        for model in layout_on(config, day['date']):
            for number in model['numbers']:
                row = index.get((day['date'],model['model_id'],number))
                if row is not None and valid_record(row):
                    continue
                missing.append({'date':day['date'], 'model_id':model['model_id'], 'number':number,
                                'reason':'missing_record' if row is None else 'invalid_or_missing_measurement',
                                'missing_fields': [k for k in ('games','bb','rb','difference')
                                                   if row is None or type(row.get(k)) is not int]})
    return {'as_of':as_of, 'coverage':coverage, 'missing':missing,
            'data_sha256':fingerprint(records),
            'note':'Missing publication does not establish zero play, closure, or a changed installation.'}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', required=True)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    config = json.loads((base/'machines.json').read_text())
    records = json.loads((base/'data.json').read_text())['machine_records']
    root = base/'history'/'research'
    root.mkdir(parents=True, exist_ok=True)
    for name, value in [('strategy-comparison',build_report(config,records,args.as_of)),
                        ('missing-audit',audit_missing(config,records,args.as_of))]:
        if name == 'strategy-comparison':
            for model in value['models'].values():
                del model['daily']
        (root/(name+'-'+args.as_of+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print('Saved paired comparison and missing-data audit; live forecasts unchanged.')
