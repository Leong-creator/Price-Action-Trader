#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_capital_backtest_lib import (  # noqa: E402
    CAPITAL_MODEL_PATH,
    CandidateTrade,
    build_metric_rows,
    load_capital_model,
    simulate_account,
    write_metrics,
    write_trade_ledger,
)
from scripts.m12_23_detector_tightening_rerun_lib import project_path  # noqa: E402
from scripts.m12_liquid_universe_scanner_lib import Bar, load_bars  # noqa: E402


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_23_DIR = M10_DIR / "visual_detectors" / "m12_23"
OUTPUT_DIR = M10_DIR / "visual_detectors" / "m12_24_small_pilot"
M12_23_SUMMARY = M12_23_DIR / "m12_23_detector_tightening_summary.json"
M12_23_EVENTS = M12_23_DIR / "m12_23_tightened_detector_events.jsonl"
PILOT_STRATEGIES = ("M10-PA-004", "M10-PA-007")
INITIAL_CAPITAL = Decimal("100000")
PERCENT = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
MAX_HOLDING_BARS = 20
FORBIDDEN_OUTPUT_TEXT = (
    "live-ready",
    "real_orders=true",
    "broker_connection=true",
    "paper approval",
    "order_id",
    "fill_id",
    "account_id",
    "cash_balance",
    "position_qty",
)


