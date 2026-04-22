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
        self.wave3 = load_json("reports/strategy_lab/wave3_robustness_summary.json")
        self.records = {
            item["strategy_id"]: item
            for item in self.triage["records"]
        }

    def test_batch_summary_counts_match_controlled_wave(self) -> None:
        self.assertEqual(self.batch_summary["eligible_strategy_count"], 4)
        self.assertEqual(self.batch_summary["tested_strategy_count"], 4)
        self.assertEqual(self.batch_summary["completed_backtests"], 4)
        self.assertEqual(self.batch_summary["dataset_count"], 4)
        self.assertEqual(self.batch_summary["symbols"], ["SPY", "QQQ", "NVDA", "TSLA"])
        self.assertEqual(
            self.batch_summary["triage_counts"],
            {
                "deferred_single_source_risk": 1,
                "modify_and_retest": 4,
            },
        )

    def test_triage_matrix_preserves_wave2_and_appends_wave3(self) -> None:
        wave3_by_id = {item["strategy_id"]: item for item in self.wave3["strategies"]}
        for strategy_id in ("SF-001", "SF-002", "SF-003", "SF-004"):
            record = self.records[strategy_id]
            self.assertEqual(record["current_wave"], "wave3")
            self.assertEqual(record["triage_status"], wave3_by_id[strategy_id]["triage_status"])
            self.assertEqual(record["best_variant_id"], "v0.2-candidate")
            history = {item["wave"]: item for item in record["history"]}
            self.assertIn("wave2", history)
            self.assertIn("wave3", history)
            self.assertEqual(history["wave2"]["spec_version"], "v0.1")
            self.assertEqual(history["wave2"]["best_variant_id"], "quality_filter")
            self.assertEqual(history["wave3"]["spec_version"], "v0.2-candidate")
            self.assertEqual(history["wave3"]["triage_status"], wave3_by_id[strategy_id]["triage_status"])
        self.assertEqual(self.records["SF-005"]["triage_status"], "deferred_single_source_risk")
        self.assertEqual(self.records["SF-005"]["sample_status"], "not_run")

    def test_strategy_summary_top_level_fields_are_present(self) -> None:
        for strategy_id in ("SF-001", "SF-002", "SF-003", "SF-004"):
            summary = load_json(f"reports/strategy_lab/{strategy_id}/summary.json")
            self.assertEqual(summary["strategy_id"], strategy_id)
            self.assertEqual(summary["backtest_status"], "completed")
            self.assertEqual(summary["sample_status"], "robust_candidate")
            self.assertEqual(summary["dataset_count"], 4)
            self.assertEqual(summary["dataset_paths"][0].startswith("local_data/longbridge_intraday/"), True)
            self.assertEqual(summary["symbol_count"], 4)
            self.assertGreaterEqual(summary["regime_count"], 2)
            self.assertEqual(summary["best_variant_id"], "quality_filter")
            self.assertEqual(summary["baseline_variant"]["cash_metrics"]["starting_capital"], "25000.0000")
            self.assertEqual(summary["baseline_variant"]["cash_metrics"]["risk_per_trade"], "100.0000")
            self.assertIsNotNone(summary["best_variant"]["cash_metrics"]["ending_equity"])
            self.assertEqual(summary["boundary"], "paper/simulated")
        deferred = load_json("reports/strategy_lab/SF-005/summary.json")
        self.assertEqual(deferred["triage_status"], "deferred_single_source_risk")
        self.assertEqual(deferred["backtest_status"], "not_run")

    def test_final_report_mentions_wave_scope_and_deferred_strategy(self) -> None:
        report = read_text("reports/strategy_lab/final_strategy_factory_report.md")
        self.assertIn("dataset_count", report)
        self.assertIn("SPY, QQQ, NVDA, TSLA", report)
        self.assertIn("coverage_window", report)
        self.assertIn("SF-005", report)
        self.assertIn("deferred_single_source_risk", report)
        self.assertIn("paper/simulated", report)
        self.assertIn("not live / not real-money", report)

        trade_report = read_text("reports/strategy_lab/final_strategy_factory_trade_report.md")
        self.assertIn("Trading-Style Batch Report", trade_report)
        self.assertIn("Baseline Trades", trade_report)
        self.assertIn("Best Variant", trade_report)
        self.assertIn("capital_model", trade_report)

        cash_report = read_text("reports/strategy_lab/final_strategy_factory_cash_report.md")
        self.assertIn("Cash-Equity Batch Report", cash_report)
        self.assertIn("starting_capital", cash_report)
        self.assertIn("risk_per_trade", cash_report)
        self.assertIn("Ending Equity", cash_report)
        self.assertIn("Net PnL", cash_report)


if __name__ == "__main__":
    unittest.main()
