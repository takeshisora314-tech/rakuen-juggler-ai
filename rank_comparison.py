"""Prospective ranking comparison only. Never selects or publishes a live model.

Capture is called only when the live engine creates a new morning snapshot.
The command-line entry point settles saved pairs; it cannot create predictions.
"""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

from collect_sources import BASE, layout_on, write_json
from forecast_engine import make_forecast, morning_input_readiness, record_index, snapshot_id, valid_record

VERSION = 'prospective-rank-pair-v1'
START_DATE = '2026-11-03'
MINIMUM_DAYS = 30
SPEC = {
    'candidate_id': 'bb-small-v1',
    'weights': {'dip': .45, 'rb': .25, 'bb': .10, 'support': .20},
    'calendar_window': 14, 'report_days': 7, 'min_daily_games': 3000,
    'min_history_days': 3, 'min_history_games': 12000,
    'shrinkage_games': 5000, 'dip_limit': 4000, 'support_limit': 30000,
    'top_n': 3, 'automatic_promotion': False,
}
ROOT = Path('history/rank-comparison')


def identity(value, key='snapshot_id'):
    body = {k:v for k,v in value.items() if k != key}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',',':'),
                                   ensure_ascii=False).encode()).hexdigest()


def code_digest(name):
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def candidates(config, records, live):
    """Same eligible machines and historic window as the frozen live engine."""
    day = live['date']
    rebuilt = make_forecast(config, records, day, (), created_at=live['created_at'])
    models = {}
    for installation in layout_on(config, day):
        model = installation['model_id']
        baseline = live['models'].get(model, {})
        status = {'status':'insufficient_prediction', 'installed_numbers':installation['numbers']}
        models[model] = status
        if baseline.get('status') != 'ready':
            continue
        # Detect a changed input/ranking implementation before accepting a pair.
        if rebuilt['models'][model]['rankings'] != baseline.get('rankings'):
            raise ValueError('Live ranks cannot be reproduced from capture inputs')
        strategy = baseline['selection']['strategy']
        current = baseline['rankings'][strategy]
        if len(current) < SPEC['top_n']:
            continue
        start = str(date.fromisoformat(day)-timedelta(days=SPEC['calendar_window']))
        rows = [r for r in records if r['model_id']==model
                and r['number'] in installation['numbers'] and start <= r['date'] < day]
        dates = sorted({r['date'] for r in rows}, reverse=True)[:SPEC['report_days']]
        usable = [r for r in rows if r['date'] in dates and valid_record(r)]
        pool_games = sum(r['games'] for r in usable)
        pools = {key:sum(r[key] for r in usable)/pool_games if pool_games else 0
                 for key in ('bb','rb')}
        scored = []
        for entry in current:
            history = [r for r in usable if r['number']==entry['number']
                       and r['games']>=SPEC['min_daily_games']]
            games = sum(r['games'] for r in history)
            def rate_score(key):
                pool = pools[key]
                rate = (sum(r[key] for r in history)+SPEC['shrinkage_games']*pool)/(games+SPEC['shrinkage_games'])
                return min(1,max(0,.5+2*(rate/pool-1))) if pool else 0
            components = {'dip':min(1,max(0,-entry['three_day_difference']/SPEC['dip_limit'])),
                          'rb':rate_score('rb'), 'bb':rate_score('bb'),
                          'support':min(1,games/SPEC['support_limit'])}
            scored.append({'number':entry['number'],
                'score':round(100*sum(SPEC['weights'][k]*v for k,v in components.items()),2),
                'components':components, 'history_games':games,
                'history_dates':sorted(r['date'] for r in history)})
        status.update(status='ready', baseline_strategy=strategy,
            cohort=sorted(r['number'] for r in current),
            baseline=[{'number':r['number'],'score':r['score']} for r in current],
            candidate=sorted(scored,key=lambda r:(-r['score'],r['number'])))
    return models


def validate(snapshot):
    if (snapshot.get('version') != VERSION or snapshot.get('kind')!='prospective_paired_ranking'
            or identity(snapshot) != snapshot.get('snapshot_id')):
        raise ValueError('Invalid ranking pair integrity or version')
    created = datetime.fromisoformat(snapshot['created_at'])
    local = created.astimezone(ZoneInfo('Asia/Tokyo'))
    if (created.tzinfo is None or str(local.date())!=snapshot['date']
            or not 5 <= local.hour < 7 or snapshot['date'] < START_DATE
            or snapshot['max_input_date'] >= snapshot['date']
            or snapshot['specification'] != SPEC):
        raise ValueError('Pair violates prospective capture policy')
    for model in snapshot['models'].values():
        if model['status'] != 'ready':
            continue
        installed = model['installed_numbers']
        cohort = model['cohort']
        if (len(set(installed))!=len(installed) or len(cohort)<SPEC['top_n']
                or len(set(cohort))!=len(cohort) or not set(cohort)<=set(installed)):
            raise ValueError('Invalid paired cohort')
        for method in ('baseline','candidate'):
            numbers = [r['number'] for r in model[method]]
            if len(numbers)!=len(cohort) or set(numbers)!=set(cohort):
                raise ValueError('Unpaired model candidates')


