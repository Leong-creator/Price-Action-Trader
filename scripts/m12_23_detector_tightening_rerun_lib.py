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

from scripts.m12_20_visual_detector_implementation_lib import (  # noqa: E402
    EVENT_CAP_PER_STRATEGY_SYMBOL,
    best_cache_file,
    cap_events_per_strategy_symbol,
    detect_broad_channel_boundary_reversal,
    detect_second_leg_trap_reversal,
    file_sha256,
    load_config,
    project_path,
    select_first_batch_symbols,
)
from scripts.m12_21_detector_quality_review_lib import review_event  # noqa: E402
from scripts.m12_22_detector_sample_visual_review_lib import review_sample  # noqa: E402
from scripts.m12_liquid_universe_scanner_lib import Bar, load_bars  # noqa: E402


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
BASE_M12_20_DIR = M10_DIR / "visual_detectors" / "m12_20"
BASE_M12_22_DIR = M10_DIR / "visual_detectors" / "m12_22"
OUTPUT_DIR = M10_DIR / "visual_detectors" / "m12_23"
BASE_M12_20_SUMMARY = BASE_M12_20_DIR / "m12_20_visual_detector_run_summary.json"
BASE_M12_22_SUMMARY = BASE_M12_22_DIR / "m12_22_sample_visual_review_summary.json"
VISUAL_DECISIONS = ("looks_valid", "borderline_needs_chart_review", "likely_false_positive")
QUALITY_STATUSES = ("auto_pass_high", "auto_pass_medium", "needs_spot_check", "auto_reject")
PERCENT = Decimal("0.01")
HUNDRED = Decimal("100")
ZERO = Decimal("0")
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
    "profit_factor",
    "win_rate",
    "drawdown",
    "equity_curve",
)


