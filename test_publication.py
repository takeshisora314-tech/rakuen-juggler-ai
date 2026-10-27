import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from check_publication import observe, run
from collect_sources import write_json
from forecast_engine import make_forecast, snapshot_id


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.config={'timezone':'Asia/Tokyo','models':[{'id':'myj5','name':'V',
          'installations':[{'from':None,'until':None,'numbers':[2221,2222,2223]}]}]}
        forecast=make_forecast(self.config,[],'2026-10-28',created_at='2026-10-27T20:00:00+00:00')
        forecast['snapshot_id']=snapshot_id(forecast)
        forecast['display_status']='locked'
        forecast['delivery']={'generated_before_deadline':True}
        self.payload={'forecast':forecast,'machine_collection':{'status':'partial'}}
        self.early=datetime(2026,10,27,21,45,tzinfo=timezone.utc)  # 06:45 JST
        self.late=datetime(2026,10,27,22,5,tzinfo=timezone.utc)

    def test_before_deadline_requires_actual_public_observation(self):
        out=observe(self.config,self.payload,self.early)
        self.assertEqual(out['deadline_status'],'verified_on_time')
        self.assertEqual(out['abstained_models'],['myj5'])
        self.assertEqual(out['ready_models'],[])

    def test_early_generation_alone_does_not_prove_early_publication(self):
        out=observe(self.config,self.payload,self.late)
        self.assertEqual(out['status'],'available')
        self.assertEqual(out['deadline_status'],'unverified')
        self.assertFalse(out['require_attention'])

    def test_same_snapshot_preserves_earliest_observation(self):
        first=observe(self.config,self.payload,self.early)
        later=observe(self.config,self.payload,self.late,first)
        self.assertEqual(later['deadline_status'],'verified_on_time')
        self.assertEqual(later['first_observed_at'],self.early.isoformat())

    def test_different_snapshot_cannot_borrow_early_evidence(self):
        old=observe(self.config,self.payload,self.early)
        f=self.payload['forecast']
        f.pop('snapshot_id');f.pop('display_status');f.pop('delivery')
        f['created_at']='2026-10-27T20:01:00+00:00'
        f['snapshot_id']=snapshot_id(f);f['display_status']='locked'
        self.assertEqual(observe(self.config,self.payload,self.late,old)['deadline_status'],'unverified')

    def test_tampered_payload_is_rejected(self):
        self.payload['forecast']['models']['myj5']['status']='ready'
        self.assertEqual(observe(self.config,self.payload,self.late)['status'],'invalid_payload')

    def test_missing_or_preview_is_not_a_published_daily_forecast(self):
        for value in ({},{'forecast':{**self.payload['forecast'],'display_status':'preview'}}):
            self.assertTrue(observe(self.config,value,self.late)['require_attention'])
            self.assertFalse(observe(self.config,value,self.early)['require_attention'])

    def test_boundary_observation_is_not_before_seven(self):
        out=observe(self.config,self.payload,datetime(2026,10,27,22,tzinfo=timezone.utc))
        self.assertEqual(out['deadline_status'],'unverified')

    def test_future_evidence_is_ignored(self):
        first=observe(self.config,self.payload,self.early)
        first['evidence'][first['snapshot_id']]='2026-10-29T00:00:00+00:00'
        self.assertEqual(observe(self.config,self.payload,self.late,first)['deadline_status'],'unverified')

    def test_late_generation_cannot_become_on_time(self):
        forecast=make_forecast(self.config,[],'2026-10-28',created_at='2026-10-27T22:01:00+00:00')
        forecast['snapshot_id']=snapshot_id(forecast);forecast['display_status']='locked'
        out=observe(self.config,{'forecast':forecast},self.late)
        self.assertEqual(out['status'],'late_generated')
        self.assertTrue(out['require_attention'])

    def test_network_error_is_recorded_without_replacing_forecasts(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);write_json(base/'machines.json',self.config)
            write_json(base/'data.json',self.payload)
            before=(base/'data.json').read_bytes()
            def failure(): raise ValueError('HTTP 503')
            out=run(base,self.late,failure)
            self.assertEqual(out['status'],'unreachable')
            self.assertEqual((base/'data.json').read_bytes(),before)
            self.assertEqual(len(list((base/'history'/'publication-checks').rglob('*.json'))),1)

    def test_no_overwrite_of_observations(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);write_json(base/'machines.json',self.config)
            run(base,self.early,lambda:self.payload)
            with self.assertRaises(FileExistsError): run(base,self.early,lambda:self.payload)

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError): observe(self.config,self.payload,datetime(2026,10,28))


if __name__=='__main__': unittest.main()
