#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_capital_backtest_lib import (  # noqa: E402
    CAPITAL_MODEL_PATH,
    M10_8_DIR,
    CandidateTrade,
    CapitalTrade,
    build_metric_rows,
    load_capital_model,
    simulate_account,
)


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M10_4_DIR = M10_DIR / "historical_pilot" / "m10_4_wave_a_pilot"
M10_9_DIR = M10_DIR / "definition_tightening" / "m10_9_pa_005"
STRATEGY_ID = "M10-PA-005"
TIMEFRAMES = ("1d", "1h", "15m", "5m")
INTRADAY_COOLDOWN_MINUTES = {"1h": 20 * 60, "15m": 20 * 15, "5m": 20 * 5}
FORBIDDEN_OUTPUT_STRINGS = (
    "PA-SC-",
    "SF-",
    "live-ready",
    "broker_connection=true",
    "real_orders=true",
)


@dataclass(frozen=True, slots=True)
class TighteningLedgerRow:
    strategy_id: str
    timeframe: str
    before_candidates: int
    after_dedupe_candidates: int
    after_tightening_candidates: int
    duplicate_removed: int
    cooldown_removed: int
    cooldown_minutes: int
    range_geometry_fields_available: bool
    definition_tightening_status: str
    review_note: str


def run_m10_9_definition_tightening(output_dir: Path = M10_9_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    model = load_capital_model(CAPITAL_MODEL_PATH)

    all_after_trades: list[CapitalTrade] = []
    ledger_rows: list[TighteningLedgerRow] = []
    for timeframe in TIMEFRAMES:
        candidates = load_pa005_candidates(timeframe)
        kept, ledger = tighten_candidates(candidates, timeframe)
        ledger_rows.append(ledger)
        for symbol, symbol_candidates in group_by_symbol(kept).items():
            for tier in model.cost_tiers:
                all_after_trades.extend(
                    simulate_account(
                        candidates=symbol_candidates,
                        model=model,
                        tier=tier,
                        spec_ref=f"reports/strategy_lab/m10_price_action_strategy_refresh/backtest_specs/{STRATEGY_ID}.json",
                        source_ledger_ref=(
                            "reports/strategy_lab/m10_price_action_strategy_refresh/historical_pilot/"
                            f"m10_4_wave_a_pilot/{STRATEGY_ID}/{timeframe}/source_ledger.json"
                        ),
                        quality_flag=quality_flag_for_after(timeframe),
                    )
                )

    after_metrics = build_metric_rows(all_after_trades, model)
    before_metrics = load_m10_8_metrics()
    before_after_rows = build_before_after_rows(before_metrics, after_metrics, ledger_rows)
    write_before_after_metrics(output_dir / "m10_9_before_after_metrics.csv", before_after_rows)
    write_json(output_dir / "m10_9_definition_filter_ledger.json", build_filter_ledger(ledger_rows))
    summary = build_summary(ledger_rows, before_after_rows, output_dir)
    write_json(output_dir / "m10_9_retest_summary.json", summary)
    write_definition_report(output_dir / "m10_9_definition_fix_report.md", ledger_rows, before_after_rows)
    write_client_summary(output_dir / "m10_9_wave_a_retest_client_summary.md", before_after_rows)
    validate_outputs(output_dir)
    return summary


def load_pa005_candidates(timeframe: str) -> list[CandidateTrade]:
    path = M10_4_DIR / STRATEGY_ID / timeframe / "candidate_events.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            CandidateTrade(
                strategy_id=row["strategy_id"],
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                direction=row["direction"],
                signal_timestamp=row["signal_timestamp"],
                entry_timestamp=row["entry_timestamp"],
                entry_price=Decimal(row["entry_price"]),
                stop_price=Decimal(row["stop_price"]),
                target_price=Decimal(row["target_price"]),
                risk_per_share=Decimal(row["risk_per_share"]),
                exit_timestamp=row["exit_timestamp"],
                exit_price=Decimal(row["exit_price"]),
                exit_reason=row["exit_reason"],
                gross_r=Decimal(row["gross_r"]),
                baseline_net_r=Decimal(row["baseline_net_r"]),
                setup_notes=row["setup_notes"],
            )
            for row in csv.DictReader(handle)
        ]


