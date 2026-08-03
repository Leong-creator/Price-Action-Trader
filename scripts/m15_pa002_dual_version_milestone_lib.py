#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from scripts.m15_longbridge_fill_attribution_lib import (
    group_completed_trade_performance_rows,
    summarize_completed_trade_rows,
)
from scripts.m15_longbridge_realtime_account_state_lib import (
    FILL_ATTRIBUTION_JSON,
    ROOT,
    load_config as load_account_config,
    project_path,
    read_json,
    write_json,
)


NEW_YORK = ZoneInfo("America/New_York")
POSTMARKET_EVALUATION_TIME = time(16, 15)
DEFAULT_OUTPUT_SUBDIR = ""
DEFAULT_STATUS_JSON = "m15_pa002_dual_version_milestone_status.json"
DEFAULT_REVIEW_JSON = "m15_pa002_dual_version_review.json"
DEFAULT_REVIEW_MD = "m15_pa002_dual_version_review.md"
MARKET_CALENDAR_CONFIG_PATH = ROOT / "config" / "examples" / "m12_47_session_supervisor.json"
BASELINE_RUNTIME_ID = "M10-PA-002-5m"
BASELINE_BUCKET_ID = "pa002_5m"
REPAIRED_RUNTIME_ID = "M10-PA-002-5m-repaired-v1"
REPAIRED_BUCKET_ID = "pa002_5m_repaired_v1"
FINAL_MIN_NET_PNL = Decimal("0")
FINAL_MIN_PROFIT_FACTOR = Decimal("1.20")
FINAL_MIN_AVERAGE_WIN_LOSS_RATIO = Decimal("1.20")
FINAL_MAX_DRAWDOWN = Decimal("400")
FINAL_MAX_CONTRIBUTION_RATIO = Decimal("0.50")


@dataclass(frozen=True, slots=True)
class Pa002DualVersionMilestoneConfig:
    stage: str
    account_config_path: Path
    fill_attribution_path: Path
    output_dir: Path
    status_json_path: Path
    review_json_path: Path
    review_md_path: Path
    technical_review_min_effective_days: int
    final_review_min_effective_days: int
    final_review_min_completed_trades: int


def load_config(account_config_path: str | Path) -> Pa002DualVersionMilestoneConfig:
    account_config = load_account_config(account_config_path)
    output_dir = account_config.output_dir / DEFAULT_OUTPUT_SUBDIR
    return Pa002DualVersionMilestoneConfig(
        stage="M15.pa002_dual_version_milestone",
        account_config_path=Path(account_config_path) if Path(account_config_path).is_absolute() else ROOT / Path(account_config_path),
        fill_attribution_path=account_config.output_dir / FILL_ATTRIBUTION_JSON,
        output_dir=output_dir,
        status_json_path=output_dir / DEFAULT_STATUS_JSON,
        review_json_path=output_dir / DEFAULT_REVIEW_JSON,
        review_md_path=output_dir / DEFAULT_REVIEW_MD,
        technical_review_min_effective_days=5,
        final_review_min_effective_days=15,
        final_review_min_completed_trades=100,
    )


