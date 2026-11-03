from morning_window import morning_deadline, before_morning_deadline, in_morning_window
"""Freeze research count mixtures before opening and score observed counts later."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from collect_sources import layout_on, write_json
from evaluate_count_models import FIXED, ASSUMED_CONTRACT, fit_weights
from forecast_engine import record_index, morning_input_readiness
from setting_model import score_count_prediction

VERSION = 'research-count-forward-v1'


def identity(snapshot):
    content = {k:v for k,v in snapshot.items() if k != 'snapshot_id'}
    return hashlib.sha256(json.dumps(content,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def freeze(base, config, records, now):
    if now.tzinfo is None:
        raise ValueError('Timezone-aware timestamp required')
    local = now.astimezone(ZoneInfo(config['timezone']))
    day = str(local.date())
    path = base/'history/count-predictions'/(day+'.json')
    if path.exists():
        saved = json.loads(path.read_text())
        if identity(saved) != saved.get('snapshot_id'):
            raise ValueError('Research snapshot integrity mismatch')
        return saved
    if not in_morning_window(local):
        return None
    if not morning_input_readiness(config,records,day)['ready']:
        return None
    record_index(records)
    models = {}
    for model in layout_on(config,day):
        fitted = fit_weights(records,config,model['model_id'],day)
        models[model['model_id']] = {'status':'ready' if fitted else 'insufficient_training',
                                    'numbers':model['numbers']}
        if fitted:
            models[model['model_id']].update(fitted)
    saved = {'version':VERSION,'date':day,'created_at':now.isoformat(),'models':models,
             'fixed_weights':FIXED,'calibrated':False,
             'purpose':'prospective_research_count_score_only',
             'assumptions': ['Normal-game semantics follow user report and remain conditional.',
                             'Exclusive BB/RB, completed day, constant setting and dated identity assumed.',
                             'No individual machine ranking or verified setting probabilities.',
                             'Observed games condition scoring; target-day under 3000G excluded.'],
             'data_sha256':hashlib.sha256((base/'data.json').read_bytes()).hexdigest()}
    saved['snapshot_id'] = identity(saved)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:
        json.dump(saved,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    return saved


def score(snapshot, records, config):
    if snapshot.get('version') != VERSION or identity(snapshot) != snapshot.get('snapshot_id'):
        raise ValueError('Invalid research snapshot')
    created = datetime.fromisoformat(snapshot['created_at'])
    if created.tzinfo is None:
        raise ValueError('Missing timezone')
    local = created.astimezone(ZoneInfo(config['timezone']))
    if str(local.date()) != snapshot['date'] or not in_morning_window(local):
        raise ValueError('Snapshot outside morning window')
    index = record_index(records)
    result = {'date':snapshot['date'],'snapshot_id':snapshot['snapshot_id'],'calibrated':False,'models':{}}
    for model, prediction in snapshot['models'].items():
        out = {'status':'no_prediction','pending':0,'excluded':0,'scored':0,'mean_log_scores':{}}
        result['models'][model] = out
        if prediction['status'] != 'ready':
            continue
        values = {name:[] for name in (*snapshot['fixed_weights'],'rolling_mixture')}
        for number in prediction['numbers']:
            row = index.get((snapshot['date'],model,number))
            if row is None:
                out['pending'] += 1
                continue
            scores = {}
            for name, weights in {**snapshot['fixed_weights'],'rolling_mixture':prediction['weights']}.items():
                p = {'target_date':snapshot['date'],'trained_through':prediction['trained_through'],
                     'model_id':model,'number':number,'setting_weights':weights}
                value = score_count_prediction(row,config,p,ASSUMED_CONTRACT)
                if value['status'] != 'conditional_score':
                    break
                scores[name] = value['log_predictive_probability']
            if len(scores) != len(values):
                out['excluded'] += 1
                continue
            for name,value in scores.items():
                values[name].append(value)
            out['scored'] += 1
        out['status'] = 'pending_results' if out['pending'] else 'complete' if out['scored'] else 'no_scorable_results'
        out['mean_log_scores'] = {name:mean(v) if v else None for name,v in values.items()}
    return result


def summarize_validation(evaluations, as_of):
    """Describe frozen, completed past dates; never promote a live strategy."""
    past = [e for e in evaluations if e['date'] < as_of]
    if len({e['date'] for e in past}) != len(past):
        raise ValueError('Duplicate prospective evaluation date')
    models = {}
    for model in sorted({m for e in past for m in e['models']}):
        eligible = [e['models'][model] for e in past if model in e['models']
                    and e['models'][model]['status'] == 'complete'
                    and e['models'][model]['scored'] > 0]
        days = len(eligible)
        rows = sum(m['scored'] for m in eligible)
        methods = {}
        for name in (*FIXED, 'rolling_mixture'):
            gains = [m['mean_log_scores'][name]-m['mean_log_scores']['equal'] for m in eligible]
            methods[name] = {
                'mean_daily_gain_vs_equal': mean(gains) if days else None,
                'mean_row_gain_vs_equal': sum(g*m['scored'] for g,m in zip(gains,eligible))/rows if rows else None,
                'days_above_equal': sum(g > 0 for g in gains),
                'days_below_equal': sum(g < 0 for g in gains)}
        models[model] = {'completed_days':days, 'scored_rows':rows,
            'excluded_rows':sum(m['excluded'] for m in eligible),
            'days_remaining_to_minimum':max(0,30-days),
            'validation_status':'minimum_sample_reached_review_required' if days >= 30 else 'insufficient_prospective_days',
            'methods':methods}
    complete = [e['date'] for e in past if e['models'] and all(
        m['status'] == 'complete' and m['scored'] > 0 for m in e['models'].values())]
    return {'kind':'frozen_prospective_count_validation', 'as_of':as_of,
        'calibrated':False, 'changes_live_strategy':False,
        'minimum_completed_days_per_model':30,
        'completed_dates':sorted(complete), 'models':models,
        'interpretation':[
            'Higher conditional BB/RB log score is better; compare the same scored rows.',
            'Daily and row-weighted gains are separate; partial dates and same-day results are excluded.',
            'Thirty completed dates is a minimum review gate, not proof or automatic adoption.',
            'No verified setting labels: count fit is not setting 4-6 accuracy, win rate or profit.',
            'Normal-game semantics, constant setting and factory-rate assumptions remain conditional.']}


def run(base=Path(__file__).parent, now=None):
    now = now or datetime.now(timezone.utc)
    config = json.loads((base/'machines.json').read_text())
    records = json.loads((base/'data.json').read_text())['machine_records']
    freeze(base,config,records,now)
    day = str(now.astimezone(ZoneInfo(config['timezone'])).date())
    count = 0
    evaluations = []
    for path in sorted((base/'history/count-predictions').glob('*.json')):
        snapshot = json.loads(path.read_text())
        if snapshot['date'] > day:
            continue
        evaluation = score(snapshot,records,config)
        write_json(base/'history/count-evaluations'/path.name,evaluation)
        evaluations.append(evaluation)
        count += 1
    write_json(base/'history/research'/('prospective-count-validation-'+day+'.json'),
               summarize_validation(evaluations,day))
    print(json.dumps({'research_snapshots_evaluated':count,'date':day}))


if __name__ == '__main__':
    run()
