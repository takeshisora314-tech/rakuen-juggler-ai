import copy
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from collect_sources import write_json
from forecast_engine import (VERSION, WEIGHTS, evaluate, make_forecast,
                             choose_strategy, run, save_snapshot, snapshot_id)


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.config = {'timezone':'Asia/Tokyo', 'models':[{
            'id':'myj5', 'name':'マイジャグラーV',
            'installations':[{'from':None,'until':None,'numbers':[2201,2202,2203,2204]}]}]}
        self.rows = [self.row(day, n) for day in ('2026-10-24','2026-10-25','2026-10-26')
                     for n in (2201,2202,2203,2204)]

    def row(self, day, n):
        return {'date':day,'model_id':'myj5','number':n,'games':5000,
                'bb':20,'rb':20+n-2201,'difference':100*(n-2203),
                'source_url':'https://min-repo.com/3431462/'}

    def forecast(self, rows=None):
        return make_forecast(self.config, self.rows if rows is None else rows,
                             '2026-10-27', created_at='2026-10-26T20:00:00+00:00')

    def test_three_strategies_have_three_candidates(self):
        model = self.forecast()['models']['myj5']
        self.assertEqual(model['status'],'ready')
        self.assertEqual(set(model['strategies']),set(WEIGHTS))
        for candidates in model['strategies'].values():
            self.assertEqual(len(candidates),3)
            self.assertTrue(all(0<=r['score']<=100 for r in candidates))

    def test_future_results_cannot_change_forecast(self):
        future = [{**self.row('2026-10-27',n),'difference':99999} for n in range(2201,2205)]
        self.assertEqual(self.forecast()['models'],self.forecast(self.rows+future)['models'])

    def test_full_rankings_preserve_top_three_evaluation(self):
        model=self.forecast()['models']['myj5']
        for strategy in WEIGHTS:
            self.assertEqual(len(model['rankings'][strategy]),4)
            self.assertEqual(model['rankings'][strategy][:3],model['strategies'][strategy])

    def test_late_run_never_backdates_and_daytime_retains_locked_forecast(self):
        with TemporaryDirectory() as directory:
            base=Path(directory)
            write_json(base/'machines.json',self.config)
            write_json(base/'data.json',{'machine_records':self.rows})
            late=run(base,datetime(2026,10,26,22,tzinfo=timezone.utc))  # 07:00 JST
            self.assertEqual(late['forecast']['display_status'],'preview')
            self.assertFalse((base/'history'/'forecasts'/'2026-10-27.json').exists())
            run(base,datetime(2026,10,26,20,tzinfo=timezone.utc))
            path=base/'history'/'forecasts'/'2026-10-27.json'
            saved=path.read_bytes()
            daytime=run(base,datetime(2026,10,27,3,tzinfo=timezone.utc))
            self.assertEqual(daytime['forecast']['date'],'2026-10-27')
            self.assertEqual(daytime['forecast']['display_status'],'locked')
            self.assertEqual(path.read_bytes(),saved)

    def test_insufficient_history_abstains(self):
        result = self.forecast(self.rows[4:])['models']['myj5']
        self.assertEqual(result['status'],'insufficient_history')
        self.assertFalse(result['strategies'])

    def test_stale_history_abstains(self):
        snap=make_forecast(self.config,self.rows,'2026-10-30')
        self.assertEqual(snap['models']['myj5']['status'],'stale_data')

    def test_missing_counts_are_not_zero_filled(self):
        for r in self.rows: r['rb']=None
        self.assertEqual(self.forecast()['models']['myj5']['status'],'insufficient_eligible_machines')

    def test_low_games_excluded(self):
        for r in self.rows: r['games']=100
        self.assertNotEqual(self.forecast()['models']['myj5']['status'],'ready')

    def test_duplicate_records_rejected(self):
        with self.assertRaises(ValueError): self.forecast(self.rows+[self.rows[0]])

    def test_replacement_does_not_inherit_old_model(self):
        old=self.config['models'][0]
        old['installations'][0]['until']='2026-10-27'
        self.config['models'].append({'id':'myj6','name':'マイジャグラーVI',
            'installations':[{'from':'2026-10-27','until':None,'numbers':[2201,2202,2203,2204]}]})
        snap=self.forecast()
        self.assertNotIn('myj5',snap['models'])
        self.assertEqual(snap['models']['myj6']['status'],'insufficient_history')

    def test_pending_results_are_not_failures(self):
        result=evaluate(self.forecast(),self.rows)
        self.assertEqual(result['status'],'pending')
        self.assertEqual(result['models']['myj5']['status'],'pending_results')

    def test_evaluation_uses_exact_business_day(self):
        result=evaluate(self.forecast(),self.rows+[self.row('2026-10-27',n) for n in range(2201,2205)])
        self.assertEqual(result['status'],'complete')
        item=result['models']['myj5']
        self.assertEqual(item['eligible_mean_difference'],-50)
        metrics=item['strategies']['balanced']
        self.assertEqual(metrics['count'],3)
        self.assertEqual(metrics['mean_difference'],round(sum(r['difference'] for r in metrics['results'])/3,2))

    def test_missing_actual_keeps_entire_comparison_pending(self):
        rows=[self.row('2026-10-27',n) for n in range(2201,2204)]
        self.assertEqual(evaluate(self.forecast(),rows)['status'],'pending')

    def test_snapshot_is_write_once_and_hash_checked(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'forecast.json'
            snapshot=save_snapshot(path,self.forecast())
            original=path.read_bytes()
            with self.assertRaises(FileExistsError): save_snapshot(path,self.forecast())
            self.assertEqual(path.read_bytes(),original)
            snapshot['date']='2026-10-28'
            with self.assertRaises(ValueError): evaluate(snapshot,self.rows)

    def paired(self, count, kind='prospective', gain=200):
        return [{'date':str(date(2026,9,1)+timedelta(days=i)), 'kind':kind,'version':VERSION,
                 'models':{'myj5':{'status':'complete','strategies':{
                     s:{'lift_vs_eligible_mean':gain if s=='dip' else 0,'positive_rate':0.5}
                     for s in WEIGHTS}}}} for i in range(count)]

    def test_no_daily_chasing_with_small_sample(self):
        self.assertEqual(choose_strategy(self.paired(29),'myj5','2026-10-27')['strategy'],'balanced')

    def test_only_prospective_comparisons_can_switch(self):
        retrospective=choose_strategy(self.paired(35,'retrospective'),'myj5','2026-10-27')
        self.assertEqual(retrospective['paired_days'],0)
        prospective=choose_strategy(self.paired(30),'myj5','2026-10-27')
        self.assertEqual(prospective['strategy'],'dip')
        self.assertEqual(prospective['status'],'switched_by_rule')

    def test_small_gain_cannot_switch(self):
        self.assertEqual(choose_strategy(self.paired(30,gain=50),'myj5','2026-10-27')['strategy'],'balanced')

    def test_future_evaluations_cannot_select_strategy(self):
        self.assertEqual(choose_strategy(self.paired(30),'myj5','2026-09-02')['paired_days'],1)

    def test_preview_is_not_archived_and_morning_forecast_is_immutable(self):
        with TemporaryDirectory() as directory:
            base=Path(directory)
            write_json(base/'machines.json',self.config)
            write_json(base/'data.json',{'machine_records':self.rows,'keep':'untouched'})
            preview=run(base,datetime(2026,10,26,12,tzinfo=timezone.utc))
            self.assertEqual(preview['forecast']['display_status'],'preview')
            self.assertFalse((base/'history'/'forecasts'/'2026-10-27.json').exists())
            morning=datetime(2026,10,26,20,tzinfo=timezone.utc)
            locked=run(base,morning)
            path=base/'history'/'forecasts'/'2026-10-27.json'
            original=path.read_bytes()
            again=run(base,morning+timedelta(hours=1))
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(again['forecast']['snapshot_id'],locked['forecast']['snapshot_id'])
            night=run(base,datetime(2026,10,27,14,tzinfo=timezone.utc))
            self.assertEqual(night['evaluation']['prospective'][0]['status'],'pending')
            write_json(base/'data.json',{**night,'machine_records':self.rows+[
                self.row('2026-10-27',n) for n in range(2201,2205)]})
            settled=run(base,datetime(2026,10,27,20,tzinfo=timezone.utc))
            self.assertEqual(settled['evaluation']['prospective'][0]['status'],'complete')
            self.assertEqual(settled['keep'],'untouched')

    def test_naive_clock_rejected(self):
        with self.assertRaises(ValueError): run(now=datetime(2026,10,26))


if __name__ == '__main__':
    unittest.main()
