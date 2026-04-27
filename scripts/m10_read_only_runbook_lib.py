#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M10_13_DIR = M10_DIR / "read_only_observation" / "m10_13"
M10_12_METRICS = M10_DIR / "all_strategy_scorecard" / "m10_12" / "m10_12_all_strategy_metrics.csv"
M10_12_SUMMARY = M10_DIR / "all_strategy_scorecard" / "m10_12" / "m10_12_all_strategy_scorecard_summary.json"
WAVE_A_METRICS = M10_DIR / "capital_backtest" / "m10_8_wave_a" / "m10_8_wave_a_metrics.csv"
WAVE_B_METRICS = M10_DIR / "capital_backtest" / "m10_11_wave_b" / "m10_11_wave_b_metrics.csv"
M10_5_SCHEMA = M10_DIR / "m10_5_observation_event_schema.json"
M10_5_QUEUE = M10_DIR / "m10_5_observation_candidate_queue.json"
DEFAULT_SYMBOLS = ("SPY", "QQQ", "NVDA", "TSLA")
FORBIDDEN_OUTPUT_STRINGS = ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true")
VISUAL_REVIEW_STRATEGIES = {"M10-PA-008", "M10-PA-009"}
OBSERVATION_PRIORITY = (
    "M10-PA-001",
    "M10-PA-002",
    "M10-PA-012",
    "M10-PA-008",
    "M10-PA-009",
    "M10-PA-003",
    "M10-PA-011",
    "M10-PA-013",
)


