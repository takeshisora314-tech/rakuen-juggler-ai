"""Experimental, preregistered rules; no claim of true settings or win probability."""
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from zoneinfo import ZoneInfo

from collect_sources import BASE, layout_on, write_json

VERSION = 'experimental-v1'
DEFAULT = 'balanced'
WEIGHTS = {
    'balanced': (0.45, 0.35, 0.20),
    'dip': (0.80, 0.10, 0.10),
    'rb': (0.20, 0.70, 0.10),
}
POLICY = {'min_history_days': 3, 'min_daily_games': 3000,
          'min_total_games': 12000, 'max_source_age_days': 2,
          'comparison_days': 30, 'switch_min_lift_gain': 100,
          'forecast_lock_from_jst_hour': 5, 'forecast_lock_before_jst_hour': 7}


def integer(value):
    return type(value) is int


def valid_record(row):
    return (all(integer(row.get(k)) for k in ('number', 'games', 'bb', 'rb', 'difference'))
            and min(row['games'], row['bb'], row['rb']) >= 0
            and row['bb'] + row['rb'] <= row['games'])


def record_index(records):
    index = {}
    for row in records:
        key = (row['date'], row['model_id'], row['number'])
        if key in index:
            raise ValueError('Duplicate dated machine record')
        index[key] = row
    return index


def comparison_metrics_valid(metrics):
    """Require the fixed top-three protocol, finite metrics and consistent counts."""
    if not isinstance(metrics, dict) or type(metrics.get('count')) is not int or metrics['count'] != 3:
        return False
    for field in ('positive_count', 'low_play_count'):
        if type(metrics.get(field)) is not int or not 0 <= metrics[field] <= 3:
            return False
    for field in ('positive_rate', 'mean_difference', 'lift_vs_eligible_mean'):
        value = metrics.get(field)
        if type(value) not in (int, float) or not math.isfinite(value):
            return False
    return math.isclose(metrics['positive_rate'], metrics['positive_count']/3,
                        rel_tol=0, abs_tol=1e-9)


def choose_strategy(evaluations, model_id, target_day):
    """Only prospective, already completed, paired evaluations may change rules."""
    dates = {}
    for evaluation in evaluations:
        if (not isinstance(evaluation, dict) or evaluation.get('kind') != 'prospective'
                or evaluation.get('version') != VERSION):
            continue
        day = evaluation.get('date')
        try:
            if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or day >= target_day:
                continue
        except ValueError:
            continue
        dates.setdefault(day, []).append(evaluation)
    pairs = []
    for day, entries in dates.items():
        # Reject every copy of an ambiguous date, rather than picking a favorable one.
        if len(entries) != 1:
            continue
        models = entries[0].get('models', {})
        model = models.get(model_id, {}) if isinstance(models, dict) else {}
        if not isinstance(model, dict):
            continue
        strategies = model.get('strategies', {})
        if (model.get('status') == 'complete' and isinstance(strategies, dict)
                and all(comparison_metrics_valid(strategies.get(s)) for s in WEIGHTS)):
            pairs.append((day, strategies))
    pairs = sorted(pairs)[-60:]
    info = {'paired_days': len(pairs), 'minimum_days': POLICY['comparison_days'],
            'status': 'insufficient_evaluation', 'strategy': DEFAULT}
    if len(pairs) < POLICY['comparison_days']:
        return info
    summaries = {s: {'lift': mean(p[s]['lift_vs_eligible_mean'] for _, p in pairs),
                     'positive_rate': mean(p[s]['positive_rate'] for _, p in pairs)}
                 for s in WEIGHTS}
    best = max(WEIGHTS, key=lambda s: (summaries[s]['lift'], s == DEFAULT))
    baseline = summaries[DEFAULT]
    improve = (summaries[best]['lift'] - baseline['lift'] >= POLICY['switch_min_lift_gain']
               and summaries[best]['positive_rate'] >= baseline['positive_rate'])
    info.update(strategy=best if improve else DEFAULT,
                status='switched_by_rule' if improve else 'kept_default',
                comparison=summaries)
    return info


