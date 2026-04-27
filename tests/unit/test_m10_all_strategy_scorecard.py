from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.m10_all_strategy_scorecard_lib import M10_12_DIR, M10_7_REQUIRED_METRICS, run_m10_12_all_strategy_scorecard


class M10AllStrategyScorecardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = run_m10_12_all_strategy_scorecard()

    def test_summary_covers_all_16_clean_room_strategies(self) -> None:
        summary = self.summary

        self.assertEqual(summary["strategy_count"], 16)
        self.assertTrue(summary["paper_simulated_only"])
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["paper_trading_approval"])
        self.assertEqual(
            summary["status_counts"],
            {
                "completed_capital_test": 8,
                "needs_definition_fix": 3,
                "research_only": 2,
                "visual_only_not_backtestable": 1,
                "supporting_rule": 2,
            },
        )

    def test_metrics_have_one_row_per_strategy_and_client_fields(self) -> None:
        metrics_path = M10_12_DIR / "m10_12_all_strategy_metrics.csv"
        with metrics_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 16)
        self.assertEqual({row["strategy_id"] for row in rows}, {f"M10-PA-{idx:03d}" for idx in range(1, 17)})
        for row in rows:
            self.assertIn(row["machine_status"], self.summary["status_counts"])
            self.assertNotEqual(row["client_status"], "")
            self.assertNotEqual(row["decision_reason"], "")

        tested = [row for row in rows if row["machine_status"] == "completed_capital_test"]
        for field in M10_7_REQUIRED_METRICS:
            self.assertTrue(all(row[field] != "" for row in tested))
        self.assertTrue(all(row["metric_completeness"] == "full_m10_7_required_metrics" for row in tested))

        pa005 = next(row for row in rows if row["strategy_id"] == "M10-PA-005")
        self.assertEqual(pa005["machine_status"], "needs_definition_fix")
        self.assertEqual(pa005["metric_completeness"], "partial_retest_metrics")
        self.assertIn("does not persist full M10.7 metric set", pa005["metric_gap_note"])
        self.assertEqual(pa005["portfolio_eligible"], "false")

    def test_decision_matrix_preserves_expected_statuses(self) -> None:
        matrix = json.loads((M10_12_DIR / "m10_12_strategy_decision_matrix.json").read_text(encoding="utf-8"))
        rows = {row["strategy_id"]: row for row in matrix["strategies"]}

        self.assertEqual(rows["M10-PA-001"]["machine_status"], "completed_capital_test")
        self.assertEqual(rows["M10-PA-002"]["machine_status"], "completed_capital_test")
        self.assertEqual(rows["M10-PA-005"]["machine_status"], "needs_definition_fix")
        self.assertEqual(rows["M10-PA-012"]["machine_status"], "completed_capital_test")
        self.assertEqual(rows["M10-PA-014"]["machine_status"], "supporting_rule")
        self.assertEqual(rows["M10-PA-015"]["machine_status"], "supporting_rule")
        self.assertEqual(rows["M10-PA-006"]["machine_status"], "research_only")
        self.assertEqual(rows["M10-PA-016"]["machine_status"], "research_only")
        self.assertFalse(matrix["broker_connection"])
        self.assertFalse(matrix["real_orders"])
        self.assertFalse(matrix["paper_trading_approval"])

    def test_portfolio_proxy_uses_client_business_policy(self) -> None:
        portfolio = self.summary["portfolio_proxy"]

        self.assertEqual(portfolio["portfolio_initial_capital"], "100000.00")
        self.assertEqual(portfolio["max_simultaneous_risk_percent"], "4.00")
        self.assertEqual(portfolio["max_simultaneous_positions"], 8)
        self.assertEqual(
            portfolio["selected_strategy_ids"],
            [
                "M10-PA-001",
                "M10-PA-002",
                "M10-PA-012",
                "M10-PA-013",
                "M10-PA-003",
                "M10-PA-008",
                "M10-PA-009",
                "M10-PA-011",
            ],
        )
        self.assertEqual(portfolio["selection_rule"], "completed_capital_test_only_in_priority_order")
        self.assertIn("M10-PA-005", {item["strategy_id"] for item in portfolio["excluded_priority_candidates"]})
        self.assertIn("not_executable", portfolio["proxy_method"])
        self.assertIn("not one timestamp-synchronized portfolio", portfolio["not_executable_reason"])
        self.assertNotEqual(portfolio["proxy_final_equity"], "")
        self.assertNotEqual(portfolio["proxy_net_profit"], "")

    def test_external_output_dir_is_supported_for_cli_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = run_m10_12_all_strategy_scorecard(Path(tmpdir))

        self.assertTrue(summary["output_dir"].startswith("/"))
        self.assertEqual(summary["strategy_count"], 16)

    def test_reports_keep_legacy_and_live_boundaries(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in [
                M10_12_DIR / "m10_12_all_strategy_scorecard_summary.json",
                M10_12_DIR / "m10_12_strategy_decision_matrix.json",
                M10_12_DIR / "m10_12_all_strategy_scorecard.md",
                M10_12_DIR / "m10_12_portfolio_simulation_report.md",
                M10_12_DIR / "m10_12_client_final_report.md",
            ]
        )
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true"):
            self.assertNotIn(forbidden.lower(), lowered)


if __name__ == "__main__":
    unittest.main()