def run_pa002_dual_version_milestone_evaluator(
    account_config_path: str | Path,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    config = load_config(account_config_path)
    generated_at = generated_at or datetime.now(UTC)
    previous = read_json(config.status_json_path)
    payload = build_status_payload(config, generated_at)
    apply_notification_state(payload, previous)
    persist_outputs(config, payload)
    return payload


def build_status_payload(
    config: Pa002DualVersionMilestoneConfig,
    generated_at: datetime,
) -> dict[str, Any]:
    ny_now = generated_at.astimezone(NEW_YORK)
    evaluation_market_date = ny_now.date().isoformat()
    fill_attribution = read_json(config.fill_attribution_path)
    fill_generated_at = str(fill_attribution.get("generated_at") or "")
    completed_trades = [
        dict(row)
        for row in fill_attribution.get("completed_trades", [])
        if isinstance(row, dict) and is_pa002_trade(row)
    ]
    normal_trades = [row for row in completed_trades if not bool(row.get("fault_day"))]
    attribution_anomaly_count = len(
        [
            row
            for row in fill_attribution.get("anomalies", [])
            if isinstance(row, dict) and anomaly_is_pa002(row)
        ]
    )
    version_rows = build_version_rows(
        normal_trades,
        attribution_anomaly_count=attribution_anomaly_count,
    )
    aggregate_summary = summarize_completed_trade_rows(normal_trades)
    aggregate_effective_days = sorted(
        {
            close_market_date(row)
            for row in normal_trades
            if close_market_date(row)
        }
    )
    phase = milestone_phase_for_versions(
        version_rows=version_rows,
        technical_review_min_effective_days=config.technical_review_min_effective_days,
        final_review_min_effective_days=config.final_review_min_effective_days,
        final_review_min_completed_trades=config.final_review_min_completed_trades,
    )
    recommendation = milestone_recommendation(phase, version_rows)
    status_value = evaluation_status(ny_now, fill_attribution, completed_trades)
    notification_dedup_key = build_notification_dedup_key(
        evaluation_market_date=evaluation_market_date,
        status_value=status_value,
        phase=phase,
        recommendation_code=str(recommendation.get("code") or ""),
        effective_day_count=len(aggregate_effective_days),
        completed_trade_count=int(aggregate_summary.get("completed_trade_count", 0) or 0),
        version_rows=version_rows,
    )
    payload = {
        "schema_version": "m15.pa002-dual-version-milestone.v1",
        "stage": config.stage,
        "generated_at": to_utc_iso(generated_at),
        "evaluation_market_date": evaluation_market_date,
        "evaluation_new_york_time": ny_now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "evaluation_status": status_value,
        "milestone_phase": phase,
        "technical_review_min_effective_days": config.technical_review_min_effective_days,
        "final_review_min_effective_days": config.final_review_min_effective_days,
        "final_review_min_completed_trades": config.final_review_min_completed_trades,
        "aggregate": {
            **aggregate_summary,
            "effective_trading_day_count": len(aggregate_effective_days),
            "effective_trading_dates": aggregate_effective_days,
            "version_count": len(version_rows),
        },
        "version_summaries": version_rows,
        "conditional_follow_up_recommendations": build_conditional_follow_up_recommendations(
            phase,
            version_rows,
        ),
        "recommendation": recommendation,
        "notification": {
            "notification_dedup_key": notification_dedup_key,
            "title": "PA002 双版本盘后里程碑评估",
            "plain_text": recommendation.get("plain_text", ""),
            "notification_pending": False,
            "notification_reason": "",
        },
        "source_status": {
            "fill_attribution_ready": bool(fill_attribution),
            "fill_attribution_generated_at": fill_generated_at,
            "pa002_completed_trade_count_including_fault_days": len(completed_trades),
            "pa002_normal_completed_trade_count": len(normal_trades),
            "fill_attribution_anomaly_count": attribution_anomaly_count,
            "postmarket_cutoff_reached": (
                is_us_market_trading_day(ny_now.date()) and ny_now.time() >= POSTMARKET_EVALUATION_TIME
            ),
        },
        "outputs": {
            "status_json": project_path(config.status_json_path),
            "review_json": project_path(config.review_json_path),
            "review_md": project_path(config.review_md_path),
        },
        "refs": {
            "account_config": project_path(config.account_config_path),
            "fill_attribution": project_path(config.fill_attribution_path),
        },
        "paper_simulated_only": True,
        "longbridge_actual_fills_only": True,
        "local_simulation_used": False,
        "live_execution": False,
        "real_money_actions": False,
        "auto_strategy_mutation": False,
        "auto_promotion": False,
        "plain_language_result": recommendation.get("plain_text", ""),
    }
    return payload


def persist_outputs(config: Pa002DualVersionMilestoneConfig, payload: dict[str, Any]) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.status_json_path, payload)
    write_json(config.review_json_path, build_review_payload(payload))
    config.review_md_path.write_text(build_review_md(payload), encoding="utf-8")


def build_review_payload(status_payload: dict[str, Any]) -> dict[str, Any]:
    aggregate = dict(status_payload.get("aggregate") or {})
    recommendation = dict(status_payload.get("recommendation") or {})
    return {
        "schema_version": "m15.pa002-dual-version-milestone-review.v1",
        "stage": status_payload.get("stage", ""),
        "generated_at": status_payload.get("generated_at", ""),
        "evaluation_market_date": status_payload.get("evaluation_market_date", ""),
        "evaluation_status": status_payload.get("evaluation_status", ""),
        "milestone_phase": status_payload.get("milestone_phase", ""),
        "aggregate": aggregate,
        "version_summaries": list(status_payload.get("version_summaries") or []),
        "conditional_follow_up_recommendations": list(
            status_payload.get("conditional_follow_up_recommendations") or []
        ),
        "recommendation": recommendation,
        "notification": dict(status_payload.get("notification") or {}),
        "plain_language_result": status_payload.get("plain_language_result", ""),
    }