def run_m12_23_detector_tightening_rerun(
    *,
    generated_at: str | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_config()
    symbols = select_first_batch_symbols(config)
    raw_events: list[dict[str, Any]] = []
    strict_raw_events: list[dict[str, Any]] = []
    input_rows: list[dict[str, str]] = []
    deferred_rows: list[dict[str, str]] = []
    bars_by_path: dict[str, list[Bar]] = {}

    for symbol in symbols:
        cache_path = best_cache_file(config.local_data_roots, symbol, "1d", config.daily_start, config.daily_end)
        if cache_path is None:
            deferred_rows.append({"symbol": symbol, "timeframe": "1d", "reason": "daily_cache_missing"})
            continue
        bars = load_bars(cache_path)
        checksum = file_sha256(cache_path)
        input_rows.append(
            {
                "symbol": symbol,
                "timeframe": "1d",
                "data_path": project_path(cache_path),
                "source_checksum": checksum,
                "bar_count": str(len(bars)),
                "first_bar": bars[0].timestamp if bars else "",
                "last_bar": bars[-1].timestamp if bars else "",
            }
        )
        bars_by_path[project_path(cache_path)] = bars
        symbol_raw = detect_broad_channel_boundary_reversal(
            generated_at=generated_at,
            symbol=symbol,
            bars=bars,
            data_path=cache_path,
            source_checksum=checksum,
        )
        symbol_raw.extend(
            detect_second_leg_trap_reversal(
                generated_at=generated_at,
                symbol=symbol,
                bars=bars,
                data_path=cache_path,
                source_checksum=checksum,
            )
        )
        raw_events.extend(symbol_raw)
        strict_raw_events.extend(event for event in symbol_raw if passes_tightening(event, bars))

    strict_retained_events = cap_events_per_strategy_symbol(strict_raw_events)
    strict_quality_rows: list[dict[str, Any]] = []
    strict_visual_rows: list[dict[str, Any]] = []
    for event in strict_retained_events:
        cache_path = resolve_repo_path(event["source_cache_path"])
        bars = bars_by_path.get(project_path(cache_path))
        if bars is None:
            bars = load_bars(cache_path)
            bars_by_path[project_path(cache_path)] = bars
        quality_row = review_event(event, bars, cache_path, generated_at)
        strict_quality_rows.append(quality_row)
        strict_visual_rows.append(review_sample(quality_row_to_sample(quality_row), event, bars, generated_at))

    baseline_m12_20 = load_json(BASE_M12_20_SUMMARY)
    baseline_m12_22 = load_json(BASE_M12_22_SUMMARY)
    raw_audit_rows = build_raw_capped_audit_rows(raw_events, strict_raw_events, strict_retained_events)
    comparison_rows = build_comparison_rows(baseline_m12_22, strict_visual_rows)
    summary = build_summary(
        generated_at=generated_at,
        symbols=symbols,
        input_rows=input_rows,
        deferred_rows=deferred_rows,
        baseline_m12_20=baseline_m12_20,
        baseline_m12_22=baseline_m12_22,
        raw_events=raw_events,
        strict_raw_events=strict_raw_events,
        strict_retained_events=strict_retained_events,
        strict_quality_rows=strict_quality_rows,
        strict_visual_rows=strict_visual_rows,
        raw_audit_rows=raw_audit_rows,
        comparison_rows=comparison_rows,
    )

    write_json(output_dir / "m12_23_detector_tightening_summary.json", summary)
    write_json(output_dir / "m12_23_input_manifest.json", {"schema_version": "m12.23.input-manifest.v1", "items": input_rows})
    write_json(output_dir / "m12_23_deferred_inputs.json", {"schema_version": "m12.23.deferred-inputs.v1", "items": deferred_rows})
    write_json(output_dir / "m12_23_raw_capped_audit.json", {"schema_version": "m12.23.raw-capped-audit.v1", "items": raw_audit_rows})
    write_csv(output_dir / "m12_23_raw_capped_audit.csv", raw_audit_rows)
    write_jsonl(output_dir / "m12_23_tightened_detector_events.jsonl", strict_retained_events)
    write_csv(output_dir / "m12_23_tightened_detector_events.csv", strict_retained_events)
    write_jsonl(output_dir / "m12_23_tightened_quality_ledger.jsonl", strict_quality_rows)
    write_csv(output_dir / "m12_23_tightened_quality_ledger.csv", strict_quality_rows)
    write_csv(output_dir / "m12_23_tightened_visual_review_ledger.csv", strict_visual_rows)
    write_csv(output_dir / "m12_23_before_after_comparison.csv", comparison_rows)
    (output_dir / "m12_23_detector_tightening_report.md").write_text(build_report_md(summary), encoding="utf-8")
    (output_dir / "m12_23_next_step.md").write_text(build_next_step_md(summary), encoding="utf-8")
    (output_dir / "m12_23_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def passes_tightening(event: dict[str, Any], bars: list[Bar]) -> bool:
    if event["strategy_id"] == "M10-PA-004":
        return passes_pa004_tightening(event, bars)
    if event["strategy_id"] == "M10-PA-007":
        return passes_pa007_tightening(event, bars)
    return False


def passes_pa004_tightening(event: dict[str, Any], bars: list[Bar]) -> bool:
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    try:
        current = bars[by_ts[event["bar_timestamp"]]]
        start = by_ts[event["range_start_timestamp"]]
        end = by_ts[event["range_end_timestamp"]]
    except (KeyError, IndexError):
        return False
    window = bars[start : end + 1]
    range_high = d(event["range_high"])
    range_low = d(event["range_low"])
    height = range_high - range_low
    if height <= ZERO:
        return False
    midpoint = (range_high + range_low) / Decimal("2")
    height_percent = d(event["range_height_percent"])
    if height_percent < Decimal("14"):
        return False
    upper_touches = int(event["upper_boundary_touch_count"])
    lower_touches = int(event["lower_boundary_touch_count"])
    if min(upper_touches, lower_touches) < 3:
        return False
    touch_balance = Decimal(min(upper_touches, lower_touches)) / Decimal(max(upper_touches, lower_touches))
    if touch_balance < Decimal("0.35"):
        return False
    above_mid = sum(1 for bar in window if bar.close >= midpoint)
    below_mid = sum(1 for bar in window if bar.close <= midpoint)
    midpoint_balance = Decimal(min(above_mid, below_mid)) / Decimal(max(above_mid, below_mid))
    if midpoint_balance < Decimal("0.35"):
        return False
    if candle_body_ratio(current) < Decimal("0.20"):
        return False
    if height_percent > Decimal("80"):
        return False
    return True


def passes_pa007_tightening(event: dict[str, Any], bars: list[Bar]) -> bool:
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    try:
        current = bars[by_ts[event["bar_timestamp"]]]
        leg1_idx = by_ts[event["leg1_timestamp"]]
        leg2_idx = by_ts[event["leg2_timestamp"]]
        current_idx = by_ts[event["bar_timestamp"]]
    except (KeyError, IndexError):
        return False
    spacing = leg2_idx - leg1_idx
    delay = current_idx - leg2_idx
    if spacing < 4 or spacing > 14:
        return False
    if delay > 8:
        return False
    leg1 = d(event["leg1_price"])
    leg2 = d(event["leg2_price"])
    leg_distance_pct = abs(leg2 - leg1) / max(Decimal("0.01"), abs(leg1)) * HUNDRED
    if leg_distance_pct > Decimal("3.5"):
        return False
    if candle_body_ratio(current) < Decimal("0.20"):
        return False
    between = bars[min(leg1_idx, leg2_idx) : max(leg1_idx, leg2_idx) + 1]
    if event["direction"] == "看涨":
        swing_depth = (max(bar.high for bar in between) - min(leg1, leg2)) / max(
            Decimal("0.01"), max(bar.high for bar in between)
        )
    else:
        swing_depth = (max(leg1, leg2) - min(bar.low for bar in between)) / max(Decimal("0.01"), max(leg1, leg2))
    return swing_depth >= Decimal("0.025")


def quality_row_to_sample(row: dict[str, Any]) -> dict[str, str]:
    return {
        "event_id": row["event_id"],
        "quality_status": row["quality_status"],
        "quality_score": row["quality_score"],
    }


def build_raw_capped_audit_rows(
    raw_events: list[dict[str, Any]],
    strict_raw_events: list[dict[str, Any]],
    strict_retained_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_counts = Counter(row["strategy_id"] for row in raw_events)
    strict_raw_counts = Counter(row["strategy_id"] for row in strict_raw_events)
    strict_retained_counts = Counter(row["strategy_id"] for row in strict_retained_events)
    rows: list[dict[str, Any]] = []
    for strategy_id in ("M10-PA-004", "M10-PA-007"):
        raw_count = raw_counts.get(strategy_id, 0)
        strict_raw = strict_raw_counts.get(strategy_id, 0)
        retained = strict_retained_counts.get(strategy_id, 0)
        rows.append(
            {
                "strategy_id": strategy_id,
                "raw_before_tightening": raw_count,
                "raw_after_tightening": strict_raw,
                "retained_after_cap": retained,
                "event_cap_per_strategy_symbol": EVENT_CAP_PER_STRATEGY_SYMBOL,
                "tightening_retention_percent": pct(Decimal(strict_raw) / Decimal(max(1, raw_count)) * HUNDRED),
                "cap_retention_percent_after_tightening": pct(Decimal(retained) / Decimal(max(1, strict_raw)) * HUNDRED),
                "cap_hides_distribution_risk": "true" if strict_raw > retained else "false",
                "plain_note": "保留样本仍受每策略/标的上限影响，进入历史测试前必须继续看 raw/capped 分布。",
            }
        )
    return rows


def build_comparison_rows(baseline_m12_22: dict[str, Any], strict_visual_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    strict_by_strategy: dict[str, Counter[str]] = defaultdict(Counter)
    for row in strict_visual_rows:
        strict_by_strategy[row["strategy_id"]][row["visual_review_decision"]] += 1
    rows: list[dict[str, Any]] = []
    for strategy_id in ("M10-PA-004", "M10-PA-007"):
        before = baseline_m12_22["visual_review_decision_by_strategy"][strategy_id]
        after = strict_by_strategy[strategy_id]
        rows.append(
            {
                "strategy_id": strategy_id,
                "before_valid": before["looks_valid"],
                "before_borderline": before["borderline_needs_chart_review"],
                "before_false_positive": before["likely_false_positive"],
                "after_valid": after.get("looks_valid", 0),
                "after_borderline": after.get("borderline_needs_chart_review", 0),
                "after_false_positive": after.get("likely_false_positive", 0),
                "borderline_reduction": before["borderline_needs_chart_review"] - after.get("borderline_needs_chart_review", 0),
                "false_positive_reduction": before["likely_false_positive"] - after.get("likely_false_positive", 0),
            }
        )
    before_all = baseline_m12_22["visual_review_decision_counts"]
    after_all = Counter(row["visual_review_decision"] for row in strict_visual_rows)
    rows.append(
        {
            "strategy_id": "ALL",
            "before_valid": before_all["looks_valid"],
            "before_borderline": before_all["borderline_needs_chart_review"],
            "before_false_positive": before_all["likely_false_positive"],
            "after_valid": after_all.get("looks_valid", 0),
            "after_borderline": after_all.get("borderline_needs_chart_review", 0),
            "after_false_positive": after_all.get("likely_false_positive", 0),
            "borderline_reduction": before_all["borderline_needs_chart_review"] - after_all.get("borderline_needs_chart_review", 0),
            "false_positive_reduction": before_all["likely_false_positive"] - after_all.get("likely_false_positive", 0),
        }
    )
    return rows


def build_summary(
    *,
    generated_at: str,
    symbols: list[str],
    input_rows: list[dict[str, str]],
    deferred_rows: list[dict[str, str]],
    baseline_m12_20: dict[str, Any],
    baseline_m12_22: dict[str, Any],
    raw_events: list[dict[str, Any]],
    strict_raw_events: list[dict[str, Any]],
    strict_retained_events: list[dict[str, Any]],
    strict_quality_rows: list[dict[str, Any]],
    strict_visual_rows: list[dict[str, Any]],
    raw_audit_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    after_visual = Counter(row["visual_review_decision"] for row in strict_visual_rows)
    after_quality = Counter(row["quality_status"] for row in strict_quality_rows)
    after_by_strategy: dict[str, dict[str, int]] = {}
    for strategy_id in ("M10-PA-004", "M10-PA-007"):
        subset = [row for row in strict_visual_rows if row["strategy_id"] == strategy_id]
        counts = Counter(row["visual_review_decision"] for row in subset)
        after_by_strategy[strategy_id] = {decision: counts.get(decision, 0) for decision in VISUAL_DECISIONS}
    baseline_counts = baseline_m12_22["visual_review_decision_counts"]
    false_positive_reduction = baseline_counts["likely_false_positive"] - after_visual.get("likely_false_positive", 0)
    borderline_reduction = baseline_counts["borderline_needs_chart_review"] - after_visual.get("borderline_needs_chart_review", 0)
    passed_tightening_gate = (
        after_visual.get("likely_false_positive", 0) < baseline_counts["likely_false_positive"]
        and after_visual.get("borderline_needs_chart_review", 0) < baseline_counts["borderline_needs_chart_review"]
        and after_visual.get("likely_false_positive", 0) <= max(10, baseline_counts["likely_false_positive"] // 4)
        and after_visual.get("borderline_needs_chart_review", 0) <= max(80, baseline_counts["borderline_needs_chart_review"] // 5)
    )
    return {
        "schema_version": "m12.23.detector-tightening-summary.v1",
        "stage": "M12.23.detector_tightening_rerun",
        "generated_at": generated_at,
        "plain_language_result": (
            "已收紧 M10-PA-004/007 的机器识别规则，并重跑检测、结构复核和严格图形复核；"
            "边界和疑似误判已明显下降，可进入小范围历史测试准备。"
            if passed_tightening_gate
            else "已收紧 M10-PA-004/007 的机器识别规则，但边界或疑似误判仍偏多，暂不进入历史测试。"
        ),
        "symbols_requested": len(symbols),
        "daily_cache_ready_symbols": len(input_rows),
        "deferred_input_count": len(deferred_rows),
        "timeframe": "1d",
        "baseline_m12_20_event_count": baseline_m12_20["detector_event_count"],
        "baseline_m12_20_raw_before_cap": baseline_m12_20["raw_detector_event_count_before_cap"],
        "baseline_m12_22_visual_review_counts": baseline_counts,
        "strict_raw_event_count": len(strict_raw_events),
        "strict_retained_event_count": len(strict_retained_events),
        "strict_quality_status_counts": {status: after_quality.get(status, 0) for status in QUALITY_STATUSES},
        "strict_visual_review_counts": {decision: after_visual.get(decision, 0) for decision in VISUAL_DECISIONS},
        "strict_visual_review_by_strategy": after_by_strategy,
        "borderline_reduction": borderline_reduction,
        "false_positive_reduction": false_positive_reduction,
        "raw_capped_audit": raw_audit_rows,
        "before_after_comparison": comparison_rows,
        "passed_tightening_gate_for_small_pilot": passed_tightening_gate,
        "can_enter_full_backtest_now": False,
        "can_enter_small_pilot_next": passed_tightening_gate,
        "next_step": (
            "进入 M12.24：只做 PA004/PA007 的 1d 小范围历史测试，并继续保留只读/模拟边界。"
            if passed_tightening_gate
            else "继续收紧 detector；不要进入历史测试。"
        ),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_report_md(summary: dict[str, Any]) -> str:
    lines = [
        "# M12.23 检测器收紧重跑报告",
        "",
        "## 用人话结论",
        "",
        f"- 收紧前，M12.22 里边界样例 `{summary['baseline_m12_22_visual_review_counts']['borderline_needs_chart_review']}` 条，疑似误判 `{summary['baseline_m12_22_visual_review_counts']['likely_false_positive']}` 条。",
        f"- 收紧后，本轮边界样例 `{summary['strict_visual_review_counts']['borderline_needs_chart_review']}` 条，疑似误判 `{summary['strict_visual_review_counts']['likely_false_positive']}` 条。",
        f"- 边界样例减少 `{summary['borderline_reduction']}` 条，疑似误判减少 `{summary['false_positive_reduction']}` 条。",
        f"- 收紧后保留 `{summary['strict_retained_event_count']}` 条候选图形，仍然只是候选，不是买卖信号。",
        f"- 结论：{summary['plain_language_result']}",
        "",
        "## 分策略对比",
        "",
        "| 策略 | 收紧前清晰 | 收紧前边界 | 收紧前疑似误判 | 收紧后清晰 | 收紧后边界 | 收紧后疑似误判 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["before_after_comparison"]:
        if row["strategy_id"] == "ALL":
            continue
        lines.append(
            f"| `{row['strategy_id']}` | {row['before_valid']} | {row['before_borderline']} | {row['before_false_positive']} | "
            f"{row['after_valid']} | {row['after_borderline']} | {row['after_false_positive']} |"
        )
    lines.extend(
        [
            "",
            "## raw/capped 审计",
            "",
            "| 策略 | 原始候选 | 收紧后原始候选 | cap 后保留 | 收紧保留率 | cap 后保留率 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summary["raw_capped_audit"]:
        lines.append(
            f"| `{row['strategy_id']}` | {row['raw_before_tightening']} | {row['raw_after_tightening']} | "
            f"{row['retained_after_cap']} | {row['tightening_retention_percent']}% | "
            f"{row['cap_retention_percent_after_tightening']}% |"
        )
    lines.extend(
        [
            "",
            "## 后续处理",
            "",
            "- 这一步只解决机器是否更像目标图形，不统计收益、胜率或资金曲线。",
            "- 如果进入 M12.24，也只做小范围历史测试，不直接进入模拟买卖试运行。",
            "- 每日测试主线继续跑 `M10-PA-001 / 002 / 012 + M12-FTD-001`，不被本阶段阻塞。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_next_step_md(summary: dict[str, Any]) -> str:
    if summary["can_enter_small_pilot_next"]:
        next_step = "M12.24 可以启动：只跑 `M10-PA-004/007` 的 `1d` 小范围历史测试。"
    else:
        next_step = "继续收紧检测器，不启动 M12.24。"
    return (
        "# M12.23 后续动作\n\n"
        f"- {next_step}\n"
        "- 不能进入完整历史回测。\n"
        "- 不能进入模拟买卖试运行。\n"
        "- 不能把本阶段图形质量当作盈利能力。\n"
    )


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "```yaml\n"
        "task_id: M12.23-detector-tightening-rerun\n"
        "role: main-agent\n"
        "branch_or_worktree: feature/m12-23-detector-tightening-rerun\n"
        "objective: 收紧 M10-PA-004/007 检测器并重跑检测、结构复核和严格图形复核\n"
        "status: success\n"
        "files_changed:\n"
        "  - scripts/m12_23_detector_tightening_rerun_lib.py\n"
        "  - scripts/run_m12_23_detector_tightening_rerun.py\n"
        "  - tests/unit/test_m12_23_detector_tightening_rerun.py\n"
        "  - reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_23/*\n"
        "interfaces_changed: []\n"
        "tests_run:\n"
        "  - python -m unittest tests/unit/test_m12_23_detector_tightening_rerun.py -v\n"
        "verification_results:\n"
        f"  - 收紧后保留候选 {summary['strict_retained_event_count']} 条\n"
        f"  - 边界样例 {summary['strict_visual_review_counts']['borderline_needs_chart_review']} 条\n"
        f"  - 疑似误判 {summary['strict_visual_review_counts']['likely_false_positive']} 条\n"
        f"  - 可进入 M12.24 小范围历史测试准备：{str(summary['can_enter_small_pilot_next']).lower()}\n"
        "assumptions:\n"
        "  - 仅使用第一批 50 只股票/ETF 的 1d 本地只读缓存\n"
        "  - 本阶段只证明检测器质量改善，不证明盈利能力\n"
        "risks:\n"
        "  - cap 后保留样本仍可能与 raw 全历史分布不同，M12.24 必须继续保留来源与样本边界说明\n"
        "qa_focus:\n"
        "  - 检查 before/after、raw/capped audit、禁出字段和 PA004/PA007 队列边界\n"
        "rollback_notes:\n"
        "  - 回滚本阶段提交即可撤回 M12.23 收紧重跑产物\n"
        "next_recommended_action: M12.24 只做 PA004/PA007 的 1d 小范围历史测试\n"
        "needs_user_decision: false\n"
        "user_decision_needed: ''\n"
        "```\n"
    )


def candle_body_ratio(bar: Bar) -> Decimal:
    return abs(bar.close - bar.open) / max(Decimal("0.01"), bar.high - bar.low)


def d(value: Any) -> Decimal:
    return Decimal(str(value))


def pct(value: Decimal) -> str:
    return str(value.quantize(PERCENT, rounding=ROUND_HALF_UP))


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def load_json(path: Path) -> dict[str, Any]:
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


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")
