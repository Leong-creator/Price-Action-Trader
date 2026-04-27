from __future__ import annotations

import json
import unittest

from scripts.m11_paper_gate_lib import M11_DIR, run_m11_paper_gate


class M11PaperGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = run_m11_paper_gate()
        cls.candidates = json.loads((M11_DIR / "m11_candidate_strategy_list.json").read_text(encoding="utf-8"))

    def test_gate_is_not_approved_and_boundaries_are_closed(self) -> None:
        summary = self.summary
        candidates = self.candidates

        self.assertEqual(summary["gate_decision"], "not_approved")
        self.assertFalse(summary["paper_trading_approval"])
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["live_execution"])
        self.assertFalse(candidates["boundaries"]["paper_trading_approval"])
        self.assertFalse(candidates["boundaries"]["broker_connection"])
        self.assertFalse(candidates["boundaries"]["real_orders"])
        self.assertFalse(candidates["boundaries"]["live_execution"])

    def test_candidate_list_matches_m10_13_primary_queue(self) -> None:
        self.assertEqual(
            [item["strategy_id"] for item in self.candidates["candidate_strategies"]],
            ["M10-PA-001", "M10-PA-002", "M10-PA-012", "M10-PA-008", "M10-PA-009"],
        )
        for item in self.candidates["candidate_strategies"]:
            self.assertEqual(item["gate_status"], "not_approved_pending_read_only_observation")
            self.assertIn("no_completed_real_read_only_observation_window", item["approval_blockers"])
            self.assertIn("no_human_business_approval_for_paper_trading", item["approval_blockers"])

    def test_client_candidate_tiers_and_gate_evidence_status_are_explicit(self) -> None:
        groups = self.candidates["candidate_groups"]
        by_id = {item["strategy_id"]: item for item in self.candidates["candidate_strategies"]}

        self.assertEqual(groups["tier_a_core_after_read_only_observation"], ["M10-PA-001", "M10-PA-002", "M10-PA-012"])
        self.assertEqual(groups["tier_b_conditional_visual_after_review"], ["M10-PA-008", "M10-PA-009"])
        self.assertEqual(groups["watchlist_deferred"], ["M10-PA-003", "M10-PA-011", "M10-PA-013"])
        self.assertEqual(groups["blocked_definition_fix"], ["M10-PA-004", "M10-PA-005", "M10-PA-007"])
        self.assertFalse(self.candidates["gate_evidence_policy"]["current_gate_evidence_accepted"])
        self.assertEqual(by_id["M10-PA-001"]["client_gate_tier"], "tier_a_core_after_read_only_observation")
        self.assertEqual(by_id["M10-PA-008"]["client_gate_tier"], "tier_b_conditional_visual_after_review")
        for item in by_id.values():
            self.assertFalse(item["counts_as_gate_evidence_now"])
            self.assertTrue(item["risk_notes"])

    def test_visual_candidates_have_extra_visual_blocker(self) -> None:
        by_id = {item["strategy_id"]: item for item in self.candidates["candidate_strategies"]}

        self.assertIn("manual_visual_context_review_required", by_id["M10-PA-008"]["approval_blockers"])
        self.assertIn("manual_visual_context_review_required", by_id["M10-PA-009"]["approval_blockers"])
        self.assertNotIn("manual_visual_context_review_required", by_id["M10-PA-001"]["approval_blockers"])

    def test_exclusions_and_blocking_conditions_are_explicit(self) -> None:
        excluded = self.candidates["excluded_from_gate"]
        self.assertEqual(excluded["definition_not_closed"], ["M10-PA-005"])
        self.assertIn("M10-PA-013", excluded["non_positive_or_watchlist_only"])
        self.assertIn("M10-PA-014", excluded["supporting_only"])
        self.assertIn("M10-PA-016", excluded["research_only"])
        self.assertIn("no_completed_real_read_only_observation_window", self.candidates["blocking_conditions"])
        self.assertIn("no_human_business_approval_for_paper_trading", self.candidates["blocking_conditions"])

    def test_reports_and_policy_keep_no_live_guardrails(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in [
                M11_DIR / "m11_paper_gate_report.md",
                M11_DIR / "m11_candidate_strategy_list.json",
                M11_DIR / "m11_risk_and_pause_policy.md",
                M11_DIR / "m11_paper_gate_summary.json",
            ]
        )
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "paper_trading_approval=true", "broker_connection=true", "real_orders=true"):
            self.assertNotIn(forbidden.lower(), lowered)
        self.assertIn("paper trading 继续关闭", combined)
        self.assertIn("broker connection: `false`", combined)
        self.assertIn("real orders: `false`", combined)


if __name__ == "__main__":
    unittest.main()
