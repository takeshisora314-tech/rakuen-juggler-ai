import copy
import json
import math
import unittest

from collect_sources import BASE
from setting_model import compare_priors, infer_day, REQUIRED_CONTRACT


class PriorSensitivityTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((BASE / 'machines.json').read_text())
        self.row = {'date': '2026-10-26', 'model_id': 'myj5',
                    'number': 2221, 'games': 8000, 'bb': 30, 'rb': 24}
        self.contract = {key: True for key in REQUIRED_CONTRACT}
        # Hypothetical test scenarios, not measured store allocations.
        self.scenarios = {'equal': [1] * 6, 'low_weight': [4, 4, 4, 1, 1, 1]}

    def compare(self, **kwargs):
        args = dict(record=self.row, config=self.config, scenarios=self.scenarios,
                    observation_contract=self.contract)
        return compare_priors(**{**args, **kwargs})

    def test_scenarios_match_independent_inference_and_range(self):
        result = self.compare()
        self.assertEqual(result['status'], 'conditional_comparison')
        masses = []
        for name, prior in self.scenarios.items():
            direct = infer_day(self.row, self.config, prior, self.contract)
            self.assertEqual(result['scenarios'][name], direct)
            masses.append(direct['conditional_mass_4_6'])
        self.assertEqual(result['conditional_mass_4_6_range'],
                         {'minimum': min(masses), 'maximum': max(masses),
                          'span': max(masses) - min(masses)})
        self.assertFalse(result['calibrated'])
        self.assertIn('not a confidence interval', result['warning'])

    def test_prior_odds_change_posterior_odds_by_same_factor(self):
        result = self.compare()['scenarios']
        equal = result['equal']['conditional_mass_4_6']
        low = result['low_weight']['conditional_mass_4_6']
        self.assertAlmostEqual(low / (1 - low), equal / (1 - equal) / 4)

    def test_rescaled_prior_and_scenario_order_do_not_change_result(self):
        result = self.compare(scenarios={'a': [1] * 6, 'b': [10] * 6})
        self.assertAlmostEqual(result['conditional_mass_4_6_range']['span'], 0)
        reverse = dict(reversed(list(self.scenarios.items())))
        self.assertEqual(self.compare(), self.compare(scenarios=reverse))

    def test_zero_weights_remain_zero(self):
        result = self.compare(scenarios={'low': [1, 1, 1, 0, 0, 0],
                                         'high': [0, 0, 0, 1, 1, 1]})
        self.assertEqual(result['conditional_mass_4_6_range'],
                         {'minimum': 0, 'maximum': 1, 'span': 1})

    def test_unverified_contract_never_produces_numeric_summary(self):
        for contract in (None, {}, {**self.contract, 'normal_game_trials': False}):
            result = self.compare(observation_contract=contract)
            self.assertEqual(result['status'], 'inference_unavailable')
            self.assertNotIn('conditional_mass_4_6_range', result)
            self.assertTrue(all(r['status'] == 'unverified_observation_semantics'
                                for r in result['scenarios'].values()))

    def test_invalid_or_low_play_records_do_not_produce_summary(self):
        for row in (None, {**self.row, 'games': 100}, {**self.row, 'rb': None},
                    {**self.row, 'date': '2026-10-27', 'number': 2201}):
            result = self.compare(record=row)
            self.assertEqual(result['status'], 'inference_unavailable')
            self.assertNotIn('conditional_mass_4_6_range', result)

    def test_invalid_scenarios_are_rejected(self):
        cases = [None, [], {}, {'only': [1] * 6},
                 {'': [1] * 6, 'ok': [1] * 6}, {1: [1] * 6, 'ok': [1] * 6}]
        for prior in (None, '111111', [1] * 5, [0] * 6, [True] * 6,
                      [1, 1, 1, 1, 1, -1], [math.nan] * 6,
                      [math.inf] * 6, [1e308] * 6):
            cases.append({'bad': prior, 'ok': [1] * 6})
        for scenarios in cases:
            with self.subTest(scenarios=scenarios), self.assertRaises(ValueError):
                self.compare(scenarios=scenarios)

    def test_inputs_are_unchanged(self):
        before = copy.deepcopy((self.row, self.config, self.scenarios, self.contract))
        self.compare()
        self.assertEqual(before, (self.row, self.config, self.scenarios, self.contract))


if __name__ == '__main__':
    unittest.main()
