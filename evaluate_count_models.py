"""Offline, past-only replay of conditional BB/RB counts; no live strategy changes."""
import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

from forecast_engine import record_index
from setting_model import REQUIRED_CONTRACT, SPECS, infer_day, score_count_prediction

FIXED = {'equal': [1/6]*6, 'low_heavy': [.60,.20,.10,.05,.03,.02],
         'high_heavy': [.05,.05,.10,.20,.30,.30]}
# Hypotheses for this offline experiment, not verified source declarations.
ASSUMED_CONTRACT = {key: True for key in REQUIRED_CONTRACT}


def count_terms(row):
    g, b, r = (row[k] for k in ('games', 'bb', 'rb'))
    return [b*math.log(1/bd)+r*math.log(1/rd)
            +(g-b-r)*math.log1p(-1/bd-1/rd) for bd,rd in SPECS[row['model_id']]]


def fit_weights(records, config, model_id, target_day):
    """Regularized six-component mixture, fitted to individual past machine-days."""
    target = date.fromisoformat(target_day)
    start = str(target-timedelta(days=14))
    history = [r for r in records if r['model_id'] == model_id
               and start <= r['date'] < target_day
               and infer_day(r, config, FIXED['equal'], ASSUMED_CONTRACT)['status'] == 'conditional_result']
    if len(history) < 20 or len({r['date'] for r in history}) < 3:
        return None
    terms = [count_terms(r) for r in history]
    weights = FIXED['equal'][:]
    for _ in range(50):
        # One equal pseudo-observation per component prevents zero weights.
        totals = [1.0]*6
        for row in terms:
            logs = [math.log(w)+v for w,v in zip(weights,row)]
            peak = max(logs)
            resp = [math.exp(v-peak) for v in logs]
            total = sum(resp)
            totals = [a+b/total for a,b in zip(totals,resp)]
        new = [v/(len(history)+6) for v in totals]
        if max(abs(a-b) for a,b in zip(weights,new)) < 1e-8:
            weights = new
            break
        weights = new
    return {'weights': weights, 'trained_through': max(r['date'] for r in history),
            'training_rows': len(history), 'training_days': len({r['date'] for r in history})}


def evaluate_records(records, config, as_of):
    record_index(records)  # Duplicate keys must not silently get extra weight.
    target_end = date.fromisoformat(as_of)
    start = str(target_end-timedelta(days=90))
    days = sorted({r['date'] for r in records if start <= r['date'] < as_of})
    by_day = defaultdict(list)
    for row in records:
        by_day[row['date']].append(row)
    outcomes = defaultdict(lambda: defaultdict(list))
    frozen = []
    excluded = defaultdict(int)
    for day in days:
        for model in sorted({r['model_id'] for r in by_day[day]}):
            fitted = fit_weights(records, config, model, day)
            if fitted is None:
                excluded['insufficient_training_rows'] += sum(r['model_id']==model for r in by_day[day])
                continue
            frozen.append({'date':day,'model_id':model,**fitted})
            priors = {**FIXED, 'rolling_mixture': fitted['weights']}
            for row in by_day[day]:
                if row['model_id'] != model:
                    continue
                scores = {}
                for name, weights in priors.items():
                    pred = {'target_date':day,'trained_through':fitted['trained_through'],
                            'model_id':model,'number':row['number'],'setting_weights':weights}
                    result = score_count_prediction(row,config,pred,ASSUMED_CONTRACT)
                    if result['status'] != 'conditional_score':
                        break
                    scores[name] = result['log_predictive_probability']
                if len(scores) != len(priors):
                    excluded['invalid_or_under_3000_games'] += 1
                    continue
                outcomes[(model,day)]['scores'].append(scores)
    summaries = {}
    recent = str(target_end-timedelta(days=30))
    for model in sorted({m for m,d in outcomes}):
        summaries[model] = {}
        for period in ('all','recent_30'):
            groups = [v['scores'] for (m,d),v in outcomes.items()
                      if m==model and (period=='all' or d>=recent)]
            rows = [r for g in groups for r in g]
            summaries[model][period] = {'days':len(groups),'rows':len(rows),'methods':{
                name:{'mean_log_score':mean(r[name] for r in rows) if rows else None,
                      'mean_daily_gain_vs_equal':mean(mean(r[name]-r['equal'] for r in g) for g in groups) if groups else None}
                for name in (*FIXED,'rolling_mixture')}}
    return {'kind':'past_only_conditional_count_replay','as_of':as_of,'from':start,
            'calibrated':False,'changes_live_strategy':False,
            'assumptions':['Normal-game semantics extended from user report as an exploratory hypothesis for all dates.',
                           'Exclusive BB/RB, constant daily setting, completed day and dated model identity are assumed.',
                           'Actual games are conditioned on, not predicted. No setting labels or profit forecasts.',
                           'Only earlier 14 calendar days train the mixture; >=20 rows across >=3 dates, each >=3000G.',
                           'Same evaluation rows for every method. Higher log score is better.',
                           'Target-day >=3000G filtering uses observed outcomes; this is a conditional subgroup, not all pre-opening candidates.',
                           'Recent 30 days are descriptive, not untouched holdout. Historical publication timing is unknown.',
                           'Fixed priors and mixture design were chosen after prior sensitivity inspection; not prospective validation.'],
            'fixed_weights':FIXED,'mixture':{'max_iterations':50,'equal_pseudocount_per_setting':1},
            'excluded':dict(excluded),'summaries':summaries,'training_weights':frozen}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of',required=True)
    parser.add_argument('--base',type=Path,default=Path(__file__).parent)
    args=parser.parse_args()
    data=(args.base/'data.json').read_bytes(); config=(args.base/'machines.json').read_bytes()
    report=evaluate_records(json.loads(data)['machine_records'],json.loads(config),args.as_of)
    report.update(data_sha256=hashlib.sha256(data).hexdigest(),config_sha256=hashlib.sha256(config).hexdigest())
    path=args.base/'history/research'/('count-model-comparison-'+args.as_of+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report['summaries'],ensure_ascii=False))


if __name__=='__main__':
    main()
