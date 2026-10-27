"""Bound collection time and record failures without discarding saved facts."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from collect_sources import BASE, write_json


def run(base=BASE, runner=subprocess.run, backfill_only=False):
    started = datetime.now(timezone.utc)
    failure = None
    try:
        runner([sys.executable, str(base/'collect_machines.py')]+(['--backfill-only'] if backfill_only else []), cwd=base,
               timeout=240, check=True)
    except subprocess.TimeoutExpired:
        failure = 'Collection exceeded 240 seconds; saved records retained'
    except (subprocess.CalledProcessError, OSError) as exc:
        failure = f'Collection process failed: {exc}'[:400]
    # Read AFTER process exit: never overwrite facts already saved by the child.
    data = json.loads((base/'data.json').read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Refusing to overwrite invalid data.json')
    result_key='history_backfill' if backfill_only else 'machine_collection'
    if failure:
        previous = data.get(result_key, {})
        data[result_key] = {'attempted_at':started.isoformat(),
            'status':'error', 'reason':failure, 'models':{},
            'using_saved_records':True,
            'previous_attempt':{k:v for k,v in previous.items() if k != 'previous_attempt'}}
        write_json(base/'data.json', data)
    result = data.get(result_key, {})
    finished = datetime.now(timezone.utc)
    config = json.loads((base/'machines.json').read_text(encoding='utf-8'))
    day = str(started.astimezone(ZoneInfo(config['timezone'])).date())
    stamp = started.strftime('%H%M%S-%fZ')
    path = base/'history'/'collection-runs'/day/(stamp+'.json')
    evidence = {'started_at':started.isoformat(), 'finished_at':finished.isoformat(),
                'mode':'history_backfill' if backfill_only else 'daily',
                'process_failed':bool(failure), 'result':result,
                'saved_record_count':len(data.get('machine_records', []))}
    if path.exists():
        raise FileExistsError('Refusing to overwrite a collection-run record')
    write_json(path, evidence)
    print(json.dumps({'collection_status':result.get('status'),
                      'using_saved_records':bool(failure)},ensure_ascii=False))
    return evidence


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--backfill-only',action='store_true')
    run(backfill_only=parser.parse_args().backfill_only)
