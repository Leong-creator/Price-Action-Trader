#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_12_daily_observation_loop_lib import (  # noqa: E402
    best_cache_file,
    load_config,
    project_path,
    select_first_batch_symbols,
)
from scripts.m12_liquid_universe_scanner_lib import Bar, load_bars  # noqa: E402


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
OUTPUT_DIR = M10_DIR / "visual_detectors" / "m12_20"
M12_12_STATUS_PATH = M10_DIR / "daily_observation" / "m12_12_loop" / "m12_13_all_strategy_status_matrix.json"
M12_15_SUMMARY_PATH = M10_DIR / "ftd_v02_ab_retest" / "m12_15" / "m12_15_ftd_v02_ab_retest_summary.json"
M12_16_PLAN_PATH = M10_DIR / "source_candidate_test_plan" / "m12_16" / "m12_16_source_candidate_test_plan.json"
M12_18_SUMMARY_PATH = M10_DIR / "visual_observation" / "m12_18" / "m12_18_visual_observation_summary.json"
M12_19_SUMMARY_PATH = M10_DIR / "visual_detectors" / "m12_19" / "m12_19_visual_detector_summary.json"
DETECTOR_RULES_REF = M10_DIR / "visual_detectors" / "m12_19" / "m12_19_detector_rules.json"

DETECTOR_STRATEGIES = ("M10-PA-004", "M10-PA-007")
DAILY_TEST_STRATEGIES = ("M10-PA-001", "M10-PA-002", "M10-PA-012", "M12-FTD-001")
MONEY = Decimal("0.01")
PERCENT = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
EVENT_CAP_PER_STRATEGY_SYMBOL = 50
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
SOURCE_REFS_BY_STRATEGY = {
    "M10-PA-004": [
        "reports/strategy_lab/m10_price_action_strategy_refresh/source_ledgers/M10-PA-004.json",
        "reports/strategy_lab/m10_price_action_strategy_refresh/visual_golden_cases/M10-PA-004.json",
        "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_016F_channels_limit_orders_breakouts_reversals_tr_channels.md",
    ],
    "M10-PA-007": [
        "reports/strategy_lab/m10_price_action_strategy_refresh/source_ledgers/M10-PA-007.json",
        "reports/strategy_lab/m10_price_action_strategy_refresh/visual_golden_cases/M10-PA-007.json",
        "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_015D_breakouts_second_leg_traps_strong_breakouts.md",
    ],
}


