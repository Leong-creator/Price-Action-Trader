#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_decision_ladder.json"


@dataclass(frozen=True, slots=True)
class StrategyDecisionLadderConfig:
    stage: str
    goal_readiness_report_path: Path
    internal_sim_next_session_plan_path: Path
    rescue_ab_evidence_tracker_path: Path
    rescue_parameter_shadow_spec_path: Path
    rescue_external_reference_map_path: Path
    objective_execution_plan_path: Path
    decision_ladder_json_path: Path
    decision_ladder_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategyDecisionLadderConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategyDecisionLadderConfig(
        stage=str(payload["stage"]),
        goal_readiness_report_path=resolve_repo_path(inputs["m14_goal_readiness_report"]),
        internal_sim_next_session_plan_path=resolve_repo_path(inputs["m14_internal_sim_next_session_plan"]),
        rescue_ab_evidence_tracker_path=resolve_repo_path(inputs["m14_rescue_ab_evidence_tracker"]),
        rescue_parameter_shadow_spec_path=resolve_repo_path(inputs["m14_rescue_parameter_shadow_spec"]),
        rescue_external_reference_map_path=resolve_repo_path(inputs["m14_rescue_external_reference_map"]),
        objective_execution_plan_path=resolve_repo_path(inputs["m14_objective_execution_plan"]),
        decision_ladder_json_path=resolve_repo_path(outputs["decision_ladder_json"]),
        decision_ladder_md_path=resolve_repo_path(outputs["decision_ladder_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategyDecisionLadderConfig) -> None:
    if config.stage != "M14.strategy_decision_ladder":
        raise ValueError("M14 strategy decision ladder stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy decision ladder must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy decision ladder must keep internal simulated accounts enabled")
    forbidden = (
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
    for key in forbidden:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy decision ladder cannot enable {key}")


def run_m14_strategy_decision_ladder(
    config: StrategyDecisionLadderConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    goal = read_json(config.goal_readiness_report_path)
    next_session = read_json(config.internal_sim_next_session_plan_path)
    rescue_ab = read_json(config.rescue_ab_evidence_tracker_path)
    shadow_spec = read_json(config.rescue_parameter_shadow_spec_path)
    external_map = read_json(config.rescue_external_reference_map_path)
    objective_execution = read_json(config.objective_execution_plan_path)

    rescue_rows = [dict(row) for row in rescue_ab.get("rows", [])]
    shadow_rows = [dict(row) for row in shadow_spec.get("spec_rows", [])]
    next_rows_by_strategy = {
        str(row.get("strategy_id", "")): dict(row)
        for row in next_session.get("strategy_session_rows", [])
    }
    external_by_strategy = build_external_strategy_map(external_map)
    ladder_rows = [
        build_ladder_row(
            strategy_row=dict(row),
            next_session_row=next_rows_by_strategy.get(str(row.get("strategy_id", "")), {}),
            rescue_rows=matching_rescue_rows(dict(row), rescue_rows),
            shadow_rows=matching_shadow_rows(dict(row), shadow_rows),
            external_row=external_by_strategy.get(str(row.get("strategy_id", "")), {}),
        )
        for row in goal.get("strategy_action_matrix", [])
    ]
    ladder_rows.sort(key=lambda row: (row["route_rank"], row["strategy_id"]))
    state_counts = Counter(row["ladder_state"] for row in ladder_rows)
    next_counts = Counter(row["next_decision"] for row in ladder_rows)
    summary = {
        "current_project_stage": str(goal.get("project_stage_label", "")),
        "m14_trading_date": str(goal.get("m14_trading_date", "")),
        "ten_day_challenge_complete": bool(goal.get("challenge", {}).get("ten_day_challenge_complete", False)),
        "challenge_progress_label": str(goal.get("challenge", {}).get("challenge_progress_label", "")),
        "strategy_ladder_row_count": len(ladder_rows),
        "approved_next_step_count": sum(1 for row in ladder_rows if row["can_advance_next_step"]),
        "rescue_continue_count": sum(1 for row in ladder_rows if row["continue_rescue"]),
        "manual_review_ready_count": sum(1 for row in ladder_rows if row["manual_review_ready"]),
        "promotion_candidate_count": sum(1 for row in ladder_rows if row["can_promote_now"]),
        "final_discard_allowed_count": sum(1 for row in ladder_rows if row["final_discard_allowed"]),
        "final_discard_blocked_count": sum(1 for row in ladder_rows if not row["final_discard_allowed"]),
        "shadow_or_plugin_hold_count": state_counts.get("shadow_or_plugin_hold", 0),
        "wait_first_ledger_strategy_count": state_counts.get("wait_first_rescue_ledger", 0),
        "shadow_spec_strategy_count": sum(1 for row in ladder_rows if row["shadow_spec_count"]),
        "candidate_variant_count": sum(row["candidate_variant_count"] for row in ladder_rows),
        "rescue_ab_row_count": int_or_zero(rescue_ab.get("summary", {}).get("rescue_runtime_strategy_count")),
        "rescue_promotion_allowed_count": int_or_zero(rescue_ab.get("summary", {}).get("promotion_allowed_count")),
        "objective_execution_action_count": int_or_zero(
            objective_execution.get("summary", {}).get("execution_action_count")
        ),
        "objective_execution_waiting_for_fresh_refresh_action_count": int_or_zero(
            objective_execution.get("summary", {}).get("waiting_for_fresh_refresh_action_count")
        ),
        "parameter_mutation_allowed_count": 0,
        "implementation_mutation_allowed_count": 0,
        "m13_registry_mutation_count": 0,
        "m12_account_specs_mutation_count": 0,
        "broker_readiness_status_mutation_count": 0,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "copy_trading_allowed": False,
        "external_override_allowed": False,
        "ladder_state_counts": dict(sorted(state_counts.items())),
        "next_decision_counts": dict(sorted(next_counts.items())),
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-decision-ladder.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_goal_readiness_report": project_path(config.goal_readiness_report_path),
            "m14_internal_sim_next_session_plan": project_path(config.internal_sim_next_session_plan_path),
            "m14_rescue_ab_evidence_tracker": project_path(config.rescue_ab_evidence_tracker_path),
            "m14_rescue_parameter_shadow_spec": project_path(config.rescue_parameter_shadow_spec_path),
            "m14_rescue_external_reference_map": project_path(config.rescue_external_reference_map_path),
            "m14_objective_execution_plan": project_path(config.objective_execution_plan_path),
        },
        "summary": summary,
        "ladder_rows": ladder_rows,
        "decision_policy": {
            "approved_strategy_rule": "Approved strategies can advance only to the next internal simulated-account refresh.",
            "rescue_rule": "Weak strategies stay in rescue A/B, shadow spec, or detector rebuild until rescue evidence is complete.",
            "discard_rule": "Final discard is allowed only after rescue routes, shadow specs, first-ledger checks, and 10-day A/B evidence are exhausted and manual M14 review agrees.",
            "external_reference_rule": "External projects can provide review patterns only; they cannot override local M13/M14 gates.",
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
    write_json(config.decision_ladder_json_path, payload)
    config.decision_ladder_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.decision_ladder_md_path.write_text(build_decision_ladder_md(payload), encoding="utf-8")
    return payload


def build_ladder_row(
    *,
    strategy_row: dict[str, Any],
    next_session_row: dict[str, Any],
    rescue_rows: list[dict[str, Any]],
    shadow_rows: list[dict[str, Any]],
    external_row: dict[str, Any],
) -> dict[str, Any]:
    route_category = route_category_for(strategy_row)
    ladder_state, next_decision = classify_ladder_state(route_category, rescue_rows, shadow_rows, strategy_row)
    final_discard_blockers = final_discard_blockers_for(route_category, rescue_rows, shadow_rows, strategy_row)
    can_advance = route_category == "approved_internal_sim_continue" and bool(
        strategy_row.get("can_enter_internal_simulation", False)
    )
    can_promote = any(bool(row.get("can_promote", False)) for row in rescue_rows)
    manual_ready = can_promote or any(bool(row.get("ready_for_manual_review", False)) for row in rescue_rows)
    return {
        "strategy_id": str(strategy_row.get("strategy_id", "")),
        "display_name": str(strategy_row.get("display_name", "")),
        "route_rank": route_rank(route_category),
        "route_category": route_category,
        "paper_trial_gate": str(strategy_row.get("paper_trial_gate", "")),
        "decision": str(strategy_row.get("decision", "")),
        "decision_reason": str(strategy_row.get("decision_reason", "")),
        "completed_trading_days": int_or_zero(strategy_row.get("completed_trading_days")),
        "can_enter_internal_simulation": bool(strategy_row.get("can_enter_internal_simulation", False)),
        "can_advance_next_step": can_advance,
        "continue_rescue": route_category in {"rescue_ab_collect", "parallel_ab_collect", "rebuild_detector_then_ab"},
        "manual_review_ready": manual_ready,
        "can_promote_now": can_promote,
        "ladder_state": ladder_state,
        "next_decision": next_decision,
        "session_action": str(next_session_row.get("session_action", "")),
        "broker_watch": bool(next_session_row.get("broker_dry_run_blocked_count", 0)),
        "linked_next_refresh_watch_count": int_or_zero(next_session_row.get("linked_next_refresh_watch_count")),
        "rescue_runtime_strategy_ids": list(strategy_row.get("rescue_runtime_strategy_ids", [])),
        "rescue_ab_row_count": len(rescue_rows),
        "rescue_ab_observed_days_max": max([int_or_zero(row.get("observed_trading_days_count")) for row in rescue_rows] or [0]),
        "rescue_ab_remaining_days_min": min([int_or_zero(row.get("remaining_ab_trading_days")) for row in rescue_rows] or [0]),
        "rescue_no_ledger_count": sum(
            1 for row in rescue_rows if str(row.get("evidence_status", "")).startswith("no_m13")
        ),
        "shadow_spec_count": len(shadow_rows),
        "candidate_variant_count": sum(int_or_zero(row.get("variant_count")) for row in shadow_rows),
        "shadow_spec_states": sorted({str(row.get("spec_state", "")) for row in shadow_rows if row.get("spec_state")}),
        "external_reference_pattern_ids": list(external_row.get("external_reference_pattern_ids", [])),
        "external_review_lanes": list(external_row.get("local_review_lanes", [])),
        "final_discard_allowed": not final_discard_blockers,
        "final_discard_blockers": final_discard_blockers,
        "next_action": next_action_for(ladder_state, next_decision),
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


def route_category_for(row: dict[str, Any]) -> str:
    category = str(row.get("next_action_category", ""))
    mapping = {
        "continue_internal_simulation": "approved_internal_sim_continue",
        "collect_rescue_ab_evidence": "rescue_ab_collect",
        "continue_parallel_ab_evidence": "parallel_ab_collect",
        "rebuild_detector_ab_evidence": "rebuild_detector_then_ab",
        "continue_shadow_or_plugin_review": "shadow_or_plugin_hold",
    }
    return mapping.get(category, "manual_review_required")


def classify_ladder_state(
    route_category: str,
    rescue_rows: list[dict[str, Any]],
    shadow_rows: list[dict[str, Any]],
    strategy_row: dict[str, Any],
) -> tuple[str, str]:
    if route_category == "approved_internal_sim_continue":
        return ("approved_continue_internal_sim", "advance_internal_sim_next_refresh")
    if route_category == "shadow_or_plugin_hold":
        return ("shadow_or_plugin_hold", "keep_shadow_research_coverage")
    if any(bool(row.get("can_promote", False)) for row in rescue_rows):
        return ("ready_for_manual_promote_review", "manual_m14_promote_or_continue_review")
    if any(str(row.get("evidence_status", "")).startswith("no_m13") for row in rescue_rows):
        return ("wait_first_rescue_ledger", "collect_first_m13_rescue_ledger")
    if shadow_rows:
        return ("continue_rescue_with_shadow_specs", "continue_ab_and_shadow_parameter_review")
    if route_category == "rebuild_detector_then_ab":
        return ("rebuild_detector_before_discard", "rebuild_then_collect_ab_evidence")
    if bool(strategy_row.get("requires_10_day_ab_evidence", False)):
        return ("continue_rescue_ab_collection", "collect_10_day_rescue_ab_evidence")
    return ("manual_review_required", "inspect_before_state_change")


def final_discard_blockers_for(
    route_category: str,
    rescue_rows: list[dict[str, Any]],
    shadow_rows: list[dict[str, Any]],
    strategy_row: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if route_category == "approved_internal_sim_continue":
        blockers.append("strategy_is_approved_for_internal_sim")
    if route_category == "shadow_or_plugin_hold":
        blockers.append("strategy_is_shadow_plugin_or_research_coverage")
    if rescue_rows:
        blockers.append("rescue_runtime_exists")
    if shadow_rows:
        blockers.append("shadow_parameter_spec_exists")
    if any(not bool(row.get("meets_min_ab_trading_days", False)) for row in rescue_rows):
        blockers.append("rescue_10_day_ab_window_incomplete")
    if any(str(row.get("evidence_status", "")).startswith("no_m13") for row in rescue_rows):
        blockers.append("first_m13_rescue_ledger_missing")
    if bool(strategy_row.get("requires_10_day_ab_evidence", False)) and not rescue_rows:
        blockers.append("required_rescue_evidence_missing")
    blockers.append("manual_m14_final_review_required")
    return sorted(dict.fromkeys(blockers))


def next_action_for(ladder_state: str, next_decision: str) -> str:
    actions = {
        "approved_continue_internal_sim": "Continue only in the next M12.47-supervised internal simulated-account refresh.",
        "shadow_or_plugin_hold": "Keep as shadow/plugin/research coverage; do not present as an independent trading account.",
        "ready_for_manual_promote_review": "Prepare manual M14 review; promotion still cannot bypass guardrails.",
        "wait_first_rescue_ledger": "Wait for first rescue-specific M13 ledger evidence from M12.47-owned refresh.",
        "continue_rescue_with_shadow_specs": "Keep rescue A/B collection and use shadow specs after fresh evidence.",
        "rebuild_detector_before_discard": "Rebuild detector and collect A/B evidence before any final discard.",
        "continue_rescue_ab_collection": "Continue rescue-specific 10 trading-day A/B evidence collection.",
    }
    return actions.get(ladder_state, f"Manual review required before {next_decision}.")


def matching_rescue_rows(strategy_row: dict[str, Any], rescue_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strategy_id = str(strategy_row.get("strategy_id", ""))
    rescue_ids = {str(item) for item in strategy_row.get("rescue_runtime_strategy_ids", []) if str(item)}
    return [
        dict(row)
        for row in rescue_rows
        if str(row.get("parent_strategy_id", "")) == strategy_id or str(row.get("strategy_id", "")) in rescue_ids
    ]


def matching_shadow_rows(strategy_row: dict[str, Any], shadow_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strategy_id = str(strategy_row.get("strategy_id", ""))
    rescue_ids = {str(item) for item in strategy_row.get("rescue_runtime_strategy_ids", []) if str(item)}
    return [
        dict(row)
        for row in shadow_rows
        if str(row.get("parent_strategy_id", "")) == strategy_id or str(row.get("strategy_id", "")) in rescue_ids
    ]


def build_external_strategy_map(external_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    rows = list(external_map.get("rescue_reference_rows", [])) + list(
        external_map.get("broker_blocker_reference_rows", [])
    )
    for row in rows:
        strategy_id = str(row.get("strategy_id", ""))
        parent_strategy_id = str(row.get("parent_strategy_id", ""))
        if strategy_id and strategy_id not in mapped:
            mapped[strategy_id] = dict(row)
        if parent_strategy_id and parent_strategy_id not in mapped:
            mapped[parent_strategy_id] = dict(row)
    return mapped


def route_rank(route_category: str) -> int:
    ranks = {
        "approved_internal_sim_continue": 0,
        "rescue_ab_collect": 1,
        "parallel_ab_collect": 2,
        "rebuild_detector_then_ab": 3,
        "shadow_or_plugin_hold": 4,
    }
    return ranks.get(route_category, 9)


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Strategy decision ladder covers {summary['strategy_ladder_row_count']} strategies. "
        f"{summary['approved_next_step_count']} can advance only to the next internal simulated-account refresh; "
        f"{summary['rescue_continue_count']} must continue rescue or detector work; "
        f"{summary['shadow_or_plugin_hold_count']} stay as shadow/plugin/research coverage. "
        f"Final discard allowed now: {summary['final_discard_allowed_count']}. "
        f"Promotion candidates now: {summary['promotion_candidate_count']}. "
        "No broker/live, real orders, paper approval, parameter mutation, registry/account-spec mutation, "
        "broker-readiness mutation, or manual M12.37 once-mode is enabled."
    )


def build_decision_ladder_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Decision Ladder",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Strategy rows: `{summary['strategy_ladder_row_count']}`",
        f"- Approved next-step count: `{summary['approved_next_step_count']}`",
        f"- Rescue continue count: `{summary['rescue_continue_count']}`",
        f"- Promotion candidates: `{summary['promotion_candidate_count']}`",
        f"- Final discard allowed: `{summary['final_discard_allowed_count']}`",
        f"- Candidate variants linked: `{summary['candidate_variant_count']}`",
        "- Boundary: internal simulated accounts only; no broker/live, no real orders, no paper approval, no manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Decision Policy",
        "",
    ]
    for key, value in payload["decision_policy"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Ladder Rows", ""])
    for row in payload["ladder_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Route: `{row['route_category']}`",
                f"- Ladder state: `{row['ladder_state']}`",
                f"- Next decision: `{row['next_decision']}`",
                f"- Can advance next step: `{row['can_advance_next_step']}`",
                f"- Continue rescue: `{row['continue_rescue']}`",
                f"- Final discard allowed: `{row['final_discard_allowed']}`",
                f"- Final discard blockers: `{', '.join(row['final_discard_blockers'])}`",
                f"- Shadow specs / variants: `{row['shadow_spec_count']}/{row['candidate_variant_count']}`",
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
