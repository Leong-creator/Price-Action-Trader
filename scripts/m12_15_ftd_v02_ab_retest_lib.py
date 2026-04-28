#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.m12_12_daily_observation_loop_lib import (  # noqa: E402
    FORMAL_DAILY_ID,
    M1212Config,
    FormalTrade,
    best_cache_file,
    classify_daily_context,
    daily_signal_quality,
    decimal,
    load_bars,
    load_config as load_m12_12_config,
    metric_row_for_trades,
    money,
    pct,
    project_path,
    resolve_trade_exit,
    select_first_batch_symbols,
)


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
SOURCE_REVISIT_DIR = M10_DIR / "source_revisit" / "m12_14_source_strategy_closure"
OUTPUT_DIR = M10_DIR / "ftd_v02_ab_retest" / "m12_15"
MONEY = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
FORBIDDEN_OUTPUT_TEXT = (
    "live-ready",
    "real_orders=true",
    "broker_connection=true",
    "paper approval",
    "real order",
    "real account",
)


@dataclass(frozen=True, slots=True)
class VariantSpec:
    variant_id: str
    title: str
    plain_rule: str
    entry_mode: str
    source_fields: tuple[str, ...]
    use_pullback_guard: bool = False
    use_follow_through_confirm: bool = False
    use_context_signal_quality: bool = False
    use_higher_timeframe_proxy: bool = False


VARIANTS: tuple[VariantSpec, ...] = (
    VariantSpec(
        variant_id="baseline",
        title="M12.12 简化版",
        plain_rule="沿用 M12.12 当前规则，作为对照组。",
        entry_mode="next_open",
        source_fields=("行情背景", "信号K质量", "止损和目标"),
    ),
    VariantSpec(
        variant_id="pullback_guard",
        title="只加长回调保护",
        plain_rule="当回调拖得太久时，不再把顺势信号K当普通趋势恢复。",
        entry_mode="next_open",
        source_fields=("长回调保护",),
        use_pullback_guard=True,
    ),
    VariantSpec(
        variant_id="follow_through_confirm",
        title="只加1-2根K线跟进确认",
        plain_rule="信号K后必须在1-2根K线内出现同向跟进，否则跳过。",
        entry_mode="confirmation_close",
        source_fields=("入场确认",),
        use_follow_through_confirm=True,
    ),
    VariantSpec(
        variant_id="context_signal_quality",
        title="行情背景 + 信号K质量",
        plain_rule="要求更清楚的趋势背景和更强的信号K，过滤震荡里的强K线。",
        entry_mode="next_open",
        source_fields=("行情背景", "信号K质量"),
        use_context_signal_quality=True,
    ),
    VariantSpec(
        variant_id="full_v02",
        title="完整多来源增强版",
        plain_rule="同时使用长回调保护、跟进确认、背景分类、信号K质量和更高周期近似过滤。",
        entry_mode="confirmation_close",
        source_fields=("行情背景", "信号K质量", "更高周期一致性", "长回调保护", "入场确认", "止损和目标"),
        use_pullback_guard=True,
        use_follow_through_confirm=True,
        use_context_signal_quality=True,
        use_higher_timeframe_proxy=True,
    ),
)


