#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_evidence_gap_burndown.json"
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
class StrategyEvidenceGapBurndownConfig:
    stage: str
    strategy_evidence_gap_matrix_path: Path
    objective_execution_plan_path: Path
    rescue_parameter_experiment_queue_path: Path
    rescue_parameter_activation_gate_path: Path
    rescue_external_reference_map_path: Path
    burndown_json_path: Path
    burndown_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategyEvidenceGapBurndownConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategyEvidenceGapBurndownConfig(
        stage=str(payload["stage"]),
        strategy_evidence_gap_matrix_path=resolve_repo_path(inputs["m14_strategy_evidence_gap_matrix"]),
        objective_execution_plan_path=resolve_repo_path(inputs["m14_objective_execution_plan"]),
        rescue_parameter_experiment_queue_path=resolve_repo_path(
            inputs["m14_rescue_parameter_experiment_queue"]
        ),
        rescue_parameter_activation_gate_path=resolve_repo_path(
            inputs["m14_rescue_parameter_activation_gate"]
        ),
        rescue_external_reference_map_path=resolve_repo_path(inputs["m14_rescue_external_reference_map"]),
        burndown_json_path=resolve_repo_path(outputs["burndown_json"]),
        burndown_md_path=resolve_repo_path(outputs["burndown_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategyEvidenceGapBurndownConfig) -> None:
    if config.stage != "M14.strategy_evidence_gap_burndown":
        raise ValueError("M14 strategy evidence gap burndown stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy evidence gap burndown must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy evidence gap burndown must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy evidence gap burndown cannot enable {key}")


def run_m14_strategy_evidence_gap_burndown(
    config: StrategyEvidenceGapBurndownConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    gap_matrix = read_json(config.strategy_evidence_gap_matrix_path)
    execution_plan = read_json(config.objective_execution_plan_path)
    experiment_queue = read_json(config.rescue_parameter_experiment_queue_path)
    activation_gate = read_json(config.rescue_parameter_activation_gate_path)
    external_map = read_json(config.rescue_external_reference_map_path)

    experiment_rows = list(experiment_queue.get("experiment_rows", []))
    activation_rows = list(activation_gate.get("gate_rows", []))
    execution_actions = list(execution_plan.get("execution_actions", []))
    burndown_rows = [
        build_burndown_row(
            gap_row=dict(row),
            experiment_rows=matching_strategy_rows(dict(row), experiment_rows),
            activation_rows=matching_strategy_rows(dict(row), activation_rows),
            execution_actions=matching_execution_actions(dict(row), execution_actions),
        )
        for row in gap_matrix.get("gap_rows", [])
    ]
    burndown_rows.sort(key=lambda row: (priority_rank(row["priority"]), int_or_zero(row["sequence_rank"]), row["strategy_id"]))
    summary = build_summary(
        gap_matrix=gap_matrix,
        execution_plan=execution_plan,
        experiment_queue=experiment_queue,
        activation_gate=activation_gate,
        external_map=external_map,
        burndown_rows=burndown_rows,
    )
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-evidence-gap-burndown.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_evidence_gap_matrix": project_path(config.strategy_evidence_gap_matrix_path),
            "m14_objective_execution_plan": project_path(config.objective_execution_plan_path),
            "m14_rescue_parameter_experiment_queue": project_path(
                config.rescue_parameter_experiment_queue_path
            ),
            "m14_rescue_parameter_activation_gate": project_path(
                config.rescue_parameter_activation_gate_path
            ),
            "m14_rescue_external_reference_map": project_path(config.rescue_external_reference_map_path),
        },
        "summary": summary,
        "burndown_rows": burndown_rows,
        "burndown_policy": {
            "purpose": "Turn open M14 strategy evidence gaps into an ordered rescue/internal-sim work queue.",
            "approved_strategy_rule": "Approved internal-sim strategies may only continue through the next M12.47-supervised refresh and post-refresh M13/M14 recompute.",
            "rescue_rule": "Weak strategies keep rescue or shadow review until first ledger, rescue 10-day A/B, and manual M14 review evidence are complete.",
            "pre_refresh_rule": "Before fresh market evidence exists, only artifact review, shadow-spec review, and external-reference checklist work are allowed.",
            "mutation_rule": "No parameter, registry, account-spec, broker-readiness, broker/live, or manual M12.37 once-mode mutation is allowed.",
        },
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.burndown_json_path, payload)
    config.burndown_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.burndown_md_path.write_text(build_burndown_md(payload), encoding="utf-8")
    return payload


def build_burndown_row(
    *,
    gap_row: dict[str, Any],
    experiment_rows: list[dict[str, Any]],
    activation_rows: list[dict[str, Any]],
    execution_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    missing = list(gap_row.get("missing_evidence_categories", []))
    lane = burn_down_lane_for(gap_row, missing)
    priority = priority_for(gap_row, lane, missing)
    next_evidence = next_evidence_for(missing)
    blocked_by = blocked_by_for(missing)
    pre_refresh_actions = pre_refresh_actions_for(missing, experiment_rows, activation_rows)
    action_ids = [str(row.get("action_id", "")) for row in execution_actions if row.get("action_id")]
    return {
        "strategy_id": str(gap_row.get("strategy_id", "")),
        "display_name": str(gap_row.get("display_name", "")),
        "route_category": str(gap_row.get("route_category", "")),
        "gap_state": str(gap_row.get("gap_state", "")),
        "burn_down_lane": lane,
        "priority": priority,
        "sequence_rank": sequence_rank_for(priority, lane, gap_row),
        "open_evidence_gap_count": int_or_zero(gap_row.get("open_evidence_gap_count")),
        "missing_evidence_categories": missing,
        "blocked_by": blocked_by,
        "next_evidence_to_collect": next_evidence,
        "pre_refresh_review_available": bool(pre_refresh_actions),
        "pre_refresh_review_actions": pre_refresh_actions,
        "execution_action_ids": action_ids,
        "requires_m12_47_fresh_refresh": bool(gap_row.get("requires_m12_47_fresh_refresh", False)),
        "can_continue_internal_sim_now": bool(gap_row.get("can_continue_internal_sim_now", False)),
        "can_promote_now": False,
        "continue_rescue": bool(gap_row.get("continue_rescue", False)),
        "final_discard_allowed": False,
        "manual_review_ready": bool(gap_row.get("manual_review_ready", False)),
        "broker_watch": bool(gap_row.get("broker_watch", False)),
        "rescue_ab_observed_days_max": int_or_zero(gap_row.get("rescue_ab_observed_days_max")),
        "rescue_ab_remaining_days_min": int_or_zero(gap_row.get("rescue_ab_remaining_days_min")),
        "candidate_variant_count": int_or_zero(gap_row.get("candidate_variant_count")),
        "parameter_experiment_row_count": len(experiment_rows),
        "activation_gate_row_count": len(activation_rows),
        "activation_waiting_for_fresh_refresh_count": sum(
            1 for row in activation_rows if str(row.get("gate_state", "")) == "waiting_for_m12_47_fresh_refresh"
        ),
        "shadow_review_candidate_count": sum(1 for row in activation_rows if row.get("shadow_review_candidate")),
        "allowed_operations": ["artifact_review", "m12_47_supervised_refresh_review"],
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


def build_summary(
    *,
    gap_matrix: dict[str, Any],
    execution_plan: dict[str, Any],
    experiment_queue: dict[str, Any],
    activation_gate: dict[str, Any],
    external_map: dict[str, Any],
    burndown_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    gap_summary = gap_matrix.get("summary", {})
    execution_summary = execution_plan.get("summary", {})
    experiment_summary = experiment_queue.get("summary", {})
    activation_summary = activation_gate.get("summary", {})
    external_summary = external_map.get("summary", {})
    priority_counts = Counter(row["priority"] for row in burndown_rows)
    lane_counts = Counter(row["burn_down_lane"] for row in burndown_rows)
    return {
        "current_project_stage": str(gap_summary.get("current_project_stage", "")),
        "m14_trading_date": str(gap_summary.get("m14_trading_date", "")),
        "challenge_progress_label": str(gap_summary.get("challenge_progress_label", "")),
        "burndown_row_count": len(burndown_rows),
        "open_evidence_gap_row_count": int_or_zero(gap_summary.get("open_evidence_gap_row_count")),
        "requires_m12_47_fresh_refresh_count": sum(
            1 for row in burndown_rows if row["requires_m12_47_fresh_refresh"]
        ),
        "ready_for_internal_sim_refresh_count": lane_counts.get("approved_internal_sim_refresh", 0),
        "first_ledger_watch_row_count": sum(
            1 for row in burndown_rows if "first_m13_rescue_ledger" in row["missing_evidence_categories"]
        ),
        "rescue_ab_collection_row_count": sum(
            1 for row in burndown_rows if "rescue_10_day_ab_window" in row["missing_evidence_categories"]
        ),
        "shadow_review_wait_row_count": sum(
            1 for row in burndown_rows if "shadow_parameter_review" in row["missing_evidence_categories"]
        ),
        "shadow_plugin_hold_row_count": lane_counts.get("shadow_plugin_research", 0),
        "pre_refresh_review_available_count": sum(
            1 for row in burndown_rows if row["pre_refresh_review_available"]
        ),
        "p0_row_count": priority_counts.get("P0", 0),
        "p1_row_count": priority_counts.get("P1", 0),
        "p2_row_count": priority_counts.get("P2", 0),
        "priority_counts": dict(sorted(priority_counts.items())),
        "burn_down_lane_counts": dict(sorted(lane_counts.items())),
        "objective_execution_action_count": int_or_zero(execution_summary.get("execution_action_count")),
        "objective_execution_p0_action_count": int_or_zero(execution_summary.get("p0_action_count")),
        "objective_execution_waiting_for_fresh_refresh_action_count": int_or_zero(
            execution_summary.get("waiting_for_fresh_refresh_action_count")
        ),
        "parameter_experiment_row_count": int_or_zero(experiment_summary.get("experiment_row_count")),
        "parameter_experiment_allowed_now_count": int_or_zero(experiment_summary.get("allowed_now_count")),
        "parameter_activation_gate_row_count": int_or_zero(activation_summary.get("gate_row_count")),
        "parameter_activation_shadow_review_candidate_count": int_or_zero(
            activation_summary.get("shadow_review_candidate_count")
        ),
        "parameter_activation_waiting_for_fresh_refresh_count": int_or_zero(
            activation_summary.get("waiting_for_fresh_refresh_count")
        ),
        "external_reference_project_count": int_or_zero(external_summary.get("external_reference_project_count")),
        "external_reference_mapped_rescue_row_count": int_or_zero(
            external_summary.get("mapped_rescue_row_count")
        ),
        "external_reference_broker_blocker_row_count": int_or_zero(
            external_summary.get("broker_blocker_reference_row_count")
        ),
        "promotion_candidate_count": 0,
        "final_discard_allowed_count": 0,
        "manual_execution_allowed_count": 0,
        "parameter_mutation_allowed_count": 0,
        "broker_or_live_enabled": False,
        "manual_m12_37_once_allowed": False,
    }


def burn_down_lane_for(gap_row: dict[str, Any], missing: list[str]) -> str:
    gap_state = str(gap_row.get("gap_state", ""))
    route_category = str(gap_row.get("route_category", ""))
    if gap_state == "approved_wait_next_refresh":
        return "approved_internal_sim_refresh"
    if "first_m13_rescue_ledger" in missing:
        return "first_rescue_ledger"
    if route_category == "rebuild_detector_then_ab" or "detector_rebuild_evidence" in missing:
        return "detector_rebuild_ab"
    if "shadow_parameter_review" in missing:
        return "rescue_shadow_parameter_review"
    if "rescue_10_day_ab_window" in missing:
        return "rescue_ab_collection"
    if "independent_strategy_evidence_missing" in missing:
        return "shadow_plugin_research"
    return "manual_review"


def priority_for(gap_row: dict[str, Any], lane: str, missing: list[str]) -> str:
    if lane in {"approved_internal_sim_refresh", "first_rescue_ledger"}:
        return "P0"
    if "m12_47_fresh_refresh" in missing and lane != "shadow_plugin_research":
        return "P0"
    if lane in {"rescue_shadow_parameter_review", "rescue_ab_collection", "detector_rebuild_ab"}:
        return "P1"
    if bool(gap_row.get("broker_watch", False)):
        return "P1"
    return "P2"


def sequence_rank_for(priority: str, lane: str, gap_row: dict[str, Any]) -> int:
    lane_rank = {
        "approved_internal_sim_refresh": 10,
        "first_rescue_ledger": 20,
        "rescue_shadow_parameter_review": 30,
        "rescue_ab_collection": 40,
        "detector_rebuild_ab": 50,
        "shadow_plugin_research": 70,
        "manual_review": 90,
    }.get(lane, 99)
    return priority_rank(priority) * 100 + lane_rank + int_or_zero(gap_row.get("route_rank"))


def priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(priority, 9)


def next_evidence_for(missing: list[str]) -> str:
    labels = {
        "m12_47_fresh_refresh": "Next M12.47-supervised fresh refresh and post-run M13 ledger update.",
        "first_m13_rescue_ledger": "First rescue-specific M13 signal/account ledger row.",
        "rescue_10_day_ab_window": "10 trading-day rescue A/B evidence window.",
        "shadow_parameter_review": "Parameter shadow spec and activation-gate review after fresh evidence.",
        "detector_rebuild_evidence": "Detector rebuild evidence from current-cycle diagnostics.",
        "independent_strategy_evidence_missing": "Independent strategy evidence beyond plugin or research-only coverage.",
        "manual_m14_review": "Manual M14 review after machine evidence is complete.",
    }
    for key in labels:
        if key in missing:
            return labels[key]
    return "Manual M14 review after current evidence is complete."


def blocked_by_for(missing: list[str]) -> list[str]:
    blockers = {
        "m12_47_fresh_refresh": "m12_47_fresh_refresh_not_observed",
        "first_m13_rescue_ledger": "first_rescue_specific_ledger_missing",
        "rescue_10_day_ab_window": "rescue_10_day_ab_window_incomplete",
        "shadow_parameter_review": "shadow_parameter_review_not_open",
        "detector_rebuild_evidence": "detector_rebuild_evidence_missing",
        "independent_strategy_evidence_missing": "independent_strategy_evidence_missing",
        "manual_m14_review": "manual_m14_review_pending",
    }
    return [blockers[key] for key in missing if key in blockers]


def pre_refresh_actions_for(
    missing: list[str],
    experiment_rows: list[dict[str, Any]],
    activation_rows: list[dict[str, Any]],
) -> list[str]:
    actions: list[str] = []
    if "m12_47_fresh_refresh" in missing:
        actions.append("Review existing artifacts only; wait for M12.47 to own any evidence-changing refresh.")
    if "shadow_parameter_review" in missing and (experiment_rows or activation_rows):
        actions.append("Check shadow parameter families and activation gates for review readiness; do not mutate parameters.")
    if any(str(row.get("experiment_family", "")).endswith("_shadow") for row in experiment_rows):
        actions.append("Review broker-blocker or target/stop shadow variants as internal-sim evidence contracts only.")
    if "detector_rebuild_evidence" in missing:
        actions.append("Review detector rebuild diagnostics and source examples before any new variant is proposed.")
    if "independent_strategy_evidence_missing" in missing:
        actions.append("Recheck source evidence and keep the item in shadow/plugin/research coverage unless an independent account is justified.")
    return list(dict.fromkeys(actions))


def matching_strategy_rows(gap_row: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strategy_id = str(gap_row.get("strategy_id", ""))
    related_ids = {strategy_id, *[str(item) for item in gap_row.get("rescue_runtime_strategy_ids", []) if str(item)]}
    return [
        dict(row)
        for row in rows
        if str(row.get("strategy_id", "")) in related_ids
        or str(row.get("parent_strategy_id", "")) in related_ids
    ]


def matching_execution_actions(gap_row: dict[str, Any], actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strategy_id = str(gap_row.get("strategy_id", ""))
    related_ids = {strategy_id, *[str(item) for item in gap_row.get("rescue_runtime_strategy_ids", []) if str(item)]}
    return [
        dict(action)
        for action in actions
        if related_ids.intersection({str(item) for item in action.get("strategy_ids", [])})
    ]


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Strategy evidence burndown has {summary['burndown_row_count']} rows: "
        f"{summary['p0_row_count']} P0, {summary['p1_row_count']} P1, and {summary['p2_row_count']} P2. "
        f"{summary['ready_for_internal_sim_refresh_count']} approved strategies are waiting for the next "
        f"M12.47-supervised internal-sim refresh; {summary['first_ledger_watch_row_count']} rows need first "
        f"rescue ledgers; {summary['rescue_ab_collection_row_count']} need rescue 10-day A/B evidence; "
        f"{summary['shadow_review_wait_row_count']} need shadow-review evidence. "
        f"Pre-refresh artifact review is available for {summary['pre_refresh_review_available_count']} rows, "
        "but broker/live, real orders, paper approval, parameter mutation, registry/account-spec mutation, "
        "broker-readiness mutation, and manual M12.37 once-mode remain disabled."
    )


def build_burndown_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Evidence Gap Burndown",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Rows / open gaps: `{summary['burndown_row_count']}/{summary['open_evidence_gap_row_count']}`",
        f"- Priority P0/P1/P2: `{summary['p0_row_count']}/{summary['p1_row_count']}/{summary['p2_row_count']}`",
        f"- Approved refresh / first-ledger / rescue A/B / shadow-review: `{summary['ready_for_internal_sim_refresh_count']}/{summary['first_ledger_watch_row_count']}/{summary['rescue_ab_collection_row_count']}/{summary['shadow_review_wait_row_count']}`",
        f"- Pre-refresh review rows: `{summary['pre_refresh_review_available_count']}`",
        f"- Promotion candidates / final discard allowed: `{summary['promotion_candidate_count']}/{summary['final_discard_allowed_count']}`",
        "- Boundary: internal simulated accounts only; no broker/live, no real orders, no paper approval, no manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Burndown Rows",
        "",
    ]
    for row in payload["burndown_rows"]:
        lines.extend(
            [
                f"### {row['priority']} {row['strategy_id']}",
                "",
                f"- Lane: `{row['burn_down_lane']}`",
                f"- Gap state: `{row['gap_state']}`",
                f"- Missing evidence: `{', '.join(row['missing_evidence_categories'])}`",
                f"- Next evidence: {row['next_evidence_to_collect']}",
                f"- Blocked by: `{', '.join(row['blocked_by'])}`",
                f"- Pre-refresh review: `{row['pre_refresh_review_available']}`",
                f"- Execution actions: `{', '.join(row['execution_action_ids'])}`",
                f"- Candidate variants / activation rows: `{row['candidate_variant_count']}/{row['activation_gate_row_count']}`",
                f"- Final discard allowed: `{row['final_discard_allowed']}`",
                f"- Parameter mutation allowed: `{row['parameter_mutation']}`",
                "",
            ]
        )
    return "\n".join(lines)


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
