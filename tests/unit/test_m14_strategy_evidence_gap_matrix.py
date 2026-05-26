from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_evidence_gap_matrix_lib import (
    load_config,
    run_m14_strategy_evidence_gap_matrix,
)


class M14StrategyEvidenceGapMatrixTest(unittest.TestCase):
    def test_builds_strategy_gap_matrix_without_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_evidence_gap_matrix(
                load_config(config_path),
                generated_at="2026-05-27T03:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.strategy-evidence-gap-matrix.v1")
            self.assertEqual(result["summary"]["strategy_gap_row_count"], 4)
            self.assertEqual(result["summary"]["open_evidence_gap_row_count"], 4)
            self.assertEqual(result["summary"]["requires_m12_47_fresh_refresh_count"], 3)
            self.assertEqual(result["summary"]["approved_next_refresh_gap_count"], 1)
            self.assertEqual(result["summary"]["rescue_gap_count"], 2)
            self.assertEqual(result["summary"]["shadow_or_plugin_gap_count"], 1)
            self.assertEqual(result["summary"]["wait_first_ledger_gap_count"], 1)
            self.assertEqual(result["summary"]["rescue_10_day_ab_gap_count"], 2)
            self.assertEqual(result["summary"]["shadow_review_gap_count"], 1)
            self.assertEqual(result["summary"]["final_discard_allowed_count"], 0)
            self.assertEqual(result["summary"]["promotion_candidate_count"], 0)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["parameter_mutation"])

            rows = {row["strategy_id"]: row for row in result["gap_rows"]}
            self.assertEqual(rows["M10-PA-004"]["gap_state"], "approved_wait_next_refresh")
            self.assertIn("m12_47_fresh_refresh", rows["M10-PA-004"]["missing_evidence_categories"])
            self.assertEqual(rows["M10-PA-001"]["gap_state"], "wait_shadow_parameter_review")
            self.assertIn("shadow_parameter_review", rows["M10-PA-001"]["missing_evidence_categories"])
            self.assertEqual(rows["M10-PA-011"]["gap_state"], "wait_first_rescue_ledger")
            self.assertIn("first_m13_rescue_ledger", rows["M10-PA-011"]["missing_evidence_categories"])
            self.assertEqual(rows["M10-PA-003"]["gap_state"], "shadow_or_plugin_hold")
            for row in result["gap_rows"]:
                self.assertFalse(row["final_discard_allowed"])
                self.assertFalse(row["parameter_mutation_allowed"])
                self.assertFalse(row["manual_m12_37_once"])

            persisted = json.loads((root / "gap_matrix.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "gap_matrix.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Evidence Gap Matrix", md)
            self.assertIn("Final discard allowed: `0`", md)
            self.assertIn("approved_wait_next_refresh", md)

    def test_rejects_unsafe_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["parameter_mutation"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "parameter_mutation"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        ladder_path = root / "ladder.json"
        rescue_path = root / "rescue.json"
        shadow_path = root / "shadow.json"
        audit_path = root / "audit.json"
        execution_path = root / "execution.json"
        checklist_path = root / "checklist.json"
        config_path = root / "config.json"

        ladder_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                    },
                    "ladder_rows": [
                        self._ladder_row("M10-PA-004", "approved_internal_sim_continue", "approved_continue_internal_sim"),
                        self._ladder_row("M10-PA-001", "rescue_ab_collect", "continue_rescue_with_shadow_specs"),
                        self._ladder_row("M10-PA-011", "rebuild_detector_then_ab", "wait_first_rescue_ledger"),
                        self._ladder_row("M10-PA-003", "shadow_or_plugin_hold", "shadow_or_plugin_hold"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        rescue_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "rescue_runtime_strategy_count": 2,
                        "m13_ledger_observed_strategy_count": 1,
                        "no_m13_ledger_evidence_count": 1,
                        "promotion_allowed_count": 0,
                    },
                    "rows": [
                        {
                            "strategy_id": "M10-PA-001-m14-modify-20260522",
                            "parent_strategy_id": "M10-PA-001",
                            "evidence_status": "collecting_ab_evidence",
                            "observed_trading_days_count": 1,
                            "remaining_ab_trading_days": 9,
                        },
                        {
                            "strategy_id": "M10-PA-011-ORB-R1",
                            "parent_strategy_id": "M10-PA-011",
                            "evidence_status": "no_m13_rescue_ledger_evidence_yet",
                            "observed_trading_days_count": 0,
                            "remaining_ab_trading_days": 10,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        shadow_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "candidate_variant_count": 2,
                    },
                    "spec_rows": [
                        {
                            "strategy_id": "M10-PA-001-m14-modify-20260522",
                            "parent_strategy_id": "M10-PA-001",
                            "spec_state": "fresh_recheck_spec_ready_wait_refresh",
                            "variant_count": 2,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        audit_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "objective_complete": False,
                        "blocked_count": 3,
                        "in_progress_count": 2,
                    }
                }
            ),
            encoding="utf-8",
        )
        execution_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "execution_action_count": 7,
                        "waiting_for_fresh_refresh_action_count": 5,
                    }
                }
            ),
            encoding="utf-8",
        )
        checklist_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "recompute_step_count": 20,
                        "acceptance_gate_count": 7,
                        "fresh_refresh_observed": False,
                        "source_quote": "fallback_quotes_only",
                    },
                    "recompute_steps": [
                        {"step_id": "wait_for_m12_47_supervisor_refresh", "command": ""},
                        {"step_id": "review_post_refresh_outcomes", "command": "python scripts/run_m14_rescue_post_refresh_outcome_review.py"},
                        {"step_id": "refresh_rescue_ab_evidence", "command": "python scripts/run_m14_rescue_ab_evidence_tracker.py"},
                        {"step_id": "refresh_rescue_optimization_backlog", "command": "python scripts/run_m14_rescue_optimization_backlog.py"},
                        {"step_id": "refresh_parameter_experiment_queue", "command": "python scripts/run_m14_rescue_parameter_experiment_queue.py"},
                        {"step_id": "refresh_parameter_activation_gate", "command": "python scripts/run_m14_rescue_parameter_activation_gate.py"},
                        {"step_id": "refresh_parameter_shadow_specs", "command": "python scripts/run_m14_rescue_parameter_shadow_spec.py"},
                        {"step_id": "strategy_decision_ladder_refresh", "command": "python scripts/run_m14_strategy_decision_ladder.py"},
                        {"step_id": "project_stage_assessment_refresh", "command": "python scripts/run_m14_project_stage_assessment.py"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-evidence-gap-matrix.config.v1",
                    "stage": "M14.strategy_evidence_gap_matrix",
                    "inputs": {
                        "m14_strategy_decision_ladder": str(ladder_path),
                        "m14_rescue_ab_evidence_tracker": str(rescue_path),
                        "m14_rescue_parameter_shadow_spec": str(shadow_path),
                        "m14_objective_completion_audit": str(audit_path),
                        "m14_objective_execution_plan": str(execution_path),
                        "m14_post_fresh_refresh_recompute_checklist": str(checklist_path),
                    },
                    "outputs": {
                        "gap_matrix_json": str(root / "gap_matrix.json"),
                        "gap_matrix_md": str(root / "gap_matrix.md"),
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "internal_simulated_account": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                        "manual_m12_37_once": False,
                        "m13_registry_mutation": False,
                        "m12_account_specs_mutation": False,
                        "broker_readiness_status_mutation": False,
                        "parameter_mutation": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _ladder_row(self, strategy_id: str, route_category: str, ladder_state: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "display_name": strategy_id,
            "route_rank": {
                "approved_internal_sim_continue": 0,
                "rescue_ab_collect": 1,
                "rebuild_detector_then_ab": 3,
                "shadow_or_plugin_hold": 4,
            }.get(route_category, 9),
            "route_category": route_category,
            "ladder_state": ladder_state,
            "next_decision": "advance_internal_sim_next_refresh"
            if ladder_state == "approved_continue_internal_sim"
            else "continue_ab_and_shadow_parameter_review",
            "decision": "promote" if route_category == "approved_internal_sim_continue" else "modify",
            "paper_trial_gate": "approved_internal_sim_only"
            if route_category == "approved_internal_sim_continue"
            else "not_approved_modify_candidate",
            "completed_trading_days": 10,
            "can_advance_next_step": route_category == "approved_internal_sim_continue",
            "continue_rescue": route_category in {"rescue_ab_collect", "rebuild_detector_then_ab"},
            "manual_review_ready": False,
            "can_promote_now": False,
            "broker_watch": False,
            "linked_next_refresh_watch_count": 0,
            "rescue_runtime_strategy_ids": [f"{strategy_id}-m14-modify-20260522"]
            if route_category != "approved_internal_sim_continue"
            else [],
            "final_discard_allowed": False,
            "final_discard_blockers": ["manual_m14_final_review_required"],
        }


if __name__ == "__main__":
    unittest.main()