def make_forecast(config, records, target_day, evaluations=(), created_at=None):
    record_index(records)  # reject duplicates rather than double-counting
    target = date.fromisoformat(target_day)
    cutoff = str(target - timedelta(days=14))
    result = {'version': VERSION, 'date': target_day,
              'created_at': created_at or datetime.now(timezone.utc).isoformat(),
              'kind': 'prospective', 'policy': POLICY, 'models': {}}
    for model in layout_on(config, target_day):
        model_id = model['model_id']
        rows = [r for r in records if r['model_id'] == model_id
                and r['number'] in model['numbers'] and cutoff <= r['date'] < target_day]
        days = sorted({r['date'] for r in rows}, reverse=True)[:7]
        out = {'status': 'insufficient_history', 'history_days': len(days),
               'latest_source_date': days[0] if days else None,
               'selection': choose_strategy(evaluations, model_id, target_day),
               'strategies': {}, 'rankings': {}, 'eligible_numbers': []}
        result['models'][model_id] = out
        if len(days) < POLICY['min_history_days']:
            continue
        if (target - date.fromisoformat(days[0])).days > POLICY['max_source_age_days']:
            out['status'] = 'stale_data'
            continue
        usable = [r for r in rows if r['date'] in days and valid_record(r)]
        pool_games = sum(r['games'] for r in usable)
        pool_rb = sum(r['rb'] for r in usable)
        pool_rate = pool_rb / pool_games if pool_games else 0
        features = []
        for number in model['numbers']:
            history = sorted([r for r in usable if r['number'] == number
                              and r['games'] >= POLICY['min_daily_games']],
                             key=lambda r: r['date'], reverse=True)
            if len(history) < 3 or history[0]['date'] != days[0]:
                continue
            games = sum(r['games'] for r in history)
            if games < POLICY['min_total_games']:
                continue
            rb = sum(r['rb'] for r in history)
            dip3 = sum(r['difference'] for r in history[:3])
            # These are experimental priority points, never probabilities.
            dip_score = min(1, max(0, -dip3 / 4000))
            rb_rate = (rb + 5000 * pool_rate) / (games + 5000)
            rb_score = min(1, max(0, 0.5 + 2 * (rb_rate / pool_rate - 1))) if pool_rate else 0
            support = min(1, games / 30000)
            features.append({'number': number, 'history_days': len(history),
                             'latest_date': history[0]['date'],
                             'latest_games': history[0]['games'],
                             'latest_difference': history[0]['difference'],
                             'three_day_difference': dip3, 'history_games': games,
                             'history_rb': rb, 'rb_denominator': round(games/rb, 1) if rb else None,
                             '_components': (dip_score, rb_score, support)})
        if not features:
            out['status'] = 'insufficient_eligible_machines'
            continue
        out['status'] = 'ready'
        out['eligible_numbers'] = sorted(r['number'] for r in features)
        for strategy, weights in WEIGHTS.items():
            ranked = [{**{k:v for k,v in row.items() if k != '_components'},
                       'score': round(100 * sum(w*x for w,x in zip(weights, row['_components'])), 2)}
                      for row in features]
            ordered = sorted(ranked, key=lambda r:(-r['score'],r['number']))
            out['rankings'][strategy] = ordered
            out['strategies'][strategy] = ordered[:3]  # up to three eligible candidates
    return result


