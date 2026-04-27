from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import m12_visual_review_precheck_lib as MODULE


OUTPUT_DIR = MODULE.M10_DIR / "visual_review" / "m12_3_precheck"


class M12VisualReviewPrecheckTests(unittest.TestCase):
    def test_precheck_strategy_scope_and_required_review_flags(self) -> None:
        config = MODULE.load_visual_precheck_config()
        with tempfile.TemporaryDirectory() as tmp:
            index = MODULE.run_m12_visual_precheck(replace(config, output_dir=Path(tmp)), generated_at="2026-04-27T12:00:00Z")

        self.assertEqual([row["strategy_id"] for row in index["strategy_rows"]], list(MODULE.M12_3_STRATEGY_IDS))
        by_id = {row["strategy_id"]: row for row in index["strategy_rows"]}
        self.assertTrue(by_id["M10-PA-008"]["required_manual_review"])
        self.assertTrue(by_id["M10-PA-009"]["required_manual_review"])
        self.assertFalse(by_id["M10-PA-013"]["visual_pack_present"])
        self.assertEqual(by_id["M10-PA-013"]["source_type"], "pre_existing_candidate")
        self.assertTrue(by_id["M10-PA-004"]["definition_fix_required"])
        self.assertTrue(by_id["M10-PA-007"]["definition_fix_required"])

    def test_case_rows_reuse_m10_2_packs_and_resolve_old_worktree_assets(self) -> None:
        config = MODULE.load_visual_precheck_config()
        with tempfile.TemporaryDirectory() as tmp:
            index = MODULE.run_m12_visual_precheck(replace(config, output_dir=Path(tmp)), generated_at="2026-04-27T12:00:00Z")

        self.assertEqual(index["case_count"], 30)
        self.assertEqual(index["checksum_match_count"], 30)
        self.assertEqual(index["case_location_counts"], {"old_m10_worktree": 30})
        first = index["case_rows"][0]
        self.assertIn("visual_golden_cases", index["strategy_rows"][0]["case_pack_json"])
        self.assertEqual(first["manual_review_status"], "agent_selected_pending_manual_review")
        self.assertTrue(first["checksum_match"])

    def test_generated_outputs_keep_gate_and_boundary_separation(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_visual_review_precheck.py before full validation")
        index = json.loads((OUTPUT_DIR / "m12_3_visual_precheck_index.json").read_text(encoding="utf-8"))
        by_id = {row["strategy_id"]: row for row in index["strategy_rows"]}

        self.assertFalse(index["paper_trading_approval"])
        self.assertFalse(index["broker_connection"])
        self.assertFalse(index["real_orders"])
        self.assertFalse(index["live_execution"])
        self.assertEqual(by_id["M10-PA-008"]["gate_decision"], "ready_for_wave_b_backtest")
        self.assertTrue(by_id["M10-PA-008"]["required_manual_review"])
        self.assertEqual(index["case_rows"][0]["reviewer_decision"], None)

    def test_generated_outputs_do_not_contain_legacy_or_execution_claims(self) -> None:
        combined = "\n".join(path.read_text(encoding="utf-8") for path in OUTPUT_DIR.glob("m12_3_*") if path.is_file())
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "order_id", "fill_price", "position", "cash", "pnl"):
            self.assertNotIn(forbidden.lower(), lowered)


if __name__ == "__main__":
    unittest.main()
