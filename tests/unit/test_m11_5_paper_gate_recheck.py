from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import m11_5_paper_gate_recheck_lib as MODULE


OUTPUT_DIR = MODULE.M11_5_DIR


class M115PaperGateRecheckTests(unittest.TestCase):
    def test_gate_stays_not_approved_from_m12_6_inputs(self) -> None:
        config = MODULE.load_gate_recheck_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m11_5_paper_gate_recheck(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-27T13:00:00Z",
            )
            blockers = json.loads((Path(tmp) / "m11_5_blockers_and_approvals.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["gate_decision"], "not_approved")
        self.assertFalse(summary["paper_trading_approval"])
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["live_execution"])
        self.assertFalse(blockers["paper_trading_approval"])
        self.assertIn("no_completed_real_read_only_observation_window", blockers["blocking_conditions"])
        self.assertIn("manual_visual_review_still_pending", blockers["blocking_conditions"])
        self.assertIn("scanner_universe_cache_coverage_incomplete", blockers["blocking_conditions"])
        self.assertIn("unresolved_definition_blockers", blockers["blocking_conditions"])
        self.assertIn("definition_blockers_closed_or_formally_deferred", blockers["approvals_required_before_next_gate"])

    def test_candidate_list_keeps_tier_a_and_visual_conditional_only(self) -> None:
        config = MODULE.load_gate_recheck_config()
        with tempfile.TemporaryDirectory() as tmp:
            MODULE.run_m11_5_paper_gate_recheck(replace(config, output_dir=Path(tmp)))
            candidates = json.loads((Path(tmp) / "m11_5_candidate_strategy_list.json").read_text(encoding="utf-8"))

        self.assertEqual(
            [item["strategy_id"] for item in candidates["candidate_strategies"]],
            ["M10-PA-001", "M10-PA-002", "M10-PA-012", "M10-PA-008", "M10-PA-009"],
        )
        by_id = {item["strategy_id"]: item for item in candidates["candidate_strategies"]}
        self.assertEqual(by_id["M10-PA-001"]["scanner_candidates"], 6)
        self.assertEqual(by_id["M10-PA-002"]["scanner_candidates"], 0)
        self.assertEqual(by_id["M10-PA-012"]["scanner_candidates"], 6)
        self.assertEqual(by_id["M10-PA-001"]["paper_gate_recheck_status"], "not_approved_blocked_by_open_gate_conditions")
        self.assertEqual(by_id["M10-PA-008"]["paper_gate_recheck_status"], "not_approved_pending_manual_visual_review")
        self.assertIn("unresolved_definition_blockers", by_id["M10-PA-001"]["approval_blockers"])
        self.assertIn("unresolved_definition_blockers", by_id["M10-PA-008"]["approval_blockers"])
        self.assertFalse(any(item["counts_as_gate_evidence_now"] for item in candidates["candidate_strategies"]))

    def test_reports_do_not_claim_trading_approval(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m11_5_paper_gate_recheck.py before full validation")
        combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in OUTPUT_DIR.glob("m11_5_*") if path.is_file())
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "paper_trading_approval=true", "broker_connection=true", "real_orders=true"):
            self.assertNotIn(forbidden.lower(), lowered)
        self.assertIn("not_approved", combined)
        self.assertIn("paper trading 继续关闭", combined)
        self.assertIn("不进入 paper trading", combined)

    def test_required_artifacts_exist_and_handoff_has_protocol_fields(self) -> None:
        expected = {
            "m11_5_candidate_strategy_list.json",
            "m11_5_blockers_and_approvals.json",
            "m11_5_blockers_and_approvals.md",
            "m11_5_paper_gate_recheck_report.md",
            "m11_5_paper_gate_recheck_summary.json",
            "m11_5_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("m11_5_*")})
        handoff = (OUTPUT_DIR / "m11_5_handoff.md").read_text(encoding="utf-8")
        for field in ("task_id:", "role:", "status:", "commands_run:", "tests_run:", "rollback_notes:"):
            self.assertIn(field, handoff)


if __name__ == "__main__":
    unittest.main()
