import copy
import unittest
from evaluate_count_models import fit_weights,evaluate_records,diagnose_rows


class CountReplayTests(unittest.TestCase):
    def test_diagnostics_use_paired_rows_and_separate_daily_weight(self):
        rows=[]
        for day,n,games,gain in [('2026-09-05',1,4000,2),('2026-10-30',9,7000,-1)]:
            rows += [{'date':day,'model_id':'myj5','games':games,'scores':{
                'equal':-10,'low_heavy':-11,'high_heavy':-9,'rolling_mixture':-10+gain}} for _ in range(n)]
        result=diagnose_rows(rows,'2026-11-02')['models']['myj5']
        comp=result['all']['comparisons']['equal']
        self.assertAlmostEqual(comp['mean_row_gain'],-.7)
        self.assertEqual(comp['mean_daily_gain'],.5)
        self.assertEqual((comp['positive_days'],comp['negative_days']),(1,1))
        for label,count in [('earlier',1),('recent_30',9),('games_3000_5999',1),('games_6000_plus',9),('weekend',1),('weekday',9)]:
            self.assertEqual(result[label]['rows'],count)
        with self.assertRaises(ValueError):diagnose_rows(rows,'2026-10-30')

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
