from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_objective_completion_audit_lib import load_config, run_m14_objective_completion_audit


class M14ObjectiveCompletionAuditTest(unittest.TestCase):
    def test_builds_objective_audit_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_objective_completion_audit(
                load_config(config_path),
                generated_at="2026-05-26T22:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.objective-completion-audit.v1")
            self.assertFalse(result["summary"]["objective_complete"])
            self.assertEqual(result["summary"]["current_project_stage"], "M14 fixture stage")
            self.assertTrue(result["summary"]["ten_day_challenge_complete"])
            self.assertEqual(result["summary"]["challenge_progress_label"], "10/10")
            self.assertEqual(result["summary"]["approved_internal_sim_strategy_count"], 2)
            self.assertEqual(result["summary"]["approved_internal_sim_strategy_ids"], ["M10-PA-004", "M10-PA-005"])
            self.assertEqual(result["summary"]["rescue_runtime_strategy_count"], 2)
            self.assertEqual(result["summary"]["rescue_m13_ledger_observed_strategy_count"], 1)
            self.assertEqual(result["summary"]["rescue_no_m13_ledger_evidence_count"], 1)
            self.assertEqual(result["summary"]["rescue_promotion_allowed_count"], 0)
            self.assertEqual(result["summary"]["parameter_experiment_row_count"], 4)
            self.assertEqual(result["summary"]["parameter_activation_shadow_review_candidate_count"], 0)
            self.assertEqual(result["summary"]["parameter_shadow_spec_row_count"], 4)
            self.assertEqual(result["summary"]["parameter_shadow_spec_candidate_variant_count"], 4)
            self.assertEqual(result["summary"]["parameter_shadow_spec_waiting_for_fresh_refresh_count"], 3)
            self.assertEqual(result["summary"]["parameter_shadow_spec_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_decision_ladder_row_count"], 6)
            self.assertEqual(result["summary"]["strategy_decision_approved_next_step_count"], 2)
            self.assertEqual(result["summary"]["strategy_decision_rescue_continue_count"], 3)
            self.assertEqual(result["summary"]["strategy_decision_final_discard_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_decision_promotion_candidate_count"], 0)
            self.assertEqual(result["summary"]["strategy_evidence_gap_row_count"], 6)
            self.assertEqual(result["summary"]["strategy_evidence_open_gap_row_count"], 6)
            self.assertEqual(result["summary"]["strategy_evidence_requires_fresh_refresh_count"], 4)
            self.assertEqual(result["summary"]["strategy_evidence_wait_first_ledger_gap_count"], 1)
            self.assertEqual(result["summary"]["strategy_evidence_rescue_10_day_ab_gap_count"], 3)
            self.assertEqual(result["summary"]["strategy_evidence_shadow_review_gap_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_recheck_row_count"], 3)
            self.assertEqual(result["summary"]["strategy_source_recheck_visual_candidate_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_recheck_future_reextract_candidate_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_recheck_research_hold_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_recheck_supporting_rule_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_recheck_external_hold_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_recheck_can_create_strategy_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_recheck_parameter_mutation_allowed_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_reextract_plan_row_count"], 3)
            self.assertEqual(result["summary"]["strategy_source_reextract_future_candidate_count"], 1)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_task_count"], 7)
            self.assertEqual(result["summary"]["strategy_source_reextract_review_question_count"], 6)
            self.assertEqual(result["summary"]["strategy_source_reextract_can_create_strategy_now_count"], 0)
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
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_checksum_match_count"], 10)
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_ready_count"], 2)
            self.assertEqual(
                result["summary"]["strategy_source_visual_alignment_manual_confirmation_required_count"],
                2,
            )
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_can_draft_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_alignment_can_create_strategy_now_count"], 0)
            self.assertEqual(
                result["summary"]["strategy_source_visual_alignment_parameter_mutation_allowed_count"],
                0,
            )
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_packet_row_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_item_count"], 6)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_case_count"], 10)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_packet_ready_count"], 2)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_recorded_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_future_spec_unblocked_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_can_draft_now_count"], 0)
            self.assertEqual(result["summary"]["strategy_source_visual_confirmation_can_create_strategy_now_count"], 0)
            self.assertEqual(
                result["summary"]["strategy_source_visual_confirmation_parameter_mutation_allowed_count"],
                0,
            )
            self.assertFalse(result["summary"]["fresh_refresh_observed"])
            self.assertEqual(result["summary"]["post_refresh_waiting_count"], 4)
            self.assertEqual(result["summary"]["external_reference_project_count"], 2)
            self.assertFalse(result["summary"]["broker_or_live_enabled"])
            self.assertFalse(result["summary"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["summary"]["requirement_count"], 13)
            self.assertEqual(
                result["summary"]["requirement_state_counts"],
                {"blocked": 3, "guardrail": 3, "in_progress": 3, "proven": 4},
            )
            self.assertFalse(result["objective_completion_assessment"]["objective_complete"])

            rows = {row["requirement_id"]: row for row in result["requirement_rows"]}
            self.assertEqual(rows["project_stage_identified"]["state"], "proven")
            self.assertEqual(rows["ten_day_challenge_complete"]["state"], "proven")
            self.assertEqual(rows["weak_strategies_rescue_not_discarded"]["state"], "in_progress")
            self.assertIn("decision ladder keeps 3", rows["weak_strategies_rescue_not_discarded"]["evidence"])
            self.assertIn("evidence gap matrix has 6 open rows", rows["weak_strategies_rescue_not_discarded"]["evidence"])
            self.assertIn(
                "m14_strategy_decision_ladder",
                rows["weak_strategies_rescue_not_discarded"]["source_refs"],
            )
            self.assertIn(
                "m14_strategy_evidence_gap_matrix",
                rows["weak_strategies_rescue_not_discarded"]["source_refs"],
            )
            self.assertEqual(rows["rescue_evidence_sufficient_for_promotion"]["state"], "blocked")
            self.assertEqual(rows["parameter_optimization_path_ready"]["state"], "in_progress")
            self.assertIn("shadow specs cover 4", rows["parameter_optimization_path_ready"]["evidence"])
            self.assertIn("evidence gap matrix shows 2 shadow-review gaps", rows["parameter_optimization_path_ready"]["evidence"])
            self.assertIn(
                "m14_rescue_parameter_shadow_spec",
                rows["parameter_optimization_path_ready"]["source_refs"],
            )
            self.assertIn(
                "m14_strategy_evidence_gap_matrix",
                rows["parameter_optimization_path_ready"]["source_refs"],
            )
            self.assertEqual(rows["source_reextract_path_ready"]["state"], "in_progress")
            self.assertIn("3 artifact-only rows", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("1 future source-reextract candidates", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("source reextract plan has 3 rows", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("7 review tasks", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("source reextract review has 2 packets", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("10 source-backed atoms", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("2 draftable future specs", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("source visual alignment gate has 2 rows", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("10 visual cases", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("2 manual-confirmation-required rows", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("source visual confirmation packet has 2 rows", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("6 confirmation questions", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn("0 recorded confirmations", rows["source_reextract_path_ready"]["evidence"])
            self.assertIn(
                "m14_strategy_source_recheck_triage",
                rows["source_reextract_path_ready"]["source_refs"],
            )
            self.assertIn(
                "m14_strategy_source_reextract_plan",
                rows["source_reextract_path_ready"]["source_refs"],
            )
            self.assertIn(
                "m14_strategy_source_reextract_review",
                rows["source_reextract_path_ready"]["source_refs"],
            )
            self.assertIn(
                "m14_strategy_source_visual_alignment_gate",
                rows["source_reextract_path_ready"]["source_refs"],
            )
            self.assertIn(
                "m14_strategy_source_visual_confirmation_packet",
                rows["source_reextract_path_ready"]["source_refs"],
            )
            self.assertEqual(rows["fresh_refresh_required_before_parameter_activation"]["state"], "blocked")
            self.assertEqual(rows["broker_live_real_order_disabled"]["state"], "guardrail")
            self.assertEqual(rows["manual_m12_37_once_disabled"]["state"], "guardrail")
            for row in result["requirement_rows"]:
                self.assertFalse(row["broker_connection"])
                self.assertFalse(row["real_order"])
                self.assertFalse(row["live_execution"])
                self.assertFalse(row["manual_m12_37_once"])
                self.assertFalse(row["parameter_mutation"])

            persisted = json.loads((root / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "audit.md").read_text(encoding="utf-8")
            self.assertIn("M14 Objective Completion Audit", md)
            self.assertIn("Objective complete: `False`", md)
            self.assertIn("Parameter shadow specs/variants: `4/4`", md)
            self.assertIn("Strategy evidence gaps open/fresh/first-ledger/10-day/shadow: `6/4/1/3/2`", md)
            self.assertIn("Source recheck rows/future-reextract: `3/1`", md)
            self.assertIn("Source reextract plan rows/future/tasks/questions: `3/1/7/6`", md)
            self.assertIn("Source reextract review packets/atoms/answers/draftable/visual-required: `2/10/6/2/2`", md)
            self.assertIn("Source visual alignment gate rows/cases/checksum/ready/manual-required: `2/10/10/2/2`", md)
            self.assertIn("Source visual confirmation packet rows/questions/cases/ready/recorded/unblocked: `2/6/10/2/0/0`", md)
            self.assertIn("source_reextract_path_ready", md)
            self.assertIn("fresh_refresh_required_before_parameter_activation", md)

    def test_rejects_mutation_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["parameter_mutation"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "parameter_mutation"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        project_stage_path = root / "project_stage.json"
        goal_path = root / "goal.json"
        launch_path = root / "launch.json"
        next_session_path = root / "next_session.json"
        rescue_ab_path = root / "rescue_ab.json"
        parameter_queue_path = root / "parameter_queue.json"
        activation_gate_path = root / "activation_gate.json"
        parameter_shadow_spec_path = root / "parameter_shadow_spec.json"
        decision_ladder_path = root / "decision_ladder.json"
        evidence_gap_matrix_path = root / "evidence_gap_matrix.json"
        source_recheck_path = root / "source_recheck.json"
        source_reextract_plan_path = root / "source_reextract_plan.json"
        source_reextract_review_path = root / "source_reextract_review.json"
        source_visual_alignment_gate_path = root / "source_visual_alignment_gate.json"
        source_visual_confirmation_packet_path = root / "source_visual_confirmation_packet.json"
        external_map_path = root / "external_map.json"
        broker_plan_path = root / "broker_plan.json"
        config_path = root / "config.json"

        project_stage_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "manual_m12_37_once": False,
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "challenge_progress_label": "10/10",
                        "ten_day_challenge_complete": True,
                        "approved_internal_sim_strategy_count": 2,
                        "approved_internal_sim_strategy_ids": ["M10-PA-004", "M10-PA-005"],
                        "launch_ready_strategy_count": 2,
                        "approved_runtime_input_connected_count": 3,
                        "approved_runtime_input_count": 3,
                        "can_run_next_internal_sim_session": True,
                        "rescue_runtime_strategy_count": 2,
                        "rescue_m13_ledger_observed_strategy_count": 1,
                        "rescue_no_m13_ledger_evidence_count": 1,
                        "rescue_promotion_allowed_count": 0,
                        "parameter_experiment_row_count": 4,
                        "parameter_experiment_allowed_now_count": 0,
                        "parameter_experiment_blocked_until_fresh_refresh_count": 3,
                        "parameter_activation_gate_row_count": 4,
                        "parameter_activation_shadow_review_candidate_count": 0,
                        "parameter_activation_waiting_for_fresh_refresh_count": 4,
                        "parameter_activation_implementation_mutation_allowed_count": 0,
                        "parameter_activation_parameter_mutation_allowed_count": 0,
                        "post_refresh_fresh_refresh_observed": False,
                        "post_refresh_waiting_count": 4,
                        "post_refresh_source_quote": "fallback_quotes_only",
                        "external_reference_project_count": 2,
                        "external_reference_mapped_rescue_row_count": 3,
                        "external_reference_broker_blocker_row_count": 1,
                        "broker_dry_run_ready_count": 1,
                        "broker_dry_run_blocked_count": 1,
                    },
                }
            ),
            encoding="utf-8",
        )
        goal_path.write_text(
            json.dumps(
                {
                    "project_stage_label": "M14 fixture stage",
                    "m14_trading_date": "2026-05-22",
                    "challenge": {
                        "ten_day_challenge_complete": True,
                        "challenge_progress_label": "10/10",
                    },
                    "internal_simulation_gate": {
                        "approved_internal_sim_strategy_count": 2,
                        "approved_internal_sim_strategy_ids": ["M10-PA-004", "M10-PA-005"],
                    },
                }
            ),
            encoding="utf-8",
        )
        launch_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "can_continue_internal_simulated_account": True,
                        "launch_ready_strategy_count": 2,
                    }
                }
            ),
            encoding="utf-8",
        )
        next_session_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "can_run_next_internal_sim_session": True,
                        "approved_runtime_input_connected_count": 3,
                        "approved_runtime_input_count": 3,
                        "manual_m12_37_once_allowed": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        rescue_ab_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "rescue_runtime_strategy_count": 2,
                        "m13_ledger_observed_strategy_count": 1,
                        "no_m13_ledger_evidence_count": 1,
                        "promotion_allowed_count": 0,
                        "evidence_ready_for_manual_review_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        parameter_queue_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "experiment_row_count": 4,
                        "allowed_now_count": 0,
                        "blocked_until_fresh_refresh_count": 3,
                        "m13_registry_mutation_count": 0,
                        "m12_account_specs_mutation_count": 0,
                        "broker_readiness_status_mutation_count": 0,
                    }
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
                        "waiting_for_fresh_refresh_count": 4,
                        "implementation_mutation_allowed_count": 0,
                        "parameter_mutation_allowed_count": 0,
                        "fresh_refresh_observed": False,
                        "source_quote": "fallback_quotes_only",
                        "manual_m12_37_once_allowed": False,
                        "m13_registry_mutation_count": 0,
                        "m12_account_specs_mutation_count": 0,
                        "broker_readiness_status_mutation_count": 0,
                    }
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
                        "implementation_mutation_allowed_count": 0,
                        "parameter_mutation_allowed_count": 0,
                        "broker_or_live_enabled": False,
                        "manual_m12_37_once_allowed": False,
                        "m13_registry_mutation_count": 0,
                        "m12_account_specs_mutation_count": 0,
                        "broker_readiness_status_mutation_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        decision_ladder_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "strategy_ladder_row_count": 6,
                        "approved_next_step_count": 2,
                        "rescue_continue_count": 3,
                        "final_discard_allowed_count": 0,
                        "promotion_candidate_count": 0,
                        "parameter_mutation_allowed_count": 0,
                        "broker_or_live_enabled": False,
                        "manual_m12_37_once_allowed": False,
                        "m13_registry_mutation_count": 0,
                        "m12_account_specs_mutation_count": 0,
                        "broker_readiness_status_mutation_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        evidence_gap_matrix_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "strategy_gap_row_count": 6,
                        "open_evidence_gap_row_count": 6,
                        "requires_m12_47_fresh_refresh_count": 4,
                        "wait_first_ledger_gap_count": 1,
                        "rescue_10_day_ab_gap_count": 3,
                        "shadow_review_gap_count": 2,
                        "final_discard_allowed_count": 0,
                        "promotion_candidate_count": 0,
                        "parameter_mutation_allowed_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        source_recheck_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_recheck_row_count": 3,
                        "source_visual_recheck_candidate_count": 1,
                        "research_only_risk_definition_hold_count": 1,
                        "supporting_rule_attach_to_parent_count": 1,
                        "external_reference_hold_count": 0,
                        "eligible_for_future_source_reextract_count": 1,
                        "standalone_strategy_creation_allowed_count": 0,
                        "recheck_can_close_gap_now_count": 0,
                        "recheck_can_promote_now_count": 0,
                        "recheck_can_discard_now_count": 0,
                        "parameter_mutation_allowed_now_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        source_reextract_plan_path.write_text(
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
        source_reextract_review_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_reextract_review_row_count": 2,
                        "candidate_strategy_count": 2,
                        "source_backed_atom_count": 10,
                        "source_review_answer_count": 6,
                        "future_spec_draftable_count": 2,
                        "visual_review_required_count": 2,
                        "can_create_strategy_now_count": 0,
                        "can_close_gap_now_count": 0,
                        "can_promote_now_count": 0,
                        "can_discard_now_count": 0,
                        "parameter_mutation_allowed_now_count": 0,
                    },
                    "plain_language_result": "Source reextract review fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        source_visual_alignment_gate_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_visual_alignment_gate_row_count": 2,
                        "candidate_strategy_count": 2,
                        "visual_case_count": 10,
                        "checksum_match_count": 10,
                        "ready_for_manual_visual_alignment_count": 2,
                        "manual_visual_confirmation_required_count": 2,
                        "future_spec_blocked_until_visual_confirmation_count": 2,
                        "current_worktree_asset_exists_count": 0,
                        "old_worktree_asset_exists_count": 10,
                        "missing_asset_count": 0,
                        "can_draft_future_source_reextract_spec_now_count": 0,
                        "can_create_strategy_now_count": 0,
                        "parameter_mutation_allowed_now_count": 0,
                    },
                    "plain_language_result": "Source visual alignment fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        source_visual_confirmation_packet_path.write_text(
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
        external_map_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "external_reference_project_count": 2,
                        "mapped_rescue_row_count": 3,
                        "broker_blocker_reference_row_count": 1,
                        "copy_trading_allowed": False,
                    }
                }
            ),
            encoding="utf-8",
        )
        broker_plan_path.write_text(
            json.dumps(
                {
                    "dry_run_ready_count": 1,
                    "blocked_count": 1,
                    "broker_connection_enabled": False,
                    "real_order_enabled": False,
                    "live_execution_enabled": False,
                    "paper_trading_approval": False,
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.objective-completion-audit.config.v1",
                    "stage": "M14.objective_completion_audit",
                    "project_stage_label": "fixture objective completion audit",
                    "inputs": {
                        "m14_project_stage_assessment": str(project_stage_path),
                        "m14_goal_readiness_report": str(goal_path),
                        "m14_internal_sim_launch_readiness": str(launch_path),
                        "m14_internal_sim_next_session_plan": str(next_session_path),
                        "m14_rescue_ab_evidence_tracker": str(rescue_ab_path),
                        "m14_rescue_parameter_experiment_queue": str(parameter_queue_path),
                        "m14_rescue_parameter_activation_gate": str(activation_gate_path),
                        "m14_rescue_parameter_shadow_spec": str(parameter_shadow_spec_path),
                        "m14_strategy_decision_ladder": str(decision_ladder_path),
                        "m14_strategy_evidence_gap_matrix": str(evidence_gap_matrix_path),
                        "m14_strategy_source_recheck_triage": str(source_recheck_path),
                        "m14_strategy_source_reextract_plan": str(source_reextract_plan_path),
                        "m14_strategy_source_reextract_review": str(source_reextract_review_path),
                        "m14_strategy_source_visual_alignment_gate": str(source_visual_alignment_gate_path),
                        "m14_strategy_source_visual_confirmation_packet": str(
                            source_visual_confirmation_packet_path
                        ),
                        "m14_rescue_external_reference_map": str(external_map_path),
                        "m14_2_broker_readiness_plan": str(broker_plan_path),
                    },
                    "outputs": {
                        "audit_json": str(root / "audit.json"),
                        "audit_md": str(root / "audit.md"),
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


if __name__ == "__main__":
    unittest.main()