def run_m12_15_ftd_v02_ab_retest(
    config: M1212Config | None = None,
    *,
    generated_at: str | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    config = config or load_m12_12_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)

    source_ledger = json.loads((SOURCE_REVISIT_DIR / "m12_14_early_strategy_multisource_definition_ledger.json").read_text(encoding="utf-8"))
    symbols = select_first_batch_symbols(config)
    all_trades_by_variant: dict[str, list[FormalTrade]] = {}
    metrics_rows: list[dict[str, Any]] = []
    per_symbol_rows: list[dict[str, Any]] = []
    deferred: list[dict[str, str]] = []

    for variant in VARIANTS:
        variant_trades: list[FormalTrade] = []
        for symbol in symbols:
            path = best_cache_file(config.local_data_roots, symbol, "1d", config.daily_start, config.daily_end)
            if not path:
                deferred.append({"variant_id": variant.variant_id, "symbol": symbol, "reason": "daily_cache_missing"})
                continue
            bars = load_bars(path)
            trades = generate_variant_trades(symbol, bars, config, variant)
            variant_trades.extend(trades)
            symbol_metrics = metric_with_loss_streak(symbol, trades, config.formal_daily_strategy.starting_capital)
            per_symbol_rows.append({"variant_id": variant.variant_id, "variant_title": variant.title, **symbol_metrics})
        all_trades_by_variant[variant.variant_id] = variant_trades
        overall = metric_with_loss_streak("ALL", variant_trades, config.formal_daily_strategy.starting_capital)
        metrics_rows.append(
            {
                "variant_id": variant.variant_id,
                "variant_title": variant.title,
                "plain_rule": variant.plain_rule,
                "entry_mode": variant.entry_mode,
                "source_fields": " / ".join(variant.source_fields),
                "source_refs": " | ".join(variant_source_refs(variant, source_ledger)),
                **overall,
            }
        )

    add_stability_fields(metrics_rows, per_symbol_rows)
    comparisons = compare_to_baseline(metrics_rows)
    best = select_best_variant(metrics_rows, comparisons)
    summary = build_summary(generated_at, config, source_ledger, metrics_rows, comparisons, best, deferred)
    equity_curves = build_equity_curves(all_trades_by_variant, config.formal_daily_strategy.starting_capital)

    write_json(output_dir / "m12_15_ftd_v02_ab_retest_summary.json", summary)
    write_json(output_dir / "m12_15_best_variant.json", best)
    write_json(output_dir / "m12_15_equity_curves.json", equity_curves)
    write_csv(output_dir / "m12_15_variant_metrics.csv", metrics_rows)
    write_csv(output_dir / "m12_15_per_symbol_metrics.csv", per_symbol_rows)
    write_csv(output_dir / "m12_15_trade_ledger.csv", build_trade_rows(all_trades_by_variant))
    (output_dir / "m12_15_ab_retest_report.md").write_text(build_report_md(summary, metrics_rows, best), encoding="utf-8")
    (output_dir / "m12_15_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")

    assert_no_forbidden_output(output_dir)
    return summary


def generate_variant_trades(
    symbol: str,
    bars: list[Any],
    config: M1212Config,
    variant: VariantSpec,
) -> list[FormalTrade]:
    trades: list[FormalTrade] = []
    for idx in range(3, len(bars) - 1):
        history = bars[idx - 3 : idx + 1]
        signal_bar = bars[idx]
        previous = bars[idx - 1]
        direction = classify_signal_direction(history, signal_bar, previous, variant)
        if not direction:
            continue
        if variant.use_pullback_guard and is_endless_pullback(bars, idx, direction):
            continue
        if variant.use_higher_timeframe_proxy and not higher_timeframe_proxy_allows(bars, idx, direction):
            continue
        entry_bar_index, entry, stop = resolve_variant_entry(bars, idx, direction, variant)
        if entry_bar_index is None or entry is None or stop is None:
            continue
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = entry + risk * Decimal("2") if direction == "long" else entry - risk * Decimal("2")
        future = bars[entry_bar_index : min(len(bars), entry_bar_index + 20)]
        if not future:
            continue
        exit_price, exit_timestamp, outcome, holding = resolve_trade_exit(future, direction, stop, target)
        risk_budget = config.formal_daily_strategy.starting_capital * config.formal_daily_strategy.risk_per_trade_percent / HUNDRED
        qty = risk_budget / risk
        profit = (exit_price - entry) * qty if direction == "long" else (entry - exit_price) * qty
        trades.append(
            FormalTrade(
                symbol=symbol,
                direction=direction,
                signal_timestamp=signal_bar.timestamp,
                entry_timestamp=bars[entry_bar_index].timestamp,
                exit_timestamp=exit_timestamp,
                entry_price=entry,
                stop_price=stop,
                target_price=target,
                exit_price=exit_price,
                outcome=outcome,
                simulated_profit=profit,
                holding_bars=holding,
            )
        )
    return trades


