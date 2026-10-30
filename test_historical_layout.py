import json
import unittest

from collect_sources import BASE, layout_on
from collect_machines import HEADERS, parse_tables


class HistoricalLayoutTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((BASE / 'machines.json').read_text())

    def layout(self, day):
        return {model['model_id']: model for model in layout_on(self.config, day)}

    def test_reported_extra_numbers_only_on_verified_day(self):
        for model_id, extra in [('neoim', {3194, 3195, 3196, 3197}), ('funky2', {3198})]:
            before = set(self.layout('2026-09-30')[model_id]['numbers'])
            during = set(self.layout('2026-10-01')[model_id]['numbers'])
            after = set(self.layout('2026-10-02')[model_id]['numbers'])
            self.assertEqual(during, before | extra)
            self.assertEqual(before, after)

    def test_report_table_can_be_collected_without_remapping(self):
        for model_id in ('neoim', 'funky2'):
            model = self.layout('2026-10-01')[model_id]
            table = [HEADERS] + [[str(n), '0', '1000', '-', '3', '2', '-', '-', '-'] for n in model['numbers']]
            rows = parse_tables([table], model, '2026-10-01', 'https://min-repo.com/3384763/')
            self.assertEqual({r['number'] for r in rows}, set(model['numbers']))

    def test_foreign_numbers_still_rejected(self):
        model = self.layout('2026-10-01')['funky2']
        table = [HEADERS, ['9999', '0', '1000', '-', '3', '2', '-', '-', '-']]
        with self.assertRaises(ValueError):
            parse_tables([table], model, '2026-10-01', 'https://min-repo.com/3384763/', allow_partial=True)

    def test_replacement_model_history_stays_separate(self):
        self.assertNotIn('myj6', self.layout('2026-10-26'))
        self.assertEqual(len(self.layout('2026-10-26')['myj5']['numbers']), 39)
        self.assertEqual(len(self.layout('2026-10-27')['myj5']['numbers']), 19)
        self.assertEqual(len(self.layout('2026-10-27')['myj6']['numbers']), 20)
