import copy
import json
import unittest
from pathlib import Path

from analyze_prediction_accuracy import features, rank_candidate, CANDIDATES, case_audit, audit_archives

BASE = Path(__file__).parent


class AccuracyAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((BASE/'machines.json').read_text())
        cls.records = json.loads((BASE/'data-current.json').read_text())['machine_records']

    def test_target_and_future_outcomes_cannot_change_features_or_rankings(self):
        changed = copy.deepcopy(self.records)
        for row in changed:
            if row['date'] >= '2026-11-01':
                row.update(games=10000, bb=100, rb=100, difference=20000)
        for model in ('myj5', 'myj6'):
            before = features(self.config, self.records, '2026-11-01', model)
            after = features(self.config, changed, '2026-11-01', model)
            self.assertEqual(before, after)
            for candidate in CANDIDATES:
                self.assertEqual(rank_candidate(before, candidate), rank_candidate(after, candidate))

    def test_actual_case_snapshot_reproduction_and_all_machine_denominators(self):
        self.assertEqual(self.config, json.loads((BASE/'morning_machines.json').read_text()))
        result = case_audit(BASE, self.config, self.records)
        self.assertTrue(result['morning_models_reproduced_exactly'])
        self.assertEqual(result['combined_all39']['count'], 39)
        self.assertEqual(result['combined_selected']['total_difference'], 9955)
        self.assertEqual(result['combined_selected']['positive'], 5)
        supplied = {'myj5': [(2223,9133,45,41),(2237,9465,32,42),(2234,7028,26,31)],
                    'myj6': [(2202,9574,48,31),(2206,9750,33,41),(2219,9359,31,32)]}
        for model, expected in supplied.items():
            actual = [tuple(x['actual'][k] for k in ('number','games','bb','rb'))
                      for x in result['models'][model]['reasons']]
            self.assertEqual(actual, expected)

    def test_unfinished_day_is_not_counted_as_completed_saved_prediction(self):
        result = audit_archives(BASE, self.config, self.records, '2026-11-02')
        self.assertEqual(result['models']['myj5']['dates'], ['2026-10-27','2026-10-31','2026-11-01'])
        self.assertEqual(result['models']['myj6']['dates'], ['2026-10-31','2026-11-01'])
        self.assertFalse(next(c for c in result['checks'] if c['date']=='2026-11-02')['eligible_for_completed_audit'])


if __name__ == '__main__':
    unittest.main()
