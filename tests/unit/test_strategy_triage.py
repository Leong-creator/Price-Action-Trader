from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import load_json, read_text


class TestStrategyTriage(unittest.TestCase):
    def setUp(self) -> None:
        self.batch_summary = load_json("reports/strategy_lab/backtest_batch_summary.json")
        self.triage = load_json("reports/strategy_lab/strategy_triage_matrix.json")
        self.records = {
            item["strategy_id"]: item
            for item in self.triage["records"]
        }

    def test_batch_summary_counts_match_controlled_wave(self) -> None:
        self.assertEqual(self.batch_summary["eligible_strategy_count"], 4)
        self.assertEqual(self.batch_summary["tested_strategy_count"], 4)
        self.assertEqual(self.batch_summary["completed_backtests"], 4)
        self.assertEqual(
            self.batch_summary["triage_counts"],
            {
                "deferred_single_source_risk": 1,
                "insufficient_sample": 3,
                "modify_and_retest": 1,
            },
        )

    def test_triage_matrix_matches_expected_statuses(self) -> None:
        self.assertEqual(self.records["SF-001"]["triage_status"], "modify_and_retest")
        self.assertEqual(self.records["SF-001"]["sample_status"], "exploratory_probe")
        self.assertEqual(self.records["SF-001"]["best_variant_id"], "quality_filter")
        for strategy_id in ("SF-002", "SF-003", "SF-004"):
            self.assertEqual(self.records[strategy_id]["triage_status"], "insufficient_sample")
            self.assertEqual(self.records[strategy_id]["sample_status"], "insufficient_sample")
        self.assertEqual(self.records["SF-005"]["triage_status"], "deferred_single_source_risk")
        self.assertEqual(self.records["SF-005"]["sample_status"], "not_run")

    def test_strategy_summary_top_level_fields_are_present(self) -> None:
        for strategy_id in ("SF-001", "SF-002", "SF-003", "SF-004"):
            summary = load_json(f"reports/strategy_lab/{strategy_id}/summary.json")
            self.assertEqual(summary["strategy_id"], strategy_id)
            self.assertEqual(summary["backtest_status"], "completed")
            self.assertIn(summary["sample_status"], {"exploratory_probe", "insufficient_sample"})
            self.assertIsNotNone(summary["best_variant_id"])
            self.assertEqual(summary["boundary"], "paper/simulated")
        deferred = load_json("reports/strategy_lab/SF-005/summary.json")
        self.assertEqual(deferred["triage_status"], "deferred_single_source_risk")
        self.assertEqual(deferred["backtest_status"], "not_run")

    def test_final_report_mentions_wave_scope_and_deferred_strategy(self) -> None:
        report = read_text("reports/strategy_lab/final_strategy_factory_report.md")
        self.assertIn("eligible_strategy_count", report)
        self.assertIn("tested_strategy_count", report)
        self.assertIn("SF-005", report)
        self.assertIn("deferred_single_source_risk", report)
        self.assertIn("paper/simulated", report)
        self.assertIn("not live / not real-money", report)


if __name__ == "__main__":
    unittest.main()
