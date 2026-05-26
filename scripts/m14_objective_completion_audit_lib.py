#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_objective_completion_audit.json"


@dataclass(frozen=True, slots=True)
class ObjectiveCompletionAuditConfig:
    stage: str
    project_stage_label: str
    project_stage_assessment_path: Path
    goal_readiness_report_path: Path
    internal_sim_launch_readiness_path: Path
    internal_sim_next_session_plan_path: Path
    rescue_ab_evidence_tracker_path: Path
    rescue_parameter_experiment_queue_path: Path
    rescue_parameter_activation_gate_path: Path
    rescue_parameter_shadow_spec_path: Path
    strategy_decision_ladder_path: Path
    strategy_evidence_gap_matrix_path: Path
    strategy_source_recheck_triage_path: Path
    strategy_source_reextract_plan_path: Path
    strategy_source_reextract_review_path: Path
    strategy_source_visual_alignment_gate_path: Path
    rescue_external_reference_map_path: Path
    broker_readiness_plan_path: Path
    audit_json_path: Path
    audit_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> ObjectiveCompletionAuditConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = ObjectiveCompletionAuditConfig(
        stage=str(payload["stage"]),
        project_stage_label=str(payload["project_stage_label"]),
        project_stage_assessment_path=resolve_repo_path(inputs["m14_project_stage_assessment"]),
        goal_readiness_report_path=resolve_repo_path(inputs["m14_goal_readiness_report"]),
        internal_sim_launch_readiness_path=resolve_repo_path(inputs["m14_internal_sim_launch_readiness"]),
        internal_sim_next_session_plan_path=resolve_repo_path(inputs["m14_internal_sim_next_session_plan"]),
        rescue_ab_evidence_tracker_path=resolve_repo_path(inputs["m14_rescue_ab_evidence_tracker"]),
        rescue_parameter_experiment_queue_path=resolve_repo_path(
            inputs["m14_rescue_parameter_experiment_queue"]
        ),
        rescue_parameter_activation_gate_path=resolve_repo_path(
            inputs["m14_rescue_parameter_activation_gate"]
        ),
        rescue_parameter_shadow_spec_path=resolve_repo_path(inputs["m14_rescue_parameter_shadow_spec"]),
        strategy_decision_ladder_path=resolve_repo_path(inputs["m14_strategy_decision_ladder"]),
        strategy_evidence_gap_matrix_path=resolve_repo_path(inputs["m14_strategy_evidence_gap_matrix"]),
        strategy_source_recheck_triage_path=resolve_repo_path(
            inputs["m14_strategy_source_recheck_triage"]
        ),
        strategy_source_reextract_plan_path=resolve_repo_path(
            inputs["m14_strategy_source_reextract_plan"]
        ),
        strategy_source_reextract_review_path=resolve_repo_path(
            inputs["m14_strategy_source_reextract_review"]
        ),
        strategy_source_visual_alignment_gate_path=resolve_repo_path(
            inputs["m14_strategy_source_visual_alignment_gate"]
        ),
        rescue_external_reference_map_path=resolve_repo_path(inputs["m14_rescue_external_reference_map"]),
        broker_readiness_plan_path=resolve_repo_path(inputs["m14_2_broker_readiness_plan"]),
        audit_json_path=resolve_repo_path(outputs["audit_json"]),
        audit_md_path=resolve_repo_path(outputs["audit_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: ObjectiveCompletionAuditConfig) -> None:
    if config.stage != "M14.objective_completion_audit":
        raise ValueError("M14 objective completion audit stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 objective completion audit must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 objective completion audit must keep internal simulated accounts enabled")
    forbidden_true_keys = (
        "broker_connection",
        "real_order",
        "live_execution",
        "paper_trading_approval",
        "manual_m12_37_once",
        "m13_registry_mutation",
        "m12_account_specs_mutation",
        "broker_readiness_status_mutation",
        "parameter_mutation",
    )
    for key in forbidden_true_keys:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 objective completion audit cannot enable {key}")


def run_m14_objective_completion_audit(
    config: ObjectiveCompletionAuditConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    project_stage = read_json(config.project_stage_assessment_path)
    goal = read_json(config.goal_readiness_report_path)
    launch = read_json(config.internal_sim_launch_readiness_path)
    next_session = read_json(config.internal_sim_next_session_plan_path)
    rescue_ab = read_json(config.rescue_ab_evidence_tracker_path)
    parameter_queue = read_json(config.rescue_parameter_experiment_queue_path)
    activation_gate = read_json(config.rescue_parameter_activation_gate_path)
    parameter_shadow_spec = read_json(config.rescue_parameter_shadow_spec_path)
    decision_ladder = read_json(config.strategy_decision_ladder_path)
    evidence_gap_matrix = read_json(config.strategy_evidence_gap_matrix_path)
    source_recheck = read_json(config.strategy_source_recheck_triage_path)
    source_reextract_plan = read_json(config.strategy_source_reextract_plan_path)
    source_reextract_review = read_json(config.strategy_source_reextract_review_path)
    source_visual_alignment_gate = read_json(config.strategy_source_visual_alignment_gate_path)
    external_map = read_json(config.rescue_external_reference_map_path)
    broker_plan = read_json(config.broker_readiness_plan_path)

    summary = build_summary(
        project_stage=project_stage,
        goal=goal,
        launch=launch,
        next_session=next_session,
        rescue_ab=rescue_ab,
        parameter_queue=parameter_queue,
        activation_gate=activation_gate,
        parameter_shadow_spec=parameter_shadow_spec,
        decision_ladder=decision_ladder,
        evidence_gap_matrix=evidence_gap_matrix,
        source_recheck=source_recheck,
        source_reextract_plan=source_reextract_plan,
        source_reextract_review=source_reextract_review,
        source_visual_alignment_gate=source_visual_alignment_gate,
        external_map=external_map,
        broker_plan=broker_plan,
    )
    requirement_rows = build_requirement_rows(summary)
    state_counts = dict(sorted(Counter(row["state"] for row in requirement_rows).items()))
    summary.update(
        {
            "requirement_count": len(requirement_rows),
            "requirement_state_counts": state_counts,
            "proven_count": state_counts.get("proven", 0),
            "in_progress_count": state_counts.get("in_progress", 0),
            "blocked_count": state_counts.get("blocked", 0),
            "guardrail_count": state_counts.get("guardrail", 0),
        }
    )
    summary["objective_complete"] = False
    summary["objective_blockers"] = [
        row["requirement_id"]
        for row in requirement_rows
        if row["state"] in {"blocked", "in_progress"}
    ]

    payload: dict[str, Any] = {
        "schema_version": "m14.objective-completion-audit.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "project_stage_label": config.project_stage_label,
        "m14_trading_date": summary["m14_trading_date"],
        "input_refs": {
            "m14_project_stage_assessment": project_path(config.project_stage_assessment_path),
            "m14_goal_readiness_report": project_path(config.goal_readiness_report_path),
            "m14_internal_sim_launch_readiness": project_path(config.internal_sim_launch_readiness_path),
            "m14_internal_sim_next_session_plan": project_path(config.internal_sim_next_session_plan_path),
            "m14_rescue_ab_evidence_tracker": project_path(config.rescue_ab_evidence_tracker_path),
            "m14_rescue_parameter_experiment_queue": project_path(
                config.rescue_parameter_experiment_queue_path
            ),
            "m14_rescue_parameter_activation_gate": project_path(
                config.rescue_parameter_activation_gate_path
            ),
            "m14_rescue_parameter_shadow_spec": project_path(config.rescue_parameter_shadow_spec_path),
            "m14_strategy_decision_ladder": project_path(config.strategy_decision_ladder_path),
            "m14_strategy_evidence_gap_matrix": project_path(config.strategy_evidence_gap_matrix_path),
            "m14_strategy_source_recheck_triage": project_path(
                config.strategy_source_recheck_triage_path
            ),
            "m14_strategy_source_reextract_plan": project_path(
                config.strategy_source_reextract_plan_path
            ),
            "m14_strategy_source_reextract_review": project_path(
                config.strategy_source_reextract_review_path
            ),
            "m14_strategy_source_visual_alignment_gate": project_path(
                config.strategy_source_visual_alignment_gate_path
            ),
            "m14_rescue_external_reference_map": project_path(config.rescue_external_reference_map_path),
            "m14_2_broker_readiness_plan": project_path(config.broker_readiness_plan_path),
        },
        "summary": summary,
        "requirement_rows": requirement_rows,
        "objective_completion_assessment": {
            "objective_complete": False,
            "completion_state": "not_complete",
            "reason": (
                "Project stage, 10-day challenge, approved internal simulation, external-reference mapping, "
                "parameter shadow specs, strategy decision ladder, strategy evidence gap matrix, and guardrails "
                "are visible, but rescue promotion, fresh-refresh review, and parameter activation are still "
                "blocked or in progress."
            ),
            "blocked_or_in_progress_requirement_ids": summary["objective_blockers"],
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
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.audit_json_path, payload)
    config.audit_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.audit_md_path.write_text(build_audit_md(payload), encoding="utf-8")
    return payload


def build_summary(
    *,
    project_stage: dict[str, Any],
    goal: dict[str, Any],
    launch: dict[str, Any],
    next_session: dict[str, Any],
    rescue_ab: dict[str, Any],
    parameter_queue: dict[str, Any],
    activation_gate: dict[str, Any],
    parameter_shadow_spec: dict[str, Any],
    decision_ladder: dict[str, Any],
    evidence_gap_matrix: dict[str, Any],
    source_recheck: dict[str, Any],
    source_reextract_plan: dict[str, Any],
    source_reextract_review: dict[str, Any],
    source_visual_alignment_gate: dict[str, Any],
    external_map: dict[str, Any],
    broker_plan: dict[str, Any],
) -> dict[str, Any]:
    stage_summary = project_stage.get("summary", {})
    goal_challenge = goal.get("challenge", {})
    goal_internal = goal.get("internal_simulation_gate", {})
    launch_summary = launch.get("summary", {})
    next_summary = next_session.get("summary", {})
    rescue_summary = rescue_ab.get("summary", {})
    parameter_summary = parameter_queue.get("summary", {})
    activation_summary = activation_gate.get("summary", {})
    parameter_shadow_summary = parameter_shadow_spec.get("summary", {})
    decision_summary = decision_ladder.get("summary", {})
    evidence_gap_summary = evidence_gap_matrix.get("summary", {})
    source_recheck_summary = source_recheck.get("summary", {})
    source_reextract_summary = source_reextract_plan.get("summary", {})
    source_reextract_review_summary = source_reextract_review.get("summary", {})
    source_visual_alignment_summary = source_visual_alignment_gate.get("summary", {})
    external_summary = external_map.get("summary", {})
    parameter_shadow_mutation_allowed_count = int_or_zero(
        stage_summary.get(
            "parameter_shadow_spec_parameter_mutation_allowed_count",
            parameter_shadow_summary.get("parameter_mutation_allowed_count"),
        )
    )
    decision_parameter_mutation_allowed_count = int_or_zero(
        stage_summary.get(
            "strategy_decision_parameter_mutation_allowed_count",
            decision_summary.get("parameter_mutation_allowed_count"),
        )
    )
    return {
        "current_project_stage": str(
            stage_summary.get("current_project_stage") or goal.get("project_stage_label", "")
        ),
        "m14_trading_date": str(
            project_stage.get("m14_trading_date")
            or goal.get("m14_trading_date")
            or next_session.get("m14_trading_date", "")
        ),
        "ten_day_challenge_complete": bool(
            stage_summary.get("ten_day_challenge_complete", goal_challenge.get("ten_day_challenge_complete", False))
        ),
        "challenge_progress_label": str(
            stage_summary.get("challenge_progress_label") or goal_challenge.get("challenge_progress_label", "")
        ),
        "approved_internal_sim_strategy_count": int_or_zero(
            stage_summary.get(
                "approved_internal_sim_strategy_count",
                goal_internal.get("approved_internal_sim_strategy_count"),
            )
        ),
        "approved_internal_sim_strategy_ids": list(
            stage_summary.get(
                "approved_internal_sim_strategy_ids",
                goal_internal.get("approved_internal_sim_strategy_ids", []),
            )
        ),
        "launch_ready_strategy_count": int_or_zero(
            stage_summary.get("launch_ready_strategy_count", launch_summary.get("launch_ready_strategy_count"))
        ),
        "can_continue_internal_simulated_account": bool(
            launch_summary.get("can_continue_internal_simulated_account", False)
        ),
        "can_run_next_internal_sim_session": bool(
            stage_summary.get(
                "can_run_next_internal_sim_session",
                next_summary.get("can_run_next_internal_sim_session", False),
            )
        ),
        "approved_runtime_input_connected_count": int_or_zero(
            stage_summary.get(
                "approved_runtime_input_connected_count",
                next_summary.get("approved_runtime_input_connected_count"),
            )
        ),
        "approved_runtime_input_count": int_or_zero(
            stage_summary.get("approved_runtime_input_count", next_summary.get("approved_runtime_input_count"))
        ),
        "rescue_runtime_strategy_count": int_or_zero(
            stage_summary.get(
                "rescue_runtime_strategy_count",
                rescue_summary.get("rescue_runtime_strategy_count"),
            )
        ),
        "rescue_m13_ledger_observed_strategy_count": int_or_zero(
            stage_summary.get(
                "rescue_m13_ledger_observed_strategy_count",
                rescue_summary.get("m13_ledger_observed_strategy_count"),
            )
        ),
        "rescue_no_m13_ledger_evidence_count": int_or_zero(
            stage_summary.get(
                "rescue_no_m13_ledger_evidence_count",
                rescue_summary.get("no_m13_ledger_evidence_count"),
            )
        ),
        "rescue_promotion_allowed_count": int_or_zero(
            stage_summary.get(
                "rescue_promotion_allowed_count",
                rescue_summary.get("promotion_allowed_count"),
            )
        ),
        "rescue_evidence_ready_for_manual_review_count": int_or_zero(
            rescue_summary.get("evidence_ready_for_manual_review_count")
        ),
        "parameter_experiment_row_count": int_or_zero(
            stage_summary.get("parameter_experiment_row_count", parameter_summary.get("experiment_row_count"))
        ),
        "parameter_experiment_allowed_now_count": int_or_zero(
            stage_summary.get("parameter_experiment_allowed_now_count", parameter_summary.get("allowed_now_count"))
        ),
        "parameter_experiment_blocked_until_fresh_refresh_count": int_or_zero(
            stage_summary.get(
                "parameter_experiment_blocked_until_fresh_refresh_count",
                parameter_summary.get("blocked_until_fresh_refresh_count"),
            )
        ),
        "parameter_activation_gate_row_count": int_or_zero(
            stage_summary.get("parameter_activation_gate_row_count", activation_summary.get("gate_row_count"))
        ),
        "parameter_activation_shadow_review_candidate_count": int_or_zero(
            stage_summary.get(
                "parameter_activation_shadow_review_candidate_count",
                activation_summary.get("shadow_review_candidate_count"),
            )
        ),
        "parameter_activation_waiting_for_fresh_refresh_count": int_or_zero(
            stage_summary.get(
                "parameter_activation_waiting_for_fresh_refresh_count",
                activation_summary.get("waiting_for_fresh_refresh_count"),
            )
        ),
        "parameter_activation_implementation_mutation_allowed_count": int_or_zero(
            stage_summary.get(
                "parameter_activation_implementation_mutation_allowed_count",
                activation_summary.get("implementation_mutation_allowed_count"),
            )
        ),
        "parameter_activation_parameter_mutation_allowed_count": int_or_zero(
            stage_summary.get(
                "parameter_activation_parameter_mutation_allowed_count",
                activation_summary.get("parameter_mutation_allowed_count"),
            )
        ),
        "parameter_shadow_spec_row_count": int_or_zero(
            stage_summary.get("parameter_shadow_spec_row_count", parameter_shadow_summary.get("spec_row_count"))
        ),
        "parameter_shadow_spec_candidate_variant_count": int_or_zero(
            stage_summary.get(
                "parameter_shadow_spec_candidate_variant_count",
                parameter_shadow_summary.get("candidate_variant_count"),
            )
        ),
        "parameter_shadow_spec_waiting_for_fresh_refresh_count": int_or_zero(
            stage_summary.get(
                "parameter_shadow_spec_waiting_for_fresh_refresh_count",
                parameter_shadow_summary.get("waiting_for_fresh_refresh_count"),
            )
        ),
        "parameter_shadow_spec_implementation_mutation_allowed_count": int_or_zero(
            stage_summary.get(
                "parameter_shadow_spec_implementation_mutation_allowed_count",
                parameter_shadow_summary.get("implementation_mutation_allowed_count"),
            )
        ),
        "parameter_shadow_spec_parameter_mutation_allowed_count": parameter_shadow_mutation_allowed_count,
        "strategy_decision_ladder_row_count": int_or_zero(
            stage_summary.get("strategy_decision_ladder_row_count", decision_summary.get("strategy_ladder_row_count"))
        ),
        "strategy_decision_approved_next_step_count": int_or_zero(
            stage_summary.get(
                "strategy_decision_approved_next_step_count",
                decision_summary.get("approved_next_step_count"),
            )
        ),
        "strategy_decision_rescue_continue_count": int_or_zero(
            stage_summary.get("strategy_decision_rescue_continue_count", decision_summary.get("rescue_continue_count"))
        ),
        "strategy_decision_final_discard_allowed_count": int_or_zero(
            stage_summary.get(
                "strategy_decision_final_discard_allowed_count",
                decision_summary.get("final_discard_allowed_count"),
            )
        ),
        "strategy_decision_promotion_candidate_count": int_or_zero(
            stage_summary.get(
                "strategy_decision_promotion_candidate_count",
                decision_summary.get("promotion_candidate_count"),
            )
        ),
        "strategy_decision_parameter_mutation_allowed_count": decision_parameter_mutation_allowed_count,
        "strategy_evidence_gap_row_count": int_or_zero(
            stage_summary.get("strategy_evidence_gap_row_count", evidence_gap_summary.get("strategy_gap_row_count"))
        ),
        "strategy_evidence_open_gap_row_count": int_or_zero(
            stage_summary.get(
                "strategy_evidence_open_gap_row_count",
                evidence_gap_summary.get("open_evidence_gap_row_count"),
            )
        ),
        "strategy_evidence_requires_fresh_refresh_count": int_or_zero(
            stage_summary.get(
                "strategy_evidence_requires_fresh_refresh_count",
                evidence_gap_summary.get("requires_m12_47_fresh_refresh_count"),
            )
        ),
        "strategy_evidence_wait_first_ledger_gap_count": int_or_zero(
            stage_summary.get(
                "strategy_evidence_wait_first_ledger_gap_count",
                evidence_gap_summary.get("wait_first_ledger_gap_count"),
            )
        ),
        "strategy_evidence_rescue_10_day_ab_gap_count": int_or_zero(
            stage_summary.get(
                "strategy_evidence_rescue_10_day_ab_gap_count",
                evidence_gap_summary.get("rescue_10_day_ab_gap_count"),
            )
        ),
        "strategy_evidence_shadow_review_gap_count": int_or_zero(
            stage_summary.get(
                "strategy_evidence_shadow_review_gap_count",
                evidence_gap_summary.get("shadow_review_gap_count"),
            )
        ),
        "strategy_evidence_final_discard_allowed_count": int_or_zero(
            stage_summary.get(
                "strategy_evidence_final_discard_allowed_count",
                evidence_gap_summary.get("final_discard_allowed_count"),
            )
        ),
        "strategy_evidence_promotion_candidate_count": int_or_zero(
            stage_summary.get(
                "strategy_evidence_promotion_candidate_count",
                evidence_gap_summary.get("promotion_candidate_count"),
            )
        ),
        "strategy_evidence_parameter_mutation_allowed_count": int_or_zero(
            stage_summary.get(
                "strategy_evidence_parameter_mutation_allowed_count",
                evidence_gap_summary.get("parameter_mutation_allowed_count"),
            )
        ),
        "strategy_source_recheck_row_count": int_or_zero(
            stage_summary.get(
                "strategy_source_recheck_row_count",
                source_recheck_summary.get("source_recheck_row_count"),
            )
        ),
        "strategy_source_recheck_visual_candidate_count": int_or_zero(
            stage_summary.get(
                "strategy_source_recheck_visual_candidate_count",
                source_recheck_summary.get("source_visual_recheck_candidate_count"),
            )
        ),
        "strategy_source_recheck_research_hold_count": int_or_zero(
            stage_summary.get(
                "strategy_source_recheck_research_hold_count",
                source_recheck_summary.get("research_only_risk_definition_hold_count"),
            )
        ),
        "strategy_source_recheck_supporting_rule_count": int_or_zero(
            stage_summary.get(
                "strategy_source_recheck_supporting_rule_count",
                source_recheck_summary.get("supporting_rule_attach_to_parent_count"),
            )
        ),
        "strategy_source_recheck_external_hold_count": int_or_zero(
            stage_summary.get(
                "strategy_source_recheck_external_hold_count",
                source_recheck_summary.get("external_reference_hold_count"),
            )
        ),
        "strategy_source_recheck_future_reextract_candidate_count": int_or_zero(
            stage_summary.get(
                "strategy_source_recheck_future_reextract_candidate_count",
                source_recheck_summary.get("eligible_for_future_source_reextract_count"),
            )
        ),
        "strategy_source_recheck_can_create_strategy_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_recheck_can_create_strategy_now_count",
                source_recheck_summary.get("standalone_strategy_creation_allowed_count"),
            )
        ),
        "strategy_source_recheck_can_close_gap_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_recheck_can_close_gap_now_count",
                source_recheck_summary.get("recheck_can_close_gap_now_count"),
            )
        ),
        "strategy_source_recheck_can_promote_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_recheck_can_promote_now_count",
                source_recheck_summary.get("recheck_can_promote_now_count"),
            )
        ),
        "strategy_source_recheck_can_discard_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_recheck_can_discard_now_count",
                source_recheck_summary.get("recheck_can_discard_now_count"),
            )
        ),
        "strategy_source_recheck_parameter_mutation_allowed_count": int_or_zero(
            stage_summary.get(
                "strategy_source_recheck_parameter_mutation_allowed_count",
                source_recheck_summary.get("parameter_mutation_allowed_now_count"),
            )
        ),
        "strategy_source_reextract_plan_row_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_plan_row_count",
                source_reextract_summary.get("source_reextract_plan_row_count"),
            )
        ),
        "strategy_source_reextract_future_candidate_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_future_candidate_count",
                source_reextract_summary.get("future_source_reextract_candidate_count"),
            )
        ),
        "strategy_source_reextract_research_hold_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_research_hold_count",
                source_reextract_summary.get("research_only_hold_no_reextract_count"),
            )
        ),
        "strategy_source_reextract_supporting_only_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_supporting_only_count",
                source_reextract_summary.get("supporting_rule_no_standalone_reextract_count"),
            )
        ),
        "strategy_source_reextract_external_hold_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_external_hold_count",
                source_reextract_summary.get("external_reference_hold_count"),
            )
        ),
        "strategy_source_reextract_review_task_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_task_count",
                source_reextract_summary.get("source_ref_review_task_count"),
            )
        ),
        "strategy_source_reextract_review_question_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_question_count",
                source_reextract_summary.get("source_review_question_count"),
            )
        ),
        "strategy_source_reextract_can_draft_future_spec_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_can_draft_future_spec_count",
                source_reextract_summary.get("can_draft_future_source_reextract_spec_count"),
            )
        ),
        "strategy_source_reextract_can_create_strategy_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_can_create_strategy_now_count",
                source_reextract_summary.get("can_create_strategy_now_count"),
            )
        ),
        "strategy_source_reextract_can_close_gap_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_can_close_gap_now_count",
                source_reextract_summary.get("can_close_gap_now_count"),
            )
        ),
        "strategy_source_reextract_can_promote_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_can_promote_now_count",
                source_reextract_summary.get("can_promote_now_count"),
            )
        ),
        "strategy_source_reextract_can_discard_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_can_discard_now_count",
                source_reextract_summary.get("can_discard_now_count"),
            )
        ),
        "strategy_source_reextract_parameter_mutation_allowed_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_parameter_mutation_allowed_count",
                source_reextract_summary.get("parameter_mutation_allowed_now_count"),
            )
        ),
        "strategy_source_reextract_review_row_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_row_count",
                source_reextract_review_summary.get("source_reextract_review_row_count"),
            )
        ),
        "strategy_source_reextract_review_candidate_strategy_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_candidate_strategy_count",
                source_reextract_review_summary.get("candidate_strategy_count"),
            )
        ),
        "strategy_source_reextract_review_source_atom_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_source_atom_count",
                source_reextract_review_summary.get("source_backed_atom_count"),
            )
        ),
        "strategy_source_reextract_review_answer_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_answer_count",
                source_reextract_review_summary.get("source_review_answer_count"),
            )
        ),
        "strategy_source_reextract_review_visual_required_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_visual_required_count",
                source_reextract_review_summary.get("visual_review_required_count"),
            )
        ),
        "strategy_source_reextract_review_future_spec_draftable_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_future_spec_draftable_count",
                source_reextract_review_summary.get("future_spec_draftable_count"),
            )
        ),
        "strategy_source_reextract_review_can_create_strategy_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_can_create_strategy_now_count",
                source_reextract_review_summary.get("can_create_strategy_now_count"),
            )
        ),
        "strategy_source_reextract_review_can_close_gap_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_can_close_gap_now_count",
                source_reextract_review_summary.get("can_close_gap_now_count"),
            )
        ),
        "strategy_source_reextract_review_can_promote_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_can_promote_now_count",
                source_reextract_review_summary.get("can_promote_now_count"),
            )
        ),
        "strategy_source_reextract_review_can_discard_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_can_discard_now_count",
                source_reextract_review_summary.get("can_discard_now_count"),
            )
        ),
        "strategy_source_reextract_review_parameter_mutation_allowed_count": int_or_zero(
            stage_summary.get(
                "strategy_source_reextract_review_parameter_mutation_allowed_count",
                source_reextract_review_summary.get("parameter_mutation_allowed_now_count"),
            )
        ),
        "strategy_source_visual_alignment_gate_row_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_gate_row_count",
                source_visual_alignment_summary.get("source_visual_alignment_gate_row_count"),
            )
        ),
        "strategy_source_visual_alignment_candidate_strategy_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_candidate_strategy_count",
                source_visual_alignment_summary.get("candidate_strategy_count"),
            )
        ),
        "strategy_source_visual_alignment_case_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_case_count",
                source_visual_alignment_summary.get("visual_case_count"),
            )
        ),
        "strategy_source_visual_alignment_checksum_match_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_checksum_match_count",
                source_visual_alignment_summary.get("checksum_match_count"),
            )
        ),
        "strategy_source_visual_alignment_ready_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_ready_count",
                source_visual_alignment_summary.get("ready_for_manual_visual_alignment_count"),
            )
        ),
        "strategy_source_visual_alignment_manual_confirmation_required_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_manual_confirmation_required_count",
                source_visual_alignment_summary.get("manual_visual_confirmation_required_count"),
            )
        ),
        "strategy_source_visual_alignment_future_spec_blocked_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_future_spec_blocked_count",
                source_visual_alignment_summary.get("future_spec_blocked_until_visual_confirmation_count"),
            )
        ),
        "strategy_source_visual_alignment_current_asset_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_current_asset_count",
                source_visual_alignment_summary.get("current_worktree_asset_exists_count"),
            )
        ),
        "strategy_source_visual_alignment_old_asset_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_old_asset_count",
                source_visual_alignment_summary.get("old_worktree_asset_exists_count"),
            )
        ),
        "strategy_source_visual_alignment_missing_asset_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_missing_asset_count",
                source_visual_alignment_summary.get("missing_asset_count"),
            )
        ),
        "strategy_source_visual_alignment_can_draft_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_can_draft_now_count",
                source_visual_alignment_summary.get("can_draft_future_source_reextract_spec_now_count"),
            )
        ),
        "strategy_source_visual_alignment_can_create_strategy_now_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_can_create_strategy_now_count",
                source_visual_alignment_summary.get("can_create_strategy_now_count"),
            )
        ),
        "strategy_source_visual_alignment_parameter_mutation_allowed_count": int_or_zero(
            stage_summary.get(
                "strategy_source_visual_alignment_parameter_mutation_allowed_count",
                source_visual_alignment_summary.get("parameter_mutation_allowed_now_count"),
            )
        ),
        "fresh_refresh_observed": bool(
            activation_summary.get(
                "fresh_refresh_observed",
                stage_summary.get("post_refresh_fresh_refresh_observed", False),
            )
        ),
        "post_refresh_waiting_count": int_or_zero(
            stage_summary.get(
                "post_refresh_waiting_count",
                activation_summary.get("waiting_for_fresh_refresh_count"),
            )
        ),
        "source_quote": str(
            activation_summary.get("source_quote") or stage_summary.get("post_refresh_source_quote", "")
        ),
        "external_reference_project_count": int_or_zero(
            stage_summary.get(
                "external_reference_project_count",
                external_summary.get("external_reference_project_count"),
            )
        ),
        "external_reference_mapped_rescue_row_count": int_or_zero(
            stage_summary.get(
                "external_reference_mapped_rescue_row_count",
                external_summary.get("mapped_rescue_row_count"),
            )
        ),
        "external_reference_broker_blocker_row_count": int_or_zero(
            stage_summary.get(
                "external_reference_broker_blocker_row_count",
                external_summary.get("broker_blocker_reference_row_count"),
            )
        ),
        "external_reference_copy_trading_allowed": bool(
            external_summary.get("copy_trading_allowed", False)
        ),
        "broker_dry_run_ready_count": int_or_zero(
            stage_summary.get("broker_dry_run_ready_count", broker_plan.get("dry_run_ready_count"))
        ),
        "broker_dry_run_blocked_count": int_or_zero(
            stage_summary.get("broker_dry_run_blocked_count", broker_plan.get("blocked_count"))
        ),
        "broker_or_live_enabled": any(
            bool(value)
            for value in (
                project_stage.get("broker_connection"),
                project_stage.get("real_order"),
                project_stage.get("live_execution"),
                project_stage.get("paper_trading_approval"),
                broker_plan.get("broker_connection_enabled"),
                broker_plan.get("real_order_enabled"),
                broker_plan.get("live_execution_enabled"),
                broker_plan.get("paper_trading_approval"),
                parameter_shadow_summary.get("broker_or_live_enabled"),
                decision_summary.get("broker_or_live_enabled"),
            )
        ),
        "manual_m12_37_once_allowed": bool(
            project_stage.get("manual_m12_37_once")
            or stage_summary.get("manual_m12_37_once_allowed")
            or activation_summary.get("manual_m12_37_once_allowed")
            or next_summary.get("manual_m12_37_once_allowed")
            or parameter_shadow_summary.get("manual_m12_37_once_allowed")
            or decision_summary.get("manual_m12_37_once_allowed")
        ),
        "m13_registry_mutation_count": int_or_zero(
            activation_summary.get("m13_registry_mutation_count")
            or parameter_summary.get("m13_registry_mutation_count")
            or parameter_shadow_summary.get("m13_registry_mutation_count")
            or decision_summary.get("m13_registry_mutation_count")
        ),
        "m12_account_specs_mutation_count": int_or_zero(
            activation_summary.get("m12_account_specs_mutation_count")
            or parameter_summary.get("m12_account_specs_mutation_count")
            or parameter_shadow_summary.get("m12_account_specs_mutation_count")
            or decision_summary.get("m12_account_specs_mutation_count")
        ),
        "broker_readiness_status_mutation_count": int_or_zero(
            activation_summary.get("broker_readiness_status_mutation_count")
            or parameter_summary.get("broker_readiness_status_mutation_count")
            or parameter_shadow_summary.get("broker_readiness_status_mutation_count")
            or decision_summary.get("broker_readiness_status_mutation_count")
        ),
        "parameter_mutation_allowed_count": int_or_zero(
            activation_summary.get("parameter_mutation_allowed_count")
        )
        + parameter_shadow_mutation_allowed_count
        + decision_parameter_mutation_allowed_count,
    }


