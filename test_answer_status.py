import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from check_answers import answer_status, run
from forecast_engine import make_forecast, snapshot_id


class AnswerStatusTests(unittest.TestCase):
    def setUp(self):
        self.config = {'timezone': 'Asia/Tokyo', 'models': [{'id': 'myj5', 'name': 'V',
                       'installations': [{'from': None, 'until': None, 'numbers': [1, 2, 3]}]}]}
        self.rows = [{'date': f'2026-10-{day}', 'model_id': 'myj5', 'number': n,
                     'games': 5000, 'bb': 20, 'rb': 20, 'difference': n * 100}
                     for day in range(23, 27) for n in (1, 2, 3)]
        self.snapshot = make_forecast(self.config, self.rows, '2026-10-26', (), '2026-10-26T05:03:00+09:00')
        self.snapshot['snapshot_id'] = snapshot_id(self.snapshot)

    def status(self, snapshot=True, rows=None):
        return answer_status(self.config, self.rows if rows is None else rows,
                             self.snapshot if snapshot else None, '2026-10-26', '2026-10-26T23:30:00+09:00')

    def test_missing_forecast_is_not_complete(self):
        result = self.status(False)
        self.assertEqual(result['status'], 'missing_forecast')
        self.assertEqual(result['complete_models'], 0)

    def test_no_eligible_prediction_is_distinct_from_missing_snapshot(self):
        snapshot = make_forecast(self.config, [], '2026-10-26', (), '2026-10-26T05:03:00+09:00')
        snapshot['snapshot_id'] = snapshot_id(snapshot)
        result = answer_status(self.config, [], snapshot, '2026-10-26', '2026-10-26T23:30:00+09:00')
        self.assertEqual(result['status'], 'no_predictions')

    def test_missing_actual_remains_pending_until_all_eligible_rows_arrive(self):
        incomplete = [r for r in self.rows if not (r['date'] == '2026-10-26' and r['number'] == 3)]
        result = self.status(rows=incomplete)
        self.assertEqual((result['status'], result['pending_models']), ('pending_results', 1))
        self.assertEqual(self.status()['status'], 'complete')

    def test_one_complete_model_does_not_hide_another_pending_model(self):
        config = copy.deepcopy(self.config)
        config['models'].append({'id': 'mr', 'name': 'Mr', 'installations': [{'from': None, 'until': None, 'numbers': [4, 5, 6]}]})
        rows = self.rows + [{**r, 'model_id': 'mr', 'number': r['number'] + 3} for r in self.rows]
        snapshot = make_forecast(config, rows, '2026-10-26', (), '2026-10-26T05:03:00+09:00')
        snapshot['snapshot_id'] = snapshot_id(snapshot)
        rows = [r for r in rows if not (r['date'] == '2026-10-26' and r['number'] == 6)]
        result = answer_status(config, rows, snapshot, '2026-10-26', '2026-10-26T23:30:00+09:00')
        self.assertEqual((result['status'], result['complete_models'], result['pending_models']), ('partial_results', 1, 1))

    def test_mismatched_or_modified_snapshot_is_rejected(self):
        self.snapshot['date'] = '2026-10-25'
        with self.assertRaises(ValueError):
            self.status()

    def test_deadline_and_timezone_are_checked(self):
        self.snapshot['created_at'] = '2026-10-26T07:00:00+09:00'
        self.snapshot['snapshot_id'] = snapshot_id(self.snapshot)
        with self.assertRaises(ValueError):
            self.status()

    def test_inputs_and_saved_forecast_are_preserved(self):
        before = copy.deepcopy((self.config, self.rows, self.snapshot))
        self.status()
        self.assertEqual(before, (self.config, self.rows, self.snapshot))

    def test_target_day_changes_at_23_and_midnight_retains_previous_day(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'machines.json').write_text(json.dumps(self.config))
            (base / 'data.json').write_text(json.dumps({'machine_records': self.rows}))
            before = (base / 'data.json').read_bytes()
            for hour, expected in [(13, '2026-10-25'), (14, '2026-10-26'), (15, '2026-10-26')]:
                result = run(base, datetime(2026, 10, 26, hour, tzinfo=timezone.utc))
                self.assertEqual(result['date'], expected)
                self.assertEqual(result['status'], 'missing_forecast')
            self.assertEqual(before, (base / 'data.json').read_bytes())
