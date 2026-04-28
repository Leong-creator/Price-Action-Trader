from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_20_visual_detector_implementation_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1220VisualDetectorImplementationTests(unittest.TestCase):
    def test_temp_run_creates_machine_detector_events_and_unified_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_20_visual_detector_implementation(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(tmp),
            )
            with (Path(tmp) / "m12_20_detector_events.csv").open(encoding="utf-8") as handle:
                events = list(csv.DictReader(handle))
            queue = json.loads((Path(tmp) / "m12_20_unified_strategy_queue.json").read_text(encoding="utf-8"))

        self.assertEqual(set(summary["machine_detector_strategy_ids"]), {"M10-PA-004", "M10-PA-007"})
        self.assertGreater(summary["detector_event_count"], 0)
        self.assertGreater(summary["detector_event_count_by_strategy"].get("M10-PA-004", 0), 0)
        self.assertGreater(summary["detector_event_count_by_strategy"].get("M10-PA-007", 0), 0)
        self.assertTrue(events)
        self.assertEqual({row["strategy_id"] for row in events}, {"M10-PA-004", "M10-PA-007"})
        for row in events:
            self.assertTrue(row["event_id"])
            self.assertTrue(row["source_cache_path"].endswith("_longbridge.csv"))
            self.assertEqual(len(row["source_checksum"]), 64)
            self.assertTrue(row["source_refs"].startswith("["))
            self.assertIn("m12_19_detector_rules.json", row["spec_ref"])
            self.assertEqual(row["source_lineage"], "native_daily_cache")
            self.assertEqual(row["not_trade_signal"], "true")
            self.assertEqual(row["paper_simulated_only"], "true")
            self.assertEqual(row["broker_connection"], "false")
            self.assertEqual(row["real_orders"], "false")
            self.assertEqual(row["live_execution"], "false")
            self.assertIn("automatic_reason", row)
        daily_ids = set(queue["daily_test_strategy_ids"])
        self.assertEqual(daily_ids, {"M10-PA-001", "M10-PA-002", "M10-PA-012", "M12-FTD-001"})
        by_id = {row["strategy_id"]: row for row in queue["items"]}
        self.assertEqual(by_id["M10-PA-004"]["unified_queue"], "machine_detector_observation")
        self.assertEqual(by_id["M10-PA-007"]["unified_queue"], "machine_detector_observation")
        self.assertEqual(by_id["M12-FTD-001"]["unified_queue"], "daily_readonly_test")
        self.assertIn("M12-SRC-001", by_id["M12-FTD-001"]["source_candidate_links"])

    def test_event_ids_are_deterministic_for_same_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            MODULE.run_m12_20_visual_detector_implementation(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(a),
            )
            MODULE.run_m12_20_visual_detector_implementation(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(b),
            )
            with (Path(a) / "m12_20_detector_events.csv").open(encoding="utf-8") as handle:
                a_events = list(csv.DictReader(handle))
            with (Path(b) / "m12_20_detector_events.csv").open(encoding="utf-8") as handle:
                b_events = list(csv.DictReader(handle))

        self.assertEqual([row["event_id"] for row in a_events], [row["event_id"] for row in b_events])

    def test_checked_in_artifacts_are_client_readable_and_safe(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_20_visual_detector_implementation.py first")
        expected = {
            "m12_20_visual_detector_run_summary.json",
            "m12_20_input_manifest.json",
            "m12_20_deferred_inputs.json",
            "m12_20_detector_events.jsonl",
            "m12_20_detector_events.csv",
            "m12_20_detector_quality_report.md",
            "m12_20_unified_strategy_queue.json",
            "m12_20_unified_strategy_queue.csv",
            "m12_20_unified_strategy_queue.md",
            "m12_20_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_20_visual_detector_run_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["daily_test_strategy_ids"], ["M10-PA-001", "M10-PA-002", "M10-PA-012", "M12-FTD-001"])
        self.assertFalse(summary["paper_trading_approval"])
        report = (OUTPUT_DIR / "m12_20_detector_quality_report.md").read_text(encoding="utf-8")
        for text in ("用人话结论", "候选图形", "不是买卖信号", "宽通道", "第二腿"):
            self.assertIn(text, report)
        queue_md = (OUTPUT_DIR / "m12_20_unified_strategy_queue.md").read_text(encoding="utf-8")
        self.assertIn("不再把 16 条 M10 策略和 6 条来源回看候选分开讲", queue_md)
        all_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in OUTPUT_DIR.glob("*") if path.is_file())
        for forbidden in (
            "live-ready",
            "real_orders=true",
            "broker_connection=true",
            "paper approval",
            "order_id",
            "fill_id",
            "account_id",
            "cash_balance",
            "position_qty",
        ):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
