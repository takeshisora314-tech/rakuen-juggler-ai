"""Record explicit evening settlement state without rewriting morning forecasts."""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from collect_sources import BASE, layout_on, write_json
from forecast_engine import VERSION, evaluate, snapshot_id


def answer_status(config, records, snapshot, day, checked_at):
    models = {m['model_id']: {'status': 'no_prediction'} for m in layout_on(config, day)}
    result = {'schema_version': 1, 'policy_version': VERSION, 'date': day,
              'checked_at': checked_at, 'snapshot_id': None, 'models': models,
              'predicted_models': 0, 'complete_models': 0, 'pending_models': 0,
              'abstained_models': len(models), 'status': 'missing_forecast'}
    if snapshot is None:
        return result
    if (snapshot.get('date') != day or snapshot.get('kind') != 'prospective'
            or snapshot.get('version') != VERSION
            or snapshot.get('snapshot_id') != snapshot_id(snapshot)):
        raise ValueError('Answer check requires an intact dated morning forecast')
    created = datetime.fromisoformat(snapshot['created_at'])
    if created.tzinfo is None:
        raise ValueError('Forecast time must have timezone')
    local = created.astimezone(ZoneInfo(config['timezone']))
    if str(local.date()) != day or local.hour >= 7:
        raise ValueError('Forecast was not saved before its morning deadline')
    evaluation = evaluate(snapshot, records)
    for model_id in models:
        model = evaluation['models'].get(model_id, {})
        models[model_id]['status'] = model.get('status', 'no_prediction')
    predicted = sum(m['status'] != 'no_prediction' for m in models.values())
    complete = sum(m['status'] == 'complete' for m in models.values())
    pending = predicted - complete
    result.update(snapshot_id=snapshot['snapshot_id'], predicted_models=predicted,
                  complete_models=complete, pending_models=pending,
                  abstained_models=len(models) - predicted,
                  status=('no_predictions' if not predicted else 'complete' if not pending
                          else 'partial_results' if complete else 'pending_results'))
    return result


def run(base=BASE, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Timezone-aware execution time required')
    config = json.loads((base / 'machines.json').read_text())
    data = json.loads((base / 'data.json').read_text())
    local = now.astimezone(ZoneInfo(config['timezone']))
    day = str(local.date() if local.hour >= 23 else local.date() - timedelta(days=1))
    path = base / 'history/forecasts' / (day + '.json')
    snapshot = json.loads(path.read_text()) if path.exists() else None
    result = answer_status(config, data.get('machine_records', []), snapshot, day, now.isoformat())
    write_json(base / 'answer_status.json', result)
    print(json.dumps({'answer_date': day, 'answer_status': result['status'],
                      'complete_models': result['complete_models'],
                      'pending_models': result['pending_models']}, ensure_ascii=False))
    return result


if __name__ == '__main__':
    run()
