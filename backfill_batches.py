"""Bounded sequential history batches; never overlap the morning forecast window."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from run_collection import run


def run_batches(limit=2, collect=run, save=lambda:None, clock=None, pause=time.sleep):
    if type(limit) is not int or limit not in (2,4,6):
        raise ValueError('Batch limit must be 2, 4 or 6')
    clock=clock or (lambda:datetime.now(ZoneInfo('Asia/Tokyo')))
    completed=[]
    for batch in range(limit):
        now=clock()
        if now.tzinfo is None:
            raise ValueError('Timezone-aware clock required')
        if 4 <= now.astimezone(ZoneInfo('Asia/Tokyo')).hour < 7:
            print('Paused history backfill for morning forecast window')
            break
        evidence=collect(backfill_only=True)
        save()  # Commit each saved batch before any next source request.
        completed.append(evidence)
        result=evidence['result']
        progressed=any(item.get('status') in ('complete','partial')
                       for item in result.get('backfill',{}).values())
        if evidence['process_failed'] or result.get('status') in ('blocked','error') or not progressed:
            break
        if batch+1 < limit:
            pause(10)
    return completed