def build_requirement_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        requirement_row(
            "project_stage_identified",
            "Full project stage is identified from current M14 artifacts.",
            "proven" if summary["current_project_stage"] else "blocked",
            f"Current stage: {summary['current_project_stage']}.",
            "",
            "Keep regenerating stage assessment from current artifacts after each material M14 update.",
            ["m14_project_stage_assessment", "m14_goal_readiness_report"],
        ),
        requirement_row(
            "ten_day_challenge_complete",
            "10-day challenge gate is complete.",
            "proven" if summary["ten_day_challenge_complete"] else "blocked",
            f"Challenge progress is {summary['challenge_progress_label']}.",
            "" if summary["ten_day_challenge_complete"] else "Challenge gate is not complete.",
            "Do not advance strategy state until the challenge gate is complete.",
            ["m14_goal_readiness_report"],
        ),
        requirement_row(
            "approved_strategies_can_continue_internal_sim",
            "Approved strategies can continue internal simulated-account testing.",
            "proven"
            if summary["approved_internal_sim_strategy_count"] > 0
            and summary["can_run_next_internal_sim_session"]
            else "blocked",
            (
                f"{summary['approved_internal_sim_strategy_count']} approved strategies "
                f"({', '.join(summary['approved_internal_sim_strategy_ids'])}) and "
                f"{summary['approved_runtime_input_connected_count']}/{summary['approved_runtime_input_count']} "
                "approved runtimes connected."
            ),
            "" if summary["can_run_next_internal_sim_session"] else "Next internal sim session is not ready.",
            "Run only through the M12.47-supervised internal simulated-account flow.",
            ["m14_internal_sim_launch_readiness", "m14_internal_sim_next_session_plan"],
        ),
        requirement_row(
            "real_simulated_account_test_not_broker_live",
            "User-facing simulated-account progression is interpreted as internal simulation only.",
            "guardrail",
            (
                "Internal simulated account is enabled while broker connection, broker paper, live execution, "
                "and real orders remain disabled."
            ),
            "Broker paper/live still requires explicit future approval.",
            "Keep broker readiness in dry-run preview only.",
            ["m14_internal_sim_next_session_plan", "m14_2_broker_readiness_plan"],
        ),
        requirement_row(
            "weak_strategies_rescue_not_discarded",
            "Weak strategies have rescue or rebuild routes before any final discard.",
            "in_progress" if summary["rescue_runtime_strategy_count"] > 0 else "blocked",
            (
                f"{summary['rescue_runtime_strategy_count']} rescue runtimes exist; "
                f"{summary['rescue_m13_ledger_observed_strategy_count']} have M13 ledger evidence; "
                f"decision ladder keeps {summary['strategy_decision_rescue_continue_count']} strategies "
                f"in rescue/continuation and final-discard allowed remains "
                f"{summary['strategy_decision_final_discard_allowed_count']}; "
                f"evidence gap matrix has {summary['strategy_evidence_open_gap_row_count']} open rows, "
                f"{summary['strategy_evidence_rescue_10_day_ab_gap_count']} rescue 10-day A/B gaps, and "
                f"{summary['strategy_evidence_wait_first_ledger_gap_count']} first-ledger gaps."
            ),
            "" if summary["rescue_runtime_strategy_count"] > 0 else "No rescue runtime coverage is visible.",
            "Continue rescue A/B collection, zero-signal diagnostics, and detector rebuild work before discarding.",
            [
                "m14_rescue_ab_evidence_tracker",
                "m14_strategy_decision_ladder",
                "m14_strategy_evidence_gap_matrix",
                "m14_project_stage_assessment",
            ],
        ),
        requirement_row(
            "rescue_evidence_sufficient_for_promotion",
            "Rescue variants have enough evidence for promotion or final decision.",
            "proven" if summary["rescue_promotion_allowed_count"] > 0 else "blocked",
            (
                f"Promotion allowed: {summary['rescue_promotion_allowed_count']}; "
                f"manual-review ready: {summary['rescue_evidence_ready_for_manual_review_count']}; "
                f"no-ledger rows: {summary['rescue_no_m13_ledger_evidence_count']}."
            ),
            "Rescue runtimes still need their own 10 trading-day A/B evidence.",
            "Wait for rescue-specific M13 ledgers and complete the 10-day rescue A/B window.",
            ["m14_rescue_ab_evidence_tracker"],
        ),
        requirement_row(
            "parameter_optimization_path_ready",
            "Parameter optimization has a queued review path without mutating strategy state.",
            "in_progress" if summary["parameter_experiment_row_count"] > 0 else "blocked",
            (
                f"Parameter queue has {summary['parameter_experiment_row_count']} rows; "
                f"shadow specs cover {summary['parameter_shadow_spec_row_count']} rows and "
                f"{summary['parameter_shadow_spec_candidate_variant_count']} candidate variants; "
                f"allowed-now changes {summary['parameter_experiment_allowed_now_count']}; "
                f"activation shadow-review candidates {summary['parameter_activation_shadow_review_candidate_count']}; "
                f"evidence gap matrix shows {summary['strategy_evidence_shadow_review_gap_count']} shadow-review gaps; "
                f"parameter mutations allowed {summary['parameter_mutation_allowed_count']}."
            ),
            "" if summary["parameter_experiment_row_count"] > 0 else "No parameter queue is visible.",
            "Use queued shadow review families only after fresh evidence appears.",
            [
                "m14_rescue_parameter_experiment_queue",
                "m14_rescue_parameter_activation_gate",
                "m14_rescue_parameter_shadow_spec",
                "m14_strategy_evidence_gap_matrix",
            ],
        ),
        requirement_row(
            "source_reextract_path_ready",
            "Original-source recheck and future source-reextract candidates are tracked before creating new strategies.",
            "in_progress"
            if summary["strategy_source_recheck_row_count"] > 0
            and summary["strategy_source_reextract_plan_row_count"] > 0
            and summary["strategy_source_reextract_review_row_count"] > 0
            and summary["strategy_source_visual_alignment_gate_row_count"] > 0
            else "blocked",
            (
                f"Source recheck triage has {summary['strategy_source_recheck_row_count']} artifact-only rows, "
                f"{summary['strategy_source_recheck_visual_candidate_count']} source/visual candidates, "
                f"{summary['strategy_source_recheck_future_reextract_candidate_count']} future source-reextract candidates, "
                f"{summary['strategy_source_recheck_research_hold_count']} research-only holds, "
                f"{summary['strategy_source_recheck_supporting_rule_count']} supporting-only rows, and "
                f"{summary['strategy_source_recheck_external_hold_count']} external-reference holds; "
                f"source reextract plan has {summary['strategy_source_reextract_plan_row_count']} rows, "
                f"{summary['strategy_source_reextract_future_candidate_count']} future candidates, "
                f"{summary['strategy_source_reextract_review_task_count']} review tasks, and "
                f"{summary['strategy_source_reextract_review_question_count']} review questions; "
                f"source reextract review has {summary['strategy_source_reextract_review_row_count']} packets, "
                f"{summary['strategy_source_reextract_review_source_atom_count']} source-backed atoms, "
                f"{summary['strategy_source_reextract_review_answer_count']} source-review answers, "
                f"{summary['strategy_source_reextract_review_future_spec_draftable_count']} draftable future specs, and "
                f"{summary['strategy_source_reextract_review_visual_required_count']} visual-review-required rows; "
                f"source visual alignment gate has {summary['strategy_source_visual_alignment_gate_row_count']} rows, "
                f"{summary['strategy_source_visual_alignment_case_count']} visual cases, "
                f"{summary['strategy_source_visual_alignment_checksum_match_count']} checksum matches, "
                f"{summary['strategy_source_visual_alignment_ready_count']} ready-for-manual-alignment rows, and "
                f"{summary['strategy_source_visual_alignment_manual_confirmation_required_count']} manual-confirmation-required rows; "
                f"create/close/promote/discard/mutation allowed now is "
                f"{summary['strategy_source_visual_alignment_can_create_strategy_now_count']}/"
                f"{summary['strategy_source_reextract_review_can_close_gap_now_count']}/"
                f"{summary['strategy_source_reextract_review_can_promote_now_count']}/"
                f"{summary['strategy_source_reextract_review_can_discard_now_count']}/"
                f"{summary['strategy_source_visual_alignment_parameter_mutation_allowed_count']}."
            ),
            ""
            if summary["strategy_source_recheck_row_count"] > 0
            and summary["strategy_source_reextract_plan_row_count"] > 0
            and summary["strategy_source_reextract_review_row_count"] > 0
            and summary["strategy_source_visual_alignment_gate_row_count"] > 0
            else "Source recheck triage, source reextract plan, source reextract review, or source visual alignment gate artifact is missing.",
            "Use this queue to review original source refs and visual packs; do not create, promote, discard, or mutate a strategy from source review alone.",
            [
                "m14_strategy_source_recheck_triage",
                "m14_strategy_source_reextract_plan",
                "m14_strategy_source_reextract_review",
                "m14_strategy_source_visual_alignment_gate",
            ],
        ),
        requirement_row(
            "fresh_refresh_required_before_parameter_activation",
            "Fresh M12.47-owned refresh is required before parameter activation.",
            "proven" if summary["fresh_refresh_observed"] and summary["post_refresh_waiting_count"] == 0 else "blocked",
            (
                f"fresh_refresh_observed={summary['fresh_refresh_observed']}; "
                f"waiting rows={summary['post_refresh_waiting_count']}; "
                f"quote_source={summary['source_quote']}."
            ),
            "Current evidence still waits for a fresh supervisor-owned refresh.",
            "Wait for the next M12.47-owned trading-window refresh; do not run M12.37 once-mode manually.",
            ["m14_rescue_parameter_activation_gate", "m14_project_stage_assessment"],
        ),
        requirement_row(
            "external_project_reference_mapped",
            "External project references are mapped as architecture inspiration only.",
            "proven"
            if summary["external_reference_project_count"] > 0
            and not summary["external_reference_copy_trading_allowed"]
            else "blocked",
            (
                f"{summary['external_reference_project_count']} external projects mapped to "
                f"{summary['external_reference_mapped_rescue_row_count']} rescue rows and "
                f"{summary['external_reference_broker_blocker_row_count']} broker-blocker rows."
            ),
            "" if not summary["external_reference_copy_trading_allowed"] else "Copy-trading was allowed unexpectedly.",
            "Keep references as local architecture/review inspiration only.",
            ["m14_rescue_external_reference_map"],
        ),
        requirement_row(
            "broker_live_real_order_disabled",
            "Broker connection, broker paper, live execution, and real orders stay disabled.",
            "guardrail" if not summary["broker_or_live_enabled"] else "blocked",
            (
                f"Broker dry-run ready/blocked rows: "
                f"{summary['broker_dry_run_ready_count']}/{summary['broker_dry_run_blocked_count']}; "
                f"broker_or_live_enabled={summary['broker_or_live_enabled']}."
            ),
            "" if not summary["broker_or_live_enabled"] else "Broker/live boundary was enabled.",
            "Require explicit user approval before any broker paper/live path.",
            ["m14_2_broker_readiness_plan", "m14_project_stage_assessment"],
        ),
        requirement_row(
            "manual_m12_37_once_disabled",
            "Manual M12.37 once-mode remains disabled.",
            "guardrail" if not summary["manual_m12_37_once_allowed"] else "blocked",
            f"manual_m12_37_once_allowed={summary['manual_m12_37_once_allowed']}.",
            "" if not summary["manual_m12_37_once_allowed"] else "Manual M12.37 once-mode was allowed.",
            "Only M12.47 may launch M12.37 during its supervised trading window.",
            ["m14_internal_sim_next_session_plan", "m14_rescue_parameter_activation_gate"],
        ),
        requirement_row(
            "objective_complete",
            "The full user objective is complete end to end.",
            "blocked",
            (
                "Stage and approved internal simulation are ready, but rescue promotion, fresh-refresh review, "
                "and parameter activation are not complete; strategy ladder still allows "
                f"{summary['strategy_decision_final_discard_allowed_count']} final discards and "
                f"{summary['strategy_decision_promotion_candidate_count']} promotion candidates; "
                f"evidence gap matrix still has {summary['strategy_evidence_open_gap_row_count']} open rows."
            ),
            "Objective is not complete while rescue promotion is 0, fresh refresh is absent, parameter activation candidates are 0, and evidence gaps remain open.",
            "Continue internal simulation and rescue evidence collection under read-only/simulated guardrails.",
            ["m14_objective_completion_audit", "m14_strategy_evidence_gap_matrix"],
        ),
    ]