def classify_signal_direction(history: list[Any], signal_bar: Any, previous: Any, variant: VariantSpec) -> str:
    if variant.use_context_signal_quality:
        context = classify_strict_context(history)
        signal = strict_signal_quality(signal_bar, previous)
    else:
        context = classify_daily_context(history)
        signal = daily_signal_quality(signal_bar, previous)
    if context == "上涨趋势" and signal == "看涨信号K" and signal_bar.high > previous.high:
        return "long"
    if context == "下跌趋势" and signal == "看跌信号K" and signal_bar.low < previous.low:
        return "short"
    return ""


def classify_strict_context(bars: list[Any]) -> str:
    if len(bars) < 4:
        return "不清楚"
    closes = [bar.close for bar in bars]
    higher_closes = sum(1 for left, right in zip(closes, closes[1:]) if right > left)
    lower_closes = sum(1 for left, right in zip(closes, closes[1:]) if right < left)
    if higher_closes >= 3 and bars[-1].high >= max(bar.high for bar in bars[:-1]):
        return "上涨趋势"
    if lower_closes >= 3 and bars[-1].low <= min(bar.low for bar in bars[:-1]):
        return "下跌趋势"
    return "震荡或过渡"


def strict_signal_quality(bar: Any, previous: Any) -> str:
    true_range = bar.high - bar.low
    if true_range <= 0:
        return "无效"
    body = abs(bar.close - bar.open)
    if body / true_range < Decimal("0.50"):
        return "不够强"
    upper_tail = bar.high - bar.close
    lower_tail = bar.close - bar.low
    if bar.close > bar.open and upper_tail / true_range <= Decimal("0.25") and bar.close > previous.close:
        return "看涨信号K"
    if bar.close < bar.open and lower_tail / true_range <= Decimal("0.25") and bar.close < previous.close:
        return "看跌信号K"
    return "不够强"


def is_endless_pullback(bars: list[Any], idx: int, direction: str) -> bool:
    lookback_start = max(0, idx - 40)
    window = bars[lookback_start : idx + 1]
    if len(window) < 25:
        return False
    if direction == "long":
        extreme_offset = max(range(len(window)), key=lambda pos: window[pos].high)
        bars_since_extreme = len(window) - 1 - extreme_offset
        return bars_since_extreme >= 20 and bars[idx].high < window[extreme_offset].high
    extreme_offset = min(range(len(window)), key=lambda pos: window[pos].low)
    bars_since_extreme = len(window) - 1 - extreme_offset
    return bars_since_extreme >= 20 and bars[idx].low > window[extreme_offset].low


def higher_timeframe_proxy_allows(bars: list[Any], idx: int, direction: str) -> bool:
    if idx < 20:
        return False
    recent = bars[idx - 20 : idx + 1]
    early_avg = sum((bar.close for bar in recent[:10]), ZERO) / Decimal("10")
    late_avg = sum((bar.close for bar in recent[-10:]), ZERO) / Decimal("10")
    if direction == "long":
        return late_avg > early_avg and bars[idx].close > recent[0].close
    return late_avg < early_avg and bars[idx].close < recent[0].close


