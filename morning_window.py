"""Dated JST cutoff; never relax the validity of historical forecasts."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

EXTENDED_FROM = '2026-11-04'

def morning_deadline(day):
    day = str(day)
    cutoff = time(8, 30) if day >= EXTENDED_FROM else time(7)
    return datetime.combine(datetime.fromisoformat(day).date(), cutoff, ZoneInfo('Asia/Tokyo'))

def before_morning_deadline(moment):
    if moment.tzinfo is None:
        raise ValueError('Timezone-aware timestamp required')
    local = moment.astimezone(ZoneInfo('Asia/Tokyo'))
    return local < morning_deadline(local.date())

def in_morning_window(moment):
    local = moment.astimezone(ZoneInfo('Asia/Tokyo'))
    return local.hour >= 5 and before_morning_deadline(moment)
