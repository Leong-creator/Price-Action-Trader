#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_liquid_universe_scanner_lib import Bar, load_bars  # noqa: E402


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_20_DIR = M10_DIR / "visual_detectors" / "m12_20"
M12_21_DIR = M10_DIR / "visual_detectors" / "m12_21"
OUTPUT_DIR = M10_DIR / "visual_detectors" / "m12_22"
SAMPLE_CSV = M12_21_DIR / "m12_21_review_sample.csv"
FULL_REVIEW_LEDGER = M12_21_DIR / "m12_21_full_quality_ledger.jsonl"
SOURCE_EVENTS = M12_20_DIR / "m12_20_detector_events.jsonl"
QUALITY_SUMMARY = M12_21_DIR / "m12_21_detector_quality_summary.json"
VISUAL_DECISIONS = ("looks_valid", "borderline_needs_chart_review", "likely_false_positive")
CHART_CONTROL_PER_BUCKET = 12
FORBIDDEN_TEXT = (
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
    "profit_factor",
)
PERCENT = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")


def run_m12_22_detector_sample_visual_review(
    *,
    generated_at: str | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_events = {event["event_id"]: event for event in load_jsonl(SOURCE_EVENTS)}
    sample_rows = load_csv(SAMPLE_CSV)
    full_review_rows = load_jsonl(FULL_REVIEW_LEDGER)
    m12_21_summary = load_json(QUALITY_SUMMARY)
    bars_by_path: dict[str, list[Bar]] = {}

    review_rows: list[dict[str, Any]] = []
    for row in full_review_rows:
        event = source_events[row["event_id"]]
        source_path = resolve_repo_path(event["source_cache_path"])
        cache_key = project_path(source_path)
        if cache_key not in bars_by_path:
            bars_by_path[cache_key] = load_bars(source_path)
        review_rows.append(review_sample(row, event, bars_by_path[cache_key], generated_at))

    chart_rows = select_annotated_chart_rows(review_rows)
    summary = build_summary(generated_at, review_rows, m12_21_summary, sample_rows, chart_rows)
    write_json(output_dir / "m12_22_sample_visual_review_summary.json", summary)
    write_csv(output_dir / "m12_22_sample_visual_review_ledger.csv", review_rows)
    (output_dir / "m12_22_sample_visual_review_report.md").write_text(build_report_md(summary, review_rows), encoding="utf-8")
    (output_dir / "m12_22_annotated_review_packet.html").write_text(
        build_annotated_packet_html(summary, chart_rows, source_events, bars_by_path),
        encoding="utf-8",
    )
    (output_dir / "m12_22_next_test_plan.md").write_text(build_next_plan_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def review_sample(sample: dict[str, str], event: dict[str, Any], bars: list[Bar], generated_at: str) -> dict[str, Any]:
    if event["strategy_id"] == "M10-PA-004":
        decision, score, reasons, metrics = review_pa004(event, bars)
    elif event["strategy_id"] == "M10-PA-007":
        decision, score, reasons, metrics = review_pa007(event, bars)
    else:
        raise ValueError(f"Unsupported strategy for M12.22 visual review: {event['strategy_id']}")
    return {
        "schema_version": "m12.22.detector-sample-visual-review.v1",
        "stage": "M12.22.detector_sample_visual_review",
        "generated_at": generated_at,
        "event_id": event["event_id"],
        "strategy_id": event["strategy_id"],
        "strategy_title": event["strategy_title"],
        "symbol": event["symbol"],
        "timeframe": event["timeframe"],
        "bar_timestamp": event["bar_timestamp"],
        "direction": event["direction"],
        "m12_21_quality_status": sample["quality_status"],
        "m12_21_quality_score": sample["quality_score"],
        "visual_review_decision": decision,
        "visual_review_score": pct(score),
        "visual_review_reason": "；".join(reasons),
        "range_height_percent": metrics.get("range_height_percent", ""),
        "boundary_touch_balance": metrics.get("boundary_touch_balance", ""),
        "midpoint_activity_balance": metrics.get("midpoint_activity_balance", ""),
        "leg_spacing_bars": metrics.get("leg_spacing_bars", ""),
        "confirmation_delay_bars": metrics.get("confirmation_delay_bars", ""),
        "leg_price_distance_percent": metrics.get("leg_price_distance_percent", ""),
        "body_ratio": metrics.get("body_ratio", ""),
        "source_cache_path": event["source_cache_path"],
        "source_checksum": event["source_checksum"],
        "source_refs": json.dumps(event["source_refs"], ensure_ascii=False),
        "evidence_refs": json.dumps(event["evidence_refs"], ensure_ascii=False),
        "chart_packet_ref": "reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_21/m12_21_review_packet.html",
        "not_actionable": "true",
        "paper_simulated_only": "true",
        "broker_connection": "false",
        "real_orders": "false",
        "live_execution": "false",
    }


def review_pa004(event: dict[str, Any], bars: list[Bar]) -> tuple[str, Decimal, list[str], dict[str, str]]:
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    current_idx = by_ts[event["bar_timestamp"]]
    current = bars[current_idx]
    start = by_ts[event["range_start_timestamp"]]
    end = by_ts[event["range_end_timestamp"]]
    window = bars[start : end + 1]
    range_high = d(event["range_high"])
    range_low = d(event["range_low"])
    height = max(Decimal("0.01"), range_high - range_low)
    midpoint = (range_high + range_low) / Decimal("2")
    height_percent = d(event["range_height_percent"])
    upper_touches = int(event["upper_boundary_touch_count"])
    lower_touches = int(event["lower_boundary_touch_count"])
    touch_balance = Decimal(min(upper_touches, lower_touches)) / Decimal(max(upper_touches, lower_touches))
    above_mid = sum(1 for bar in window if bar.close >= midpoint)
    below_mid = sum(1 for bar in window if bar.close <= midpoint)
    midpoint_balance = Decimal(min(above_mid, below_mid)) / Decimal(max(above_mid, below_mid))
    body_ratio = candle_body_ratio(current)

    score = ZERO
    reasons: list[str] = []
    if height_percent >= Decimal("18"):
        score += Decimal("25")
    elif height_percent >= Decimal("14"):
        score += Decimal("17")
        reasons.append("通道宽度够用但不算很宽")
    else:
        score += Decimal("6")
        reasons.append("通道宽度偏窄，容易像普通震荡")

    if min(upper_touches, lower_touches) >= 4:
        score += Decimal("22")
    elif min(upper_touches, lower_touches) >= 3:
        score += Decimal("16")
    else:
        score += Decimal("6")
        reasons.append("至少一侧边界触碰偏少")

    if touch_balance >= Decimal("0.35"):
        score += Decimal("16")
    elif touch_balance >= Decimal("0.25"):
        score += Decimal("8")
        reasons.append("上下边界触碰不够均衡")
    else:
        reasons.append("边界触碰严重偏向一侧")

    if midpoint_balance >= Decimal("0.35"):
        score += Decimal("14")
    elif midpoint_balance >= Decimal("0.25"):
        score += Decimal("7")
        reasons.append("价格在通道两侧活动不够均衡")
    else:
        reasons.append("价格主要停留在通道一侧")

    if body_ratio >= Decimal("0.35"):
        score += Decimal("13")
    elif body_ratio >= Decimal("0.20"):
        score += Decimal("7")
        reasons.append("反转K线实体一般")
    else:
        reasons.append("反转K线力度偏弱")

    if height_percent <= Decimal("80"):
        score += Decimal("10")
    elif height_percent <= Decimal("120"):
        score += Decimal("5")
        reasons.append("波动过大，建议人工看图排除极端行情")
    else:
        reasons.append("波动极大，更像极端行情而非稳定宽通道")

    if not reasons:
        reasons.append("通道宽度、双边触碰、边界反转和中轴活动都比较像目标图形")
    decision = visual_decision(score)
    return decision, score, reasons, {
        "range_height_percent": pct(height_percent),
        "boundary_touch_balance": pct(touch_balance * HUNDRED),
        "midpoint_activity_balance": pct(midpoint_balance * HUNDRED),
        "body_ratio": pct(body_ratio * HUNDRED),
    }


def review_pa007(event: dict[str, Any], bars: list[Bar]) -> tuple[str, Decimal, list[str], dict[str, str]]:
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    current_idx = by_ts[event["bar_timestamp"]]
    current = bars[current_idx]
    leg1_idx = by_ts[event["leg1_timestamp"]]
    leg2_idx = by_ts[event["leg2_timestamp"]]
    spacing = leg2_idx - leg1_idx
    delay = current_idx - leg2_idx
    leg1 = d(event["leg1_price"])
    leg2 = d(event["leg2_price"])
    base = max(Decimal("0.01"), abs(leg1))
    leg_distance_pct = abs(leg2 - leg1) / base * HUNDRED
    body_ratio = candle_body_ratio(current)
    between = bars[min(leg1_idx, leg2_idx) : max(leg1_idx, leg2_idx) + 1]
    if event["direction"] == "看涨":
        swing_depth = (max(bar.high for bar in between) - min(leg1, leg2)) / max(Decimal("0.01"), max(bar.high for bar in between))
    else:
        swing_depth = (max(leg1, leg2) - min(bar.low for bar in between)) / max(Decimal("0.01"), max(leg1, leg2))

    score = ZERO
    reasons: list[str] = []
    if 4 <= spacing <= 14:
        score += Decimal("24")
    elif 3 <= spacing <= 22:
        score += Decimal("14")
        reasons.append("两腿间距可用但不理想")
    else:
        reasons.append("两腿间距不稳定")

    if delay <= 6:
        score += Decimal("24")
    elif delay <= 10:
        score += Decimal("14")
        reasons.append("反向确认略晚")
    else:
        score += Decimal("4")
        reasons.append("反向确认太晚，可能已经不是第二腿陷阱")

    if leg_distance_pct <= Decimal("2.5"):
        score += Decimal("18")
    elif leg_distance_pct <= Decimal("5"):
        score += Decimal("9")
        reasons.append("第二腿和第一腿距离偏大")
    else:
        reasons.append("第二腿偏离第一腿过大")

    if body_ratio >= Decimal("0.35"):
        score += Decimal("14")
    elif body_ratio >= Decimal("0.20"):
        score += Decimal("7")
        reasons.append("反转确认K线力度一般")
    else:
        reasons.append("反转确认K线力度偏弱")

    if swing_depth >= Decimal("0.05"):
        score += Decimal("12")
    elif swing_depth >= Decimal("0.025"):
        score += Decimal("6")
        reasons.append("两腿之间的摆动不够明显")
    else:
        reasons.append("两腿之间几乎没有清楚摆动")

    if not reasons:
        reasons.append("两腿间距、价位关系、反转确认和中间摆动都比较像目标图形")
    decision = visual_decision(score)
    return decision, score, reasons, {
        "leg_spacing_bars": str(spacing),
        "confirmation_delay_bars": str(delay),
        "leg_price_distance_percent": pct(leg_distance_pct),
        "body_ratio": pct(body_ratio * HUNDRED),
    }


def visual_decision(score: Decimal) -> str:
    if score >= Decimal("72"):
        return "looks_valid"
    if score >= Decimal("52"):
        return "borderline_needs_chart_review"
    return "likely_false_positive"


def candle_body_ratio(bar: Bar) -> Decimal:
    true_range = max(Decimal("0.01"), bar.high - bar.low)
    return abs(bar.close - bar.open) / true_range


def select_annotated_chart_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [row for row in rows if row["m12_21_quality_status"] == "needs_spot_check"]
    selected_ids = {row["event_id"] for row in selected}
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["event_id"] in selected_ids:
            continue
        grouped[(row["strategy_id"], row["m12_21_quality_status"], row["direction"])].append(row)
    for key in sorted(grouped):
        bucket = sorted(grouped[key], key=lambda item: (item["visual_review_decision"], item["event_id"]))
        for row in bucket[:CHART_CONTROL_PER_BUCKET]:
            selected.append(row)
            selected_ids.add(row["event_id"])
    return selected


def build_summary(
    generated_at: str,
    rows: list[dict[str, Any]],
    m12_21_summary: dict[str, Any],
    m12_21_sample_rows: list[dict[str, str]],
    chart_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    by_decision = Counter(row["visual_review_decision"] for row in rows)
    by_strategy_decision: dict[str, dict[str, int]] = defaultdict(dict)
    by_strategy_m12_status: dict[str, dict[str, int]] = defaultdict(dict)
    for strategy_id in sorted({row["strategy_id"] for row in rows}):
        subset = [row for row in rows if row["strategy_id"] == strategy_id]
        counts = Counter(row["visual_review_decision"] for row in subset)
        by_strategy_decision[strategy_id] = {decision: counts.get(decision, 0) for decision in VISUAL_DECISIONS}
        status_counts = Counter(row["m12_21_quality_status"] for row in subset)
        by_strategy_m12_status[strategy_id] = dict(sorted(status_counts.items()))
    needs_rows = [row for row in rows if row["m12_21_quality_status"] == "needs_spot_check"]
    needs_counts = Counter(row["visual_review_decision"] for row in needs_rows)
    ready = by_decision["likely_false_positive"] == 0 and by_decision["borderline_needs_chart_review"] <= max(3, len(rows) // 10)
    return {
        "schema_version": "m12.22.detector-sample-visual-review-summary.v1",
        "stage": "M12.22.detector_sample_visual_review",
        "generated_at": generated_at,
        "plain_language_result": "已检查 M12.21 抽样图形包，并对 retained candidates 做全量严格复核；边界样例偏多，检测器需要先收紧。",
        "review_scope": "all_m12_21_retained_candidates",
        "reviewed_event_count": len(rows),
        "m12_21_sample_count": len(m12_21_sample_rows),
        "annotated_chart_packet_count": len(chart_rows),
        "needs_spot_check_reviewed_count": len(needs_rows),
        "needs_spot_check_decision_counts": {decision: needs_counts.get(decision, 0) for decision in VISUAL_DECISIONS},
        "visual_review_decision_counts": {decision: by_decision.get(decision, 0) for decision in VISUAL_DECISIONS},
        "visual_review_decision_by_strategy": by_strategy_decision,
        "m12_21_status_count_by_strategy": by_strategy_m12_status,
        "m12_21_retained_event_count": m12_21_summary["reviewed_event_count"],
        "m12_21_raw_detector_event_count_before_cap": m12_21_summary["raw_detector_event_count_before_cap"],
        "m12_21_retention_rate_after_cap_percent_by_strategy": m12_21_summary["retention_rate_after_cap_percent_by_strategy"],
        "can_enter_full_backtest_now": False,
        "can_enter_small_pilot_after_tightening": ready,
        "next_step": "先收紧 M10-PA-004 的宽度/双边触碰/中轴活动阈值，并对 M10-PA-007 的反向确认延迟和两腿偏离做上限；之后重跑检测器和抽样图形复核。",
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_report_md(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# M12.22 抽样图形复核报告",
        "",
        "## 用人话结论",
        "",
        f"- M12.21 原抽样包有 `{summary['m12_21_sample_count']}` 条候选图形。",
        f"- 已对 M12.21 保留下来的 `{summary['reviewed_event_count']}` 条候选做全量严格复核。",
        f"- 已生成 `{summary['annotated_chart_packet_count']}` 条标注图包，覆盖全部 `{summary['needs_spot_check_reviewed_count']}` 条边界样例，并补了通过样例对照组。",
        f"- 全量严格复核里，看起来像目标图形：`{summary['visual_review_decision_counts']['looks_valid']}` 条。",
        f"- 全量严格复核里，边界样例，需要人工或规则收紧：`{summary['visual_review_decision_counts']['borderline_needs_chart_review']}` 条。",
        f"- 全量严格复核里，明显疑似误判：`{summary['visual_review_decision_counts']['likely_false_positive']}` 条。",
        f"- 仅看原本最该复核的 needs_spot_check：像目标图形 `{summary['needs_spot_check_decision_counts']['looks_valid']}` 条，边界 `{summary['needs_spot_check_decision_counts']['borderline_needs_chart_review']}` 条，疑似误判 `{summary['needs_spot_check_decision_counts']['likely_false_positive']}` 条。",
        "- 结论：现在不能直接进入完整历史回测，先收紧检测器，再做小范围试跑。",
        "",
        "## 分策略结果",
        "",
        "| 策略 | 像目标图形 | 边界样例 | 疑似误判 | 处理建议 |",
        "|---|---:|---:|---:|---|",
    ]
    for strategy_id, counts in summary["visual_review_decision_by_strategy"].items():
        if strategy_id == "M10-PA-004":
            suggestion = "先收紧宽通道：提高宽度要求，要求上下边界更均衡，过滤普通震荡。"
        else:
            suggestion = "先限制反向确认太晚和两腿距离过大的样例，减少普通摆动误判。"
        lines.append(
            f"| `{strategy_id}` | {counts['looks_valid']} | {counts['borderline_needs_chart_review']} | "
            f"{counts['likely_false_positive']} | {suggestion} |"
        )
    lines.extend([
        "",
        "## 为什么还不能直接跑完整历史回测",
        "",
        "- M12.21 复核的是 M12.20 保留下来的候选，不是原始全历史分布。",
        "- `M10-PA-007` 原始识别 `20190` 条，但只保留 `2500` 条，保留比例 `12.38%`，截断影响很大。",
        "- 抽样里如果边界样例较多，直接回测会把检测器噪音也算进去，结果不可信。",
        "",
        "## 本轮抽样中的典型问题",
        "",
    ])
    problem_rows = [row for row in rows if row["visual_review_decision"] != "looks_valid"][:20]
    if not problem_rows:
        lines.append("- 未发现明显边界或误判样例。")
    else:
        lines.extend(["| 策略 | 标的 | 日期 | 判断 | 原因 |", "|---|---|---|---|---|"])
        for row in problem_rows:
            lines.append(
                f"| `{row['strategy_id']}` | `{row['symbol']}` | {row['bar_timestamp'][:10]} | "
                f"{row['visual_review_decision']} | {row['visual_review_reason']} |"
            )
    return "\n".join(lines) + "\n"


def build_next_plan_md(summary: dict[str, Any]) -> str:
    return (
        "# M12.22 后续测试规划\n\n"
        "## 下一步顺序\n\n"
        "1. 收紧 `M10-PA-004` 宽通道检测器，减少普通震荡误判。\n"
        "2. 给 `M10-PA-007` 增加反向确认延迟上限，过滤确认太晚的第二腿样例。\n"
        "3. 重跑 M12.20/M12.21/M12.22 三步：机器识别 -> 全量结构复核 -> 抽样图形复核。\n"
        "4. 如果抽样边界样例降到可接受范围，再跑小范围历史测试；小范围通过后才考虑放入每日观察。\n\n"
        "## 当前不能做的事\n\n"
        "- 不能把 `M10-PA-004/007` 放进每日测试主线。\n"
        "- 不能把结构通过率或抽样通过率当成盈利能力。\n"
        "- 不能进入模拟买卖试运行。\n\n"
        f"本轮全量严格复核：像目标图形 `{summary['visual_review_decision_counts']['looks_valid']}` 条，"
        f"边界样例 `{summary['visual_review_decision_counts']['borderline_needs_chart_review']}` 条，"
        f"疑似误判 `{summary['visual_review_decision_counts']['likely_false_positive']}` 条。\n"
    )


def build_annotated_packet_html(
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    source_events: dict[str, dict[str, Any]],
    bars_by_path: dict[str, list[Bar]],
) -> str:
    cards = []
    for row in rows:
        event = source_events[row["event_id"]]
        bars = bars_by_path.get(project_path(resolve_repo_path(event["source_cache_path"])), [])
        cards.append(build_chart_card(row, event, bars))
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<title>M12.22 标注图形复核包</title>"
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;color:#1f2933;background:#f7f8fa}"
        ".hero{background:white;border:1px solid #d8dde6;padding:16px;margin-bottom:16px}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:12px}"
        ".card{background:white;border:1px solid #d8dde6;padding:12px}.meta{font-size:13px;color:#52606d}"
        ".badge{display:inline-block;padding:2px 6px;border-radius:4px;background:#e9eef6;margin-right:4px}"
        "svg{width:100%;height:220px;background:#fff}</style></head><body>"
        "<section class=\"hero\"><h1>M12.22 标注图形复核包</h1>"
        f"<p>图包 {summary['annotated_chart_packet_count']} 条，覆盖全部 {summary['needs_spot_check_reviewed_count']} 条边界样例，并加入通过样例对照组。</p>"
        "<p>图中红线是触发K线；蓝线是收盘价走势；宽通道标出上下边界；第二腿标出 leg1、leg2 和陷阱价位。</p>"
        "<p>这些仍是候选图形质量复核，不是交易或收益结论。</p></section>"
        "<section class=\"grid\">"
        + "\n".join(cards)
        + "</section></body></html>"
    )


def build_chart_card(row: dict[str, Any], event: dict[str, Any], bars: list[Bar]) -> str:
    if event["strategy_id"] == "M10-PA-004":
        svg = pa004_svg(event, bars)
    else:
        svg = pa007_svg(event, bars)
    return (
        "<article class=\"card\">"
        f"<div><span class=\"badge\">{event['strategy_id']}</span>"
        f"<span class=\"badge\">{row['m12_21_quality_status']}</span>"
        f"<span class=\"badge\">{row['visual_review_decision']}</span></div>"
        f"<h3>{event['symbol']} {event['direction']} {event['bar_timestamp'][:10]}</h3>"
        f"{svg}"
        f"<p class=\"meta\">{row['visual_review_reason']}</p>"
        "</article>"
    )


def pa004_svg(event: dict[str, Any], bars: list[Bar]) -> str:
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    start = by_ts[event["range_start_timestamp"]]
    end = by_ts[event["bar_timestamp"]]
    window = bars[max(0, start - 5) : end + 1]
    range_high = d(event["range_high"])
    range_low = d(event["range_low"])
    overlays = [
        ("range_high", range_high, "#2f855a"),
        ("range_low", range_low, "#2f855a"),
        ("midpoint", (range_high + range_low) / Decimal("2"), "#718096"),
    ]
    return line_svg(window, event["bar_timestamp"], overlays, {})


def pa007_svg(event: dict[str, Any], bars: list[Bar]) -> str:
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    leg1 = by_ts[event["leg1_timestamp"]]
    current = by_ts[event["bar_timestamp"]]
    window = bars[max(0, leg1 - 10) : current + 1]
    overlays = [("trap", d(event["trap_break_level"]), "#805ad5")]
    markers = {
        event["leg1_timestamp"]: "L1",
        event["leg2_timestamp"]: "L2",
        event["bar_timestamp"]: "确认",
    }
    return line_svg(window, event["bar_timestamp"], overlays, markers)


def line_svg(
    bars: list[Bar],
    event_timestamp: str,
    overlays: list[tuple[str, Decimal, str]],
    markers: dict[str, str],
) -> str:
    if not bars:
        return "<svg viewBox=\"0 0 420 220\"><text x=\"16\" y=\"110\">无图表数据</text></svg>"
    width = 420
    height = 220
    pad = 24
    max_price = max([bar.high for bar in bars] + [price for _, price, _ in overlays])
    min_price = min([bar.low for bar in bars] + [price for _, price, _ in overlays])
    span = max(Decimal("0.01"), max_price - min_price)
    step = (width - pad * 2) / max(1, len(bars) - 1)

    def x_for(i: int) -> float:
        return pad + i * step

    def y_for(price: Decimal) -> float:
        return float(pad + (max_price - price) / span * Decimal(str(height - pad * 2)))

    close_points = " ".join(f"{x_for(i):.1f},{y_for(bar.close):.1f}" for i, bar in enumerate(bars))
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    event_index = by_ts.get(event_timestamp, len(bars) - 1)
    parts = [
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"标注价格走势\">",
        f"<polyline points=\"{close_points}\" fill=\"none\" stroke=\"#1f77b4\" stroke-width=\"2\"/>",
    ]
    for label, price, color in overlays:
        y = y_for(price)
        parts.append(f"<line x1=\"{pad}\" y1=\"{y:.1f}\" x2=\"{width-pad}\" y2=\"{y:.1f}\" stroke=\"{color}\" stroke-width=\"1.5\"/>")
        parts.append(f"<text x=\"{pad+4}\" y=\"{max(12, y-4):.1f}\" fill=\"{color}\" font-size=\"11\">{label}</text>")
    event_x = x_for(event_index)
    parts.append(f"<line x1=\"{event_x:.1f}\" y1=\"{pad}\" x2=\"{event_x:.1f}\" y2=\"{height-pad}\" stroke=\"#d64545\" stroke-width=\"2\"/>")
    for ts, label in markers.items():
        idx = by_ts.get(ts)
        if idx is None:
            continue
        bar = bars[idx]
        x = x_for(idx)
        y = y_for(bar.close)
        parts.append(f"<circle cx=\"{x:.1f}\" cy=\"{y:.1f}\" r=\"4\" fill=\"#d64545\"/>")
        parts.append(f"<text x=\"{x+4:.1f}\" y=\"{max(12, y-6):.1f}\" fill=\"#d64545\" font-size=\"11\">{label}</text>")
    parts.append("</svg>")
    return "".join(parts)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def d(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def pct(value: Decimal) -> str:
    return str(value.quantize(PERCENT, rounding=ROUND_HALF_UP))


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
        for forbidden in FORBIDDEN_TEXT:
            if forbidden in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")
