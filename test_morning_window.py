import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from collect_sources import write_json
from forecast_engine import run
from morning_window import in_morning_window, morning_deadline
from check_answers import answer_status
from rank_comparison import validate

class MorningDeadlineTests(unittest.TestCase):
    def test_dated_boundary_including_utc(self):
        for stamp, expected in [('2026-11-03T07:00:00+09:00',False),
                                ('2026-11-04T07:00:00+09:00',True),
                                ('2026-11-04T08:29:59+09:00',True),
                                ('2026-11-03T23:29:59+00:00',True),
                                ('2026-11-04T08:30:00+09:00',False),
                                ('2026-11-04T04:59:59+09:00',False)]:
            with self.subTest(stamp=stamp):
                self.assertEqual(in_morning_window(datetime.fromisoformat(stamp)),expected)
        self.assertEqual(morning_deadline('2026-11-03').hour,7)

    def setup_base(self, base):
        config={'timezone':'Asia/Tokyo','models':[{'id':'myj5','name':'V',
                'installations':[{'from':None,'until':None,'numbers':[2201,2202,2203]}]}]}
        rows=[{'date':day,'model_id':'myj5','number':n,'games':5000,'bb':20,'rb':22,
               'difference':500,'source_url':'https://min-repo.com/example/'}
              for day in ('2026-11-01','2026-11-02','2026-11-03') for n in (2201,2202,2203)]
        write_json(base/'machines.json',config)
        write_json(base/'data.json',{'machine_records':rows})
        return config,rows

    def test_delayed_results_capture_pair_and_remain_immutable(self):
        with TemporaryDirectory() as d:
            base=Path(d);config,rows=self.setup_base(base)
            write_json(base/'data.json',{'machine_records':rows[:-1]})
            self.assertEqual(run(base,datetime.fromisoformat('2026-11-04T07:33:00+09:00'))['forecast']['display_status'],'waiting_for_results')
            write_json(base/'data.json',{'machine_records':rows})
            result=run(base,datetime.fromisoformat('2026-11-04T08:29:59+09:00'))
            live=base/'history/forecasts/2026-11-04.json'
            pair=base/'history/rank-comparison/forecasts/2026-11-04.json'
            self.assertTrue(live.exists());validate(json.loads(pair.read_text()))
            self.assertEqual(result['forecast']['delivery']['deadline_jst'],'2026-11-04T08:30:00+09:00')
            self.assertTrue(result['forecast']['delivery']['generated_before_deadline'])
            before=(live.read_bytes(),pair.read_bytes())
            run(base,datetime.fromisoformat('2026-11-04T09:00:00+09:00'))
            self.assertEqual((live.read_bytes(),pair.read_bytes()),before)
            # Settlement accepts the new dated window; no target-day results => pending.
            status=answer_status(config,rows,json.loads(live.read_text()),'2026-11-04','2026-11-04T23:30:00+09:00')
            self.assertEqual(status['status'],'pending_results')

    def test_no_backfill_at_0830(self):
        with TemporaryDirectory() as d:
            base=Path(d);self.setup_base(base)
            run(base,datetime.fromisoformat('2026-11-04T08:30:00+09:00'))
            self.assertFalse((base/'history/forecasts/2026-11-04.json').exists())
            self.assertFalse((base/'history/rank-comparison/forecasts/2026-11-04.json').exists())
