#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_pre_refresh_review_packet.json"
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
class StrategyPreRefreshReviewPacketConfig:
    stage: str
    strategy_evidence_gap_burndown_path: Path
    rescue_external_reference_map_path: Path
    review_packet_json_path: Path
    review_packet_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategyPreRefreshReviewPacketConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategyPreRefreshReviewPacketConfig(
        stage=str(payload["stage"]),
        strategy_evidence_gap_burndown_path=resolve_repo_path(
            inputs["m14_strategy_evidence_gap_burndown"]
        ),
        rescue_external_reference_map_path=resolve_repo_path(
            inputs["m14_rescue_external_reference_map"]
        ),
        review_packet_json_path=resolve_repo_path(outputs["review_packet_json"]),
        review_packet_md_path=resolve_repo_path(outputs["review_packet_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategyPreRefreshReviewPacketConfig) -> None:
    if config.stage != "M14.strategy_pre_refresh_review_packet":
        raise ValueError("M14 strategy pre-refresh review packet stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy pre-refresh review packet must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy pre-refresh review packet must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy pre-refresh review packet cannot enable {key}")


def run_m14_strategy_pre_refresh_review_packet(
    config: StrategyPreRefreshReviewPacketConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    burndown = read_json(config.strategy_evidence_gap_burndown_path)
    external_map = read_json(config.rescue_external_reference_map_path)
    external_rows = list(external_map.get("rescue_reference_rows", [])) + list(
        external_map.get("broker_blocker_reference_rows", [])
    )
    review_rows = [
        build_review_row(dict(row), matching_external_reference_rows(dict(row), external_rows))
        for row in burndown.get("burndown_rows", [])
        if bool(row.get("pre_refresh_review_available", False))
    ]
    review_rows.sort(key=lambda row: (priority_rank(row["priority"]), int_or_zero(row["sequence_rank"]), row["strategy_id"]))
    held_rows = [
        build_held_row(dict(row))
        for row in burndown.get("burndown_rows", [])
        if not bool(row.get("pre_refresh_review_available", False))
    ]
    summary = build_summary(
        burndown=burndown,
        external_map=external_map,
        review_rows=review_rows,
        held_rows=held_rows,
    )
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-pre-refresh-review-packet.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_evidence_gap_burndown": project_path(config.strategy_evidence_gap_burndown_path),
            "m14_rescue_external_reference_map": project_path(config.rescue_external_reference_map_path),
        },
        "summary": summary,
        "review_rows": review_rows,
        "held_rows": held_rows,
        "review_policy": {
            "purpose": "Convert pre-refresh-available burndown rows into a no-mutation artifact review packet.",
            "allowed_now": "Review existing artifacts, shadow specs, activation gates, source evidence, and external-reference checklists.",
            "not_allowed_now": "No evidence-changing refresh, parameter change, registry/account-spec mutation, broker readiness status mutation, broker/live path, real order, paper approval, or manual M12.37 once-mode.",
            "completion_rule": "A pre-refresh review can prepare notes and acceptance checks, but cannot close rescue, promotion, final-discard, or parameter-activation requirements by itself.",
        },
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.review_packet_json_path, payload)
    config.review_packet_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.review_packet_md_path.write_text(build_review_packet_md(payload), encoding="utf-8")
    return payload


def build_review_row(
    burndown_row: dict[str, Any],
    external_reference_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    lane = str(burndown_row.get("burn_down_lane", ""))
    missing = list(burndown_row.get("missing_evidence_categories", []))
    external_pattern_ids = sorted(
        {
            str(pattern_id)
            for row in external_reference_rows
            for pattern_id in row.get("external_reference_pattern_ids", [])
            if str(pattern_id)
        }
    )
    external_actions = list(
        dict.fromkeys(
            str(row.get("pre_refresh_action") or row.get("local_application", ""))
            for row in external_reference_rows
            if str(row.get("pre_refresh_action") or row.get("local_application", ""))
        )
    )
    review_lanes = sorted(
        {
            str(lane_name)
            for row in external_reference_rows
            for lane_name in row.get("local_review_lanes", [])
            if str(lane_name)
        }
    )
    return {
        "review_id": f"pre_refresh::{burndown_row.get('strategy_id', '')}",
        "strategy_id": str(burndown_row.get("strategy_id", "")),
        "display_name": str(burndown_row.get("display_name", "")),
        "priority": str(burndown_row.get("priority", "")),
        "sequence_rank": int_or_zero(burndown_row.get("sequence_rank")),
        "burn_down_lane": lane,
        "review_focus": review_focus_for(lane, missing),
        "pre_refresh_review_actions": list(burndown_row.get("pre_refresh_review_actions", [])),
        "external_reference_pattern_ids": external_pattern_ids,
        "external_reference_review_actions": external_actions,
        "external_reference_local_review_lanes": review_lanes,
        "requires_m12_47_fresh_refresh": bool(burndown_row.get("requires_m12_47_fresh_refresh", False)),
        "fresh_refresh_dependency_state": (
            "waiting_for_m12_47_fresh_refresh"
            if bool(burndown_row.get("requires_m12_47_fresh_refresh", False))
            else "artifact_only_pre_refresh_review"
        ),
        "next_evidence_to_collect": str(burndown_row.get("next_evidence_to_collect", "")),
        "blocked_by": list(burndown_row.get("blocked_by", [])),
        "missing_evidence_categories": missing,
        "review_can_close_gap_now": False,
        "review_can_promote_now": False,
        "review_can_discard_now": False,
        "parameter_mutation_allowed_now": False,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
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


def build_held_row(burndown_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": str(burndown_row.get("strategy_id", "")),
        "priority": str(burndown_row.get("priority", "")),
        "burn_down_lane": str(burndown_row.get("burn_down_lane", "")),
        "hold_reason": "No useful pre-refresh review action is available; wait for rescue A/B or manual M14 review evidence.",
        "next_evidence_to_collect": str(burndown_row.get("next_evidence_to_collect", "")),
        "review_can_close_gap_now": False,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
    }


def build_summary(
    *,
    burndown: dict[str, Any],
    external_map: dict[str, Any],
    review_rows: list[dict[str, Any]],
    held_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    burndown_summary = burndown.get("summary", {})
    external_summary = external_map.get("summary", {})
    priority_counts = Counter(row["priority"] for row in review_rows)
    lane_counts = Counter(row["burn_down_lane"] for row in review_rows)
    action_counts = Counter(
        action
        for row in review_rows
        for action in row["pre_refresh_review_actions"]
    )
    return {
        "current_project_stage": str(burndown_summary.get("current_project_stage", "")),
        "m14_trading_date": str(burndown_summary.get("m14_trading_date", "")),
        "challenge_progress_label": str(burndown_summary.get("challenge_progress_label", "")),
        "source_burndown_row_count": int_or_zero(burndown_summary.get("burndown_row_count")),
        "review_row_count": len(review_rows),
        "held_no_pre_refresh_action_count": len(held_rows),
        "held_no_pre_refresh_action_strategy_ids": [row["strategy_id"] for row in held_rows],
        "p0_review_count": priority_counts.get("P0", 0),
        "p1_review_count": priority_counts.get("P1", 0),
        "p2_review_count": priority_counts.get("P2", 0),
        "review_priority_counts": dict(sorted(priority_counts.items())),
        "review_lane_counts": dict(sorted(lane_counts.items())),
        "review_action_counts": dict(sorted(action_counts.items())),
        "m12_47_fresh_refresh_dependent_review_count": sum(
            1 for row in review_rows if row["requires_m12_47_fresh_refresh"]
        ),
        "artifact_only_review_count": sum(
            1 for row in review_rows if not row["requires_m12_47_fresh_refresh"]
        ),
        "shadow_parameter_review_row_count": lane_counts.get("rescue_shadow_parameter_review", 0),
        "approved_internal_sim_review_row_count": lane_counts.get("approved_internal_sim_refresh", 0),
        "first_ledger_review_row_count": lane_counts.get("first_rescue_ledger", 0),
        "detector_rebuild_review_row_count": lane_counts.get("detector_rebuild_ab", 0),
        "source_recheck_review_row_count": lane_counts.get("shadow_plugin_research", 0),
        "external_reference_review_row_count": sum(
            1 for row in review_rows if row["external_reference_pattern_ids"]
        ),
        "external_reference_project_count": int_or_zero(external_summary.get("external_reference_project_count")),
        "external_reference_copy_trading_allowed": False,
        "review_can_close_gap_now_count": 0,
        "review_can_promote_now_count": 0,
        "review_can_discard_now_count": 0,
        "parameter_mutation_allowed_now_count": 0,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
    }


def review_focus_for(lane: str, missing: list[str]) -> str:
    if lane == "approved_internal_sim_refresh":
        return "Confirm approved internal-sim runtime and broker-watch contracts before the next M12.47 refresh."
    if lane == "first_rescue_ledger":
        return "Audit registry, account input, signal ledger, and account ledger paths for the first rescue-specific ledger."
    if lane == "rescue_shadow_parameter_review":
        return "Review shadow parameter families and activation gates, but keep all parameter implementation frozen."
    if lane == "detector_rebuild_ab":
        return "Review detector rebuild diagnostics and source examples before any post-refresh A/B decision."
    if lane == "shadow_plugin_research" or "independent_strategy_evidence_missing" in missing:
        return "Recheck source evidence and keep the item in shadow/plugin/research coverage unless independent evidence is proven."
    return "Review existing artifacts only; do not close the gap without fresh evidence and manual M14 review."


def matching_external_reference_rows(
    burndown_row: dict[str, Any],
    external_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    strategy_id = str(burndown_row.get("strategy_id", ""))
    matches: list[dict[str, Any]] = []
    for row in external_rows:
        row_strategy = str(row.get("strategy_id", ""))
        row_parent = str(row.get("parent_strategy_id", ""))
        runtime_ids = {str(item) for item in row.get("runtime_ids", []) if str(item)}
        if strategy_id in {row_strategy, row_parent} or strategy_id in runtime_ids:
            matches.append(dict(row))
    return matches


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Pre-refresh review packet has {summary['review_row_count']} review rows "
        f"({summary['p0_review_count']} P0, {summary['p1_review_count']} P1, {summary['p2_review_count']} P2) "
        f"and {summary['held_no_pre_refresh_action_count']} held row. "
        f"{summary['m12_47_fresh_refresh_dependent_review_count']} review rows still depend on M12.47 fresh evidence, "
        f"while {summary['artifact_only_review_count']} can only receive artifact/source review before refresh. "
        f"External-reference checklists apply to {summary['external_reference_review_row_count']} rows. "
        "No review row can close gaps, promote, discard, mutate parameters, run M12.37 manually, or enable broker/live."
    )


def build_review_packet_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Pre-Refresh Review Packet",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Review rows / held rows: `{summary['review_row_count']}/{summary['held_no_pre_refresh_action_count']}`",
        f"- P0/P1/P2 review rows: `{summary['p0_review_count']}/{summary['p1_review_count']}/{summary['p2_review_count']}`",
        f"- Fresh-dependent / artifact-only rows: `{summary['m12_47_fresh_refresh_dependent_review_count']}/{summary['artifact_only_review_count']}`",
        f"- External-reference review rows: `{summary['external_reference_review_row_count']}`",
        f"- Close/promote/discard/mutate allowed now: `{summary['review_can_close_gap_now_count']}/{summary['review_can_promote_now_count']}/{summary['review_can_discard_now_count']}/{summary['parameter_mutation_allowed_now_count']}`",
        "- Boundary: review-only; no broker/live, no real orders, no paper approval, no manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Review Rows",
        "",
    ]
    for row in payload["review_rows"]:
        lines.extend(
            [
                f"### {row['priority']} {row['strategy_id']}",
                "",
                f"- Lane: `{row['burn_down_lane']}`",
                f"- Focus: {row['review_focus']}",
                f"- Fresh dependency: `{row['fresh_refresh_dependency_state']}`",
                f"- Next evidence: {row['next_evidence_to_collect']}",
                f"- Pre-refresh actions: `{'; '.join(row['pre_refresh_review_actions'])}`",
                f"- External patterns: `{', '.join(row['external_reference_pattern_ids'])}`",
                f"- Can close/promote/discard/mutate now: `{row['review_can_close_gap_now']}/{row['review_can_promote_now']}/{row['review_can_discard_now']}/{row['parameter_mutation_allowed_now']}`",
                "",
            ]
        )
    if payload["held_rows"]:
        lines.extend(["## Held Rows", ""])
        for row in payload["held_rows"]:
            lines.extend(
                [
                    f"- `{row['strategy_id']}`: {row['hold_reason']} Next evidence: {row['next_evidence_to_collect']}",
                ]
            )
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