def resolve_variant_entry(
    bars: list[Any],
    idx: int,
    direction: str,
    variant: VariantSpec,
) -> tuple[int | None, Decimal | None, Decimal | None]:
    signal_bar = bars[idx]
    if not variant.use_follow_through_confirm:
        entry_bar_index = idx + 1
        if entry_bar_index >= len(bars):
            return None, None, None
        entry = bars[entry_bar_index].open
        stop = signal_bar.low if direction == "long" else signal_bar.high
        return entry_bar_index, entry, stop
    for entry_bar_index in range(idx + 1, min(len(bars), idx + 3)):
        confirm = bars[entry_bar_index]
        if direction == "long" and confirm.close > signal_bar.high and confirm.close > confirm.open:
            return entry_bar_index, confirm.close, signal_bar.low
        if direction == "short" and confirm.close < signal_bar.low and confirm.close < confirm.open:
            return entry_bar_index, confirm.close, signal_bar.high
    return None, None, None


def metric_with_loss_streak(symbol: str, trades: list[FormalTrade], starting_capital: Decimal) -> dict[str, Any]:
    row = metric_row_for_trades(symbol, trades, starting_capital)
    streak = 0
    max_streak = 0
    for trade in sorted(trades, key=lambda item: item.entry_timestamp):
        if trade.simulated_profit < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    row["max_consecutive_losses"] = max_streak
    return row


def variant_source_refs(variant: VariantSpec, source_ledger: dict[str, Any]) -> list[str]:
    refs: set[str] = set()
    by_field = {item["field"]: item for item in source_ledger["upgrade_fields"]}
    for field in variant.source_fields:
        refs.update(by_field[field]["source_refs"])
    return sorted(refs)


def add_stability_fields(metrics_rows: list[dict[str, Any]], per_symbol_rows: list[dict[str, Any]]) -> None:
    rows_by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in per_symbol_rows:
        rows_by_variant[row["variant_id"]].append(row)
    for row in metrics_rows:
        symbol_rows = rows_by_variant[row["variant_id"]]
        profits = [(item["symbol"], decimal(item["net_profit"])) for item in symbol_rows]
        positive = [(symbol, profit) for symbol, profit in profits if profit > 0]
        negative = [(symbol, profit) for symbol, profit in profits if profit < 0]
        total_positive = sum((profit for _, profit in positive), ZERO)
        top3_positive = sum((profit for _, profit in sorted(positive, key=lambda item: item[1], reverse=True)[:3]), ZERO)
        top3_share = top3_positive / total_positive * HUNDRED if total_positive > 0 else ZERO
        row["profitable_symbol_count"] = len(positive)
        row["losing_symbol_count"] = len(negative)
        row["top3_profit_share_percent"] = pct(top3_share)
        row["per_symbol_stability"] = "分散较好" if len(positive) >= 30 and top3_share < Decimal("35") else "收益集中，需观察"
        row["overfit_concentration"] = "high" if top3_share >= Decimal("50") else "medium" if top3_share >= Decimal("35") else "low"