def capture(base, config, records, live, now):
    """Only accept a just-created live snapshot, never reconstruct an old day."""
    if now.tzinfo is None:
        raise ValueError('Timezone-aware execution required')
    local = now.astimezone(ZoneInfo('Asia/Tokyo'))
    day = str(local.date())
    if day < START_DATE or not 5 <= local.hour < 7:
        return None
    if (live.get('date')!=day or live.get('created_at')!=now.isoformat()
            or live.get('kind')!='prospective' or live.get('snapshot_id')!=snapshot_id(live)):
        raise ValueError('Pair requires the newly frozen morning prediction')
    path = base/ROOT/'forecasts'/(day+'.json')
    if path.exists():
        saved = json.loads(path.read_text())
        validate(saved)
        if saved['live_snapshot_id']!=live['snapshot_id']:
            raise ValueError('Pair belongs to another live forecast')
        return saved
    live_path = base/'history/forecasts'/(day+'.json')
    if not live_path.exists() or json.loads(live_path.read_text()) != live:
        raise ValueError('Live prediction must be saved first')
    if not morning_input_readiness(config, records, day)['ready']:
        return None
    record_index(records)
    # Deliberately omit target/future rows from both input digest and features.
    start = str(local.date()-timedelta(days=SPEC['calendar_window']))
    prior = sorted([r for r in records if start <= r['date'] < day],
                   key=lambda r:(r['date'],r['model_id'],r['number']))
    saved = {'version':VERSION, 'date':day, 'created_at':now.isoformat(),
        'kind':'prospective_paired_ranking', 'live_snapshot_id':live['snapshot_id'],
        'specification':SPEC, 'baseline_code_sha256':code_digest('forecast_engine.py'),
        'candidate_code_sha256':code_digest('rank_comparison.py'),
        'configuration_sha256':identity(config), 'input_sha256':identity({'records':prior}),
        'max_input_date':max((r['date'] for r in prior),default='0001-01-01'),
        'models':candidates(config, records, live)}
    saved['snapshot_id'] = identity(saved)
    validate(saved)
    path.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation: fail without replacing an already saved morning pair.
    with path.open('x',encoding='utf-8') as stream:
        json.dump(saved,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    return saved


def metrics(rows, installed_mean):
    return {'count':len(rows), 'positive_count':sum(r['difference']>0 for r in rows),
        'positive_rate':mean(r['difference']>0 for r in rows),
        'total_difference':sum(r['difference'] for r in rows),
        'mean_difference':mean(r['difference'] for r in rows),
        'mean_lift_vs_all':mean(r['difference'] for r in rows)-installed_mean}


def score(snapshot, records, now):
    validate(snapshot)
    if now.tzinfo is None:
        raise ValueError('Timezone-aware execution required')
    local = now.astimezone(ZoneInfo('Asia/Tokyo'))
    day = snapshot['date']
    index = record_index(records)
    result = {'version':VERSION,'date':day,'snapshot_id':snapshot['snapshot_id'],
              'checked_at':now.isoformat(),'models':{}}
    complete_time = day < str(local.date()) or (day==str(local.date()) and (local.hour,local.minute)>=(23,30))
    for name, model in snapshot['models'].items():
        out = {'status':'no_paired_prediction'}
        result['models'][name] = out
        if model['status']!='ready':
            continue
        if not complete_time:
            out['status'] = 'waiting_for_day_end'
            continue
        missing = [n for n in model['installed_numbers']
                   if not valid_record(index.get((day,name,n),{}))]
        if missing:
            out.update(status='pending_results',missing_numbers=missing)
            continue
        actual = [index[(day,name,n)] for n in model['installed_numbers']]
        all_mean = mean(r['difference'] for r in actual)
        out.update(status='complete',settled_at=now.isoformat(),all_installed=metrics(actual,all_mean),
            actual_sha256=identity({'records':actual}),methods={})
        for method in ('baseline','candidate'):
            ranked = [index[(day,name,r['number'])] for r in model[method]]
            out['methods'][method] = {'top3':metrics(ranked[:3],all_mean),
                'by_rank':[{'rank':i+1,**{k:r[k] for k in ('number','games','bb','rb','difference')}}
                           for i,r in enumerate(ranked)]}
    return result


def summarize(entries, as_of):
    """Count only completed same-date paired observations, grouped by frozen rules."""
    groups = {}
    seen = set()
    for snap, evaluation in entries:
        validate(snap)
        if evaluation['snapshot_id']!=snap['snapshot_id'] or evaluation['date']!=snap['date']:
            raise ValueError('Evaluation references a different morning pair')
        if snap['date'] in seen:
            raise ValueError('Duplicate paired date')
        seen.add(snap['date'])
        if snap['date'] > as_of:
            continue
        for name, value in evaluation['models'].items():
            if value['status']!='complete':
                continue
            model = snap['models'][name]
            signature = identity({'baseline_code':snap['baseline_code_sha256'],
                'candidate_code':snap['candidate_code_sha256'],'configuration':snap['configuration_sha256'],
                'baseline_strategy':model['baseline_strategy'],'specification':snap['specification']})
            group = groups.setdefault((name,signature),{'model_id':name,'signature':signature,
                'baseline_strategy':model['baseline_strategy'],'observations':[]})
            group['observations'].append({'date':snap['date'],**value})
    models = {}
    for (name,signature), group in sorted(groups.items()):
        days = group.pop('observations')
        methods = {}
        for method in ('baseline','candidate'):
            count = sum(d['methods'][method]['top3']['count'] for d in days)
            positives = sum(d['methods'][method]['top3']['positive_count'] for d in days)
            total = sum(d['methods'][method]['top3']['total_difference'] for d in days)
            rank_rows = {}
            for d in days:
                for row in d['methods'][method]['by_rank']:
                    rank_rows.setdefault(row['rank'],[]).append(row)
            methods[method] = {'top3':{'count':count,'positive_count':positives,
                'positive_rate':positives/count,'mean_difference':total/count,
                'mean_lift_vs_all':mean(d['methods'][method]['top3']['mean_lift_vs_all'] for d in days)},
                'by_rank':{str(k):metrics(v,mean(d['all_installed']['mean_difference'] for d in days if len(d['methods'][method]['by_rank'])>=k))
                           for k,v in sorted(rank_rows.items())}}
        gains = [d['methods']['candidate']['top3']['mean_difference']-d['methods']['baseline']['top3']['mean_difference'] for d in days]
        group.update(completed_days=len(days),dates=sorted(d['date'] for d in days),methods=methods,
            minimum_days=MINIMUM_DAYS,days_remaining=max(0,MINIMUM_DAYS-len(days)),
            status='minimum_reached_review_required' if len(days)>=MINIMUM_DAYS else 'insufficient_completed_days',
            paired_comparison={'mean_difference_gain':mean(gains),'median_daily_gain':median(gains),
                'positive_rate_change':methods['candidate']['top3']['positive_rate']-methods['baseline']['top3']['positive_rate'],
                'days_better':sum(g>0 for g in gains),'days_worse':sum(g<0 for g in gains),
                'minimum_daily_gain':min(gains),'maximum_daily_gain':max(gains)})
        models.setdefault(name,{'segments':[]})['segments'].append(group)
    return {'version':VERSION,'as_of':as_of,'start_date':START_DATE,'minimum_days':MINIMUM_DAYS,
        'automatic_promotion':False,'changes_live_strategy':False,'models':models,
        'notes':['Only complete model-days with all installed numeric results enter paired statistics.',
                 'Same-day results wait until 23:30 JST; delayed results are retried later.',
                 'Rule/configuration/live-strategy changes start separate 30-day segments.',
                 'All-machine lift averages daily baselines; zero difference is not positive.',
                 'Thirty days triggers human review only; daily profit is not verified setting accuracy.']}


def render_summary(summary):
    lines = ['# 日次予想モデル比較', '',
        '現行の公開予想は継続。候補はBB10%追加。自動切り替えなし。',
        f"\n集計時点：{summary['as_of']}。開始：{START_DATE}。機種・同一ルールごとに30評価日が最低目安。",
        '\n未取得・不完全な日は成績の分母に入れず、実績取得後に再照合する。朝に保存できなかった予想は後から作らない。']
    if not summary['models']:
        lines += ['','比較可能な完了日はまだありません。']
    for name, model in summary['models'].items():
        for segment in model['segments']:
            lines += ['',f"## {name}（現行 {segment['baseline_strategy']}）",'',
                f"評価済み {segment['completed_days']}日 / 最低目安まで {segment['days_remaining']}日。区分 {segment['signature'][:12]}",
                '', '| 指標 | 現行 | BB10%候補 |', '| --- | --- | --- |']
            a,b=(segment['methods'][m]['top3'] for m in ('baseline','candidate'))
            lines += [f"| プラス率 | {a['positive_rate']:.1%} | {b['positive_rate']:.1%} |",
                f"| 平均差枚 | {a['mean_difference']:+.0f} | {b['mean_difference']:+.0f} |",
                f"| 全台平均との差 | {a['mean_lift_vs_all']:+.0f} | {b['mean_lift_vs_all']:+.0f} |",
                '', '順位別成績（プラス率 / 平均差枚）', '', '| 順位 | 現行 | BB10%候補 |', '| --- | --- | --- |']
            for rank,a in segment['methods']['baseline']['by_rank'].items():
                b=segment['methods']['candidate']['by_rank'][rank]
                lines.append(f"| {rank}位 | {a['positive_rate']:.1%} / {a['mean_difference']:+.0f} | {b['positive_rate']:.1%} / {b['mean_difference']:+.0f} |")
    lines += ['', '30日に達しても改善確定とは扱わず、偏りや機種別の悪化を確認してから採否を判断する。', '']
    return '\n'.join(lines)


def run(base=BASE, now=None, new_snapshot=None, config=None, records=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Timezone-aware execution required')
    base = Path(base)
    config = config if config is not None else json.loads((base/'machines.json').read_text())
    records = records if records is not None else json.loads((base/'data.json').read_text()).get('machine_records',[])
    local = now.astimezone(ZoneInfo('Asia/Tokyo'))
    today = str(local.date())
    errors = []
    if new_snapshot is not None:
        try:
            capture(base,config,records,new_snapshot,now)
        except Exception as exc:
            errors.append({'stage':'capture','error':str(exc)})
    entries = []
    pending = []
    for path in sorted((base/ROOT/'forecasts').glob('*.json')):
        try:
            snap = json.loads(path.read_text())
            validate(snap)
            if snap['date']>today:
                continue
            live_path = base/'history/forecasts'/path.name
            live = json.loads(live_path.read_text())
            if snapshot_id(live)!=snap['live_snapshot_id'] or live.get('snapshot_id')!=snap['live_snapshot_id']:
                raise ValueError('Original live forecast is missing or changed')
            target = base/ROOT/'evaluations'/path.name
            previous = json.loads(target.read_text()) if target.exists() else None
            if previous and (previous.get('snapshot_id')!=snap['snapshot_id']
                    or identity(previous,'evaluation_id')!=previous.get('evaluation_id')):
                raise ValueError('Invalid saved paired evaluation')
            if previous and datetime.fromisoformat(previous['checked_at']) > now:
                raise ValueError('Saved evaluation comes from a future observation')
            # Settled model-days are immutable; incomplete models can fill in later.
            complete = previous and all(v['status'] in ('complete','no_paired_prediction') for v in previous['models'].values())
            evaluation = previous if complete else score(snap,records,now)
            if previous and not complete:
                for model,value in previous['models'].items():
                    if value['status']=='complete':
                        evaluation['models'][model]=value
            if not complete:
                evaluation['evaluation_id'] = identity(evaluation,'evaluation_id')
                if evaluation!=previous:
                    write_json(target,evaluation)
            entries.append((snap,evaluation))
            pending += [{'date':snap['date'],'model_id':m,'status':v['status']}
                        for m,v in evaluation['models'].items() if v['status']!='complete']
        except Exception as exc:
            errors.append({'stage':'evaluate','file':path.name,'error':str(exc)})
    summary = summarize(entries,today)
    summary.update(checked_at=now.isoformat(),captured_days=len(entries),pending=pending,errors=errors,
        today_capture_status='not_started' if today < START_DATE
            else 'saved' if (base/ROOT/'forecasts'/(today+'.json')).exists()
            else 'not_captured_no_backfill' if local.hour>=7 else 'waiting_for_new_morning_forecast')
    write_json(base/ROOT/'status.json',summary)
    report = base/ROOT/'REPORT.md'
    report.write_text(render_summary(summary),encoding='utf-8')
    print(json.dumps({'rank_comparison_days':len(entries),'errors':len(errors),'date':today}))
    return summary


if __name__ == '__main__':
    run()
