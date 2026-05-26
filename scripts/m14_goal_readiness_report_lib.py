#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_goal_readiness_report.json"


@dataclass(frozen=True, slots=True)
class GoalReadinessConfig:
    stage: str
    project_stage_label: str
    m14_summary_path: Path
    paper_gate_path: Path
    rescue_plan_path: Path
    rescue_coverage_path: Path
    rescue_ab_evidence_path: Path
    rescue_optimization_backlog_path: Path
    rescue_zero_signal_diagnostics_path: Path
    rescue_target_stop_diagnostics_path: Path
    rescue_target_stop_shadow_normalization_path: Path
    broker_readiness_path: Path
    broker_blocker_shadow_repair_path: Path
    readiness_json_path: Path
    readiness_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> GoalReadinessConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = GoalReadinessConfig(
        stage=str(payload["stage"]),
        project_stage_label=str(payload["project_stage_label"]),
        m14_summary_path=resolve_repo_path(inputs["m14_summary"]),
        paper_gate_path=resolve_repo_path(inputs["m14_paper_trial_gate"]),
        rescue_plan_path=resolve_repo_path(inputs["m14_strategy_rescue_plan"]),
        rescue_coverage_path=resolve_repo_path(inputs["m14_rescue_runtime_coverage"]),
        rescue_ab_evidence_path=resolve_repo_path(inputs["m14_rescue_ab_evidence_tracker"]),
        rescue_optimization_backlog_path=resolve_repo_path(inputs["m14_rescue_optimization_backlog"]),
        rescue_zero_signal_diagnostics_path=resolve_repo_path(inputs["m14_rescue_zero_signal_diagnostics"]),
        rescue_target_stop_diagnostics_path=resolve_repo_path(inputs["m14_rescue_target_stop_diagnostics"]),
        rescue_target_stop_shadow_normalization_path=resolve_repo_path(
            inputs["m14_rescue_target_stop_shadow_normalization"]
        ),
        broker_readiness_path=resolve_repo_path(inputs["m14_2_broker_readiness_plan"]),
        broker_blocker_shadow_repair_path=resolve_repo_path(inputs["m14_2_broker_blocker_shadow_repair"]),
        readiness_json_path=resolve_repo_path(outputs["readiness_json"]),
        readiness_md_path=resolve_repo_path(outputs["readiness_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: GoalReadinessConfig) -> None:
    if config.stage != "M14.goal_readiness_report":
        raise ValueError("M14 goal readiness stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 goal readiness must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 goal readiness must keep internal simulated account enabled")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 goal readiness cannot enable {key}")


def run_m14_goal_readiness_report(
    config: GoalReadinessConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary = read_json(config.m14_summary_path)
    paper_gate = read_json(config.paper_gate_path)
    rescue_plan = read_json(config.rescue_plan_path)
    rescue_coverage = read_json(config.rescue_coverage_path)
    rescue_ab_evidence = read_json(config.rescue_ab_evidence_path)
    rescue_optimization_backlog = read_json(config.rescue_optimization_backlog_path)
    rescue_zero_signal_diagnostics = read_json(config.rescue_zero_signal_diagnostics_path)
    rescue_target_stop_diagnostics = read_json(config.rescue_target_stop_diagnostics_path)
    rescue_target_stop_shadow_normalization = read_json(config.rescue_target_stop_shadow_normalization_path)
    broker_readiness = read_json(config.broker_readiness_path)
    broker_blocker_shadow_repair = read_json(config.broker_blocker_shadow_repair_path)

    gate_rows = list(paper_gate.get("rows", []))
    approved_ids = tuple(str(item) for item in paper_gate.get("approved_internal_sim_strategy_ids", []))
    gate_counts = dict(sorted(Counter(str(row.get("paper_trial_gate", "")) for row in gate_rows).items()))
    ten_day_complete = (
        int_or_zero(summary.get("effective_challenge_trading_days")) >= int_or_zero(summary.get("required_challenge_trading_days"))
        and str(summary.get("challenge_progress_label", "")) == "10/10"
    )
    boundaries = build_boundaries(
        summary,
        paper_gate,
        rescue_coverage,
        rescue_ab_evidence,
        rescue_optimization_backlog,
        rescue_zero_signal_diagnostics,
        rescue_target_stop_diagnostics,
        rescue_target_stop_shadow_normalization,
        broker_readiness,
        broker_blocker_shadow_repair,
    )
    boundaries_ok = all(boundaries.values())
    internal_sim_ready = bool(ten_day_complete and approved_ids and boundaries_ok)
    rescue_ready = bool(
        rescue_coverage.get("all_registered_rescue_inputs_connected")
        and rescue_coverage.get("all_planned_rescue_actions_have_runtime_coverage")
    )

    payload: dict[str, Any] = {
        "schema_version": "m14.goal-readiness-report.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "project_stage_label": config.project_stage_label,
        "m14_stage": str(summary.get("stage", "")),
        "m14_trading_date": str(summary.get("trading_date", "")),
        "input_refs": {
            "m14_summary": project_path(config.m14_summary_path),
            "m14_paper_trial_gate": project_path(config.paper_gate_path),
            "m14_strategy_rescue_plan": project_path(config.rescue_plan_path),
            "m14_rescue_runtime_coverage": project_path(config.rescue_coverage_path),
            "m14_rescue_ab_evidence_tracker": project_path(config.rescue_ab_evidence_path),
            "m14_rescue_optimization_backlog": project_path(config.rescue_optimization_backlog_path),
            "m14_rescue_zero_signal_diagnostics": project_path(config.rescue_zero_signal_diagnostics_path),
            "m14_rescue_target_stop_diagnostics": project_path(config.rescue_target_stop_diagnostics_path),
            "m14_rescue_target_stop_shadow_normalization": project_path(
                config.rescue_target_stop_shadow_normalization_path
            ),
            "m14_2_broker_readiness_plan": project_path(config.broker_readiness_path),
            "m14_2_broker_blocker_shadow_repair": project_path(config.broker_blocker_shadow_repair_path),
        },
        "challenge": {
            "challenge_progress_label": str(summary.get("challenge_progress_label", "")),
            "effective_challenge_trading_days": int_or_zero(summary.get("effective_challenge_trading_days")),
            "required_challenge_trading_days": int_or_zero(summary.get("required_challenge_trading_days")),
            "ten_day_challenge_complete": ten_day_complete,
            "data_quality_state": str(summary.get("data_quality_state", "")),
            "recompute_only": bool(summary.get("recompute_only", False)),
            "m12_current_day_runtime_ready": bool(summary.get("m12_current_day_runtime_ready", False)),
        },
        "internal_simulation_gate": {
            "can_enter_internal_simulation_for_approved_strategies": internal_sim_ready,
            "approved_internal_sim_strategy_ids": list(approved_ids),
            "approved_internal_sim_strategy_count": len(approved_ids),
            "gate_scope": str(paper_gate.get("gate_scope", "")),
            "gate_counts": gate_counts,
        },
        "rescue_status": {
            "rescue_runtime_connected_strategy_count": int_or_zero(rescue_coverage.get("connected_rescue_strategy_count")),
            "registered_rescue_strategy_count": int_or_zero(rescue_coverage.get("registered_rescue_strategy_count")),
            "registered_rescue_account_count": int_or_zero(rescue_coverage.get("registered_rescue_account_count")),
            "planned_action_covered_count": int_or_zero(rescue_coverage.get("planned_action_covered_count")),
            "planned_action_row_count": int_or_zero(rescue_coverage.get("planned_action_row_count")),
            "all_registered_rescue_inputs_connected": bool(rescue_coverage.get("all_registered_rescue_inputs_connected")),
            "all_planned_rescue_actions_have_runtime_coverage": bool(rescue_coverage.get("all_planned_rescue_actions_have_runtime_coverage")),
            "rescue_ready_for_ab_evidence_collection": rescue_ready,
            "pending_rescue_strategy_ids": list(rescue_coverage.get("pending_rescue_strategy_ids", [])),
            "pending_planned_action_strategy_ids": list(rescue_coverage.get("pending_planned_action_strategy_ids", [])),
            "next_required_evidence": str(rescue_coverage.get("next_required_evidence", "")),
        },
        "rescue_ab_evidence": build_rescue_ab_evidence_summary(rescue_ab_evidence),
        "rescue_optimization_backlog": build_rescue_optimization_backlog_summary(rescue_optimization_backlog),
        "rescue_zero_signal_diagnostics": build_rescue_zero_signal_diagnostics_summary(rescue_zero_signal_diagnostics),
        "rescue_target_stop_diagnostics": build_rescue_target_stop_diagnostics_summary(rescue_target_stop_diagnostics),
        "rescue_target_stop_shadow_normalization": build_rescue_target_stop_shadow_normalization_summary(
            rescue_target_stop_shadow_normalization
        ),
        "broker_readiness": {
            "mode": str(broker_readiness.get("mode", "")),
            "dry_run_ready_count": int_or_zero(broker_readiness.get("dry_run_ready_count")),
            "blocked_count": int_or_zero(broker_readiness.get("blocked_count")),
            "source_risk_check_count": int_or_zero(broker_readiness.get("source_risk_check_count")),
            "broker_connection_enabled": bool(broker_readiness.get("broker_connection_enabled", False)),
            "real_order_enabled": bool(broker_readiness.get("real_order_enabled", False)),
            "live_execution_enabled": bool(broker_readiness.get("live_execution_enabled", False)),
            "paper_trading_approval": bool(broker_readiness.get("paper_trading_approval", False)),
            "dry_run_only_not_broker_paper": True,
        },
        "broker_blocker_shadow_repair": build_broker_blocker_shadow_repair_summary(broker_blocker_shadow_repair),
        "execution_boundaries": boundaries,
        "strategy_action_matrix": build_strategy_action_matrix(gate_rows, rescue_coverage),
        "external_reference_policy": {
            "references": list(rescue_plan.get("external_references", [])),
            "allowed_use": "architecture inspiration, shadow diagnostics, and local A/B rescue design only",
            "forbidden_use": "copy-trading, direct execution, or bypassing local M13/M14 ledgers and risk gates",
        },
        "goal_completion_assessment": {
            "goal_complete": False,
            "reason": (
                "The 10-day challenge is complete and approved strategies can continue internal simulation, "
                "but rescue variants still need their own 10 trading-day A/B evidence before final promote/modify/reject."
            ),
        },
    }
    payload["next_actions"] = build_next_actions(payload)
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.readiness_json_path, payload)
    config.readiness_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.readiness_md_path.write_text(build_readiness_md(payload), encoding="utf-8")
    return payload


def build_boundaries(
    summary: dict[str, Any],
    paper_gate: dict[str, Any],
    rescue_coverage: dict[str, Any],
    rescue_ab_evidence: dict[str, Any],
    rescue_optimization_backlog: dict[str, Any],
    rescue_zero_signal_diagnostics: dict[str, Any],
    rescue_target_stop_diagnostics: dict[str, Any],
    rescue_target_stop_shadow_normalization: dict[str, Any],
    broker_readiness: dict[str, Any],
    broker_blocker_shadow_repair: dict[str, Any],
) -> dict[str, bool]:
    return {
        "paper_simulated_only": all(
            boundary_flag(item, "paper_simulated_only")
            for item in (
                summary,
                paper_gate,
                rescue_coverage,
                rescue_ab_evidence,
                rescue_optimization_backlog,
                rescue_zero_signal_diagnostics,
                rescue_target_stop_diagnostics,
                rescue_target_stop_shadow_normalization,
                broker_blocker_shadow_repair,
            )
        ),
        "internal_simulated_account": bool(summary.get("internal_simulated_account")) and bool(paper_gate.get("internal_simulated_account")),
        "broker_connection_disabled": not any(
            bool(item.get("broker_connection", item.get("broker_paper_connection", item.get("broker_connection_enabled", False))))
            for item in (
                summary,
                paper_gate,
                rescue_coverage,
                rescue_ab_evidence,
                rescue_optimization_backlog,
                rescue_zero_signal_diagnostics,
                rescue_target_stop_diagnostics,
                rescue_target_stop_shadow_normalization,
                broker_readiness,
                broker_blocker_shadow_repair,
            )
        ),
        "real_order_disabled": (
            not bool(broker_readiness.get("real_order_enabled", False))
            and not bool(rescue_coverage.get("real_order", False))
            and not bool(rescue_ab_evidence.get("real_order", False))
            and not bool(rescue_optimization_backlog.get("real_order", False))
            and not bool(rescue_zero_signal_diagnostics.get("real_order", False))
            and not bool(rescue_target_stop_diagnostics.get("real_order", False))
            and not bool(rescue_target_stop_shadow_normalization.get("real_order", False))
            and not bool(broker_blocker_shadow_repair.get("real_order", False))
        ),
        "live_execution_disabled": not any(
            bool(item.get("live_execution", item.get("live_execution_enabled", False)))
            for item in (
                summary,
                paper_gate,
                rescue_coverage,
                rescue_ab_evidence,
                rescue_optimization_backlog,
                rescue_zero_signal_diagnostics,
                rescue_target_stop_diagnostics,
                rescue_target_stop_shadow_normalization,
                broker_readiness,
                broker_blocker_shadow_repair,
            )
        ),
        "paper_trading_approval_disabled": not any(
            bool(item.get("paper_trading_approval", False))
            for item in (
                summary,
                paper_gate,
                rescue_coverage,
                rescue_ab_evidence,
                rescue_optimization_backlog,
                rescue_zero_signal_diagnostics,
                rescue_target_stop_diagnostics,
                rescue_target_stop_shadow_normalization,
                broker_readiness,
                broker_blocker_shadow_repair,
            )
        ),
    }


def build_rescue_ab_evidence_summary(rescue_ab_evidence: dict[str, Any]) -> dict[str, Any]:
    summary = rescue_ab_evidence.get("summary", {})
    return {
        "min_ab_trading_days": int_or_zero(rescue_ab_evidence.get("min_ab_trading_days")),
        "rescue_runtime_strategy_count": int_or_zero(summary.get("rescue_runtime_strategy_count")),
        "m13_ledger_observed_strategy_count": int_or_zero(summary.get("m13_ledger_observed_strategy_count")),
        "collecting_evidence_count": int_or_zero(summary.get("collecting_evidence_count")),
        "evidence_ready_for_manual_review_count": int_or_zero(summary.get("evidence_ready_for_manual_review_count")),
        "no_m13_ledger_evidence_count": int_or_zero(summary.get("no_m13_ledger_evidence_count")),
        "promotion_allowed_count": int_or_zero(summary.get("promotion_allowed_count")),
        "pending_evidence_strategy_ids": list(summary.get("pending_evidence_strategy_ids", [])),
        "no_m13_ledger_evidence_strategy_ids": list(summary.get("no_m13_ledger_evidence_strategy_ids", [])),
        "evidence_ready_for_manual_review_strategy_ids": list(summary.get("evidence_ready_for_manual_review_strategy_ids", [])),
        "plain_language_result": str(rescue_ab_evidence.get("plain_language_result", "")),
    }


def build_rescue_optimization_backlog_summary(backlog: dict[str, Any]) -> dict[str, Any]:
    summary = backlog.get("summary", {})
    return {
        "rescue_strategy_count": int_or_zero(summary.get("rescue_strategy_count")),
        "actionable_before_10d_count": int_or_zero(summary.get("actionable_before_10d_count")),
        "wait_for_more_ab_evidence_count": int_or_zero(summary.get("wait_for_more_ab_evidence_count")),
        "zero_signal_after_connection_count": int_or_zero(summary.get("zero_signal_after_connection_count")),
        "signal_generated_no_account_operation_count": int_or_zero(
            summary.get("signal_generated_no_account_operation_count")
        ),
        "broker_dry_run_blocked_count": int_or_zero(summary.get("broker_dry_run_blocked_count")),
        "broker_blocker_strategy_count": int_or_zero(summary.get("broker_blocker_strategy_count")),
        "high_priority_strategy_ids": list(summary.get("high_priority_strategy_ids", [])),
        "broker_blocker_reason_counts": dict(summary.get("broker_blocker_reason_counts", {})),
        "plain_language_result": str(backlog.get("plain_language_result", "")),
    }


def build_rescue_zero_signal_diagnostics_summary(diagnostics: dict[str, Any]) -> dict[str, Any]:
    summary = diagnostics.get("summary", {})
    return {
        "zero_signal_runtime_count": int_or_zero(summary.get("zero_signal_runtime_count")),
        "zero_signal_strategy_count": int_or_zero(summary.get("zero_signal_strategy_count")),
        "parent_source_available_runtime_count": int_or_zero(summary.get("parent_source_available_runtime_count")),
        "parent_source_absent_runtime_count": int_or_zero(summary.get("parent_source_absent_runtime_count")),
        "parent_detector_zero_signal_runtime_count": int_or_zero(summary.get("parent_detector_zero_signal_runtime_count")),
        "quote_refresh_candidate_runtime_count": int_or_zero(summary.get("quote_refresh_candidate_runtime_count")),
        "quality_filter_blocked_runtime_count": int_or_zero(summary.get("quality_filter_blocked_runtime_count")),
        "potential_signal_if_fresh_quote_count": int_or_zero(summary.get("potential_signal_if_fresh_quote_count")),
        "shadow_reward_min_r_pass_counts": dict(summary.get("shadow_reward_min_r_pass_counts", {})),
        "dominant_issue_counts": dict(summary.get("dominant_issue_counts", {})),
        "rejection_reason_counts": dict(summary.get("rejection_reason_counts", {})),
        "plain_language_result": str(diagnostics.get("plain_language_result", "")),
    }


def build_rescue_target_stop_diagnostics_summary(diagnostics: dict[str, Any]) -> dict[str, Any]:
    summary = diagnostics.get("summary", {})
    return {
        "diagnosed_runtime_count": int_or_zero(summary.get("diagnosed_runtime_count")),
        "target_stop_issue_runtime_count": int_or_zero(summary.get("target_stop_issue_runtime_count")),
        "shadow_candidate_runtime_count": int_or_zero(summary.get("shadow_candidate_runtime_count")),
        "reward_ge_1_0_runtime_count": int_or_zero(summary.get("reward_ge_1_0_runtime_count")),
        "reward_ge_1_1_runtime_count": int_or_zero(summary.get("reward_ge_1_1_runtime_count")),
        "reward_ge_1_2_runtime_count": int_or_zero(summary.get("reward_ge_1_2_runtime_count")),
        "runtime_ids": list(summary.get("runtime_ids", [])),
        "strategy_ids": list(summary.get("strategy_ids", [])),
        "parent_strategy_ids": list(summary.get("parent_strategy_ids", [])),
        "dominant_target_stop_issue_counts": dict(summary.get("dominant_target_stop_issue_counts", {})),
        "plain_language_result": str(diagnostics.get("plain_language_result", "")),
    }


def build_rescue_target_stop_shadow_normalization_summary(normalization: dict[str, Any]) -> dict[str, Any]:
    summary = normalization.get("summary", {})
    return {
        "diagnosed_runtime_count": int_or_zero(summary.get("diagnosed_runtime_count")),
        "runtime_with_shadow_candidate_count": int_or_zero(summary.get("runtime_with_shadow_candidate_count")),
        "runtime_without_shadow_candidate_count": int_or_zero(summary.get("runtime_without_shadow_candidate_count")),
        "source_candidate_row_count": int_or_zero(summary.get("source_candidate_row_count")),
        "best_variant_candidate_row_count": int_or_zero(summary.get("best_variant_candidate_row_count")),
        "best_variant_id_counts": dict(summary.get("best_variant_id_counts", {})),
        "runtime_ids": list(summary.get("runtime_ids", [])),
        "strategy_ids": list(summary.get("strategy_ids", [])),
        "parent_strategy_ids": list(summary.get("parent_strategy_ids", [])),
        "opening_range_minutes": int_or_zero(summary.get("opening_range_minutes")),
        "plain_language_result": str(normalization.get("plain_language_result", "")),
    }


def build_broker_blocker_shadow_repair_summary(shadow_repair: dict[str, Any]) -> dict[str, Any]:
    summary = shadow_repair.get("summary", {})
    return {
        "source_blocked_rows": int_or_zero(summary.get("source_blocked_rows")),
        "shadow_rows": int_or_zero(summary.get("shadow_rows")),
        "strategy_count": int_or_zero(summary.get("strategy_count")),
        "risk_cap_candidate_count": int_or_zero(summary.get("risk_cap_candidate_count")),
        "defer_for_exposure_count": int_or_zero(summary.get("defer_for_exposure_count")),
        "cooldown_defer_count": int_or_zero(summary.get("cooldown_defer_count")),
        "would_change_original_readiness_count": int_or_zero(summary.get("would_change_original_readiness_count")),
        "broker_or_live_enabled": bool(summary.get("broker_or_live_enabled", False)),
        "shadow_action_counts": dict(summary.get("shadow_action_counts", {})),
        "shadow_status_counts": dict(summary.get("shadow_status_counts", {})),
        "readiness_status_mutation": bool(shadow_repair.get("readiness_status_mutation", False)),
        "plain_language_result": str(shadow_repair.get("plain_language_result", "")),
    }


def build_strategy_action_matrix(
    gate_rows: list[dict[str, Any]],
    rescue_coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    rescue_by_parent = {
        str(row.get("strategy_id", "")): row
        for row in rescue_coverage.get("planned_action_rows", [])
        if row.get("strategy_id")
    }
    matrix: list[dict[str, Any]] = []
    for row in gate_rows:
        strategy_id = str(row.get("strategy_id", ""))
        gate = str(row.get("paper_trial_gate", ""))
        rescue_row = rescue_by_parent.get(strategy_id, {})
        action = action_for_gate(gate, str(row.get("decision", "")), bool(rescue_row))
        matrix.append(
            {
                "strategy_id": strategy_id,
                "display_name": str(row.get("display_name", "")),
                "completed_trading_days": int_or_zero(row.get("completed_trading_days")),
                "decision": str(row.get("decision", "")),
                "decision_reason": str(row.get("decision_reason", "")),
                "paper_trial_gate": gate,
                "next_action_category": action,
                "runtime_ids": list(row.get("runtime_ids", [])),
                "rescue_coverage_status": str(rescue_row.get("coverage_status", "")),
                "rescue_runtime_strategy_ids": list(rescue_row.get("coverage_strategy_ids", [])),
                "requires_10_day_ab_evidence": action in {"collect_rescue_ab_evidence", "continue_parallel_ab_evidence", "rebuild_detector_ab_evidence"},
                "can_enter_internal_simulation": gate == "approved_internal_sim_only",
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return matrix


def action_for_gate(gate: str, decision: str, has_rescue_coverage: bool) -> str:
    if gate == "approved_internal_sim_only":
        return "continue_internal_simulation"
    if gate == "not_approved_modify_candidate":
        return "collect_rescue_ab_evidence" if has_rescue_coverage else "create_rescue_runtime"
    if gate == "not_approved_parallel_modify_testing":
        return "continue_parallel_ab_evidence"
    if gate == "not_approved_rejected":
        return "rebuild_detector_ab_evidence" if has_rescue_coverage else "final_reject_review"
    if decision == "continue_testing":
        return "continue_shadow_or_plugin_review"
    return "hold_until_gate_evidence"


def build_next_actions(payload: dict[str, Any]) -> list[dict[str, str]]:
    actions = [
        {
            "priority": "P0",
            "action": "Run approved strategies in internal simulated-account testing only",
            "evidence": ", ".join(payload["internal_simulation_gate"]["approved_internal_sim_strategy_ids"]) or "none",
            "boundary": "No broker connection, no real order, no live execution.",
        },
        {
            "priority": "P0",
            "action": "Collect 10 trading-day A/B evidence for connected rescue runtimes",
            "evidence": (
                f"{payload['rescue_ab_evidence']['m13_ledger_observed_strategy_count']}/"
                f"{payload['rescue_ab_evidence']['rescue_runtime_strategy_count']} rescue strategies have M13 ledger evidence; "
                f"{payload['rescue_ab_evidence']['evidence_ready_for_manual_review_count']} ready for manual review"
            ),
            "boundary": "Connected rescue runtime is not a promotion or approval.",
        },
        {
            "priority": "P1",
            "action": "Keep M14.2 broker readiness in dry-run preview mode",
            "evidence": (
                f"{payload['broker_readiness']['dry_run_ready_count']} dry-run ready, "
                f"{payload['broker_readiness']['blocked_count']} blocked"
            ),
            "boundary": "Manual user approval is still required before any broker paper/live path.",
        },
    ]
    backlog = payload.get("rescue_optimization_backlog", {})
    if int_or_zero(backlog.get("actionable_before_10d_count")):
        actions.insert(
            2,
            {
                "priority": "P0",
                "action": "Work the rescue optimization backlog before the 10-day A/B window completes",
                "evidence": (
                    f"{backlog['actionable_before_10d_count']} actionable; "
                    f"{backlog['zero_signal_after_connection_count']} zero-signal connected variants; "
                    f"{backlog['signal_generated_no_account_operation_count']} signal-to-account no-op variants"
                ),
                "boundary": "Optimization backlog cannot change broker/live approval or count as promotion evidence.",
            },
        )
    diagnostics = payload.get("rescue_zero_signal_diagnostics", {})
    if int_or_zero(diagnostics.get("zero_signal_runtime_count")):
        actions.insert(
            3,
            {
                "priority": "P0",
                "action": "Use zero-signal diagnostics before changing rescue parameters",
                "evidence": (
                    f"{diagnostics['quote_refresh_candidate_runtime_count']} quote-refresh candidates; "
                    f"{diagnostics['quality_filter_blocked_runtime_count']} quality/filter candidates; "
                    f"{diagnostics['parent_source_absent_runtime_count']} source-mapping candidates; "
                    f"{diagnostics['parent_detector_zero_signal_runtime_count']} parent-detector zero-signal candidates"
                ),
                "boundary": "Fresh-data rerun and shadow parameter tests only; no broker/live approval.",
            },
        )
    target_stop = payload.get("rescue_target_stop_diagnostics", {})
    if int_or_zero(target_stop.get("target_stop_issue_runtime_count")):
        actions.insert(
            4,
            {
                "priority": "P0",
                "action": "Use PA012 target/stop diagnostics before changing rescue runtime thresholds",
                "evidence": (
                    f"{target_stop['target_stop_issue_runtime_count']} target/stop issue runtimes; "
                    f"issue counts {target_stop['dominant_target_stop_issue_counts']}"
                ),
                "boundary": "Target/stop fixes stay shadow-only until 10 trading-day A/B evidence exists.",
            },
        )
    shadow_normalization = payload.get("rescue_target_stop_shadow_normalization", {})
    if int_or_zero(shadow_normalization.get("runtime_with_shadow_candidate_count")):
        actions.insert(
            5,
            {
                "priority": "P0",
                "action": "Collect first fresh M13 ledger row for the PA012 target/stop normalized shadow runtime",
                "evidence": (
                    f"{shadow_normalization['best_variant_candidate_row_count']}/"
                    f"{shadow_normalization['source_candidate_row_count']} eligible rows pass the best shadow variant; "
                    f"best variants {shadow_normalization['best_variant_id_counts']}"
                ),
                "boundary": "Connected shadow runtime is still simulated-only and requires 10 rescue A/B trading days before review.",
            },
        )
    shadow_repair = payload.get("broker_blocker_shadow_repair", {})
    if int_or_zero(shadow_repair.get("shadow_rows")):
        actions.insert(
            6,
            {
                "priority": "P0",
                "action": "Apply broker-blocker shadow repair plan only as internal simulated A/B prep",
                "evidence": (
                    f"{shadow_repair['risk_cap_candidate_count']} quantity-cap candidate; "
                    f"{shadow_repair['defer_for_exposure_count']} exposure deferrals; "
                    f"{shadow_repair['cooldown_defer_count']} cooldown halts"
                ),
                "boundary": "Original broker readiness rows remain blocked; no broker/live approval or readiness mutation.",
            },
        )
    if not payload["challenge"]["m12_current_day_runtime_ready"]:
        actions.append(
            {
                "priority": "P1",
                "action": "Treat the current artifact set as a recompute/audit snapshot until the next trading session refresh",
                "evidence": str(payload["challenge"]["data_quality_state"]),
                "boundary": "Do not manually run M12.37 once-mode; M12.47 owns session launch.",
            }
        )
    return actions


def build_plain_language_result(payload: dict[str, Any]) -> str:
    approved = payload["internal_simulation_gate"]["approved_internal_sim_strategy_ids"]
    rescue = payload["rescue_status"]
    rescue_ab = payload["rescue_ab_evidence"]
    backlog = payload["rescue_optimization_backlog"]
    diagnostics = payload["rescue_zero_signal_diagnostics"]
    target_stop = payload["rescue_target_stop_diagnostics"]
    shadow_normalization = payload["rescue_target_stop_shadow_normalization"]
    broker = payload["broker_readiness"]
    shadow_repair = payload["broker_blocker_shadow_repair"]
    return (
        f"Project is at {payload['project_stage_label']}. "
        f"10-day challenge complete: {payload['challenge']['challenge_progress_label']}. "
        f"{len(approved)} strategies can continue internal simulated-account testing only: {', '.join(approved) or 'none'}. "
        f"Rescue coverage is {rescue['rescue_runtime_connected_strategy_count']}/{rescue['registered_rescue_strategy_count']} strategies "
        f"and {rescue['planned_action_covered_count']}/{rescue['planned_action_row_count']} planned actions. "
        f"Rescue A/B evidence is now {rescue_ab['m13_ledger_observed_strategy_count']}/{rescue_ab['rescue_runtime_strategy_count']} strategies observed, "
        f"{rescue_ab['evidence_ready_for_manual_review_count']} ready for manual review, "
        f"promotion allowed {rescue_ab['promotion_allowed_count']}. "
        f"Pre-10-day optimization backlog has {backlog['actionable_before_10d_count']} actionable items: "
        f"{backlog['zero_signal_after_connection_count']} zero-signal and "
        f"{backlog['signal_generated_no_account_operation_count']} signal-to-account no-op. "
        f"Zero-signal diagnosis: {diagnostics['quote_refresh_candidate_runtime_count']} should be rechecked after fresh quote refresh, "
        f"{diagnostics['quality_filter_blocked_runtime_count']} need filter/parameter work, "
        f"{diagnostics['parent_source_absent_runtime_count']} need source mapping, "
        f"{diagnostics['parent_detector_zero_signal_runtime_count']} should keep same-timeframe mapping and wait for parent detector evidence. "
        f"Target/stop diagnosis reviewed {target_stop['diagnosed_runtime_count']} reward/R runtimes, "
        f"with {target_stop['target_stop_issue_runtime_count']} still needing target/stop geometry work before threshold changes. "
        f"Target/stop shadow normalization has {shadow_normalization['runtime_with_shadow_candidate_count']} candidate runtimes "
        f"and {shadow_normalization['best_variant_candidate_row_count']}/{shadow_normalization['source_candidate_row_count']} eligible rows passing the best shadow variant. "
        f"Broker blocker shadow repair has {shadow_repair['risk_cap_candidate_count']} quantity-cap candidate, "
        f"{shadow_repair['defer_for_exposure_count']} exposure deferrals, and {shadow_repair['cooldown_defer_count']} cooldown halts. "
        f"Broker readiness remains {broker['mode']}: {broker['dry_run_ready_count']} dry-run ready, {broker['blocked_count']} blocked; no broker/live/real order approval."
    )


def build_readiness_md(payload: dict[str, Any]) -> str:
    approved = ", ".join(payload["internal_simulation_gate"]["approved_internal_sim_strategy_ids"]) or "none"
    lines = [
        "# M14 Goal Readiness Report",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Project stage: `{payload['project_stage_label']}`",
        f"- Challenge progress: `{payload['challenge']['challenge_progress_label']}`",
        f"- Internal simulated-account ready strategies: `{approved}`",
        "- Boundary: internal simulated only; no broker connection, no real orders, no live execution.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Gate Counts",
        "",
    ]
    for key, value in payload["internal_simulation_gate"]["gate_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    rescue_ab = payload["rescue_ab_evidence"]
    lines.extend(
        [
            "",
            "## Rescue A/B Evidence",
            "",
            f"- Observed rescue strategies: `{rescue_ab['m13_ledger_observed_strategy_count']}/{rescue_ab['rescue_runtime_strategy_count']}`",
            f"- Collecting evidence: `{rescue_ab['collecting_evidence_count']}`",
            f"- Ready for manual review: `{rescue_ab['evidence_ready_for_manual_review_count']}`",
            f"- Promotion allowed: `{rescue_ab['promotion_allowed_count']}`",
        ]
    )
    backlog = payload["rescue_optimization_backlog"]
    lines.extend(
        [
            "",
            "## Rescue Optimization Backlog",
            "",
            f"- Actionable before 10-day A/B completion: `{backlog['actionable_before_10d_count']}`",
            f"- Zero-signal connected variants: `{backlog['zero_signal_after_connection_count']}`",
            f"- Signal-to-account no-op variants: `{backlog['signal_generated_no_account_operation_count']}`",
            f"- Broker dry-run blockers: `{backlog['broker_dry_run_blocked_count']}`",
        ]
    )
    diagnostics = payload["rescue_zero_signal_diagnostics"]
    lines.extend(
        [
            "",
            "## Rescue Zero-Signal Diagnostics",
            "",
            f"- Zero-signal runtimes diagnosed: `{diagnostics['zero_signal_runtime_count']}`",
            f"- Quote-refresh candidates: `{diagnostics['quote_refresh_candidate_runtime_count']}`",
            f"- Quality/filter candidates: `{diagnostics['quality_filter_blocked_runtime_count']}`",
            f"- Source-mapping candidates: `{diagnostics['parent_source_absent_runtime_count']}`",
            f"- Parent-detector same-timeframe zero-signal: `{diagnostics['parent_detector_zero_signal_runtime_count']}`",
            f"- Potential entries if fresh quote gate clears: `{diagnostics['potential_signal_if_fresh_quote_count']}`",
            f"- Shadow reward min-R pass counts: `{diagnostics['shadow_reward_min_r_pass_counts']}`",
        ]
    )
    target_stop = payload["rescue_target_stop_diagnostics"]
    lines.extend(
        [
            "",
            "## Rescue Target/Stop Diagnostics",
            "",
            f"- Diagnosed reward/R runtimes: `{target_stop['diagnosed_runtime_count']}`",
            f"- Target/stop issue runtimes: `{target_stop['target_stop_issue_runtime_count']}`",
            f"- Shadow-candidate runtimes: `{target_stop['shadow_candidate_runtime_count']}`",
            f"- Reward >= 1.0R runtime count: `{target_stop['reward_ge_1_0_runtime_count']}`",
            f"- Dominant target/stop issues: `{target_stop['dominant_target_stop_issue_counts']}`",
        ]
    )
    shadow_normalization = payload["rescue_target_stop_shadow_normalization"]
    lines.extend(
        [
            "",
            "## Rescue Target/Stop Shadow Normalization",
            "",
            f"- Diagnosed runtimes: `{shadow_normalization['diagnosed_runtime_count']}`",
            f"- Runtime with shadow candidate: `{shadow_normalization['runtime_with_shadow_candidate_count']}`",
            f"- Best candidate rows: `{shadow_normalization['best_variant_candidate_row_count']}/{shadow_normalization['source_candidate_row_count']}`",
            f"- Best variant counts: `{shadow_normalization['best_variant_id_counts']}`",
            f"- Runtime ids: `{', '.join(shadow_normalization['runtime_ids']) or 'none'}`",
        ]
    )
    shadow_repair = payload["broker_blocker_shadow_repair"]
    lines.extend(
        [
            "",
            "## Broker Blocker Shadow Repair",
            "",
            f"- Source blocked rows: `{shadow_repair['source_blocked_rows']}`",
            f"- Quantity-cap candidates: `{shadow_repair['risk_cap_candidate_count']}`",
            f"- Exposure deferrals: `{shadow_repair['defer_for_exposure_count']}`",
            f"- Cooldown halts: `{shadow_repair['cooldown_defer_count']}`",
            f"- Original readiness mutation: `{shadow_repair['readiness_status_mutation']}`",
            f"- Shadow action counts: `{shadow_repair['shadow_action_counts']}`",
        ]
    )
    lines.extend(["", "## Next Actions", ""])
    for item in payload["next_actions"]:
        lines.append(f"- `{item['priority']}` {item['action']} Evidence: {item['evidence']} Boundary: {item['boundary']}")
    lines.extend(["", "## Strategy Action Matrix", ""])
    for row in payload["strategy_action_matrix"]:
        lines.append(
            f"- `{row['strategy_id']}` gate `{row['paper_trial_gate']}` -> `{row['next_action_category']}`"
        )
    lines.extend(["", "## Completion Assessment", "", payload["goal_completion_assessment"]["reason"], ""])
    return "\n".join(lines)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def boundary_flag(payload: dict[str, Any], key: str) -> bool:
    if key in payload:
        return bool(payload.get(key))
    hard_boundaries = payload.get("hard_boundaries")
    if isinstance(hard_boundaries, dict):
        return bool(hard_boundaries.get(key, False))
    return False
