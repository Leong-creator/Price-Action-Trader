from __future__ import annotations

import json
import unittest

from scripts.m10_read_only_runbook_lib import M10_13_DIR, run_m10_13_read_only_runbook


class M10ReadOnlyObservationRunbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = run_m10_13_read_only_runbook()
        cls.queue = json.loads((M10_13_DIR / "m10_13_observation_candidate_queue.json").read_text(encoding="utf-8"))

    def test_primary_queue_contains_only_screened_completed_capital_tests(self) -> None:
        queue = self.queue
        self.assertEqual(
            [item["strategy_id"] for item in queue["primary_observation_queue"]],
            ["M10-PA-001", "M10-PA-002", "M10-PA-012", "M10-PA-008", "M10-PA-009"],
        )
        self.assertEqual(queue["selection_policy"]["primary_queue_rule"], "completed_capital_test AND portfolio_eligible=true AND aggregate return > 0 AND timeframe return > 0")
        self.assertIn("extends the M10.5 Wave A observation plan", queue["selection_policy"]["m10_5_relationship"])
        self.assertFalse(queue["boundaries"]["broker_connection"])
        self.assertFalse(queue["boundaries"]["real_orders"])
        self.assertFalse(queue["boundaries"]["live_execution"])
        self.assertFalse(queue["boundaries"]["paper_trading_approval"])

    def test_timeframe_selection_uses_positive_timeframe_results_only(self) -> None:
        rows = {item["strategy_id"]: item for item in self.queue["primary_observation_queue"]}

        self.assertEqual(rows["M10-PA-001"]["timeframes"], ["1d", "15m", "5m"])
        self.assertEqual(rows["M10-PA-002"]["timeframes"], ["1d", "1h", "15m"])
        self.assertEqual(rows["M10-PA-012"]["timeframes"], ["15m", "5m"])
        self.assertEqual(rows["M10-PA-008"]["timeframes"], ["1h", "15m", "5m"])
        self.assertEqual(rows["M10-PA-009"]["timeframes"], ["1h", "15m"])
        self.assertEqual([item["timeframe"] for item in rows["M10-PA-001"]["reserve_timeframes"]], ["1h"])
        self.assertEqual([item["timeframe"] for item in rows["M10-PA-002"]["reserve_timeframes"]], ["5m"])
        for item in rows.values():
            for timeframe in item["selected_timeframe_metrics"]:
                self.assertGreater(float(timeframe["return_percent"]), 0.0)

    def test_excluded_and_watchlist_paths_are_explicit(self) -> None:
        excluded = self.queue["excluded_strategy_ids"]
        self.assertIn("M10-PA-005", {item["strategy_id"] for item in excluded["needs_definition_fix"]})
        self.assertIn("M10-PA-013", {item["strategy_id"] for item in excluded["non_positive_aggregate"]})
        self.assertIn("M10-PA-010", {item["strategy_id"] for item in excluded["visual_only_not_backtestable"]})
        self.assertIn("M10-PA-014", {item["strategy_id"] for item in excluded["supporting_rule"]})
        self.assertIn("M10-PA-016", {item["strategy_id"] for item in excluded["research_only"]})
        self.assertIn("M10-PA-013", {item["strategy_id"] for item in self.queue["watchlist_deferred"]})

    def test_visual_wave_b_candidates_keep_manual_review_requirement(self) -> None:
        rows = {item["strategy_id"]: item for item in self.queue["primary_observation_queue"]}

        self.assertTrue(rows["M10-PA-008"]["requires_visual_review_context"])
        self.assertTrue(rows["M10-PA-009"]["requires_visual_review_context"])
        self.assertEqual(rows["M10-PA-008"]["selection_basis"], "m10_11_wave_b_plus_m10_12_screen")
        self.assertIn("manual_visual_context_review_required", rows["M10-PA-008"]["review_requirements"])
        self.assertFalse(rows["M10-PA-001"]["requires_visual_review_context"])
        self.assertEqual(rows["M10-PA-001"]["selection_basis"], "m10_5_wave_a_plan_plus_m10_12_screen")

    def test_pause_conditions_cover_contract_schema_lineage_input_and_status(self) -> None:
        pause_codes = {item["code"] for item in self.queue["pause_conditions"]}

        self.assertTrue(
            {
                "queue_contract_violation",
                "schema_or_ref_failure",
                "lineage_or_timing_drift",
                "input_missing_or_lineage_unknown",
                "deferred_input_streak",
                "definition_density_drift",
                "review_status_regression",
                "live_or_broker_request",
            }.issubset(pause_codes)
        )

    def test_reports_contain_weekly_client_sections_and_guardrails(self) -> None:
        runbook = (M10_13_DIR / "m10_13_read_only_observation_runbook.md").read_text(encoding="utf-8")
        template = (M10_13_DIR / "m10_13_weekly_observation_template.md").read_text(encoding="utf-8")
        summary = json.loads((M10_13_DIR / "m10_13_read_only_observation_runbook_summary.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["primary_strategy_count"], 5)
        self.assertEqual(summary["primary_strategy_timeframe_count"], 13)
        for text in ("本周触发策略", "历史基线指标", "观察质量指标", "策略和标的分布", "资金曲线偏离", "暂停条件"):
            self.assertIn(text, template)
        for metric in ("Initial Capital", "Final Equity", "Net Profit", "Return %", "Win Rate", "Profit Factor", "Max Drawdown", "Max Consecutive Losses", "Average Holding Bars"):
            self.assertIn(metric, template)
        for quality_field in ("Observed Bars", "Deferred Inputs", "Schema Pass Rate", "Source/Spec Ref Completeness", "Review Status", "Quality Flag", "Lineage", "Week-over-week Status"):
            self.assertIn(quality_field, template)
        self.assertIn("M10-PA-005", runbook)
        combined = f"{runbook}\n{template}\n{json.dumps(self.queue, ensure_ascii=False)}".lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true"):
            self.assertNotIn(forbidden.lower(), combined)


if __name__ == "__main__":
    unittest.main()