def build_review_md(status_payload: dict[str, Any]) -> str:
    aggregate = dict(status_payload.get("aggregate") or {})
    version_rows = list(status_payload.get("version_summaries") or [])
    recommendation = dict(status_payload.get("recommendation") or {})
    lines = [
        "# M15 PA002 双版本盘后里程碑评估",
        "",
        f"- 生成时间: `{status_payload.get('generated_at', '')}`",
        f"- 纽约交易日: `{status_payload.get('evaluation_market_date', '')}`",
        f"- 评估状态: `{status_payload.get('evaluation_status', '')}`",
        f"- 当前阶段: `{status_payload.get('milestone_phase', '')}`",
        f"- 结论: {status_payload.get('plain_language_result', '')}",
        "",
        "## 汇总",
        "",
        f"- 有效交易日: `{aggregate.get('effective_trading_day_count', 0)}`",
        f"- 完整交易: `{aggregate.get('completed_trade_count', 0)}`",
        f"- 扣费后净盈亏: `{aggregate.get('normal_estimated_net_realized_pnl', '')}`",
        f"- 通知去重键: `{status_payload.get('notification', {}).get('notification_dedup_key', '')}`",
        "",
        "## 版本明细",
        "",
        "| 版本 | 有效交易日 | 完整交易 | 扣费后净盈亏 | 胜率 | 盈利因子 | 平均盈亏比 | 最大回撤 | 最终门槛 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in version_rows:
        lines.append(
            f"| {row.get('version_label', '')} | {row.get('effective_trading_day_count', 0)} | "
            f"{row.get('completed_trade_count', 0)} | {row.get('estimated_net_realized_pnl', '')} | "
            f"{row.get('win_rate_after_estimated_fees_pct', '')} | {row.get('profit_factor_after_estimated_fees', '')} | "
            f"{row.get('average_win_loss_ratio_after_estimated_fees', '')} | "
            f"{row.get('maximum_drawdown_after_estimated_fees', '')} | "
            f"{'通过' if row.get('final_quality_gate_passed') else '未通过'} |"
        )
    if not version_rows:
        lines.append("| 无数据 | 0 | 0 | 0.00 | 0.0000 | 0.00 | 0.00 | 0.00 | 未通过 |")
    lines.extend(
        [
            "",
            "## 建议",
            "",
            f"- 建议代码: `{recommendation.get('code', '')}`",
            f"- 说明: {recommendation.get('plain_text', '')}",
            "- 边界: 只给建议，不自动改策略、不自动晋级、不回退任何现有配置。",
            "",
            "## 有条件后续版本",
            "",
        ]
    )
    for row in status_payload.get("conditional_follow_up_recommendations", []):
        lines.append(
            f"- `{row.get('variant_id', '')}`: {row.get('plain_text', '')} "
            f"(状态: `{row.get('status', '')}`)"
        )
    lines.append("")
    return "\n".join(lines)


def evaluation_status(
    ny_now: datetime,
    fill_attribution: dict[str, Any],
    completed_trades: list[dict[str, Any]],
) -> str:
    if not is_us_market_trading_day(ny_now.date()):
        return "waiting_non_trading_day"
    if ny_now.time() < POSTMARKET_EVALUATION_TIME:
        return "waiting_for_postmarket_cutoff"
    if not fill_attribution:
        return "source_not_ready"
    if not completed_trades:
        return "ready_but_no_pa002_completed_trades"
    return "evaluated"


def milestone_phase(
    *,
    effective_day_count: int,
    completed_trade_count: int,
    technical_review_min_effective_days: int,
    final_review_min_effective_days: int,
    final_review_min_completed_trades: int,
) -> str:
    if effective_day_count < technical_review_min_effective_days:
        return "collecting_sample_before_technical_review"
    if effective_day_count < final_review_min_effective_days or completed_trade_count < final_review_min_completed_trades:
        return "technical_review_only"
    return "final_review_ready"


def milestone_phase_for_versions(
    *,
    version_rows: list[dict[str, Any]],
    technical_review_min_effective_days: int,
    final_review_min_effective_days: int,
    final_review_min_completed_trades: int,
) -> str:
    by_label = {str(row.get("version_label") or ""): row for row in version_rows}
    required = [by_label.get("baseline", {}), by_label.get("repaired_v1", {})]
    if any(int(row.get("effective_trading_day_count", 0) or 0) < technical_review_min_effective_days for row in required):
        return "collecting_sample_before_technical_review"
    if any(
        int(row.get("effective_trading_day_count", 0) or 0) < final_review_min_effective_days
        or int(row.get("completed_trade_count", 0) or 0) < final_review_min_completed_trades
        for row in required
    ):
        return "technical_review_only"
    return "final_review_ready"


def milestone_recommendation(
    phase: str,
    version_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if phase == "collecting_sample_before_technical_review":
        return {
            "code": "collect_more_effective_days",
            "plain_text": "PA002 盘后评估已写入，但现行版或修复版至少有一个还没达到 5 个有效交易日，先继续收集长桥实际完整交易样本。",
        }
    if phase == "technical_review_only":
        return {
            "code": "technical_check_only_keep_sampling",
            "plain_text": "PA002 已达到 5 个有效交易日，可做技术检查；但未同时满足 15 个有效交易日和 100 笔完整交易，暂不做最终去留判断。",
        }
    eligible_rows = [row for row in version_rows if bool(row.get("final_quality_gate_passed"))]
    best = best_version_row(eligible_rows)
    if best is None:
        return {
            "code": "final_review_no_version_passes_quality_gate",
            "plain_text": "PA002 已满足最终样本门槛，但没有版本同时通过净利润、盈利因子、平均盈亏比、回撤、集中度和归因完整性要求；保留人工复核，不自动切换。",
        }
    return {
        "code": "final_review_manual_compare_best_version",
        "plain_text": (
            f"PA002 已满足最终评估门槛；当前通过全部质量门槛且扣费后最优的是 {best.get('version_label', '')}，"
            "建议人工复核后再决定保留哪个版本，不自动切换。"
        ),
    }


def build_version_rows(
    normal_trades: list[dict[str, Any]],
    *,
    attribution_anomaly_count: int = 0,
) -> list[dict[str, Any]]:
    by_version: dict[str, list[dict[str, Any]]] = {}
    for row in normal_trades:
        version_label = resolve_version_label(row)
        by_version.setdefault(version_label, []).append(row)
    version_rows: list[dict[str, Any]] = []
    for version_label, rows in sorted(by_version.items()):
        summary = summarize_completed_trade_rows(rows)
        perf_rows = group_completed_trade_performance_rows(rows, "runtime_id")
        best_runtime = best_runtime_row(perf_rows)
        quality = completed_trade_quality(rows)
        version_rows.append(
            {
                "version_label": version_label,
                "runtime_ids": sorted({str(row.get("runtime_id") or "") for row in rows if str(row.get("runtime_id") or "")}),
                "capital_buckets": sorted({str(row.get("capital_bucket") or "") for row in rows if str(row.get("capital_bucket") or "")}),
                "effective_trading_day_count": len(
                    {
                        close_market_date(row)
                        for row in rows
                        if close_market_date(row)
                    }
                ),
                "completed_trade_count": summary.get("completed_trade_count", 0),
                "gross_realized_pnl": summary.get("gross_realized_pnl", "0.00"),
                "estimated_fees": summary.get("estimated_fees", "0.00"),
                "estimated_net_realized_pnl": summary.get("estimated_net_realized_pnl", "0.00"),
                "win_rate_after_estimated_fees_pct": str(best_runtime.get("win_rate_after_estimated_fees_pct", "0.0000")),
                "profit_factor_after_estimated_fees": str(best_runtime.get("profit_factor_after_estimated_fees", "")),
                "maximum_drawdown_after_estimated_fees": str(best_runtime.get("maximum_drawdown_after_estimated_fees", "")),
                **quality,
                **final_quality_gate(
                    summary=summary,
                    performance=best_runtime,
                    quality=quality,
                    attribution_anomaly_count=attribution_anomaly_count,
                ),
            }
        )
    for required_label, runtime_id, bucket_id in (
        ("baseline", BASELINE_RUNTIME_ID, BASELINE_BUCKET_ID),
        ("repaired_v1", REPAIRED_RUNTIME_ID, REPAIRED_BUCKET_ID),
    ):
        if any(row.get("version_label") == required_label for row in version_rows):
            continue
        version_rows.append(
            {
                "version_label": required_label,
                "runtime_ids": [runtime_id],
                "capital_buckets": [bucket_id],
                "effective_trading_day_count": 0,
                "completed_trade_count": 0,
                "gross_realized_pnl": "0.00",
                "estimated_fees": "0.00",
                "estimated_net_realized_pnl": "0.00",
                "win_rate_after_estimated_fees_pct": "0.0000",
                "profit_factor_after_estimated_fees": "",
                "maximum_drawdown_after_estimated_fees": "0.00",
                "average_win_after_estimated_fees": "0.00",
                "average_loss_after_estimated_fees": "0.00",
                "average_win_loss_ratio_after_estimated_fees": "0.0000",
                "maximum_symbol_profit_contribution_ratio": "0.0000",
                "maximum_day_profit_contribution_ratio": "0.0000",
                "final_quality_gate_passed": False,
                "final_quality_gate_blockers": ["insufficient_completed_trades"],
            }
        )
    version_rows.sort(
        key=lambda row: (
            -int(row.get("effective_trading_day_count", 0) or 0),
            -int(row.get("completed_trade_count", 0) or 0),
            -decimal_value(row.get("estimated_net_realized_pnl")),
            str(row.get("version_label") or ""),
        )
    )
    return version_rows


def completed_trade_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    net_values = [decimal_value(row.get("estimated_net_pnl")) for row in rows]
    wins = [value for value in net_values if value > 0]
    losses = [-value for value in net_values if value < 0]
    average_win = sum(wins, Decimal("0")) / Decimal(len(wins)) if wins else Decimal("0")
    average_loss = sum(losses, Decimal("0")) / Decimal(len(losses)) if losses else Decimal("0")
    average_ratio = (
        average_win / average_loss
        if average_loss > 0
        else (Decimal("999") if average_win > 0 else Decimal("0"))
    )
    positive_total = sum(wins, Decimal("0"))
    negative_total = sum(losses, Decimal("0"))
    profit_factor = (
        positive_total / negative_total
        if negative_total > 0
        else (Decimal("999") if positive_total > 0 else Decimal("0"))
    )
    symbol_profit: dict[str, Decimal] = {}
    day_profit: dict[str, Decimal] = {}
    for row, net in zip(rows, net_values):
        if net <= 0:
            continue
        symbol = str(row.get("symbol") or "unknown")
        market_date = close_market_date(row) or "unknown"
        symbol_profit[symbol] = symbol_profit.get(symbol, Decimal("0")) + net
        day_profit[market_date] = day_profit.get(market_date, Decimal("0")) + net
    max_symbol_ratio = (
        max(symbol_profit.values(), default=Decimal("0")) / positive_total
        if positive_total > 0
        else Decimal("0")
    )
    max_day_ratio = (
        max(day_profit.values(), default=Decimal("0")) / positive_total
        if positive_total > 0
        else Decimal("0")
    )
    return {
        "average_win_after_estimated_fees": fmt_decimal(average_win, 2),
        "average_loss_after_estimated_fees": fmt_decimal(average_loss, 2),
        "average_win_loss_ratio_after_estimated_fees": fmt_decimal(average_ratio, 4),
        "profit_factor_after_estimated_fees": fmt_decimal(profit_factor, 4),
        "maximum_symbol_profit_contribution_ratio": fmt_decimal(max_symbol_ratio, 4),
        "maximum_day_profit_contribution_ratio": fmt_decimal(max_day_ratio, 4),
    }


def final_quality_gate(
    *,
    summary: dict[str, Any],
    performance: dict[str, Any],
    quality: dict[str, Any],
    attribution_anomaly_count: int,
) -> dict[str, Any]:
    blockers: list[str] = []
    if decimal_value(summary.get("estimated_net_realized_pnl")) <= FINAL_MIN_NET_PNL:
        blockers.append("net_pnl_not_positive")
    if decimal_value(quality.get("profit_factor_after_estimated_fees")) < FINAL_MIN_PROFIT_FACTOR:
        blockers.append("profit_factor_below_1_20")
    if decimal_value(quality.get("average_win_loss_ratio_after_estimated_fees")) < FINAL_MIN_AVERAGE_WIN_LOSS_RATIO:
        blockers.append("average_win_loss_ratio_below_1_20")
    if decimal_value(performance.get("maximum_drawdown_after_estimated_fees")) > FINAL_MAX_DRAWDOWN:
        blockers.append("maximum_drawdown_above_400")
    if decimal_value(quality.get("maximum_symbol_profit_contribution_ratio")) > FINAL_MAX_CONTRIBUTION_RATIO:
        blockers.append("profit_too_concentrated_by_symbol")
    if decimal_value(quality.get("maximum_day_profit_contribution_ratio")) > FINAL_MAX_CONTRIBUTION_RATIO:
        blockers.append("profit_too_concentrated_by_day")
    if attribution_anomaly_count:
        blockers.append("fill_attribution_anomaly_present")
    return {
        "final_quality_gate_passed": not blockers,
        "final_quality_gate_blockers": blockers,
        "final_quality_gate_thresholds": {
            "net_pnl_min_exclusive": "0.00",
            "profit_factor_min": "1.20",
            "average_win_loss_ratio_min": "1.20",
            "maximum_drawdown_max": "400.00",
            "maximum_symbol_profit_contribution_ratio_max": "0.5000",
            "maximum_day_profit_contribution_ratio_max": "0.5000",
            "fill_attribution_anomaly_count_max": 0,
        },
    }


def build_conditional_follow_up_recommendations(
    phase: str,
    version_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    repaired = next(
        (row for row in version_rows if row.get("version_label") == "repaired_v1"),
        {},
    )
    trade_count = int(repaired.get("completed_trade_count", 0) or 0)
    profit_factor = decimal_value(repaired.get("profit_factor_after_estimated_fees"))
    win_rate = decimal_value(repaired.get("win_rate_after_estimated_fees_pct"))
    average_ratio = decimal_value(repaired.get("average_win_loss_ratio_after_estimated_fees"))
    review_available = phase in {"technical_review_only", "final_review_ready"}
    recommendations = [
        {
            "variant_id": "pa002-next-bar-confirmation",
            "status": "recommend_for_separate_test" if review_available and trade_count >= 20 and profit_factor < Decimal("0.80") else "not_triggered",
            "plain_text": "仅当复刻版已有至少20笔且盈利因子低于0.80时，单独测试下一根五分钟K线继续确认。",
        },
        {
            "variant_id": "pa002-strong-breakout-filter",
            "status": "recommend_for_separate_test" if review_available and trade_count >= 30 and win_rate < Decimal("30") else "not_triggered",
            "plain_text": "仅当复刻版已有至少30笔且扣费后胜率低于30%时，单独测试更严格的突破实体、收盘位置和成交量门槛。",
        },
        {
            "variant_id": "pa002-market-sector-confirmation",
            "status": "awaiting_market_context_evidence",
            "plain_text": "只有成交诊断能证明亏损集中于大盘、科技或芯片板块逆风日时，才单独测试市场和行业确认；当前不自动启用。",
        },
        {
            "variant_id": "pa002-structure-stop-2r-target",
            "status": "recommend_for_separate_test" if review_available and trade_count >= 30 and win_rate >= Decimal("35") and average_ratio < Decimal("1.20") else "not_triggered",
            "plain_text": "仅当复刻版已有至少30笔、胜率不低于35%但平均盈亏比低于1.20时，单独测试结构止损和2R目标。",
        },
    ]
    return recommendations


def best_runtime_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    return max(
        rows,
        key=lambda row: (
            decimal_value(row.get("estimated_net_realized_pnl")),
            int(row.get("completed_trade_count", 0) or 0),
        ),
    )


def best_version_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            decimal_value(row.get("estimated_net_realized_pnl")),
            int(row.get("completed_trade_count", 0) or 0),
        ),
    )


def resolve_version_label(row: dict[str, Any]) -> str:
    runtime_id = str(row.get("runtime_id") or "")
    capital_bucket = str(row.get("capital_bucket") or "")
    lower_runtime = runtime_id.lower()
    lower_bucket = capital_bucket.lower()
    if runtime_id == BASELINE_RUNTIME_ID or capital_bucket == BASELINE_BUCKET_ID:
        return "baseline"
    if runtime_id == REPAIRED_RUNTIME_ID or capital_bucket == REPAIRED_BUCKET_ID:
        return "repaired_v1"
    if any(token in lower_runtime or token in lower_bucket for token in ("repair", "repaired", "dual", "variant", "modify", "shadow")):
        return runtime_id or capital_bucket or "variant"
    return runtime_id or capital_bucket or "unknown"


def is_pa002_trade(row: dict[str, Any]) -> bool:
    runtime_id = str(row.get("runtime_id") or "")
    capital_bucket = str(row.get("capital_bucket") or "")
    return (
        runtime_id in {BASELINE_RUNTIME_ID, REPAIRED_RUNTIME_ID}
        or capital_bucket in {BASELINE_BUCKET_ID, REPAIRED_BUCKET_ID}
    )


def anomaly_is_pa002(row: dict[str, Any]) -> bool:
    exact_identities = {
        BASELINE_RUNTIME_ID,
        BASELINE_BUCKET_ID,
        REPAIRED_RUNTIME_ID,
        REPAIRED_BUCKET_ID,
    }

    def contains_identity(value: Any) -> bool:
        if isinstance(value, dict):
            return any(contains_identity(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(contains_identity(item) for item in value)
        return str(value or "") in exact_identities

    return contains_identity(row)


def close_market_date(row: dict[str, Any]) -> str:
    market_date = str(row.get("close_market_date") or "")
    if market_date:
        return market_date
    return ny_market_date_from_iso(str(row.get("closed_at") or ""))


def ny_market_date_from_iso(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(NEW_YORK).date().isoformat()


def build_notification_dedup_key(
    *,
    evaluation_market_date: str,
    status_value: str,
    phase: str,
    recommendation_code: str,
    effective_day_count: int,
    completed_trade_count: int,
    version_rows: list[dict[str, Any]],
) -> str:
    version_signature = "|".join(
        f"{row.get('version_label','')}:{row.get('completed_trade_count',0)}:{row.get('estimated_net_realized_pnl','0.00')}"
        for row in version_rows
    )
    return (
        f"pa002-dual-version:{evaluation_market_date}:{status_value}:{phase}:{recommendation_code}:"
        f"{effective_day_count}:{completed_trade_count}:{version_signature}"
    )


def apply_notification_state(payload: dict[str, Any], previous: dict[str, Any]) -> None:
    notification = payload.get("notification") if isinstance(payload.get("notification"), dict) else {}
    phase = str(payload.get("milestone_phase") or "")
    previous_phase = str(previous.get("milestone_phase") or "")
    status = str(payload.get("evaluation_status") or "")
    previous_status = str(previous.get("evaluation_status") or "")
    anomaly_count = int(payload.get("source_status", {}).get("fill_attribution_anomaly_count", 0) or 0)
    previous_anomaly_count = int(previous.get("source_status", {}).get("fill_attribution_anomaly_count", 0) or 0)
    milestone_reached = phase in {"technical_review_only", "final_review_ready"} and phase != previous_phase
    anomaly = (
        status == "source_not_ready" and status != previous_status
    ) or (anomaly_count > 0 and previous_anomaly_count == 0)
    notification["notification_pending"] = bool(milestone_reached or anomaly)
    notification["notification_reason"] = (
        "new_milestone" if milestone_reached else ("source_anomaly" if anomaly else "no_new_milestone")
    )
    payload["notification"] = notification


def is_us_market_trading_day(value: date) -> bool:
    return value.weekday() < 5 and value not in load_us_market_holidays()


def load_us_market_holidays() -> frozenset[date]:
    payload = read_json(MARKET_CALENDAR_CONFIG_PATH)
    holidays: set[date] = set()
    for raw in payload.get("market_holidays", []):
        if not isinstance(raw, str):
            continue
        try:
            holidays.add(date.fromisoformat(raw))
        except ValueError:
            continue
    return frozenset(holidays)


def decimal_value(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def fmt_decimal(value: Decimal, places: int) -> str:
    quantum = Decimal("1").scaleb(-places)
    return str(value.quantize(quantum))


def to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
