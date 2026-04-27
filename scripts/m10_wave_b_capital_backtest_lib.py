#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_capital_backtest_lib import (  # noqa: E402
    CandidateTrade,
    CapitalTrade,
    M10_DIR,
    build_metric_rows,
    load_capital_model,
    write_equity_curves,
    write_metrics,
    write_trade_ledger,
)
from scripts.m10_historical_pilot_lib import OhlcvRow, load_dataset_for_timeframe, load_pilot_config  # noqa: E402


M10_10_QUEUE_PATH = M10_DIR / "visual_wave_b_gate" / "m10_10" / "m10_10_wave_b_entry_queue.json"
M10_11_DIR = M10_DIR / "capital_backtest" / "m10_11_wave_b"
FORBIDDEN_OUTPUT_STRINGS = ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true")
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class EventDraft:
    strategy_id: str
    symbol: str
    timeframe: str
    direction: str
    signal_index: int
    entry_index: int
    stop_price: Decimal
    setup_notes: str


def run_m10_11_wave_b_capital_backtest(output_dir: Path = M10_11_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    curve_dir = output_dir / "m10_11_wave_b_equity_curves"
    curve_dir.mkdir(parents=True, exist_ok=True)
    model = load_capital_model()
    config = load_pilot_config()
    queue = load_json(M10_10_QUEUE_PATH)
    entries = queue["entries"]

    all_trades: list[CapitalTrade] = []
    baseline_candidates: list[CandidateTrade] = []
    detection_rows: list[dict[str, Any]] = []
    curve_points: dict[tuple[str, str, str, str], list[tuple[int, str, Decimal]]] = {}
    for entry in entries:
        strategy_id = entry["strategy_id"]
        for timeframe in entry["timeframes"]:
            for symbol in config.symbols:
                bars, dataset_record = load_dataset_for_timeframe(symbol=symbol, timeframe=timeframe, config=config)
                if not bars:
                    detection_rows.append(
                        detection_row(strategy_id, timeframe, symbol, 0, "data_unavailable_deferred", dataset_record.lineage)
                    )
                    continue
                drafts = detect_wave_b_events(strategy_id, bars)
                candidates = [candidate_from_event(draft, bars) for draft in drafts]
                candidates = [candidate for candidate in candidates if candidate is not None]
                baseline_candidates.extend(candidates)
                detection_rows.append(
                    detection_row(strategy_id, timeframe, symbol, len(candidates), "events_generated", dataset_record.lineage)
                )
                for tier in model.cost_tiers:
                    simulated = simulate_account_for_wave_b(strategy_id, timeframe, symbol, candidates, tier, model)
                    all_trades.extend(simulated)
                    key = (strategy_id, timeframe, symbol, tier["tier"])
                    curve_points[key] = [(0, "start", model.initial_capital)] + [
                        (trade.sequence, trade.exit_timestamp, trade.equity_after) for trade in simulated
                    ]

    metrics = build_metric_rows(all_trades, model)
    baseline_trades = [trade for trade in all_trades if trade.cost_tier == "baseline"]
    write_trade_ledger(output_dir / "m10_11_wave_b_trade_ledger.csv", baseline_trades)
    write_metrics(output_dir / "m10_11_wave_b_metrics.csv", metrics)
    write_candidate_events(output_dir / "m10_11_wave_b_candidate_events.csv", baseline_candidates)
    write_detection_ledger(output_dir / "m10_11_wave_b_detection_ledger.json", detection_rows)
    write_equity_curves(curve_dir, curve_points)
    write_scorecard(output_dir / "m10_11_wave_b_strategy_scorecard.md", metrics)
    write_client_report(output_dir / "m10_11_wave_b_client_report.md", metrics)
    summary = build_summary(queue, metrics, baseline_trades, detection_rows, output_dir)
    write_json(output_dir / "m10_11_wave_b_capital_summary.json", summary)
    validate_outputs(output_dir)
    return summary


def detect_wave_b_events(strategy_id: str, bars: list[OhlcvRow]) -> list[EventDraft]:
    if strategy_id == "M10-PA-013":
        return detect_support_resistance_failed_test(bars, strategy_id)
    if strategy_id == "M10-PA-003":
        return detect_tight_channel_continuation(bars, strategy_id)
    if strategy_id == "M10-PA-008":
        return detect_major_trend_reversal(bars, strategy_id)
    if strategy_id == "M10-PA-009":
        return detect_wedge_reversal(bars, strategy_id)
    if strategy_id == "M10-PA-011":
        return detect_opening_reversal(bars, strategy_id)
    raise ValueError(f"Unsupported M10.11 strategy: {strategy_id}")


def detect_support_resistance_failed_test(bars: list[OhlcvRow], strategy_id: str) -> list[EventDraft]:
    events: list[EventDraft] = []
    last_emit = -999
    for i in range(25, len(bars) - 1):
        if i - last_emit < 20:
            continue
        prior = bars[i - 20 : i]
        high = max(bar.high for bar in prior)
        low = min(bar.low for bar in prior)
        bar = bars[i]
        avg_price = sum((item.close for item in prior), ZERO) / Decimal("20")
        if avg_price <= 0 or (high - low) / avg_price > Decimal("0.10"):
            continue
        if bar.high >= high and bar.close < high and bar.close < bar.open:
            events.append(EventDraft(strategy_id, bar.symbol, bar.timeframe, "short", i, i + 1, bar.high, "support_resistance_failed_upside_test"))
            last_emit = i
        elif bar.low <= low and bar.close > low and bar.close > bar.open:
            events.append(EventDraft(strategy_id, bar.symbol, bar.timeframe, "long", i, i + 1, bar.low, "support_resistance_failed_downside_test"))
            last_emit = i
    return events


def detect_tight_channel_continuation(bars: list[OhlcvRow], strategy_id: str) -> list[EventDraft]:
    events: list[EventDraft] = []
    last_emit = -999
    for i in range(30, len(bars) - 1):
        if i - last_emit < 12:
            continue
        recent = bars[i - 12 : i]
        closes = [bar.close for bar in recent]
        up_closes = sum(1 for left, right in zip(closes, closes[1:]) if right >= left)
        down_closes = sum(1 for left, right in zip(closes, closes[1:]) if right <= left)
        higher_lows = sum(1 for left, right in zip(recent, recent[1:]) if right.low >= left.low)
        lower_highs = sum(1 for left, right in zip(recent, recent[1:]) if right.high <= left.high)
        bar = bars[i]
        if up_closes >= 8 and higher_lows >= 7 and bar.close > bars[i - 1].high:
            stop = min(item.low for item in bars[i - 5 : i + 1])
            events.append(EventDraft(strategy_id, bar.symbol, bar.timeframe, "long", i, i + 1, stop, "tight_channel_continuation_long"))
            last_emit = i
        elif down_closes >= 8 and lower_highs >= 7 and bar.close < bars[i - 1].low:
            stop = max(item.high for item in bars[i - 5 : i + 1])
            events.append(EventDraft(strategy_id, bar.symbol, bar.timeframe, "short", i, i + 1, stop, "tight_channel_continuation_short"))
            last_emit = i
    return events


def detect_major_trend_reversal(bars: list[OhlcvRow], strategy_id: str) -> list[EventDraft]:
    events: list[EventDraft] = []
    last_emit = -999
    closes = [bar.close for bar in bars]
    for i in range(60, len(bars) - 1):
        if i - last_emit < 35:
            continue
        sma20 = sum(closes[i - 20 : i], ZERO) / Decimal("20")
        sma50 = sum(closes[i - 50 : i], ZERO) / Decimal("50")
        prior_down = bars[i - 10].close < sma50 and bars[i - 1].close < sma20
        prior_up = bars[i - 10].close > sma50 and bars[i - 1].close > sma20
        recent = bars[i - 12 : i + 1]
        bar = bars[i]
        if prior_down and bar.close > sma20 and bar.close > bars[i - 1].high:
            stop = min(item.low for item in recent)
            events.append(EventDraft(strategy_id, bar.symbol, bar.timeframe, "long", i, i + 1, stop, "major_trend_reversal_bottom_proxy"))
            last_emit = i
        elif prior_up and bar.close < sma20 and bar.close < bars[i - 1].low:
            stop = max(item.high for item in recent)
            events.append(EventDraft(strategy_id, bar.symbol, bar.timeframe, "short", i, i + 1, stop, "major_trend_reversal_top_proxy"))
            last_emit = i
    return events


def detect_wedge_reversal(bars: list[OhlcvRow], strategy_id: str) -> list[EventDraft]:
    events: list[EventDraft] = []
    last_emit = -999
    for i in range(35, len(bars) - 1):
        if i - last_emit < 35:
            continue
        window = bars[i - 30 : i + 1]
        low_pivots = pivot_lows(window)
        high_pivots = pivot_highs(window)
        bar = bars[i]
        if len(low_pivots) >= 3:
            lows = [window[idx].low for idx in low_pivots[-3:]]
            if lows[0] > lows[1] > lows[2] and bar.close > bars[i - 1].high:
                events.append(EventDraft(strategy_id, bar.symbol, bar.timeframe, "long", i, i + 1, min(lows), "wedge_reversal_three_push_down"))
                last_emit = i
                continue
        if len(high_pivots) >= 3:
            highs = [window[idx].high for idx in high_pivots[-3:]]
            if highs[0] < highs[1] < highs[2] and bar.close < bars[i - 1].low:
                events.append(EventDraft(strategy_id, bar.symbol, bar.timeframe, "short", i, i + 1, max(highs), "wedge_reversal_three_push_up"))
                last_emit = i
    return events


def detect_opening_reversal(bars: list[OhlcvRow], strategy_id: str) -> list[EventDraft]:
    if not bars or bars[0].timeframe not in {"5m", "15m"}:
        return []
    events: list[EventDraft] = []
    opening_bars_required = 6 if bars[0].timeframe == "5m" else 2
    sessions: dict[Any, list[tuple[int, OhlcvRow]]] = defaultdict(list)
    for idx, bar in enumerate(bars):
        sessions[bar.timestamp.date()].append((idx, bar))
    for session_bars in sessions.values():
        ordered = sorted(session_bars, key=lambda item: item[1].timestamp)
        if len(ordered) <= opening_bars_required + 2:
            continue
        opening = [bar for _, bar in ordered[:opening_bars_required]]
        open_high = max(bar.high for bar in opening)
        open_low = min(bar.low for bar in opening)
        open_mid = (open_high + open_low) / Decimal("2")
        for local_idx in range(opening_bars_required, min(len(ordered) - 1, opening_bars_required + 8)):
            global_index, bar = ordered[local_idx]
            if bar.high > open_high and bar.close < open_mid and bar.close < bar.open:
                events.append(EventDraft(strategy_id, bar.symbol, bar.timeframe, "short", global_index, global_index + 1, bar.high, "opening_reversal_failed_upside_push"))
                break
            if bar.low < open_low and bar.close > open_mid and bar.close > bar.open:
                events.append(EventDraft(strategy_id, bar.symbol, bar.timeframe, "long", global_index, global_index + 1, bar.low, "opening_reversal_failed_downside_push"))
                break
    return events


def pivot_lows(window: list[OhlcvRow]) -> list[int]:
    return [
        idx
        for idx in range(2, len(window) - 2)
        if window[idx].low <= window[idx - 1].low
        and window[idx].low <= window[idx - 2].low
        and window[idx].low <= window[idx + 1].low
        and window[idx].low <= window[idx + 2].low
    ]


def pivot_highs(window: list[OhlcvRow]) -> list[int]:
    return [
        idx
        for idx in range(2, len(window) - 2)
        if window[idx].high >= window[idx - 1].high
        and window[idx].high >= window[idx - 2].high
        and window[idx].high >= window[idx + 1].high
        and window[idx].high >= window[idx + 2].high
    ]


def candidate_from_event(event: EventDraft, bars: list[OhlcvRow]) -> CandidateTrade | None:
    if event.entry_index >= len(bars):
        return None
    entry = bars[event.entry_index]
    risk = entry.open - event.stop_price if event.direction == "long" else event.stop_price - entry.open
    if risk <= ZERO:
        return None
    target = entry.open + risk * Decimal("2") if event.direction == "long" else entry.open - risk * Decimal("2")
    exit_timestamp = bars[-1].timestamp
    exit_price = bars[-1].close
    exit_reason = "end_of_data"
    for bar in bars[event.entry_index :]:
        if event.direction == "long":
            stop_hit = bar.low <= event.stop_price
            target_hit = bar.high >= target
            if stop_hit:
                exit_timestamp = bar.timestamp
                exit_price = event.stop_price
                exit_reason = "stop_hit" if not target_hit else "stop_before_target_same_bar"
                break
            if target_hit:
                exit_timestamp = bar.timestamp
                exit_price = target
                exit_reason = "target_hit"
                break
        else:
            stop_hit = bar.high >= event.stop_price
            target_hit = bar.low <= target
            if stop_hit:
                exit_timestamp = bar.timestamp
                exit_price = event.stop_price
                exit_reason = "stop_hit" if not target_hit else "stop_before_target_same_bar"
                break
            if target_hit:
                exit_timestamp = bar.timestamp
                exit_price = target
                exit_reason = "target_hit"
                break
    gross_r = pnl_r(event.direction, entry.open, exit_price, risk)
    return CandidateTrade(
        strategy_id=event.strategy_id,
        symbol=event.symbol,
        timeframe=event.timeframe,
        direction=event.direction,
        signal_timestamp=bars[event.signal_index].timestamp.isoformat(),
        entry_timestamp=entry.timestamp.isoformat(),
        entry_price=entry.open,
        stop_price=event.stop_price,
        target_price=target,
        risk_per_share=risk,
        exit_timestamp=exit_timestamp.isoformat(),
        exit_price=exit_price,
        exit_reason=exit_reason,
        gross_r=gross_r,
        baseline_net_r=gross_r,
        setup_notes=event.setup_notes,
    )


def pnl_r(direction: str, entry: Decimal, exit_price: Decimal, risk: Decimal) -> Decimal:
    pnl = exit_price - entry if direction == "long" else entry - exit_price
    return pnl / risk


def simulate_account_for_wave_b(
    strategy_id: str,
    timeframe: str,
    symbol: str,
    candidates: list[CandidateTrade],
    tier: dict[str, Any],
    model: Any,
) -> list[CapitalTrade]:
    from scripts.m10_capital_backtest_lib import simulate_account

    return simulate_account(
        candidates=candidates,
        model=model,
        tier=tier,
        spec_ref=f"reports/strategy_lab/m10_price_action_strategy_refresh/visual_wave_b_gate/m10_10/m10_10_wave_b_entry_queue.json#{strategy_id}",
        source_ledger_ref=f"reports/strategy_lab/m10_price_action_strategy_refresh/visual_wave_b_gate/m10_10/m10_10_visual_gate_summary.json#{strategy_id}",
        quality_flag=quality_flag(strategy_id, timeframe, symbol),
    )


def quality_flag(strategy_id: str, timeframe: str, symbol: str) -> str:
    if strategy_id in {"M10-PA-003", "M10-PA-008", "M10-PA-009", "M10-PA-011"}:
        return "visual_proxy_review"
    return "wave_b_low_visual_candidate"


def write_candidate_events(path: Path, candidates: list[CandidateTrade]) -> None:
    fields = [
        "strategy_id",
        "symbol",
        "timeframe",
        "direction",
        "signal_timestamp",
        "entry_timestamp",
        "entry_price",
        "stop_price",
        "target_price",
        "risk_per_share",
        "exit_timestamp",
        "exit_price",
        "exit_reason",
        "gross_r",
        "baseline_net_r",
        "setup_notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({field: getattr(candidate, field) for field in fields})


def write_detection_ledger(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = {
        "schema_version": "m10.11.wave-b-detection-ledger.v1",
        "stage": "M10.11.wave_b_capital_backtest",
        "rows": rows,
    }
    write_json(path, payload)


def detection_row(
    strategy_id: str,
    timeframe: str,
    symbol: str,
    candidate_count: int,
    status: str,
    lineage: str,
) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "timeframe": timeframe,
        "symbol": symbol,
        "candidate_count": candidate_count,
        "status": status,
        "data_lineage": lineage,
    }


def write_scorecard(path: Path, rows: list[dict[str, str]]) -> None:
    strategy_rows = [row for row in rows if row["grain"] == "strategy" and row["cost_tier"] == "baseline"]
    lines = [
        "# M10.11 Wave B Strategy Scorecard",
        "",
        "## 摘要",
        "",
        "- 本报告只覆盖 M10.10 queue 中的 Wave B 策略。",
        "- 结果是 historical simulation，不是策略批准、paper trading 批准或实盘结论。",
        "",
        "| Strategy | Accounts | Final Equity | Net Profit | Return % | Trades | Win Rate | Profit Factor | Max Drawdown | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in sorted(strategy_rows, key=lambda item: item["strategy_id"]):
        lines.append(
            "| {strategy_id} | {account_count} | {final_equity} | {net_profit} | {return_percent} | "
            "{trade_count} | {win_rate} | {profit_factor} | {max_drawdown} | {status} |".format(**row)
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_client_report(path: Path, rows: list[dict[str, str]]) -> None:
    baseline = [row for row in rows if row["cost_tier"] == "baseline"]
    strategy_rows = [row for row in baseline if row["grain"] == "strategy"]
    tf_rows = [row for row in baseline if row["grain"] == "strategy_timeframe"]
    lines = [
        "# M10.11 Wave B Client Report",
        "",
        "## 给甲方看的结果",
        "",
        "- 覆盖策略：`M10-PA-013/003/008/009/011`。",
        "- 账户口径：每条 strategy/timeframe/symbol 独立 `100,000 USD`，单笔风险 `0.5%`。",
        "- 本报告只展示历史模拟测试成绩，不批准 paper trading 或实盘。",
        "",
        "## Strategy Summary",
        "",
        "| Strategy | Net Profit | Return % | Trades | Win Rate | Max Drawdown |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(strategy_rows, key=lambda item: item["strategy_id"]):
        lines.append(
            f"| {row['strategy_id']} | {row['net_profit']} | {row['return_percent']} | "
            f"{row['trade_count']} | {row['win_rate']} | {row['max_drawdown']} |"
        )
    lines.extend(
        [
            "",
            "## Timeframe Detail",
            "",
            "| Strategy | Timeframe | Net Profit | Return % | Trades | Win Rate | Max Drawdown |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sorted(tf_rows, key=lambda item: (item["strategy_id"], item["timeframe"])):
        lines.append(
            f"| {row['strategy_id']} | {row['timeframe']} | {row['net_profit']} | "
            f"{row['return_percent']} | {row['trade_count']} | {row['win_rate']} | {row['max_drawdown']} |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "这些结果来自 OHLCV 近似规则。视觉策略仍需要人工图形复核，不能直接解释为可交易策略。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_summary(
    queue: dict[str, Any],
    metrics: list[dict[str, str]],
    baseline_trades: list[CapitalTrade],
    detection_rows: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    strategy_rows = [row for row in metrics if row["grain"] == "strategy" and row["cost_tier"] == "baseline"]
    return {
        "schema_version": "m10.11.wave-b-capital-summary.v1",
        "generated_at": "2026-04-27T00:00:00Z",
        "stage": "M10.11.wave_b_capital_backtest",
        "wave_b_strategy_ids": queue["wave_b_strategy_ids"],
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "paper_trading_approval": False,
        "output_dir": output_dir.relative_to(ROOT).as_posix(),
        "trade_ledger_rows": len(baseline_trades),
        "metric_rows": len(metrics),
        "detection_rows": detection_rows,
        "baseline_strategy_results": strategy_rows,
        "boundary_note": "Historical simulation only; visual strategies use OHLCV proxy rules and require review.",
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_outputs(output_dir: Path) -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in [
            output_dir / "m10_11_wave_b_capital_summary.json",
            output_dir / "m10_11_wave_b_strategy_scorecard.md",
            output_dir / "m10_11_wave_b_client_report.md",
        ]
        if path.exists()
    )
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_STRINGS:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden output string found: {forbidden}")


if __name__ == "__main__":
    run_m10_11_wave_b_capital_backtest()
