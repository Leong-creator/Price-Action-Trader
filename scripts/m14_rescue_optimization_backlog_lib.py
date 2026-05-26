#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_optimization_backlog.json"


@dataclass(frozen=True, slots=True)
class RescueOptimizationBacklogConfig:
    stage: str
    rescue_plan_path: Path
    rescue_ab_evidence_path: Path
    broker_readiness_path: Path
    backlog_json_path: Path
    backlog_md_path: Path
    min_ab_trading_days: int
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescueOptimizationBacklogConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescueOptimizationBacklogConfig(
        stage=str(payload["stage"]),
        rescue_plan_path=resolve_repo_path(inputs["m14_strategy_rescue_plan"]),
        rescue_ab_evidence_path=resolve_repo_path(inputs["m14_rescue_ab_evidence_tracker"]),
        broker_readiness_path=resolve_repo_path(inputs["m14_2_broker_readiness_plan"]),
        backlog_json_path=resolve_repo_path(outputs["backlog_json"]),
        backlog_md_path=resolve_repo_path(outputs["backlog_md"]),
        min_ab_trading_days=int(payload["min_ab_trading_days"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescueOptimizationBacklogConfig) -> None:
    if config.stage != "M14.rescue_optimization_backlog":
        raise ValueError("M14 rescue optimization backlog stage drift")
    if config.min_ab_trading_days != 10:
        raise ValueError("M14 rescue optimization backlog must keep the 10-day A/B requirement")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue optimization backlog must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue optimization backlog cannot enable {key}")


def run_m14_rescue_optimization_backlog(
    config: RescueOptimizationBacklogConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rescue_plan = read_json(config.rescue_plan_path)
    rescue_ab_evidence = read_json(config.rescue_ab_evidence_path)
    broker_readiness = read_json(config.broker_readiness_path)

    plan_rows = list(rescue_plan.get("rows", []))
    plan_by_strategy_id = {str(row.get("strategy_id", "")): row for row in plan_rows if row.get("strategy_id")}
    plan_by_variant_id = {str(row.get("next_variant_id", "")): row for row in plan_rows if row.get("next_variant_id")}
    rescue_rows = [
        build_rescue_backlog_row(
            evidence_row=dict(row),
            plan_row=matching_plan_row(dict(row), plan_by_strategy_id, plan_by_variant_id),
            min_ab_trading_days=config.min_ab_trading_days,
        )
        for row in rescue_ab_evidence.get("rows", [])
    ]
    rescue_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    broker_blocker_rows = build_broker_blocker_rows(broker_readiness)

    issue_counts = dict(sorted(Counter(row["issue_type"] for row in rescue_rows).items()))
    broker_reason_counts = Counter()
    for row in broker_blocker_rows:
        broker_reason_counts.update(row["reason_counts"])

    summary = {
        "rescue_strategy_count": len(rescue_rows),
        "actionable_before_10d_count": sum(1 for row in rescue_rows if row["pre_10_day_actionable"]),
        "wait_for_more_ab_evidence_count": sum(1 for row in rescue_rows if row["work_state"] == "wait_for_more_ab_evidence"),
        "zero_signal_after_connection_count": issue_counts.get("zero_signal_after_connection", 0),
        "signal_generated_no_account_operation_count": issue_counts.get("signal_generated_no_account_operation", 0),
        "missing_rescue_ledger_count": issue_counts.get("missing_rescue_ledger", 0),
        "ready_for_manual_review_count": issue_counts.get("ready_for_manual_review", 0),
        "issue_counts": issue_counts,
        "high_priority_strategy_ids": [
            row["strategy_id"] for row in rescue_rows if row["priority"] == "P0" and row["pre_10_day_actionable"]
        ],
        "broker_dry_run_blocked_count": sum(row["blocked_count"] for row in broker_blocker_rows),
        "broker_blocker_strategy_count": len(broker_blocker_rows),
        "broker_blocker_reason_counts": dict(sorted(broker_reason_counts.items())),
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.rescue-optimization-backlog.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_rescue_plan": project_path(config.rescue_plan_path),
            "m14_rescue_ab_evidence_tracker": project_path(config.rescue_ab_evidence_path),
            "m14_2_broker_readiness_plan": project_path(config.broker_readiness_path),
        },
        "min_ab_trading_days": config.min_ab_trading_days,
        "summary": summary,
        "rescue_rows": rescue_rows,
        "broker_dry_run_blockers": broker_blocker_rows,
        "hard_boundaries": {
            "paper_simulated_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
        },
        "paper_or_live_approval": False,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.backlog_json_path, payload)
    config.backlog_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.backlog_md_path.write_text(build_backlog_md(payload), encoding="utf-8")
    return payload


def matching_plan_row(
    evidence_row: dict[str, Any],
    plan_by_strategy_id: dict[str, dict[str, Any]],
    plan_by_variant_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    strategy_id = str(evidence_row.get("strategy_id", ""))
    parent_strategy_id = str(evidence_row.get("parent_strategy_id", ""))
    return dict(
        plan_by_variant_id.get(strategy_id)
        or plan_by_strategy_id.get(parent_strategy_id)
        or plan_by_strategy_id.get(strategy_id)
        or {}
    )


def build_rescue_backlog_row(
    *,
    evidence_row: dict[str, Any],
    plan_row: dict[str, Any],
    min_ab_trading_days: int,
) -> dict[str, Any]:
    strategy_id = str(evidence_row.get("strategy_id", ""))
    signal_count = int_or_zero(evidence_row.get("signal_count"))
    source_row_count = int_or_zero(evidence_row.get("source_row_count"))
    open_count = int_or_zero(evidence_row.get("open_count"))
    close_count = int_or_zero(evidence_row.get("close_count"))
    risk_blocked_count = int_or_zero(evidence_row.get("risk_blocked_count"))
    observed_days = int_or_zero(evidence_row.get("observed_trading_days_count"))
    remaining_days = max(0, min_ab_trading_days - observed_days)
    evidence_status = str(evidence_row.get("evidence_status", ""))
    active_operation_count = open_count + close_count + risk_blocked_count
    issue_type, priority, action = classify_rescue_issue(
        evidence_status=evidence_status,
        signal_count=signal_count,
        source_row_count=source_row_count,
        active_operation_count=active_operation_count,
        risk_blocked_count=risk_blocked_count,
        remaining_days=remaining_days,
    )
    pre_10_day_actionable = issue_type in {
        "missing_rescue_ledger",
        "zero_signal_after_connection",
        "signal_generated_no_account_operation",
        "risk_blocked_after_signal",
    }
    work_state = "actionable_before_10d" if pre_10_day_actionable else "wait_for_more_ab_evidence"
    if issue_type == "ready_for_manual_review":
        work_state = "ready_for_manual_m14_review"

    rescue_mode = str(plan_row.get("rescue_mode", "")) or infer_rescue_mode(issue_type)
    return {
        "backlog_id": f"m14-rescue-opt-{slug(strategy_id)}",
        "strategy_id": strategy_id,
        "parent_strategy_id": str(evidence_row.get("parent_strategy_id", "")),
        "runtime_ids": list(evidence_row.get("runtime_ids", [])),
        "priority": priority,
        "issue_type": issue_type,
        "work_state": work_state,
        "pre_10_day_actionable": pre_10_day_actionable,
        "recommended_action": action,
        "optimization_family": optimization_family(rescue_mode, issue_type),
        "parent_rescue_mode": rescue_mode,
        "parent_decision": str(plan_row.get("decision", "")),
        "parent_decision_reason": str(plan_row.get("decision_reason", "")),
        "parent_optimization_hypothesis": str(plan_row.get("optimization_hypothesis", "")),
        "evidence_status": evidence_status,
        "observed_trading_days_count": observed_days,
        "remaining_ab_trading_days": remaining_days,
        "required_ab_trading_days": min_ab_trading_days,
        "signal_count": signal_count,
        "source_row_count": source_row_count,
        "open_count": open_count,
        "close_count": close_count,
        "risk_blocked_count": risk_blocked_count,
        "m13_account_ledger_row_count": int_or_zero(evidence_row.get("m13_account_ledger_row_count")),
        "promotion_gate": "10 rescue A/B trading days plus manual M14 review",
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def classify_rescue_issue(
    *,
    evidence_status: str,
    signal_count: int,
    source_row_count: int,
    active_operation_count: int,
    risk_blocked_count: int,
    remaining_days: int,
) -> tuple[str, str, str]:
    if evidence_status == "no_m13_rescue_ledger_evidence_yet":
        return (
            "missing_rescue_ledger",
            "P0",
            "Fix the rescue runtime ledger path before waiting for more trading days.",
        )
    if evidence_status == "evidence_ready_for_manual_review" or remaining_days <= 0:
        return (
            "ready_for_manual_review",
            "P1",
            "Run manual M14 promote/modify/reject review; auto-promotion remains disabled.",
        )
    if signal_count == 0 and source_row_count == 0:
        return (
            "zero_signal_after_connection",
            "P0",
            "Audit detector thresholds, source-row mapping, universe coverage, and timeframe routing; test one relax/quality parameter family in shadow before changing risk.",
        )
    if signal_count > 0 and active_operation_count == 0:
        return (
            "signal_generated_no_account_operation",
            "P0",
            "Audit signal-to-account bridge, trading-date normalization, and no-op reason attribution; do not treat signals as execution evidence until account operations are explicit.",
        )
    if risk_blocked_count > 0:
        return (
            "risk_blocked_after_signal",
            "P1",
            "Tune sizing, exposure allocation, stop distance, or cooldown rules before changing setup semantics.",
        )
    return (
        "collect_more_ab_evidence",
        "P2",
        "Continue collecting rescue A/B ledger days without changing the frozen variant.",
    )


def infer_rescue_mode(issue_type: str) -> str:
    if issue_type == "zero_signal_after_connection":
        return "detector_threshold_or_source_mapping_review"
    if issue_type == "signal_generated_no_account_operation":
        return "signal_to_account_bridge_review"
    if issue_type == "risk_blocked_after_signal":
        return "resize_or_risk_gate_variant"
    return "ab_evidence_collection"


def optimization_family(rescue_mode: str, issue_type: str) -> str:
    if issue_type == "zero_signal_after_connection":
        return "detector_threshold_source_mapping_timeframe"
    if issue_type == "signal_generated_no_account_operation":
        return "ledger_bridge_trading_date_noop_reason"
    if rescue_mode == "drawdown_control_variant":
        return "volatility_filter_risk_sizing_trailing_exit"
    if rescue_mode == "expectancy_repair_variant":
        return "entry_confirmation_stop_distance_profit_taking_grid"
    if rescue_mode == "entry_quality_and_filter_variant":
        return "trend_context_news_veto_entry_confirmation"
    if rescue_mode == "resize_or_risk_gate_variant":
        return "position_sizing_exposure_allocation"
    if rescue_mode == "rebuild_detector_before_abandon":
        return "detector_contract_rebuild"
    return "ab_evidence_collection"


def build_broker_blocker_rows(broker_readiness: dict[str, Any]) -> list[dict[str, Any]]:
    blocked_rows = [
        dict(row)
        for row in broker_readiness.get("rows", [])
        if str(row.get("readiness_status", "")) == "blocked"
    ]
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in blocked_rows:
        by_strategy[str(row.get("strategy_id", ""))].append(row)

    rows: list[dict[str, Any]] = []
    for strategy_id, strategy_rows in sorted(by_strategy.items()):
        reason_counts = Counter()
        signal_ids: list[str] = []
        symbols: set[str] = set()
        for row in strategy_rows:
            reason_counts.update(reason_codes(row))
            if row.get("signal_id"):
                signal_ids.append(str(row["signal_id"]))
            if row.get("symbol"):
                symbols.add(str(row["symbol"]))
        reasons = dict(sorted(reason_counts.items()))
        rows.append(
            {
                "strategy_id": strategy_id,
                "priority": broker_blocker_priority(reasons),
                "blocked_count": len(strategy_rows),
                "reason_counts": reasons,
                "symbols": sorted(symbols),
                "source_signal_ids": signal_ids,
                "recommended_action": broker_blocker_action(reasons),
                "paper_simulated_only": True,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return rows


def reason_codes(row: dict[str, Any]) -> list[str]:
    source_reasons = row.get("source_risk_reason_codes")
    if isinstance(source_reasons, list) and source_reasons:
        return [str(item) for item in source_reasons]
    reasons = row.get("reason_codes")
    if isinstance(reasons, list) and reasons:
        return [str(item) for item in reasons]
    return [str(row.get("risk_outcome", "blocked"))]


def broker_blocker_priority(reasons: dict[str, int]) -> str:
    p0_reasons = {"max_risk_per_order_exceeded", "consecutive_losses_limit"}
    if any(reason in reasons for reason in p0_reasons):
        return "P0"
    return "P1"


def broker_blocker_action(reasons: dict[str, int]) -> str:
    if "max_risk_per_order_exceeded" in reasons:
        return "Reduce per-order risk through quantity cap, wider source validation, or strategy-specific stop/target normalization before any broker-paper review."
    if "consecutive_losses_limit" in reasons:
        return "Keep the loss-streak guard active and add cooldown/quality veto diagnostics before allowing further simulated entries."
    if "max_total_exposure_exceeded" in reasons:
        return "Add portfolio exposure allocation or signal ranking so lower-priority entries defer instead of exceeding total exposure."
    return "Review dry-run risk reason codes and keep broker/live disabled."


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Rescue optimization backlog has {summary['rescue_strategy_count']} rescue rows; "
        f"{summary['actionable_before_10d_count']} can be worked before the 10-day A/B window completes. "
        f"Zero-signal connected variants: {summary['zero_signal_after_connection_count']}; "
        f"signal-without-account-operation variants: {summary['signal_generated_no_account_operation_count']}. "
        f"Broker dry-run blockers remain {summary['broker_dry_run_blocked_count']} events across "
        f"{summary['broker_blocker_strategy_count']} strategies. No broker connection, real order, live execution, or paper-trading approval is enabled."
    )


def build_backlog_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Rescue Optimization Backlog",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Rescue rows: `{summary['rescue_strategy_count']}`",
        f"- Actionable before 10-day A/B completion: `{summary['actionable_before_10d_count']}`",
        f"- Zero-signal connected variants: `{summary['zero_signal_after_connection_count']}`",
        f"- Signal without account operation variants: `{summary['signal_generated_no_account_operation_count']}`",
        f"- Broker dry-run blockers: `{summary['broker_dry_run_blocked_count']}`",
        "- Boundary: internal simulated only; no broker connection, no real orders, no live execution.",
        "",
        "## Rescue Backlog",
        "",
    ]
    for row in payload["rescue_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Priority: `{row['priority']}`",
                f"- Issue: `{row['issue_type']}`",
                f"- Work state: `{row['work_state']}`",
                f"- Evidence days: `{row['observed_trading_days_count']}/{row['required_ab_trading_days']}`",
                f"- Signal/source/open/close/risk-blocked: `{row['signal_count']} / {row['source_row_count']} / {row['open_count']} / {row['close_count']} / {row['risk_blocked_count']}`",
                f"- Optimization family: `{row['optimization_family']}`",
                f"- Action: {row['recommended_action']}",
                "",
            ]
        )
    lines.extend(["## Broker Dry-run Blockers", ""])
    if not payload["broker_dry_run_blockers"]:
        lines.append("- none")
    for row in payload["broker_dry_run_blockers"]:
        lines.extend(
            [
                f"- `{row['strategy_id']}` priority `{row['priority']}`, blocked `{row['blocked_count']}`, reasons `{row['reason_counts']}`. Action: {row['recommended_action']}",
            ]
        )
    lines.extend(["", "## Summary", "", payload["plain_language_result"], ""])
    return "\n".join(lines)


def slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")


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
