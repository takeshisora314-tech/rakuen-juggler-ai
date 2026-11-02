"""Offline ranking audit. Does not modify production data, forecasts or rules."""
import argparse
import ast
import bisect
import hashlib
import itertools
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from collect_sources import layout_on
from forecast_engine import make_forecast, record_index, snapshot_id, valid_record
from setting_model import infer_day, REQUIRED_CONTRACT

MODELS = ('myj5','myj6')
PRIORS = {'equal':[1/6]*6,'low_heavy':[.60,.20,.10,.05,.03,.02],
          'high_heavy':[.05,.05,.10,.20,.30,.30]}
CONTRACT = {k:True for k in REQUIRED_CONTRACT}
# Fixed exploratory candidates; no selection from the Nov 1 outcome.
CANDIDATES = {
    'current': '45% three-day dip + 35% shrunk historical REG + 20% play support',
    'bb_small': 'Same cohort/window; 45% dip + 25% REG + 10% BB + 20% support',
    'dip_moderate': 'Same cohort/window; 30% dip + 35% REG + 15% BB + 20% support',
    'history_90': 'bb_small with BB/REG rates from preceding 90 calendar days',
    'previous_day': 'bb_small with BB/REG rates from the latest previous report day'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def features(config, records, target, model_id):
    model=next(m for m in layout_on(config,target) if m['model_id']==model_id)
    start=str(date.fromisoformat(target)-timedelta(days=14))
    rows=[r for r in records if r['model_id']==model_id and r['number'] in model['numbers']
          and start<=r['date']<target]
    days=sorted({r['date'] for r in rows},reverse=True)[:7]
    usable=[r for r in rows if r['date'] in days and valid_record(r)]
    g=sum(r['games'] for r in usable)
    pools={k:sum(r[k] for r in usable)/g if g else 0 for k in ('bb','rb')}
    out={}
    for n in model['numbers']:
        history=sorted([r for r in usable if r['number']==n and r['games']>=3000],
                       key=lambda r:r['date'],reverse=True)
        if len(history)<3 or history[0]['date']!=days[0] or sum(r['games'] for r in history)<12000:
            continue
        total=sum(r['games'] for r in history)
        dip=sum(r['difference'] for r in history[:3])
        def component(k, selected, pool):
            gs=sum(r['games'] for r in selected)
            rate=(sum(r[k] for r in selected)+5000*pool)/(gs+5000)
            return min(1,max(0,.5+2*(rate/pool-1))) if pool else 0
        long_start=str(date.fromisoformat(target)-timedelta(days=90))
        long=[r for r in records if r['model_id']==model_id and r['number'] in model['numbers']
              and long_start<=r['date']<target and valid_record(r)]
        long_g=sum(r['games'] for r in long)
        long_pool={k:sum(r[k] for r in long)/long_g if long_g else 0 for k in ('bb','rb')}
        long_machine=[r for r in long if r['number']==n and r['games']>=3000]
        values={'dip':min(1,max(0,-dip/4000)),'support':min(1,total/30000),
                'rb':component('rb',history,pools['rb']),'bb':component('bb',history,pools['bb']),
                'rb_90':component('rb',long_machine,long_pool['rb']),
                'bb_90':component('bb',long_machine,long_pool['bb']),
                'rb_day':component('rb',history[:1],pools['rb']),
                'bb_day':component('bb',history[:1],pools['bb']),
                'history_days':len(history),'history_games':total,
                'history_bb':sum(r['bb'] for r in history),'history_rb':sum(r['rb'] for r in history),
                'three_day_difference':dip,'latest_date':history[0]['date'],
                'latest_games':history[0]['games'],'latest_difference':history[0]['difference'],
                'training_dates':sorted({r['date'] for r in history}),
                'pool_rb_denominator':1/pools['rb'] if pools['rb'] else None}
        values['current_points']={'dip':45*values['dip'],'rb':35*values['rb'],'support':20*values['support']}
        out[n]=values
    return out


def rank_candidate(fs, name):
    def value(v):
        if name=='current': return .45*v['dip']+.35*v['rb']+.20*v['support']
        if name=='dip_moderate': return .30*v['dip']+.35*v['rb']+.15*v['bb']+.20*v['support']
        rb,bb=('rb_90','bb_90') if name=='history_90' else ('rb_day','bb_day') if name=='previous_day' else ('rb','bb')
        return .45*v['dip']+.25*v[rb]+.10*v[bb]+.20*v['support']
    return sorted(fs,key=lambda n:(-round(100*value(fs[n]),2),n))


def outcome_summary(rows, config):
    if not rows: return None
    valid=[r for r in rows if valid_record(r)]
    masses={k:[] for k in PRIORS}
    for row in valid:
        for label,prior in PRIORS.items():
            result=infer_day(row,config,prior,CONTRACT)
            if result['status']=='conditional_result': masses[label].append(result['conditional_mass_4_6'])
    return {'count':len(valid),'positive':sum(r['difference']>0 for r in valid),
        'positive_rate':mean(r['difference']>0 for r in valid) if valid else None,
        'total_difference':sum(r['difference'] for r in valid),
        'mean_difference':mean(r['difference'] for r in valid) if valid else None,
        'under_3000':sum(r['games']<3000 for r in valid),
        'conditional_setting_reference':{k:{'eligible':len(v),
            'mean_mass_4_6':mean(v) if v else None,
            'share_mass_at_least_half':mean(x>=.5 for x in v) if v else None}
            for k,v in masses.items()}}


def grouped_ranks(groups, config):
    result={}
    for model, entries in groups.items():
        by_rank=defaultdict(list); top=[];backup=[]
        for entry in entries:
            for rank,row in enumerate(entry['rows'],1):
                by_rank[rank].append(row)
                (top if rank<=3 else backup).append(row) if rank<=10 else None
        result[model]={'dates':[e['date'] for e in entries], 'days':len(entries),
            'by_rank':{str(k):outcome_summary(v,config) for k,v in sorted(by_rank.items())},
            'top3':outcome_summary(top,config),'ranks4_10':outcome_summary(backup,config)}
    return result


def audit_archives(base, config, records, as_of):
    index=record_index(records); groups=defaultdict(list);checks=[]
    for path in sorted((base/'history/forecasts').glob('*.json')):
        s=json.loads(path.read_text());created=datetime.fromisoformat(s['created_at']).astimezone(ZoneInfo('Asia/Tokyo'))
        valid=snapshot_id(s)==s.get('snapshot_id') and s.get('kind')=='prospective' and str(created.date())==s['date'] and created.hour<7
        checks.append({'date':s['date'],'hash_valid':snapshot_id(s)==s.get('snapshot_id'),
                       'created_at':s['created_at'],'pre07_generation_valid':valid,
                       'eligible_for_completed_audit':valid and s['date']<as_of})
        if not valid or s['date']>=as_of: continue
        for model in MODELS:
            v=s['models'].get(model,{})
            if v.get('status')!='ready':continue
            method=v['selection']['strategy'];ranking=v.get('rankings',{}).get(method,v['strategies'][method])
            actual=[index.get((s['date'],model,r['number'])) for r in ranking]
            if all(r is not None and valid_record(r) for r in actual):
                groups[model].append({'date':s['date'],'rows':actual})
    return {'checks':checks,'models':grouped_ranks(groups,config),
            'note':'Archive creation timestamps are cross-checked separately against first Git commit; publication before 07:00 is a different question.'}


def case_audit(base, config, records):
    snapshot=json.loads((base/'history/forecasts/2026-11-01.json').read_text())
    morning=json.loads((base/'data-morning.json').read_text())
    from morning_forecast_engine import make_forecast as original_make
    reconstructed=original_make(config,morning['machine_records'],'2026-11-01',
        morning['evaluation']['prospective'],created_at=snapshot['created_at'])
    if reconstructed['models']!=snapshot['models']:raise ValueError('Morning snapshot not reproduced')
    index=record_index(records);result={};selected_all=[];actual_all=[]
    for model in MODELS:
        v=snapshot['models'][model];method=v['selection']['strategy'];ranking=v['rankings'][method]
        fs=features(config,morning['machine_records'],'2026-11-01',model)
        if rank_candidate(fs,'current')!=[r['number'] for r in ranking]:raise ValueError('Feature reconstruction mismatch')
        layout=next(m for m in layout_on(config,'2026-11-01') if m['model_id']==model)
        actual=[index[('2026-11-01',model,n)] for n in layout['numbers']]
        selected=[index[('2026-11-01',model,r['number'])] for r in ranking[:3]]
        selected_all+=selected;actual_all+=actual
        selected_numbers={r['number'] for r in selected}
        reasons=[]
        for rank,candidate in enumerate(ranking[:3],1):
            row=index[('2026-11-01',model,candidate['number'])];f=fs[candidate['number']]
            score=round(sum(f['current_points'].values()),2)
            if score!=candidate['score']:raise ValueError('Score decomposition mismatch')
            reasons.append({'rank':rank,'saved_prediction':candidate,'actual':row,'features':f})
        result[model]={'all_installed':outcome_summary(actual,config),
            'top3':outcome_summary(selected,config),
            'unselected':outcome_summary([r for r in actual if r['number'] not in selected_numbers],config),
            'selected_mean_lift_vs_all':mean(r['difference'] for r in selected)-mean(r['difference'] for r in actual),
            'reasons':reasons,
            'all39_detail':[{'rank':i+1,'number':r['number'],'actual':index[('2026-11-01',model,r['number'])]} for i,r in enumerate(ranking)]}
    # Exact comparison to uniformly drawing three machines from each model that day.
    pools=[[r['difference'] for r in index.values() if r['date']=='2026-11-01' and r['model_id']==m] for m in MODELS]
    sums=[sorted(sum(c) for c in itertools.combinations(pool,3)) for pool in pools]
    observed=sum(r['difference'] for r in selected_all)
    exceed=sum(len(sums[1])-bisect.bisect_left(sums[1],observed-x) for x in sums[0])
    return {'date':'2026-11-01','snapshot_id':snapshot['snapshot_id'],'created_at':snapshot['created_at'],
        'morning_models_reproduced_exactly':True,'models':result,
        'combined_selected':outcome_summary(selected_all,config),'combined_all39':outcome_summary(actual_all,config),
        'one_day_stratified_random_reference':{'combinations':len(sums[0])*len(sums[1]),
            'tail_probability_for_difference':exceed/(len(sums[0])*len(sums[1])),
            'note':'Conditional one-day random-selection reference, not a future-performance significance claim.'}}


def replay(config, records, as_of):
    index=record_index(records);daily=[];baseline_groups=defaultdict(list)
    start=date.fromisoformat(as_of)-timedelta(days=90)
    for offset in range(90):
        day=str(start+timedelta(days=offset))
        forecast=make_forecast(config,records,day,evaluations=(),created_at=day+'T05:00:00+09:00')
        for model in MODELS:
            v=forecast['models'].get(model,{})
            if v.get('status')!='ready':continue
            layout=next(m for m in layout_on(config,day) if m['model_id']==model)
            actual=[index.get((day,model,n)) for n in layout['numbers']]
            if any(r is None or not valid_record(r) for r in actual):continue
            fs=features(config,records,day,model)
            if rank_candidate(fs,'current')!=[r['number'] for r in v['rankings']['balanced']]:raise ValueError('Baseline replay drift')
            all_mean=mean(r['difference'] for r in actual)
            rankings={name:rank_candidate(fs,name) for name in CANDIDATES}
            entry={'date':day,'model_id':model,'cohort':len(fs),'installed':len(actual),
                'weekend':date.fromisoformat(day).weekday()>=5,'all_mean':all_mean,
                'all_positive_rate':mean(r['difference']>0 for r in actual),'methods':{}}
            for name, ranking in rankings.items():
                selected=[index[(day,model,n)] for n in ranking[:3]]
                entry['methods'][name]={'numbers':ranking[:3],
                    'mean_difference':mean(r['difference'] for r in selected),
                    'positive_rate':mean(r['difference']>0 for r in selected),
                    'lift':mean(r['difference'] for r in selected)-all_mean}
            daily.append(entry)
            baseline_groups[model].append({'date':day,'rows':[index[(day,model,n)] for n in rankings['current']]})
    summaries={}
    for model in MODELS:
        summaries[model]={}
        for period in ('all','development','validation','case_nov1','weekday','weekend'):
            chosen=[r for r in daily if r['model_id']==model and (
                period=='all' or period=='development' and r['date']<'2026-10-03' or
                period=='validation' and '2026-10-03'<=r['date']<'2026-11-01' or
                period=='case_nov1' and r['date']=='2026-11-01' or
                period=='weekday' and not r['weekend'] or period=='weekend' and r['weekend'])]
            methods={}
            for name in CANDIDATES:
                gains=[r['methods'][name]['mean_difference']-r['methods']['current']['mean_difference'] for r in chosen]
                if not chosen:continue
                ci=None
                if len(gains)>=10:
                    rng=random.Random(1701);boots=sorted(mean(rng.choices(gains,k=len(gains))) for _ in range(3000))
                    ci=[boots[74],boots[2924]]
                methods[name]={'mean_difference':mean(r['methods'][name]['mean_difference'] for r in chosen),
                    'positive_rate':mean(r['methods'][name]['positive_rate'] for r in chosen),
                    'mean_lift_vs_installed':mean(r['methods'][name]['lift'] for r in chosen),
                    'mean_daily_gain_vs_current':mean(gains),
                    'paired_day_bootstrap_95':ci,
                    'positive_rate_change_vs_current':mean(r['methods'][name]['positive_rate']-r['methods']['current']['positive_rate'] for r in chosen)}
            summaries[model][period]={'days':len(chosen),'rows_selected_per_method':sum(min(3,r['cohort']) for r in chosen),'methods':methods}
    return {'summaries':summaries,'daily':daily,'baseline_rank_metrics':grouped_ranks(baseline_groups,config),
            'limitations':['Retrospective past-only replay; historical publication availability is unknown.',
                'All alternatives use identical eligible machines and dates; outcomes excluded unless every installed machine is valid.',
                'Validation split is chronological but not a pristine untouched holdout; candidates were designed after earlier exploratory work.',
                'Nov 1 is reported separately and excluded from validation. No automated production promotion.',
                'Bootstrap resamples paired days; it does not remove serial dependence, multiple comparisons or selection bias.',
                'Weekends are descriptive, not store-event labels. Actual setting labels are absent.']}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--base',type=Path,default=Path(__file__).parent)
    args=parser.parse_args();base=args.base;as_of='2026-11-02'
    data=json.loads((base/'data-current.json').read_text());config=json.loads((base/'machines.json').read_text())
    records=[r for r in data['machine_records'] if r['date']<as_of]
    record_index(records)
    report={'as_of':as_of,'changes_live_strategy':False,'calibrated':False,
        'candidate_specifications':CANDIDATES,
        'setting_reference_definition':'Conditional BB/RB posterior mass on settings 4-6 under explicit equal/low-heavy/high-heavy priors, and share >=0.5; >=3000G only. Neither is verified setting accuracy.',
        'sha256':{p:digest(base/p) for p in ['data-current.json','data-morning.json','machines.json','forecast_engine.py','morning_forecast_engine.py']},
        'case':case_audit(base,config,records),
        'saved_morning_predictions':audit_archives(base,config,records,as_of),
        'historical_comparison':replay(config,records,as_of)}
    path=base/'prediction-accuracy-review-2026-11-02.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(path),'case':{m:report['case']['models'][m]['selected_mean_lift_vs_all'] for m in MODELS},
        'saved_days':{m:v['days'] for m,v in report['saved_morning_predictions']['models'].items()},
        'historical_days':{m:v['all']['days'] for m,v in report['historical_comparison']['summaries'].items()}},ensure_ascii=False))


if __name__=='__main__':main()
