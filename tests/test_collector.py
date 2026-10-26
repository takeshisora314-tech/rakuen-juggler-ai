import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import collect_sources as collector


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((collector.BASE / "machines.json").read_text(encoding="utf-8"))

    def test_before_replacement(self):
        models = {m["model_id"]: m for m in collector.layout_on(self.config, "2026-10-26")}
        self.assertNotIn("myj6", models)
        self.assertEqual(models["myj5"]["numbers"], list(range(2201, 2240)))

    def test_replacement_and_future(self):
        for day in ("2026-10-27", "2027-01-01"):
            models = {m["model_id"]: m for m in collector.layout_on(self.config, day)}
            self.assertEqual(models["myj6"]["numbers"], list(range(2201, 2221)))
            self.assertEqual(models["myj5"]["numbers"], list(range(2221, 2240)))
            self.assertEqual(len(models), 8)

    def test_historical_identity_and_other_models(self):
        self.assertEqual(collector.model_for_number(self.config, "2026-10-26", 2201), "myj5")
        self.assertEqual(collector.model_for_number(self.config, "2026-10-27", 2201), "myj6")
        self.assertEqual(collector.model_for_number(self.config, "2026-10-27", 2221), "myj5")
        before = collector.layout_on(self.config, "2026-10-26")
        after = collector.layout_on(self.config, "2026-10-27")
        self.assertEqual([m for m in before if not m["model_id"].startswith("myj")],
                         [m for m in after if not m["model_id"].startswith("myj")])

    def test_duplicate_rejected(self):
        config = copy.deepcopy(self.config)
        config["models"][1]["installations"][1]["numbers"].append(2201)
        with self.assertRaises(ValueError):
            collector.layout_on(config, "2026-10-27")

    @patch.object(collector, "check_sources", return_value={"example": {"ok": True}})
    def test_jst_boundary_and_history_preserved(self, check):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "data.json"
            legacy = [{"date": "2026-10-26", "model_id": "myj5", "number": 2201, "bb": 10}]
            data_path.write_text(json.dumps({"records": legacy}), encoding="utf-8")
            history = root / "history"
            before = datetime(2026, 10, 26, 14, 59, 59, tzinfo=timezone.utc)
            after = datetime(2026, 10, 26, 15, 0, 0, tzinfo=timezone.utc)
            first = collector.collect(data_path, collector.BASE / "machines.json", history, before)
            second = collector.collect(data_path, collector.BASE / "machines.json", history, after)
            self.assertEqual(first["layout"]["date"], "2026-10-26")
            self.assertEqual(second["layout"]["date"], "2026-10-27")
            self.assertEqual(second["records"], legacy)
            self.assertEqual(len(list(history.rglob("*.json"))), 2)
            self.assertFalse(second["machine_results_available"])
            self.assertEqual(second["collection_stage"], "source_checks_only")
            with self.assertRaises(FileExistsError):
                collector.collect(data_path, collector.BASE / "machines.json", history, after)

    @patch.object(collector.requests, "get")
    def test_network_error_does_not_prevent_other_sources(self, get):
        get.side_effect = [collector.requests.Timeout("test timeout"),
                           SimpleNamespace(ok=False, status_code=403),
                           SimpleNamespace(ok=True, status_code=200)]
        statuses = collector.check_sources("2026-10-26T00:00:00+00:00")
        self.assertEqual(len(statuses), 3)
        self.assertFalse(statuses["min-repo"]["ok"])
        self.assertEqual(statuses["ana-slo"]["status"], 403)
        self.assertTrue(statuses["d-delta"]["ok"])
        self.assertEqual(get.call_count, 3)

    def test_invalid_existing_data_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "data.json"
            data_path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                collector.collect(data_path, collector.BASE / "machines.json", root / "history")
            self.assertEqual(data_path.read_text(encoding="utf-8"), "[]")


if __name__ == "__main__":
    unittest.main()
