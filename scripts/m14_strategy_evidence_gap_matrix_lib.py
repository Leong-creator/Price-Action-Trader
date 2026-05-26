#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_evidence_gap_matrix.json"
FORBIDDEN_OPERATIONS = (
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


@dataclass(frozen=True, slots=True)
class StrategyEvidenceGapMatrixConfig:
    stage: str
    strategy_decision_ladder_path: Path
    rescue_ab_evidence_tracker_path: Path
    rescue_parameter_shadow_spec_path: Path
    objective_completion_audit_path: Path
    objective_execution_plan_path: Path
    post_fresh_refresh_recompute_checklist_path: Path
    gap_matrix_json_path: Path
    gap_matrix_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategyEvidenceGapMatrixConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategyEvidenceGapMatrixConfig(
        stage=str(payload["stage"]),
        strategy_decision_ladder_path=resolve_repo_path(inputs["m14_strategy_decision_ladder"]),
        rescue_ab_evidence_tracker_path=resolve_repo_path(inputs["m14_rescue_ab_evidence_tracker"]),
        rescue_parameter_shadow_spec_path=resolve_repo_path(inputs["m14_rescue_parameter_shadow_spec"]),
        objective_completion_audit_path=resolve_repo_path(inputs["m14_objective_completion_audit"]),
        objective_execution_plan_path=resolve_repo_path(inputs["m14_objective_execution_plan"]),
        post_fresh_refresh_recompute_checklist_path=resolve_repo_path(
            inputs["m14_post_fresh_refresh_recompute_checklist"]
        ),
        gap_matrix_json_path=resolve_repo_path(outputs["gap_matrix_json"]),
        gap_matrix_md_path=resolve_repo_path(outputs["gap_matrix_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategyEvidenceGapMatrixConfig) -> None:
    if config.stage != "M14.strategy_evidence_gap_matrix":
        raise ValueError("M14 strategy evidence gap matrix stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy evidence gap matrix must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy evidence gap matrix must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy evidence gap matrix cannot enable {key}")


def run_m14_strategy_evidence_gap_matrix(
    config: StrategyEvidenceGapMatrixConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    decision_ladder = read_json(config.strategy_decision_ladder_path)
    rescue_ab = read_json(config.rescue_ab_evidence_tracker_path)
    shadow_spec = read_json(config.rescue_parameter_shadow_spec_path)
    objective_audit = read_json(config.objective_completion_audit_path)
    objective_execution = read_json(config.objective_execution_plan_path)
    checklist = read_json(config.post_fresh_refresh_recompute_checklist_path)

    rescue_rows = [dict(row) for row in rescue_ab.get("rows", [])]
    shadow_rows = [dict(row) for row in shadow_spec.get("spec_rows", [])]
    recompute_steps_by_id = {str(row.get("step_id", "")): dict(row) for row in checklist.get("recompute_steps", [])}
    gap_rows = [
        build_gap_row(
            ladder_row=dict(row),
            rescue_rows=matching_rescue_rows(dict(row), rescue_rows),
            shadow_rows=matching_shadow_rows(dict(row), shadow_rows),
            recompute_steps_by_id=recompute_steps_by_id,
        )
        for row in decision_ladder.get("ladder_rows", [])
    ]
    gap_rows.sort(key=lambda row: (row["route_rank"], row["strategy_id"]))
    gap_state_counts = Counter(row["gap_state"] for row in gap_rows)
    missing_category_counts = Counter(
        category for row in gap_rows for category in row["missing_evidence_categories"]
    )
    objective_summary = objective_audit.get("summary", {})
    execution_summary = objective_execution.get("summary", {})
    checklist_summary = checklist.get("summary", {})
    decision_summary = decision_ladder.get("summary", {})
    rescue_summary = rescue_ab.get("summary", {})
    shadow_summary = shadow_spec.get("summary", {})
    summary = {
        "current_project_stage": str(decision_summary.get("current_project_stage", "")),
        "m14_trading_date": str(decision_summary.get("m14_trading_date", "")),
        "challenge_progress_label": str(decision_summary.get("challenge_progress_label", "")),
        "strategy_gap_row_count": len(gap_rows),
        "open_evidence_gap_row_count": sum(1 for row in gap_rows if row["open_evidence_gap_count"]),
        "requires_m12_47_fresh_refresh_count": sum(1 for row in gap_rows if row["requires_m12_47_fresh_refresh"]),
        "approved_next_refresh_gap_count": gap_state_counts.get("approved_wait_next_refresh", 0),
        "rescue_gap_count": sum(1 for row in gap_rows if row["route_category"] in {"rescue_ab_collect", "parallel_ab_collect", "rebuild_detector_then_ab"}),
        "shadow_or_plugin_gap_count": sum(1 for row in gap_rows if row["route_category"] == "shadow_or_plugin_hold"),
        "wait_first_ledger_gap_count": missing_category_counts.get("first_m13_rescue_ledger", 0),
        "rescue_10_day_ab_gap_count": missing_category_counts.get("rescue_10_day_ab_window", 0),
        "shadow_review_gap_count": missing_category_counts.get("shadow_parameter_review", 0),
        "manual_m14_review_gap_count": missing_category_counts.get("manual_m14_review", 0),
        "final_discard_allowed_count": sum(1 for row in gap_rows if row["final_discard_allowed"]),
        "promotion_candidate_count": sum(1 for row in gap_rows if row["can_promote_now"]),
        "parameter_shadow_variant_count": int_or_zero(shadow_summary.get("candidate_variant_count")),
        "parameter_mutation_allowed_count": sum(1 for row in gap_rows if row["parameter_mutation_allowed"]),
        "implementation_mutation_allowed_count": 0,
        "rescue_runtime_strategy_count": int_or_zero(rescue_summary.get("rescue_runtime_strategy_count")),
        "rescue_m13_ledger_observed_strategy_count": int_or_zero(
            rescue_summary.get("m13_ledger_observed_strategy_count")
        ),
        "rescue_no_m13_ledger_evidence_count": int_or_zero(
            rescue_summary.get("no_m13_ledger_evidence_count")
        ),
        "rescue_promotion_allowed_count": int_or_zero(rescue_summary.get("promotion_allowed_count")),
        "objective_complete": bool(objective_summary.get("objective_complete", False)),
        "objective_blocked_count": int_or_zero(objective_summary.get("blocked_count")),
        "objective_in_progress_count": int_or_zero(objective_summary.get("in_progress_count")),
        "objective_execution_action_count": int_or_zero(execution_summary.get("execution_action_count")),
        "objective_execution_waiting_for_fresh_refresh_action_count": int_or_zero(
            execution_summary.get("waiting_for_fresh_refresh_action_count")
        ),
        "post_fresh_recompute_step_count": int_or_zero(checklist_summary.get("recompute_step_count")),
        "post_fresh_recompute_acceptance_gate_count": int_or_zero(checklist_summary.get("acceptance_gate_count")),
        "fresh_refresh_observed": bool(checklist_summary.get("fresh_refresh_observed", False)),
        "source_quote": str(checklist_summary.get("source_quote", "")),
        "gap_state_counts": dict(sorted(gap_state_counts.items())),
        "missing_evidence_category_counts": dict(sorted(missing_category_counts.items())),
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "copy_trading_allowed": False,
        "external_override_allowed": False,
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-evidence-gap-matrix.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_decision_ladder": project_path(config.strategy_decision_ladder_path),
            "m14_rescue_ab_evidence_tracker": project_path(config.rescue_ab_evidence_tracker_path),
            "m14_rescue_parameter_shadow_spec": project_path(config.rescue_parameter_shadow_spec_path),
            "m14_objective_completion_audit": project_path(config.objective_completion_audit_path),
            "m14_objective_execution_plan": project_path(config.objective_execution_plan_path),
            "m14_post_fresh_refresh_recompute_checklist": project_path(
                config.post_fresh_refresh_recompute_checklist_path
            ),
        },
        "summary": summary,
        "gap_rows": gap_rows,
        "gap_policy": {
            "approved_rule": "Approved strategies need the next M12.47-supervised internal simulated-account refresh and post-refresh M13/M14 recompute evidence.",
            "rescue_rule": "Weak strategies stay in rescue, detector rebuild, or shadow-parameter review until first ledger, 10-day A/B, and M14 review evidence are complete.",
            "discard_rule": "Final discard remains blocked for every strategy until rescue and shadow evidence is exhausted and manual M14 review agrees.",
            "mutation_rule": "This matrix is read-only and cannot mutate parameters, registries, account specs, or broker readiness.",
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
    write_json(config.gap_matrix_json_path, payload)
    config.gap_matrix_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.gap_matrix_md_path.write_text(build_gap_matrix_md(payload), encoding="utf-8")
    return payload


def build_gap_row(
    *,
    ladder_row: dict[str, Any],
    rescue_rows: list[dict[str, Any]],
    shadow_rows: list[dict[str, Any]],
    recompute_steps_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    missing = missing_evidence_categories_for(ladder_row, rescue_rows, shadow_rows)
    step_ids = recompute_step_ids_for(missing, ladder_row)
    available_step_ids = [step_id for step_id in step_ids if step_id in recompute_steps_by_id]
    gap_state = gap_state_for(ladder_row, missing)
    return {
        "strategy_id": str(ladder_row.get("strategy_id", "")),
        "display_name": str(ladder_row.get("display_name", "")),
        "route_rank": int_or_zero(ladder_row.get("route_rank")),
        "route_category": str(ladder_row.get("route_category", "")),
        "ladder_state": str(ladder_row.get("ladder_state", "")),
        "gap_state": gap_state,
        "next_decision": str(ladder_row.get("next_decision", "")),
        "decision": str(ladder_row.get("decision", "")),
        "paper_trial_gate": str(ladder_row.get("paper_trial_gate", "")),
        "completed_trading_days": int_or_zero(ladder_row.get("completed_trading_days")),
        "can_continue_internal_sim_now": bool(ladder_row.get("can_advance_next_step", False)),
        "can_promote_now": bool(ladder_row.get("can_promote_now", False)),
        "continue_rescue": bool(ladder_row.get("continue_rescue", False)),
        "manual_review_ready": bool(ladder_row.get("manual_review_ready", False)),
        "broker_watch": bool(ladder_row.get("broker_watch", False)),
        "linked_next_refresh_watch_count": int_or_zero(ladder_row.get("linked_next_refresh_watch_count")),
        "rescue_runtime_strategy_ids": list(ladder_row.get("rescue_runtime_strategy_ids", [])),
        "rescue_ab_row_count": len(rescue_rows),
        "rescue_ab_observed_days_max": max(
            [int_or_zero(row.get("observed_trading_days_count")) for row in rescue_rows] or [0]
        ),
        "rescue_ab_remaining_days_min": min(
            [int_or_zero(row.get("remaining_ab_trading_days")) for row in rescue_rows] or [0]
        ),
        "rescue_no_ledger_count": sum(
            1 for row in rescue_rows if str(row.get("evidence_status", "")).startswith("no_m13")
        ),
        "shadow_spec_count": len(shadow_rows),
        "candidate_variant_count": sum(int_or_zero(row.get("variant_count")) for row in shadow_rows),
        "shadow_spec_states": sorted({str(row.get("spec_state", "")) for row in shadow_rows if row.get("spec_state")}),
        "missing_evidence_categories": missing,
        "open_evidence_gap_count": len(missing),
        "required_artifacts": required_artifacts_for(missing),
        "post_fresh_recompute_step_ids": available_step_ids,
        "post_fresh_recompute_commands": [
            str(recompute_steps_by_id[step_id].get("command", ""))
            for step_id in available_step_ids
            if recompute_steps_by_id[step_id].get("command")
        ],
        "requires_m12_47_fresh_refresh": "m12_47_fresh_refresh" in missing,
        "allowed_next_move": allowed_next_move_for(gap_state),
        "final_discard_allowed": bool(ladder_row.get("final_discard_allowed", False)),
        "final_discard_blockers": list(ladder_row.get("final_discard_blockers", [])),
        "parameter_mutation_allowed": False,
        "implementation_mutation_allowed": False,
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
        "paper_simulated_only": True,
        "internal_simulated_account": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
    }


def missing_evidence_categories_for(
    ladder_row: dict[str, Any],
    rescue_rows: list[dict[str, Any]],
    shadow_rows: list[dict[str, Any]],
) -> list[str]:
    ladder_state = str(ladder_row.get("ladder_state", ""))
    route_category = str(ladder_row.get("route_category", ""))
    missing: list[str] = []
    if ladder_state == "approved_continue_internal_sim":
        missing.extend(["m12_47_fresh_refresh", "post_refresh_m13_m14_recompute"])
        if bool(ladder_row.get("broker_watch", False)) or int_or_zero(ladder_row.get("linked_next_refresh_watch_count")):
            missing.append("broker_dry_run_watch_recheck")
    elif ladder_state == "wait_first_rescue_ledger":
        missing.extend(
            [
                "m12_47_fresh_refresh",
                "first_m13_rescue_ledger",
                "rescue_10_day_ab_window",
                "manual_m14_review",
            ]
        )
    elif ladder_state == "continue_rescue_with_shadow_specs":
        missing.extend(["m12_47_fresh_refresh", "rescue_10_day_ab_window", "shadow_parameter_review", "manual_m14_review"])
    elif ladder_state == "continue_rescue_ab_collection":
        missing.extend(["rescue_10_day_ab_window", "manual_m14_review"])
    elif ladder_state == "rebuild_detector_before_discard":
        missing.extend(["detector_rebuild_evidence", "rescue_10_day_ab_window", "manual_m14_review"])
    elif ladder_state == "ready_for_manual_promote_review":
        missing.append("manual_m14_review")
    elif ladder_state == "shadow_or_plugin_hold" or route_category == "shadow_or_plugin_hold":
        missing.extend(["independent_strategy_evidence_missing", "manual_m14_review"])
    else:
        missing.append("manual_m14_review")
    if any(str(row.get("evidence_status", "")).startswith("no_m13") for row in rescue_rows):
        missing.extend(["m12_47_fresh_refresh", "first_m13_rescue_ledger"])
    if shadow_rows and not any(item == "shadow_parameter_review" for item in missing):
        missing.append("shadow_parameter_review")
    if bool(ladder_row.get("final_discard_blockers", [])) and "manual_m14_review" not in missing:
        missing.append("manual_m14_review")
    return sorted(dict.fromkeys(missing))


def recompute_step_ids_for(missing: list[str], ladder_row: dict[str, Any]) -> list[str]:
    step_ids: list[str] = []
    if "m12_47_fresh_refresh" in missing:
        step_ids.extend(["wait_for_m12_47_supervisor_refresh", "review_post_refresh_outcomes"])
    if "first_m13_rescue_ledger" in missing or "rescue_10_day_ab_window" in missing:
        step_ids.extend(["refresh_rescue_ab_evidence", "refresh_rescue_optimization_backlog"])
    if "detector_rebuild_evidence" in missing:
        step_ids.extend(["refresh_zero_signal_diagnostics", "refresh_next_refresh_readiness"])
    if "shadow_parameter_review" in missing or "broker_dry_run_watch_recheck" in missing:
        step_ids.extend(
            [
                "refresh_next_refresh_readiness",
                "refresh_parameter_experiment_queue",
                "refresh_parameter_activation_gate",
                "refresh_parameter_shadow_specs",
            ]
        )
    if str(ladder_row.get("next_decision", "")) == "advance_internal_sim_next_refresh":
        step_ids.extend(["refresh_internal_sim_launch_readiness", "refresh_internal_sim_next_session_plan"])
    step_ids.extend(
        [
            "objective_audit_first_pass",
            "objective_execution_first_pass",
            "strategy_decision_ladder_refresh",
            "objective_audit_after_ladder",
            "objective_execution_after_ladder",
            "project_stage_assessment_refresh",
        ]
    )
    return list(dict.fromkeys(step_ids))


def required_artifacts_for(missing: list[str]) -> list[str]:
    artifact_map = {
        "m12_47_fresh_refresh": "M12.47-supervised M12/M13 refreshed artifacts",
        "post_refresh_m13_m14_recompute": "post-refresh M13/M14 recompute artifacts",
        "broker_dry_run_watch_recheck": "M14.2 broker dry-run blocker recheck",
        "first_m13_rescue_ledger": "rescue-specific M13 signal/account ledger row",
        "rescue_10_day_ab_window": "10 trading-day rescue A/B evidence",
        "shadow_parameter_review": "M14 parameter shadow spec and activation gate",
        "manual_m14_review": "manual M14 review after machine evidence is complete",
        "detector_rebuild_evidence": "detector rebuild diagnostics and same-cycle evidence",
        "independent_strategy_evidence_missing": "independent strategy evidence beyond shadow/plugin/research coverage",
    }
    return [artifact_map[item] for item in missing if item in artifact_map]


def gap_state_for(ladder_row: dict[str, Any], missing: list[str]) -> str:
    if str(ladder_row.get("ladder_state", "")) == "approved_continue_internal_sim":
        return "approved_wait_next_refresh"
    if "first_m13_rescue_ledger" in missing:
        return "wait_first_rescue_ledger"
    if "shadow_parameter_review" in missing:
        return "wait_shadow_parameter_review"
    if "detector_rebuild_evidence" in missing:
        return "wait_detector_rebuild"
    if "independent_strategy_evidence_missing" in missing:
        return "shadow_or_plugin_hold"
    if "rescue_10_day_ab_window" in missing:
        return "collect_rescue_ab_evidence"
    return "manual_review_required"


def allowed_next_move_for(gap_state: str) -> str:
    moves = {
        "approved_wait_next_refresh": "wait_for_m12_47_supervised_internal_sim_refresh",
        "wait_first_rescue_ledger": "wait_for_first_rescue_specific_m13_ledger",
        "wait_shadow_parameter_review": "continue_rescue_ab_and_shadow_spec_review",
        "wait_detector_rebuild": "rebuild_detector_then_collect_ab_evidence",
        "shadow_or_plugin_hold": "keep_shadow_plugin_or_research_coverage",
        "collect_rescue_ab_evidence": "continue_rescue_10_day_ab_collection",
        "manual_review_required": "manual_m14_review_after_machine_evidence",
    }
    return moves.get(gap_state, "manual_m14_review_after_machine_evidence")


def matching_rescue_rows(ladder_row: dict[str, Any], rescue_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strategy_id = str(ladder_row.get("strategy_id", ""))
    rescue_ids = {str(item) for item in ladder_row.get("rescue_runtime_strategy_ids", []) if str(item)}
    return [
        dict(row)
        for row in rescue_rows
        if str(row.get("parent_strategy_id", "")) == strategy_id or str(row.get("strategy_id", "")) in rescue_ids
    ]


def matching_shadow_rows(ladder_row: dict[str, Any], shadow_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strategy_id = str(ladder_row.get("strategy_id", ""))
    rescue_ids = {str(item) for item in ladder_row.get("rescue_runtime_strategy_ids", []) if str(item)}
    return [
        dict(row)
        for row in shadow_rows
        if str(row.get("parent_strategy_id", "")) == strategy_id or str(row.get("strategy_id", "")) in rescue_ids
    ]


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Strategy evidence gap matrix covers {summary['strategy_gap_row_count']} strategy rows; "
        f"{summary['open_evidence_gap_row_count']} still have open evidence gaps and "
        f"{summary['requires_m12_47_fresh_refresh_count']} require the next M12.47 fresh refresh. "
        f"First-ledger gaps: {summary['wait_first_ledger_gap_count']}; "
        f"10-day rescue A/B gaps: {summary['rescue_10_day_ab_gap_count']}; "
        f"shadow-review gaps: {summary['shadow_review_gap_count']}; "
        f"final discards allowed now: {summary['final_discard_allowed_count']}; "
        f"promotion candidates now: {summary['promotion_candidate_count']}. "
        "No broker/live, real orders, paper approval, parameter mutation, registry/account-spec mutation, "
        "broker-readiness mutation, or manual M12.37 once-mode is enabled."
    )


def build_gap_matrix_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Evidence Gap Matrix",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Strategy gap rows: `{summary['strategy_gap_row_count']}`",
        f"- Open evidence gap rows: `{summary['open_evidence_gap_row_count']}`",
        f"- Requires M12.47 fresh refresh: `{summary['requires_m12_47_fresh_refresh_count']}`",
        f"- First-ledger / 10-day A/B / shadow-review gaps: `{summary['wait_first_ledger_gap_count']}/{summary['rescue_10_day_ab_gap_count']}/{summary['shadow_review_gap_count']}`",
        f"- Final discard allowed: `{summary['final_discard_allowed_count']}`",
        f"- Promotion candidates: `{summary['promotion_candidate_count']}`",
        f"- Parameter mutation allowed: `{summary['parameter_mutation_allowed_count']}`",
        "- Boundary: internal simulated accounts only; no broker/live, no real orders, no paper approval, no manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Gap Policy",
        "",
    ]
    for key, value in payload["gap_policy"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Gap Rows", ""])
    for row in payload["gap_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Route: `{row['route_category']}`",
                f"- Ladder state: `{row['ladder_state']}`",
                f"- Gap state: `{row['gap_state']}`",
                f"- Missing evidence: `{', '.join(row['missing_evidence_categories'])}`",
                f"- Required artifacts: `{'; '.join(row['required_artifacts'])}`",
                f"- Recompute steps: `{', '.join(row['post_fresh_recompute_step_ids'])}`",
                f"- Allowed next move: `{row['allowed_next_move']}`",
                f"- Final discard allowed: `{row['final_discard_allowed']}`",
                f"- Parameter mutation allowed: `{row['parameter_mutation_allowed']}`",
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
