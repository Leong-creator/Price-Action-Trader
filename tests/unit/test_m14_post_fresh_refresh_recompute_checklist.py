from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_post_fresh_refresh_recompute_checklist_lib import (
    load_config,
    run_m14_post_fresh_refresh_recompute_checklist,
)


class M14PostFreshRefreshRecomputeChecklistTest(unittest.TestCase):
    def test_builds_safe_recompute_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_post_fresh_refresh_recompute_checklist(
                load_config(config_path),
                generated_at="2026-05-27T00:10:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.post-fresh-refresh-recompute-checklist.v1")
            self.assertFalse(result["summary"]["fresh_refresh_observed"])
            self.assertEqual(result["summary"]["source_quote"], "fallback_quotes_only")
            self.assertEqual(result["summary"]["recompute_step_count"], 29)
            self.assertEqual(result["summary"]["m14_script_step_count"], 28)
            self.assertEqual(result["summary"]["acceptance_gate_count"], 9)
            self.assertTrue(result["summary"]["two_pass_stabilization_required"])
            self.assertEqual(result["summary"]["trial_acceptance_approved_trial_strategy_count"], 2)
            self.assertEqual(result["summary"]["trial_acceptance_trial_start_ready_count"], 2)
            self.assertTrue(result["summary"]["trial_acceptance_can_start_internal_sim_trial_now"])
            self.assertEqual(result["summary"]["trial_acceptance_fresh_refresh_required_count"], 2)
            self.assertEqual(result["summary"]["trial_acceptance_global_gate_pass_count"], 3)
            self.assertEqual(result["summary"]["trial_acceptance_global_gate_waiting_count"], 2)
            self.assertEqual(result["summary"]["trial_acceptance_legacy_historical_profit_planning_input_count"], 0)
            self.assertEqual(result["summary"]["rescue_no_m13_ledger_evidence_count"], 2)
            self.assertEqual(result["summary"]["parameter_shadow_spec_candidate_variant_count"], 4)
            self.assertEqual(result["summary"]["strategy_decision_final_discard_allowed_count"], 0)
            self.assertEqual(result["summary"]["objective_blocker_burndown_row_count"], 7)
            self.assertEqual(result["summary"]["objective_blocker_p0_count"], 4)
            self.assertEqual(result["summary"]["objective_blocker_p1_count"], 3)
            self.assertEqual(result["summary"]["objective_blocker_legacy_historical_profit_planning_input_count"], 0)
            self.assertEqual(result["summary"]["strategy_next_step_row_count"], 5)
            self.assertEqual(result["summary"]["strategy_next_step_approved_internal_sim_continue_count"], 2)
            self.assertEqual(result["summary"]["strategy_next_step_rescue_or_shadow_review_count"], 2)
            self.assertEqual(result["summary"]["strategy_next_step_source_review_or_plugin_research_count"], 1)
            self.assertEqual(result["summary"]["strategy_next_step_legacy_historical_profit_planning_input_count"], 0)
            self.assertEqual(result["summary"]["legacy_historical_profit_planning_input_count"], 0)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_row_count"], 4)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_ready_now_count"], 1)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_wait_fresh_count"], 2)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_backfill_count"], 1)
            self.assertEqual(result["summary"]["future_source_reextract_spec_prep_row_count"], 2)
            self.assertEqual(result["summary"]["future_source_reextract_spec_unblocked_count"], 0)
            self.assertEqual(result["summary"]["future_source_reextract_spec_pending_confirmation_count"], 16)
            self.assertEqual(
                result["summary"]["future_source_reextract_spec_legacy_historical_profit_planning_input_count"],
                0,
            )
            self.assertEqual(result["summary"]["parameter_mutation_allowed_count"], 0)
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["live_execution"])

            steps = {row["step_id"]: row for row in result["recompute_steps"]}
            self.assertEqual(
                steps["wait_for_m12_47_supervisor_refresh"]["step_type"],
                "wait",
            )
            self.assertEqual(
                steps["review_post_refresh_outcomes"]["command"],
                "python scripts/run_m14_rescue_post_refresh_outcome_review.py",
            )
            self.assertEqual(
                steps["objective_audit_after_ladder"]["command"],
                "python scripts/run_m14_objective_completion_audit.py",
            )
            self.assertEqual(
                steps["strategy_evidence_gap_matrix_refresh"]["command"],
                "python scripts/run_m14_strategy_evidence_gap_matrix.py",
            )
            self.assertEqual(
                steps["strategy_evidence_gap_burndown_refresh"]["command"],
                "python scripts/run_m14_strategy_evidence_gap_burndown.py",
            )
            self.assertEqual(
                steps["strategy_source_visual_confirmation_response_gate_refresh"]["command"],
                "python scripts/run_m14_strategy_source_visual_confirmation_response_gate.py",
            )
            self.assertEqual(
                steps["strategy_future_source_reextract_spec_prep_refresh"]["command"],
                "python scripts/run_m14_strategy_future_source_reextract_spec_prep.py",
            )
            self.assertEqual(
                steps["objective_blocker_burndown_refresh"]["command"],
                "python scripts/run_m14_objective_blocker_burndown.py",
            )
            self.assertEqual(
                steps["strategy_next_step_readiness_matrix_refresh"]["command"],
                "python scripts/run_m14_strategy_next_step_readiness_matrix.py",
            )
            self.assertEqual(
                steps["internal_sim_trial_acceptance_gate_refresh"]["command"],
                "python scripts/run_m14_internal_sim_trial_acceptance_gate.py",
            )
            self.assertEqual(
                steps["strategy_pre_refresh_review_packet_refresh"]["command"],
                "python scripts/run_m14_strategy_pre_refresh_review_packet.py",
            )
            self.assertEqual(
                steps["strategy_pre_refresh_review_audit_refresh"]["command"],
                "python scripts/run_m14_strategy_pre_refresh_review_audit.py",
            )
            for row in result["recompute_steps"]:
                self.assertNotIn("run_m12_37_intraday_auto_loop.py", row["command"])
                self.assertFalse(row["manual_m12_37_once_allowed"])
                self.assertFalse(row["broker_connection"])
                self.assertFalse(row["real_order"])
                self.assertFalse(row["live_execution"])
                self.assertFalse(row["parameter_mutation"])
                self.assertFalse(row["legacy_historical_profit_planning_input"])

            gates = {row["gate_id"]: row for row in result["acceptance_gates"]}
            self.assertEqual(gates["fresh_refresh_source_gate"]["state"], "waiting")
            self.assertEqual(gates["no_final_discard_without_rescue_exhaustion_gate"]["state"], "passed")
            self.assertEqual(gates["broker_live_boundary_gate"]["state"], "passed")
            self.assertEqual(gates["legacy_history_metric_exclusion_gate"]["state"], "passed")
            self.assertEqual(gates["internal_sim_trial_acceptance_gate"]["state"], "passed")

            persisted = json.loads((root / "checklist.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "checklist.md").read_text(encoding="utf-8")
            self.assertIn("M14 Post-Fresh-Refresh Recompute Checklist", md)
            self.assertIn("M14 read-only script steps: `28`", md)
            self.assertIn("Objective blocker rows/P0/P1/legacy-history-planning-inputs: `7/4/3/0`", md)
            self.assertIn("Strategy next-step rows/approved/rescue-or-shadow/source-review: `5/2/2/1`", md)
            self.assertIn("Strategy next-step promote/discard/parameter/broker/legacy-history inputs: `0/0/0/0/0`", md)
            self.assertIn("Internal-sim trial ready/approved/fresh-required/legacy-history inputs: `2/2/2/0`", md)
            self.assertIn("Pre-refresh review audit rows/ready/waiting/backfill: `4/1/2/1`", md)
            self.assertIn("Future source-reextract spec prep rows/drafts/unblocked/blocked/pending/legacy-history inputs: `2/2/0/2/16/0`", md)
            self.assertIn("Final discard allowed: `0`", md)

    def test_rejects_manual_once_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["manual_m12_37_once"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "manual_m12_37_once"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        next_session_path = root / "next_session.json"
        trial_acceptance_path = root / "trial_acceptance.json"
        post_refresh_path = root / "post_refresh.json"
        rescue_ab_path = root / "rescue_ab.json"
        next_refresh_path = root / "next_refresh.json"
        parameter_queue_path = root / "parameter_queue.json"
        activation_gate_path = root / "activation_gate.json"
        shadow_spec_path = root / "shadow_spec.json"
        decision_ladder_path = root / "decision_ladder.json"
        pre_refresh_audit_path = root / "pre_refresh_audit.json"
        future_spec_path = root / "future_spec.json"
        objective_audit_path = root / "objective_audit.json"
        objective_execution_path = root / "objective_execution.json"
        objective_blocker_path = root / "objective_blocker.json"
        next_step_matrix_path = root / "next_step_matrix.json"
        config_path = root / "config.json"

        next_session_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "can_run_next_internal_sim_session": True,
                        "next_session_mode": "m12_47_supervised_fresh_refresh_only",
                        "approved_runtime_input_connected_count": 4,
                        "approved_runtime_input_count": 4,
                    },
                }
            ),
            encoding="utf-8",
        )
        trial_acceptance_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "approved_trial_strategy_count": 2,
                        "trial_start_ready_count": 2,
                        "can_start_internal_sim_trial_now": True,
                        "fresh_refresh_required_count": 2,
                        "global_gate_count": 5,
                        "global_gate_state_counts": {"pass": 3, "waiting": 2},
                        "legacy_historical_profit_planning_input_count": 0,
                        "can_start_broker_paper": False,
                        "broker_or_live_enabled": False,
                    }
                }
            ),
            encoding="utf-8",
        )
        post_refresh_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "fresh_refresh_observed": False,
                        "source_quote": "fallback_quotes_only",
                        "waiting_count": 13,
                        "passed_count": 0,
                        "failed_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        rescue_ab_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "rescue_runtime_strategy_count": 11,
                        "m13_ledger_observed_strategy_count": 9,
                        "no_m13_ledger_evidence_count": 2,
                        "promotion_allowed_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        next_refresh_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "watch_rows": 13,
                        "parameter_change_allowed_now_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        parameter_queue_path.write_text(
            json.dumps({"summary": {"experiment_row_count": 4}}),
            encoding="utf-8",
        )
        activation_gate_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "gate_row_count": 4,
                        "waiting_for_fresh_refresh_count": 3,
                        "shadow_review_candidate_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        shadow_spec_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "spec_row_count": 4,
                        "candidate_variant_count": 4,
                    }
                }
            ),
            encoding="utf-8",
        )
        decision_ladder_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "m14_trading_date": "2026-05-22",
                        "strategy_ladder_row_count": 5,
                        "final_discard_allowed_count": 0,
                        "promotion_candidate_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        pre_refresh_audit_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "audit_row_count": 4,
                        "ready_for_artifact_review_now_count": 1,
                        "pre_review_ready_wait_fresh_evidence_count": 2,
                        "needs_supporting_artifact_backfill_count": 1,
                    }
                }
            ),
            encoding="utf-8",
        )
        future_spec_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "future_source_reextract_spec_prep_row_count": 2,
                        "conditional_spec_draft_count": 2,
                        "future_spec_unblocked_count": 0,
                        "blocked_until_manual_visual_confirmation_count": 2,
                        "manual_confirmation_pending_count": 16,
                        "legacy_historical_profit_planning_input_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        objective_audit_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "objective_complete": False,
                        "blocked_count": 3,
                        "in_progress_count": 2,
                    },
                }
            ),
            encoding="utf-8",
        )
        objective_execution_path.write_text(
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
        objective_blocker_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "blocker_burndown_row_count": 7,
                        "p0_blocker_count": 4,
                        "p1_blocker_count": 3,
                        "legacy_historical_profit_planning_input_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        next_step_matrix_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "strategy_next_step_row_count": 5,
                        "approved_internal_sim_continue_count": 2,
                        "rescue_or_shadow_review_count": 2,
                        "source_review_or_plugin_research_count": 1,
                        "promotion_allowed_count": 0,
                        "final_discard_allowed_count": 0,
                        "parameter_activation_allowed_count": 0,
                        "broker_paper_start_allowed_count": 0,
                        "legacy_historical_profit_planning_input_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.post-fresh-refresh-recompute-checklist.config.v1",
                    "stage": "M14.post_fresh_refresh_recompute_checklist",
                    "project_stage_label": "fixture post-refresh checklist",
                    "inputs": {
                        "m14_internal_sim_next_session_plan": str(next_session_path),
                        "m14_internal_sim_trial_acceptance_gate": str(trial_acceptance_path),
                        "m14_rescue_post_refresh_outcome_review": str(post_refresh_path),
                        "m14_rescue_ab_evidence_tracker": str(rescue_ab_path),
                        "m14_rescue_next_refresh_readiness": str(next_refresh_path),
                        "m14_rescue_parameter_experiment_queue": str(parameter_queue_path),
                        "m14_rescue_parameter_activation_gate": str(activation_gate_path),
                        "m14_rescue_parameter_shadow_spec": str(shadow_spec_path),
                        "m14_strategy_decision_ladder": str(decision_ladder_path),
                        "m14_strategy_pre_refresh_review_audit": str(pre_refresh_audit_path),
                        "m14_strategy_future_source_reextract_spec_prep": str(future_spec_path),
                        "m14_objective_completion_audit": str(objective_audit_path),
                        "m14_objective_execution_plan": str(objective_execution_path),
                        "m14_objective_blocker_burndown": str(objective_blocker_path),
                        "m14_strategy_next_step_readiness_matrix": str(next_step_matrix_path),
                    },
                    "outputs": {
                        "checklist_json": str(root / "checklist.json"),
                        "checklist_md": str(root / "checklist.md"),
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
                        "legacy_historical_profit_planning_input": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path


if __name__ == "__main__":
    unittest.main()