def run_m10_13_read_only_runbook(output_dir: Path = M10_13_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    strategy_rows = read_csv(M10_12_METRICS)
    timeframe_rows = collect_timeframe_metrics()
    queue = build_observation_queue(strategy_rows, timeframe_rows)
    write_json(output_dir / "m10_13_observation_candidate_queue.json", queue)
    write_runbook(output_dir / "m10_13_read_only_observation_runbook.md", queue)
    write_weekly_template(output_dir / "m10_13_weekly_observation_template.md", queue)
    summary = {
        "schema_version": "m10.13.read-only-observation-runbook-summary.v1",
        "generated_at": "2026-04-27T00:00:00Z",
        "stage": "M10.13.read_only_observation_runbook",
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "primary_strategy_count": len(queue["primary_observation_queue"]),
        "primary_strategy_ids": [item["strategy_id"] for item in queue["primary_observation_queue"]],
        "primary_strategy_timeframe_count": sum(len(item["timeframes"]) for item in queue["primary_observation_queue"]),
        "output_dir": format_output_dir(output_dir),
    }
    write_json(output_dir / "m10_13_read_only_observation_runbook_summary.json", summary)
    validate_outputs(output_dir)
    return summary


def build_observation_queue(strategy_rows: list[dict[str, str]], timeframe_rows: list[dict[str, str]]) -> dict[str, Any]:
    strategy_by_id = {row["strategy_id"]: row for row in strategy_rows}
    timeframe_by_strategy: dict[str, list[dict[str, str]]] = {}
    for row in timeframe_rows:
        timeframe_by_strategy.setdefault(row["strategy_id"], []).append(row)

    primary = []
    watchlist = []
    excluded: dict[str, list[dict[str, str]]] = {
        "needs_definition_fix": [],
        "visual_only_not_backtestable": [],
        "supporting_rule": [],
        "research_only": [],
        "non_positive_aggregate": [],
    }
    ordered_strategy_ids = list(OBSERVATION_PRIORITY) + sorted(strategy_id for strategy_id in strategy_by_id if strategy_id not in OBSERVATION_PRIORITY)
    for strategy_id in ordered_strategy_ids:
        row = strategy_by_id[strategy_id]
        machine_status = row["machine_status"]
        if row["portfolio_eligible"] != "true":
            excluded.setdefault(machine_status, []).append(exclusion_row(row, f"status={machine_status}"))
            continue
        aggregate_return = Decimal(row["return_percent"])
        if aggregate_return <= Decimal("0"):
            item = exclusion_row(row, "aggregate_return_not_positive")
            item["return_percent"] = row["return_percent"]
            excluded["non_positive_aggregate"].append(item)
            watchlist.append(build_watchlist_item(row, timeframe_by_strategy.get(strategy_id, [])))
            continue
        all_timeframes = sorted(timeframe_by_strategy.get(strategy_id, []), key=lambda item: timeframe_sort_key(item["timeframe"]))
        selected_timeframes = [
            build_timeframe_item(tf_row)
            for tf_row in all_timeframes
            if Decimal(tf_row["return_percent"]) > Decimal("0")
        ]
        reserve_timeframes = [
            build_timeframe_item(tf_row)
            for tf_row in all_timeframes
            if Decimal(tf_row["return_percent"]) <= Decimal("0")
        ]
        if not selected_timeframes:
            item = exclusion_row(row, "no_positive_timeframe_after_m10_12_screen")
            excluded["non_positive_aggregate"].append(item)
            watchlist.append(build_watchlist_item(row, timeframe_by_strategy.get(strategy_id, [])))
            continue
        primary.append(build_primary_item(row, selected_timeframes, reserve_timeframes))

    return {
        "schema_version": "m10.13.observation-candidate-queue.v1",
        "generated_at": "2026-04-27T00:00:00Z",
        "stage": "M10.13.read_only_observation_runbook",
        "input_refs": {
            "m10_12_metrics": "reports/strategy_lab/m10_price_action_strategy_refresh/all_strategy_scorecard/m10_12/m10_12_all_strategy_metrics.csv",
            "m10_12_summary": "reports/strategy_lab/m10_price_action_strategy_refresh/all_strategy_scorecard/m10_12/m10_12_all_strategy_scorecard_summary.json",
            "m10_5_event_schema": "reports/strategy_lab/m10_price_action_strategy_refresh/m10_5_observation_event_schema.json",
            "m10_5_candidate_queue": "reports/strategy_lab/m10_price_action_strategy_refresh/m10_5_observation_candidate_queue.json",
            "wave_a_metrics": "reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_8_wave_a/m10_8_wave_a_metrics.csv",
            "wave_b_metrics": "reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_11_wave_b/m10_11_wave_b_metrics.csv",
        },
        "boundaries": {
            "paper_simulated_only": True,
            "runbook_only": True,
            "observation_runner_started": False,
            "broker_connection": False,
            "real_orders": False,
            "live_execution": False,
            "paper_trading_approval": False,
            "profitability_claim_allowed": False,
        },
        "selection_policy": {
            "primary_queue_rule": "completed_capital_test AND portfolio_eligible=true AND aggregate return > 0 AND timeframe return > 0",
            "m10_5_relationship": "M10.13 extends the M10.5 Wave A observation plan after M10.11/M10.12; Wave B strategies may enter only after completed capital test and manual visual context review flags.",
            "excluded_statuses": ["needs_definition_fix", "visual_only_not_backtestable", "supporting_rule", "research_only"],
            "negative_aggregate_policy": "watchlist_only_not_primary_observation",
            "negative_timeframe_policy": "reserve_only_not_primary_observation",
            "m10_pa_005_policy": "excluded_until_range_geometry_definition_fix_is_completed",
        },
        "symbols": list(DEFAULT_SYMBOLS),
        "observation_cadence": {
            "1d": "after_regular_session_close_only",
            "1h": "regular_session_bar_close_only",
            "15m": "regular_session_bar_close_only",
            "5m": "regular_session_bar_close_only",
        },
        "lineage_requirements": {
            "1d": "native_cache",
            "5m": "native_cache",
            "15m": "derived_from_5m",
            "1h": "derived_from_5m",
        },
        "primary_observation_queue": primary,
        "watchlist_deferred": watchlist,
        "excluded_strategy_ids": excluded,
        "weekly_report_requirements": [
            "weekly_triggered_strategy_count",
            "events_by_strategy_symbol_timeframe",
            "candidate_vs_skip_counts",
            "hypothetical_equity_curve_deviation_from_m10_12",
            "pause_condition_hits",
            "manual_review_decisions",
        ],
        "pause_conditions": build_pause_conditions(),
    }


def build_primary_item(row: dict[str, str], selected_timeframes: list[dict[str, str]], reserve_timeframes: list[dict[str, str]]) -> dict[str, Any]:
    strategy_id = row["strategy_id"]
    return {
        "strategy_id": strategy_id,
        "title": row["title"],
        "queue_status": "primary_read_only_observation_candidate",
        "selection_basis": "m10_11_wave_b_plus_m10_12_screen" if strategy_id in VISUAL_REVIEW_STRATEGIES else "m10_5_wave_a_plan_plus_m10_12_screen",
        "requires_visual_review_context": strategy_id in VISUAL_REVIEW_STRATEGIES,
        "timeframes": [item["timeframe"] for item in selected_timeframes],
        "reserve_timeframes": reserve_timeframes,
        "symbols": list(DEFAULT_SYMBOLS),
        "historical_metric_snapshot": metric_snapshot(row),
        "selected_timeframe_metrics": selected_timeframes,
        "review_requirements": review_requirements_for(strategy_id),
    }


def build_timeframe_item(row: dict[str, str]) -> dict[str, str]:
    return {
        "timeframe": row["timeframe"],
        "return_percent": row["return_percent"],
        "trade_count": row["trade_count"],
        "win_rate": row["win_rate"],
        "max_drawdown": row["max_drawdown"],
        "lineage": "derived_from_5m" if row["timeframe"] in {"15m", "1h"} else "native_cache",
        "cadence": "after_regular_session_close_only" if row["timeframe"] == "1d" else "regular_session_bar_close_only",
    }


def build_watchlist_item(row: dict[str, str], timeframe_rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "strategy_id": row["strategy_id"],
        "title": row["title"],
        "queue_status": "watchlist_only_not_primary",
        "reason": "aggregate_return_not_positive_or_no_positive_timeframe",
        "historical_metric_snapshot": metric_snapshot(row),
        "positive_timeframes_seen": [
            build_timeframe_item(tf_row)
            for tf_row in sorted(timeframe_rows, key=lambda item: timeframe_sort_key(item["timeframe"]))
            if Decimal(tf_row["return_percent"]) > Decimal("0")
        ],
    }


def metric_snapshot(row: dict[str, str]) -> dict[str, str]:
    return {
        "return_percent": row["return_percent"],
        "net_profit": row["net_profit"],
        "trade_count": row["trade_count"],
        "win_rate": row["win_rate"],
        "max_drawdown": row["max_drawdown"],
        "metric_completeness": row["metric_completeness"],
    }


def exclusion_row(row: dict[str, str], reason: str) -> dict[str, str]:
    return {
        "strategy_id": row["strategy_id"],
        "title": row["title"],
        "machine_status": row["machine_status"],
        "reason": reason,
    }


def review_requirements_for(strategy_id: str) -> list[str]:
    requirements = [
        "record_only_at_defined_bar_close",
        "compare_weekly_event_density_to_m10_12_baseline",
        "manual_review_before_status_change",
    ]
    if strategy_id in VISUAL_REVIEW_STRATEGIES:
        requirements.append("manual_visual_context_review_required")
    return requirements


def build_pause_conditions() -> list[dict[str, str]]:
    return [
        {
            "code": "queue_contract_violation",
            "trigger": "strategy/timeframe is outside the M10.13 queue contract or contains a legacy id",
            "action": "reject the event artifact and fix queue generation before continuing",
        },
        {
            "code": "schema_or_ref_failure",
            "trigger": "observation event schema fails or source_refs/spec_ref/bar_timestamp is missing",
            "action": "pause affected queue item and repair event writer before review",
        },
        {
            "code": "lineage_or_timing_drift",
            "trigger": "15m/1h lineage is not derived_from_5m, or 1d event is not after close",
            "action": "pause affected timeframe and correct input lineage/timing",
        },
        {
            "code": "input_missing_or_lineage_unknown",
            "trigger": "required OHLCV cache, feed, or lineage is missing",
            "action": "pause observation for affected strategy/timeframe and write deferred input note",
        },
        {
            "code": "deferred_input_streak",
            "trigger": "same strategy/timeframe has deferred inputs for two consecutive weekly cycles",
            "action": "remove from active weekly review until data input is restored",
        },
        {
            "code": "definition_density_drift",
            "trigger": "weekly event density exceeds 2x M10.12 baseline or crosses 100 events per 1000 bars",
            "action": "pause affected strategy/timeframe for definition review",
        },
        {
            "code": "review_status_regression",
            "trigger": "review status regresses to needs_definition_fix, needs_visual_review, or reject_for_now",
            "action": "move item out of active observation until manual review is closed",
        },
        {
            "code": "equity_curve_deviation",
            "trigger": "hypothetical observation drawdown exceeds 1.25x corresponding M10.12 historical max drawdown",
            "action": "pause new observations and require manual review",
        },
        {
            "code": "manual_review_backlog",
            "trigger": "unreviewed observation events remain open for more than one weekly cycle",
            "action": "pause expansion and clear review backlog first",
        },
        {
            "code": "visual_context_unresolved",
            "trigger": "visual-review strategy has ambiguous chart context",
            "action": "keep event as needs_visual_review and do not include it in paper gate evidence",
        },
        {
            "code": "live_or_broker_request",
            "trigger": "any workflow requires broker connection, live feed subscription, real account, or real order",
            "action": "stop M10.13 path and require explicit user approval",
        },
    ]


def write_runbook(path: Path, queue: dict[str, Any]) -> None:
    lines = [
        "# M10.13 Read-only Observation Runbook",
        "",
        "## 摘要",
        "",
        "- 本文件是后续只读观察的执行手册，本阶段不启动真实观察。",
        "- broker connection、real account、live execution、real orders 和 paper trading approval 继续关闭。",
        "- 主观察队列只纳入已完成资金测试、整体收益为正、且分周期筛选为正的策略周期。",
        "- M10.13 在 M10.5 的 Wave A 观察计划基础上，允许 M10.11/M10.12 筛选通过的 Wave B 策略进入观察队列；视觉策略必须保留人工图形语境复核。",
        "",
        "## 主观察队列",
        "",
        "| Strategy | Timeframes | Symbols | Review Notes |",
        "|---|---|---|---|",
    ]
    for item in queue["primary_observation_queue"]:
        visual_note = "需要人工图形语境复核" if item["requires_visual_review_context"] else "常规人工复核"
        lines.append(
            f"| {item['strategy_id']} | `{' / '.join(item['timeframes'])}` | `{' / '.join(item['symbols'])}` | {visual_note} |"
        )
    lines.extend(
        [
            "",
            "## Reserve Timeframes",
            "",
            "| Strategy | Reserve Timeframes | Reason |",
            "|---|---|---|",
        ]
    )
    for item in queue["primary_observation_queue"]:
        if item["reserve_timeframes"]:
            lines.append(
                f"| {item['strategy_id']} | `{' / '.join(tf['timeframe'] for tf in item['reserve_timeframes'])}` | timeframe historical return is not positive |"
            )
    lines.extend(
        [
            "",
            "## 观察节奏",
            "",
            "- `1d`：只在 regular session 收盘后观察。",
            "- `1h / 15m / 5m`：只在 regular-session bar close 后观察。",
            "- 每周在人工复核完成后生成一次周报。",
            "",
            "## 暂停条件",
            "",
            "| Code | Trigger | Action |",
            "|---|---|---|",
        ]
    )
    for item in queue["pause_conditions"]:
        lines.append(f"| {item['code']} | {item['trigger']} | {item['action']} |")
    lines.extend(
        [
            "",
            "## 排除说明",
            "",
            "- `M10-PA-005` 在 range-geometry 定义修正完成前不进入主观察队列。",
            "- supporting 和 research-only 条目不作为独立观察触发器。",
            "- 整体资金测试为负的策略只保留在 watchlist/deferred，不进入主观察队列。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_weekly_template(path: Path, queue: dict[str, Any]) -> None:
    lines = [
        "# M10.13 Weekly Observation Template",
        "",
        "## Week",
        "",
        "- week range:",
        "- reviewer:",
        "- data source and lineage notes:",
        "",
        "## 本周触发策略",
        "",
        "| Strategy | Symbol | Timeframe | Candidate Events | Skip/No-trade | Manual Review Status |",
        "|---|---|---:|---:|---:|---|",
        "",
        "## 历史基线指标",
        "",
        "| Strategy | Timeframe | Initial Capital | Final Equity | Net Profit | Return % | Trade Count | Win Rate | Profit Factor | Max Drawdown | Max Consecutive Losses | Average Holding Bars |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        "",
        "## 观察质量指标",
        "",
        "| Strategy | Timeframe | Observed Bars | Candidate Events | Skip/No-trade | Deferred Inputs | Schema Pass Rate | Source/Spec Ref Completeness | Review Status | Quality Flag | Lineage | Week-over-week Status |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|",
        "",
        "## 策略和标的分布",
        "",
        "| Strategy | Symbols Seen | Timeframes Seen | Notes |",
        "|---|---|---|---|",
        "",
        "## 资金曲线偏离",
        "",
        "| Strategy | Historical Baseline Ref | Observation Equity Proxy | Deviation | Action |",
        "|---|---:|---:|---:|---|",
        "",
        "## 暂停条件",
        "",
        "| Condition | Hit? | Evidence | Action |",
        "|---|---|---|---|",
    ]
    for item in queue["pause_conditions"]:
        lines.append(f"| {item['code']} |  |  | {item['action']} |")
    lines.extend(
        [
            "",
            "## 人工复核结论",
            "",
            "- continue_observation:",
            "- needs_definition_fix:",
            "- needs_visual_review:",
            "- reject_for_now:",
            "",
            "## 边界",
            "",
            "本周报模板不批准 paper trading、broker connection、live execution 或 real orders。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def collect_timeframe_metrics() -> list[dict[str, str]]:
    rows = []
    for path in [WAVE_A_METRICS, WAVE_B_METRICS]:
        for row in read_csv(path):
            if row["grain"] == "strategy_timeframe" and row["cost_tier"] == "baseline":
                rows.append(row)
    return rows


def timeframe_sort_key(timeframe: str) -> int:
    return {"1d": 0, "1h": 1, "15m": 2, "5m": 3}.get(timeframe, 99)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def format_output_dir(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def validate_outputs(output_dir: Path) -> None:
    combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in output_dir.glob("*"))
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_STRINGS:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden output string found: {forbidden}")


if __name__ == "__main__":
    run_m10_13_read_only_runbook()