def compare_to_baseline(metrics_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = next(row for row in metrics_rows if row["variant_id"] == "baseline")
    base_profit = decimal(baseline["net_profit"])
    base_dd = decimal(baseline["max_drawdown_percent"])
    base_trades = Decimal(str(baseline["trade_count"]))
    base_streak = Decimal(str(baseline["max_consecutive_losses"]))
    rows: list[dict[str, Any]] = []
    for row in metrics_rows:
        profit = decimal(row["net_profit"])
        dd = decimal(row["max_drawdown_percent"])
        trades = Decimal(str(row["trade_count"]))
        streak = Decimal(str(row["max_consecutive_losses"]))
        rows.append(
            {
                "variant_id": row["variant_id"],
                "net_profit_delta_vs_baseline": money(profit - base_profit),
                "return_delta_percent_vs_baseline": pct(decimal(row["return_percent"]) - decimal(baseline["return_percent"])),
                "drawdown_delta_percent_vs_baseline": pct(dd - base_dd),
                "drawdown_reduction_percent": pct(base_dd - dd),
                "trade_count_delta_vs_baseline": int(trades - base_trades),
                "trade_count_retention_percent": pct(trades / base_trades * HUNDRED if base_trades else ZERO),
                "profit_retention_percent": pct(profit / base_profit * HUNDRED if base_profit else ZERO),
                "max_consecutive_losses_delta_vs_baseline": int(streak - base_streak),
                "per_symbol_stability": row["per_symbol_stability"],
                "overfit_concentration": row["overfit_concentration"],
            }
        )
    return rows


def select_best_variant(metrics_rows: list[dict[str, Any]], comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    comparison_by_id = {row["variant_id"]: row for row in comparisons}
    baseline = next(row for row in metrics_rows if row["variant_id"] == "baseline")
    baseline_dd = decimal(baseline["max_drawdown_percent"])
    candidates = []
    for row in metrics_rows:
        profit = decimal(row["net_profit"])
        dd = decimal(row["max_drawdown_percent"])
        pf = decimal(row["profit_factor"])
        retention = decimal(comparison_by_id[row["variant_id"]]["profit_retention_percent"])
        drawdown_reduction = decimal(comparison_by_id[row["variant_id"]]["drawdown_reduction_percent"])
        acceptable = profit > 0 and int(row["trade_count"]) >= 30
        score = drawdown_reduction * Decimal("2") + (pf * Decimal("10")) + (retention / Decimal("10"))
        if row["variant_id"] == "baseline":
            score -= Decimal("100") if baseline_dd > Decimal("25") else ZERO
        candidates.append((acceptable, score, row))
    acceptable_rows = [item for item in candidates if item[0]]
    _, _, best = max(acceptable_rows or candidates, key=lambda item: item[1])
    if best["variant_id"] == "baseline" and baseline_dd > Decimal("25"):
        decision = "继续观察，baseline 收益强但回撤仍太大"
    elif decimal(best["max_drawdown_percent"]) < baseline_dd:
        decision = "进入每日测试候选，先用该版本观察回撤是否稳定改善"
    else:
        decision = "继续观察，未证明回撤改善"
    return {
        "schema_version": "m12.15.best-variant.v1",
        "selected_variant_id": best["variant_id"],
        "selected_variant_title": best["variant_title"],
        "decision": decision,
        "selection_rule": "优先降低最大回撤和连续亏损，同时要求净利润为正、样本不少于30笔；不按最高收益直接选择。",
        "metrics": best,
        "paper_gate_evidence_now": False,
    }


def build_summary(
    generated_at: str,
    config: M1212Config,
    source_ledger: dict[str, Any],
    metrics_rows: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    best: dict[str, Any],
    deferred: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "schema_version": "m12.15.ftd-v02-ab-retest-summary.v1",
        "stage": "M12.15.ftd_v02_ab_retest",
        "generated_at": generated_at,
        "strategy_id": FORMAL_DAILY_ID,
        "plain_language_result": "早期高收益日线策略已完成5个版本A/B重测；结论按收益、回撤、胜率、交易数和连续亏损一起看。",
        "starting_capital": money(config.formal_daily_strategy.starting_capital),
        "risk_per_trade_percent": str(config.formal_daily_strategy.risk_per_trade_percent),
        "variant_count": len(metrics_rows),
        "variants": metrics_rows,
        "comparisons_vs_baseline": comparisons,
        "best_variant": best,
        "source_refs": sorted({ref for item in source_ledger["upgrade_fields"] for ref in item["source_refs"]}),
        "source_ledger_ref": project_path(SOURCE_REVISIT_DIR / "m12_14_early_strategy_multisource_definition_ledger.json"),
        "not_source_of_truth": ["M12-BENCH-001", "early screenshot", "signal_bar_entry_placeholder"],
        "deferred": deferred,
        "not_profit_curve_tuned": True,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_equity_curves(all_trades_by_variant: dict[str, list[FormalTrade]], starting_capital: Decimal) -> dict[str, Any]:
    curves = {}
    for variant_id, trades in all_trades_by_variant.items():
        equity = starting_capital
        points = [{"timestamp": "", "equity": money(equity)}]
        for trade in sorted(trades, key=lambda item: item.exit_timestamp):
            equity += trade.simulated_profit
            points.append({"timestamp": trade.exit_timestamp, "equity": money(equity)})
        curves[variant_id] = sample_points(points)
    return {
        "schema_version": "m12.15.equity-curves.v1",
        "sampling_note": "Each curve is sampled for report readability; trade ledger contains full trades.",
        "curves": curves,
    }


def sample_points(points: list[dict[str, str]], max_points: int = 120) -> list[dict[str, str]]:
    if len(points) <= max_points:
        return points
    step = max(1, len(points) // max_points)
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


def build_trade_rows(all_trades_by_variant: dict[str, list[FormalTrade]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for variant_id, trades in all_trades_by_variant.items():
        for trade in trades:
            rows.append(
                {
                    "variant_id": variant_id,
                    "strategy_id": FORMAL_DAILY_ID,
                    "symbol": trade.symbol,
                    "direction": "看涨" if trade.direction == "long" else "看跌",
                    "signal_timestamp": trade.signal_timestamp,
                    "entry_timestamp": trade.entry_timestamp,
                    "exit_timestamp": trade.exit_timestamp,
                    "hypothetical_entry_price": money(trade.entry_price),
                    "hypothetical_stop_price": money(trade.stop_price),
                    "hypothetical_target_price": money(trade.target_price),
                    "hypothetical_exit_price": money(trade.exit_price),
                    "outcome": trade.outcome,
                    "simulated_profit": money(trade.simulated_profit),
                    "holding_bars": str(trade.holding_bars),
                }
            )
    rows.sort(key=lambda row: (row["variant_id"], row["entry_timestamp"], row["symbol"]))
    return rows


def build_report_md(summary: dict[str, Any], metrics_rows: list[dict[str, Any]], best: dict[str, Any]) -> str:
    lines = [
        "# M12.15 FTD v0.2 A/B 重测报告",
        "",
        "## 用人话结论",
        "",
        f"- 本轮对 `{FORMAL_DAILY_ID}` 跑了 `{summary['variant_count']}` 个版本。",
        f"- 当前选出的版本：`{best['selected_variant_id']}`，结论：{best['decision']}。",
        "- 选择规则不是谁收益最高选谁，而是先看回撤和连续亏损有没有改善，再看收益是否还能保留。",
        "",
        "## 版本成绩",
        "",
        "| 版本 | 净利润 | 收益率 | 胜率 | 最大回撤 | 交易数 | 最大连续亏损 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metrics_rows:
        lines.append(
            f"| `{row['variant_id']}` | {row['net_profit']} | {row['return_percent']}% | {row['win_rate']}% | "
            f"{row['max_drawdown_percent']}% | {row['trade_count']} | {row['max_consecutive_losses']} |"
        )
    lines.extend(
        [
            "",
            "## 下一步",
            "",
            "- 如果最佳版本相比 baseline 明显压低回撤，就在 M12.17 接入每日只读测试。",
            "- 如果所有增强版都牺牲过多收益或没有压低回撤，则 `M12-FTD-001` 继续作为观察/选股因子，不进入模拟买卖准入。",
            "- 本阶段不接真实账户、不下真实订单、不批准模拟买卖试运行。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_handoff_md(summary: dict[str, Any]) -> str:
    best = summary["best_variant"]
    return (
        "# M12.15 Handoff\n\n"
        "## 用人话结论\n\n"
        f"`{FORMAL_DAILY_ID}` 已完成 v0.2 A/B 重测；当前选择 `{best['selected_variant_id']}`。"
        f"{best['decision']}\n\n"
        "## 下一步\n\n"
        "- M12.16 使用本结果安排 6 条来源回看候选。\n"
        "- M12.17 把最佳版本接入每日只读测试。\n"
    )


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")