def tighten_candidates(
    candidates: Iterable[CandidateTrade],
    timeframe: str,
) -> tuple[list[CandidateTrade], TighteningLedgerRow]:
    ordered = sorted(candidates, key=lambda item: (item.symbol, item.direction, item.entry_timestamp))
    deduped: list[CandidateTrade] = []
    seen: set[tuple[str, str, str, str]] = set()
    for candidate in ordered:
        key = (
            candidate.symbol,
            candidate.direction,
            candidate.signal_timestamp,
            candidate.entry_timestamp,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    if timeframe in INTRADAY_COOLDOWN_MINUTES:
        kept = apply_intraday_cooldown(deduped, timeframe)
    else:
        kept = deduped

    duplicate_removed = len(ordered) - len(deduped)
    cooldown_removed = len(deduped) - len(kept)
    status = "definition_breadth_reduced_not_cleared" if timeframe in INTRADAY_COOLDOWN_MINUTES else "daily_duplicate_cleanup_only"
    review_note = (
        "日内复测移除重复确认事件，并对同标的同方向失败突破施加 20-bar 成熟窗口冷却；range geometry 仍需上游持久化。"
        if timeframe in INTRADAY_COOLDOWN_MINUTES
        else "日线仅移除完全重复的确认事件，不应用日内冷却。"
    )
    return kept, TighteningLedgerRow(
        strategy_id=STRATEGY_ID,
        timeframe=timeframe,
        before_candidates=len(ordered),
        after_dedupe_candidates=len(deduped),
        after_tightening_candidates=len(kept),
        duplicate_removed=duplicate_removed,
        cooldown_removed=cooldown_removed,
        cooldown_minutes=INTRADAY_COOLDOWN_MINUTES.get(timeframe, 0),
        range_geometry_fields_available=False,
        definition_tightening_status=status,
        review_note=review_note,
    )


def apply_intraday_cooldown(candidates: list[CandidateTrade], timeframe: str) -> list[CandidateTrade]:
    minimum_gap = timedelta(minutes=INTRADAY_COOLDOWN_MINUTES[timeframe])
    last_kept: dict[tuple[str, str], datetime] = {}
    kept: list[CandidateTrade] = []
    for candidate in candidates:
        key = (candidate.symbol, candidate.direction)
        entry_timestamp = datetime.fromisoformat(candidate.entry_timestamp)
        previous = last_kept.get(key)
        if previous is not None and entry_timestamp - previous < minimum_gap:
            continue
        kept.append(candidate)
        last_kept[key] = entry_timestamp
    return kept


def group_by_symbol(candidates: Iterable[CandidateTrade]) -> dict[str, list[CandidateTrade]]:
    grouped: dict[str, list[CandidateTrade]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.symbol].append(candidate)
    return dict(grouped)


def quality_flag_for_after(timeframe: str) -> str:
    if timeframe in INTRADAY_COOLDOWN_MINUTES:
        return "definition_breadth_review"
    return "normal_density_review"


def load_m10_8_metrics() -> list[dict[str, str]]:
    path = M10_8_DIR / "m10_8_wave_a_metrics.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle)]


def build_before_after_rows(
    before_rows: list[dict[str, str]],
    after_rows: list[dict[str, str]],
    ledger_rows: list[TighteningLedgerRow],
) -> list[dict[str, str]]:
    before_by_key = {
        (row["timeframe"], row["cost_tier"]): row
        for row in before_rows
        if row["strategy_id"] == STRATEGY_ID and row["grain"] == "strategy_timeframe"
    }
    after_by_key = {
        (row["timeframe"], row["cost_tier"]): row
        for row in after_rows
        if row["strategy_id"] == STRATEGY_ID and row["grain"] == "strategy_timeframe"
    }
    ledger_by_timeframe = {row.timeframe: row for row in ledger_rows}
    output: list[dict[str, str]] = []
    for timeframe in TIMEFRAMES:
        ledger = ledger_by_timeframe[timeframe]
        for cost_tier in ("baseline", "stress_low", "stress_high"):
            before = before_by_key[(timeframe, cost_tier)]
            after = after_by_key[(timeframe, cost_tier)]
            output.append(
                {
                    "strategy_id": STRATEGY_ID,
                    "timeframe": timeframe,
                    "cost_tier": cost_tier,
                    "before_trade_count": before["trade_count"],
                    "after_trade_count": after["trade_count"],
                    "removed_count": str(int(before["trade_count"]) - int(after["trade_count"])),
                    "removed_percent": percent(int(before["trade_count"]) - int(after["trade_count"]), int(before["trade_count"])),
                    "before_net_profit": before["net_profit"],
                    "after_net_profit": after["net_profit"],
                    "delta_net_profit": decimal_delta(after["net_profit"], before["net_profit"]),
                    "before_return_percent": before["return_percent"],
                    "after_return_percent": after["return_percent"],
                    "before_win_rate": before["win_rate"],
                    "after_win_rate": after["win_rate"],
                    "before_profit_factor": before["profit_factor"],
                    "after_profit_factor": after["profit_factor"],
                    "before_max_drawdown": before["max_drawdown"],
                    "after_max_drawdown": after["max_drawdown"],
                    "before_status": before["status"],
                    "after_status": after["status"],
                    "definition_tightening_status": ledger.definition_tightening_status,
                    "range_geometry_fields_available": str(ledger.range_geometry_fields_available).lower(),
                    "review_note": ledger.review_note,
                }
            )
    return output


def build_filter_ledger(rows: list[TighteningLedgerRow]) -> dict[str, Any]:
    return {
        "schema_version": "m10.9.definition-filter-ledger.v1",
        "stage": "M10.9.definition_tightening",
        "strategy_id": STRATEGY_ID,
        "filter_basis": "non_pnl_structural_cleanup",
        "filters": [
            "dedupe_same_symbol_direction_signal_entry_confirmation",
            "intraday_same_symbol_direction_20_bar_cooldown",
        ],
        "range_geometry_fields_available": False,
        "upstream_gap": "M10.4 candidate_events.csv 未持久化 range_high/range_low/range_midpoint/breakout_extreme/reentry_confirmation_index，因此 M10.9 不能只靠交易行完整复核 Brooks 交易区间结构。",
        "rows": [ledger_row_to_dict(row) for row in rows],
    }


def build_summary(
    ledger_rows: list[TighteningLedgerRow],
    before_after_rows: list[dict[str, str]],
    output_dir: Path,
) -> dict[str, Any]:
    baseline = [row for row in before_after_rows if row["cost_tier"] == "baseline"]
    return {
        "schema_version": "m10.9.definition-tightening-summary.v1",
        "generated_at": "2026-04-27T00:00:00Z",
        "stage": "M10.9.definition_tightening",
        "strategy_id": STRATEGY_ID,
        "affected_timeframes": list(TIMEFRAMES),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_account": False,
        "real_orders": False,
        "paper_trading_approval": False,
        "capital_model_ref": "reports/strategy_lab/m10_price_action_strategy_refresh/m10_7_capital_model.json",
        "m10_8_input_ref": "reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_8_wave_a/m10_8_wave_a_metrics.csv",
        "output_dir": output_dir.relative_to(ROOT).as_posix(),
        "filter_ledger": [ledger_row_to_dict(row) for row in ledger_rows],
        "baseline_before_after": baseline,
        "definition_cleared": False,
        "definition_cleared_reason": "事件数量已降低，但 range geometry 字段仍缺失；在上游 detector 持久化结构化区间证据前，M10-PA-005 继续保留 definition review。",
    }


def write_before_after_metrics(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "strategy_id",
        "timeframe",
        "cost_tier",
        "before_trade_count",
        "after_trade_count",
        "removed_count",
        "removed_percent",
        "before_net_profit",
        "after_net_profit",
        "delta_net_profit",
        "before_return_percent",
        "after_return_percent",
        "before_win_rate",
        "after_win_rate",
        "before_profit_factor",
        "after_profit_factor",
        "before_max_drawdown",
        "after_max_drawdown",
        "before_status",
        "after_status",
        "definition_tightening_status",
        "range_geometry_fields_available",
        "review_note",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_definition_report(
    path: Path,
    ledger_rows: list[TighteningLedgerRow],
    before_after_rows: list[dict[str, str]],
) -> None:
    baseline = [row for row in before_after_rows if row["cost_tier"] == "baseline"]
    lines = [
        "# M10.9 定义修正报告",
        "",
        "## 摘要",
        "",
        "- 范围：只处理 `M10-PA-005`。",
        "- 规则：先移除重复确认事件，再对 `1h / 15m / 5m` 的同标的同方向触发施加 20-bar 冷却。",
        "- 依据：只做结构性清理；没有任何过滤条件使用 PnL、资金曲线、胜率或 profit factor。",
        "- 结果：触发密度下降，但定义尚未解除复核，因为 M10.4 没有持久化 range geometry 字段。",
        "",
        "## 过滤账本",
        "",
        "| Timeframe | Before | After Dedupe | After Tightening | Removed | Cooldown Removed | Status |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in ledger_rows:
        removed = row.before_candidates - row.after_tightening_candidates
        lines.append(
            f"| {row.timeframe} | {row.before_candidates} | {row.after_dedupe_candidates} | "
            f"{row.after_tightening_candidates} | {removed} | {row.cooldown_removed} | "
            f"{row.definition_tightening_status} |"
        )
    lines.extend(
        [
            "",
            "## Baseline 复测指标",
            "",
            "| Timeframe | Before Trades | After Trades | Before Net Profit | After Net Profit | Before Win Rate | After Win Rate | Before Max DD | After Max DD |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in baseline:
        lines.append(
            f"| {row['timeframe']} | {row['before_trade_count']} | {row['after_trade_count']} | "
            f"{row['before_net_profit']} | {row['after_net_profit']} | {row['before_win_rate']} | "
            f"{row['after_win_rate']} | {row['before_max_drawdown']} | {row['after_max_drawdown']} |"
        )
    lines.extend(
        [
            "",
            "## 上游缺口",
            "",
            "- 当前 candidate events 不包含 `range_high`、`range_low`、`range_midpoint`、`breakout_extreme` 或 `reentry_confirmation_index`。",
            "- 因为这些字段缺失，本阶段不能诚实地声称 Brooks 交易区间定义已经完全修好。",
            "- `M10-PA-005` 继续保持 `needs_definition_fix`；本次复测只作为清理后的对照，不作为升级决策。",
            "",
            "## 边界",
            "",
            "本阶段只是历史模拟复测。不接 broker，不接真实账户，不启用自动执行，不批准 paper trading，也不开放真实订单路径。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_client_summary(path: Path, before_after_rows: list[dict[str, str]]) -> None:
    baseline = [row for row in before_after_rows if row["cost_tier"] == "baseline"]
    lines = [
        "# M10.9 Wave A 复测客户摘要",
        "",
        "## 本次改了什么",
        "",
        "`M10-PA-005` 在日内数据上触发过密。本次复测移除重复触发，并限制同一个 20-bar 窗口内反复出现的同方向失败突破触发。",
        "",
        "## 给甲方看的结果",
        "",
        "| Timeframe | Trades Before | Trades After | Net Profit Before | Net Profit After | Win Rate Before | Win Rate After | Decision |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in baseline:
        decision = "keep_in_definition_review" if row["timeframe"] in INTRADAY_COOLDOWN_MINUTES else "daily_reference_only"
        lines.append(
            f"| {row['timeframe']} | {row['before_trade_count']} | {row['after_trade_count']} | "
            f"{row['before_net_profit']} | {row['after_net_profit']} | {row['before_win_rate']} | "
            f"{row['after_win_rate']} | {decision} |"
        )
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "本次清理让测试噪音下降，尤其是 `5m` 和 `15m`。但这个策略还不能解除定义复核。下一步真正要修的是让 detector 记录实际交易区间边界、中点、突破极值和重新回到区间内的确认 bar，这样才能从策略结构本身审计，而不是只从交易结果行反推。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_outputs(output_dir: Path) -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in [
            output_dir / "m10_9_retest_summary.json",
            output_dir / "m10_9_definition_filter_ledger.json",
            output_dir / "m10_9_definition_fix_report.md",
            output_dir / "m10_9_wave_a_retest_client_summary.md",
        ]
        if path.exists()
    )
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_STRINGS:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden output string found: {forbidden}")


def ledger_row_to_dict(row: TighteningLedgerRow) -> dict[str, Any]:
    return {
        "strategy_id": row.strategy_id,
        "timeframe": row.timeframe,
        "before_candidates": row.before_candidates,
        "after_dedupe_candidates": row.after_dedupe_candidates,
        "after_tightening_candidates": row.after_tightening_candidates,
        "duplicate_removed": row.duplicate_removed,
        "cooldown_removed": row.cooldown_removed,
        "cooldown_minutes": row.cooldown_minutes,
        "range_geometry_fields_available": row.range_geometry_fields_available,
        "definition_tightening_status": row.definition_tightening_status,
        "review_note": row.review_note,
    }


def percent(part: int, whole: int) -> str:
    if whole <= 0:
        return "0.0000"
    return f"{(Decimal(part) / Decimal(whole) * Decimal('100')):.4f}"


def decimal_delta(after: str, before: str) -> str:
    return f"{(Decimal(after) - Decimal(before)):.2f}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run_m10_9_definition_tightening()
