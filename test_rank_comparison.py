import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from collect_sources import write_json
from forecast_engine import make_forecast, run as run_live, save_snapshot
from rank_comparison import (ROOT, SPEC, capture, identity, metrics, run,
                             score, summarize, validate)


class RankingPairTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.config = {'timezone':'Asia/Tokyo','models':[{'id':'myj5','name':'V',
            'installations':[{'from':None,'until':None,'numbers':[2201,2202,2203,2204]}]}]}
        self.rows = [self.row(d,n) for d in ('2026-10-31','2026-11-01','2026-11-02')
                     for n in (2201,2202,2203,2204)]
        self.now = datetime.fromisoformat('2026-11-03T05:03:00+09:00')
        self.night = datetime.fromisoformat('2026-11-03T23:30:00+09:00')
        self.actual = [self.row('2026-11-03',n) for n in (2201,2202,2203,2204)]
        write_json(self.base/'machines.json',self.config)
        write_json(self.base/'data.json',{'machine_records':self.rows})

    def row(self, day, number):
        return {'date':day,'model_id':'myj5','number':number,'games':5000,
                'bb':10+(number-2201)*9,'rb':20,'difference':(number-2202)*700,
                'source_url':'https://min-repo.com/example/'}

    def pair(self, records=None):
        records = self.rows if records is None else records
        live = save_snapshot(self.base/'history/forecasts/2026-11-03.json',
            make_forecast(self.config,records,'2026-11-03',(),self.now.isoformat()))
        pair = capture(self.base,self.config,records,live,self.now)
        return live,pair

    def test_capture_both_rankings_same_cohort_and_exact_live_order(self):
        live,pair = self.pair()
        validate(pair)
        model = pair['models']['myj5']
        self.assertEqual(model['cohort'],[2201,2202,2203,2204])
        self.assertEqual([r['number'] for r in model['baseline']],
                         [r['number'] for r in live['models']['myj5']['rankings']['balanced']])
        self.assertEqual(set(r['number'] for r in model['candidate']),set(model['cohort']))
        self.assertEqual(pair['max_input_date'],'2026-11-02')
        self.assertFalse(SPEC['automatic_promotion'])
        self.assertEqual([r['number'] for r in model['candidate']],[2201,2204,2203,2202])
        self.assertEqual([r['score'] for r in model['candidate']],[46.13,32.5,30.37,24.63])

    def test_morning_hook_captures_without_changing_live_output_or_existing_bytes(self):
        with redirect_stdout(io.StringIO()):
            result = run_live(self.base,self.now)
        path = self.base/'history/forecasts/2026-11-03.json'
        primary = path.read_bytes()
        comparison_path = self.base/ROOT/'forecasts/2026-11-03.json'
        self.assertTrue(comparison_path.exists())
        validate(json.loads(comparison_path.read_text()))
        self.assertEqual(result['forecast']['display_status'],'locked')
        reference = make_forecast(self.config,self.rows,'2026-11-03',(),self.now.isoformat())
        self.assertEqual(result['forecast']['models'],reference['models'])
        research_bytes = comparison_path.read_bytes()
        write_json(self.base/'data.json',{'machine_records':self.rows+self.actual})
        with redirect_stdout(io.StringIO()):
            run_live(self.base,self.now+timedelta(minutes=30))
            run_live(self.base,self.night)
        self.assertEqual(path.read_bytes(),primary)
        self.assertEqual(comparison_path.read_bytes(),research_bytes)

    def test_no_capture_for_preexisting_forecast_or_cli_backfill(self):
        live = save_snapshot(self.base/'history/forecasts/2026-11-03.json',
            make_forecast(self.config,self.rows,'2026-11-03',(),self.now.isoformat()))
        with redirect_stdout(io.StringIO()):
            run_live(self.base,self.now+timedelta(minutes=30))
            result=run(self.base,now=self.night)
        self.assertFalse((self.base/ROOT/'forecasts/2026-11-03.json').exists())
        self.assertEqual(result['models'],{})
        with self.assertRaises(ValueError):
            capture(self.base,self.config,self.rows,live,self.now+timedelta(minutes=1))
        self.assertIsNone(capture(self.base,self.config,self.rows,live,self.night))

    def test_target_future_rows_do_not_change_pair_and_inputs_are_not_mutated(self):
        original = copy.deepcopy(self.rows)
        live,pair = self.pair()
        with TemporaryDirectory() as directory:
            b=Path(directory)
            save_snapshot(b/'history/forecasts/2026-11-03.json',live)
            future = self.actual+[self.row('2026-11-04',2201)]
            second = capture(b,self.config,self.rows+future,live,self.now)
        self.assertEqual(pair,second)
        self.assertEqual(original,self.rows)

    def test_different_input_or_corrupt_pair_is_rejected(self):
        live,pair = self.pair()
        bad = copy.deepcopy(pair)
        bad['models']['myj5']['candidate'][0]['number']=9999
        with self.assertRaises(ValueError):validate(bad)
        # Removing the destination makes this a new capture attempt, not a retry.
        (self.base/ROOT/'forecasts/2026-11-03.json').unlink()
        changed=[{**r,'rb':1} if r['number']==2201 else r for r in self.rows]
        with self.assertRaises(ValueError):capture(self.base,self.config,changed,live,self.now)

    def test_end_of_day_and_all_installed_rows_required_not_only_selected(self):
        _,pair = self.pair()
        self.assertEqual(score(pair,self.rows+self.actual,self.now)['models']['myj5']['status'],
                         'waiting_for_day_end')
        before=self.night-timedelta(minutes=1)
        self.assertEqual(score(pair,self.rows+self.actual,before)['models']['myj5']['status'],
                         'waiting_for_day_end')
        # Exclude a machine that neither method selects, if available; the rule
        # still requires every installed machine for a valid all-machine mean.
        selected={r['number'] for method in ('baseline','candidate')
                  for r in pair['models']['myj5'][method][:3]}
        missing=next((n for n in (2201,2202,2203,2204) if n not in selected),2204)
        incomplete=[r for r in self.actual if r['number']!=missing]
        result=score(pair,self.rows+incomplete,self.night)['models']['myj5']
        self.assertEqual(result['status'],'pending_results')
        self.assertNotIn('methods',result)
        invalid=[{**r,'difference':None} if r['number']==2204 else r for r in self.actual]
        self.assertEqual(score(pair,self.rows+invalid,self.night)['models']['myj5']['status'],'pending_results')
        ready=score(pair,self.rows+self.actual,self.night)['models']['myj5']
        self.assertEqual(ready['status'],'complete')
        self.assertEqual(ready['all_installed']['count'],4)
        for method in ('baseline','candidate'):
            self.assertEqual(ready['methods'][method]['top3']['count'],3)
            self.assertEqual(len(ready['methods'][method]['by_rank']),4)

    def test_missing_day_not_counted_then_late_results_settle_once(self):
        live,pair=self.pair()
        original=(self.base/'data.json').read_bytes()
        with redirect_stdout(io.StringIO()):
            pending=run(self.base,now=self.night)
        self.assertEqual(pending['models'],{})
        self.assertEqual(pending['pending'][0]['status'],'pending_results')
        with redirect_stdout(io.StringIO()):
            result=run(self.base,now=self.night+timedelta(hours=7),records=self.rows+self.actual)
        segment=result['models']['myj5']['segments'][0]
        self.assertEqual(segment['completed_days'],1)
        self.assertEqual(segment['days_remaining'],29)
        target=self.base/ROOT/'evaluations/2026-11-03.json'
        settled=target.read_bytes()
        with redirect_stdout(io.StringIO()):
            again=run(self.base,now=self.night+timedelta(days=1),records=self.rows)
        self.assertEqual(again['models']['myj5']['segments'][0]['completed_days'],1)
        self.assertEqual(target.read_bytes(),settled)
        self.assertEqual((self.base/'data.json').read_bytes(),original)
        self.assertEqual(json.loads((self.base/'history/forecasts/2026-11-03.json').read_text()),live)

    def test_unranked_installed_machine_is_required_for_all_machine_mean(self):
        self.config['models'][0]['installations'][0]['numbers'].append(2205)
        extra=[{**self.row(d,2205),'games':500,'bb':2,'rb':2,'difference':0}
               for d in ('2026-10-31','2026-11-01','2026-11-02')]
        _,pair=self.pair(self.rows+extra)
        model=pair['models']['myj5']
        self.assertNotIn(2205,model['cohort'])
        self.assertIn(2205,model['installed_numbers'])
        pending=score(pair,self.rows+self.actual,self.night)['models']['myj5']
        self.assertEqual(pending['missing_numbers'],[2205])
        self.assertNotIn('methods',pending)

    def test_partial_models_do_not_inflate_denominators(self):
        live,pair=self.pair()
        pair=copy.deepcopy(pair)
        pair['models']['myj6']={**copy.deepcopy(pair['models']['myj5']),
                              'installed_numbers':[2301,2302,2303,2304],'cohort':[2301,2302,2303,2304]}
        for method in ('baseline','candidate'):
            for row in pair['models']['myj6'][method]:row['number']+=100
        pair['snapshot_id']=identity(pair)
        scored=score(pair,self.rows+self.actual,self.night)
        result=summarize([(pair,scored)],'2026-11-04')
        self.assertIn('myj5',result['models'])
        self.assertNotIn('myj6',result['models'])

    def test_arithmetic_zero_not_positive_and_rank_denominators(self):
        rows=[{'difference':-100},{'difference':0},{'difference':400}]
        value=metrics(rows,25)
        self.assertEqual(value['positive_rate'],1/3)
        self.assertEqual(value['mean_difference'],100)
        self.assertEqual(value['mean_lift_vs_all'],75)
        _,pair=self.pair()
        evaluation=score(pair,self.rows+self.actual,self.night)
        summary=summarize([(pair,evaluation)],'2026-11-04')
        for method in summary['models']['myj5']['segments'][0]['methods'].values():
            self.assertEqual(method['top3']['count'],3)
            self.assertTrue(all(r['count']==1 for r in method['by_rank'].values()))

    def test_future_observation_cannot_be_borrowed_by_an_earlier_execution(self):
        self.pair()
        with redirect_stdout(io.StringIO()):
            run(self.base,now=self.night,records=self.rows+self.actual)
            earlier=run(self.base,now=self.now,records=self.rows)
        self.assertEqual(earlier['models'],{})
        self.assertEqual(len(earlier['errors']),1)

    def test_missing_forecast_or_tampered_evaluation_is_excluded(self):
        self.pair()
        with redirect_stdout(io.StringIO()):
            run(self.base,now=self.night,records=self.rows+self.actual)
        target=self.base/ROOT/'evaluations/2026-11-03.json'
        edited=json.loads(target.read_text())
        edited['models']['myj5']['methods']['candidate']['top3']['mean_difference']=99999
        write_json(target,edited)
        with redirect_stdout(io.StringIO()):
            result=run(self.base,now=self.night+timedelta(days=1),records=self.rows+self.actual)
        self.assertEqual(result['models'],{})
        self.assertEqual(len(result['errors']),1)
        (self.base/'history/forecasts/2026-11-03.json').unlink()
        with redirect_stdout(io.StringIO()):
            result=run(self.base,now=self.night+timedelta(days=1),records=self.rows+self.actual)
        self.assertEqual(result['models'],{})
        self.assertEqual(len(result['errors']),1)

    def test_30_days_requires_review_never_promotes_and_rule_changes_segment(self):
        _,pair=self.pair()
        evaluation=score(pair,self.rows+self.actual,self.night)
        entries=[]
        for i in range(30):
            day=str(self.now.date()+timedelta(days=i))
            s=copy.deepcopy(pair);s['date']=day;s['created_at']=day+'T05:03:00+09:00'
            s['snapshot_id']=identity(s)
            e=copy.deepcopy(evaluation);e.update(date=day,snapshot_id=s['snapshot_id'])
            entries.append((s,e))
        result=summarize(entries,'2026-12-03')
        segment=result['models']['myj5']['segments'][0]
        self.assertEqual(segment['completed_days'],30)
        self.assertEqual(segment['status'],'minimum_reached_review_required')
        self.assertFalse(result['automatic_promotion'])
        self.assertFalse(result['changes_live_strategy'])
        entries[-1][0]['baseline_code_sha256']='changed-version'
        entries[-1][0]['snapshot_id']=identity(entries[-1][0])
        entries[-1][1]['snapshot_id']=entries[-1][0]['snapshot_id']
        result=summarize(entries,'2026-12-03')
        self.assertEqual(sorted(s['completed_days'] for s in result['models']['myj5']['segments']),[1,29])
        with self.assertRaises(ValueError):summarize(entries+entries[:1],'2026-12-03')

    def test_comparison_failure_does_not_stop_or_change_public_forecast(self):
        with patch('rank_comparison.run',side_effect=RuntimeError('research failure')):
            with redirect_stdout(io.StringIO()):result=run_live(self.base,self.now)
        self.assertEqual(result['forecast']['display_status'],'locked')
        self.assertTrue((self.base/'history/forecasts/2026-11-03.json').exists())
        self.assertEqual(result['forecast']['models'],
                         make_forecast(self.config,self.rows,'2026-11-03',(),self.now.isoformat())['models'])


if __name__ == '__main__':
    unittest.main()
