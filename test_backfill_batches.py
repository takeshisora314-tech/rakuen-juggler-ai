import unittest
from datetime import datetime, timezone
from unittest.mock import Mock
from backfill_batches import run_batches


class BatchTests(unittest.TestCase):
    def good(self):
        return {'process_failed':False,'result':{'status':'partial','backfill':{'day':{'status':'complete'}}}}

    def execute(self,**kwargs):
        return run_batches(clock=lambda:datetime(2026,10,28,0,tzinfo=timezone.utc),**kwargs)

    def test_manual_six_batches_are_sequential_saved_and_paced(self):
        events=[]
        collect=Mock(side_effect=lambda **kwargs:(events.append('collect') or self.good()))
        save=Mock(side_effect=lambda:events.append('save'))
        pause=Mock(side_effect=lambda seconds:events.append(seconds))
        self.assertEqual(len(self.execute(limit=6,collect=collect,save=save,pause=pause)),6)
        self.assertEqual(events, ['collect','save',10]*5+['collect','save'])
        collect.assert_called_with(backfill_only=True)

    def test_scheduled_default_is_still_two_batches(self):
        collect=Mock(return_value=self.good())
        self.assertEqual(len(self.execute(collect=collect,pause=Mock())),2)

    def test_block_error_timeout_and_no_progress_stop_after_saving(self):
        for evidence in ({'process_failed':True,'result':{}},
                         {'process_failed':False,'result':{'status':'blocked'}},
                         {'process_failed':False,'result':{'status':'error'}},
                         {'process_failed':False,'result':{'status':'partial','backfill':{'day':{'status':'cached'}}}}):
            collect=Mock(return_value=evidence);save=Mock();pause=Mock()
            self.execute(limit=6,collect=collect,save=save,pause=pause)
            self.assertEqual(collect.call_count,1);save.assert_called_once();pause.assert_not_called()

    def test_four_to_seven_jst_window_does_not_start_collection(self):
        for hour in (19,20,21):  # UTC -> 04, 05, 06 JST next day
            collect=Mock();save=Mock()
            run_batches(6,collect,save,lambda:datetime(2026,10,27,hour,tzinfo=timezone.utc),Mock())
            collect.assert_not_called();save.assert_not_called()

    def test_crossing_into_morning_pauses_before_next_batch(self):
        clock=Mock(side_effect=[datetime(2026,10,27,18,59,tzinfo=timezone.utc),datetime(2026,10,27,19,tzinfo=timezone.utc)])
        collect=Mock(return_value=self.good())
        self.assertEqual(len(run_batches(6,collect,Mock(),clock,Mock())),1)

    def test_save_failure_stops_all_further_collection(self):
        collect=Mock(return_value=self.good())
        with self.assertRaises(PermissionError):
            self.execute(limit=6,collect=collect,save=Mock(side_effect=PermissionError('Push failed')),pause=Mock())
        self.assertEqual(collect.call_count,1)

    def test_invalid_limits_rejected_before_network(self):
        for limit in (True,0,1,7,'6'):
            collect=Mock()
            with self.assertRaises(ValueError):self.execute(limit=limit,collect=collect)
            collect.assert_not_called()


if __name__=='__main__':unittest.main()
