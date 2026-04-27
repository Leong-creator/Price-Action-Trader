from __future__ import annotations

import json
import unittest

from scripts.m10_visual_wave_b_gate_lib import (
    M10_10_DIR,
    NOT_IN_GATE_IDS,
    PRE_EXISTING_WAVE_B_IDS,
    VISUAL_IDS,
    run_m10_10_visual_wave_b_gate,
)


class M10VisualWaveBGateTests(unittest.TestCase):
    def test_visual_gate_reviews_only_visual_strategy_ids(self) -> None:
        summary = run_m10_10_visual_wave_b_gate()

        self.assertEqual(summary["visual_strategy_ids"], list(VISUAL_IDS))
        self.assertEqual({row["strategy_id"] for row in summary["review_rows"]}, set(VISUAL_IDS))
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["paper_trading_approval"])

    def test_ready_queue_contains_only_gate_ready_and_existing_wave_b_candidate(self) -> None:
        run_m10_10_visual_wave_b_gate()
        queue = json.loads((M10_10_DIR / "m10_10_wave_b_entry_queue.json").read_text(encoding="utf-8"))

        self.assertEqual(queue["pre_existing_wave_b_candidate_ids"], list(PRE_EXISTING_WAVE_B_IDS))
        self.assertEqual(
            set(queue["ready_visual_strategy_ids"]),
            {"M10-PA-003", "M10-PA-008", "M10-PA-009", "M10-PA-011"},
        )
        self.assertEqual(
            set(queue["wave_b_strategy_ids"]),
            {"M10-PA-013", "M10-PA-003", "M10-PA-008", "M10-PA-009", "M10-PA-011"},
        )
        excluded = set(queue["excluded_strategy_ids"])
        self.assertTrue(set(NOT_IN_GATE_IDS).issubset(excluded))
        self.assertNotIn("M10-PA-004", queue["wave_b_strategy_ids"])
        self.assertNotIn("M10-PA-007", queue["wave_b_strategy_ids"])
        self.assertNotIn("M10-PA-010", queue["wave_b_strategy_ids"])

    def test_pack_evidence_requirements_are_preserved(self) -> None:
        summary = run_m10_10_visual_wave_b_gate()

        self.assertEqual(summary["decision_counts"]["blocked_missing_evidence"], 0)
        for row in summary["review_rows"]:
            self.assertTrue(row["evidence_complete"])
            self.assertEqual(row["pack_status"], "visual_pack_ready")
            self.assertGreaterEqual(row["case_counts"]["positive"], 3)
            self.assertGreaterEqual(row["case_counts"]["counterexample"], 1)
            self.assertGreaterEqual(row["case_counts"]["boundary"], 1)

    def test_opening_reversal_scope_is_intraday_only(self) -> None:
        run_m10_10_visual_wave_b_gate()
        queue = json.loads((M10_10_DIR / "m10_10_wave_b_entry_queue.json").read_text(encoding="utf-8"))
        entries = {entry["strategy_id"]: entry for entry in queue["entries"]}

        self.assertEqual(entries["M10-PA-011"]["timeframes"], ["15m", "5m"])
        self.assertEqual(entries["M10-PA-003"]["timeframes"], ["1h", "15m", "5m"])

    def test_reports_keep_legacy_and_live_boundaries(self) -> None:
        run_m10_10_visual_wave_b_gate()
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in [
                M10_10_DIR / "m10_10_wave_b_entry_queue.json",
                M10_10_DIR / "m10_10_visual_gate_summary.json",
                M10_10_DIR / "m10_10_visual_strategy_review.md",
                M10_10_DIR / "m10_10_visual_client_summary.md",
            ]
        )
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true"):
            self.assertNotIn(forbidden.lower(), lowered)


if __name__ == "__main__":
    unittest.main()
