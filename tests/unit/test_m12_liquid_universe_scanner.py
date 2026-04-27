from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import m12_liquid_universe_scanner_lib as MODULE


OUTPUT_DIR = MODULE.M12_5_DIR


class M12LiquidUniverseScannerTests(unittest.TestCase):
    def test_universe_size_and_tier_a_scope_are_locked(self) -> None:
        config = MODULE.load_scanner_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_liquid_universe_scanner(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-27T13:00:00Z",
            )
            universe = json.loads((Path(tmp) / "m12_5_universe_definition.json").read_text(encoding="utf-8"))
            inventory = json.loads((Path(tmp) / "m12_5_cache_inventory.json").read_text(encoding="utf-8"))

        self.assertGreaterEqual(universe["symbol_count"], 100)
        self.assertLessEqual(universe["symbol_count"], 200)
        self.assertEqual(len(inventory["items"]), universe["symbol_count"] * 4)
        self.assertTrue(any(item["lineage"] == "derived_from_5m" and item["cache_exists"] for item in inventory["items"]))
        self.assertEqual(summary["strategy_scope"], ["M10-PA-001", "M10-PA-002", "M10-PA-012"])
        self.assertIn("M10-PA-008", summary["excluded_strategy_ids"])
        self.assertEqual(summary["request_policy"]["live_requests_used"], 0)

    def test_config_rejects_execution_boundary_fields(self) -> None:
        config_payload = json.loads(MODULE.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        config_payload["broker_connection"] = False
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "scanner.json"
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.load_scanner_config(config_path)

    def test_candidates_are_traceable_and_do_not_include_excluded_strategies(self) -> None:
        config = MODULE.load_scanner_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_liquid_universe_scanner(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-27T13:00:00Z",
            )
            with (Path(tmp) / "m12_5_scanner_candidates.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), summary["candidate_count"])
        self.assertTrue(rows, "local cache should produce at least one scanner candidate")
        self.assertLessEqual({row["strategy_id"] for row in rows}, {"M10-PA-001", "M10-PA-002", "M10-PA-012"})
        self.assertNotIn("M10-PA-008", {row["strategy_id"] for row in rows})
        for row in rows:
            self.assertTrue(row["entry_price"])
            self.assertTrue(row["stop_price"])
            self.assertTrue(row["target_price"])
            self.assertIn("backtest_specs", row["spec_ref"])
            self.assertTrue(row["source_refs"])
            self.assertTrue(row["data_path"])
            self.assertTrue(row["data_checksum"])
            self.assertEqual(row["queue_action"], "eligible_for_read_only_observation")

    def test_missing_data_is_deferred_without_fake_candidates(self) -> None:
        config = MODULE.load_scanner_config()
        with tempfile.TemporaryDirectory() as empty_data, tempfile.TemporaryDirectory() as output_dir:
            summary = MODULE.run_m12_liquid_universe_scanner(
                replace(config, local_data_roots=(Path(empty_data),), output_dir=Path(output_dir)),
                generated_at="2026-04-27T13:00:00Z",
            )
            with (Path(output_dir) / "m12_5_scanner_candidates.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            deferred = json.loads((Path(output_dir) / "m12_5_deferred_inputs.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["candidate_count"], 0)
        self.assertEqual(rows, [])
        self.assertEqual(len(deferred["items"]), summary["universe_symbol_count"])
        self.assertTrue(all(item["reason"] == "symbol_unscanned_no_local_cache" for item in deferred["items"]))

    def test_generated_outputs_keep_readonly_boundary_and_lineage_counts(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_liquid_universe_scanner.py before full validation")
        summary = json.loads((OUTPUT_DIR / "m12_5_scanner_summary.json").read_text(encoding="utf-8"))
        candidates = (OUTPUT_DIR / "m12_5_scanner_candidates.csv").read_text(encoding="utf-8")
        combined = "\n".join(path.read_text(encoding="utf-8") for path in OUTPUT_DIR.glob("m12_5_*") if path.is_file())

        self.assertEqual(summary["strategy_scope"], ["M10-PA-001", "M10-PA-002", "M10-PA-012"])
        self.assertIn("derived_from_5m", summary["lineage_counts"])
        self.assertNotIn("order_id", combined)
        self.assertNotIn("fill_price", combined)
        self.assertNotIn("position", combined)
        self.assertNotIn("cash", combined)
        self.assertNotIn("live-ready", combined.lower())
        self.assertNotIn("broker_connection", combined)
        self.assertNotIn("real_orders", combined)
        self.assertNotIn("live_execution", combined)
        self.assertNotIn("paper_trading_approval", combined)
        self.assertNotIn("M10-PA-008", candidates)


if __name__ == "__main__":
    unittest.main()
