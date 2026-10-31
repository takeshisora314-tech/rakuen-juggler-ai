import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from test_count_models import CountReplayTests
from track_count_predictions import freeze,score


class CountTrackingTests(unittest.TestCase):
    def setUp(self):
        fixture=CountReplayTests();fixture.setUp()
        self.config,self.rows=fixture.config,fixture.rows

    def test_no_late_creation_and_no_snapshot_overwrite(self):
        with TemporaryDirectory() as td:
            base=Path(td);(base/'data.json').write_text(json.dumps({'machine_records':self.rows}))
            self.assertIsNone(freeze(base,self.config,self.rows,datetime.fromisoformat('2026-10-25T17:00:00+09:00')))
            morning=freeze(base,self.config,self.rows,datetime.fromisoformat('2026-10-25T05:03:00+09:00'))
            self.assertEqual(morning,freeze(base,self.config,[],datetime.fromisoformat('2026-10-25T23:30:00+09:00')))
            self.assertLess(morning['models']['myj5']['trained_through'],'2026-10-25')
            pending=score(morning,self.rows,self.config)['models']['myj5']
            self.assertEqual((pending['pending'],pending['scored']),(8,0))
            actual=[{**r,'date':'2026-10-25'} for r in self.rows if r['date']=='2026-10-24']
            complete=score(morning,self.rows+actual,self.config)['models']['myj5']
            self.assertEqual((complete['status'],complete['scored']),('complete',8))
            self.assertEqual(len(complete['mean_log_scores']),4)
            morning['models']['myj5']['weights'][0]=1
            with self.assertRaises(ValueError):score(morning,self.rows,self.config)
