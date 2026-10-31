import copy
import unittest
from evaluate_count_models import fit_weights,evaluate_records


class CountReplayTests(unittest.TestCase):
    def setUp(self):
        self.config={'timezone':'Asia/Tokyo','models':[{'id':'myj5','name':'V','installations':[
            {'from':None,'until':None,'numbers':list(range(1,9))}]}]}
        self.rows=[{'date':f'2026-10-{d:02d}','model_id':'myj5','number':n,'games':5000,
                    'bb':18,'rb':12,'difference':0} for d in range(20,25) for n in range(1,9)]

    def test_target_and_future_outcomes_do_not_affect_weights(self):
        before=fit_weights(self.rows,self.config,'myj5','2026-10-23')
        changed=[{**r,'bb':200} if r['date']>='2026-10-23' else r for r in self.rows]
        self.assertEqual(before,fit_weights(changed,self.config,'myj5','2026-10-23'))
        self.assertEqual(before['trained_through'],'2026-10-22')
        self.assertAlmostEqual(sum(before['weights']),1)

    def test_low_play_and_short_history_are_not_fitted(self):
        self.assertIsNone(fit_weights(self.rows,self.config,'myj5','2026-10-22'))
        self.assertIsNone(fit_weights([{**r,'games':2999} for r in self.rows],self.config,'myj5','2026-10-25'))

    def test_duplicate_record_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_records(self.rows+[self.rows[0]],self.config,'2026-10-25')

    def test_same_rows_scored_for_all_methods_and_inputs_preserved(self):
        before=copy.deepcopy(self.rows)
        result=evaluate_records(self.rows,self.config,'2026-10-25')
        group=result['summaries']['myj5']['all']
        self.assertEqual((group['days'],group['rows']),(2,16))
        self.assertEqual(len(group['methods']),4)
        self.assertEqual(self.rows,before)
        self.assertFalse(result['changes_live_strategy'])
