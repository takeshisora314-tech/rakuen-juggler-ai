import copy
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evaluate_history import build_report, summarize
from forecast_engine import VERSION, WEIGHTS, make_forecast, snapshot_id


class HistoryReportTests(unittest.TestCase):
    def setUp(self):
        self.config = {'timezone': 'Asia/Tokyo', 'models': [{'id': 'test', 'name': 'Test',
                       'installations': [{'from': None, 'until': None, 'numbers': [1, 2, 3, 4]}]}]}
        self.rows = [{'date': f'2026-10-{day:02}', 'model_id': 'test', 'number': n,
                     'games': 5000, 'bb': 20, 'rb': 20, 'difference': 100 * (n - 2)}
                     for day in range(20, 27) for n in range(1, 5)]

    def snapshot(self):
        snapshot = make_forecast(self.config, self.rows, '2026-10-26', (), '2026-10-26T05:00:00+09:00')
        snapshot['snapshot_id'] = snapshot_id(snapshot)
        return snapshot

    def test_real_morning_results_and_replay_are_separate(self):
        result = build_report(self.config, self.rows, '2026-10-27', 7, [self.snapshot()])
        self.assertEqual(result['prospective']['models']['test']['paired_days'], 1)
        self.assertEqual(result['retrospective']['models']['test']['paired_days'], 4)
        for group in ('prospective', 'retrospective'):
            model = result[group]['models']['test']
            for metrics in model['strategies'].values():
                self.assertEqual(metrics['count'], model['paired_days'] * 3)

    def test_empty_evidence_has_no_fake_zero_rates(self):
        result = build_report(self.config, [], '2026-10-27', 7)
        self.assertEqual(result['prospective']['models']['test']['strategies'], {})
        model = result['retrospective']['models']['test']
        self.assertEqual(model['paired_days'], 0)
        self.assertEqual(model['status_counts'], {'no_prediction': 7})

    def test_missing_outcome_is_pending_and_excluded_for_every_strategy(self):
        rows = [r for r in self.rows if not (r['date'] == '2026-10-26' and r['number'] == 4)]
        result = build_report(self.config, rows, '2026-10-27', 7, [self.snapshot()])
        model = result['prospective']['models']['test']
        self.assertEqual(model['status_counts'], {'pending_results': 1})
        self.assertEqual(model['strategies'], {})

    def test_future_records_do_not_change_report_metrics_or_inputs(self):
        before = copy.deepcopy((self.config, self.rows))
        future = [{**r, 'date': '2026-10-27', 'difference': 999999} for r in self.rows[:4]]
        a = build_report(self.config, self.rows, '2026-10-27', 7)
        b = build_report(self.config, self.rows + future, '2026-10-27', 7)
        self.assertEqual(a['retrospective'], b['retrospective'])
        self.assertEqual(before, (self.config, self.rows))

    def test_snapshot_integrity_and_morning_time_required(self):
        for change in ({'date': '2026-10-25'}, {'kind': 'retrospective'}):
            with self.assertRaises(ValueError):
                build_report(self.config, self.rows, '2026-10-27', 7, [{**self.snapshot(), **change}])
        late = self.snapshot()
        late['created_at'] = '2026-10-26T07:00:00+09:00'
        late['snapshot_id'] = snapshot_id(late)
        with self.assertRaises(ValueError):
            build_report(self.config, self.rows, '2026-10-27', 7, [late])

    def test_legacy_pre_five_snapshot_remains_valid_before_deadline(self):
        early = self.snapshot()
        early['created_at'] = '2026-10-26T04:48:00+09:00'
        early['snapshot_id'] = snapshot_id(early)
        report = build_report(self.config, self.rows, '2026-10-27', 7, [early])
        self.assertEqual(report['prospective']['models']['test']['paired_days'], 1)

    def test_ambiguous_dates_and_invalid_metrics_are_not_counted(self):
        metrics = {'count': 3, 'positive_count': 2, 'positive_rate': 2 / 3,
                   'mean_difference': 100, 'lift_vs_eligible_mean': 20, 'low_play_count': 1}
        entry = {'date': '2026-10-26', 'kind': 'prospective', 'version': VERSION,
                 'models': {'test': {'status': 'complete', 'strategies': {s: metrics.copy() for s in WEIGHTS}}}}
        result = summarize([entry, copy.deepcopy(entry)], ['test'], 'prospective', '2026-10-01', '2026-10-27')
        self.assertEqual(result['ambiguous_dates_excluded'], 1)
        self.assertEqual(result['models']['test']['paired_days'], 0)
        entry['models']['test']['strategies']['rb']['positive_rate'] = float('nan')
        result = summarize([entry], ['test'], 'prospective', '2026-10-01', '2026-10-27')
        self.assertEqual(result['models']['test']['status_counts'], {'invalid_metrics': 1})

    def test_new_model_is_inactive_before_installation(self):
        config = copy.deepcopy(self.config)
        config['models'][0]['installations'][0]['from'] = '2026-10-26'
        report = build_report(config, [], '2026-10-27', 7)
        self.assertEqual(report['retrospective']['models']['test']['status_counts'], {'inactive': 6, 'no_prediction': 1})

    def test_invalid_windows_and_duplicate_records_fail(self):
        for days in (0, 91, True):
            with self.assertRaises(ValueError):
                build_report(self.config, self.rows, '2026-10-27', days)
        with self.assertRaises(ValueError):
            build_report(self.config, self.rows + [self.rows[0]], '2026-10-27', 7)

    def test_explicit_report_output_preserves_inputs_and_rejects_archive_paths(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            config_path = base / 'machines.json'
            data_path = base / 'data.json'
            config_path.write_text(json.dumps(self.config))
            data_path.write_text(json.dumps({'machine_records': self.rows}))
            before = (config_path.read_bytes(), data_path.read_bytes())
            script = str(Path(__file__).with_name('evaluate_history.py'))
            command = [sys.executable, script, '--base', str(base), '--as-of', '2026-10-27', '--days', '7', '--output']
            report_path = base / 'evaluation_report.json'
            subprocess.run(command + [str(report_path)], check=True, capture_output=True)
            self.assertEqual(json.loads(report_path.read_text())['calendar_days'], 7)
            for protected in (data_path, config_path, base / 'history/forecasts/x.json', base / 'history/evaluations/x.json'):
                result = subprocess.run(command + [str(protected)], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
            self.assertEqual(before, (config_path.read_bytes(), data_path.read_bytes()))
