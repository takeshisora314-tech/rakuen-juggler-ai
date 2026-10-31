import copy
import math
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from collect_sources import write_json
from collect_sources import BASE
from setting_model import infer_day, REQUIRED_CONTRACT, SPECS, SOURCES
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

    def test_one_or_two_eligible_machines_are_ranked_and_evaluated(self):
        for numbers in ((2201,), (2201, 2202)):
            with self.subTest(numbers=numbers):
                rows = [r for r in self.rows if r['number'] in numbers]
                forecast = self.forecast(rows)
                model = forecast['models']['myj5']
                self.assertEqual(model['status'], 'ready')
                self.assertEqual(model['eligible_numbers'], list(numbers))
                for candidates in model['strategies'].values():
                    self.assertEqual(len(candidates), len(numbers))
                actual = [self.row('2026-10-27', n) for n in numbers]
                pending = evaluate(forecast, [])['models']['myj5']
                self.assertEqual(pending['status'], 'pending_results')
                result = evaluate(forecast, actual)['models']['myj5']
                self.assertEqual(result['status'], 'complete')
                for metrics in result['strategies'].values():
                    self.assertEqual(metrics['count'], len(numbers))

    def test_no_eligible_machine_still_abstains(self):
        rows = [{**r, 'games': 2999} for r in self.rows]
        model = self.forecast(rows)['models']['myj5']
        self.assertEqual(model['status'], 'insufficient_eligible_machines')
        self.assertEqual(model['strategies'], {})

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

    def test_prediction_rows_preserve_saved_order_and_partial_actuals(self):
        snap=self.forecast()
        original=copy.deepcopy(snap)
        ordered=snap['models']['myj5']['rankings']['balanced']
        number=ordered[0]['number']
        result=evaluate(snap,[self.row('2026-10-27',number)])['models']['myj5']
        rows=result['prediction_results']
        self.assertEqual([r['number'] for r in rows],[r['number'] for r in ordered])
        self.assertEqual([r['rank'] for r in rows],list(range(1,len(ordered)+1)))
        self.assertEqual(rows[0]['status'],'available')
        self.assertTrue(all(r['actual'] is None for r in rows[1:]))
        self.assertEqual(result['status'],'pending_results')
        self.assertEqual(result['strategies'],{})
        self.assertEqual(snap,original)
        wrong_day=evaluate(snap,[self.row('2026-10-26',number)])['models']['myj5']
        self.assertTrue(all(r['actual'] is None for r in wrong_day['prediction_results']))

    def test_legacy_snapshot_uses_its_original_top_three(self):
        snap=self.forecast();del snap['models']['myj5']['rankings']
        rows=evaluate(snap,self.rows)['models']['myj5']['prediction_results']
        self.assertEqual(len(rows),3)
        self.assertEqual([r['number'] for r in rows],[r['number'] for r in snap['models']['myj5']['strategies']['balanced']])

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
                     s:{'count':3,'positive_count':2,'low_play_count':0,
                        'mean_difference':gain if s=='dip' else 0,
                        'lift_vs_eligible_mean':gain if s=='dip' else 0,'positive_rate':2/3}
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

    def test_duplicate_dates_cannot_create_thirty_comparison_days(self):
        comparisons=self.paired(29)
        comparisons.append(copy.deepcopy(comparisons[0]))
        result=choose_strategy(comparisons,'myj5','2026-10-27')
        self.assertEqual(result['paired_days'],28)
        self.assertEqual(result['strategy'],'balanced')
        self.assertEqual(choose_strategy(comparisons[::-1],'myj5','2026-10-27'),result)

    def test_invalid_comparison_metrics_cannot_switch(self):
        for field,value in [('count',2),('count',True),('positive_count',4),
                            ('positive_count',True),('low_play_count',-1),
                            ('positive_rate',math.nan),('positive_rate',0.5),
                            ('mean_difference',math.inf),('mean_difference','100'),
                            ('lift_vs_eligible_mean',math.nan),('lift_vs_eligible_mean',True)]:
            with self.subTest(field=field,value=value):
                comparisons=self.paired(30)
                comparisons[0]['models']['myj5']['strategies']['rb'][field]=value
                result=choose_strategy(comparisons,'myj5','2026-10-27')
                self.assertEqual(result['paired_days'],29)
                self.assertEqual(result['strategy'],'balanced')

    def test_missing_strategy_and_pending_results_are_not_paired(self):
        for change in ('missing','pending'):
            comparisons=self.paired(30)
            model=comparisons[0]['models']['myj5']
            if change=='missing': del model['strategies']['rb']
            else: model['status']='pending_results'
            self.assertEqual(choose_strategy(comparisons,'myj5','2026-10-27')['paired_days'],29)

    def test_invalid_dates_and_shapes_are_ignored(self):
        comparisons=self.paired(1)
        for bad in (None,42,{}, {'kind':'prospective','version':VERSION},
                    {**comparisons[0],'date':'2026-02-30'},
                    {**comparisons[0],'date':'20260902'},
                    {**comparisons[0],'date':'2026-09-02','models':None},
                    {**comparisons[0],'date':'2026-09-03','models':{'myj5':None}}):
            result=choose_strategy([*comparisons,bad],'myj5','2026-10-27')
            self.assertEqual(result['paired_days'],1)

    def test_only_latest_sixty_valid_unique_days_are_compared(self):
        result=choose_strategy(self.paired(70),'myj5','2026-12-01')
        self.assertEqual(result['paired_days'],60)
        self.assertEqual(result['strategy'],'dip')

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

    def test_before_five_is_today_preview_then_five_locks(self):
        with TemporaryDirectory() as directory:
            base=Path(directory)
            write_json(base/'machines.json',self.config)
            write_json(base/'data.json',{'machine_records':self.rows})
            path=base/'history'/'forecasts'/'2026-10-27.json'
            for hour,minute in ((15,0),(19,59)):
                early=run(base,datetime(2026,10,26,hour,minute,tzinfo=timezone.utc))
                self.assertEqual(early['forecast']['date'],'2026-10-27')
                self.assertEqual(early['forecast']['display_status'],'preview')
                self.assertFalse(path.exists())
            locked=run(base,datetime(2026,10,26,20,tzinfo=timezone.utc))
            self.assertTrue(path.exists())
            self.assertEqual(locked['forecast']['display_status'],'locked')

    def test_at_seven_does_not_create_late_morning_forecast(self):
        with TemporaryDirectory() as directory:
            base=Path(directory)
            write_json(base/'machines.json',self.config)
            write_json(base/'data.json',{'machine_records':self.rows})
            late=run(base,datetime(2026,10,26,22,tzinfo=timezone.utc))
            self.assertEqual(late['forecast']['display_status'],'preview')
            self.assertEqual(late['forecast']['date'],'2026-10-28')
            self.assertFalse((base/'history'/'forecasts'/'2026-10-27.json').exists())

    def test_naive_clock_rejected(self):
        with self.assertRaises(ValueError): run(now=datetime(2026,10,26))