def snapshot_id(snapshot):
    body = {k:v for k,v in snapshot.items() if k != 'snapshot_id'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save_snapshot(path, snapshot):
    """Exclusive creation: a real pre-opening forecast is never rewritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {**snapshot, 'snapshot_id': snapshot_id(snapshot)}
    with path.open('x', encoding='utf-8') as stream:
        json.dump(out, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return out


def evaluate(snapshot, records):
    if snapshot.get('snapshot_id') and snapshot_id(snapshot) != snapshot['snapshot_id']:
        raise ValueError('Forecast snapshot integrity mismatch')
    index = record_index(records)
    out = {'version': snapshot['version'], 'kind': snapshot['kind'],
           'date': snapshot['date'], 'snapshot_id': snapshot.get('snapshot_id'),
           'models': {}}
    for model_id, forecast in snapshot['models'].items():
        item = {'status': 'no_prediction', 'strategies': {}}
        out['models'][model_id] = item
        if forecast['status'] != 'ready':
            continue
        actual = {number: index.get((snapshot['date'], model_id, number))
                  for number in forecast['eligible_numbers']}
        selected = forecast['selection']['strategy']
        candidates = forecast.get('rankings', {}).get(selected, forecast['strategies'][selected])
        item['selected_strategy'] = selected
        item['prediction_results'] = []
        for rank, candidate in enumerate(candidates, 1):
            row = actual.get(candidate['number'])
            available = bool(row and valid_record(row))
            item['prediction_results'].append({
                'rank': rank, 'number': candidate['number'], 'score': candidate.get('score'),
                'status': 'available' if available else 'pending_results',
                'actual': {k:row[k] for k in ('games','bb','rb','difference','source_url') if k in row}
                          if available else None})
        if not actual or any(not row or not valid_record(row) for row in actual.values()):
            item['status'] = 'pending_results'
            continue
        baseline = mean(row['difference'] for row in actual.values())
        item.update(status='complete', eligible_mean_difference=round(baseline,2),
                    selected_strategy=forecast['selection']['strategy'])
        for strategy, candidates in forecast['strategies'].items():
            rows = [actual[r['number']] for r in candidates]
            average = mean(r['difference'] for r in rows)
            item['strategies'][strategy] = {
                'count': len(rows), 'positive_count': sum(r['difference'] > 0 for r in rows),
                'positive_rate': sum(r['difference'] > 0 for r in rows)/len(rows),
                'mean_difference': round(average,2),
                'lift_vs_eligible_mean': round(average-baseline,2),
                'low_play_count': sum(r['games'] < 3000 for r in rows),
                'results': [{k:r[k] for k in ('number','games','bb','rb','difference','source_url')
                             if k in r} for r in rows]}
    out['status'] = ('pending' if any(m['status'] == 'pending_results'
                                    for m in out['models'].values()) else 'complete')
    return out


def run(base=BASE, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Timezone-aware execution time required')
    config = json.loads((base/'machines.json').read_text(encoding='utf-8'))
    data = json.loads((base/'data.json').read_text(encoding='utf-8'))
    records = data.get('machine_records', [])
    local = now.astimezone(ZoneInfo(config['timezone']))
    today = str(local.date())
    forecast_root = base/'history'/'forecasts'
    evaluation_root = base/'history'/'evaluations'
    evaluations = []
    for path in sorted(forecast_root.glob('*.json')):
        snap = json.loads(path.read_text(encoding='utf-8'))
        if snapshot_id(snap) != snap.get('snapshot_id'):
            raise ValueError('Archived forecast integrity mismatch')
        if snap['date'] >= today:
            continue
        result_path = evaluation_root/path.name
        old = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else None
        if old and old.get('snapshot_id') != snap['snapshot_id']:
            raise ValueError('Evaluation references a different forecast')
        if old and old.get('status') == 'complete':
            evaluation = old
        else:
            evaluation = evaluate(snap, records)
            if evaluation != old:
                write_json(result_path, evaluation)
        evaluations.append(evaluation)
    # At/after 23:00, same-day published data may settle an existing morning snapshot.
    same_day = forecast_root/(today+'.json')
    if local.hour >= 23 and same_day.exists():
        snap = json.loads(same_day.read_text(encoding='utf-8'))
        if snapshot_id(snap) != snap.get('snapshot_id'):
            raise ValueError('Same-day forecast integrity mismatch')
        result_path = evaluation_root/(today+'.json')
        old = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else None
        if old and old.get('snapshot_id') != snap['snapshot_id']:
            raise ValueError('Same-day evaluation references a different forecast')
        evaluation = old if old and old.get('status') == 'complete' else evaluate(snap, records)
        if evaluation != old:
            write_json(result_path, evaluation)
        evaluations.append(evaluation)
    before_deadline = (POLICY['forecast_lock_from_jst_hour'] <= local.hour
                       < POLICY['forecast_lock_before_jst_hour'])
    show_locked_today = same_day.exists() and local.hour < 23
    target = today if local.hour < POLICY['forecast_lock_before_jst_hour'] or show_locked_today else str(local.date()+timedelta(days=1))
    live_path = forecast_root/(target+'.json')
    if before_deadline or show_locked_today:
        if live_path.exists():
            forecast = json.loads(live_path.read_text(encoding='utf-8'))
            if snapshot_id(forecast) != forecast['snapshot_id']:
                raise ValueError('Existing forecast integrity mismatch')
        else:
            forecast = save_snapshot(live_path, make_forecast(
                config, records, target, evaluations, now.isoformat()))
        forecast['display_status'] = 'locked'
        forecast['delivery'] = {'deadline_jst': target+'T07:00:00+09:00',
            'generated_before_deadline': datetime.fromisoformat(forecast['created_at']).astimezone(
                ZoneInfo(config['timezone'])).hour < 7}
    else:
        forecast = make_forecast(config, records, target, evaluations, now.isoformat())
        forecast['display_status'] = 'preview'
    # Retrospective replay is explicitly separate and never changes strategy selection.
    replay = []
    for day in sorted({r['date'] for r in records})[-14:]:
        if day >= today:
            continue
        snap = make_forecast(config, records, day, (), now.isoformat())
        snap['kind'] = 'retrospective'
        result = evaluate(snap, records)
        if any(m['status'] == 'complete' for m in result['models'].values()):
            replay.append(result)
    data['forecast'] = forecast
    data['evaluation'] = {'policy_version': VERSION,
                          'prospective': evaluations[-60:], 'retrospective': replay,
                          'note': 'Positive difference is an outcome proxy, not proof of a high setting.'}
    write_json(base/'data.json', data)
    print(json.dumps({'forecast_date':target, 'status':forecast['display_status'],
                      'ready_models':[m for m,v in forecast['models'].items() if v['status']=='ready'],
                      'prospective_days':len(evaluations), 'retrospective_days':len(replay)}, ensure_ascii=False))
    return data


if __name__ == '__main__':
    run()
