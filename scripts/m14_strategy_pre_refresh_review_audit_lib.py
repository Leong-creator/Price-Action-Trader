#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_pre_refresh_review_audit.json"
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
class StrategyPreRefreshReviewAuditConfig:
    stage: str
    strategy_pre_refresh_review_packet_path: Path
    strategy_evidence_gap_burndown_path: Path
    strategy_decision_ladder_path: Path
    rescue_parameter_shadow_spec_path: Path
    rescue_parameter_activation_gate_path: Path
    rescue_external_reference_map_path: Path
    review_audit_json_path: Path
    review_audit_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategyPreRefreshReviewAuditConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategyPreRefreshReviewAuditConfig(
        stage=str(payload["stage"]),
        strategy_pre_refresh_review_packet_path=resolve_repo_path(
            inputs["m14_strategy_pre_refresh_review_packet"]
        ),
        strategy_evidence_gap_burndown_path=resolve_repo_path(
            inputs["m14_strategy_evidence_gap_burndown"]
        ),
        strategy_decision_ladder_path=resolve_repo_path(inputs["m14_strategy_decision_ladder"]),
        rescue_parameter_shadow_spec_path=resolve_repo_path(
            inputs["m14_rescue_parameter_shadow_spec"]
        ),
        rescue_parameter_activation_gate_path=resolve_repo_path(
            inputs["m14_rescue_parameter_activation_gate"]
        ),
        rescue_external_reference_map_path=resolve_repo_path(
            inputs["m14_rescue_external_reference_map"]
        ),
        review_audit_json_path=resolve_repo_path(outputs["review_audit_json"]),
        review_audit_md_path=resolve_repo_path(outputs["review_audit_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategyPreRefreshReviewAuditConfig) -> None:
    if config.stage != "M14.strategy_pre_refresh_review_audit":
        raise ValueError("M14 strategy pre-refresh review audit stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy pre-refresh review audit must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy pre-refresh review audit must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy pre-refresh review audit cannot enable {key}")


def run_m14_strategy_pre_refresh_review_audit(
    config: StrategyPreRefreshReviewAuditConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    packet = read_json(config.strategy_pre_refresh_review_packet_path)
    burndown = read_json(config.strategy_evidence_gap_burndown_path)
    decision_ladder = read_json(config.strategy_decision_ladder_path)
    shadow_spec = read_json(config.rescue_parameter_shadow_spec_path)
    activation_gate = read_json(config.rescue_parameter_activation_gate_path)
    external_map = read_json(config.rescue_external_reference_map_path)

    context = {
        "burndown_rows": list(burndown.get("burndown_rows", [])),
        "decision_ladder_rows": list(decision_ladder.get("ladder_rows", [])),
        "shadow_spec_rows": list(shadow_spec.get("spec_rows", [])),
        "activation_gate_rows": list(activation_gate.get("gate_rows", [])),
        "external_rows": list(external_map.get("rescue_reference_rows", []))
        + list(external_map.get("broker_blocker_reference_rows", [])),
    }
    audit_rows = [
        build_audit_row(dict(row), context)
        for row in packet.get("review_rows", [])
    ]
    audit_rows.sort(key=lambda row: (priority_rank(row["priority"]), int_or_zero(row["sequence_rank"]), row["strategy_id"]))
    held_rows = [build_held_audit_row(dict(row)) for row in packet.get("held_rows", [])]
    summary = build_summary(
        packet=packet,
        audit_rows=audit_rows,
        held_rows=held_rows,
    )
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-pre-refresh-review-audit.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_pre_refresh_review_packet": project_path(
                config.strategy_pre_refresh_review_packet_path
            ),
            "m14_strategy_evidence_gap_burndown": project_path(
                config.strategy_evidence_gap_burndown_path
            ),
            "m14_strategy_decision_ladder": project_path(config.strategy_decision_ladder_path),
            "m14_rescue_parameter_shadow_spec": project_path(
                config.rescue_parameter_shadow_spec_path
            ),
            "m14_rescue_parameter_activation_gate": project_path(
                config.rescue_parameter_activation_gate_path
            ),
            "m14_rescue_external_reference_map": project_path(config.rescue_external_reference_map_path),
        },
        "summary": summary,
        "audit_rows": audit_rows,
        "held_rows": held_rows,
        "audit_policy": {
            "purpose": "Audit whether pre-refresh review rows have enough existing artifacts for review work before fresh evidence arrives.",
            "allowed_now": "Check local artifacts, shadow specs, activation gates, external-reference lanes, and decision-ladder context.",
            "not_allowed_now": "No evidence-changing refresh, parameter mutation, registry/account-spec mutation, broker readiness mutation, broker/live path, paper approval, or manual M12.37 once-mode.",
            "completion_rule": "This audit can mark review work as artifact-ready, but cannot close gaps, promote, discard, or activate parameters.",
        },
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.review_audit_json_path, payload)
    config.review_audit_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.review_audit_md_path.write_text(build_review_audit_md(payload), encoding="utf-8")
    return payload


def build_audit_row(
    review_row: dict[str, Any],
    context: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    strategy_id = str(review_row.get("strategy_id", ""))
    missing = list(review_row.get("missing_evidence_categories", []))
    lane = str(review_row.get("burn_down_lane", ""))
    burndown_matches = match_rows(strategy_id, context["burndown_rows"])
    ladder_matches = match_rows(strategy_id, context["decision_ladder_rows"])
    shadow_matches = match_rows(strategy_id, context["shadow_spec_rows"])
    activation_matches = match_rows(strategy_id, context["activation_gate_rows"])
    external_matches = match_rows(strategy_id, context["external_rows"])
    shadow_required = needs_shadow_artifact(lane, missing)
    external_required = bool(review_row.get("external_reference_pattern_ids", []))
    missing_artifacts = []
    if not burndown_matches:
        missing_artifacts.append("m14_strategy_evidence_gap_burndown_row")
    if not ladder_matches:
        missing_artifacts.append("m14_strategy_decision_ladder_row")
    if shadow_required and not shadow_matches:
        missing_artifacts.append("m14_rescue_parameter_shadow_spec_row")
    if shadow_required and not activation_matches:
        missing_artifacts.append("m14_rescue_parameter_activation_gate_row")
    if external_required and not external_matches:
        missing_artifacts.append("m14_rescue_external_reference_map_row")
    audit_state = audit_state_for(bool(review_row.get("requires_m12_47_fresh_refresh", False)), missing_artifacts)
    return {
        "review_id": str(review_row.get("review_id", "")),
        "strategy_id": strategy_id,
        "display_name": str(review_row.get("display_name", "")),
        "priority": str(review_row.get("priority", "")),
        "sequence_rank": int_or_zero(review_row.get("sequence_rank")),
        "burn_down_lane": lane,
        "review_focus": str(review_row.get("review_focus", "")),
        "audit_state": audit_state,
        "can_prepare_review_notes_now": not missing_artifacts,
        "fresh_evidence_required_before_decision": bool(
            review_row.get("requires_m12_47_fresh_refresh", False)
        ),
        "artifact_only_review": not bool(review_row.get("requires_m12_47_fresh_refresh", False)),
        "shadow_parameter_artifacts_required": shadow_required,
        "external_reference_artifacts_required": external_required,
        "artifact_support": {
            "burndown_row_present": bool(burndown_matches),
            "decision_ladder_row_present": bool(ladder_matches),
            "shadow_spec_row_count": len(shadow_matches),
            "activation_gate_row_count": len(activation_matches),
            "external_reference_row_count": len(external_matches),
            "shadow_spec_ready": bool(shadow_matches) if shadow_required else True,
            "activation_gate_ready": bool(activation_matches) if shadow_required else True,
            "external_reference_ready": bool(external_matches) if external_required else True,
        },
        "missing_supporting_artifacts": missing_artifacts,
        "pre_refresh_review_actions": list(review_row.get("pre_refresh_review_actions", [])),
        "external_reference_pattern_ids": list(review_row.get("external_reference_pattern_ids", [])),
        "external_reference_review_actions": list(review_row.get("external_reference_review_actions", [])),
        "next_evidence_to_collect": str(review_row.get("next_evidence_to_collect", "")),
        "blocked_by": list(review_row.get("blocked_by", [])),
        "missing_evidence_categories": missing,
        "review_can_close_gap_now": False,
        "review_can_promote_now": False,
        "review_can_discard_now": False,
        "parameter_mutation_allowed_now": False,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        **hard_boundaries(),
    }


def build_held_audit_row(held_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": str(held_row.get("strategy_id", "")),
        "priority": str(held_row.get("priority", "")),
        "burn_down_lane": str(held_row.get("burn_down_lane", "")),
        "audit_state": "held_wait_for_rescue_ab_or_manual_review",
        "hold_reason": str(held_row.get("hold_reason", "")),
        "next_evidence_to_collect": str(held_row.get("next_evidence_to_collect", "")),
        "can_prepare_review_notes_now": False,
        "review_can_close_gap_now": False,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
    }


def build_summary(
    *,
    packet: dict[str, Any],
    audit_rows: list[dict[str, Any]],
    held_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    packet_summary = packet.get("summary", {})
    state_counts = Counter(row["audit_state"] for row in audit_rows)
    priority_counts = Counter(row["priority"] for row in audit_rows)
    lane_counts = Counter(row["burn_down_lane"] for row in audit_rows)
    fresh_dependent_count = sum(row["fresh_evidence_required_before_decision"] for row in audit_rows)
    artifact_only_count = sum(row["artifact_only_review"] for row in audit_rows)
    shadow_parameter_required_count = sum(
        row["shadow_parameter_artifacts_required"] for row in audit_rows
    )
    shadow_parameter_artifact_ready_count = sum(
        row["shadow_parameter_artifacts_required"]
        and row["artifact_support"]["shadow_spec_ready"]
        and row["artifact_support"]["activation_gate_ready"]
        for row in audit_rows
    )
    activation_gate_artifact_ready_count = sum(
        row["shadow_parameter_artifacts_required"]
        and row["artifact_support"]["activation_gate_ready"]
        for row in audit_rows
    )
    external_reference_required_count = sum(
        row["external_reference_artifacts_required"] for row in audit_rows
    )
    external_reference_ready_count = sum(
        row["external_reference_artifacts_required"]
        and row["artifact_support"]["external_reference_ready"]
        for row in audit_rows
    )
    decision_ladder_present_count = sum(
        row["artifact_support"]["decision_ladder_row_present"] for row in audit_rows
    )
    return {
        "current_project_stage": str(packet_summary.get("current_project_stage", "")),
        "m14_trading_date": str(packet_summary.get("m14_trading_date", "")),
        "challenge_progress_label": str(packet_summary.get("challenge_progress_label", "")),
        "source_review_row_count": int_or_zero(packet_summary.get("review_row_count")),
        "source_review_packet_row_count": int_or_zero(packet_summary.get("review_row_count")),
        "audit_row_count": len(audit_rows),
        "held_row_count": len(held_rows),
        "ready_for_artifact_review_now_count": state_counts.get("ready_for_artifact_review_now", 0),
        "pre_review_ready_wait_fresh_evidence_count": state_counts.get(
            "pre_review_ready_wait_fresh_evidence", 0
        ),
        "needs_supporting_artifact_backfill_count": state_counts.get(
            "needs_supporting_artifact_backfill", 0
        ),
        "fresh_dependent_count": fresh_dependent_count,
        "fresh_dependent_audit_count": fresh_dependent_count,
        "artifact_only_count": artifact_only_count,
        "artifact_only_audit_count": artifact_only_count,
        "external_reference_required_count": external_reference_required_count,
        "external_reference_ready_count": external_reference_ready_count,
        "external_reference_artifact_audit_count": external_reference_required_count,
        "external_reference_artifact_ready_count": external_reference_ready_count,
        "shadow_parameter_required_count": shadow_parameter_required_count,
        "shadow_parameter_artifact_audit_count": shadow_parameter_required_count,
        "shadow_parameter_artifact_ready_count": shadow_parameter_artifact_ready_count,
        "activation_gate_artifact_ready_count": activation_gate_artifact_ready_count,
        "decision_ladder_present_count": decision_ladder_present_count,
        "decision_ladder_context_ready_count": decision_ladder_present_count,
        "source_recheck_review_count": lane_counts.get("shadow_plugin_research", 0),
        "review_notes_preparable_count": sum(row["can_prepare_review_notes_now"] for row in audit_rows),
        "audit_state_counts": dict(sorted(state_counts.items())),
        "audit_priority_counts": dict(sorted(priority_counts.items())),
        "audit_lane_counts": dict(sorted(lane_counts.items())),
        "review_can_close_gap_now_count": 0,
        "review_can_promote_now_count": 0,
        "review_can_discard_now_count": 0,
        "parameter_mutation_allowed_now_count": 0,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
    }


def needs_shadow_artifact(lane: str, missing: list[str]) -> bool:
    return "shadow_parameter_review" in missing or lane == "rescue_shadow_parameter_review"


def audit_state_for(requires_fresh_refresh: bool, missing_artifacts: list[str]) -> str:
    if missing_artifacts:
        return "needs_supporting_artifact_backfill"
    if requires_fresh_refresh:
        return "pre_review_ready_wait_fresh_evidence"
    return "ready_for_artifact_review_now"


def match_rows(strategy_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for row in rows:
        row_strategy = str(row.get("strategy_id", ""))
        row_parent = str(row.get("parent_strategy_id", ""))
        runtime_ids = {str(item) for item in row.get("runtime_ids", []) if str(item)}
        rescue_runtime_ids = {str(item) for item in row.get("rescue_runtime_strategy_ids", []) if str(item)}
        if strategy_id in {row_strategy, row_parent} or strategy_id in runtime_ids or strategy_id in rescue_runtime_ids:
            matches.append(dict(row))
    return matches


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Pre-refresh review audit checked {summary['audit_row_count']} review rows. "
        f"{summary['ready_for_artifact_review_now_count']} rows are artifact-only and ready for review now; "
        f"{summary['pre_review_ready_wait_fresh_evidence_count']} rows have enough supporting artifacts but still wait for M12.47 fresh evidence; "
        f"{summary['needs_supporting_artifact_backfill_count']} rows need supporting artifact backfill before review. "
        f"Shadow-parameter artifact readiness is {summary['shadow_parameter_artifact_ready_count']}/"
        f"{summary['shadow_parameter_artifact_audit_count']}; external-reference readiness is "
        f"{summary['external_reference_artifact_ready_count']}/{summary['external_reference_artifact_audit_count']}. "
        "This audit cannot close gaps, promote, discard, mutate parameters, run M12.37 manually, or enable broker/live."
    )


def build_review_audit_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Pre-Refresh Review Audit",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Audit rows / held rows: `{summary['audit_row_count']}/{summary['held_row_count']}`",
        f"- Ready now / ready waiting fresh / needs artifact backfill: `{summary['ready_for_artifact_review_now_count']}/{summary['pre_review_ready_wait_fresh_evidence_count']}/{summary['needs_supporting_artifact_backfill_count']}`",
        f"- Fresh-dependent / artifact-only rows: `{summary['fresh_dependent_audit_count']}/{summary['artifact_only_audit_count']}`",
        f"- Shadow artifact ready/required: `{summary['shadow_parameter_artifact_ready_count']}/{summary['shadow_parameter_artifact_audit_count']}`",
        f"- External-reference artifact ready/required: `{summary['external_reference_artifact_ready_count']}/{summary['external_reference_artifact_audit_count']}`",
        f"- Close/promote/discard/mutate allowed now: `{summary['review_can_close_gap_now_count']}/{summary['review_can_promote_now_count']}/{summary['review_can_discard_now_count']}/{summary['parameter_mutation_allowed_now_count']}`",
        "- Boundary: artifact audit only; no broker/live, no real orders, no paper approval, no manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Audit Rows",
        "",
    ]
    for row in payload["audit_rows"]:
        lines.extend(
            [
                f"### {row['priority']} {row['strategy_id']}",
                "",
                f"- State: `{row['audit_state']}`",
                f"- Lane: `{row['burn_down_lane']}`",
                f"- Focus: {row['review_focus']}",
                f"- Missing supporting artifacts: `{', '.join(row['missing_supporting_artifacts'])}`",
                f"- Fresh evidence required before decision: `{row['fresh_evidence_required_before_decision']}`",
                f"- Can prepare review notes now: `{row['can_prepare_review_notes_now']}`",
                f"- Can close/promote/discard/mutate now: `{row['review_can_close_gap_now']}/{row['review_can_promote_now']}/{row['review_can_discard_now']}/{row['parameter_mutation_allowed_now']}`",
                "",
            ]
        )
    if payload["held_rows"]:
        lines.extend(["## Held Rows", ""])
        for row in payload["held_rows"]:
            lines.append(f"- `{row['strategy_id']}`: `{row['audit_state']}` - {row['hold_reason']}")
    return "\n".join(lines)


def priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(priority, 9)


def hard_boundaries() -> dict[str, bool]:
    return {
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