def requirement_row(
    requirement_id: str,
    label: str,
    state: str,
    evidence: str,
    blocker: str,
    next_action: str,
    source_refs: list[str],
) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "label": label,
        "state": state,
        "evidence": evidence,
        "blocker": blocker,
        "next_action": next_action,
        "source_refs": source_refs,
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
    }


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    approved = ", ".join(summary["approved_internal_sim_strategy_ids"])
    return (
        f"Objective audit is not complete yet. Proven: project is at {summary['current_project_stage']}, "
        f"the 10-day challenge is {summary['challenge_progress_label']}, and approved internal simulated-account "
        f"strategies can continue: {approved}. In progress: {summary['rescue_runtime_strategy_count']} rescue "
        f"runtimes, {summary['parameter_experiment_row_count']} parameter experiment rows, "
        f"{summary['parameter_shadow_spec_candidate_variant_count']} parameter shadow variants, and "
        f"{summary['strategy_decision_rescue_continue_count']} rescue-continuation ladder rows. "
        f"Source recheck triage tracks {summary['strategy_source_recheck_row_count']} artifact-only rows, "
        f"including {summary['strategy_source_recheck_future_reextract_candidate_count']} future source-reextract candidates; "
        f"the source reextract plan now carries {summary['strategy_source_reextract_plan_row_count']} rows, "
        f"{summary['strategy_source_reextract_future_candidate_count']} future candidates, and "
        f"{summary['strategy_source_reextract_review_task_count']} source-review tasks; "
        f"the source reextract review now carries {summary['strategy_source_reextract_review_row_count']} packets, "
        f"{summary['strategy_source_reextract_review_source_atom_count']} source-backed atoms, and "
        f"{summary['strategy_source_reextract_review_future_spec_draftable_count']} draftable future specs after visual alignment; "
        f"the visual alignment gate has {summary['strategy_source_visual_alignment_gate_row_count']} rows, "
        f"{summary['strategy_source_visual_alignment_case_count']} visual cases, and "
        f"{summary['strategy_source_visual_alignment_ready_count']} rows ready for manual visual alignment, "
        f"but {summary['strategy_source_visual_alignment_manual_confirmation_required_count']} still require manual visual confirmation. "
        f"Evidence gap matrix still has {summary['strategy_evidence_open_gap_row_count']} open rows, "
        f"including {summary['strategy_evidence_requires_fresh_refresh_count']} fresh-refresh waits, "
        f"{summary['strategy_evidence_wait_first_ledger_gap_count']} first-ledger gaps, and "
        f"{summary['strategy_evidence_rescue_10_day_ab_gap_count']} rescue 10-day A/B gaps. Blocked: rescue "
        f"promotion remains {summary['rescue_promotion_allowed_count']}, fresh refresh observed is "
        f"{summary['fresh_refresh_observed']} with {summary['post_refresh_waiting_count']} waiting rows, and "
        f"parameter activation has {summary['parameter_activation_shadow_review_candidate_count']} shadow-review "
        f"candidates. Final-discard allowed is {summary['strategy_decision_final_discard_allowed_count']}. "
        "Broker/live, real orders, paper approval, parameter mutation, registry/account-spec mutation, "
        "and manual M12.37 once-mode remain disabled."
    )


