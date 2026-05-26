#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_objective_execution_plan.json"

FORBIDDEN_OPERATIONS = [
    "manual_m12_37_once",
    "broker_connection",
    "real_order",
    "live_execution",
    "paper_trading_approval",
    "m13_registry_mutation",
    "m12_account_specs_mutation",
    "broker_readiness_status_mutation",
    "parameter_mutation",
]


@dataclass(frozen=True, slots=True)
class ObjectiveExecutionPlanConfig:
    stage: str
    project_stage_label: str
    objective_completion_audit_path: Path
    internal_sim_next_session_plan_path: Path
    rescue_ab_evidence_tracker_path: Path
    rescue_parameter_activation_gate_path: Path
    rescue_external_reference_map_path: Path
    broker_readiness_plan_path: Path
    execution_plan_json_path: Path
    execution_plan_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> ObjectiveExecutionPlanConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = ObjectiveExecutionPlanConfig(
        stage=str(payload["stage"]),
        project_stage_label=str(payload["project_stage_label"]),
        objective_completion_audit_path=resolve_repo_path(inputs["m14_objective_completion_audit"]),
        internal_sim_next_session_plan_path=resolve_repo_path(inputs["m14_internal_sim_next_session_plan"]),
        rescue_ab_evidence_tracker_path=resolve_repo_path(inputs["m14_rescue_ab_evidence_tracker"]),
        rescue_parameter_activation_gate_path=resolve_repo_path(
            inputs["m14_rescue_parameter_activation_gate"]
        ),
        rescue_external_reference_map_path=resolve_repo_path(inputs["m14_rescue_external_reference_map"]),
        broker_readiness_plan_path=resolve_repo_path(inputs["m14_2_broker_readiness_plan"]),
        execution_plan_json_path=resolve_repo_path(outputs["execution_plan_json"]),
        execution_plan_md_path=resolve_repo_path(outputs["execution_plan_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: ObjectiveExecutionPlanConfig) -> None:
    if config.stage != "M14.objective_execution_plan":
        raise ValueError("M14 objective execution plan stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 objective execution plan must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 objective execution plan must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 objective execution plan cannot enable {key}")


def run_m14_objective_execution_plan(
    config: ObjectiveExecutionPlanConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    objective_audit = read_json(config.objective_completion_audit_path)
    next_session = read_json(config.internal_sim_next_session_plan_path)
    rescue_ab = read_json(config.rescue_ab_evidence_tracker_path)
    activation_gate = read_json(config.rescue_parameter_activation_gate_path)
    external_map = read_json(config.rescue_external_reference_map_path)
    broker_plan = read_json(config.broker_readiness_plan_path)

    rescue_rows = build_rescue_strategy_rows(rescue_ab)
    parameter_rows = build_parameter_gate_digest_rows(activation_gate)
    summary = build_summary(
        objective_audit=objective_audit,
        next_session=next_session,
        rescue_ab=rescue_ab,
        activation_gate=activation_gate,
        external_map=external_map,
        broker_plan=broker_plan,
        rescue_rows=rescue_rows,
        parameter_rows=parameter_rows,
    )
    execution_actions = build_execution_actions(summary, rescue_rows, parameter_rows)
    action_state_counts = dict(sorted(Counter(row["action_state"] for row in execution_actions).items()))
    priority_counts = dict(sorted(Counter(row["priority"] for row in execution_actions).items()))
    summary.update(
        {
            "execution_action_count": len(execution_actions),
            "execution_action_state_counts": action_state_counts,
            "execution_priority_counts": priority_counts,
            "p0_action_count": priority_counts.get("P0", 0),
            "waiting_for_fresh_refresh_action_count": sum(
                1 for row in execution_actions if row["requires_m12_47_fresh_refresh"]
            ),
            "manual_execution_allowed_count": sum(
                1 for row in execution_actions if row["manual_execution_allowed"]
            ),
        }
    )

    payload: dict[str, Any] = {
        "schema_version": "m14.objective-execution-plan.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "project_stage_label": config.project_stage_label,
        "m14_trading_date": summary["m14_trading_date"],
        "input_refs": {
            "m14_objective_completion_audit": project_path(config.objective_completion_audit_path),
            "m14_internal_sim_next_session_plan": project_path(config.internal_sim_next_session_plan_path),
            "m14_rescue_ab_evidence_tracker": project_path(config.rescue_ab_evidence_tracker_path),
            "m14_rescue_parameter_activation_gate": project_path(
                config.rescue_parameter_activation_gate_path
            ),
            "m14_rescue_external_reference_map": project_path(config.rescue_external_reference_map_path),
            "m14_2_broker_readiness_plan": project_path(config.broker_readiness_plan_path),
        },
        "summary": summary,
        "execution_actions": execution_actions,
        "rescue_strategy_rows": rescue_rows,
        "parameter_gate_digest_rows": parameter_rows,
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
    write_json(config.execution_plan_json_path, payload)
    config.execution_plan_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.execution_plan_md_path.write_text(build_execution_plan_md(payload), encoding="utf-8")
    return payload


def build_summary(
    *,
    objective_audit: dict[str, Any],
    next_session: dict[str, Any],
    rescue_ab: dict[str, Any],
    activation_gate: dict[str, Any],
    external_map: dict[str, Any],
    broker_plan: dict[str, Any],
    rescue_rows: list[dict[str, Any]],
    parameter_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    objective_summary = objective_audit.get("summary", {})
    objective_assessment = objective_audit.get("objective_completion_assessment", {})
    next_summary = next_session.get("summary", {})
    rescue_summary = rescue_ab.get("summary", {})
    activation_summary = activation_gate.get("summary", {})
    external_summary = external_map.get("summary", {})
    broker_or_live_enabled = any(
        bool(value)
        for value in (
            broker_plan.get("broker_connection_enabled"),
            broker_plan.get("real_order_enabled"),
            broker_plan.get("live_execution_enabled"),
            broker_plan.get("paper_trading_approval"),
            objective_audit.get("broker_connection"),
            objective_audit.get("real_order"),
            objective_audit.get("live_execution"),
            objective_audit.get("paper_trading_approval"),
        )
    )
    return {
        "objective_complete": bool(objective_summary.get("objective_complete", False)),
        "objective_completion_state": str(objective_assessment.get("completion_state", "")),
        "objective_blockers": list(objective_summary.get("objective_blockers", [])),
        "current_project_stage": str(objective_summary.get("current_project_stage", "")),
        "m14_trading_date": str(objective_summary.get("m14_trading_date") or next_session.get("m14_trading_date", "")),
        "approved_internal_sim_strategy_count": int_or_zero(
            objective_summary.get("approved_internal_sim_strategy_count")
        ),
        "approved_internal_sim_strategy_ids": list(objective_summary.get("approved_internal_sim_strategy_ids", [])),
        "can_run_next_internal_sim_session": bool(next_summary.get("can_run_next_internal_sim_session", False)),
        "next_session_mode": str(next_summary.get("next_session_mode", "")),
        "approved_runtime_input_connected_count": int_or_zero(
            next_summary.get("approved_runtime_input_connected_count")
        ),
        "approved_runtime_input_count": int_or_zero(next_summary.get("approved_runtime_input_count")),
        "broker_watch_strategy_count": int_or_zero(next_summary.get("broker_watch_strategy_count")),
        "broker_watch_strategy_ids": list(next_summary.get("broker_watch_strategy_ids", [])),
        "rescue_runtime_strategy_count": int_or_zero(rescue_summary.get("rescue_runtime_strategy_count")),
        "rescue_pending_evidence_count": len(rescue_summary.get("pending_evidence_strategy_ids", [])),
        "rescue_m13_ledger_observed_strategy_count": int_or_zero(
            rescue_summary.get("m13_ledger_observed_strategy_count")
        ),
        "rescue_no_m13_ledger_evidence_count": int_or_zero(
            rescue_summary.get("no_m13_ledger_evidence_count")
        ),
        "rescue_no_m13_ledger_evidence_strategy_ids": list(
            rescue_summary.get("no_m13_ledger_evidence_strategy_ids", [])
        ),
        "rescue_promotion_allowed_count": int_or_zero(rescue_summary.get("promotion_allowed_count")),
        "rescue_ready_for_manual_review_count": int_or_zero(
            rescue_summary.get("evidence_ready_for_manual_review_count")
        ),
        "rescue_rows_collecting_count": sum(
            1 for row in rescue_rows if row["execution_state"] == "collect_rescue_ab_evidence"
        ),
        "rescue_rows_first_ledger_wait_count": sum(
            1 for row in rescue_rows if row["execution_state"] == "wait_first_m13_rescue_ledger"
        ),
        "parameter_gate_row_count": int_or_zero(activation_summary.get("gate_row_count")),
        "parameter_waiting_for_fresh_refresh_count": int_or_zero(
            activation_summary.get("waiting_for_fresh_refresh_count")
        ),
        "parameter_continue_ab_collection_count": int_or_zero(
            activation_summary.get("continue_ab_collection_count")
        ),
        "parameter_shadow_review_candidate_count": int_or_zero(
            activation_summary.get("shadow_review_candidate_count")
        ),
        "parameter_implementation_mutation_allowed_count": int_or_zero(
            activation_summary.get("implementation_mutation_allowed_count")
        ),
        "parameter_mutation_allowed_count": int_or_zero(
            activation_summary.get("parameter_mutation_allowed_count")
        ),
        "fresh_refresh_observed": bool(activation_summary.get("fresh_refresh_observed", False)),
        "source_quote": str(activation_summary.get("source_quote", "")),
        "parameter_gate_state_counts": dict(activation_summary.get("gate_state_counts", {})),
        "parameter_digest_waiting_count": sum(
            1 for row in parameter_rows if row["execution_state"] == "wait_fresh_refresh"
        ),
        "external_reference_project_count": int_or_zero(
            external_summary.get("external_reference_project_count")
        ),
        "external_reference_mapped_rescue_row_count": int_or_zero(
            external_summary.get("mapped_rescue_row_count")
        ),
        "external_reference_broker_blocker_row_count": int_or_zero(
            external_summary.get("broker_blocker_reference_row_count")
        ),
        "external_reference_copy_trading_allowed": bool(external_summary.get("copy_trading_allowed", False)),
        "broker_dry_run_ready_count": int_or_zero(broker_plan.get("dry_run_ready_count")),
        "broker_dry_run_blocked_count": int_or_zero(broker_plan.get("blocked_count")),
        "broker_or_live_enabled": broker_or_live_enabled,
        "manual_m12_37_once_allowed": bool(
            objective_audit.get("manual_m12_37_once")
            or activation_summary.get("manual_m12_37_once_allowed")
            or next_summary.get("manual_m12_37_once_allowed")
        ),
    }


def build_rescue_strategy_rows(rescue_ab: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in rescue_ab.get("rows", []):
        observed_days = int_or_zero(row.get("observed_trading_days_count"))
        remaining_days = int_or_zero(row.get("remaining_ab_trading_days"))
        evidence_status = str(row.get("evidence_status", ""))
        if evidence_status == "no_m13_rescue_ledger_evidence_yet":
            execution_state = "wait_first_m13_rescue_ledger"
            next_action = "Wait for the next M12.47-owned refresh to produce the first rescue-specific M13 ledger row."
        elif bool(row.get("ready_for_manual_review", False)):
            execution_state = "ready_for_manual_m14_review"
            next_action = "Run manual M14 review before any promote/modify/reject decision."
        else:
            execution_state = "collect_rescue_ab_evidence"
            next_action = "Keep collecting rescue-specific 10-trading-day A/B evidence."
        rows.append(
            {
                "strategy_id": str(row.get("strategy_id", "")),
                "parent_strategy_id": str(row.get("parent_strategy_id", "")),
                "evidence_status": evidence_status,
                "execution_state": execution_state,
                "promotion_blocked_reason": str(row.get("promotion_blocked_reason", "")),
                "observed_trading_days_count": observed_days,
                "remaining_ab_trading_days": remaining_days,
                "required_ab_trading_days": int_or_zero(row.get("required_ab_trading_days")),
                "latest_trading_date": str(row.get("latest_trading_date", "")),
                "m13_account_ledger_row_count": int_or_zero(row.get("m13_account_ledger_row_count")),
                "m13_signal_ledger_row_count": int_or_zero(row.get("m13_signal_ledger_row_count")),
                "signal_count": int_or_zero(row.get("signal_count")),
                "open_count": int_or_zero(row.get("open_count")),
                "risk_blocked_count": int_or_zero(row.get("risk_blocked_count")),
                "runtime_ids": list(row.get("runtime_ids", [])),
                "next_action": next_action,
                "manual_m12_37_once": False,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
                "parameter_mutation": False,
            }
        )
    return rows


def build_parameter_gate_digest_rows(activation_gate: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in activation_gate.get("gate_rows", []):
        gate_state = str(row.get("gate_state", ""))
        if bool(row.get("shadow_review_candidate", False)):
            execution_state = "ready_for_manual_shadow_review"
        elif gate_state == "continue_ab_collection_only":
            execution_state = "continue_ab_collection_only"
        elif gate_state == "waiting_for_m12_47_fresh_refresh":
            execution_state = "wait_fresh_refresh"
        else:
            execution_state = "hold_for_manual_review"
        rows.append(
            {
                "gate_row_id": str(row.get("gate_row_id", "")),
                "strategy_id": str(row.get("strategy_id", "")),
                "parent_strategy_id": str(row.get("parent_strategy_id", "")),
                "priority": str(row.get("priority", "")),
                "issue_type": str(row.get("issue_type", "")),
                "experiment_family": str(row.get("experiment_family", "")),
                "candidate_parameter_family": str(row.get("candidate_parameter_family", "")),
                "required_readiness_family": str(row.get("required_readiness_family", "")),
                "source_experiment_status": str(row.get("source_experiment_status", "")),
                "gate_state": gate_state,
                "execution_state": execution_state,
                "shadow_review_candidate": bool(row.get("shadow_review_candidate", False)),
                "implementation_mutation_allowed": False,
                "parameter_mutation_allowed": False,
                "next_action": str(row.get("next_action", "")),
                "runtime_ids": list(row.get("runtime_ids", [])),
                "manual_m12_37_once": False,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return rows


def build_execution_actions(
    summary: dict[str, Any],
    rescue_rows: list[dict[str, Any]],
    parameter_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        execution_action(
            action_id="approved_internal_sim_next_refresh",
            priority="P0",
            action_state="ready_for_m12_47_supervisor_window"
            if summary["can_run_next_internal_sim_session"]
            else "blocked",
            execution_gate="m12_47_supervised_refresh_required",
            requirement_ids=["approved_strategies_can_continue_internal_sim"],
            evidence=(
                f"{summary['approved_internal_sim_strategy_count']} approved strategies and "
                f"{summary['approved_runtime_input_connected_count']}/{summary['approved_runtime_input_count']} "
                "approved runtime inputs are connected."
            ),
            next_action="Wait for the M12.47 supervisor trading window and review refreshed M13 ledgers afterward.",
            strategy_ids=summary["approved_internal_sim_strategy_ids"],
            runtime_ids=[],
            blocked_by=[] if summary["can_run_next_internal_sim_session"] else ["internal_sim_next_session_not_ready"],
            requires_m12_47_fresh_refresh=True,
            next_verification_artifacts=[
                "m14_internal_sim_next_session_plan",
                "m13_daily_strategy_scorecard",
                "m13_account_operation_ledger",
            ],
            success_condition="Approved strategies stay connected and refresh their internal simulated-account ledgers.",
        ),
        execution_action(
            action_id="rescue_first_ledger_watch",
            priority="P0",
            action_state="waiting_for_m12_47_fresh_refresh"
            if summary["rescue_no_m13_ledger_evidence_count"]
            else "complete",
            execution_gate="m12_47_supervised_refresh_required",
            requirement_ids=[
                "weak_strategies_rescue_not_discarded",
                "rescue_evidence_sufficient_for_promotion",
            ],
            evidence=(
                f"{summary['rescue_no_m13_ledger_evidence_count']} rescue runtimes still have no M13 rescue ledger."
            ),
            next_action="After the next supervisor-owned refresh, verify first M13 ledger rows for no-ledger rescue runtimes.",
            strategy_ids=summary["rescue_no_m13_ledger_evidence_strategy_ids"],
            runtime_ids=runtime_ids_for_strategies(rescue_rows, summary["rescue_no_m13_ledger_evidence_strategy_ids"]),
            blocked_by=["m12_47_fresh_refresh_not_observed"]
            if summary["rescue_no_m13_ledger_evidence_count"]
            else [],
            requires_m12_47_fresh_refresh=bool(summary["rescue_no_m13_ledger_evidence_count"]),
            next_verification_artifacts=[
                "m14_rescue_ab_evidence_tracker",
                "m13_daily_strategy_scorecard",
                "m13_strategy_signal_ledger",
            ],
            success_condition="Each no-ledger rescue runtime has at least one rescue-specific M13 ledger row.",
        ),
        execution_action(
            action_id="rescue_ab_evidence_window",
            priority="P0",
            action_state="collecting_rescue_ab_evidence"
            if summary["rescue_promotion_allowed_count"] == 0
            else "ready_for_manual_m14_review",
            execution_gate="m12_47_supervised_refresh_required",
            requirement_ids=["rescue_evidence_sufficient_for_promotion"],
            evidence=(
                f"{summary['rescue_m13_ledger_observed_strategy_count']}/"
                f"{summary['rescue_runtime_strategy_count']} rescue strategies have ledger evidence; "
                f"promotion allowed remains {summary['rescue_promotion_allowed_count']}."
            ),
            next_action="Keep rescue variants collecting their own 10-trading-day A/B evidence before promote/modify/reject.",
            strategy_ids=[row["strategy_id"] for row in rescue_rows],
            runtime_ids=flatten_runtime_ids(rescue_rows),
            blocked_by=["needs_10_rescue_ab_trading_days"]
            if summary["rescue_promotion_allowed_count"] == 0
            else [],
            requires_m12_47_fresh_refresh=True,
            next_verification_artifacts=["m14_rescue_ab_evidence_tracker", "m14_objective_completion_audit"],
            success_condition="Rescue variants reach the required rescue-specific A/B evidence window and manual review gate.",
        ),
        execution_action(
            action_id="parameter_shadow_review_after_fresh_evidence",
            priority="P0",
            action_state="waiting_for_m12_47_fresh_refresh_no_candidates"
            if summary["parameter_shadow_review_candidate_count"] == 0
            else "ready_for_manual_shadow_review",
            execution_gate="m12_47_supervised_refresh_required",
            requirement_ids=[
                "parameter_optimization_path_ready",
                "fresh_refresh_required_before_parameter_activation",
            ],
            evidence=(
                f"{summary['parameter_gate_row_count']} parameter gate rows; "
                f"{summary['parameter_waiting_for_fresh_refresh_count']} waiting for fresh refresh; "
                f"{summary['parameter_shadow_review_candidate_count']} shadow-review candidates."
            ),
            next_action="Re-run the activation gate after a fresh M12.47-owned refresh; only passed rows may enter manual shadow review.",
            strategy_ids=unique_nonempty(row["strategy_id"] for row in parameter_rows),
            runtime_ids=flatten_runtime_ids(parameter_rows),
            blocked_by=["m12_47_fresh_refresh_not_observed"]
            if not summary["fresh_refresh_observed"]
            else [],
            requires_m12_47_fresh_refresh=not summary["fresh_refresh_observed"],
            next_verification_artifacts=[
                "m14_rescue_parameter_activation_gate",
                "m14_rescue_post_refresh_outcome_review",
            ],
            success_condition="Fresh evidence opens shadow-review candidates while implementation and parameter mutation stay disabled.",
        ),
        execution_action(
            action_id="broker_dry_run_watch_only",
            priority="P0",
            action_state="guardrail_watch_only",
            execution_gate="guardrail_monitor_only",
            requirement_ids=["broker_live_real_order_disabled", "real_simulated_account_test_not_broker_live"],
            evidence=(
                f"Broker dry-run ready/blocked rows are "
                f"{summary['broker_dry_run_ready_count']}/{summary['broker_dry_run_blocked_count']}; "
                f"broker_or_live_enabled={summary['broker_or_live_enabled']}."
            ),
            next_action="Keep broker readiness dry-run preview only and treat blockers as internal simulation diagnostics.",
            strategy_ids=summary["broker_watch_strategy_ids"],
            runtime_ids=[],
            blocked_by=[] if not summary["broker_or_live_enabled"] else ["broker_or_live_boundary_regression"],
            requires_m12_47_fresh_refresh=False,
            next_verification_artifacts=["m14_2_broker_readiness_plan", "m14_objective_completion_audit"],
            success_condition="Broker/live flags remain false while blocker fixes are evaluated only in internal simulation.",
        ),
        execution_action(
            action_id="external_reference_review_lanes",
            priority="P1",
            action_state="review_only_available_now",
            execution_gate="review_only_no_local_gate_override",
            requirement_ids=["external_project_reference_mapped"],
            evidence=(
                f"{summary['external_reference_project_count']} external projects mapped to "
                f"{summary['external_reference_mapped_rescue_row_count']} rescue rows and "
                f"{summary['external_reference_broker_blocker_row_count']} broker-blocker rows."
            ),
            next_action="Use external references only for local shadow review lanes and decision-log hygiene.",
            strategy_ids=[],
            runtime_ids=[],
            blocked_by=[] if not summary["external_reference_copy_trading_allowed"] else ["copy_trading_boundary"],
            requires_m12_47_fresh_refresh=False,
            next_verification_artifacts=["m14_rescue_external_reference_map"],
            success_condition="External patterns improve local review checklists without overriding M13/M14 gates.",
        ),
        execution_action(
            action_id="objective_completion_recheck",
            priority="P1",
            action_state="blocked_or_in_progress",
            execution_gate="audit_recheck_after_evidence_updates",
            requirement_ids=["objective_complete"],
            evidence=(
                f"Objective complete={summary['objective_complete']}; blockers={summary['objective_blockers']}."
            ),
            next_action="Regenerate objective audit after fresh-refresh, rescue evidence, and parameter activation artifacts update.",
            strategy_ids=[],
            runtime_ids=[],
            blocked_by=list(summary["objective_blockers"]),
            requires_m12_47_fresh_refresh=True,
            next_verification_artifacts=["m14_objective_completion_audit", "m14_project_stage_assessment"],
            success_condition="Objective audit has no blocked or in-progress requirements and all guardrails remain intact.",
        ),
    ]


def execution_action(
    *,
    action_id: str,
    priority: str,
    action_state: str,
    execution_gate: str,
    requirement_ids: list[str],
    evidence: str,
    next_action: str,
    strategy_ids: list[str],
    runtime_ids: list[str],
    blocked_by: list[str],
    requires_m12_47_fresh_refresh: bool,
    next_verification_artifacts: list[str],
    success_condition: str,
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "priority": priority,
        "action_state": action_state,
        "execution_gate": execution_gate,
        "requirement_ids": requirement_ids,
        "evidence": evidence,
        "next_action": next_action,
        "strategy_ids": strategy_ids,
        "runtime_ids": runtime_ids,
        "blocked_by": blocked_by,
        "requires_m12_47_fresh_refresh": requires_m12_47_fresh_refresh,
        "manual_execution_allowed": False,
        "allowed_operations": ["artifact_review", "m12_47_supervised_refresh_review"],
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
        "next_verification_artifacts": next_verification_artifacts,
        "success_condition": success_condition,
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
    return (
        f"Objective execution plan has {summary['execution_action_count']} actions, "
        f"including {summary['p0_action_count']} P0 actions. "
        f"{summary['waiting_for_fresh_refresh_action_count']} actions still require an M12.47-owned fresh refresh. "
        f"Approved internal sim is ready for {summary['approved_internal_sim_strategy_count']} strategies; "
        f"rescue evidence remains {summary['rescue_m13_ledger_observed_strategy_count']}/"
        f"{summary['rescue_runtime_strategy_count']} observed with "
        f"{summary['rescue_no_m13_ledger_evidence_count']} first-ledger waits. "
        f"Parameter activation has {summary['parameter_shadow_review_candidate_count']} shadow-review candidates "
        f"and {summary['parameter_waiting_for_fresh_refresh_count']} rows waiting for fresh evidence. "
        "Manual M12.37 once-mode, broker/live, real orders, paper approval, registry/account-spec mutation, "
        "broker readiness mutation, and parameter mutation remain disabled."
    )


def build_execution_plan_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Objective Execution Plan",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Objective complete: `{summary['objective_complete']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Execution actions: `{summary['execution_action_count']}`",
        f"- P0 actions: `{summary['p0_action_count']}`",
        f"- Actions requiring M12.47 fresh refresh: `{summary['waiting_for_fresh_refresh_action_count']}`",
        f"- Rescue evidence observed: `{summary['rescue_m13_ledger_observed_strategy_count']}/{summary['rescue_runtime_strategy_count']}`",
        f"- Rescue no-ledger waits: `{summary['rescue_no_m13_ledger_evidence_count']}`",
        f"- Parameter shadow-review candidates: `{summary['parameter_shadow_review_candidate_count']}`",
        f"- Manual execution allowed count: `{summary['manual_execution_allowed_count']}`",
        "- Boundary: internal simulated accounts only; no broker connection, no real orders, no live execution.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Execution Actions",
        "",
    ]
    for row in payload["execution_actions"]:
        lines.extend(
            [
                f"### {row['action_id']}",
                "",
                f"- Priority: `{row['priority']}`",
                f"- State: `{row['action_state']}`",
                f"- Gate: `{row['execution_gate']}`",
                f"- Requires M12.47 fresh refresh: `{row['requires_m12_47_fresh_refresh']}`",
                f"- Evidence: {row['evidence']}",
                f"- Blocked by: `{', '.join(row['blocked_by']) or 'none'}`",
                f"- Next action: {row['next_action']}",
                f"- Success condition: {row['success_condition']}",
                "",
            ]
        )
    lines.extend(["## Rescue Strategy Rows", ""])
    for row in payload["rescue_strategy_rows"]:
        lines.extend(
            [
                f"- `{row['strategy_id']}`: `{row['execution_state']}`, "
                f"observed `{row['observed_trading_days_count']}/{row['required_ab_trading_days']}`, "
                f"remaining `{row['remaining_ab_trading_days']}`",
            ]
        )
    lines.extend(["", "## Parameter Gate Digest", ""])
    for row in payload["parameter_gate_digest_rows"]:
        lines.append(
            f"- `{row['strategy_id']}` `{row['experiment_family']}`: `{row['execution_state']}`"
        )
    lines.append("")
    return "\n".join(lines)


def runtime_ids_for_strategies(rows: list[dict[str, Any]], strategy_ids: list[str]) -> list[str]:
    selected = []
    strategy_id_set = set(strategy_ids)
    for row in rows:
        if row["strategy_id"] in strategy_id_set:
            selected.extend(row["runtime_ids"])
    return unique_nonempty(selected)


def flatten_runtime_ids(rows: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in rows:
        values.extend(row.get("runtime_ids", []))
    return unique_nonempty(values)


def unique_nonempty(values: Any) -> list[str]:
    output = []
    seen = set()
    for value in values:
        text = str(value)
        if text and text not in seen:
            output.append(text)
            seen.add(text)
    return output


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
