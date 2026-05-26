#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_project_stage_assessment.json"


@dataclass(frozen=True, slots=True)
class ProjectStageAssessmentConfig:
    stage: str
    project_stage_label: str
    goal_readiness_report_path: Path
    internal_sim_next_session_plan_path: Path
    strategy_rescue_plan_path: Path
    rescue_optimization_backlog_path: Path
    rescue_post_refresh_outcome_review_path: Path
    rescue_external_reference_map_path: Path
    rescue_parameter_experiment_queue_path: Path
    rescue_parameter_activation_gate_path: Path
    objective_completion_audit_path: Path
    assessment_json_path: Path
    assessment_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> ProjectStageAssessmentConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = ProjectStageAssessmentConfig(
        stage=str(payload["stage"]),
        project_stage_label=str(payload["project_stage_label"]),
        goal_readiness_report_path=resolve_repo_path(inputs["m14_goal_readiness_report"]),
        internal_sim_next_session_plan_path=resolve_repo_path(inputs["m14_internal_sim_next_session_plan"]),
        strategy_rescue_plan_path=resolve_repo_path(inputs["m14_strategy_rescue_plan"]),
        rescue_optimization_backlog_path=resolve_repo_path(inputs["m14_rescue_optimization_backlog"]),
        rescue_post_refresh_outcome_review_path=resolve_repo_path(
            inputs["m14_rescue_post_refresh_outcome_review"]
        ),
        rescue_external_reference_map_path=resolve_repo_path(inputs["m14_rescue_external_reference_map"]),
        rescue_parameter_experiment_queue_path=resolve_repo_path(
            inputs["m14_rescue_parameter_experiment_queue"]
        ),
        rescue_parameter_activation_gate_path=resolve_repo_path(
            inputs["m14_rescue_parameter_activation_gate"]
        ),
        objective_completion_audit_path=resolve_repo_path(inputs["m14_objective_completion_audit"]),
        assessment_json_path=resolve_repo_path(outputs["assessment_json"]),
        assessment_md_path=resolve_repo_path(outputs["assessment_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: ProjectStageAssessmentConfig) -> None:
    if config.stage != "M14.project_stage_assessment":
        raise ValueError("M14 project stage assessment stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 project stage assessment must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 project stage assessment must keep internal simulated accounts enabled")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval", "manual_m12_37_once"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 project stage assessment cannot enable {key}")


def run_m14_project_stage_assessment(
    config: ProjectStageAssessmentConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    goal = read_json(config.goal_readiness_report_path)
    next_session = read_json(config.internal_sim_next_session_plan_path)
    rescue_plan = read_json(config.strategy_rescue_plan_path)
    backlog = read_json(config.rescue_optimization_backlog_path)
    post_refresh = read_json(config.rescue_post_refresh_outcome_review_path)
    external_map = read_json(config.rescue_external_reference_map_path)
    parameter_queue = read_json(config.rescue_parameter_experiment_queue_path)
    activation_gate = read_json(config.rescue_parameter_activation_gate_path)
    objective_audit = read_json(config.objective_completion_audit_path)

    strategy_routes = build_strategy_routes(
        action_matrix=list(goal.get("strategy_action_matrix", [])),
        next_session_rows=list(next_session.get("strategy_session_rows", [])),
        rescue_plan_rows=list(rescue_plan.get("rows", [])),
    )
    summary = build_summary(
        goal,
        next_session,
        backlog,
        post_refresh,
        external_map,
        parameter_queue,
        activation_gate,
        objective_audit,
        strategy_routes,
    )
    payload: dict[str, Any] = {
        "schema_version": "m14.project-stage-assessment.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "project_stage_label": config.project_stage_label,
        "source_project_stage_label": str(goal.get("project_stage_label", "")),
        "m14_trading_date": str(goal.get("m14_trading_date") or next_session.get("m14_trading_date", "")),
        "input_refs": {
            "m14_goal_readiness_report": project_path(config.goal_readiness_report_path),
            "m14_internal_sim_next_session_plan": project_path(config.internal_sim_next_session_plan_path),
            "m14_strategy_rescue_plan": project_path(config.strategy_rescue_plan_path),
            "m14_rescue_optimization_backlog": project_path(config.rescue_optimization_backlog_path),
            "m14_rescue_post_refresh_outcome_review": project_path(
                config.rescue_post_refresh_outcome_review_path
            ),
            "m14_rescue_external_reference_map": project_path(config.rescue_external_reference_map_path),
            "m14_rescue_parameter_experiment_queue": project_path(
                config.rescue_parameter_experiment_queue_path
            ),
            "m14_rescue_parameter_activation_gate": project_path(
                config.rescue_parameter_activation_gate_path
            ),
            "m14_objective_completion_audit": project_path(config.objective_completion_audit_path),
        },
        "summary": summary,
        "stage_assessment": build_stage_assessment(
            goal,
            next_session,
            backlog,
            post_refresh,
            external_map,
            parameter_queue,
            activation_gate,
            objective_audit,
            summary,
        ),
        "strategy_routes": strategy_routes,
        "next_fresh_refresh_acceptance": build_next_fresh_refresh_acceptance(next_session, goal),
        "rescue_policy": build_rescue_policy(goal, backlog),
        "rescue_post_refresh_outcome_review": build_post_refresh_outcome_review(post_refresh),
        "rescue_external_reference_map": build_external_reference_map(external_map),
        "rescue_parameter_experiment_queue": build_parameter_experiment_queue(parameter_queue),
        "rescue_parameter_activation_gate": build_parameter_activation_gate(activation_gate),
        "objective_completion_audit": build_objective_completion_audit(objective_audit),
        "external_reference_policy": dict(goal.get("external_reference_policy", {})),
        "goal_completion_assessment": {
            "goal_complete": False,
            "reason": (
                "The 10-day challenge is complete and approved strategies can continue internal simulation, "
                "but the objective audit remains not complete because rescue promotion, fresh-refresh review, "
                "and parameter activation are still blocked or in progress."
            ),
        },
        "hard_boundaries": {
            "paper_simulated_only": True,
            "internal_simulated_account": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
            "manual_m12_37_once": False,
        },
        "paper_simulated_only": True,
        "internal_simulated_account": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.assessment_json_path, payload)
    config.assessment_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.assessment_md_path.write_text(build_assessment_md(payload), encoding="utf-8")
    return payload


def build_summary(
    goal: dict[str, Any],
    next_session: dict[str, Any],
    backlog: dict[str, Any],
    post_refresh: dict[str, Any],
    external_map: dict[str, Any],
    parameter_queue: dict[str, Any],
    activation_gate: dict[str, Any],
    objective_audit: dict[str, Any],
    strategy_routes: list[dict[str, Any]],
) -> dict[str, Any]:
    challenge = goal.get("challenge", {})
    internal_gate = goal.get("internal_simulation_gate", {})
    launch = goal.get("internal_sim_launch_readiness", {})
    rescue_ab = goal.get("rescue_ab_evidence", {})
    next_refresh = goal.get("rescue_next_refresh_readiness", {})
    broker = goal.get("broker_readiness", {})
    next_summary = next_session.get("summary", {})
    backlog_summary = backlog.get("summary", {})
    post_summary = post_refresh.get("summary", {})
    external_summary = external_map.get("summary", {})
    parameter_summary = parameter_queue.get("summary", {})
    activation_summary = activation_gate.get("summary", {})
    objective_summary = objective_audit.get("summary", {})
    route_counts = dict(sorted(Counter(str(row.get("route_category", "")) for row in strategy_routes).items()))
    return {
        "current_project_stage": str(goal.get("project_stage_label", "")),
        "ten_day_challenge_complete": bool(challenge.get("ten_day_challenge_complete", False)),
        "challenge_progress_label": str(challenge.get("challenge_progress_label", "")),
        "effective_challenge_trading_days": int_or_zero(challenge.get("effective_challenge_trading_days")),
        "required_challenge_trading_days": int_or_zero(challenge.get("required_challenge_trading_days")),
        "data_quality_state": str(challenge.get("data_quality_state", "")),
        "approved_internal_sim_strategy_count": int_or_zero(
            internal_gate.get("approved_internal_sim_strategy_count")
        ),
        "approved_internal_sim_strategy_ids": list(internal_gate.get("approved_internal_sim_strategy_ids", [])),
        "launch_ready_strategy_count": int_or_zero(launch.get("launch_ready_strategy_count")),
        "approved_runtime_input_connected_count": int_or_zero(
            next_summary.get("approved_runtime_input_connected_count")
        ),
        "approved_runtime_input_count": int_or_zero(next_summary.get("approved_runtime_input_count")),
        "can_run_next_internal_sim_session": bool(next_summary.get("can_run_next_internal_sim_session", False)),
        "next_session_mode": str(next_summary.get("next_session_mode", "")),
        "broker_watch_strategy_count": int_or_zero(next_summary.get("broker_watch_strategy_count")),
        "broker_watch_strategy_ids": list(next_summary.get("broker_watch_strategy_ids", [])),
        "rescue_runtime_strategy_count": int_or_zero(rescue_ab.get("rescue_runtime_strategy_count")),
        "rescue_m13_ledger_observed_strategy_count": int_or_zero(
            rescue_ab.get("m13_ledger_observed_strategy_count")
        ),
        "rescue_no_m13_ledger_evidence_count": int_or_zero(rescue_ab.get("no_m13_ledger_evidence_count")),
        "rescue_no_m13_ledger_strategy_ids": list(rescue_ab.get("no_m13_ledger_evidence_strategy_ids", [])),
        "rescue_promotion_allowed_count": int_or_zero(rescue_ab.get("promotion_allowed_count")),
        "rescue_next_refresh_watch_rows": int_or_zero(next_refresh.get("watch_rows")),
        "rescue_parameter_change_allowed_now_count": int_or_zero(
            next_refresh.get("parameter_change_allowed_now_count")
        ),
        "post_refresh_fresh_refresh_observed": bool(post_summary.get("fresh_refresh_observed", False)),
        "post_refresh_source_quote": str(post_summary.get("source_quote", "")),
        "post_refresh_source_scan_date": str(post_summary.get("source_scan_date", "")),
        "post_refresh_latest_ledger_trading_date": str(post_summary.get("latest_ledger_trading_date", "")),
        "post_refresh_watch_rows": int_or_zero(post_summary.get("watch_rows")),
        "post_refresh_waiting_count": int_or_zero(post_summary.get("waiting_count")),
        "post_refresh_passed_count": int_or_zero(post_summary.get("passed_count")),
        "post_refresh_failed_count": int_or_zero(post_summary.get("failed_count")),
        "post_refresh_manual_m12_37_once_allowed": False,
        "external_reference_mapped_rescue_row_count": int_or_zero(
            external_summary.get("mapped_rescue_row_count")
        ),
        "external_reference_broker_blocker_row_count": int_or_zero(
            external_summary.get("broker_blocker_reference_row_count")
        ),
        "external_reference_p0_row_count": int_or_zero(external_summary.get("p0_reference_row_count")),
        "external_reference_project_count": int_or_zero(
            external_summary.get("external_reference_project_count")
        ),
        "external_reference_copy_trading_allowed": False,
        "external_reference_external_override_allowed": False,
        "parameter_experiment_row_count": int_or_zero(parameter_summary.get("experiment_row_count")),
        "parameter_experiment_allowed_now_count": int_or_zero(parameter_summary.get("allowed_now_count")),
        "parameter_experiment_blocked_until_fresh_refresh_count": int_or_zero(
            parameter_summary.get("blocked_until_fresh_refresh_count")
        ),
        "parameter_experiment_shadow_runtime_wait_first_ledger_count": int_or_zero(
            parameter_summary.get("shadow_runtime_wait_first_ledger_count")
        ),
        "parameter_experiment_broker_blocker_count": int_or_zero(
            parameter_summary.get("broker_blocker_experiment_count")
        ),
        "parameter_experiment_target_stop_count": int_or_zero(
            parameter_summary.get("target_stop_experiment_count")
        ),
        "parameter_experiment_m13_registry_mutation_count": int_or_zero(
            parameter_summary.get("m13_registry_mutation_count")
        ),
        "parameter_experiment_m12_account_specs_mutation_count": int_or_zero(
            parameter_summary.get("m12_account_specs_mutation_count")
        ),
        "parameter_experiment_broker_readiness_status_mutation_count": int_or_zero(
            parameter_summary.get("broker_readiness_status_mutation_count")
        ),
        "parameter_activation_gate_row_count": int_or_zero(activation_summary.get("gate_row_count")),
        "parameter_activation_shadow_review_candidate_count": int_or_zero(
            activation_summary.get("shadow_review_candidate_count")
        ),
        "parameter_activation_waiting_for_fresh_refresh_count": int_or_zero(
            activation_summary.get("waiting_for_fresh_refresh_count")
        ),
        "parameter_activation_evidence_failed_count": int_or_zero(
            activation_summary.get("evidence_failed_count")
        ),
        "parameter_activation_first_ledger_ready_count": int_or_zero(
            activation_summary.get("first_ledger_ready_count")
        ),
        "parameter_activation_implementation_mutation_allowed_count": int_or_zero(
            activation_summary.get("implementation_mutation_allowed_count")
        ),
        "parameter_activation_parameter_mutation_allowed_count": int_or_zero(
            activation_summary.get("parameter_mutation_allowed_count")
        ),
        "objective_audit_requirement_count": int_or_zero(objective_summary.get("requirement_count")),
        "objective_audit_proven_count": int_or_zero(objective_summary.get("proven_count")),
        "objective_audit_blocked_count": int_or_zero(objective_summary.get("blocked_count")),
        "objective_audit_in_progress_count": int_or_zero(objective_summary.get("in_progress_count")),
        "objective_audit_guardrail_count": int_or_zero(objective_summary.get("guardrail_count")),
        "objective_audit_complete": bool(objective_summary.get("objective_complete", False)),
        "objective_audit_blockers": list(objective_summary.get("objective_blockers", [])),
        "rescue_actionable_before_10d_count": int_or_zero(
            backlog_summary.get("actionable_before_10d_count")
        ),
        "rescue_zero_signal_after_connection_count": int_or_zero(
            backlog_summary.get("zero_signal_after_connection_count")
        ),
        "broker_dry_run_ready_count": int_or_zero(broker.get("dry_run_ready_count")),
        "broker_dry_run_blocked_count": int_or_zero(broker.get("blocked_count")),
        "strategy_route_count": len(strategy_routes),
        "route_counts": route_counts,
        "can_start_broker_paper": False,
        "broker_or_live_enabled": False,
        "manual_m12_37_once_allowed": False,
        "goal_complete": False,
    }


def build_stage_assessment(
    goal: dict[str, Any],
    next_session: dict[str, Any],
    backlog: dict[str, Any],
    post_refresh: dict[str, Any],
    external_map: dict[str, Any],
    parameter_queue: dict[str, Any],
    activation_gate: dict[str, Any],
    objective_audit: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    post_refresh_status = (
        "post_refresh_reviewed"
        if summary["post_refresh_fresh_refresh_observed"]
        else "waiting_for_m12_47_fresh_refresh"
    )
    return {
        "current_phase": summary["current_project_stage"],
        "stage_decision": "continue_approved_internal_sim_and_collect_rescue_ab_evidence",
        "ten_day_status": (
            "complete" if summary["ten_day_challenge_complete"] else "incomplete"
        ),
        "internal_sim_status": (
            "ready_for_m12_47_supervised_next_session"
            if summary["can_run_next_internal_sim_session"]
            else "hold_until_internal_sim_readiness_repaired"
        ),
        "rescue_status": "connected_but_not_promoted",
        "post_refresh_status": post_refresh_status,
        "external_reference_status": "architecture_reference_only_no_external_override",
        "parameter_experiment_status": "queued_for_post_refresh_review_no_mutation",
        "parameter_activation_status": "waiting_for_fresh_refresh_no_activation",
        "objective_completion_status": (
            "complete" if summary["objective_audit_complete"] else "blocked_or_in_progress"
        ),
        "broker_status": "dry_run_preview_only_not_broker_paper",
        "next_required_evidence": [
            (
                f"{summary['rescue_runtime_strategy_count']} rescue runtimes must collect their own A/B evidence; "
                f"{summary['rescue_m13_ledger_observed_strategy_count']} currently have M13 ledger evidence."
            ),
            (
                f"{summary['rescue_no_m13_ledger_evidence_count']} rescue runtimes need a first M13 ledger row after the next M12.47 refresh."
            ),
            (
                f"Post-refresh review has {summary['post_refresh_waiting_count']} waiting, "
                f"{summary['post_refresh_passed_count']} passed/evidence, and {summary['post_refresh_failed_count']} failed rows."
            ),
            (
                f"External-reference map covers {summary['external_reference_mapped_rescue_row_count']} rescue rows "
                f"and {summary['external_reference_broker_blocker_row_count']} broker-blocker rows as architecture references only."
            ),
            (
                f"Parameter experiment queue has {summary['parameter_experiment_row_count']} rows, "
                f"{summary['parameter_experiment_allowed_now_count']} allowed now, and "
                f"{summary['parameter_experiment_blocked_until_fresh_refresh_count']} waiting for a fresh refresh."
            ),
            (
                f"Parameter activation gate has {summary['parameter_activation_gate_row_count']} rows, "
                f"{summary['parameter_activation_shadow_review_candidate_count']} shadow-review candidates, "
                f"and {summary['parameter_activation_implementation_mutation_allowed_count']} implementation mutations allowed."
            ),
            (
                f"Objective completion audit has {summary['objective_audit_requirement_count']} requirements, "
                f"{summary['objective_audit_blocked_count']} blocked and "
                f"{summary['objective_audit_in_progress_count']} in progress."
            ),
            (
                f"{summary['broker_dry_run_blocked_count']} broker dry-run blocker rows must stay watch-only until repaired in internal simulation."
            ),
        ],
        "next_session_plain_result": str(next_session.get("plain_language_result", "")),
        "goal_plain_result": str(goal.get("plain_language_result", "")),
        "backlog_plain_result": str(backlog.get("plain_language_result", "")),
        "post_refresh_plain_result": str(post_refresh.get("plain_language_result", "")),
        "external_reference_plain_result": str(external_map.get("plain_language_result", "")),
        "parameter_experiment_plain_result": str(parameter_queue.get("plain_language_result", "")),
        "parameter_activation_plain_result": str(activation_gate.get("plain_language_result", "")),
        "objective_completion_plain_result": str(objective_audit.get("plain_language_result", "")),
    }


def build_post_refresh_outcome_review(post_refresh: dict[str, Any]) -> dict[str, Any]:
    summary = post_refresh.get("summary", {})
    source_state = post_refresh.get("source_state", {})
    return {
        "fresh_refresh_observed": bool(summary.get("fresh_refresh_observed", False)),
        "source_quote": str(summary.get("source_quote", "")),
        "source_scan_date": str(summary.get("source_scan_date", "")),
        "latest_ledger_trading_date": str(summary.get("latest_ledger_trading_date", "")),
        "watch_rows": int_or_zero(summary.get("watch_rows")),
        "waiting_count": int_or_zero(summary.get("waiting_count")),
        "passed_count": int_or_zero(summary.get("passed_count")),
        "failed_count": int_or_zero(summary.get("failed_count")),
        "outcome_status_counts": dict(summary.get("outcome_status_counts", {})),
        "readiness_family_counts": dict(summary.get("readiness_family_counts", {})),
        "dashboard_generated_at": str(source_state.get("dashboard_generated_at", "")),
        "manual_m12_37_once_allowed": False,
        "parameter_change_allowed_now_count": 0,
        "broker_or_live_enabled": False,
        "plain_language_result": str(post_refresh.get("plain_language_result", "")),
    }


def build_external_reference_map(external_map: dict[str, Any]) -> dict[str, Any]:
    summary = external_map.get("summary", {})
    return {
        "mapped_rescue_row_count": int_or_zero(summary.get("mapped_rescue_row_count")),
        "broker_blocker_reference_row_count": int_or_zero(
            summary.get("broker_blocker_reference_row_count")
        ),
        "p0_reference_row_count": int_or_zero(summary.get("p0_reference_row_count")),
        "external_reference_project_count": int_or_zero(summary.get("external_reference_project_count")),
        "next_refresh_dependent_count": int_or_zero(summary.get("next_refresh_dependent_count")),
        "parameter_change_allowed_now_count": int_or_zero(
            summary.get("parameter_change_allowed_now_count")
        ),
        "copy_trading_allowed": False,
        "external_decision_can_override_local_gate": False,
        "broker_or_live_enabled": False,
        "plain_language_result": str(external_map.get("plain_language_result", "")),
    }


def build_parameter_experiment_queue(parameter_queue: dict[str, Any]) -> dict[str, Any]:
    summary = parameter_queue.get("summary", {})
    return {
        "experiment_row_count": int_or_zero(summary.get("experiment_row_count")),
        "rescue_experiment_row_count": int_or_zero(summary.get("rescue_experiment_row_count")),
        "broker_blocker_experiment_count": int_or_zero(summary.get("broker_blocker_experiment_count")),
        "allowed_now_count": int_or_zero(summary.get("allowed_now_count")),
        "blocked_until_fresh_refresh_count": int_or_zero(
            summary.get("blocked_until_fresh_refresh_count")
        ),
        "shadow_runtime_wait_first_ledger_count": int_or_zero(
            summary.get("shadow_runtime_wait_first_ledger_count")
        ),
        "target_stop_experiment_count": int_or_zero(summary.get("target_stop_experiment_count")),
        "m13_registry_mutation_count": int_or_zero(summary.get("m13_registry_mutation_count")),
        "m12_account_specs_mutation_count": int_or_zero(summary.get("m12_account_specs_mutation_count")),
        "broker_readiness_status_mutation_count": int_or_zero(
            summary.get("broker_readiness_status_mutation_count")
        ),
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "plain_language_result": str(parameter_queue.get("plain_language_result", "")),
    }


def build_parameter_activation_gate(activation_gate: dict[str, Any]) -> dict[str, Any]:
    summary = activation_gate.get("summary", {})
    return {
        "gate_row_count": int_or_zero(summary.get("gate_row_count")),
        "shadow_review_candidate_count": int_or_zero(summary.get("shadow_review_candidate_count")),
        "first_ledger_ready_count": int_or_zero(summary.get("first_ledger_ready_count")),
        "waiting_for_fresh_refresh_count": int_or_zero(summary.get("waiting_for_fresh_refresh_count")),
        "evidence_failed_count": int_or_zero(summary.get("evidence_failed_count")),
        "manual_review_required_count": int_or_zero(summary.get("manual_review_required_count")),
        "implementation_mutation_allowed_count": int_or_zero(
            summary.get("implementation_mutation_allowed_count")
        ),
        "parameter_mutation_allowed_count": int_or_zero(summary.get("parameter_mutation_allowed_count")),
        "m13_registry_mutation_count": int_or_zero(summary.get("m13_registry_mutation_count")),
        "m12_account_specs_mutation_count": int_or_zero(summary.get("m12_account_specs_mutation_count")),
        "broker_readiness_status_mutation_count": int_or_zero(
            summary.get("broker_readiness_status_mutation_count")
        ),
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "plain_language_result": str(activation_gate.get("plain_language_result", "")),
    }


def build_objective_completion_audit(objective_audit: dict[str, Any]) -> dict[str, Any]:
    summary = objective_audit.get("summary", {})
    assessment = objective_audit.get("objective_completion_assessment", {})
    return {
        "objective_complete": bool(summary.get("objective_complete", False)),
        "completion_state": str(assessment.get("completion_state", "")),
        "requirement_count": int_or_zero(summary.get("requirement_count")),
        "proven_count": int_or_zero(summary.get("proven_count")),
        "blocked_count": int_or_zero(summary.get("blocked_count")),
        "in_progress_count": int_or_zero(summary.get("in_progress_count")),
        "guardrail_count": int_or_zero(summary.get("guardrail_count")),
        "requirement_state_counts": dict(summary.get("requirement_state_counts", {})),
        "objective_blockers": list(summary.get("objective_blockers", [])),
        "broker_or_live_enabled": False,
        "manual_m12_37_once_allowed": False,
        "parameter_mutation_allowed_count": int_or_zero(
            summary.get("parameter_mutation_allowed_count")
        ),
        "plain_language_result": str(objective_audit.get("plain_language_result", "")),
    }


def build_strategy_routes(
    *,
    action_matrix: list[dict[str, Any]],
    next_session_rows: list[dict[str, Any]],
    rescue_plan_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    next_by_strategy = {str(row.get("strategy_id", "")): row for row in next_session_rows}
    rescue_plan_by_strategy = {str(row.get("strategy_id", "")): row for row in rescue_plan_rows}
    routes: list[dict[str, Any]] = []
    for row in action_matrix:
        strategy_id = str(row.get("strategy_id", ""))
        next_row = next_by_strategy.get(strategy_id, {})
        plan_row = rescue_plan_by_strategy.get(strategy_id, {})
        route_category = route_category_for(row)
        routes.append(
            {
                "strategy_id": strategy_id,
                "display_name": str(row.get("display_name", "")),
                "route_category": route_category,
                "route_label": route_label_for(route_category),
                "paper_trial_gate": str(row.get("paper_trial_gate", "")),
                "decision": str(row.get("decision", "")),
                "decision_reason": str(row.get("decision_reason", "")),
                "completed_trading_days": int_or_zero(row.get("completed_trading_days")),
                "runtime_ids": list(row.get("runtime_ids", [])),
                "rescue_runtime_strategy_ids": list(row.get("rescue_runtime_strategy_ids", [])),
                "requires_10_day_ab_evidence": bool(row.get("requires_10_day_ab_evidence", False)),
                "can_enter_internal_simulation": bool(row.get("can_enter_internal_simulation", False)),
                "next_action_category": str(row.get("next_action_category", "")),
                "rescue_coverage_status": str(row.get("rescue_coverage_status", "")),
                "broker_watch": bool(next_row.get("broker_dry_run_blocked_count", 0)),
                "session_action": str(next_row.get("session_action", "")),
                "linked_next_refresh_watch_count": int_or_zero(next_row.get("linked_next_refresh_watch_count")),
                "linked_next_refresh_family_counts": dict(next_row.get("linked_next_refresh_family_counts", {})),
                "next_action": str(plan_row.get("next_action", "")) or default_next_action(route_category),
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return routes


def route_category_for(row: dict[str, Any]) -> str:
    category = str(row.get("next_action_category", ""))
    if category == "continue_internal_simulation":
        return "approved_internal_sim_continue"
    if category == "collect_rescue_ab_evidence":
        return "rescue_ab_collect"
    if category == "continue_parallel_ab_evidence":
        return "parallel_ab_collect"
    if category == "rebuild_detector_ab_evidence":
        return "rebuild_detector_then_ab"
    if category == "continue_shadow_or_plugin_review":
        return "shadow_or_plugin_review"
    return "unclassified_review"


def route_label_for(route_category: str) -> str:
    labels = {
        "approved_internal_sim_continue": "Approved internal sim continue",
        "rescue_ab_collect": "Rescue A/B evidence collection",
        "parallel_ab_collect": "Parallel A/B evidence collection",
        "rebuild_detector_then_ab": "Rebuild detector before final discard",
        "shadow_or_plugin_review": "Shadow/plugin/research review",
        "unclassified_review": "Manual review required",
    }
    return labels.get(route_category, "Manual review required")


def default_next_action(route_category: str) -> str:
    defaults = {
        "approved_internal_sim_continue": "Continue internal simulated-account testing under M12.47 supervision.",
        "rescue_ab_collect": "Keep baseline semantics frozen and collect rescue A/B evidence.",
        "parallel_ab_collect": "Continue old and modified variants in parallel until A/B evidence is sufficient.",
        "rebuild_detector_then_ab": "Rebuild detector, then collect A/B evidence before final rejection.",
        "shadow_or_plugin_review": "Keep as shadow, plugin, filter, or research coverage only.",
    }
    return defaults.get(route_category, "Review route manually before changing strategy state.")


def build_next_fresh_refresh_acceptance(
    next_session: dict[str, Any],
    goal: dict[str, Any],
) -> dict[str, Any]:
    summary = next_session.get("summary", {})
    return {
        "mode": str(summary.get("next_session_mode", "")),
        "can_run_next_internal_sim_session": bool(summary.get("can_run_next_internal_sim_session", False)),
        "manual_m12_37_once_allowed": False,
        "global_watch_rows": list(next_session.get("global_watch_rows", [])),
        "execution_protocol": list(next_session.get("execution_protocol", [])),
        "next_actions": list(goal.get("next_actions", [])),
    }


def build_rescue_policy(goal: dict[str, Any], backlog: dict[str, Any]) -> dict[str, Any]:
    rescue_ab = goal.get("rescue_ab_evidence", {})
    next_refresh = goal.get("rescue_next_refresh_readiness", {})
    backlog_summary = backlog.get("summary", {})
    return {
        "policy": "do_not_discard_before_rescue_route_exhausted",
        "promotion_allowed_count": int_or_zero(rescue_ab.get("promotion_allowed_count")),
        "parameter_change_allowed_now_count": int_or_zero(
            next_refresh.get("parameter_change_allowed_now_count")
        ),
        "actionable_before_10d_count": int_or_zero(backlog_summary.get("actionable_before_10d_count")),
        "zero_signal_after_connection_count": int_or_zero(
            backlog_summary.get("zero_signal_after_connection_count")
        ),
        "missing_rescue_ledger_count": int_or_zero(backlog_summary.get("missing_rescue_ledger_count")),
        "broker_blocker_reason_counts": dict(backlog_summary.get("broker_blocker_reason_counts", {})),
        "parameter_experiment_rule": (
            "Current parameter families are queued for post-refresh shadow review only; allowed-now remains zero."
        ),
        "parameter_activation_rule": (
            "A parameter family can only become a shadow-review candidate after post-refresh evidence passes; "
            "implementation and parameter mutation remain disabled in this assessment."
        ),
        "rule": (
            "Approved strategies continue internal simulation; weak strategies collect rescue A/B evidence, "
            "run shadow parameter tests, or rebuild detectors before any final discard."
        ),
    }


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    approved = ", ".join(summary["approved_internal_sim_strategy_ids"])
    challenge_state = "complete" if summary["ten_day_challenge_complete"] else "incomplete"
    next_session_state = "ready" if summary["can_run_next_internal_sim_session"] else "not ready"
    return (
        f"Project is at {summary['current_project_stage']}. "
        f"10-day challenge is {summary['challenge_progress_label']} and {challenge_state}. "
        f"Approved internal simulated-account strategies: {approved}. "
        f"Next session is {next_session_state} in {summary['next_session_mode']} mode, "
        f"with {summary['approved_runtime_input_connected_count']}/{summary['approved_runtime_input_count']} approved runtimes connected. "
        f"Rescue evidence is {summary['rescue_m13_ledger_observed_strategy_count']}/{summary['rescue_runtime_strategy_count']} observed, "
        f"{summary['rescue_no_m13_ledger_evidence_count']} need first ledger rows, and promotion allowed remains {summary['rescue_promotion_allowed_count']}. "
        f"Post-refresh review is "
        f"{'reviewed' if summary['post_refresh_fresh_refresh_observed'] else 'waiting for fresh M12.47 data'} "
        f"with {summary['post_refresh_waiting_count']} waiting, {summary['post_refresh_passed_count']} passed/evidence, "
        f"and {summary['post_refresh_failed_count']} failed rows from quote_source={summary['post_refresh_source_quote']}. "
        f"External references are mapped to {summary['external_reference_mapped_rescue_row_count']} rescue rows and "
        f"{summary['external_reference_broker_blocker_row_count']} broker-blocker rows as architecture references only. "
        f"Parameter experiments are queued in {summary['parameter_experiment_row_count']} rows, "
        f"with allowed-now changes at {summary['parameter_experiment_allowed_now_count']} and "
        f"{summary['parameter_experiment_blocked_until_fresh_refresh_count']} waiting for fresh refresh evidence. "
        f"Activation gate shows {summary['parameter_activation_shadow_review_candidate_count']} shadow-review candidates "
        f"and {summary['parameter_activation_implementation_mutation_allowed_count']} implementation mutations allowed. "
        f"Objective audit is complete={summary['objective_audit_complete']} with "
        f"{summary['objective_audit_blocked_count']} blocked and "
        f"{summary['objective_audit_in_progress_count']} in-progress requirements. "
        f"Broker readiness stays dry-run preview only: {summary['broker_dry_run_ready_count']} ready and {summary['broker_dry_run_blocked_count']} blocked; "
        "manual M12.37 once-mode, broker paper, live execution, real orders, and paper approval remain disabled."
    )


def build_assessment_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Project Stage Assessment",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Next session ready: `{summary['can_run_next_internal_sim_session']}`",
        f"- Approved internal sim strategies: `{', '.join(summary['approved_internal_sim_strategy_ids'])}`",
        f"- Approved runtime input coverage: `{summary['approved_runtime_input_connected_count']}/{summary['approved_runtime_input_count']}`",
        f"- Rescue evidence observed: `{summary['rescue_m13_ledger_observed_strategy_count']}/{summary['rescue_runtime_strategy_count']}`",
        f"- Rescue promotions allowed: `{summary['rescue_promotion_allowed_count']}`",
        f"- Post-refresh fresh refresh observed: `{summary['post_refresh_fresh_refresh_observed']}`",
        f"- Post-refresh quote source: `{summary['post_refresh_source_quote']}`",
        f"- Post-refresh waiting/passed/failed: `{summary['post_refresh_waiting_count']}/{summary['post_refresh_passed_count']}/{summary['post_refresh_failed_count']}`",
        f"- External reference rescue/broker rows: `{summary['external_reference_mapped_rescue_row_count']}/{summary['external_reference_broker_blocker_row_count']}`",
        f"- Parameter experiment rows: `{summary['parameter_experiment_row_count']}`",
        f"- Parameter experiments allowed now: `{summary['parameter_experiment_allowed_now_count']}`",
        f"- Parameter experiments blocked until fresh refresh: `{summary['parameter_experiment_blocked_until_fresh_refresh_count']}`",
        f"- Parameter activation shadow-review candidates: `{summary['parameter_activation_shadow_review_candidate_count']}`",
        f"- Parameter activation implementation mutations allowed: `{summary['parameter_activation_implementation_mutation_allowed_count']}`",
        f"- Objective audit complete: `{summary['objective_audit_complete']}`",
        f"- Objective audit requirements/proven/blocked/in-progress/guardrail: `{summary['objective_audit_requirement_count']}/{summary['objective_audit_proven_count']}/{summary['objective_audit_blocked_count']}/{summary['objective_audit_in_progress_count']}/{summary['objective_audit_guardrail_count']}`",
        f"- Broker dry-run ready/blocked: `{summary['broker_dry_run_ready_count']}/{summary['broker_dry_run_blocked_count']}`",
        "- Boundary: internal simulated accounts only; no broker connection, no real orders, no live execution.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Stage Assessment",
        "",
        f"- Decision: `{payload['stage_assessment']['stage_decision']}`",
        f"- Internal sim status: `{payload['stage_assessment']['internal_sim_status']}`",
        f"- Rescue status: `{payload['stage_assessment']['rescue_status']}`",
        f"- Post-refresh status: `{payload['stage_assessment']['post_refresh_status']}`",
        f"- External reference status: `{payload['stage_assessment']['external_reference_status']}`",
        f"- Parameter experiment status: `{payload['stage_assessment']['parameter_experiment_status']}`",
        f"- Parameter activation status: `{payload['stage_assessment']['parameter_activation_status']}`",
        f"- Objective completion status: `{payload['stage_assessment']['objective_completion_status']}`",
        f"- Broker status: `{payload['stage_assessment']['broker_status']}`",
        "",
        "## Route Counts",
        "",
    ]
    for route, count in summary["route_counts"].items():
        lines.append(f"- `{route}`: `{count}`")
    lines.extend(["", "## Strategy Routes", ""])
    for row in payload["strategy_routes"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Route: `{row['route_category']}`",
                f"- Gate: `{row['paper_trial_gate']}`",
                f"- Decision: `{row['decision']}`",
                f"- Completed days: `{row['completed_trading_days']}`",
                f"- Requires rescue A/B evidence: `{row['requires_10_day_ab_evidence']}`",
                f"- Broker watch: `{row['broker_watch']}`",
                f"- Next action: {row['next_action']}",
                "",
            ]
        )
    lines.extend(["## Next Fresh Refresh Acceptance", ""])
    acceptance = payload["next_fresh_refresh_acceptance"]
    lines.append(f"- Mode: `{acceptance['mode']}`")
    lines.append(f"- Manual M12.37 once-mode allowed: `{acceptance['manual_m12_37_once_allowed']}`")
    for row in acceptance["global_watch_rows"]:
        lines.append(f"- `{row.get('priority', '')}` `{row.get('watch_id', '')}`: {row.get('expected_after_refresh', '')}")
    lines.append("")
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
