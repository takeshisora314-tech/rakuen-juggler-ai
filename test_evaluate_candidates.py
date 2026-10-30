import copy
import unittest
from evaluate_candidates import build_report, summarize


class CandidateEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.config = {'timezone':'Asia/Tokyo', 'models':[{'id':'m','name':'M',
            'installations':[{'from':None,'until':None,'numbers':list(range(1,13))}]}]}
        self.rows = [{'date':day,'model_id':'m','number':n,'games':5000,
                      'bb':20,'rb':20,'difference':100 if n%2 else -50}
                     for day in ('2026-10-24','2026-10-25','2026-10-26','2026-10-27')
                     for n in range(1,13)]

    def report(self, rows=None):
        return build_report(self.config,self.rows if rows is None else rows,'2026-10-28',1)

    def test_distinct_groups_and_fixed_denominators(self):
        r=self.report();g=r['daily'][0]['groups']
        self.assertEqual(len(g['primary']),3)
        self.assertEqual(len(g['backup']),7)
        self.assertFalse({x['number'] for x in g['primary']} & {x['number'] for x in g['backup']})
        for label in g:
            s=r['models']['m'][label]
            self.assertEqual(s['positive_rate'],sum(x['difference']>0 for x in g[label])/len(g[label]))

    def test_missing_actual_excludes_day_not_zero(self):
        rows=[r for r in self.rows if not (r['date']=='2026-10-27' and r['number']==12)]
        self.assertIsNone(self.report(rows)['models']['m']['primary'])

    def test_outcomes_cannot_reorder_candidates(self):
        original=self.report()['daily'][0]['groups']
        rows=[{**r,'difference':999999-r['number']} if r['date']=='2026-10-27' else r for r in self.rows]
        changed=self.report(rows)['daily'][0]['groups']
        for label in original:
            self.assertEqual([r['number'] for r in original[label]],[r['number'] for r in changed[label]])

    def test_future_rows_and_input_preservation(self):
        before=copy.deepcopy(self.rows)
        future=[{**r,'date':'2026-10-29'} for r in self.rows[:12]]
        self.assertEqual(self.report()['models'],self.report(self.rows+future)['models'])
        self.assertEqual(self.rows,before)

    def test_no_evidence_is_not_zero_percent(self):
        self.assertIsNone(summarize([]))

    def test_duplicate_records_rejected(self):
        with self.assertRaises(ValueError): self.report(self.rows+[self.rows[0]])

    def test_invalid_window(self):
        with self.assertRaises(ValueError): build_report(self.config,self.rows,'2026-10-28',91)


if __name__=='__main__': unittest.main()
