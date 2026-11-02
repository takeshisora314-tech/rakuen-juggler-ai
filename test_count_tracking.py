import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from test_count_models import CountReplayTests
from track_count_predictions import freeze,score,summarize_validation


class CountTrackingTests(unittest.TestCase):
    def test_validation_excludes_pending_and_same_day_and_separates_weighting(self):
        def evaluation(day, n, gain, status='complete'):
            return {'date':day,'models':{'myj5':{'status':status,'scored':n,'excluded':1,
                'mean_log_scores':{'equal':-10,'low_heavy':-11,'high_heavy':-9,
                                   'rolling_mixture':-10+gain}}}}
        items=[evaluation('2026-10-29',1,2),evaluation('2026-10-30',9,-1),
               evaluation('2026-10-31',8,99,'pending_results'),evaluation('2026-11-01',10,99)]
        result=summarize_validation(items,'2026-11-01')
        m=result['models']['myj5']; r=m['methods']['rolling_mixture']
        self.assertEqual((m['completed_days'],m['scored_rows'],m['excluded_rows']),(2,10,2))
        self.assertEqual(m['days_remaining_to_minimum'],28)
        self.assertEqual(r['mean_daily_gain_vs_equal'],.5)
        self.assertAlmostEqual(r['mean_row_gain_vs_equal'],-.7)
        self.assertEqual((r['days_above_equal'],r['days_below_equal']),(1,1))
        self.assertFalse(result['changes_live_strategy'])
        with self.assertRaises(ValueError):summarize_validation(items+items,'2026-11-01')

    def test_validation_does_not_promote_at_thirty_days(self):
        from datetime import date,timedelta
        items=[{'date':str(date(2026,9,1)+timedelta(days=i)), 'models':{'myj5':{
            'status':'complete','scored':1,'excluded':0,
            'mean_log_scores':dict.fromkeys(('equal','low_heavy','high_heavy','rolling_mixture'),-5)}}} for i in range(30)]
        report=summarize_validation(items,'2026-11-01')
        self.assertEqual(report['models']['myj5']['validation_status'],'minimum_sample_reached_review_required')
        self.assertFalse(report['changes_live_strategy'])

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
