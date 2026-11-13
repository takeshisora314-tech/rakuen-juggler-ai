import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from collect_sources import layout_on, write_json
from detect_layout import confirm_layout


class DetectLayoutTests(unittest.TestCase):
    def test_retries_are_not_new_days_and_history_is_preserved(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            config = {'models': [
                {'id': 'happy8', 'name': 'Happy', 'installations': [
                    {'from': None, 'until': None, 'numbers': [219, 220]}]},
                {'id': 'myj6', 'name': 'My VI', 'installations': [
                    {'from': None, 'until': None, 'numbers': [2210, 2211]}]},
            ]}
            write_json(base/'machines.json', config)
            observed = {'happy8': [{'number': 220}], 'myj6': [{'number': 2210}, {'number': 2211}]}
            first, second = date(2026, 11, 20), date(2026, 11, 21)
            self.assertFalse(confirm_layout(base, config, first, 'first', observed))
            self.assertFalse(confirm_layout(base, config, first, 'first', observed))
            self.assertFalse(confirm_layout(base, config, second, 'second', {'happy8': observed['happy8']}))
            self.assertEqual(confirm_layout(base, config, second, 'second', observed), {'happy8': [220]})
            self.assertEqual(layout_on(config, first)[0]['numbers'], [219, 220])
            self.assertEqual(layout_on(config, second)[0]['numbers'], [220])
            self.assertEqual(json.loads((base/'machines.json').read_text()), config)

    def test_transfer_requires_unique_ownership(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            config = {'models': [
                {'id': model, 'name': model, 'installations': [
                    {'from': None, 'until': None, 'numbers': numbers}]}
                for model, numbers in [('a', [1, 2]), ('b', [3])]
            ]}
            day = date(2026, 11, 21)
            duplicate = {'a': [{'number': 1}, {'number': 2}], 'b': [{'number': 2}, {'number': 3}]}
            self.assertFalse(confirm_layout(base, config, day, 'report', duplicate))
            duplicate['a'].pop()
            self.assertEqual(confirm_layout(base, config, day, 'report', duplicate), {'a': [1], 'b': [2, 3]})