def run_m12_20_visual_detector_implementation(
    *,
    generated_at: str | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_config()
    symbols = select_first_batch_symbols(config)
    all_events: list[dict[str, str]] = []
    deferred: list[dict[str, str]] = []
    input_rows: list[dict[str, str]] = []
    raw_counts: Counter[str] = Counter()

    for symbol in symbols:
        cache_path = best_cache_file(config.local_data_roots, symbol, "1d", config.daily_start, config.daily_end)
        if cache_path is None:
            deferred.append(
                {
                    "symbol": symbol,
                    "timeframe": "1d",
                    "reason": "daily_cache_missing",
                    "action": "deferred_no_fake_data",
                }
            )
            continue
        bars = load_bars(cache_path)
        source_checksum = file_sha256(cache_path)
        input_rows.append(
            {
                "symbol": symbol,
                "timeframe": "1d",
                "data_path": project_path(cache_path),
                "source_checksum": source_checksum,
                "data_lineage": "native_daily_cache",
                "bar_count": str(len(bars)),
                "first_bar": bars[0].timestamp if bars else "",
                "last_bar": bars[-1].timestamp if bars else "",
            }
        )
        symbol_events = detect_broad_channel_boundary_reversal(
            generated_at=generated_at,
            symbol=symbol,
            bars=bars,
            data_path=cache_path,
            source_checksum=source_checksum,
        )
        symbol_events.extend(
            detect_second_leg_trap_reversal(
                generated_at=generated_at,
                symbol=symbol,
                bars=bars,
                data_path=cache_path,
                source_checksum=source_checksum,
            )
        )
        raw_counts.update(row["strategy_id"] for row in symbol_events)
        all_events.extend(cap_events_per_strategy_symbol(symbol_events))

    unified_queue = build_unified_strategy_queue(
        generated_at=generated_at,
        detector_events=all_events,
    )
    summary = build_summary(
        generated_at=generated_at,
        symbols=symbols,
        input_rows=input_rows,
        deferred=deferred,
        detector_events=all_events,
        raw_counts=raw_counts,
        unified_queue=unified_queue,
    )

    write_json(output_dir / "m12_20_visual_detector_run_summary.json", summary)
    write_json(output_dir / "m12_20_input_manifest.json", {"schema_version": "m12.20.input-manifest.v1", "items": input_rows})
    write_json(output_dir / "m12_20_deferred_inputs.json", {"schema_version": "m12.20.deferred-inputs.v1", "items": deferred})
    write_json(output_dir / "m12_20_unified_strategy_queue.json", unified_queue)
    write_jsonl(output_dir / "m12_20_detector_events.jsonl", all_events)
    write_csv(output_dir / "m12_20_detector_events.csv", all_events)
    write_csv(output_dir / "m12_20_unified_strategy_queue.csv", unified_queue["items"])
    (output_dir / "m12_20_detector_quality_report.md").write_text(build_detector_report_md(summary), encoding="utf-8")
    (output_dir / "m12_20_unified_strategy_queue.md").write_text(build_unified_queue_md(unified_queue), encoding="utf-8")
    (output_dir / "m12_20_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def detect_broad_channel_boundary_reversal(
    *,
    generated_at: str,
    symbol: str,
    bars: list[Bar],
    data_path: Path,
    source_checksum: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    last_signal_index = -999
    for idx in range(42, len(bars)):
        if idx - last_signal_index < 10:
            continue
        current = bars[idx]
        previous = bars[idx - 1]
        window = bars[idx - 41 : idx - 1]
        range_high = max(bar.high for bar in window)
        range_low = min(bar.low for bar in window)
        height = range_high - range_low
        if height <= ZERO:
            continue
        midpoint = (range_high + range_low) / Decimal("2")
        height_percent = height / midpoint * HUNDRED if midpoint > ZERO else ZERO
        if height_percent < Decimal("10"):
            continue
        above_mid = sum(1 for bar in window if bar.close >= midpoint)
        below_mid = sum(1 for bar in window if bar.close <= midpoint)
        if above_mid < 12 or below_mid < 12:
            continue
        band = height * Decimal("0.12")
        upper_touches = sum(1 for bar in window if bar.high >= range_high - band)
        lower_touches = sum(1 for bar in window if bar.low <= range_low + band)
        if upper_touches < 2 or lower_touches < 2:
            continue

        direction = ""
        boundary = ""
        if previous.low <= range_low + band and current.close > current.open and current.close > previous.high:
            direction = "long"
            boundary = "lower_boundary"
        elif previous.high >= range_high - band and current.close < current.open and current.close < previous.low:
            direction = "short"
            boundary = "upper_boundary"
        else:
            continue
        if direction == "long" and current.close < range_low:
            continue
        if direction == "short" and current.close > range_high:
            continue

        confidence = Decimal("0.55")
        if upper_touches >= 3 and lower_touches >= 3:
            confidence += Decimal("0.08")
        if (direction == "long" and current.close > midpoint) or (direction == "short" and current.close < midpoint):
            confidence += Decimal("0.06")
        events.append(
            base_event(
                generated_at=generated_at,
                strategy_id="M10-PA-004",
                strategy_title="宽通道边界反转",
                detector_name="宽通道边界反转机器检测器",
                symbol=symbol,
                bar=current,
                direction=direction,
                confidence=confidence,
                data_path=data_path,
                source_checksum=source_checksum,
                reason=(
                    f"40根日线窗口形成宽通道，价格触及{cn_boundary(boundary)}后出现反向确认K线；"
                    "这是候选图形，不是交易结论。"
                ),
                extra={
                    "detector_event_type": "broad_channel_boundary_reversal_candidate",
                    "range_start_timestamp": window[0].timestamp,
                    "range_end_timestamp": window[-1].timestamp,
                    "range_high": money(range_high),
                    "range_low": money(range_low),
                    "range_height_percent": pct(height_percent),
                    "upper_boundary_touch_count": str(upper_touches),
                    "lower_boundary_touch_count": str(lower_touches),
                    "touched_boundary": boundary,
                    "confirmation_rule": "touch_boundary_then_close_beyond_previous_bar",
                    "invalidation_note": "如果后续出现强突破并连续站到通道外，本候选应失效。",
                },
            )
        )
        last_signal_index = idx
    return events


def detect_second_leg_trap_reversal(
    *,
    generated_at: str,
    symbol: str,
    bars: list[Bar],
    data_path: Path,
    source_checksum: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    last_signal_index = -999
    for idx in range(28, len(bars)):
        if idx - last_signal_index < 8:
            continue
        current = bars[idx]
        previous = bars[idx - 1]
        lookback_start = idx - 26
        window = bars[lookback_start:idx]
        lows = local_swing_lows(window, offset=lookback_start)
        highs = local_swing_highs(window, offset=lookback_start)

        bullish = second_leg_low_candidate(lows, bars, idx)
        bearish = second_leg_high_candidate(highs, bars, idx)
        if bullish and current.close > current.open and current.close > previous.high:
            leg1_idx, leg2_idx = bullish
            direction = "long"
            confidence = leg_confidence(leg1_idx, leg2_idx, idx)
            extra = leg_extra_fields(bars, leg1_idx, leg2_idx, current, direction)
            extra["context_window_start"] = window[0].timestamp
            extra["context_window_end"] = window[-1].timestamp
        elif bearish and current.close < current.open and current.close < previous.low:
            leg1_idx, leg2_idx = bearish
            direction = "short"
            confidence = leg_confidence(leg1_idx, leg2_idx, idx)
            extra = leg_extra_fields(bars, leg1_idx, leg2_idx, current, direction)
            extra["context_window_start"] = window[0].timestamp
            extra["context_window_end"] = window[-1].timestamp
        else:
            continue
        events.append(
            base_event(
                generated_at=generated_at,
                strategy_id="M10-PA-007",
                strategy_title="第二腿陷阱反转",
                detector_name="第二腿陷阱反转机器检测器",
                symbol=symbol,
                bar=current,
                direction=direction,
                confidence=confidence,
                data_path=data_path,
                source_checksum=source_checksum,
                reason=(
                    "检测到第一腿、第二腿和反向失败确认；"
                    "这是机器识别候选，后续仍要看样例稳定性。"
                ),
                extra=extra,
            )
        )
        last_signal_index = idx
    return events


def local_swing_lows(bars: list[Bar], *, offset: int) -> list[int]:
    out: list[int] = []
    for idx in range(1, len(bars) - 1):
        if bars[idx].low <= bars[idx - 1].low and bars[idx].low < bars[idx + 1].low:
            out.append(offset + idx)
    return out


def local_swing_highs(bars: list[Bar], *, offset: int) -> list[int]:
    out: list[int] = []
    for idx in range(1, len(bars) - 1):
        if bars[idx].high >= bars[idx - 1].high and bars[idx].high > bars[idx + 1].high:
            out.append(offset + idx)
    return out


def second_leg_low_candidate(swings: list[int], bars: list[Bar], idx: int) -> tuple[int, int] | None:
    recent = [swing for swing in swings if idx - 22 <= swing <= idx - 2]
    if len(recent) < 2:
        return None
    for leg1, leg2 in reversed(list(zip(recent, recent[1:]))):
        if leg2 - leg1 < 3:
            continue
        if bars[leg2].low <= bars[leg1].low * Decimal("1.01"):
            return leg1, leg2
    return None


def second_leg_high_candidate(swings: list[int], bars: list[Bar], idx: int) -> tuple[int, int] | None:
    recent = [swing for swing in swings if idx - 22 <= swing <= idx - 2]
    if len(recent) < 2:
        return None
    for leg1, leg2 in reversed(list(zip(recent, recent[1:]))):
        if leg2 - leg1 < 3:
            continue
        if bars[leg2].high >= bars[leg1].high * Decimal("0.99"):
            return leg1, leg2
    return None


def leg_confidence(leg1_idx: int, leg2_idx: int, signal_idx: int) -> Decimal:
    confidence = Decimal("0.55")
    if 4 <= leg2_idx - leg1_idx <= 14:
        confidence += Decimal("0.06")
    if signal_idx - leg2_idx <= 5:
        confidence += Decimal("0.06")
    return confidence


def leg_extra_fields(bars: list[Bar], leg1_idx: int, leg2_idx: int, current: Bar, direction: str) -> dict[str, str]:
    leg1 = bars[leg1_idx]
    leg2 = bars[leg2_idx]
    if direction == "long":
        leg1_price = leg1.low
        leg2_price = leg2.low
        trap_break_level = min(leg1.low, leg2.low)
    else:
        leg1_price = leg1.high
        leg2_price = leg2.high
        trap_break_level = max(leg1.high, leg2.high)
    return {
        "detector_event_type": "second_leg_trap_reversal_candidate",
        "leg1_timestamp": leg1.timestamp,
        "leg1_price": money(leg1_price),
        "leg2_timestamp": leg2.timestamp,
        "leg2_price": money(leg2_price),
        "leg_spacing_bars": str(leg2_idx - leg1_idx),
        "trap_break_level": money(trap_break_level),
        "failure_close": money(current.close),
        "confirmation_rule": "second_leg_then_opposite_close_beyond_previous_bar",
        "invalidation_note": "如果第二腿后没有反向跟进，或立刻再破第二腿极值，本候选失效。",
    }


def base_event(
    *,
    generated_at: str,
    strategy_id: str,
    strategy_title: str,
    detector_name: str,
    symbol: str,
    bar: Bar,
    direction: str,
    confidence: Decimal,
    data_path: Path,
    source_checksum: str,
    reason: str,
    extra: dict[str, str],
) -> dict[str, Any]:
    row = {
        "schema_version": "m12.20.detector-event.v1",
        "detector_version": "m12.20.detector.v1",
        "stage": "M12.20.visual_detector_implementation",
        "generated_at": generated_at,
        "strategy_id": strategy_id,
        "strategy_title": strategy_title,
        "detector_name": detector_name,
        "symbol": symbol,
        "market": bar.market,
        "timeframe": "1d",
        "bar_timestamp": bar.timestamp,
        "bar_timezone": bar.timezone,
        "direction": "看涨" if direction == "long" else "看跌",
        "confidence_score": pct(confidence * HUNDRED),
        "data_path": project_path(data_path),
        "source_cache_path": project_path(data_path),
        "source_checksum": source_checksum,
        "source_lineage": "native_daily_cache",
        "spec_ref": project_path(DETECTOR_RULES_REF),
        "source_refs": SOURCE_REFS_BY_STRATEGY[strategy_id],
        "evidence_refs": [
            f"reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_19/m12_19_detector_candidates.jsonl#{strategy_id}"
        ],
        "data_lineage": "native_daily_cache",
        "automatic_reason": reason,
        "not_trade_signal": "true",
        "paper_simulated_only": "true",
        "broker_connection": "false",
        "real_orders": "false",
        "live_execution": "false",
    }
    row.update(extra)
    row["event_id"] = stable_event_id(row)
    return row


def stable_event_id(row: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(row["detector_version"]),
            str(row["strategy_id"]),
            str(row["symbol"]),
            str(row["timeframe"]),
            str(row["bar_timestamp"]),
            str(row.get("detector_event_type", "")),
            str(row.get("context_window_start", "")),
            str(row.get("context_window_end", "")),
            str(row["source_checksum"]),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def cap_events_per_strategy_symbol(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["strategy_id"], row["symbol"])].append(row)
    capped: list[dict[str, str]] = []
    for key in sorted(grouped):
        ordered = sorted(grouped[key], key=lambda row: row["bar_timestamp"])
        capped.extend(ordered[-EVENT_CAP_PER_STRATEGY_SYMBOL:])
    return sorted(capped, key=lambda row: (row["strategy_id"], row["symbol"], row["bar_timestamp"]))


def build_unified_strategy_queue(*, generated_at: str, detector_events: list[dict[str, str]]) -> dict[str, Any]:
    status_payload = load_json(M12_12_STATUS_PATH)
    source_plan = load_json(M12_16_PLAN_PATH)
    ftd_summary = load_json(M12_15_SUMMARY_PATH)
    detector_counts = Counter(row["strategy_id"] for row in detector_events)
    source_links: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in source_plan["rows"]:
        source_links[row["linked_runtime_id"]].append(
            {
                "candidate_id": row["candidate_id"],
                "queue": row["queue"],
                "status": row["status"],
                "selected_variant": row.get("selected_variant", ""),
            }
        )
        if row["linked_runtime_id"] == "M12-FTD-001-filter":
            source_links["M12-FTD-001"].append(
                {
                    "candidate_id": row["candidate_id"],
                    "queue": row["queue"],
                    "status": row["status"],
                    "selected_variant": row.get("selected_variant", ""),
                }
            )

    items: list[dict[str, str]] = []
    for item in status_payload["items"]:
        strategy_id = item["strategy_id"]
        queue = normalize_queue(strategy_id, item["status"])
        if strategy_id in DETECTOR_STRATEGIES:
            queue = "machine_detector_observation"
        if strategy_id == "M10-PA-003":
            queue = "filter_or_ranking_factor"
        if strategy_id == "M12-FTD-001":
            queue = "daily_readonly_test"
        event_count = detector_counts.get(strategy_id, 0)
        reason = item["plain_reason"]
        status = item["status"]
        if strategy_id == "M10-PA-004":
            status = "机器检测器观察中"
            reason = f"已开始机器识别宽通道边界反转；本轮检测到 {event_count} 个候选图形。"
        elif strategy_id == "M10-PA-007":
            status = "机器检测器观察中"
            reason = f"已开始机器识别第二腿陷阱反转；本轮检测到 {event_count} 个候选图形。"
        elif strategy_id == "M12-FTD-001":
            status = "已进入每日测试"
            best = ftd_summary["best_variant"]["selected_variant_id"]
            reason = f"M12.15 已选 {best} 版本；继续每日观察收益、胜率和回撤。"
        elif strategy_id == "M10-PA-003":
            status = "作为选股过滤器"
            reason = "不再单独作为买卖策略；用于给强趋势股票加分。"
        elif strategy_id in {"M10-PA-008", "M10-PA-009"}:
            status = "严格观察中"
            reason = "图例预审已关闭等待状态；现在按严格定义观察典型反转机会。"
        items.append(
            {
                "strategy_id": strategy_id,
                "title": item["title"],
                "unified_queue": queue,
                "client_status": status,
                "candidate_count_today": item["candidate_count_today"],
                "detector_event_count": str(event_count),
                "paper_gate_evidence_now": "false",
                "plain_reason": reason,
                "source_candidate_links": json.dumps(source_links.get(strategy_id, []), ensure_ascii=False),
                "next_action": next_action_for(strategy_id, queue),
            }
        )

    present = {row["strategy_id"] for row in items}
    if "M12-FTD-001-filter" not in present:
        items.append(
            {
                "strategy_id": "M12-FTD-001-filter",
                "title": "长回调保护",
                "unified_queue": "filter_or_ranking_factor",
                "client_status": "作为 FTD 风险过滤器",
                "candidate_count_today": "0",
                "detector_event_count": "0",
                "paper_gate_evidence_now": "false",
                "plain_reason": "该条不是独立买卖策略，只用于降低 M12-FTD-001 的差机会。",
                "source_candidate_links": json.dumps(source_links.get("M12-FTD-001-filter", []), ensure_ascii=False),
                "next_action": "跟随 M12-FTD-001 每日观察，不单独统计盈利。",
            }
        )

    return {
        "schema_version": "m12.20.unified-strategy-queue.v1",
        "stage": "M12.20.visual_detector_implementation",
        "generated_at": generated_at,
        "plain_language_result": "以后统一按这张表看策略，不再把 M10 的16条和 M12 的6条分开汇报。",
        "daily_test_strategy_ids": list(DAILY_TEST_STRATEGIES),
        "machine_detector_strategy_ids": list(DETECTOR_STRATEGIES),
        "items": sorted(items, key=lambda row: row["strategy_id"]),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def normalize_queue(strategy_id: str, status: str) -> str:
    if strategy_id in DAILY_TEST_STRATEGIES:
        return "daily_readonly_test"
    if "辅助" in status:
        return "supporting_rule"
    if "研究" in status:
        return "research_only"
    if "暂不" in status:
        return "paused_or_not_priority"
    if "观察" in status or "等待" in status:
        return "strict_observation"
    return "manual_review"


def next_action_for(strategy_id: str, queue: str) -> str:
    if queue == "daily_readonly_test":
        return "继续进入每日看板，优先看机会数、模拟盈亏、胜率和最大回撤。"
    if queue == "machine_detector_observation":
        return "继续收集机器识别到的候选图形，下一步抽样核对稳定性后再决定是否回测。"
    if queue == "filter_or_ranking_factor":
        return "作为选股加减分或风险过滤，不单独当买卖策略。"
    if queue == "strict_observation":
        return "先观察典型机会，不进入自动买卖准入。"
    if queue == "supporting_rule":
        return "只辅助目标、止损或仓位，不单独触发交易。"
    if queue == "research_only":
        return "保留研究，不进入每日测试。"
    return "暂不进入每日主线。"


def build_summary(
    *,
    generated_at: str,
    symbols: list[str],
    input_rows: list[dict[str, str]],
    deferred: list[dict[str, str]],
    detector_events: list[dict[str, Any]],
    raw_counts: Counter[str],
    unified_queue: dict[str, Any],
) -> dict[str, Any]:
    event_counts = Counter(row["strategy_id"] for row in detector_events)
    event_by_symbol = Counter(row["symbol"] for row in detector_events)
    return {
        "schema_version": "m12.20.visual-detector-implementation-summary.v1",
        "stage": "M12.20.visual_detector_implementation",
        "generated_at": generated_at,
        "plain_language_result": "机器识别检测器已经开始跑：M10-PA-004/007 现在有真实K线候选事件，不再停留在只写计划。",
        "symbols_requested": len(symbols),
        "daily_cache_ready_symbols": len(input_rows),
        "deferred_input_count": len(deferred),
        "timeframe": "1d",
        "event_cap_per_strategy_symbol": EVENT_CAP_PER_STRATEGY_SYMBOL,
        "raw_detector_event_count_before_cap": dict(raw_counts),
        "detector_event_count": len(detector_events),
        "detector_event_count_by_strategy": dict(event_counts),
        "top_symbols_by_detector_event_count": [
            {"symbol": symbol, "event_count": count} for symbol, count in event_by_symbol.most_common(10)
        ],
        "unified_queue_count": len(unified_queue["items"]),
        "daily_test_strategy_ids": list(DAILY_TEST_STRATEGIES),
        "machine_detector_strategy_ids": list(DETECTOR_STRATEGIES),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_detector_report_md(summary: dict[str, Any]) -> str:
    counts = summary["detector_event_count_by_strategy"]
    lines = [
        "# M12.20 机器识别检测器运行报告",
        "",
        "## 用人话结论",
        "",
        f"- 这次不是继续写计划，已经用第一批 `{summary['daily_cache_ready_symbols']}` 只股票/ETF 的日线缓存跑了检测器。",
        f"- 共识别出 `{summary['detector_event_count']}` 个候选图形："
        f"`M10-PA-004` {counts.get('M10-PA-004', 0)} 个，"
        f"`M10-PA-007` {counts.get('M10-PA-007', 0)} 个。",
        "- 这些候选还不是买卖信号，所以不统计盈利、胜率或回撤；下一步是抽样看机器识别是否像人眼看到的图形。",
        "- 每个策略/标的最多保留最近 50 个候选，避免报告被历史老样本淹没。",
        "",
        "## 接下来怎么用",
        "",
        "- `M10-PA-004`：看机器能否稳定找到宽通道、触边和触边后反转。",
        "- `M10-PA-007`：看机器能否稳定找到第一腿、第二腿、陷阱点和反向失败。",
        "- 如果抽样稳定，再进入下一轮历史回测；如果不稳定，就正式降级为图形研究，不拖每日测试主线。",
        "",
        "## 只读边界",
        "",
        "- 本阶段不接真实账户，不下真实订单，不做真钱交易。",
    ]
    return "\n".join(lines) + "\n"


def build_unified_queue_md(queue: dict[str, Any]) -> str:
    lines = [
        "# M12.20 统一策略队列表",
        "",
        "## 用人话结论",
        "",
        "- 后续按这一张表推进，不再把 16 条 M10 策略和 6 条来源回看候选分开讲。",
        "- 能进每日测试的继续进每日看板；不能直接测的，要么作为过滤器，要么作为图形检测器，要么暂停。",
        "",
        "| 策略 | 当前队列 | 状态 | 下一步 |",
        "|---|---|---|---|",
    ]
    for row in queue["items"]:
        lines.append(
            f"| `{row['strategy_id']}` {row['title']} | {row['unified_queue']} | {row['client_status']} | {row['next_action']} |"
        )
    return "\n".join(lines) + "\n"


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "```yaml\n"
        "task_id: M12.20-visual-detector-implementation\n"
        "role: main-agent\n"
        "branch_or_worktree: feature/m12-20-visual-detector-implementation\n"
        "objective: 实现 M10-PA-004/007 机器识别检测器，并把 M10/M12 策略合并成统一队列\n"
        "status: success\n"
        "files_changed:\n"
        "  - scripts/m12_20_visual_detector_implementation_lib.py\n"
        "  - scripts/run_m12_20_visual_detector_implementation.py\n"
        "  - tests/unit/test_m12_20_visual_detector_implementation.py\n"
        "  - reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_20/*\n"
        "interfaces_changed: []\n"
        "commands_run:\n"
        "  - python scripts/run_m12_20_visual_detector_implementation.py\n"
        "tests_run: []\n"
        "assumptions:\n"
        "  - 第一版检测器先使用 1d 长窗口缓存，不把当前单日5m伪装成长历史日内测试。\n"
        "risks:\n"
        "  - 检测器事件只是候选图形，不是交易信号，也不是盈利结论。\n"
        "qa_focus:\n"
        "  - 检查 M10-PA-004/007 是否只输出候选图形，不输出真实交易字段。\n"
        "rollback_notes:\n"
        "  - 回滚本阶段提交即可撤回检测器实现和 m12_20 产物。\n"
        "next_recommended_action: 抽样检查候选图形稳定性，稳定后再决定是否做历史回测。\n"
        "needs_user_decision: false\n"
        "user_decision_needed: ''\n"
        "```\n"
        f"\n本次检测器事件数：{summary['detector_event_count']}。\n"
    )


def cn_boundary(boundary: str) -> str:
    return "下边界" if boundary == "lower_boundary" else "上边界"


def money(value: Decimal) -> str:
    return str(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def pct(value: Decimal) -> str:
    return str(value.quantize(PERCENT, rounding=ROUND_HALF_UP))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")


def iter_text_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file():
            yield path