def run_m12_24_pa004_pa007_small_pilot(
    *,
    generated_at: str | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)
    m12_23_summary = load_json(M12_23_SUMMARY)
    if not m12_23_summary.get("can_enter_small_pilot_next"):
        raise RuntimeError("M12.23 gate is not open; do not run M12.24 small pilot.")

    model = load_capital_model(CAPITAL_MODEL_PATH)
    events = load_jsonl(M12_23_EVENTS)
    bars_by_path: dict[str, list[Bar]] = {}
    candidates: list[CandidateTrade] = []
    skipped_events: list[dict[str, str]] = []
    failure_examples: list[dict[str, str]] = []
    for event in events:
        if event["strategy_id"] not in PILOT_STRATEGIES:
            continue
        source_path = resolve_repo_path(event["source_cache_path"])
        key = project_path(source_path)
        if key not in bars_by_path:
            bars_by_path[key] = load_bars(source_path)
        candidate, skip = build_candidate(event, bars_by_path[key])
        if skip:
            skipped_events.append(skip)
            continue
        candidates.append(candidate)

    grouped: dict[tuple[str, str], list[CandidateTrade]] = defaultdict(list)
    for candidate in candidates:
        grouped[(candidate.strategy_id, candidate.symbol)].append(candidate)

    all_trades = []
    for (strategy_id, symbol), group in sorted(grouped.items()):
        for tier in model.cost_tiers:
            all_trades.extend(
                simulate_account(
                    candidates=group,
                    model=model,
                    tier=tier,
                    spec_ref="reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_23/m12_23_detector_tightening_summary.json",
                    source_ledger_ref="reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_23/m12_23_tightened_detector_events.jsonl",
                    quality_flag="m12_23_tightened_detector_small_pilot",
                )
            )

    metrics = build_metric_rows(all_trades, model)
    baseline_trades = [trade for trade in all_trades if trade.cost_tier == "baseline"]
    baseline_metrics = [row for row in metrics if row["cost_tier"] == "baseline"]
    decision_rows = build_decision_rows(baseline_metrics)
    failure_examples = build_failure_examples(baseline_trades)
    write_metrics(output_dir / "m12_24_pa004_pa007_metrics.csv", metrics)
    write_trade_ledger(output_dir / "m12_24_pa004_pa007_trade_ledger.csv", baseline_trades)
    write_csv(output_dir / "m12_24_pa004_pa007_skipped_events.csv", skipped_events)
    write_csv(output_dir / "m12_24_pa004_pa007_failure_examples.csv", failure_examples)
    write_csv(output_dir / "m12_24_pa004_pa007_decision_matrix.csv", decision_rows)
    summary = build_summary(
        generated_at=generated_at,
        m12_23_summary=m12_23_summary,
        candidates=candidates,
        skipped_events=skipped_events,
        metrics=metrics,
        baseline_trades=baseline_trades,
        decision_rows=decision_rows,
    )
    write_json(output_dir / "m12_24_pa004_pa007_small_pilot_summary.json", summary)
    (output_dir / "m12_24_pa004_pa007_client_report.md").write_text(build_client_report(summary, decision_rows), encoding="utf-8")
    (output_dir / "m12_24_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def build_candidate(event: dict[str, Any], bars: list[Bar]) -> tuple[CandidateTrade | None, dict[str, str]]:
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    try:
        signal_idx = by_ts[event["bar_timestamp"]]
    except KeyError:
        return None, skip_row(event, "signal_bar_not_found")
    entry_idx = signal_idx + 1
    if entry_idx >= len(bars):
        return None, skip_row(event, "missing_next_bar_entry")
    signal = bars[signal_idx]
    entry_bar = bars[entry_idx]
    direction = "long" if event["direction"] == "看涨" else "short"
    entry_price = entry_bar.open
    if event["strategy_id"] == "M10-PA-004":
        stop_price = d(event["range_low"]) if direction == "long" else d(event["range_high"])
    else:
        stop_price = d(event["trap_break_level"])
    risk = entry_price - stop_price if direction == "long" else stop_price - entry_price
    if risk <= ZERO:
        return None, skip_row(event, "non_positive_stop_distance")
    target = entry_price + risk * Decimal("2") if direction == "long" else entry_price - risk * Decimal("2")
    exit_idx, exit_price, exit_reason = resolve_exit(bars, entry_idx, direction, stop_price, target)
    gross_r = pnl_r(direction, entry_price, exit_price, risk)
    return (
        CandidateTrade(
            strategy_id=event["strategy_id"],
            symbol=event["symbol"],
            timeframe="1d",
            direction=direction,
            signal_timestamp=signal.timestamp,
            entry_timestamp=entry_bar.timestamp,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target,
            risk_per_share=risk,
            exit_timestamp=bars[exit_idx].timestamp,
            exit_price=exit_price,
            exit_reason=exit_reason,
            gross_r=gross_r,
            baseline_net_r=gross_r,
            setup_notes="m12_23_tightened_detector_candidate",
        ),
        {},
    )


def resolve_exit(
    bars: list[Bar],
    entry_idx: int,
    direction: str,
    stop_price: Decimal,
    target_price: Decimal,
) -> tuple[int, Decimal, str]:
    end_idx = min(len(bars) - 1, entry_idx + MAX_HOLDING_BARS)
    for idx in range(entry_idx, end_idx + 1):
        bar = bars[idx]
        if direction == "long":
            if bar.low <= stop_price:
                return idx, stop_price, "stop_hit"
            if bar.high >= target_price:
                return idx, target_price, "target_hit"
        else:
            if bar.high >= stop_price:
                return idx, stop_price, "stop_hit"
            if bar.low <= target_price:
                return idx, target_price, "target_hit"
    return end_idx, bars[end_idx].close, "max_holding_exit"


def build_decision_rows(metrics: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    strategy_rows = [row for row in metrics if row["grain"] == "strategy" and row["cost_tier"] == "baseline"]
    for row in sorted(strategy_rows, key=lambda item: item["strategy_id"]):
        trade_count = int(row["trade_count"])
        return_percent = d(row["return_percent"])
        max_drawdown = d(row["max_drawdown_percent"])
        profit_factor = d(row["profit_factor"] or "0")
        if trade_count < 30:
            decision = "继续收集样本"
            plain_reason = "交易次数不足，不能解释表现。"
        elif return_percent > ZERO and profit_factor >= Decimal("1") and max_drawdown <= Decimal("35"):
            decision = "进入每日观察"
            plain_reason = "收益为正，交易次数够，回撤在小范围测试阈值内。"
        elif return_percent > ZERO:
            decision = "继续收紧"
            plain_reason = "收益为正但回撤或盈亏质量还不稳。"
        else:
            decision = "保留图形研究"
            plain_reason = "本轮小范围测试没有看到可进入每日观察的模拟结果。"
        rows.append(
            {
                "strategy_id": row["strategy_id"],
                "decision": decision,
                "plain_reason": plain_reason,
                "trade_count": row["trade_count"],
                "return_percent": row["return_percent"],
                "win_rate": row["win_rate"],
                "profit_factor": row["profit_factor"],
                "max_drawdown_percent": row["max_drawdown_percent"],
            }
        )
    return rows


def build_failure_examples(trades: list[Any]) -> list[dict[str, str]]:
    examples = [
        trade for trade in trades
        if not trade.skip_reason and trade.pnl < ZERO
    ][:40]
    return [
        {
            "strategy_id": trade.strategy_id,
            "symbol": trade.symbol,
            "signal_timestamp": trade.signal_timestamp,
            "entry_timestamp": trade.entry_timestamp,
            "exit_timestamp": trade.exit_timestamp,
            "direction": trade.direction,
            "entry_price": str(trade.entry_price),
            "stop_price": str(trade.stop_price),
            "target_price": str(trade.target_price),
            "exit_price": str(trade.exit_price),
            "pnl": str(trade.pnl),
            "exit_reason": trade.exit_reason,
            "plain_reason": "这是亏损或未达目标样例，用于下一轮检查是否需要继续收紧。",
        }
        for trade in examples
    ]


def build_summary(
    *,
    generated_at: str,
    m12_23_summary: dict[str, Any],
    candidates: list[CandidateTrade],
    skipped_events: list[dict[str, str]],
    metrics: list[dict[str, str]],
    baseline_trades: list[Any],
    decision_rows: list[dict[str, str]],
) -> dict[str, Any]:
    baseline_strategy_rows = [
        row for row in metrics
        if row["grain"] == "strategy" and row["cost_tier"] == "baseline"
    ]
    return {
        "schema_version": "m12.24.pa004-pa007-small-pilot-summary.v1",
        "stage": "M12.24.pa004_pa007_small_pilot",
        "generated_at": generated_at,
        "plain_language_result": "已对 PA004/PA007 做日线小范围历史模拟，结果只用于决定是否进入每日观察，不是模拟买卖准入。",
        "source_gate": "m12_23_passed_tightening_gate",
        "m12_23_strict_retained_event_count": m12_23_summary["strict_retained_event_count"],
        "candidate_trade_count": len(candidates),
        "skipped_event_count": len(skipped_events),
        "baseline_executed_trade_count": len([trade for trade in baseline_trades if not trade.skip_reason]),
        "strategy_ids": list(PILOT_STRATEGIES),
        "timeframe": "1d",
        "capital_model": {
            "initial_capital": "100000.00",
            "risk_per_trade_percent": "0.50",
            "leverage": "none",
            "cost_tiers": ["baseline", "stress_low", "stress_high"],
        },
        "baseline_strategy_metrics": baseline_strategy_rows,
        "decision_rows": decision_rows,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_client_report(summary: dict[str, Any], decision_rows: list[dict[str, str]]) -> str:
    lines = [
        "# M12.24 PA004/PA007 小范围历史测试报告",
        "",
        "## 先说结果",
        "",
        f"- 本轮只测 `M10-PA-004 / M10-PA-007`，周期只用 `1d`。",
        f"- 收紧后候选转成可测试交易 `{summary['candidate_trade_count']}` 条，跳过 `{summary['skipped_event_count']}` 条。",
        "- 这一步开始看本金、收益、胜率和回撤，但仍然不是模拟买卖试运行。",
        "",
        "| 策略 | 结论 | 收益率 | 胜率 | 最大回撤 | 交易次数 | 原因 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in decision_rows:
        lines.append(
            f"| `{row['strategy_id']}` | {row['decision']} | {row['return_percent']}% | "
            f"{pct(d(row['win_rate']) * HUNDRED)}% | {row['max_drawdown_percent']}% | {row['trade_count']} | {row['plain_reason']} |"
        )
    lines.extend(
        [
            "",
            "## 使用口径",
            "",
            "- 初始本金：`100,000 USD`。",
            "- 单笔风险：当前权益 `0.5%`。",
            "- 不使用杠杆。",
            "- 成本压力：`1 / 2 / 5 bps`。",
            "- 入场：候选信号后的下一根日线开盘价。",
            "- 出场：先看止损，再看 2R 目标；最多持有 20 根日线。",
            "",
            "## 后续处理",
            "",
            "- 进入每日观察的策略只进入观察队列，不直接进入模拟买卖试运行。",
            "- 如果策略收益为正但回撤大，下一步继续收紧规则。",
            "- 如果策略表现弱，保留为图形研究，不拖每日主线。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "```yaml\n"
        "task_id: M12.24-pa004-pa007-small-pilot\n"
        "role: main-agent\n"
        "branch_or_worktree: feature/m12-24-pa004-pa007-small-pilot\n"
        "objective: 对通过 M12.23 的 PA004/PA007 做 1d 小范围历史模拟\n"
        "status: success\n"
        "files_changed:\n"
        "  - scripts/m12_24_pa004_pa007_small_pilot_lib.py\n"
        "  - scripts/run_m12_24_pa004_pa007_small_pilot.py\n"
        "  - tests/unit/test_m12_24_pa004_pa007_small_pilot.py\n"
        "  - reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_24_small_pilot/*\n"
        "interfaces_changed: []\n"
        "verification_results:\n"
        f"  - candidate_trade_count: {summary['candidate_trade_count']}\n"
        f"  - baseline_executed_trade_count: {summary['baseline_executed_trade_count']}\n"
        "assumptions:\n"
        "  - 只使用 1d 本地只读缓存，不解释为日内完整测试\n"
        "risks:\n"
        "  - 视觉策略仍是 OHLCV 近似，进入每日观察前需要继续看失败样例\n"
        "qa_focus:\n"
        "  - 检查资金指标、交易明细、禁出字段和不批准模拟买卖边界\n"
        "rollback_notes:\n"
        "  - 回滚本阶段提交即可撤回小范围历史测试产物\n"
        "next_recommended_action: 把通过的小范围策略加入每日观察候选，不直接进入模拟买卖试运行\n"
        "needs_user_decision: false\n"
        "user_decision_needed: ''\n"
        "```\n"
    )


def skip_row(event: dict[str, Any], reason: str) -> dict[str, str]:
    return {
        "event_id": event.get("event_id", ""),
        "strategy_id": event.get("strategy_id", ""),
        "symbol": event.get("symbol", ""),
        "bar_timestamp": event.get("bar_timestamp", ""),
        "skip_reason": reason,
    }


def pnl_r(direction: str, entry: Decimal, exit_price: Decimal, risk: Decimal) -> Decimal:
    pnl = exit_price - entry if direction == "long" else entry - exit_price
    return pnl / risk if risk else ZERO


def pct(value: Decimal) -> str:
    return str(value.quantize(PERCENT, rounding=ROUND_HALF_UP))


def d(value: Any) -> Decimal:
    return Decimal(str(value))


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")
