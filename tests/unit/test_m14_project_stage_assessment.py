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
            self.assertEqual(result["summary"]["parameter_shadow_spec_row_count"], 4)
            self.assertEqual(result["summary"]["parameter_shadow_spec_candidate_variant_count"], 4)
            self.assertEqual(result["summary"]["parameter_shadow_spec_waiting_for_fresh_refresh_count"], 3)
            self.assertEqual(result["summary"]["parameter_shadow_spec_target_stop_variant_count"], 1)
            self.assertEqual(result["summary"]["parameter_shadow_spec_broker_quantity_variant_count"], 1)
            self.assertEqual(result["summary"]["parameter_shadow_spec_broker_rule_variant_count"], 1)
            self.assertEqual(result["summary"]["parameter_shadow_spec_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_decision_ladder_row_count"], 5)
            self.assertEqual(result["summary"]["strategy_decision_approved_next_step_count"], 2)
            self.assertEqual(result["summary"]["strategy_decision_rescue_continue_count"], 2)
            self.assertEqual(result["summary"]["strategy_decision_final_discard_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_decision_candidate_variant_count"], 4)
            self.assertEqual(result["summary"]["strategy_decision_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_evidence_gap_row_count"], 5)
            self.assertEqual(result["summary"]["strategy_evidence_open_gap_row_count"], 5)
            self.assertEqual(result["summary"]["strategy_evidence_requires_fresh_refresh_count"], 4)
            self.assertEqual(result["summary"]["strategy_evidence_wait_first_ledger_gap_count"], 1)
            self.assertEqual(result["summary"]["strategy_evidence_rescue_10_day_ab_gap_count"], 2)
            self.assertEqual(result["summary"]["strategy_evidence_shadow_review_gap_count"], 2)
            self.assertEqual(result["summary"]["strategy_evidence_final_discard_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_evidence_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_evidence_burndown_row_count"], 5)
            self.assertEqual(result["summary"]["strategy_evidence_burndown_open_gap_count"], 5)
            self.assertEqual(result["summary"]["strategy_evidence_burndown_p0_count"], 3)
            self.assertEqual(result["summary"]["strategy_evidence_burndown_p1_count"], 1)
            self.assertEqual(result["summary"]["strategy_evidence_burndown_p2_count"], 1)
            self.assertEqual(result["summary"]["strategy_evidence_burndown_ready_internal_refresh_count"], 2)
            self.assertEqual(result["summary"]["strategy_evidence_burndown_first_ledger_watch_count"], 1)
            self.assertEqual(result["summary"]["strategy_evidence_burndown_rescue_ab_collection_count"], 2)
            self.assertEqual(result["summary"]["strategy_evidence_burndown_shadow_review_wait_count"], 2)
            self.assertEqual(result["summary"]["strategy_evidence_burndown_pre_refresh_review_available_count"], 4)
            self.assertEqual(result["summary"]["strategy_evidence_burndown_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_row_count"], 4)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_p0_count"], 3)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_p1_count"], 0)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_p2_count"], 1)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_fresh_dependent_count"], 3)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_artifact_only_count"], 1)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_external_reference_count"], 2)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_held_count"], 1)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_can_close_gap_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_can_promote_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_can_discard_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_row_count"], 4)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_ready_now_count"], 1)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_wait_fresh_count"], 2)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_backfill_count"], 1)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_external_required_count"], 2)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_external_ready_count"], 2)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_shadow_required_count"], 2)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_shadow_ready_count"], 1)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_can_close_gap_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_pre_refresh_review_audit_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_recheck_row_count"], 3)
            self.assertEqual(result["summary"]["strategy_source_recheck_visual_candidate_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_recheck_research_hold_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_recheck_supporting_rule_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_recheck_external_hold_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_recheck_future_reextract_candidate_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_recheck_can_create_strategy_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_recheck_can_close_gap_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_recheck_can_promote_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_recheck_can_discard_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_recheck_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_plan_row_count"], 3)
            self.assertEqual(result["summary"]["strategy_source_reextract_future_candidate_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_reextract_research_hold_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_reextract_supporting_only_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_reextract_external_hold_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_task_count"], 7)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_question_count"], 6)
            self.assertEqual(result["summary"]["strategy_source_reextract_can_draft_future_spec_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_reextract_can_create_strategy_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_can_close_gap_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_can_promote_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_can_discard_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_row_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_candidate_strategy_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_source_atom_count"], 10)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_answer_count"], 6)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_visual_required_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_future_spec_draftable_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_can_create_strategy_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_can_close_gap_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_can_promote_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_can_discard_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_gate_row_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_case_count"], 10)
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_positive_case_count"], 6)
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_counterexample_case_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_boundary_case_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_checksum_match_count"], 10)
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_ready_count"], 2)
            self.assertEqual(
                result["summary"]["strategy_source_visual_alignment_manual_confirmation_required_count"],
                2,
            )
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_can_draft_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_can_create_strategy_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_packet_row_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_item_count"], 6)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_case_count"], 10)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_packet_ready_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_recorded_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_future_spec_unblocked_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_can_draft_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_can_create_strategy_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_response_gate_row_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_response_question_required_count"], 6)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_response_question_confirmed_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_response_question_pending_count"], 6)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_response_case_required_count"], 10)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_response_case_confirmed_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_response_case_pending_count"], 10)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_response_complete_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_response_future_spec_unblocked_count"], 0)
            self.assertEqual(
                result["summary"]["strategy_source_visual_confirmation_response_ready_for_future_spec_draft_count"],
                0,
            )
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_response_invalid_count"], 0)
            self.assertEqual(
                result["summary"]["strategy_source_visual_confirmation_response_can_create_strategy_now_count"],
                0,
            )
            self.assertEqual(
                result["summary"]["strategy_source_visual_confirmation_response_parameter_mutation_allowed_count"],
                0,
            )
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
            self.assertEqual(result["summary"]["post_fresh_recompute_step_count"], 24)
            self.assertEqual(result["summary"]["post_fresh_recompute_m14_script_step_count"], 23)
            self.assertEqual(result["summary"]["post_fresh_recompute_acceptance_gate_count"], 7)
            self.assertTrue(result["summary"]["post_fresh_recompute_two_pass_required"])
            self.assertEqual(result["summary"]["post_fresh_recompute_parameter_mutation_allowed_count"], 0)
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
                result["stage_assessment"]["parameter_shadow_spec_status"],
                "shadow_specs_prepared_no_mutation",
            )
            self.assertEqual(
                result["stage_assessment"]["strategy_decision_ladder_status"],
                "no_final_discard_until_rescue_exhausted",
            )
            self.assertEqual(
                result["stage_assessment"]["strategy_pre_refresh_review_status"],
                "review_packet_ready_no_gap_closure_or_mutation",
            )
            self.assertEqual(
                result["stage_assessment"]["strategy_pre_refresh_review_audit_status"],
                "supporting_artifact_backfill_needed_no_gap_closure_or_mutation",
            )
            self.assertEqual(
                result["stage_assessment"]["strategy_source_recheck_status"],
                "source_recheck_triage_ready_no_gap_closure_or_mutation",
            )
            self.assertEqual(
                result["stage_assessment"]["strategy_source_reextract_plan_status"],
                "source_reextract_plan_ready_no_strategy_creation_or_mutation",
            )
            self.assertEqual(
                result["stage_assessment"]["strategy_source_reextract_review_status"],
                "source_reextract_review_ready_no_strategy_creation_or_mutation",
            )
            self.assertEqual(
                result["stage_assessment"]["strategy_source_visual_alignment_status"],
                "source_visual_alignment_ready_for_manual_review_no_strategy_creation_or_mutation",
            )
            self.assertEqual(
                result["stage_assessment"]["strategy_source_visual_confirmation_status"],
                "manual_confirmation_packet_ready_no_confirmation_recorded",
            )
            self.assertEqual(
                result["stage_assessment"]["strategy_source_visual_confirmation_response_status"],
                "manual_response_gate_pending_no_future_spec_unblocked",
            )
            self.assertTrue(
                any(
                    "Strategy source reextract review has 2 packets" in item
                    for item in result["stage_assessment"]["next_required_evidence"]
                )
            )
            self.assertTrue(
                any(
                    "Strategy source visual alignment gate has 2 rows" in item
                    for item in result["stage_assessment"]["next_required_evidence"]
                )
            )
            self.assertTrue(
                any(
                    "Strategy source visual confirmation packet has 2 rows" in item
                    for item in result["stage_assessment"]["next_required_evidence"]
                )
            )
            self.assertTrue(
                any(
                    "Strategy source visual confirmation response gate has 2 rows" in item
                    for item in result["stage_assessment"]["next_required_evidence"]
                )
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
            self.assertEqual(result["rescue_parameter_shadow_spec"]["spec_row_count"], 4)
            self.assertEqual(result["rescue_parameter_shadow_spec"]["candidate_variant_count"], 4)
            self.assertEqual(result["rescue_parameter_shadow_spec"]["parameter_mutation_allowed_count"], 0)
            self.assertFalse(result["rescue_parameter_shadow_spec"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["strategy_decision_ladder"]["strategy_ladder_row_count"], 5)
            self.assertEqual(result["strategy_decision_ladder"]["approved_next_step_count"], 2)
            self.assertEqual(result["strategy_decision_ladder"]["final_discard_allowed_count"], 0)
            self.assertFalse(result["strategy_decision_ladder"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["strategy_evidence_gap_matrix"]["strategy_gap_row_count"], 5)
            self.assertEqual(result["strategy_evidence_gap_matrix"]["open_evidence_gap_row_count"], 5)
            self.assertEqual(result["strategy_evidence_gap_matrix"]["final_discard_allowed_count"], 0)
            self.assertFalse(result["strategy_evidence_gap_matrix"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["strategy_evidence_gap_burndown"]["burndown_row_count"], 5)
            self.assertEqual(result["strategy_evidence_gap_burndown"]["p0_row_count"], 3)
            self.assertEqual(result["strategy_evidence_gap_burndown"]["p1_row_count"], 1)
            self.assertEqual(result["strategy_evidence_gap_burndown"]["p2_row_count"], 1)
            self.assertEqual(result["strategy_evidence_gap_burndown"]["first_ledger_watch_row_count"], 1)
            self.assertEqual(result["strategy_evidence_gap_burndown"]["rescue_ab_collection_row_count"], 2)
            self.assertFalse(result["strategy_evidence_gap_burndown"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["strategy_pre_refresh_review_packet"]["review_row_count"], 4)
            self.assertEqual(result["strategy_pre_refresh_review_packet"]["p0_review_count"], 3)
            self.assertEqual(
                result["strategy_pre_refresh_review_packet"]["m12_47_fresh_refresh_dependent_review_count"],
                3,
            )
            self.assertEqual(result["strategy_pre_refresh_review_packet"]["artifact_only_review_count"], 1)
            self.assertEqual(result["strategy_pre_refresh_review_packet"]["external_reference_review_row_count"], 2)
            self.assertEqual(result["strategy_pre_refresh_review_packet"]["review_can_close_gap_now_count"], 0)
            self.assertFalse(result["strategy_pre_refresh_review_packet"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["strategy_pre_refresh_review_audit"]["audit_row_count"], 4)
            self.assertEqual(result["strategy_pre_refresh_review_audit"]["ready_for_artifact_review_now_count"], 1)
            self.assertEqual(result["strategy_pre_refresh_review_audit"]["pre_review_ready_wait_fresh_evidence_count"], 2)
            self.assertEqual(result["strategy_pre_refresh_review_audit"]["needs_supporting_artifact_backfill_count"], 1)
            self.assertEqual(result["strategy_pre_refresh_review_audit"]["review_can_close_gap_now_count"], 0)
            self.assertFalse(result["strategy_pre_refresh_review_audit"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["strategy_source_recheck_triage"]["source_recheck_row_count"], 3)
            self.assertEqual(
                result["strategy_source_recheck_triage"]["source_visual_recheck_candidate_count"],
                1,
            )
            self.assertEqual(result["strategy_source_recheck_triage"]["recheck_can_close_gap_now_count"], 0)
            self.assertEqual(
                result["strategy_source_recheck_triage"]["parameter_mutation_allowed_now_count"],
                0,
            )
            self.assertFalse(result["strategy_source_recheck_triage"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["strategy_source_reextract_plan"]["source_reextract_plan_row_count"], 3)
            self.assertEqual(
                result["strategy_source_reextract_plan"]["future_source_reextract_candidate_count"],
                1,
            )
            self.assertEqual(result["strategy_source_reextract_plan"]["source_ref_review_task_count"], 7)
            self.assertEqual(result["strategy_source_reextract_plan"]["can_create_strategy_now_count"], 0)
            self.assertEqual(
                result["strategy_source_reextract_plan"]["parameter_mutation_allowed_now_count"],
                0,
            )
            self.assertFalse(result["strategy_source_reextract_plan"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["strategy_source_reextract_review"]["source_reextract_review_row_count"], 2)
            self.assertEqual(result["strategy_source_reextract_review"]["source_backed_atom_count"], 10)
            self.assertEqual(result["strategy_source_reextract_review"]["source_review_answer_count"], 6)
            self.assertEqual(result["strategy_source_reextract_review"]["future_spec_draftable_count"], 2)
            self.assertEqual(result["strategy_source_reextract_review"]["visual_review_required_count"], 2)
            self.assertEqual(result["strategy_source_reextract_review"]["can_create_strategy_now_count"], 0)
            self.assertEqual(
                result["strategy_source_reextract_review"]["parameter_mutation_allowed_now_count"],
                0,
            )
            self.assertFalse(result["strategy_source_reextract_review"]["manual_m12_37_once_allowed"])
            self.assertFalse(result["strategy_source_reextract_review"]["strategy_state_mutation_allowed"])
            self.assertEqual(
                result["strategy_source_visual_alignment_gate"]["source_visual_alignment_gate_row_count"],
                2,
            )
            self.assertEqual(result["strategy_source_visual_alignment_gate"]["visual_case_count"], 10)
            self.assertEqual(result["strategy_source_visual_alignment_gate"]["checksum_match_count"], 10)
            self.assertEqual(
                result["strategy_source_visual_alignment_gate"]["ready_for_manual_visual_alignment_count"],
                2,
            )
            self.assertEqual(
                result["strategy_source_visual_alignment_gate"]["manual_visual_confirmation_required_count"],
                2,
            )
            self.assertEqual(
                result["strategy_source_visual_alignment_gate"]["can_draft_future_source_reextract_spec_now_count"],
                0,
            )
            self.assertFalse(result["strategy_source_visual_alignment_gate"]["manual_m12_37_once_allowed"])
            self.assertFalse(result["strategy_source_visual_alignment_gate"]["strategy_state_mutation_allowed"])
            self.assertEqual(
                result["strategy_source_visual_confirmation_packet"]["source_visual_confirmation_packet_row_count"],
                2,
            )
            self.assertEqual(result["strategy_source_visual_confirmation_packet"]["confirmation_item_count"], 6)
            self.assertEqual(result["strategy_source_visual_confirmation_packet"]["confirmation_case_row_count"], 10)
            self.assertEqual(
                result["strategy_source_visual_confirmation_packet"]["manual_visual_confirmation_recorded_count"],
                0,
            )
            self.assertEqual(result["strategy_source_visual_confirmation_packet"]["future_spec_unblocked_count"], 0)
            self.assertEqual(
                result["strategy_source_visual_confirmation_packet"]["can_draft_future_source_reextract_spec_now_count"],
                0,
            )
            self.assertFalse(result["strategy_source_visual_confirmation_packet"]["manual_m12_37_once_allowed"])
            self.assertFalse(result["strategy_source_visual_confirmation_packet"]["strategy_state_mutation_allowed"])
            self.assertEqual(
                result["strategy_source_visual_confirmation_response_gate"][
                    "source_visual_confirmation_response_gate_row_count"
                ],
                2,
            )
            self.assertEqual(
                result["strategy_source_visual_confirmation_response_gate"]["question_response_pending_count"],
                6,
            )
            self.assertEqual(
                result["strategy_source_visual_confirmation_response_gate"]["case_response_pending_count"],
                10,
            )
            self.assertEqual(
                result["strategy_source_visual_confirmation_response_gate"]["future_spec_unblocked_count"],
                0,
            )
            self.assertFalse(
                result["strategy_source_visual_confirmation_response_gate"]["manual_m12_37_once_allowed"]
            )
            self.assertFalse(
                result["strategy_source_visual_confirmation_response_gate"]["strategy_state_mutation_allowed"]
            )
            self.assertEqual(result["objective_completion_audit"]["requirement_count"], 12)
            self.assertFalse(result["objective_completion_audit"]["objective_complete"])
            self.assertEqual(result["objective_completion_audit"]["blocked_count"], 3)
            self.assertEqual(result["objective_execution_plan"]["execution_action_count"], 7)
            self.assertEqual(result["objective_execution_plan"]["p0_action_count"], 5)
            self.assertEqual(result["objective_execution_plan"]["manual_execution_allowed_count"], 0)
            self.assertEqual(result["post_fresh_refresh_recompute_checklist"]["recompute_step_count"], 24)
            self.assertEqual(result["post_fresh_refresh_recompute_checklist"]["m14_script_step_count"], 23)
            self.assertFalse(
                result["post_fresh_refresh_recompute_checklist"]["manual_m12_37_once_allowed"]
            )
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
            self.assertIn("Parameter shadow spec rows/variants/waiting-fresh-refresh: `4/4/3`", md)
            self.assertIn("Strategy decision rows/approved-next/rescue/final-discard: `5/2/2/0`", md)
            self.assertIn("Strategy evidence gap rows/open/fresh-refresh: `5/5/4`", md)
            self.assertIn("Strategy evidence first-ledger/10-day/shadow gaps: `1/2/2`", md)
            self.assertIn("Strategy evidence burndown rows/P0/P1/P2: `5/3/1/1`", md)
            self.assertIn("Strategy evidence burndown approved-refresh/first-ledger/rescue-A-B/shadow-review: `2/1/2/2`", md)
            self.assertIn("Strategy pre-refresh review rows/P0/P1/P2: `4/3/0/1`", md)
            self.assertIn("Strategy pre-refresh review close/promote/discard/mutation allowed: `0/0/0/0`", md)
            self.assertIn("Strategy pre-refresh review audit rows/ready/waiting/backfill: `4/1/2/1`", md)
            self.assertIn("Strategy pre-refresh review audit close/promote/discard/mutation allowed: `0/0/0/0`", md)
            self.assertIn("Strategy source reextract plan rows/future/tasks/questions: `3/1/7/6`", md)
            self.assertIn("Strategy source reextract plan create/close/promote/discard/mutation allowed: `0/0/0/0/0`", md)
            self.assertIn("Strategy source reextract review packets/atoms/answers/draftable/visual-required: `2/10/6/2/2`", md)
            self.assertIn("Strategy source reextract review status: `source_reextract_review_ready_no_strategy_creation_or_mutation`", md)
            self.assertIn("Strategy source visual alignment rows/cases/checksum/ready/manual-required: `2/10/10/2/2`", md)
            self.assertIn("Strategy source visual alignment status: `source_visual_alignment_ready_for_manual_review_no_strategy_creation_or_mutation`", md)
            self.assertIn("Strategy source visual confirmation response rows/questions pending/cases pending/complete/unblocked: `2/6/10/0/0`", md)
            self.assertIn("Strategy source visual confirmation response status: `manual_response_gate_pending_no_future_spec_unblocked`", md)
            self.assertIn("Objective audit complete: `False`", md)
            self.assertIn("Objective execution actions/P0/waiting-fresh-refresh: `7/5/5`", md)
            self.assertIn("Post-fresh recompute steps/M14 scripts/gates: `24/23/7`", md)
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
        parameter_shadow_spec_path = root / "parameter_shadow_spec.json"
        strategy_decision_ladder_path = root / "strategy_decision_ladder.json"
        strategy_evidence_gap_matrix_path = root / "strategy_evidence_gap_matrix.json"
        strategy_evidence_gap_burndown_path = root / "strategy_evidence_gap_burndown.json"
        strategy_pre_refresh_review_packet_path = root / "strategy_pre_refresh_review_packet.json"
        strategy_pre_refresh_review_audit_path = root / "strategy_pre_refresh_review_audit.json"
        strategy_source_recheck_triage_path = root / "strategy_source_recheck_triage.json"
        strategy_source_reextract_plan_path = root / "strategy_source_reextract_plan.json"
        strategy_source_reextract_review_path = root / "strategy_source_reextract_review.json"
        strategy_source_visual_alignment_gate_path = root / "strategy_source_visual_alignment_gate.json"
        strategy_source_visual_confirmation_packet_path = root / "strategy_source_visual_confirmation_packet.json"
        strategy_source_visual_confirmation_response_gate_path = (
            root / "strategy_source_visual_confirmation_response_gate.json"
        )
        objective_audit_path = root / "objective_audit.json"
        objective_execution_path = root / "objective_execution.json"
        post_fresh_checklist_path = root / "post_fresh_checklist.json"
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
        parameter_shadow_spec_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "spec_row_count": 4,
                        "candidate_variant_count": 4,
                        "waiting_for_fresh_refresh_count": 3,
                        "target_stop_shadow_variant_count": 1,
                        "broker_quantity_cap_variant_count": 1,
                        "broker_rule_shadow_variant_count": 1,
                        "ready_for_manual_shadow_review_count": 0,
                        "implementation_mutation_allowed_count": 0,
                        "parameter_mutation_allowed_count": 0,
                        "m13_registry_mutation_count": 0,
                        "m12_account_specs_mutation_count": 0,
                        "broker_readiness_status_mutation_count": 0,
                    },
                    "plain_language_result": "Parameter shadow spec fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        strategy_decision_ladder_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "strategy_ladder_row_count": 5,
                        "approved_next_step_count": 2,
                        "rescue_continue_count": 2,
                        "manual_review_ready_count": 0,
                        "promotion_candidate_count": 0,
                        "final_discard_allowed_count": 0,
                        "shadow_spec_strategy_count": 2,
                        "candidate_variant_count": 4,
                        "parameter_mutation_allowed_count": 0,
                        "m13_registry_mutation_count": 0,
                        "m12_account_specs_mutation_count": 0,
                        "broker_readiness_status_mutation_count": 0,
                    },
                    "plain_language_result": "Decision ladder fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        strategy_evidence_gap_matrix_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "strategy_gap_row_count": 5,
                        "open_evidence_gap_row_count": 5,
                        "requires_m12_47_fresh_refresh_count": 4,
                        "wait_first_ledger_gap_count": 1,
                        "rescue_10_day_ab_gap_count": 2,
                        "shadow_review_gap_count": 2,
                        "final_discard_allowed_count": 0,
                        "promotion_candidate_count": 0,
                        "parameter_mutation_allowed_count": 0,
                    },
                    "plain_language_result": "Evidence gap matrix fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        strategy_evidence_gap_burndown_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "burndown_row_count": 5,
                        "open_evidence_gap_row_count": 5,
                        "priority_counts": {"P0": 3, "P1": 1, "P2": 1},
                        "burn_down_lane_counts": {
                            "approved_internal_sim_refresh": 2,
                            "first_rescue_ledger": 1,
                            "rescue_ab_collection": 2,
                            "shadow_plugin_research": 1,
                        },
                        "p0_row_count": 3,
                        "p1_row_count": 1,
                        "p2_row_count": 1,
                        "ready_for_internal_sim_refresh_count": 2,
                        "first_ledger_watch_row_count": 1,
                        "rescue_ab_collection_row_count": 2,
                        "shadow_review_wait_row_count": 2,
                        "pre_refresh_review_available_count": 4,
                        "parameter_experiment_row_count": 4,
                        "parameter_activation_waiting_for_fresh_refresh_count": 3,
                        "promotion_candidate_count": 0,
                        "final_discard_allowed_count": 0,
                        "parameter_mutation_allowed_count": 0,
                        "manual_execution_allowed_count": 0,
                    },
                    "plain_language_result": "Evidence gap burndown fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        strategy_pre_refresh_review_packet_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "review_row_count": 4,
                        "held_no_pre_refresh_action_count": 1,
                        "p0_review_count": 3,
                        "p1_review_count": 0,
                        "p2_review_count": 1,
                        "m12_47_fresh_refresh_dependent_review_count": 3,
                        "artifact_only_review_count": 1,
                        "external_reference_review_row_count": 2,
                        "review_can_close_gap_now_count": 0,
                        "review_can_promote_now_count": 0,
                        "review_can_discard_now_count": 0,
                        "parameter_mutation_allowed_now_count": 0,
                        "manual_m12_37_once_allowed": False,
                    },
                    "plain_language_result": "Pre-refresh review fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        strategy_pre_refresh_review_audit_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "audit_row_count": 4,
                        "ready_for_artifact_review_now_count": 1,
                        "pre_review_ready_wait_fresh_evidence_count": 2,
                        "needs_supporting_artifact_backfill_count": 1,
                        "external_reference_required_count": 2,
                        "external_reference_ready_count": 2,
                        "shadow_parameter_required_count": 2,
                        "shadow_parameter_artifact_ready_count": 1,
                        "decision_ladder_present_count": 4,
                        "review_can_close_gap_now_count": 0,
                        "review_can_promote_now_count": 0,
                        "review_can_discard_now_count": 0,
                        "parameter_mutation_allowed_now_count": 0,
                        "manual_m12_37_once_allowed": False,
                    },
                    "plain_language_result": "Pre-refresh audit fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        strategy_source_recheck_triage_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_recheck_row_count": 3,
                        "source_visual_recheck_candidate_count": 1,
                        "research_only_risk_definition_hold_count": 1,
                        "supporting_rule_attach_to_parent_count": 1,
                        "external_reference_hold_count": 0,
                        "source_recheck_hold_count": 0,
                        "local_m10_row_count": 3,
                        "eligible_for_future_source_reextract_count": 1,
                        "standalone_strategy_creation_allowed_count": 0,
                        "recheck_can_close_gap_now_count": 0,
                        "recheck_can_promote_now_count": 0,
                        "recheck_can_discard_now_count": 0,
                        "parameter_mutation_allowed_now_count": 0,
                        "manual_m12_37_once_allowed": False,
                    },
                    "plain_language_result": "Source recheck fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        strategy_source_reextract_plan_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_reextract_plan_row_count": 3,
                        "future_source_reextract_candidate_count": 1,
                        "research_only_hold_no_reextract_count": 1,
                        "supporting_rule_no_standalone_reextract_count": 1,
                        "external_reference_hold_count": 0,
                        "source_ref_review_task_count": 7,
                        "source_review_question_count": 6,
                        "can_draft_future_source_reextract_spec_count": 1,
                        "can_create_strategy_now_count": 0,
                        "can_close_gap_now_count": 0,
                        "can_promote_now_count": 0,
                        "can_discard_now_count": 0,
                        "parameter_mutation_allowed_now_count": 0,
                    },
                    "plain_language_result": "Source reextract plan fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        strategy_source_reextract_review_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_reextract_review_row_count": 2,
                        "candidate_strategy_count": 2,
                        "source_backed_atom_count": 10,
                        "source_review_answer_count": 6,
                        "markdown_source_ref_count": 6,
                        "markdown_source_ref_exists_count": 6,
                        "non_markdown_source_ref_count": 0,
                        "future_spec_draftable_count": 2,
                        "visual_review_required_count": 2,
                        "can_create_strategy_now_count": 0,
                        "can_close_gap_now_count": 0,
                        "can_promote_now_count": 0,
                        "can_discard_now_count": 0,
                        "parameter_mutation_allowed_now_count": 0,
                        "future_spec_readiness_counts": {
                            "draftable_after_visual_case_alignment": 1,
                            "draftable_as_visual_first_dual_route_spec": 1,
                        },
                    },
                    "plain_language_result": "Source reextract review fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        strategy_source_visual_alignment_gate_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_visual_alignment_gate_row_count": 2,
                        "candidate_strategy_count": 2,
                        "visual_case_count": 10,
                        "positive_case_count": 6,
                        "counterexample_case_count": 2,
                        "boundary_case_count": 2,
                        "checksum_match_count": 10,
                        "current_worktree_asset_exists_count": 0,
                        "old_worktree_asset_exists_count": 10,
                        "missing_asset_count": 0,
                        "ready_for_manual_visual_alignment_count": 2,
                        "manual_visual_confirmation_required_count": 2,
                        "future_spec_blocked_until_visual_confirmation_count": 2,
                        "can_draft_future_source_reextract_spec_now_count": 0,
                        "can_create_strategy_now_count": 0,
                        "parameter_mutation_allowed_now_count": 0,
                    },
                    "plain_language_result": "Source visual alignment fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        strategy_source_visual_confirmation_packet_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_visual_confirmation_packet_row_count": 2,
                        "candidate_strategy_count": 2,
                        "confirmation_item_count": 6,
                        "confirmation_case_row_count": 10,
                        "packet_ready_count": 2,
                        "manual_visual_confirmation_required_count": 2,
                        "manual_visual_confirmation_recorded_count": 0,
                        "future_spec_unblocked_count": 0,
                        "can_draft_future_source_reextract_spec_now_count": 0,
                        "can_create_strategy_now_count": 0,
                        "parameter_mutation_allowed_now_count": 0,
                    },
                    "plain_language_result": "Source visual confirmation fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        strategy_source_visual_confirmation_response_gate_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_visual_confirmation_response_gate_row_count": 2,
                        "candidate_strategy_count": 2,
                        "question_response_required_count": 6,
                        "question_response_confirmed_count": 0,
                        "question_response_pending_count": 6,
                        "case_response_required_count": 10,
                        "case_response_confirmed_count": 0,
                        "case_response_pending_count": 10,
                        "manual_visual_confirmation_complete_count": 0,
                        "future_spec_unblocked_count": 0,
                        "ready_for_future_source_reextract_spec_draft_count": 0,
                        "invalid_response_count": 0,
                        "can_create_strategy_now_count": 0,
                        "parameter_mutation_allowed_now_count": 0,
                    },
                    "plain_language_result": "Source visual confirmation response gate fixture plain result.",
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
        post_fresh_checklist_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "recompute_step_count": 24,
                        "m14_script_step_count": 23,
                        "acceptance_gate_count": 7,
                        "requires_m12_47_fresh_refresh_step_count": 24,
                        "two_pass_stabilization_required": True,
                        "fresh_refresh_observed": False,
                        "source_quote": "fallback_quotes_only",
                        "parameter_mutation_allowed_count": 0,
                    },
                    "plain_language_result": "Post-fresh checklist fixture plain result.",
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
                        "m14_rescue_parameter_shadow_spec": str(parameter_shadow_spec_path),
                        "m14_strategy_decision_ladder": str(strategy_decision_ladder_path),
                        "m14_strategy_evidence_gap_matrix": str(strategy_evidence_gap_matrix_path),
                        "m14_strategy_evidence_gap_burndown": str(strategy_evidence_gap_burndown_path),
                        "m14_strategy_pre_refresh_review_packet": str(strategy_pre_refresh_review_packet_path),
                        "m14_strategy_pre_refresh_review_audit": str(strategy_pre_refresh_review_audit_path),
                        "m14_strategy_source_recheck_triage": str(strategy_source_recheck_triage_path),
                        "m14_strategy_source_reextract_plan": str(strategy_source_reextract_plan_path),
                        "m14_strategy_source_reextract_review": str(strategy_source_reextract_review_path),
                        "m14_strategy_source_visual_alignment_gate": str(
                            strategy_source_visual_alignment_gate_path
                        ),
                        "m14_strategy_source_visual_confirmation_packet": str(
                            strategy_source_visual_confirmation_packet_path
                        ),
                        "m14_strategy_source_visual_confirmation_response_gate": str(
                            strategy_source_visual_confirmation_response_gate_path
                        ),
                        "m14_objective_completion_audit": str(objective_audit_path),
                        "m14_objective_execution_plan": str(objective_execution_path),
                        "m14_post_fresh_refresh_recompute_checklist": str(post_fresh_checklist_path),
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
