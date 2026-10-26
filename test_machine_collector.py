import json
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock
from collect_machines import HEADERS, latest_report, merge_records, parse_tables, report_day, follow_public_link
from collect_sources import BASE, layout_on


class MachineTests(unittest.TestCase):
    def setUp(self):
        self.model = {"model_id": "myj5", "numbers": [2201, 2202]}
        self.table = [HEADERS, ["2201", "46", "8,424", "100.2%", "32", "24", "1/150", "1/263", "1/351"],
                      ["2202", "-185", "0", "-", "0", "0", "-", "-", "-"]]

    def parse(self):
        return parse_tables([self.table], self.model, "2026-10-25", "https://min-repo.com/3431462/?kishu=test")

    def test_values_and_zero(self):
        rows = self.parse()
        self.assertEqual((rows[0]["games"], rows[0]["bb"], rows[0]["rb"], rows[0]["difference"]), (8424, 32, 24, 46))
        self.assertEqual(rows[1]["games"], 0)
        self.assertEqual(rows[1]["difference"], -185)

    def test_missing_values_stay_unknown(self):
        self.table[1][4] = "-"
        self.assertIsNone(self.parse()[0]["bb"])

    def test_missing_number_rejected(self):
        self.table.pop()
        with self.assertRaises(ValueError): self.parse()

    def test_duplicate_rejected(self):
        self.table[2][0] = "2201"
        with self.assertRaises(ValueError): self.parse()

    def test_changed_columns_rejected(self):
        self.table[0] = ["台番", "G数"]
        with self.assertRaises(ValueError): self.parse()

    def test_impossible_counts_rejected(self):
        self.table[1][2] = "2"
        with self.assertRaises(ValueError): self.parse()

    def test_missing_does_not_erase_and_identity_separate(self):
        old = self.parse()[0]
        merged = merge_records([old], [{**old, "bb": None}, {**old, "date": "2026-10-27", "model_id": "myj6"}])
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["bb"], 32)

    def test_year_boundary_and_publication_date(self):
        self.assertEqual(report_day("12/31(木)", date(2027, 1, 1)), date(2026, 12, 31))
        self.assertIsNone(report_day("10/26(月)", date(2026, 10, 26)))
        self.assertIsNone(report_day("10/25 平均", date(2026, 10, 26)))
        self.assertEqual(latest_report([{"text":"10/25(日)","href":"https://min-repo.com/3431462/"}], date(2026,10,26))[0], date(2026,10,25))

    def test_layout_boundary(self):
        config = json.loads((BASE / "machines.json").read_text(encoding="utf-8"))
        before = {m["model_id"]: m for m in layout_on(config, "2026-10-26")}
        after = {m["model_id"]: m for m in layout_on(config, "2026-10-27")}
        self.assertEqual(len(before["myj5"]["numbers"]), 39)
        self.assertEqual(len(after["myj6"]["numbers"]), 20)
        self.assertEqual(len(after["myj5"]["numbers"]), 19)


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_clicks_observed_link_without_direct_navigation(self):
        url = 'https://min-repo.com/3431462/'
        page = MagicMock()
        anchors = page.locator.return_value
        anchors.evaluate_all = AsyncMock(return_value=['https://min-repo.com/', url])
        anchors.nth.return_value.click = AsyncMock()
        navigation = MagicMock()
        async def response(): return 'document-response'
        navigation.value = response()
        page.expect_navigation.return_value.__aenter__ = AsyncMock(return_value=navigation)
        page.expect_navigation.return_value.__aexit__ = AsyncMock(return_value=False)
        self.assertEqual(await follow_public_link(page, url), 'document-response')
        anchors.nth.assert_called_once_with(1)
        anchors.nth.return_value.click.assert_awaited_once()
        page.goto.assert_not_called()

    async def test_missing_link_never_falls_back_to_guessed_url(self):
        page = MagicMock()
        page.locator.return_value.evaluate_all = AsyncMock(return_value=[])
        with self.assertRaises(ValueError):
            await follow_public_link(page, 'https://min-repo.com/3431462/')
        page.expect_navigation.assert_not_called()
        page.goto.assert_not_called()


if __name__ == "__main__":
    unittest.main()
