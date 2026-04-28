from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import m12_visual_review_closure_lib as MODULE


OUTPUT_DIR = MODULE.M12_9_DIR


class M12VisualReviewClosureTests(unittest.TestCase):
    def test_config_scope_and_boundaries_are_locked(self) -> None:
        config = MODULE.load_visual_closure_config()

        self.assertEqual(config.priority_strategy_ids, ("M10-PA-008", "M10-PA-009"))
        self.assertEqual(config.watchlist_strategy_ids, ("M10-PA-003", "M10-PA-011"))
        self.assertEqual(config.definition_support_strategy_ids, ("M10-PA-004", "M10-PA-007"))
        self.assertTrue(config.paper_simulated_only)
        self.assertFalse(config.broker_connection)
        self.assertFalse(config.real_orders)
        self.assertFalse(config.live_execution)
        self.assertFalse(config.paper_trading_approval)

    def test_config_rejects_scope_or_boundary_drift(self) -> None:
        config = MODULE.load_visual_closure_config()
        cases = (
            replace(config, stage="M12.9.bad"),
            replace(config, priority_strategy_ids=("M10-PA-008",)),
            replace(config, watchlist_strategy_ids=("M10-PA-003",)),
            replace(config, definition_support_strategy_ids=("M10-PA-004",)),
            replace(config, paper_simulated_only=False),
            replace(config, broker_connection=True),
            replace(config, real_orders=True),
            replace(config, live_execution=True),
            replace(config, paper_trading_approval=True),
        )

        for bad_config in cases:
            with self.subTest(bad_config=bad_config):
                with self.assertRaises(ValueError):
                    MODULE.validate_config(bad_config)

    def test_generated_index_closes_agent_precheck_but_not_paper_gate(self) -> None:
        index = json.loads((OUTPUT_DIR / "m12_9_visual_closure_index.json").read_text(encoding="utf-8"))
        rows = {row["strategy_id"]: row for row in index["strategy_rows"]}

        self.assertEqual(set(rows), {"M10-PA-008", "M10-PA-009", "M10-PA-003", "M10-PA-011", "M10-PA-004", "M10-PA-007"})
        for strategy_id in ("M10-PA-008", "M10-PA-009"):
            self.assertEqual(rows[strategy_id]["strategy_level_status"], "visual_review_closed")
            self.assertTrue(rows[strategy_id]["agent_precheck_closed"])
            self.assertTrue(rows[strategy_id]["user_confirmation_required_before_paper_gate"])
            self.assertFalse(rows[strategy_id]["paper_gate_evidence_now"])
        for strategy_id in ("M10-PA-004", "M10-PA-007"):
            self.assertEqual(rows[strategy_id]["strategy_level_status"], "needs_definition_fix")
            self.assertTrue(rows[strategy_id]["definition_fix_required"])
            self.assertFalse(rows[strategy_id]["paper_gate_evidence_now"])

    def test_case_ledger_preserves_evidence_and_review_separation(self) -> None:
        ledger = json.loads((OUTPUT_DIR / "m12_9_case_review_ledger.json").read_text(encoding="utf-8"))
        cases = ledger["case_rows"]

        self.assertEqual(len(cases), 30)
        self.assertTrue(all(row["evidence_exists"] for row in cases))
        self.assertTrue(all(row["checksum_match"] for row in cases))
        self.assertTrue(all(row["paper_gate_evidence_now"] is False for row in cases))
        priority_cases = [row for row in cases if row["strategy_id"] in {"M10-PA-008", "M10-PA-009"}]
        self.assertEqual(len(priority_cases), 10)
        self.assertTrue(all(row["user_review_required"] for row in priority_cases))
        definition_cases = [row for row in cases if row["strategy_id"] in {"M10-PA-004", "M10-PA-007"}]
        self.assertTrue(all(row["case_level_decision"] == "pass_for_definition_evidence" for row in definition_cases))

    def test_user_packet_is_limited_to_priority_visual_cases(self) -> None:
        packet = (OUTPUT_DIR / "m12_9_user_review_packet.md").read_text(encoding="utf-8")

        self.assertIn("M10-PA-008", packet)
        self.assertIn("M10-PA-009", packet)
        self.assertNotIn("M10-PA-004", packet)
        self.assertNotIn("M10-PA-007", packet)
        self.assertIn("paper_gate_evidence_now=false", packet)

    def test_runner_can_generate_temp_artifacts(self) -> None:
        config = MODULE.load_visual_closure_config()
        with tempfile.TemporaryDirectory() as tmp:
            index = MODULE.run_m12_visual_review_closure(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
            )

        self.assertEqual(index["generated_at"], "2026-04-28T00:00:00Z")
        self.assertEqual(index["strategy_count"], 6)
        self.assertEqual(index["case_count"], 30)
        self.assertEqual(index["user_review_required_case_count"], 10)

    def test_required_artifacts_exist_and_forbidden_claims_absent(self) -> None:
        expected = {
            "m12_9_visual_closure_index.json",
            "m12_9_case_review_ledger.json",
            "m12_9_user_review_packet.md",
            "m12_9_visual_gate_closure_report.md",
            "m12_9_handoff.md",
        }

        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("m12_9_*")})
        combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in OUTPUT_DIR.glob("m12_9_*") if path.is_file())
        for forbidden in ("PA-SC-", "SF-", "live-ready", "real_orders=true", "broker_connection=true"):
            self.assertNotIn(forbidden.lower(), combined.lower())
        self.assertIn("paper_trading_approval=false", combined)


if __name__ == "__main__":
    unittest.main()
