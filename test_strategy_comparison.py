import copy
import unittest
from evaluate_strategies import build_report, audit_missing
import test_evaluate_candidates as fixtures


class StrategyTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.CandidateEvaluationTests(); fixture.setUp()
        self.config, self.rows = fixture.config, fixture.rows

    def report(self, rows=None):
        return build_report(self.config, self.rows if rows is None else rows, '2026-10-28', 1)

    def test_paired_same_days_and_baseline_zero_gain(self):
        report = self.report()['models']['m']
        for group in ('primary','backup'):
            stats = report['periods']['all']
            self.assertEqual({stats[s][group]['days'] for s in stats}, {1})
            self.assertEqual(stats['balanced'][group]['paired_mean_gain_vs_balanced'],0)
        self.assertEqual(report['periods']['earlier']['balanced']['primary'],None)

    def test_missing_outcome_excludes_all_strategies(self):
        rows=[r for r in self.rows if not (r['date']=='2026-10-27' and r['number']==12)]
        model=self.report(rows)['models']['m']
        self.assertEqual(model['daily'],[])
        self.assertEqual(model['excluded']['incomplete_outcomes'],1)
        self.assertIsNone(model['periods']['all']['rb']['primary'])

    def test_future_data_has_no_effect_and_inputs_preserved(self):
        before=copy.deepcopy(self.rows)
        future=[{**r,'date':'2026-10-29'} for r in self.rows[:12]]
        self.assertEqual(self.report()['models'],self.report(self.rows+future)['models'])
        self.assertEqual(before,self.rows)

    def test_target_outcomes_do_not_change_any_ranking(self):
        original=self.report()['models']['m']['daily'][0]['outcomes']
        changed=self.report([{**r,'difference':10000-r['number']} if r['date']=='2026-10-27' else r for r in self.rows])['models']['m']['daily'][0]['outcomes']
        for strategy in original:
            for group in original[strategy]:
                self.assertEqual([r['number'] for r in original[strategy][group]],
                                 [r['number'] for r in changed[strategy][group]])

    def test_duplicate_and_invalid_window_rejected(self):
        with self.assertRaises(ValueError):self.report(self.rows+[self.rows[0]])
        for days in (0,91,True):
            with self.assertRaises(ValueError):build_report(self.config,self.rows,'2026-10-28',days)

    def test_audit_distinguishes_missing_record_from_null_and_zero(self):
        rows=[{**r,'difference':None} if r['date']=='2026-10-27' and r['number']==1 else r
              for r in self.rows if not (r['date']=='2026-10-27' and r['number']==2)]
        rows=[{**r,'difference':0} if r['number']==3 else r for r in rows]
        missing=[r for r in audit_missing(self.config,rows,'2026-10-28')['missing'] if r['date']=='2026-10-27']
        self.assertEqual([r['number'] for r in missing],[1,2])
        self.assertEqual([r['reason'] for r in missing],['invalid_or_missing_measurement','missing_record'])

if __name__=='__main__':unittest.main()
