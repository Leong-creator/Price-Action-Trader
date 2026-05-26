from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_project_stage_assessment_lib import load_config, run_m14_project_stage_assessment


class M14ProjectStageAssessmentTest(unittest.TestCase):
    def test_builds_stage_assessment_and_strategy_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_project_stage_assessment(
                load_config(config_path),
                generated_at="2026-05-26T16:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.project-stage-assessment.v1")
            self.assertEqual(result["summary"]["challenge_progress_label"], "10/10")
            self.assertTrue(result["summary"]["ten_day_challenge_complete"])
            self.assertEqual(result["summary"]["approved_internal_sim_strategy_count"], 2)
            self.assertEqual(result["summary"]["approved_internal_sim_strategy_ids"], ["M10-PA-004", "M10-PA-005"])
            self.assertTrue(result["summary"]["can_run_next_internal_sim_session"])
            self.assertEqual(result["summary"]["approved_runtime_input_connected_count"], 3)
            self.assertEqual(result["summary"]["approved_runtime_input_count"], 3)
            self.assertEqual(result["summary"]["rescue_runtime_strategy_count"], 2)
            self.assertEqual(result["summary"]["rescue_m13_ledger_observed_strategy_count"], 1)
            self.assertEqual(result["summary"]["rescue_no_m13_ledger_evidence_count"], 1)
            self.assertEqual(result["summary"]["rescue_promotion_allowed_count"], 0)
            self.assertFalse(result["summary"]["post_refresh_fresh_refresh_observed"])
            self.assertEqual(result["summary"]["post_refresh_source_quote"], "fallback_quotes_only")
            self.assertEqual(result["summary"]["post_refresh_watch_rows"], 4)
            self.assertEqual(result["summary"]["post_refresh_waiting_count"], 4)
            self.assertEqual(result["summary"]["post_refresh_passed_count"], 0)
            self.assertEqual(result["summary"]["post_refresh_failed_count"], 0)
            self.assertEqual(result["summary"]["external_reference_mapped_rescue_row_count"], 3)
            self.assertEqual(result["summary"]["external_reference_broker_blocker_row_count"], 1)
            self.assertEqual(result["summary"]["external_reference_project_count"], 2)
            self.assertFalse(result["summary"]["external_reference_copy_trading_allowed"])
            self.assertEqual(result["summary"]["parameter_experiment_row_count"], 4)
            self.assertEqual(result["summary"]["parameter_experiment_allowed_now_count"], 0)
            self.assertEqual(result["summary"]["parameter_experiment_blocked_until_fresh_refresh_count"], 3)
            self.assertEqual(result["summary"]["parameter_experiment_shadow_runtime_wait_first_ledger_count"], 1)
            self.assertEqual(result["summary"]["parameter_experiment_broker_blocker_count"], 1)
            self.assertEqual(result["summary"]["parameter_experiment_target_stop_count"], 1)
            self.assertEqual(result["summary"]["parameter_experiment_m13_registry_mutation_count"], 0)
            self.assertEqual(result["summary"]["parameter_activation_gate_row_count"], 4)
            self.assertEqual(result["summary"]["parameter_activation_shadow_review_candidate_count"], 0)
            self.assertEqual(result["summary"]["parameter_activation_waiting_for_fresh_refresh_count"], 3)
            self.assertEqual(result["summary"]["parameter_activation_implementation_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["parameter_activation_parameter_mutation_allowed_count"], 0)
            self.assertFalse(result["summary"]["objective_audit_complete"])
            self.assertEqual(result["summary"]["objective_audit_requirement_count"], 12)
            self.assertEqual(result["summary"]["objective_audit_proven_count"], 4)
            self.assertEqual(result["summary"]["objective_audit_blocked_count"], 3)
            self.assertEqual(result["summary"]["objective_audit_in_progress_count"], 2)
            self.assertEqual(result["summary"]["objective_audit_guardrail_count"], 3)
            self.assertEqual(result["summary"]["objective_execution_action_count"], 7)
            self.assertEqual(result["summary"]["objective_execution_p0_action_count"], 5)
            self.assertEqual(result["summary"]["objective_execution_waiting_for_fresh_refresh_action_count"], 5)
            self.assertEqual(result["summary"]["objective_execution_manual_execution_allowed_count"], 0)
            self.assertEqual(result["summary"]["broker_dry_run_ready_count"], 1)
            self.assertEqual(result["summary"]["broker_dry_run_blocked_count"], 1)
            self.assertFalse(result["summary"]["can_start_broker_paper"])
            self.assertFalse(result["summary"]["manual_m12_37_once_allowed"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])

            self.assertEqual(
                result["summary"]["route_counts"],
                {
                    "approved_internal_sim_continue": 2,
                    "rebuild_detector_then_ab": 1,
                    "rescue_ab_collect": 1,
                    "shadow_or_plugin_review": 1,
                },
            )
            rows = {row["strategy_id"]: row for row in result["strategy_routes"]}
            self.assertEqual(rows["M10-PA-004"]["route_category"], "approved_internal_sim_continue")
            self.assertFalse(rows["M10-PA-004"]["broker_watch"])
            self.assertEqual(rows["M10-PA-005"]["route_category"], "approved_internal_sim_continue")
            self.assertTrue(rows["M10-PA-005"]["broker_watch"])
            self.assertEqual(rows["M10-PA-001"]["route_category"], "rescue_ab_collect")
            self.assertTrue(rows["M10-PA-001"]["requires_10_day_ab_evidence"])
            self.assertEqual(rows["M10-PA-011"]["route_category"], "rebuild_detector_then_ab")

            self.assertEqual(
                result["stage_assessment"]["stage_decision"],
                "continue_approved_internal_sim_and_collect_rescue_ab_evidence",
            )
            self.assertEqual(
                result["stage_assessment"]["post_refresh_status"],
                "waiting_for_m12_47_fresh_refresh",
            )
            self.assertEqual(result["rescue_post_refresh_outcome_review"]["watch_rows"], 4)
            self.assertEqual(result["rescue_post_refresh_outcome_review"]["waiting_count"], 4)
            self.assertFalse(result["rescue_post_refresh_outcome_review"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["rescue_external_reference_map"]["mapped_rescue_row_count"], 3)
            self.assertFalse(result["rescue_external_reference_map"]["copy_trading_allowed"])
            self.assertEqual(
                result["stage_assessment"]["external_reference_status"],
                "architecture_reference_only_no_external_override",
            )
            self.assertEqual(
                result["stage_assessment"]["parameter_experiment_status"],
                "queued_for_post_refresh_review_no_mutation",
            )
            self.assertEqual(
                result["stage_assessment"]["parameter_activation_status"],
                "waiting_for_fresh_refresh_no_activation",
            )
            self.assertEqual(
                result["stage_assessment"]["objective_completion_status"],
                "blocked_or_in_progress",
            )
            self.assertEqual(
                result["stage_assessment"]["objective_execution_status"],
                "ready_queue_waiting_for_fresh_refresh",
            )
            self.assertEqual(result["rescue_parameter_experiment_queue"]["experiment_row_count"], 4)
            self.assertEqual(result["rescue_parameter_experiment_queue"]["allowed_now_count"], 0)
            self.assertFalse(result["rescue_parameter_experiment_queue"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["rescue_parameter_activation_gate"]["gate_row_count"], 4)
            self.assertEqual(result["rescue_parameter_activation_gate"]["shadow_review_candidate_count"], 0)
            self.assertEqual(result["rescue_parameter_activation_gate"]["implementation_mutation_allowed_count"], 0)
            self.assertFalse(result["rescue_parameter_activation_gate"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["objective_completion_audit"]["requirement_count"], 12)
            self.assertFalse(result["objective_completion_audit"]["objective_complete"])
            self.assertEqual(result["objective_completion_audit"]["blocked_count"], 3)
            self.assertEqual(result["objective_execution_plan"]["execution_action_count"], 7)
            self.assertEqual(result["objective_execution_plan"]["p0_action_count"], 5)
            self.assertEqual(result["objective_execution_plan"]["manual_execution_allowed_count"], 0)
            self.assertFalse(result["goal_completion_assessment"]["goal_complete"])
            self.assertEqual(
                result["rescue_policy"]["policy"],
                "do_not_discard_before_rescue_route_exhausted",
            )
            self.assertFalse(result["next_fresh_refresh_acceptance"]["manual_m12_37_once_allowed"])

            persisted = json.loads((root / "assessment.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "assessment.md").read_text(encoding="utf-8")
            self.assertIn("M14 Project Stage Assessment", md)
            self.assertIn("Manual M12.37 once-mode allowed: `False`", md)
            self.assertIn("Post-refresh fresh refresh observed: `False`", md)
            self.assertIn("Post-refresh waiting/passed/failed: `4/0/0`", md)
            self.assertIn("External reference rescue/broker rows: `3/1`", md)
            self.assertIn("Parameter experiment rows: `4`", md)
            self.assertIn("Parameter experiments allowed now: `0`", md)
            self.assertIn("Parameter activation shadow-review candidates: `0`", md)
            self.assertIn("Objective audit complete: `False`", md)
            self.assertIn("Objective execution actions/P0/waiting-fresh-refresh: `7/5/5`", md)
            self.assertIn("approved_internal_sim_continue", md)

    def test_rejects_live_or_manual_once_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["manual_m12_37_once"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "manual_m12_37_once"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        goal_path = root / "goal.json"
        next_session_path = root / "next_session.json"
        rescue_plan_path = root / "rescue_plan.json"
        backlog_path = root / "backlog.json"
        post_refresh_path = root / "post_refresh.json"
        external_map_path = root / "external_map.json"
        parameter_queue_path = root / "parameter_queue.json"
        activation_gate_path = root / "activation_gate.json"
        objective_audit_path = root / "objective_audit.json"
        objective_execution_path = root / "objective_execution.json"
        config_path = root / "config.json"

        goal_path.write_text(
            json.dumps(
                {
                    "project_stage_label": "M14 test stage",
                    "m14_trading_date": "2026-05-22",
                    "challenge": {
                        "challenge_progress_label": "10/10",
                        "ten_day_challenge_complete": True,
                        "effective_challenge_trading_days": 10,
                        "required_challenge_trading_days": 10,
                        "data_quality_state": "history_recompute_from_existing_challenge",
                    },
                    "internal_simulation_gate": {
                        "approved_internal_sim_strategy_count": 2,
                        "approved_internal_sim_strategy_ids": ["M10-PA-004", "M10-PA-005"],
                    },
                    "internal_sim_launch_readiness": {
                        "launch_ready_strategy_count": 2,
                    },
                    "rescue_ab_evidence": {
                        "rescue_runtime_strategy_count": 2,
                        "m13_ledger_observed_strategy_count": 1,
                        "no_m13_ledger_evidence_count": 1,
                        "no_m13_ledger_evidence_strategy_ids": ["M10-PA-012-shadow"],
                        "promotion_allowed_count": 0,
                    },
                    "rescue_next_refresh_readiness": {
                        "watch_rows": 4,
                        "parameter_change_allowed_now_count": 0,
                    },
                    "broker_readiness": {
                        "dry_run_ready_count": 1,
                        "blocked_count": 1,
                    },
                    "strategy_action_matrix": [
                        self._matrix_row("M10-PA-004", "continue_internal_simulation", "promote", False),
                        self._matrix_row("M10-PA-005", "continue_internal_simulation", "promote", False),
                        self._matrix_row("M10-PA-001", "collect_rescue_ab_evidence", "modify", True),
                        self._matrix_row("M10-PA-011", "rebuild_detector_ab_evidence", "reject", True),
                        self._matrix_row("M10-PA-003", "continue_shadow_or_plugin_review", "continue_testing", False),
                    ],
                    "next_actions": [
                        {"priority": "P0", "action": "Run approved strategies", "boundary": "No broker/live"}
                    ],
                    "external_reference_policy": {
                        "allowed_use": "architecture inspiration only",
                        "forbidden_use": "copy-trading",
                        "references": [],
                    },
                    "plain_language_result": "Goal fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        next_session_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "next_session_mode": "m12_47_supervised_fresh_refresh_only",
                        "can_run_next_internal_sim_session": True,
                        "approved_runtime_input_connected_count": 3,
                        "approved_runtime_input_count": 3,
                        "broker_watch_strategy_count": 1,
                        "broker_watch_strategy_ids": ["M10-PA-005"],
                    },
                    "strategy_session_rows": [
                        {
                            "strategy_id": "M10-PA-004",
                            "session_action": "continue_internal_simulated_account_testing",
                            "broker_dry_run_blocked_count": 0,
                            "linked_next_refresh_watch_count": 0,
                            "linked_next_refresh_family_counts": {},
                        },
                        {
                            "strategy_id": "M10-PA-005",
                            "session_action": "continue_internal_sim_and_watch_broker_dry_run_blockers",
                            "broker_dry_run_blocked_count": 1,
                            "linked_next_refresh_watch_count": 2,
                            "linked_next_refresh_family_counts": {"broker_rule_shadow_recheck": 2},
                        },
                    ],
                    "global_watch_rows": [
                        {
                            "priority": "P0",
                            "watch_id": "broker_live_boundary_check",
                            "expected_after_refresh": "broker/live stays disabled",
                        }
                    ],
                    "execution_protocol": [
                        {
                            "step": "wait_for_m12_47_supervisor_window",
                            "owner": "M12.47 supervisor",
                            "rule": "Do not run M12.37 once-mode manually.",
                        }
                    ],
                    "plain_language_result": "Next-session fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        rescue_plan_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {"strategy_id": "M10-PA-001", "next_action": "Create rescue variant and collect A/B evidence."},
                        {"strategy_id": "M10-PA-011", "next_action": "Rebuild detector before final rejection."},
                    ],
                    "external_references": [],
                }
            ),
            encoding="utf-8",
        )
        backlog_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "actionable_before_10d_count": 2,
                        "zero_signal_after_connection_count": 1,
                        "missing_rescue_ledger_count": 1,
                        "broker_blocker_reason_counts": {"max_total_exposure_exceeded": 1},
                    },
                    "plain_language_result": "Backlog fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        post_refresh_path.write_text(
            json.dumps(
                {
                    "source_state": {
                        "dashboard_generated_at": "2026-05-26T16:00:00Z",
                    },
                    "summary": {
                        "fresh_refresh_observed": False,
                        "source_quote": "fallback_quotes_only",
                        "source_scan_date": "2026-05-22",
                        "latest_ledger_trading_date": "2026-05-22",
                        "watch_rows": 4,
                        "waiting_count": 4,
                        "passed_count": 0,
                        "failed_count": 0,
                        "outcome_status_counts": {"waiting_for_m12_47_fresh_refresh": 4},
                        "readiness_family_counts": {
                            "first_rescue_ledger_watch": 1,
                            "fresh_quote_recheck": 3,
                        },
                        "manual_m12_37_once_allowed": False,
                    },
                    "plain_language_result": "Post-refresh fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        external_map_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "mapped_rescue_row_count": 3,
                        "broker_blocker_reference_row_count": 1,
                        "p0_reference_row_count": 4,
                        "external_reference_project_count": 2,
                        "next_refresh_dependent_count": 4,
                        "parameter_change_allowed_now_count": 0,
                        "copy_trading_allowed": False,
                        "external_decision_can_override_local_gate": False,
                        "broker_or_live_enabled": False,
                    },
                    "plain_language_result": "External reference fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        parameter_queue_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "experiment_row_count": 4,
                        "rescue_experiment_row_count": 3,
                        "broker_blocker_experiment_count": 1,
                        "allowed_now_count": 0,
                        "blocked_until_fresh_refresh_count": 3,
                        "shadow_runtime_wait_first_ledger_count": 1,
                        "target_stop_experiment_count": 1,
                        "m13_registry_mutation_count": 0,
                        "m12_account_specs_mutation_count": 0,
                        "broker_readiness_status_mutation_count": 0,
                    },
                    "plain_language_result": "Parameter queue fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        activation_gate_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "gate_row_count": 4,
                        "shadow_review_candidate_count": 0,
                        "first_ledger_ready_count": 0,
                        "waiting_for_fresh_refresh_count": 3,
                        "evidence_failed_count": 0,
                        "manual_review_required_count": 0,
                        "implementation_mutation_allowed_count": 0,
                        "parameter_mutation_allowed_count": 0,
                        "m13_registry_mutation_count": 0,
                        "m12_account_specs_mutation_count": 0,
                        "broker_readiness_status_mutation_count": 0,
                    },
                    "plain_language_result": "Activation gate fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        objective_audit_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "objective_complete": False,
                        "requirement_count": 12,
                        "proven_count": 4,
                        "blocked_count": 3,
                        "in_progress_count": 2,
                        "guardrail_count": 3,
                        "requirement_state_counts": {
                            "blocked": 3,
                            "guardrail": 3,
                            "in_progress": 2,
                            "proven": 4,
                        },
                        "objective_blockers": [
                            "weak_strategies_rescue_not_discarded",
                            "rescue_evidence_sufficient_for_promotion",
                        ],
                        "parameter_mutation_allowed_count": 0,
                    },
                    "objective_completion_assessment": {
                        "completion_state": "not_complete",
                    },
                    "plain_language_result": "Objective audit fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        objective_execution_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "execution_action_count": 7,
                        "p0_action_count": 5,
                        "waiting_for_fresh_refresh_action_count": 5,
                        "manual_execution_allowed_count": 0,
                        "execution_action_state_counts": {
                            "blocked_or_in_progress": 1,
                            "collecting_rescue_ab_evidence": 1,
                            "guardrail_watch_only": 1,
                            "ready_for_m12_47_supervisor_window": 1,
                            "review_only_available_now": 1,
                            "waiting_for_m12_47_fresh_refresh": 1,
                            "waiting_for_m12_47_fresh_refresh_no_candidates": 1,
                        },
                        "execution_priority_counts": {"P0": 5, "P1": 2},
                    },
                    "plain_language_result": "Objective execution fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.project-stage-assessment.config.v1",
                    "stage": "M14.project_stage_assessment",
                    "project_stage_label": "fixture project stage assessment",
                    "inputs": {
                        "m14_goal_readiness_report": str(goal_path),
                        "m14_internal_sim_next_session_plan": str(next_session_path),
                        "m14_strategy_rescue_plan": str(rescue_plan_path),
                        "m14_rescue_optimization_backlog": str(backlog_path),
                        "m14_rescue_post_refresh_outcome_review": str(post_refresh_path),
                        "m14_rescue_external_reference_map": str(external_map_path),
                        "m14_rescue_parameter_experiment_queue": str(parameter_queue_path),
                        "m14_rescue_parameter_activation_gate": str(activation_gate_path),
                        "m14_objective_completion_audit": str(objective_audit_path),
                        "m14_objective_execution_plan": str(objective_execution_path),
                    },
                    "outputs": {
                        "assessment_json": str(root / "assessment.json"),
                        "assessment_md": str(root / "assessment.md"),
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

    def _matrix_row(
        self,
        strategy_id: str,
        next_action_category: str,
        decision: str,
        requires_ab: bool,
    ) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "display_name": strategy_id,
            "paper_trial_gate": "approved_internal_sim_only"
            if next_action_category == "continue_internal_simulation"
            else "not_approved_modify_candidate",
            "decision": decision,
            "decision_reason": "fixture",
            "completed_trading_days": 10,
            "runtime_ids": [f"{strategy_id}-runtime"],
            "rescue_runtime_strategy_ids": [f"{strategy_id}-rescue"] if requires_ab else [],
            "requires_10_day_ab_evidence": requires_ab,
            "can_enter_internal_simulation": next_action_category == "continue_internal_simulation",
            "next_action_category": next_action_category,
            "rescue_coverage_status": "covered_by_rescue_runtime" if requires_ab else "",
        }


if __name__ == "__main__":
    unittest.main()
