#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_next_step_readiness_matrix.json"
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
    "legacy_historical_profit_planning_input",
)
AUXILIARY_MODULE_PURPOSES = {
    "M10-PA-003": "质量评分和排序模块，给主策略打分",
    "M10-PA-006": "限价入场过滤模块，过滤差入场",
    "M10-PA-010": "图形识别资料模块，帮助视觉策略补证据",
    "M10-PA-014": "目标价计算模块，服务止盈目标",
    "M10-PA-015": "止损和仓位模块，服务风控和数量计算",
    "M10-PA-016": "区间加仓辅助模块，服务已有主策略",
    "AI-TRADER-EXTERNAL": "外部参考信号，只做对照，不复制交易，不覆盖本项目判断",
}


@dataclass(frozen=True, slots=True)
class StrategyNextStepReadinessMatrixConfig:
    stage: str
    strategy_decision_ladder_path: Path
    strategy_evidence_gap_matrix_path: Path
    strategy_evidence_gap_burndown_path: Path
    objective_blocker_burndown_path: Path
    strategy_source_visual_confirmation_response_gate_path: Path
    strategy_future_source_reextract_spec_prep_path: Path
    rescue_ab_evidence_tracker_path: Path
    rescue_parameter_shadow_spec_path: Path
    next_step_matrix_json_path: Path
    next_step_matrix_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategyNextStepReadinessMatrixConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategyNextStepReadinessMatrixConfig(
        stage=str(payload["stage"]),
        strategy_decision_ladder_path=resolve_repo_path(inputs["m14_strategy_decision_ladder"]),
        strategy_evidence_gap_matrix_path=resolve_repo_path(inputs["m14_strategy_evidence_gap_matrix"]),
        strategy_evidence_gap_burndown_path=resolve_repo_path(inputs["m14_strategy_evidence_gap_burndown"]),
        objective_blocker_burndown_path=resolve_repo_path(inputs["m14_objective_blocker_burndown"]),
        strategy_source_visual_confirmation_response_gate_path=resolve_repo_path(
            inputs["m14_strategy_source_visual_confirmation_response_gate"]
        ),
        strategy_future_source_reextract_spec_prep_path=resolve_repo_path(
            inputs["m14_strategy_future_source_reextract_spec_prep"]
        ),
        rescue_ab_evidence_tracker_path=resolve_repo_path(inputs["m14_rescue_ab_evidence_tracker"]),
        rescue_parameter_shadow_spec_path=resolve_repo_path(inputs["m14_rescue_parameter_shadow_spec"]),
        next_step_matrix_json_path=resolve_repo_path(outputs["next_step_matrix_json"]),
        next_step_matrix_md_path=resolve_repo_path(outputs["next_step_matrix_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategyNextStepReadinessMatrixConfig) -> None:
    if config.stage != "M14.strategy_next_step_readiness_matrix":
        raise ValueError("M14 strategy next-step readiness matrix stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy next-step readiness matrix must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy next-step readiness matrix must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy next-step readiness matrix cannot enable {key}")


def run_m14_strategy_next_step_readiness_matrix(
    config: StrategyNextStepReadinessMatrixConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    decision_ladder = read_json(config.strategy_decision_ladder_path)
    gap_matrix = read_json(config.strategy_evidence_gap_matrix_path)
    gap_burndown = read_json(config.strategy_evidence_gap_burndown_path)
    objective_blocker = read_json(config.objective_blocker_burndown_path)
    visual_gate = read_json(config.strategy_source_visual_confirmation_response_gate_path)
    future_spec_prep = read_json(config.strategy_future_source_reextract_spec_prep_path)
    rescue_ab = read_json(config.rescue_ab_evidence_tracker_path)
    shadow_spec = read_json(config.rescue_parameter_shadow_spec_path)

    decision_rows = [dict(row) for row in decision_ladder.get("ladder_rows", [])]
    gap_rows = [dict(row) for row in gap_matrix.get("gap_rows", [])]
    burndown_rows = [dict(row) for row in gap_burndown.get("burndown_rows", [])]
    rescue_rows = [dict(row) for row in rescue_ab.get("rows", [])]
    shadow_rows = [dict(row) for row in shadow_spec.get("spec_rows", [])]
    visual_rows = [dict(row) for row in visual_gate.get("response_gate_rows", [])]
    future_spec_rows = [dict(row) for row in future_spec_prep.get("future_source_reextract_spec_prep_rows", [])]

    decision_by_strategy = {str(row.get("strategy_id", "")): row for row in decision_rows}
    gap_by_strategy = {str(row.get("strategy_id", "")): row for row in gap_rows}
    burndown_by_strategy = {str(row.get("strategy_id", "")): row for row in burndown_rows}
    rescue_by_strategy = index_rows_by_strategy(rescue_rows)
    shadow_by_strategy = index_rows_by_strategy(shadow_rows)
    visual_by_strategy = index_rows_by_strategy(visual_rows)
    future_spec_by_strategy = index_rows_by_strategy(future_spec_rows)

    strategy_ids = {
        strategy_id
        for strategy_id in set(decision_by_strategy) | set(gap_by_strategy) | set(burndown_by_strategy)
        if strategy_id
    }
    matrix_rows = [
        build_matrix_row(
            strategy_id=strategy_id,
            decision_row=decision_by_strategy.get(strategy_id, {}),
            gap_row=gap_by_strategy.get(strategy_id, {}),
            burndown_row=burndown_by_strategy.get(strategy_id, {}),
            rescue_rows=rescue_by_strategy.get(strategy_id, []),
            shadow_rows=shadow_by_strategy.get(strategy_id, []),
            visual_rows=visual_by_strategy.get(strategy_id, []),
            future_spec_rows=future_spec_by_strategy.get(strategy_id, []),
        )
        for strategy_id in strategy_ids
    ]
    matrix_rows.sort(key=lambda row: (int_or_zero(row["route_rank"], 999), int_or_zero(row["sequence_rank"], 999), row["strategy_id"]))

    summary = build_summary(
        decision_ladder=decision_ladder,
        gap_matrix=gap_matrix,
        gap_burndown=gap_burndown,
        objective_blocker=objective_blocker,
        visual_gate=visual_gate,
        future_spec_prep=future_spec_prep,
        rescue_ab=rescue_ab,
        shadow_spec=shadow_spec,
        matrix_rows=matrix_rows,
    )
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-next-step-readiness-matrix.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_decision_ladder": project_path(config.strategy_decision_ladder_path),
            "m14_strategy_evidence_gap_matrix": project_path(config.strategy_evidence_gap_matrix_path),
            "m14_strategy_evidence_gap_burndown": project_path(config.strategy_evidence_gap_burndown_path),
            "m14_objective_blocker_burndown": project_path(config.objective_blocker_burndown_path),
            "m14_strategy_source_visual_confirmation_response_gate": project_path(
                config.strategy_source_visual_confirmation_response_gate_path
            ),
            "m14_strategy_future_source_reextract_spec_prep": project_path(
                config.strategy_future_source_reextract_spec_prep_path
            ),
            "m14_rescue_ab_evidence_tracker": project_path(config.rescue_ab_evidence_tracker_path),
            "m14_rescue_parameter_shadow_spec": project_path(config.rescue_parameter_shadow_spec_path),
        },
        "summary": summary,
        "matrix_rows": matrix_rows,
        "readiness_policy": {
            "purpose": "Give one per-strategy next-step route without changing strategy state.",
            "approved_strategy_rule": "Approved strategies may only continue through the next M12.47-supervised internal simulated-account refresh.",
            "rescue_rule": "Weak or variant strategies stay in rescue A/B, first-ledger watch, or shadow-parameter review until evidence is complete.",
            "source_review_rule": "Auxiliary modules serve screening, targets, stops, sizing, add-ons, visual evidence, or external comparison; they are not standalone trading strategies.",
            "legacy_history_metric_rule": "Legacy account-dashboard history metrics are display-only and are excluded from strategy planning.",
            "mutation_rule": "No parameter, registry, account-spec, broker-readiness, broker/live, or manual M12.37 once-mode mutation is allowed.",
        },
        "legacy_history_metric_exclusion": legacy_history_metric_exclusion(objective_blocker),
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.next_step_matrix_json_path, payload)
    config.next_step_matrix_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.next_step_matrix_md_path.write_text(build_matrix_md(payload), encoding="utf-8")
    return payload


def build_matrix_row(
    *,
    strategy_id: str,
    decision_row: dict[str, Any],
    gap_row: dict[str, Any],
    burndown_row: dict[str, Any],
    rescue_rows: list[dict[str, Any]],
    shadow_rows: list[dict[str, Any]],
    visual_rows: list[dict[str, Any]],
    future_spec_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    route_category = first_non_empty(decision_row.get("route_category"), gap_row.get("route_category"), burndown_row.get("route_category"))
    burn_down_lane = str(burndown_row.get("burn_down_lane", ""))
    gap_state = str(gap_row.get("gap_state") or burndown_row.get("gap_state", ""))
    is_auxiliary = strategy_id in AUXILIARY_MODULE_PURPOSES or route_category == "shadow_or_plugin_hold" or burn_down_lane == "shadow_plugin_research"
    next_step_type = next_step_type_for(route_category, burn_down_lane, gap_state, gap_row, burndown_row)
    if is_auxiliary:
        next_step_type = "auxiliary_module_support"
    current_bucket = current_bucket_for(route_category, burn_down_lane, next_step_type)
    required_next_evidence = [
        clean_auxiliary_text(item)
        for item in required_evidence_for(gap_row, burndown_row, visual_rows, future_spec_rows)
    ]
    future_spec_legacy_input = any(
        bool(row.get("legacy_historical_profit_planning_input")) for row in future_spec_rows
    )
    can_continue_internal_sim_now = bool(first_bool(gap_row.get("can_continue_internal_sim_now"), burndown_row.get("can_continue_internal_sim_now"), decision_row.get("can_advance_next_step")))
    can_promote_now = bool(first_bool(gap_row.get("can_promote_now"), burndown_row.get("can_promote_now"), decision_row.get("can_promote_now")))
    final_discard_allowed = bool(first_bool(gap_row.get("final_discard_allowed"), burndown_row.get("final_discard_allowed"), decision_row.get("final_discard_allowed")))
    parameter_shadow_spec_present = bool(shadow_rows or int_or_zero(burndown_row.get("activation_gate_row_count")) or int_or_zero(burndown_row.get("parameter_experiment_row_count")))
    activation_waiting_for_fresh_refresh = bool(
        int_or_zero(burndown_row.get("activation_waiting_for_fresh_refresh_count"))
        or any(str(row.get("activation_gate_state", "")).startswith("waiting_for_m12_47") for row in shadow_rows)
    )
    return {
        "strategy_id": strategy_id,
        "display_name": clean_auxiliary_text(first_non_empty(decision_row.get("display_name"), gap_row.get("display_name"), burndown_row.get("display_name"))),
        "route_rank": int_or_zero(first_non_empty(decision_row.get("route_rank"), gap_row.get("route_rank")), 999),
        "sequence_rank": int_or_zero(burndown_row.get("sequence_rank"), 999),
        "route_category": route_category,
        "current_bucket": current_bucket,
        "next_step_type": next_step_type,
        "runtime_role": "auxiliary_module" if is_auxiliary else "trading_runtime",
        "auxiliary_module_purpose": auxiliary_module_purpose(strategy_id) if is_auxiliary else "",
        "standalone_trading_allowed": not is_auxiliary,
        "display_action": display_action_for(strategy_id) if is_auxiliary else next_action_for(next_step_type),
        "decision": first_non_empty(decision_row.get("decision"), gap_row.get("decision")),
        "ladder_state": first_non_empty(decision_row.get("ladder_state"), gap_row.get("ladder_state")),
        "gap_state": gap_state,
        "burn_down_lane": burn_down_lane,
        "completed_trading_days": int_or_zero(first_non_empty(decision_row.get("completed_trading_days"), gap_row.get("completed_trading_days"))),
        "can_continue_internal_sim_now": can_continue_internal_sim_now,
        "can_promote_now": can_promote_now,
        "promotion_allowed": can_promote_now,
        "continue_rescue": bool(first_bool(gap_row.get("continue_rescue"), burndown_row.get("continue_rescue"), decision_row.get("continue_rescue"))),
        "manual_review_ready": bool(first_bool(gap_row.get("manual_review_ready"), burndown_row.get("manual_review_ready"), decision_row.get("manual_review_ready"))),
        "final_discard_allowed": final_discard_allowed,
        "parameter_shadow_spec_present": parameter_shadow_spec_present,
        "parameter_activation_waiting_for_fresh_refresh": activation_waiting_for_fresh_refresh,
        "parameter_activation_allowed_now": False,
        "broker_paper_start_allowed": False,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "legacy_historical_profit_planning_input": future_spec_legacy_input,
        "required_next_evidence": required_next_evidence,
        "blocked_by": sorted({clean_auxiliary_text(item) for item in listify(burndown_row.get("blocked_by")) + listify(gap_row.get("missing_evidence_categories"))}),
        "allowed_operations": ["auxiliary_module_support"] if is_auxiliary else safe_allowed_operations(burndown_row),
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
        "rescue_runtime_strategy_ids": clean_strings(
            listify(first_non_empty(gap_row.get("rescue_runtime_strategy_ids"), decision_row.get("rescue_runtime_strategy_ids")))
        ),
        "rescue_ab_row_count": max(len(rescue_rows), int_or_zero(first_non_empty(gap_row.get("rescue_ab_row_count"), burndown_row.get("rescue_ab_row_count")))),
        "rescue_ab_observed_days_max": int_or_zero(first_non_empty(gap_row.get("rescue_ab_observed_days_max"), burndown_row.get("rescue_ab_observed_days_max"))),
        "rescue_ab_remaining_days_min": int_or_zero(first_non_empty(gap_row.get("rescue_ab_remaining_days_min"), burndown_row.get("rescue_ab_remaining_days_min"))),
        "rescue_no_ledger_count": int_or_zero(gap_row.get("rescue_no_ledger_count")),
        "shadow_spec_count": max(len(shadow_rows), int_or_zero(gap_row.get("shadow_spec_count"))),
        "shadow_spec_states": sorted(
            set(listify(gap_row.get("shadow_spec_states")) + [str(row.get("spec_state", "")) for row in shadow_rows if row.get("spec_state")])
        ),
        "visual_response_gate_count": len(visual_rows),
        "visual_question_pending_count": sum(int_or_zero(row.get("question_response_pending_count")) for row in visual_rows),
        "visual_case_pending_count": sum(int_or_zero(row.get("case_response_pending_count")) for row in visual_rows),
        "future_source_reextract_spec_prep_count": len(future_spec_rows),
        "future_source_reextract_spec_prep_draft_states": sorted(
            {str(row.get("draft_state", "")) for row in future_spec_rows if row.get("draft_state")}
        ),
        "future_source_reextract_spec_unblocked_count": sum(
            bool(row.get("manual_visual_confirmation_complete")) for row in future_spec_rows
        ),
        "future_source_reextract_spec_blocked_count": sum(
            str(row.get("draft_state", "")) != "ready_for_manual_m14_draft_review"
            for row in future_spec_rows
        ),
        "future_source_reextract_spec_pending_confirmation_count": sum(
            int_or_zero(row.get("manual_confirmation_pending_count")) for row in future_spec_rows
        ),
        "future_source_reextract_spec_legacy_historical_profit_planning_input_count": sum(
            bool(row.get("legacy_historical_profit_planning_input")) for row in future_spec_rows
        ),
        "next_action": display_action_for(strategy_id) if is_auxiliary else next_action_for(next_step_type),
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
    decision_ladder: dict[str, Any],
    gap_matrix: dict[str, Any],
    gap_burndown: dict[str, Any],
    objective_blocker: dict[str, Any],
    visual_gate: dict[str, Any],
    future_spec_prep: dict[str, Any],
    rescue_ab: dict[str, Any],
    shadow_spec: dict[str, Any],
    matrix_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    objective_summary = objective_blocker.get("summary", {})
    decision_summary = decision_ladder.get("summary", {})
    gap_summary = gap_matrix.get("summary", {})
    burndown_summary = gap_burndown.get("summary", {})
    visual_summary = visual_gate.get("summary", {})
    future_spec_summary = future_spec_prep.get("summary", {})
    rescue_summary = rescue_ab.get("summary", {})
    shadow_summary = shadow_spec.get("summary", {})
    route_counts = Counter(row["route_category"] for row in matrix_rows)
    bucket_counts = Counter(row["current_bucket"] for row in matrix_rows)
    next_step_counts = Counter(row["next_step_type"] for row in matrix_rows)
    return {
        "current_project_stage": first_non_empty(
            objective_summary.get("current_project_stage"),
            decision_summary.get("current_project_stage"),
            gap_summary.get("current_project_stage"),
        ),
        "m14_trading_date": first_non_empty(
            objective_summary.get("m14_trading_date"),
            decision_summary.get("m14_trading_date"),
            gap_summary.get("m14_trading_date"),
        ),
        "challenge_progress_label": first_non_empty(
            objective_summary.get("challenge_progress_label"),
            decision_summary.get("challenge_progress_label"),
            gap_summary.get("challenge_progress_label"),
        ),
        "ten_day_challenge_complete": bool(
            objective_summary.get("ten_day_challenge_complete")
            or decision_summary.get("ten_day_challenge_complete", False)
        ),
        "strategy_next_step_row_count": len(matrix_rows),
        "approved_internal_sim_continue_count": bucket_counts.get("approved_internal_sim_continue", 0),
        "can_continue_internal_sim_now_count": sum(1 for row in matrix_rows if row["can_continue_internal_sim_now"]),
        "rescue_or_shadow_review_count": bucket_counts.get("rescue_or_shadow_review", 0),
        "source_review_or_plugin_research_count": bucket_counts.get("source_review_or_plugin_research", 0),
        "auxiliary_module_support_count": bucket_counts.get("auxiliary_module_support", 0),
        "open_evidence_gap_row_count": int_or_zero(
            first_non_empty(gap_summary.get("open_evidence_gap_row_count"), burndown_summary.get("open_evidence_gap_row_count"))
        ),
        "requires_m12_47_fresh_refresh_count": int_or_zero(
            first_non_empty(gap_summary.get("requires_m12_47_fresh_refresh_count"), burndown_summary.get("requires_m12_47_fresh_refresh_count"))
        ),
        "promotion_allowed_count": sum(1 for row in matrix_rows if row["promotion_allowed"]),
        "final_discard_allowed_count": sum(1 for row in matrix_rows if row["final_discard_allowed"]),
        "parameter_activation_allowed_count": int_or_zero(
            objective_summary.get("parameter_activation_allowed_count")
        ),
        "broker_paper_start_allowed_count": int_or_zero(
            objective_summary.get("broker_paper_start_allowed_count")
        ),
        "manual_m12_37_once_allowed_count": 0,
        "legacy_historical_profit_planning_input_count": max(
            sum(1 for row in matrix_rows if row["legacy_historical_profit_planning_input"]),
            int_or_zero(future_spec_summary.get("legacy_historical_profit_planning_input_count")),
        ),
        "legacy_historical_profit_ignored": bool(
            objective_summary.get("legacy_historical_profit_ignored", True)
        ),
        "rescue_runtime_strategy_count": int_or_zero(rescue_summary.get("rescue_runtime_strategy_count")),
        "rescue_m13_ledger_observed_strategy_count": int_or_zero(
            rescue_summary.get("m13_ledger_observed_strategy_count")
        ),
        "rescue_no_m13_ledger_evidence_count": int_or_zero(
            rescue_summary.get("no_m13_ledger_evidence_count")
        ),
        "rescue_promotion_allowed_count": int_or_zero(rescue_summary.get("promotion_allowed_count")),
        "parameter_shadow_spec_row_count": int_or_zero(shadow_summary.get("spec_row_count")),
        "parameter_shadow_candidate_variant_count": int_or_zero(shadow_summary.get("candidate_variant_count")),
        "parameter_shadow_waiting_for_fresh_refresh_count": int_or_zero(
            shadow_summary.get("waiting_for_fresh_refresh_count")
        ),
        "source_visual_response_gate_row_count": int_or_zero(
            visual_summary.get("source_visual_confirmation_response_gate_row_count")
        ),
        "source_visual_question_pending_count": int_or_zero(
            visual_summary.get("question_response_pending_count")
        ),
        "source_visual_case_pending_count": int_or_zero(
            visual_summary.get("case_response_pending_count")
        ),
        "source_visual_future_spec_unblocked_count": int_or_zero(
            visual_summary.get("future_spec_unblocked_count")
        ),
        "future_source_reextract_spec_prep_row_count": int_or_zero(
            future_spec_summary.get("future_source_reextract_spec_prep_row_count")
        ),
        "future_source_reextract_spec_conditional_draft_count": int_or_zero(
            future_spec_summary.get("conditional_spec_draft_count")
        ),
        "future_source_reextract_spec_unblocked_count": int_or_zero(
            future_spec_summary.get("future_spec_unblocked_count")
        ),
        "future_source_reextract_spec_blocked_visual_count": int_or_zero(
            future_spec_summary.get("blocked_until_manual_visual_confirmation_count")
        ),
        "future_source_reextract_spec_pending_confirmation_count": int_or_zero(
            future_spec_summary.get("manual_confirmation_pending_count")
        ),
        "future_source_reextract_spec_legacy_historical_profit_planning_input_count": int_or_zero(
            future_spec_summary.get("legacy_historical_profit_planning_input_count")
        ),
        "objective_complete": bool(objective_summary.get("objective_complete", False)),
        "can_run_next_internal_sim_session": bool(objective_summary.get("can_run_next_internal_sim_session", False)),
        "can_start_broker_paper": bool(objective_summary.get("can_start_broker_paper", False)),
        "post_refresh_fresh_refresh_observed": bool(objective_summary.get("post_refresh_fresh_refresh_observed", False)),
        "post_refresh_source_quote": str(objective_summary.get("post_refresh_source_quote", "")),
        "post_refresh_waiting_count": int_or_zero(objective_summary.get("post_refresh_waiting_count")),
        "route_category_counts": dict(sorted(route_counts.items())),
        "current_bucket_counts": dict(sorted(bucket_counts.items())),
        "next_step_type_counts": dict(sorted(next_step_counts.items())),
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "copy_trading_allowed": False,
        "external_override_allowed": False,
    }


def current_bucket_for(route_category: str, burn_down_lane: str, next_step_type: str) -> str:
    if next_step_type == "auxiliary_module_support":
        return "auxiliary_module_support"
    if route_category == "approved_internal_sim_continue" or burn_down_lane == "approved_internal_sim_refresh":
        return "approved_internal_sim_continue"
    if next_step_type in {
        "collect_first_rescue_ledger",
        "continue_rescue_ab_collection",
        "complete_shadow_parameter_review",
        "rebuild_detector_then_ab",
    }:
        return "rescue_or_shadow_review"
    if route_category == "shadow_or_plugin_hold" or burn_down_lane == "shadow_plugin_research":
        return "source_review_or_plugin_research"
    return "m14_evidence_watch"


def next_step_type_for(
    route_category: str,
    burn_down_lane: str,
    gap_state: str,
    gap_row: dict[str, Any],
    burndown_row: dict[str, Any],
) -> str:
    missing = set(listify(gap_row.get("missing_evidence_categories")) + listify(burndown_row.get("missing_evidence_categories")))
    if route_category == "approved_internal_sim_continue" or burn_down_lane == "approved_internal_sim_refresh":
        return "continue_next_internal_sim_refresh"
    if "first_m13_rescue_ledger" in missing or gap_state == "wait_first_rescue_ledger" or burn_down_lane == "first_rescue_ledger":
        return "collect_first_rescue_ledger"
    if burn_down_lane == "detector_rebuild_ab":
        return "rebuild_detector_then_ab"
    if "shadow_parameter_review" in missing or burn_down_lane == "rescue_shadow_parameter_review":
        return "complete_shadow_parameter_review"
    if "rescue_10_day_ab_window" in missing or burn_down_lane == "rescue_ab_collection":
        return "continue_rescue_ab_collection"
    if route_category == "shadow_or_plugin_hold" or burn_down_lane == "shadow_plugin_research":
        return "source_visual_or_plugin_research"
    return "manual_m14_review"


def required_evidence_for(
    gap_row: dict[str, Any],
    burndown_row: dict[str, Any],
    visual_rows: list[dict[str, Any]],
    future_spec_rows: list[dict[str, Any]],
) -> list[str]:
    evidence = (
        listify(burndown_row.get("next_evidence_to_collect"))
        + listify(gap_row.get("missing_evidence_categories"))
        + listify(gap_row.get("required_artifacts"))
    )
    if any(int_or_zero(row.get("question_response_pending_count")) for row in visual_rows):
        evidence.append("manual_source_visual_question_responses")
    if any(int_or_zero(row.get("case_response_pending_count")) for row in visual_rows):
        evidence.append("manual_source_visual_case_responses")
    if any(int_or_zero(row.get("manual_confirmation_pending_count")) for row in future_spec_rows):
        evidence.append("future_source_reextract_spec_manual_visual_confirmation")
    if any(str(row.get("draft_state", "")) != "ready_for_manual_m14_draft_review" for row in future_spec_rows):
        evidence.append("future_source_reextract_spec_prep_review_only")
    return sorted({str(item) for item in evidence if str(item)})


def next_action_for(next_step_type: str) -> str:
    actions = {
        "continue_next_internal_sim_refresh": "Wait for the next M12.47-supervised internal simulated-account refresh, then recompute M13/M14 evidence.",
        "collect_first_rescue_ledger": "Keep the rescue runtime under observation until the first matching M13 ledger evidence appears.",
        "continue_rescue_ab_collection": "Continue rescue A/B evidence collection until the 10-trading-day rescue window is complete.",
        "complete_shadow_parameter_review": "Review shadow parameter specs and keep them inactive until fresh-refresh and review gates pass.",
        "rebuild_detector_then_ab": "Review detector/timeframe mapping, then continue A/B evidence collection if the detector is still valid.",
        "source_visual_or_plugin_research": "Keep source-visual or plugin research in review-only mode until manual confirmation is complete.",
        "auxiliary_module_support": "辅助模块继续服务主策略的筛选、目标价、止损、仓位或图形证据，不作为独立交易策略。",
        "manual_m14_review": "Hold for manual M14 review; do not promote, discard, mutate parameters, or start broker paper.",
    }
    return actions.get(next_step_type, actions["manual_m14_review"])


def auxiliary_module_purpose(strategy_id: str) -> str:
    return AUXILIARY_MODULE_PURPOSES.get(strategy_id, "筛选、风控、目标价、仓位或图形证据服务主策略")


def display_action_for(strategy_id: str) -> str:
    return f"辅助模块：启用为{auxiliary_module_purpose(strategy_id)}，不作为独立交易策略"


def clean_auxiliary_text(value: Any) -> str:
    text = str(value)
    replacements = {
        "research-only": "auxiliary-module",
        "Research-only": "Auxiliary-module",
        "plugin or auxiliary-module": "auxiliary-module",
        "plugin/research": "auxiliary-module",
        "shadow/plugin/research": "auxiliary-module",
        "source/plugin research": "auxiliary-module support",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def safe_allowed_operations(burndown_row: dict[str, Any]) -> list[str]:
    allowed = [str(item) for item in listify(burndown_row.get("allowed_operations")) if str(item)]
    unsafe = set(FORBIDDEN_OPERATIONS)
    return sorted({item for item in allowed if item not in unsafe})


def index_rows_by_strategy(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        keys = [
            str(row.get("strategy_id", "")),
            str(row.get("parent_strategy_id", "")),
        ]
        for key_name in ("runtime_ids", "variant_ids", "rescue_runtime_strategy_ids"):
            keys.extend(str(item) for item in listify(row.get(key_name)))
        for key in {key for key in keys if key}:
            indexed[key].append(row)
    return dict(indexed)


def legacy_history_metric_exclusion(objective_blocker: dict[str, Any]) -> dict[str, Any]:
    source_policy = dict(objective_blocker.get("legacy_history_metric_exclusion", {}))
    return {
        "legacy_bug_metric_excluded": True,
        "planning_input_allowed": False,
        "excluded_metric_categories": [
            "old_account_dashboard_profit_fields",
            "old_return_drawdown_fields",
            "old_profit_factor_fields",
        ],
        "excluded_from_decisions": listify(
            source_policy.get(
                "excluded_from_decisions",
                [
                    "strategy_promotion",
                    "strategy_rescue_priority",
                    "parameter_activation",
                    "broker_readiness",
                    "objective_completion",
                ],
            )
        ),
        "replacement_evidence_sources": listify(
            source_policy.get(
                "replacement_evidence_sources",
                [
                    "m13_signal_ledger",
                    "m13_account_operation_ledger",
                    "m12_47_supervised_fresh_refresh_status",
                ],
            )
        ),
    }


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
        "legacy_historical_profit_planning_input": False,
    }


def build_plain_language_result(payload: dict[str, Any]) -> list[str]:
    summary = payload["summary"]
    return [
        (
            f"Built {summary['strategy_next_step_row_count']} per-strategy next-step rows; "
            f"{summary['approved_internal_sim_continue_count']} may continue only through internal simulated refresh."
        ),
        (
            f"Promotion/discard/parameter activation/broker paper counts are "
            f"{summary['promotion_allowed_count']}/"
            f"{summary['final_discard_allowed_count']}/"
            f"{summary['parameter_activation_allowed_count']}/"
            f"{summary['broker_paper_start_allowed_count']}."
        ),
        (
            "Legacy historical profit metrics are display-only: "
            f"planning input count is {summary['legacy_historical_profit_planning_input_count']}."
        ),
        (
            "Future source-reextract spec prep remains conditional: "
            f"{summary['future_source_reextract_spec_prep_row_count']} rows, "
            f"{summary['future_source_reextract_spec_unblocked_count']} unblocked, "
            f"{summary['future_source_reextract_spec_pending_confirmation_count']} pending confirmations."
        ),
        f"辅助模块行数为 {summary['auxiliary_module_support_count']}，这些模块只服务主策略，不作为独立交易策略。",
    ]


def build_matrix_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    rows = payload["matrix_rows"]
    lines = [
        "# M14 Strategy Next-Step Readiness Matrix",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge progress: `{summary['challenge_progress_label']}`",
        f"- Strategy rows: `{summary['strategy_next_step_row_count']}`",
        f"- Continue internal sim / promote / discard / activate parameters / broker paper: "
        f"`{summary['approved_internal_sim_continue_count']}/"
        f"{summary['promotion_allowed_count']}/"
        f"{summary['final_discard_allowed_count']}/"
        f"{summary['parameter_activation_allowed_count']}/"
        f"{summary['broker_paper_start_allowed_count']}`",
        f"- Auxiliary module rows: `{summary['auxiliary_module_support_count']}`",
        f"- Legacy history metric planning inputs: `{summary['legacy_historical_profit_planning_input_count']}`",
        f"- Future source-reextract spec prep rows/drafts/unblocked/blocked/pending: `{summary['future_source_reextract_spec_prep_row_count']}/{summary['future_source_reextract_spec_conditional_draft_count']}/{summary['future_source_reextract_spec_unblocked_count']}/{summary['future_source_reextract_spec_blocked_visual_count']}/{summary['future_source_reextract_spec_pending_confirmation_count']}`",
        f"- M12.37 manual once allowed: `{summary['manual_m12_37_once_allowed']}`",
        f"- Broker/live enabled: `{summary['broker_or_live_enabled']}`",
        "",
        "## Legacy History Metric Policy",
        "",
        "Legacy account-dashboard history metrics are display-only and cannot affect strategy promotion, rescue priority, parameter activation, broker readiness, or objective completion.",
        "",
        "## Rows",
        "",
        "| Strategy | Bucket | Next step | Role | Continue sim | Promote | Discard | Legacy history input | Evidence needed |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        evidence = ", ".join(row["required_next_evidence"][:5])
        if len(row["required_next_evidence"]) > 5:
            evidence += f", +{len(row['required_next_evidence']) - 5} more"
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(row["strategy_id"]),
                    markdown_cell(row["current_bucket"]),
                    markdown_cell(row["next_step_type"]),
                    markdown_cell(row["runtime_role"]),
                    str(row["can_continue_internal_sim_now"]),
                    str(row["promotion_allowed"]),
                    str(row["final_discard_allowed"]),
                    str(row["legacy_historical_profit_planning_input"]),
                    markdown_cell(evidence),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def first_bool(*values: Any) -> bool:
    for value in values:
        if isinstance(value, bool):
            return value
    return False


def int_or_zero(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return [value]


def clean_strings(values: list[Any]) -> list[str]:
    return [str(value) for value in values if str(value)]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
