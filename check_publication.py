"""Observe the public Pages payload; generation time is NOT publication proof."""
import json
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import requests
from collect_sources import BASE, layout_on, write_json
from forecast_engine import snapshot_id

PUBLIC_URL = 'https://takeshisora314-tech.github.io/rakuen-juggler-ai/data.json'
JST = ZoneInfo('Asia/Tokyo')


def aware(value):
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError('Timezone-aware timestamp required')
    return moment


def observe(config, payload, now, previous=None, error=None):
    if now.tzinfo is None:
        raise ValueError('Timezone-aware observation required')
    today = now.astimezone(JST).date()
    deadline = datetime.combine(today, time(7), JST)
    previous = previous or {}
    out = {'schema_version': 1, 'date': str(today), 'checked_at': now.isoformat(),
           'public_url': PUBLIC_URL, 'deadline_jst': deadline.isoformat(),
           'status': 'unreachable' if error else 'missing_forecast',
           'deadline_status': 'not_yet_due' if now < deadline else 'unverified',
           'snapshot_id': None, 'evidence': {}, 'ready_models': [],
           'abstained_models': [], 'require_attention': False,
           'note': 'Observed public JSON availability, not Safari rendering or setting accuracy.'}
    # Retain only previously observed proof for this day and this exact public URL.
    if previous.get('date') == str(today) and previous.get('public_url') == PUBLIC_URL:
        for key, stamp in previous.get('evidence', {}).items():
            try:
                seen = aware(stamp)
                if seen <= now and seen.astimezone(JST).date() == today:
                    out['evidence'][key] = stamp
            except (ValueError, TypeError):
                continue
    if error:
        out['reason'] = str(error)[:300]
    else:
        try:
            if not isinstance(payload, dict):
                raise ValueError('Public payload is not an object')
            forecast = payload.get('forecast') or {}
            out['data_updated_at'] = payload.get('updated_at')
            out['collection_status'] = (payload.get('machine_collection') or {}).get('status')
            if forecast.get('date') == str(today) and forecast.get('display_status') == 'locked':
                original = {k:v for k,v in forecast.items() if k not in ('display_status', 'delivery')}
                if not forecast.get('snapshot_id') or snapshot_id(original) != forecast['snapshot_id']:
                    raise ValueError('Public forecast hash mismatch')
                created = aware(forecast['created_at'])
                if created > now or created.astimezone(JST).date() != today:
                    raise ValueError('Public forecast generation date is inconsistent')
                expected = {m['model_id'] for m in layout_on(config, today)}
                if set(forecast.get('models', {})) != expected:
                    raise ValueError('Public forecast model coverage mismatch')
                key = forecast['snapshot_id']
                out['snapshot_id'] = key
                out['created_at'] = forecast['created_at']
                out['evidence'].setdefault(key, now.isoformat())
                out['first_observed_at'] = out['evidence'][key]
                out['ready_models'] = [k for k,v in forecast['models'].items() if v.get('status') == 'ready']
                out['abstained_models'] = [k for k,v in forecast['models'].items() if v.get('status') != 'ready']
                if created >= deadline:
                    out.update(status='late_generated', deadline_status='missed')
                elif aware(out['first_observed_at']) < deadline:
                    out.update(status='available', deadline_status='verified_on_time')
                else:
                    out['status'] = 'available'
                    # Never infer on-time deployment from a pre-07:00 created_at.
                    out['deadline_status'] = 'unverified'
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            out.update(status='invalid_payload', reason=str(exc)[:300], snapshot_id=None)
    if now >= deadline and out['status'] != 'available':
        out['require_attention'] = True
    return out


def fetch_public():
    response = requests.get(PUBLIC_URL, timeout=(10,25), allow_redirects=False,
                            headers={'Cache-Control':'no-cache', 'User-Agent':'RakuenJugglerAI-publication-check'})
    if response.status_code != 200:
        raise ValueError(f'Public payload HTTP {response.status_code}')
    return response.json()


def run(base=BASE, now=None, fetcher=fetch_public):
    now = now or datetime.now(timezone.utc)
    config = json.loads((base/'machines.json').read_text(encoding='utf-8'))
    status_path = base/'publication_status.json'
    previous = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else None
    try:
        payload, error = fetcher(), None
    except (requests.RequestException, ValueError) as exc:
        payload, error = None, exc
    status = observe(config, payload, now, previous, error)
    stamp = now.astimezone(timezone.utc).strftime('%H%M%S-%fZ')
    history = base/'history'/'publication-checks'/status['date']/(stamp+'.json')
    if history.exists():
        raise FileExistsError('Refusing to overwrite an existing publication observation')
    write_json(history, status)
    write_json(status_path, status)
    print(json.dumps({k:status[k] for k in ('date','status','deadline_status','require_attention')},ensure_ascii=False))
    return status


if __name__ == '__main__':
    run()
