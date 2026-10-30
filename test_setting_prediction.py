import copy
import math
import unittest
from setting_model import score_count_prediction, SPECS, REQUIRED_CONTRACT
from collect_sources import BASE
import json

class CountPredictionTests(unittest.TestCase):
    def setUp(self):
        self.config=json.loads((BASE/'machines.json').read_text())
        self.row={'date':'2026-10-25','model_id':'myj5','number':2201,'games':8000,'bb':30,'rb':24}
        self.prediction={'target_date':'2026-10-25','trained_through':'2026-10-24',
                         'model_id':'myj5','number':2201,'setting_weights':[1]*6}
        self.contract={k:True for k in REQUIRED_CONTRACT}

    def score(self, prediction=None, contract=None):
        return score_count_prediction(self.row,self.config,self.prediction if prediction is None else prediction,
                                      self.contract if contract is None else contract)

    def test_exact_mixture_and_coefficient(self):
        n,b,r=8000,30,24
        coef=math.lgamma(n+1)-math.lgamma(b+1)-math.lgamma(r+1)-math.lgamma(n-b-r+1)
        logs=[coef+b*math.log(1/bd)+r*math.log(1/rd)+(n-b-r)*math.log1p(-1/bd-1/rd) for bd,rd in SPECS['myj5']]
        expected=math.log(sum(math.exp(t) for t in logs)/6)
        self.assertAlmostEqual(self.score()['log_predictive_probability'],expected)
        self.assertFalse(self.score()['calibrated'])

    def test_reject_same_day_future_and_identity_mismatch(self):
        for patch in ({'trained_through':'2026-10-25'},{'trained_through':'2026-10-26'},
                      {'target_date':'2026-10-26'},{'model_id':'myj6'},{'number':2202}):
            self.assertEqual(self.score({**self.prediction,**patch})['status'],'invalid_prediction')

    def test_unverified_observations_have_no_score(self):
        result=self.score(contract={})
        self.assertEqual(result['status'],'unverified_observation_semantics')
        self.assertNotIn('log_predictive_probability',result)

    def test_normalization_and_zero_weights(self):
        self.assertAlmostEqual(self.score()['log_predictive_probability'],
                               self.score({**self.prediction,'setting_weights':[10]*6})['log_predictive_probability'])
        result=self.score({**self.prediction,'setting_weights':[1,0,0,0,0,0]})
        self.assertTrue(math.isfinite(result['log_predictive_probability']))

    def test_invalid_weights(self):
        for weights in (None,[],[0]*6,[math.inf]*6,[True]*6):
            self.assertEqual(self.score({**self.prediction,'setting_weights':weights})['status'],'invalid_prediction')

    def test_no_input_mutation(self):
        before=copy.deepcopy((self.row,self.prediction,self.config))
        self.score();self.assertEqual(before,(self.row,self.prediction,self.config))

if __name__=='__main__':unittest.main()
