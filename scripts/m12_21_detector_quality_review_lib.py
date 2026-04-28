#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import html
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_liquid_universe_scanner_lib import Bar, load_bars  # noqa: E402


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
INPUT_DIR = M10_DIR / "visual_detectors" / "m12_20"
OUTPUT_DIR = M10_DIR / "visual_detectors" / "m12_21"
INPUT_EVENTS = INPUT_DIR / "m12_20_detector_events.jsonl"
FORBIDDEN_OUTPUT_TEXT = (
    "live-ready",
    "real_orders=true",
    "broker_connection=true",
    "paper approval",
    "order_id",
    "fill_id",
    "trade_id",
    "account_id",
    "cash_balance",
    "position_qty",
    "pnl",
    "profit_factor",
    "win_rate",
    "drawdown",
    "equity_curve",
)
MONEY = Decimal("0.01")
PERCENT = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
SAMPLE_LIMIT = 300
CHART_LIMIT = 80
QUALITY_STATUSES = ("auto_pass_high", "auto_pass_medium", "needs_spot_check", "auto_reject")


def run_m12_21_detector_quality_review(
    *,
    generated_at: str | None = None,
    input_events_path: Path = INPUT_EVENTS,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)

    events = load_jsonl(input_events_path)
    upstream_summary_path = input_events_path.parent / "m12_20_visual_detector_run_summary.json"
    upstream_summary = load_json(upstream_summary_path) if upstream_summary_path.exists() else {}
    bars_by_path: dict[str, list[Bar]] = {}
    review_rows: list[dict[str, Any]] = []
    for event in events:
        source_path = resolve_repo_path(event["source_cache_path"])
        key = project_path(source_path)
        if key not in bars_by_path:
            bars_by_path[key] = load_bars(source_path)
        review_rows.append(review_event(event, bars_by_path[key], source_path, generated_at))

    sample_rows = select_review_sample(review_rows, SAMPLE_LIMIT)
    chart_rows = sample_rows[:CHART_LIMIT]
    summary = build_summary(generated_at, events, review_rows, sample_rows, chart_rows, upstream_summary)

    write_json(output_dir / "m12_21_detector_quality_summary.json", summary)
    write_jsonl(output_dir / "m12_21_full_quality_ledger.jsonl", review_rows)
    write_csv(output_dir / "m12_21_full_quality_ledger.csv", review_rows)
    write_csv(output_dir / "m12_21_review_sample.csv", sample_rows)
    (output_dir / "m12_21_review_packet.md").write_text(build_review_packet_md(summary, sample_rows), encoding="utf-8")
    (output_dir / "m12_21_review_packet.html").write_text(build_review_packet_html(summary, chart_rows, bars_by_path), encoding="utf-8")
    (output_dir / "m12_21_next_action_plan.md").write_text(build_next_action_plan_md(summary), encoding="utf-8")
    (output_dir / "m12_21_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def review_event(event: dict[str, Any], bars: list[Bar], source_path: Path, generated_at: str) -> dict[str, Any]:
    if event["strategy_id"] == "M10-PA-004":
        return review_pa004_event(event, bars, source_path, generated_at)
    if event["strategy_id"] == "M10-PA-007":
        return review_pa007_event(event, bars, source_path, generated_at)
    raise ValueError(f"Unsupported detector strategy: {event['strategy_id']}")


def review_pa004_event(event: dict[str, Any], bars: list[Bar], source_path: Path, generated_at: str) -> dict[str, Any]:
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    checks: dict[str, bool] = {}
    reasons: list[str] = []
    score = Decimal("0")
    try:
        current_idx = by_ts[event["bar_timestamp"]]
        previous = bars[current_idx - 1]
        current = bars[current_idx]
        range_start = by_ts[event["range_start_timestamp"]]
        range_end = by_ts[event["range_end_timestamp"]]
        window = bars[range_start : range_end + 1]
    except (KeyError, IndexError):
        return failed_review(event, generated_at, "数据窗口或触发K线找不到")

    range_high = max(bar.high for bar in window)
    range_low = min(bar.low for bar in window)
    height = range_high - range_low
    midpoint = (range_high + range_low) / Decimal("2")
    height_percent = height / midpoint * HUNDRED if midpoint > ZERO else ZERO
    band = height * Decimal("0.12")
    upper_touches = sum(1 for bar in window if bar.high >= range_high - band)
    lower_touches = sum(1 for bar in window if bar.low <= range_low + band)
    above_mid = sum(1 for bar in window if bar.close >= midpoint)
    below_mid = sum(1 for bar in window if bar.close <= midpoint)
    direction = event["direction"]
    if direction == "看涨":
        boundary_ok = previous.low <= range_low + band
        reversal_ok = current.close > current.open and current.close > previous.high
        invalidation_ok = current.close >= range_low
        boundary_side = "lower_boundary"
    else:
        boundary_ok = previous.high >= range_high - band
        reversal_ok = current.close < current.open and current.close < previous.low
        invalidation_ok = current.close <= range_high
        boundary_side = "upper_boundary"

    checks["数据校验和一致"] = file_sha256(source_path) == event["source_checksum"]
    checks["窗口高低点一致"] = close_money(range_high, event.get("range_high", "")) and close_money(range_low, event.get("range_low", ""))
    checks["通道足够宽"] = height_percent >= Decimal("10")
    checks["上下边界都有触碰"] = upper_touches >= 2 and lower_touches >= 2
    checks["价格在通道两侧都有活动"] = above_mid >= 12 and below_mid >= 12
    checks["触边方向一致"] = event.get("touched_boundary") == boundary_side and boundary_ok
    checks["反转确认成立"] = reversal_ok
    checks["没有立即强突破失效"] = invalidation_ok

    required_ok = all(checks.values())
    if required_ok:
        score += Decimal("62")
        score += min(Decimal("15"), (height_percent - Decimal("10")) * Decimal("1.5"))
        score += min(Decimal("13"), Decimal(upper_touches + lower_touches - 4))
        if (direction == "看涨" and current.close > midpoint) or (direction == "看跌" and current.close < midpoint):
            score += Decimal("10")
    else:
        reasons = [name for name, ok in checks.items() if not ok]
    score = max(ZERO, min(Decimal("100"), score))
    status = quality_status(score, required_ok)
    if not reasons:
        reasons = pa004_quality_reason(score, upper_touches, lower_touches, height_percent)
    return review_row(event, generated_at, status, score, checks, reasons)


def review_pa007_event(event: dict[str, Any], bars: list[Bar], source_path: Path, generated_at: str) -> dict[str, Any]:
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    checks: dict[str, bool] = {}
    reasons: list[str] = []
    score = Decimal("0")
    try:
        current_idx = by_ts[event["bar_timestamp"]]
        previous = bars[current_idx - 1]
        current = bars[current_idx]
        leg1_idx = by_ts[event["leg1_timestamp"]]
        leg2_idx = by_ts[event["leg2_timestamp"]]
    except (KeyError, IndexError):
        return failed_review(event, generated_at, "腿部或触发K线找不到")

    direction = event["direction"]
    spacing = leg2_idx - leg1_idx
    signal_delay = current_idx - leg2_idx
    if direction == "看涨":
        leg1_price = bars[leg1_idx].low
        leg2_price = bars[leg2_idx].low
        trap_level = min(leg1_price, leg2_price)
        leg_relation_ok = leg2_price <= leg1_price * Decimal("1.01")
        reversal_ok = current.close > current.open and current.close > previous.high
    else:
        leg1_price = bars[leg1_idx].high
        leg2_price = bars[leg2_idx].high
        trap_level = max(leg1_price, leg2_price)
        leg_relation_ok = leg2_price >= leg1_price * Decimal("0.99")
        reversal_ok = current.close < current.open and current.close < previous.low

    checks["数据校验和一致"] = file_sha256(source_path) == event["source_checksum"]
    checks["第一腿价格一致"] = close_money(leg1_price, event.get("leg1_price", ""))
    checks["第二腿价格一致"] = close_money(leg2_price, event.get("leg2_price", ""))
    checks["腿部间距有效"] = spacing >= 3
    checks["第二腿没有偏离过大"] = leg_relation_ok
    checks["陷阱价位一致"] = close_money(trap_level, event.get("trap_break_level", ""))
    checks["反向失败确认成立"] = reversal_ok

    required_ok = all(checks.values())
    if required_ok:
        score += Decimal("62")
        if 4 <= spacing <= 14:
            score += Decimal("13")
        elif spacing <= 22:
            score += Decimal("7")
        if signal_delay <= 5:
            score += Decimal("13")
        elif signal_delay <= 8:
            score += Decimal("7")
        body = abs(current.close - current.open)
        true_range = max(Decimal("0.01"), current.high - current.low)
        score += min(Decimal("12"), (body / true_range) * Decimal("12"))
    else:
        reasons = [name for name, ok in checks.items() if not ok]
    score = max(ZERO, min(Decimal("100"), score))
    status = quality_status(score, required_ok)
    if not reasons:
        reasons = pa007_quality_reason(score, spacing, signal_delay)
    return review_row(event, generated_at, status, score, checks, reasons)


def failed_review(event: dict[str, Any], generated_at: str, reason: str) -> dict[str, Any]:
    return review_row(
        event,
        generated_at,
        "auto_reject",
        ZERO,
        {"基础数据可复核": False},
        [reason],
    )


def review_row(
    event: dict[str, Any],
    generated_at: str,
    status: str,
    score: Decimal,
    checks: dict[str, bool],
    reasons: list[str],
) -> dict[str, Any]:
    failed_checks = [name for name, ok in checks.items() if not ok]
    return {
        "schema_version": "m12.21.detector-quality-review.v1",
        "stage": "M12.21.detector_quality_review",
        "generated_at": generated_at,
        "event_id": event["event_id"],
        "strategy_id": event["strategy_id"],
        "strategy_title": event["strategy_title"],
        "symbol": event["symbol"],
        "timeframe": event["timeframe"],
        "bar_timestamp": event["bar_timestamp"],
        "direction": event["direction"],
        "detector_event_type": event["detector_event_type"],
        "quality_status": status,
        "quality_score": pct(score),
        "manual_review_priority": manual_priority(status, score),
        "failed_check_count": len(failed_checks),
        "failed_checks": failed_checks,
        "passed_check_count": sum(1 for ok in checks.values() if ok),
        "check_count": len(checks),
        "review_reason": "；".join(reasons),
        "source_cache_path": event["source_cache_path"],
        "source_checksum": event["source_checksum"],
        "source_lineage": event["source_lineage"],
        "source_refs": event["source_refs"],
        "evidence_refs": event["evidence_refs"],
        "not_trade_signal": "true",
        "paper_simulated_only": "true",
        "broker_connection": "false",
        "real_orders": "false",
        "live_execution": "false",
    }


def quality_status(score: Decimal, required_ok: bool) -> str:
    if not required_ok:
        return "auto_reject"
    if score >= Decimal("82"):
        return "auto_pass_high"
    if score >= Decimal("70"):
        return "auto_pass_medium"
    return "needs_spot_check"


def manual_priority(status: str, score: Decimal) -> str:
    if status == "auto_reject":
        return "high"
    if status == "needs_spot_check":
        return "high" if score < Decimal("66") else "medium"
    if status == "auto_pass_medium":
        return "medium"
    return "low"


def pa004_quality_reason(score: Decimal, upper_touches: int, lower_touches: int, height_percent: Decimal) -> list[str]:
    if score >= Decimal("82"):
        return [f"宽通道结构较完整，边界触碰 {upper_touches}/{lower_touches}，通道高度 {pct(height_percent)}%。"]
    return [f"结构成立但质量一般，边界触碰 {upper_touches}/{lower_touches}，通道高度 {pct(height_percent)}%，建议抽样看图。"]


def pa007_quality_reason(score: Decimal, spacing: int, signal_delay: int) -> list[str]:
    if score >= Decimal("82"):
        return [f"第二腿结构较完整，腿部间隔 {spacing} 根，确认K距离第二腿 {signal_delay} 根。"]
    return [f"第二腿结构成立但质量一般，腿部间隔 {spacing} 根，确认K距离第二腿 {signal_delay} 根，建议抽样看图。"]


def select_review_sample(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["strategy_id"], row["quality_status"], row["direction"])].append(row)
    selected: list[dict[str, Any]] = []
    for key in sorted(grouped):
        bucket = sorted(grouped[key], key=lambda row: row["event_id"])
        selected.extend(bucket[: max(4, min(20, limit // max(1, len(grouped))))])
    if len(selected) < limit:
        selected_ids = {row["event_id"] for row in selected}
        for row in sorted(rows, key=lambda item: (item["manual_review_priority"], item["event_id"])):
            if row["event_id"] not in selected_ids:
                selected.append(row)
                selected_ids.add(row["event_id"])
            if len(selected) >= limit:
                break
    return selected[:limit]


def build_summary(
    generated_at: str,
    source_events: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]],
    chart_rows: list[dict[str, Any]],
    upstream_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    upstream_summary = upstream_summary or {}
    by_strategy = Counter(row["strategy_id"] for row in review_rows)
    by_status = Counter(row["quality_status"] for row in review_rows)
    by_strategy_status: dict[str, dict[str, int]] = defaultdict(dict)
    for strategy_id in sorted(by_strategy):
        subset = [row for row in review_rows if row["strategy_id"] == strategy_id]
        counts = Counter(row["quality_status"] for row in subset)
        by_strategy_status[strategy_id] = {status: counts.get(status, 0) for status in QUALITY_STATUSES}
    reject_count = by_status.get("auto_reject", 0)
    spot_count = by_status.get("needs_spot_check", 0)
    machine_pass_count = len(review_rows) - reject_count
    raw_counts = {
        strategy_id: int(count)
        for strategy_id, count in (upstream_summary.get("raw_detector_event_count_before_cap") or {}).items()
    }
    retained_counts = dict(sorted(by_strategy.items()))
    retention_rates = {
        strategy_id: pct(Decimal(retained_counts.get(strategy_id, 0)) / Decimal(max(1, raw_count)) * HUNDRED)
        for strategy_id, raw_count in sorted(raw_counts.items())
    }
    return {
        "schema_version": "m12.21.detector-quality-summary.v1",
        "stage": "M12.21.detector_quality_review",
        "generated_at": generated_at,
        "plain_language_result": "已对 M12.20 的全部机器识别候选做全量复核；这回答的是图形结构是否自洽，不是盈利能力。",
        "source_event_scope": "retained_candidates_after_m12_20_cap",
        "source_event_count": len(source_events),
        "reviewed_event_count": len(review_rows),
        "upstream_event_cap_per_strategy_symbol": upstream_summary.get("event_cap_per_strategy_symbol"),
        "raw_detector_event_count_before_cap": raw_counts,
        "retained_detector_event_count_by_strategy": retained_counts,
        "retention_rate_after_cap_percent_by_strategy": retention_rates,
        "cap_scope_warning": "M12.20 每个 strategy/symbol 最多保留最近 50 条事件；M12.21 是 retained candidates 全量复核，不代表 raw detector 全历史分布。",
        "machine_pass_count": machine_pass_count,
        "machine_pass_percent": pct(Decimal(machine_pass_count) / Decimal(max(1, len(review_rows))) * HUNDRED),
        "needs_spot_check_count": spot_count,
        "auto_reject_count": reject_count,
        "quality_status_counts": {status: by_status.get(status, 0) for status in QUALITY_STATUSES},
        "quality_status_by_strategy": by_strategy_status,
        "sample_count": len(sample_rows),
        "chart_count": len(chart_rows),
        "top_symbols_by_review_count": [
            {"symbol": symbol, "event_count": count} for symbol, count in Counter(row["symbol"] for row in review_rows).most_common(10)
        ],
        "can_enter_backtest_now": False,
        "why_not_backtest_yet": "全量结构复核通过不等于视觉准确率；下一步要先抽样看图，确认机器没有把普通震荡误判成策略图形。",
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_review_packet_md(summary: dict[str, Any], sample_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# M12.21 检测器复核包",
        "",
        "## 用人话结论",
        "",
        f"- 已全量复核 `{summary['reviewed_event_count']}` 条机器识别候选。",
        "- 注意：这是 M12.20 保留下来的候选全量，不是原始检测器全历史分布。",
        f"- 机器规则结构通过 `{summary['machine_pass_count']}` 条，通过率 `{summary['machine_pass_percent']}%`。",
        f"- 需要抽样看图 `{summary['needs_spot_check_count']}` 条，自动拒绝 `{summary['auto_reject_count']}` 条。",
        "- 这还不是交易回测，也不是盈利结论；它只说明检测器找出来的候选是否符合自己定义的图形结构。",
        "",
        "## 原始识别 vs 本次复核范围",
        "",
        "| 策略 | 原始识别数量 | 本次复核数量 | 保留比例 |",
        "|---|---:|---:|---:|",
    ]
    for strategy_id, raw_count in summary["raw_detector_event_count_before_cap"].items():
        lines.append(
            f"| `{strategy_id}` | {raw_count} | {summary['retained_detector_event_count_by_strategy'].get(strategy_id, 0)} | "
            f"{summary['retention_rate_after_cap_percent_by_strategy'].get(strategy_id, '0.00')}% |"
        )
    lines.extend([
        "",
        "## 分策略结果",
        "",
        "| 策略 | 高质量通过 | 中等通过 | 需要看图 | 自动拒绝 |",
        "|---|---:|---:|---:|---:|",
    ])
    for strategy_id, counts in summary["quality_status_by_strategy"].items():
        lines.append(
            f"| `{strategy_id}` | {counts.get('auto_pass_high', 0)} | {counts.get('auto_pass_medium', 0)} | "
            f"{counts.get('needs_spot_check', 0)} | {counts.get('auto_reject', 0)} |"
        )
    lines.extend(["", "## 抽样清单前 40 条", "", "| 策略 | 标的 | 日期 | 方向 | 状态 | 分数 | 为什么 |", "|---|---|---|---|---|---:|---|"])
    for row in sample_rows[:40]:
        lines.append(
            f"| `{row['strategy_id']}` | `{row['symbol']}` | {row['bar_timestamp'][:10]} | {row['direction']} | "
            f"{row['quality_status']} | {row['quality_score']} | {row['review_reason']} |"
        )
    return "\n".join(lines) + "\n"


def build_review_packet_html(summary: dict[str, Any], rows: list[dict[str, Any]], bars_by_path: dict[str, list[Bar]]) -> str:
    cards = []
    for row in rows:
        bars = bars_by_path.get(row["source_cache_path"]) or bars_by_path.get(project_path(resolve_repo_path(row["source_cache_path"]))) or []
        cards.append(build_chart_card(row, bars))
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<title>M12.21 检测器复核包</title>"
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;color:#1f2933;background:#f7f8fa}"
        ".hero{background:white;border:1px solid #d8dde6;padding:16px;margin-bottom:16px}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px}"
        ".card{background:white;border:1px solid #d8dde6;padding:12px}.meta{font-size:13px;color:#52606d}"
        ".badge{display:inline-block;padding:2px 6px;border-radius:4px;background:#e9eef6;margin-right:4px}"
        "svg{width:100%;height:180px;background:#fff}</style></head><body>"
        "<section class=\"hero\"><h1>M12.21 检测器复核包</h1>"
        f"<p>全量复核 {summary['reviewed_event_count']} 条；结构通过率 {summary['machine_pass_percent']}%；"
        f"需要看图 {summary['needs_spot_check_count']} 条；自动拒绝 {summary['auto_reject_count']} 条。</p>"
        f"<p>范围说明：这是 M12.20 保留候选的全量复核；原始识别数量为 "
        f"{html.escape(json.dumps(summary['raw_detector_event_count_before_cap'], ensure_ascii=False))}。</p>"
        "<p>这些都是候选图形，只能用于质量复核，不能用于买卖动作，也不是盈利结论。</p></section>"
        "<section class=\"grid\">"
        + "\n".join(cards)
        + "</section></body></html>"
    )


def build_chart_card(row: dict[str, Any], bars: list[Bar]) -> str:
    window = chart_window(row, bars)
    svg = line_svg(window, row["bar_timestamp"])
    return (
        "<article class=\"card\">"
        f"<div><span class=\"badge\">{html.escape(row['strategy_id'])}</span>"
        f"<span class=\"badge\">{html.escape(row['quality_status'])}</span>"
        f"<span class=\"badge\">分数 {html.escape(row['quality_score'])}</span></div>"
        f"<h3>{html.escape(row['symbol'])} {html.escape(row['direction'])} {html.escape(row['bar_timestamp'][:10])}</h3>"
        f"{svg}"
        f"<p class=\"meta\">{html.escape(row['review_reason'])}</p>"
        "</article>"
    )


def chart_window(row: dict[str, Any], bars: list[Bar]) -> list[Bar]:
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    idx = by_ts.get(row["bar_timestamp"])
    if idx is None:
        return []
    start = max(0, idx - 45)
    return bars[start : idx + 1]


def line_svg(bars: list[Bar], event_timestamp: str) -> str:
    if not bars:
        return "<svg viewBox=\"0 0 360 180\"><text x=\"16\" y=\"90\">无图表数据</text></svg>"
    width = 360
    height = 180
    pad = 18
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    max_price = max(highs)
    min_price = min(lows)
    span = max(Decimal("0.01"), max_price - min_price)
    step = (width - pad * 2) / max(1, len(bars) - 1)

    def x_for(i: int) -> float:
        return pad + i * step

    def y_for(price: Decimal) -> float:
        return float(pad + (max_price - price) / span * Decimal(str(height - pad * 2)))

    close_points = " ".join(f"{x_for(i):.1f},{y_for(bar.close):.1f}" for i, bar in enumerate(bars))
    event_index = next((i for i, bar in enumerate(bars) if bar.timestamp == event_timestamp), len(bars) - 1)
    event_x = x_for(event_index)
    return (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"价格走势\">"
        f"<line x1=\"{pad}\" y1=\"{y_for(max_price):.1f}\" x2=\"{width-pad}\" y2=\"{y_for(max_price):.1f}\" stroke=\"#d8dde6\"/>"
        f"<line x1=\"{pad}\" y1=\"{y_for(min_price):.1f}\" x2=\"{width-pad}\" y2=\"{y_for(min_price):.1f}\" stroke=\"#d8dde6\"/>"
        f"<polyline points=\"{close_points}\" fill=\"none\" stroke=\"#1f77b4\" stroke-width=\"2\"/>"
        f"<line x1=\"{event_x:.1f}\" y1=\"{pad}\" x2=\"{event_x:.1f}\" y2=\"{height-pad}\" stroke=\"#d64545\" stroke-width=\"2\"/>"
        f"<circle cx=\"{event_x:.1f}\" cy=\"{y_for(bars[event_index].close):.1f}\" r=\"4\" fill=\"#d64545\"/>"
        "</svg>"
    )


def build_next_action_plan_md(summary: dict[str, Any]) -> str:
    return (
        "# M12.21 后续动作\n\n"
        "## 用人话结论\n\n"
        "检测器已经完成全量结构复核。下一步不是立刻回测盈利，而是先看抽样图形是否像真正的 PA 图形。\n\n"
        "注意：本轮全量指 M12.20 已保留候选全量；原始检测器全历史分布还需要单独做 raw/capped 审计。\n\n"
        "## 执行顺序\n\n"
        "1. 先查看 `m12_21_review_packet.html` 中的样例图，优先看 `needs_spot_check`。\n"
        "2. 如果样例中大多数确实像宽通道边界反转或第二腿陷阱，再把高质量通过样本进入小范围历史回测。\n"
        "3. 如果样例误判多，就收紧检测器，不进入盈利回测。\n\n"
        "## 当前不能做的事\n\n"
        "- 不能把这些候选直接用于买卖动作。\n"
        "- 不能把结构通过率当成策略表现。\n"
        "- 不能把本阶段结果放进模拟买卖准入。\n"
        f"\n本轮全量复核 `{summary['reviewed_event_count']}` 条，抽样包 `{summary['sample_count']}` 条，图表包 `{summary['chart_count']}` 条。\n"
    )


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "```yaml\n"
        "task_id: M12.21-detector-quality-review\n"
        "role: main-agent\n"
        "branch_or_worktree: feature/m12-21-detector-quality-review\n"
        "objective: 全量复核 M12.20 机器识别候选，并生成抽样图形复核包\n"
        "status: success\n"
        "files_changed:\n"
        "  - scripts/m12_21_detector_quality_review_lib.py\n"
        "  - scripts/run_m12_21_detector_quality_review.py\n"
        "  - tests/unit/test_m12_21_detector_quality_review.py\n"
        "  - reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_21/*\n"
        "interfaces_changed: []\n"
        "commands_run:\n"
        "  - python scripts/run_m12_21_detector_quality_review.py\n"
        "tests_run: []\n"
        "assumptions:\n"
        "  - 本阶段只复核图形候选结构，不输出策略表现或盈利。\n"
        "risks:\n"
        "  - 自动结构复核不等于人工视觉准确率；仍需抽样看图。\n"
        "qa_focus:\n"
        "  - 检查全量 ledger 覆盖 M12.20 所有事件，且无真实交易字段。\n"
        "rollback_notes:\n"
        "  - 回滚本阶段提交即可撤回 M12.21 复核产物。\n"
        "next_recommended_action: 查看抽样图形包，决定是否收紧检测器或进入小范围历史回测。\n"
        "needs_user_decision: false\n"
        "user_decision_needed: ''\n"
        "```\n"
    )


def close_money(value: Decimal, text: str) -> bool:
    try:
        return abs(value - Decimal(str(text))) <= Decimal("0.02")
    except (InvalidOperation, TypeError):
        return False


def money(value: Decimal) -> str:
    return str(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def pct(value: Decimal) -> str:
    return str(value.quantize(PERCENT, rounding=ROUND_HALF_UP))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path | None) -> str:
    if path is None:
        return ""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


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
            writer.writerow({key: csv_value(value) for key, value in row.items()})


def csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")
