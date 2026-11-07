import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from forecast_engine import make_forecast, record_index
from myj_rank_research import rankings, summarize


class MyjRankResearchTests(unittest.TestCase):
    def test_independent_variants_keep_public_top_three_and_ignore_target_results(self):
        day = datetime(2026, 11, 7, 5, tzinfo=ZoneInfo('Asia/Tokyo'))
        numbers = list(range(2201, 2212))
        config = {'models': [{'id': 'myj6', 'name': 'VI', 'installations': [
            {'from': None, 'until': None, 'numbers': numbers}]}]}
        records = []
        for lag in range(7):
            for n in numbers:
                games, rb, difference = 5000, 16, -400
                if lag == 1 and n == 2210:
                    games, rb = 1000, 2
                if lag == 1 and n == 2211:
                    difference = 2000
                records.append({'date': str((day - timedelta(days=lag)).date()), 'number': n,
                                'model_id': 'myj6', 'games': games, 'bb': 18, 'rb': rb,
                                'difference': difference})
        forecast = make_forecast(config, records, str(day.date()))
        variants = rankings(forecast, config, records)
        self.assertEqual(variants, rankings(forecast, config, [r for r in records if r['date'] < str(day.date())]))
        variants = variants['myj6']
        self.assertEqual(variants['extra_numbers'], [2210])
        self.assertEqual(variants['baseline'][:3], variants['penalty'][:3])
        self.assertEqual(variants['baseline'][:3], variants['low_play'][:3])
        old = next(r['score'] for r in variants['baseline'] if r['number'] == 2211)
        new = next(r['score'] for r in variants['penalty'] if r['number'] == 2211)
        self.assertAlmostEqual(old - new, 10)
        self.assertIn(2210, [r['number'] for r in variants['low_play']])

        snapshot = {'date': str(day.date()), 'models': {'myj6': variants}}
        self.assertEqual(summarize(iter([snapshot]), record_index(records), config, day)['myj6']['settled_days'], 0)
        night = day.replace(hour=23, minute=30)
        report = summarize(iter([snapshot]), record_index(records), config, night)['myj6']
        self.assertEqual(report['paired_4_to_10']['low_play']['count'], 7)
        self.assertEqual(report['low_play_added_in_top10']['count'], 1)
        self.assertEqual(report['by_rank']['baseline'][10]['lift_vs_all'], 0)