def build_audit_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Objective Completion Audit",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Objective complete: `{summary['objective_complete']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Approved internal sim strategies: `{', '.join(summary['approved_internal_sim_strategy_ids'])}`",
        f"- Rescue evidence observed: `{summary['rescue_m13_ledger_observed_strategy_count']}/{summary['rescue_runtime_strategy_count']}`",
        f"- Rescue promotions allowed: `{summary['rescue_promotion_allowed_count']}`",
        f"- Parameter shadow specs/variants: `{summary['parameter_shadow_spec_row_count']}/{summary['parameter_shadow_spec_candidate_variant_count']}`",
        f"- Strategy ladder rescue/final discard: `{summary['strategy_decision_rescue_continue_count']}/{summary['strategy_decision_final_discard_allowed_count']}`",
        f"- Strategy evidence gaps open/fresh/first-ledger/10-day/shadow: `{summary['strategy_evidence_open_gap_row_count']}/{summary['strategy_evidence_requires_fresh_refresh_count']}/{summary['strategy_evidence_wait_first_ledger_gap_count']}/{summary['strategy_evidence_rescue_10_day_ab_gap_count']}/{summary['strategy_evidence_shadow_review_gap_count']}`",
        f"- Source recheck rows/future-reextract: `{summary['strategy_source_recheck_row_count']}/{summary['strategy_source_recheck_future_reextract_candidate_count']}`",
        f"- Source reextract plan rows/future/tasks/questions: `{summary['strategy_source_reextract_plan_row_count']}/{summary['strategy_source_reextract_future_candidate_count']}/{summary['strategy_source_reextract_review_task_count']}/{summary['strategy_source_reextract_review_question_count']}`",
        f"- Source reextract review packets/atoms/answers/draftable/visual-required: `{summary['strategy_source_reextract_review_row_count']}/{summary['strategy_source_reextract_review_source_atom_count']}/{summary['strategy_source_reextract_review_answer_count']}/{summary['strategy_source_reextract_review_future_spec_draftable_count']}/{summary['strategy_source_reextract_review_visual_required_count']}`",
        f"- Source visual alignment gate rows/cases/checksum/ready/manual-required: `{summary['strategy_source_visual_alignment_gate_row_count']}/{summary['strategy_source_visual_alignment_case_count']}/{summary['strategy_source_visual_alignment_checksum_match_count']}/{summary['strategy_source_visual_alignment_ready_count']}/{summary['strategy_source_visual_alignment_manual_confirmation_required_count']}`",
        f"- Source visual alignment draft/create/mutation allowed: `{summary['strategy_source_visual_alignment_can_draft_now_count']}/{summary['strategy_source_visual_alignment_can_create_strategy_now_count']}/{summary['strategy_source_visual_alignment_parameter_mutation_allowed_count']}`",
        f"- Fresh refresh observed: `{summary['fresh_refresh_observed']}`",
        f"- Post-refresh waiting rows: `{summary['post_refresh_waiting_count']}`",
        f"- Parameter activation candidates: `{summary['parameter_activation_shadow_review_candidate_count']}`",
        f"- Requirement states: `{summary['requirement_state_counts']}`",
        "- Boundary: internal simulated accounts only; no broker connection, no real orders, no live execution.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Requirements",
        "",
    ]
    for row in payload["requirement_rows"]:
        lines.extend(
            [
                f"### {row['requirement_id']}",
                "",
                f"- State: `{row['state']}`",
                f"- Evidence: {row['evidence']}",
                f"- Blocker: {row['blocker'] or 'None'}",
                f"- Next action: {row['next_action']}",
                "",
            ]
        )
    return "\n".join(lines)


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