class ConditionalSettingTests(unittest.TestCase):
    def setUp(self):
        self.config=json.loads((BASE/'machines.json').read_text())
        self.row={'date':'2026-10-26','model_id':'myj5','number':2221,'games':8000,'bb':30,'rb':24}
        self.contract={k:True for k in REQUIRED_CONTRACT}

    def infer(self, row=None, prior=None):
        return infer_day(self.row if row is None else row,self.config,[1]*6 if prior is None else prior,self.contract)

    def test_contract_not_assumed(self):
        result=infer_day(self.row,self.config,[1]*6)
        self.assertEqual(result['status'],'unverified_observation_semantics')
        self.assertNotIn('conditional_mass_4_6',result)

    def test_normalization_and_not_calibrated(self):
        result=self.infer()
        self.assertAlmostEqual(sum(result['conditional_setting_distribution']),1)
        self.assertFalse(result['calibrated'])
        self.assertEqual(result['date'],self.row['date'])

    def test_more_rb_supports_higher_settings_under_same_prior(self):
        self.assertGreater(self.infer({**self.row,'rb':40})['conditional_mass_4_6'],self.infer()['conditional_mass_4_6'])

    def test_prior_matters_and_zero_prior_remains_zero(self):
        result=self.infer(prior=[1,1,1,0,0,0])
        self.assertEqual(result['conditional_mass_4_6'],0)
        self.assertGreater(self.infer()['conditional_mass_4_6'],0)

    def test_invalid_prior_rejected(self):
        for prior in ([0]*6,[1]*5,[1,1,1,1,1,math.nan],[1,1,1,1,1,-1]):
            with self.assertRaises(ValueError): self.infer(prior=prior)

    def test_layout_and_unsupported_model(self):
        self.assertEqual(self.infer({**self.row,'date':'2026-10-27','number':2201})['status'],'installation_mismatch')
        self.assertEqual(self.infer({**self.row,'model_id':'unknown'})['status'],'unsupported_model')
        self.assertEqual(self.infer({**self.row,'date':'2026-10-27','number':2201,'model_id':'myj6'})['status'],'conditional_result')

    def test_missing_low_games_and_impossible_counts_abstain(self):
        for row,status in (({**self.row,'rb':None},'invalid_record'),({**self.row,'games':1000},'insufficient_games'),({**self.row,'bb':9000},'invalid_record')):
            self.assertEqual(self.infer(row)['status'],status)

    def test_difference_not_double_counted_and_numerical_stability(self):
        self.assertEqual(self.infer(),self.infer({**self.row,'difference':99999}))
        result=self.infer({**self.row,'games':10000000,'bb':40000,'rb':30000})
        self.assertAlmostEqual(sum(result['conditional_setting_distribution']),1)

    def test_all_eight_official_tables_are_separate_and_valid(self):
        self.assertEqual(set(SPECS),set(SOURCES))
        self.assertEqual(len(SPECS),8)
        for table in SPECS.values():
            self.assertEqual(len(table),6)
            for bb,rb in table:
                self.assertGreater(bb,1);self.assertGreater(rb,1)
                self.assertLess(1/bb+1/rb,1)
        self.assertEqual(SPECS['neoim'][0],(273.1,439.8))
        self.assertEqual(SPECS['happy8'][-1],(226.0,256.0))
        self.assertNotEqual(SPECS['funky2'],SPECS['myj5'])

    def test_each_model_uses_its_own_layout_and_official_table(self):
        for model,number in (('myj5',2221),('myj6',2201),('neoim',2101),('gogo3',112),('funky2',101),('girls',201),('mr',210),('happy8',219)):
            row={**self.row,'date':'2026-10-27','model_id':model,'number':number}
            result=self.infer(row)
            self.assertEqual(result['status'],'conditional_result')
            self.assertEqual(result['source'],SOURCES[model])
            self.assertAlmostEqual(sum(result['conditional_setting_distribution']),1)

    def test_model_identity_is_not_assumed_from_short_name(self):
        contract={**self.contract,'model_identity_confirmed':False}
        result=infer_day(self.row,self.config,[1]*6,contract)
        self.assertEqual(result['status'],'unverified_observation_semantics')


if __name__ == '__main__':
    unittest.main()
