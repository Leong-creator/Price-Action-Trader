#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_historical_pilot_lib import aggregate_bars
from src.data import OhlcvRow, load_ohlcv_csv


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_10_definition_fix_and_retest.json"
OUTPUT_DIR = M10_DIR / "definition_fix" / "m12_10_definition_fix_and_retest"
TARGET_IDS = ("M10-PA-005", "M10-PA-004", "M10-PA-007")
PA005_ID = "M10-PA-005"
VISUAL_DEFINITION_IDS = ("M10-PA-004", "M10-PA-007")
PRIORITY_VISUAL_IDS = ("M10-PA-008", "M10-PA-009")
TIMEFRAMES = ("1d", "1h", "15m", "5m")
FORBIDDEN_TEXT = (
    "PA-SC-",
    "SF-",
    "promote",
    "live-ready",
    "paper_trading_approval=true",
    "broker_connection=true",
    "real_orders=true",
    "live_execution=true",
    "uses_profit_curve_tuning,true",
)


@dataclass(frozen=True, slots=True)
class M1210Config:
    title: str
    run_id: str
    m10_4_dataset_inventory_path: Path
    m10_9_before_after_metrics_path: Path
    m10_9_summary_path: Path
    m12_9_visual_closure_index_path: Path
    m12_9_case_review_ledger_path: Path
    output_dir: Path
    paper_simulated_only: bool
    paper_trading_approval: bool
    broker_connection: bool
    real_orders: bool
    live_execution: bool


@dataclass(frozen=True, slots=True)
class GeometryEvent:
    strategy_id: str
    symbol: str
    timeframe: str
    direction: str
    signal_timestamp: str
    entry_timestamp: str
    range_high: Decimal
    range_low: Decimal
    range_height: Decimal
    breakout_edge: Decimal
    breakout_timestamp: str
    reentry_close: Decimal
    reentry_timestamp: str
    failed_breakout_extreme: Decimal
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    risk_per_share: Decimal
    setup_notes: str
    event_id: str


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def load_m12_10_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M1210Config:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    config = M1210Config(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_10_definition_fix_and_retest"),
        m10_4_dataset_inventory_path=resolve_repo_path(payload["m10_4_dataset_inventory_path"]),
        m10_9_before_after_metrics_path=resolve_repo_path(payload["m10_9_before_after_metrics_path"]),
        m10_9_summary_path=resolve_repo_path(payload["m10_9_summary_path"]),
        m12_9_visual_closure_index_path=resolve_repo_path(payload["m12_9_visual_closure_index_path"]),
        m12_9_case_review_ledger_path=resolve_repo_path(payload["m12_9_case_review_ledger_path"]),
        output_dir=resolve_repo_path(payload["output_dir"]),
        paper_simulated_only=bool(payload["paper_simulated_only"]),
        paper_trading_approval=bool(payload["paper_trading_approval"]),
        broker_connection=bool(payload["broker_connection"]),
        real_orders=bool(payload["real_orders"]),
        live_execution=bool(payload["live_execution"]),
    )
    validate_config(config)
    return config


def validate_config(config: M1210Config) -> None:
    if not config.paper_simulated_only:
        raise ValueError("M12.10 must remain paper/simulated only")
    if config.paper_trading_approval or config.broker_connection or config.real_orders or config.live_execution:
        raise ValueError("M12.10 must not approve paper trading, broker, orders, or live execution")


def run_m12_10_definition_fix_and_retest(
    config: M1210Config,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    validate_config(config)
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    config.output_dir.mkdir(parents=True, exist_ok=True)

    m10_9_metrics = load_csv(config.m10_9_before_after_metrics_path)
    m10_9_summary = load_json(config.m10_9_summary_path)
    visual_closure = load_json(config.m12_9_visual_closure_index_path)
    case_ledger = load_json(config.m12_9_case_review_ledger_path)

    geometry_events, deferred_geometry = build_pa005_geometry_events(config)
    validate_geometry_event_identity(geometry_events)
    field_ledger = build_field_ledger(geometry_events, visual_closure, case_ledger)
    metrics_rows = build_metrics_rows(m10_9_metrics, field_ledger)
    summary = build_summary(config, generated_at, geometry_events, deferred_geometry, field_ledger, metrics_rows, m10_9_summary)

    write_json(config.output_dir / "m12_10_definition_field_ledger.json", field_ledger)
    write_geometry_events(config.output_dir / "m12_10_pa005_geometry_events.csv", geometry_events)
    write_metrics(config.output_dir / "m12_10_before_after_metrics.csv", metrics_rows)
    write_json(config.output_dir / "m12_10_retest_summary.json", summary)
    (config.output_dir / "m12_10_definition_fix_report.md").write_text(build_report(summary, metrics_rows), encoding="utf-8")
    (config.output_dir / "m12_10_retest_client_summary.md").write_text(build_client_summary(summary, metrics_rows), encoding="utf-8")
    (config.output_dir / "m12_10_handoff.md").write_text(build_handoff(config, summary), encoding="utf-8")
    assert_no_forbidden_output(config.output_dir)
    return summary


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def project_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def build_pa005_geometry_events(config: M1210Config) -> tuple[list[GeometryEvent], list[dict[str, str]]]:
    inventory = load_json(config.m10_4_dataset_inventory_path)
    rows = [
        row
        for row in inventory["records"]
        if row["status"] == "available" and row["timeframe"] in TIMEFRAMES
    ]
    events: list[GeometryEvent] = []
    deferred: list[dict[str, str]] = []
    for row in rows:
        csv_path = Path(row["csv_path"])
        if not csv_path.exists():
            deferred.append(
                {
                    "symbol": row["symbol"],
                    "timeframe": row["timeframe"],
                    "reason": "dataset_path_missing",
                    "csv_path": str(csv_path),
                }
            )
            continue
        bars = load_ohlcv_csv(csv_path)
        if row["lineage"] == "derived_from_5m":
            bars = aggregate_bars(bars, row["timeframe"])
        events.extend(detect_pa005_geometry_events(bars))
    events.sort(key=lambda item: (item.timeframe, item.symbol, item.signal_timestamp, item.direction))
    return events, deferred


def detect_pa005_geometry_events(bars: list[OhlcvRow]) -> list[GeometryEvent]:
    events: list[GeometryEvent] = []
    for i in range(20, len(bars) - 4):
        prior = bars[i - 20 : i]
        range_high = max(bar.high for bar in prior)
        range_low = min(bar.low for bar in prior)
        range_height = range_high - range_low
        avg_price = sum((bar.close for bar in prior), Decimal("0")) / Decimal("20")
        if avg_price <= 0 or range_height / avg_price > Decimal("0.12"):
            continue
        breakout = bars[i]
        if breakout.high > range_high:
            confirm = next((j for j in (i + 1, i + 2, i + 3) if bars[j].close < range_high), None)
            if confirm is None:
                continue
            failed_extreme = max(bar.high for bar in bars[i : confirm + 1])
            event = build_geometry_event(
                bars=bars,
                signal_index=confirm,
                breakout_index=i,
                direction="short",
                range_high=range_high,
                range_low=range_low,
                range_height=range_height,
                breakout_edge=range_high,
                failed_breakout_extreme=failed_extreme,
                setup_notes="failed_upside_range_breakout",
            )
            if event:
                events.append(event)
        elif breakout.low < range_low:
            confirm = next((j for j in (i + 1, i + 2, i + 3) if bars[j].close > range_low), None)
            if confirm is None:
                continue
            failed_extreme = min(bar.low for bar in bars[i : confirm + 1])
            event = build_geometry_event(
                bars=bars,
                signal_index=confirm,
                breakout_index=i,
                direction="long",
                range_high=range_high,
                range_low=range_low,
                range_height=range_height,
                breakout_edge=range_low,
                failed_breakout_extreme=failed_extreme,
                setup_notes="failed_downside_range_breakout",
            )
            if event:
                events.append(event)
    return events


def build_geometry_event(
    *,
    bars: list[OhlcvRow],
    signal_index: int,
    breakout_index: int,
    direction: str,
    range_high: Decimal,
    range_low: Decimal,
    range_height: Decimal,
    breakout_edge: Decimal,
    failed_breakout_extreme: Decimal,
    setup_notes: str,
) -> GeometryEvent | None:
    if signal_index + 1 >= len(bars):
        return None
    signal = bars[signal_index]
    entry = bars[signal_index + 1]
    entry_price = entry.open
    if direction == "long":
        stop = failed_breakout_extreme
        risk = entry_price - stop
        target = entry_price + risk * Decimal("2")
    else:
        stop = failed_breakout_extreme
        risk = stop - entry_price
        target = entry_price - risk * Decimal("2")
    if risk <= 0:
        return None
    breakout = bars[breakout_index]
    event_key = "|".join(
        (
            PA005_ID,
            signal.symbol,
            signal.timeframe,
            direction,
            signal.timestamp.isoformat(),
            entry.timestamp.isoformat(),
            breakout.timestamp.isoformat(),
            f"{range_high}",
            f"{range_low}",
            f"{range_height}",
            f"{breakout_edge}",
            f"{failed_breakout_extreme}",
            setup_notes,
        )
    )
    return GeometryEvent(
        strategy_id=PA005_ID,
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        direction=direction,
        signal_timestamp=signal.timestamp.isoformat(),
        entry_timestamp=entry.timestamp.isoformat(),
        range_high=range_high,
        range_low=range_low,
        range_height=range_height,
        breakout_edge=breakout_edge,
        breakout_timestamp=breakout.timestamp.isoformat(),
        reentry_close=signal.close,
        reentry_timestamp=signal.timestamp.isoformat(),
        failed_breakout_extreme=failed_breakout_extreme,
        entry_price=entry_price,
        stop_price=stop,
        target_price=target,
        risk_per_share=risk,
        setup_notes=setup_notes,
        event_id=hashlib.sha1(event_key.encode("utf-8")).hexdigest()[:24],
    )


def validate_geometry_event_identity(events: list[GeometryEvent]) -> None:
    ids = [event.event_id for event in events]
    duplicates = [event_id for event_id, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"M12.10 geometry event_id collision or duplicate rows: {duplicates[:5]}")


def build_field_ledger(
    geometry_events: list[GeometryEvent],
    visual_closure: dict[str, Any],
    case_ledger: dict[str, Any],
) -> dict[str, Any]:
    visual_rows = {row["strategy_id"]: row for row in visual_closure["strategy_rows"]}
    case_counts = Counter(row["strategy_id"] for row in case_ledger["case_rows"])
    geometry_count = len(geometry_events)
    geometry_by_timeframe = Counter(event.timeframe for event in geometry_events)
    return {
        "schema_version": "m12.10.definition-field-ledger.v1",
        "strategy_rows": [
            {
                "strategy_id": PA005_ID,
                "field_status": "geometry_fields_persisted_for_retest_review",
                "definition_decision": "reject_for_now_after_geometry_review",
                "geometry_event_count": geometry_count,
                "geometry_event_count_by_timeframe": dict(sorted(geometry_by_timeframe.items())),
                "geometry_event_identity": {
                    "event_id_semantics": "one stable row per distinct failed-breakout geometry candidate",
                    "event_id_unique": True,
                    "identity_fields": [
                        "strategy_id",
                        "symbol",
                        "timeframe",
                        "direction",
                        "signal_timestamp",
                        "entry_timestamp",
                        "breakout_timestamp",
                        "range_high",
                        "range_low",
                        "range_height",
                        "breakout_edge",
                        "failed_breakout_extreme",
                        "setup_notes",
                    ],
                },
                "required_fields": {
                    "range_high": "available",
                    "range_low": "available",
                    "range_height": "available",
                    "breakout_edge": "available",
                    "reentry_close": "available",
                    "failed_breakout_extreme": "available",
                },
                "retest_path": "m10_9_before_after_metrics_reused_with_m12_10_geometry_event_ledger",
                "paper_gate_evidence_now": False,
            },
            visual_definition_field_row("M10-PA-004", visual_rows["M10-PA-004"], case_counts["M10-PA-004"]),
            visual_definition_field_row("M10-PA-007", visual_rows["M10-PA-007"], case_counts["M10-PA-007"]),
        ],
        "priority_visual_gate_guard": [
            {
                "strategy_id": strategy_id,
                "paper_gate_evidence_now": False,
                "reason": "M12.9 requires user confirmation before visual strategies can count as gate evidence.",
            }
            for strategy_id in PRIORITY_VISUAL_IDS
        ],
    }


def visual_definition_field_row(strategy_id: str, visual_row: dict[str, Any], case_count: int) -> dict[str, Any]:
    if strategy_id == "M10-PA-004":
        fields = {
            "wide_channel_boundary": "requires_manual_or_new_detector_label",
            "boundary_touch": "requires_manual_or_new_detector_label",
            "reversal_confirmation": "requires_manual_or_new_detector_label",
            "channel_invalidation": "requires_manual_or_new_detector_label",
        }
    else:
        fields = {
            "first_leg_count": "requires_manual_or_new_detector_label",
            "second_leg_count": "requires_manual_or_new_detector_label",
            "trap_confirmation": "requires_manual_or_new_detector_label",
            "opposite_failure_point": "requires_manual_or_new_detector_label",
        }
    return {
        "strategy_id": strategy_id,
        "field_status": "downgraded_visual_only_not_backtestable",
        "definition_decision": "visual_only_not_backtestable_without_manual_labels",
        "visual_case_count": case_count,
        "source_m12_9_status": visual_row["strategy_level_status"],
        "required_fields": fields,
        "retest_path": "not_rerun_no_executable_definition",
        "paper_gate_evidence_now": False,
    }


def build_metrics_rows(m10_9_metrics: list[dict[str, str]], field_ledger: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in m10_9_metrics:
        if row["cost_tier"] != "baseline":
            continue
        rows.append(
            {
                "strategy_id": PA005_ID,
                "timeframe": row["timeframe"],
                "status": "reject_for_now_after_geometry_review",
                "before_trade_count": row["before_trade_count"],
                "after_trade_count": row["after_trade_count"],
                "before_net_profit": row["before_net_profit"],
                "after_net_profit": row["after_net_profit"],
                "before_return_percent": row["before_return_percent"],
                "after_return_percent": row["after_return_percent"],
                "before_win_rate": row["before_win_rate"],
                "after_win_rate": row["after_win_rate"],
                "before_max_drawdown": row["before_max_drawdown"],
                "after_max_drawdown": row["after_max_drawdown"],
                "geometry_fields_available": "true",
                "uses_profit_curve_tuning": "false",
                "paper_gate_evidence_now": "false",
                "notes": "M12.10 persists range geometry fields for review, but M10.9 cleaned metrics remain weak or blocker-bearing; keep rejected for now.",
            }
        )
    for item in field_ledger["strategy_rows"]:
        if item["strategy_id"] == PA005_ID:
            continue
        rows.append(
            {
                "strategy_id": item["strategy_id"],
                "timeframe": "",
                "status": item["definition_decision"],
                "before_trade_count": "",
                "after_trade_count": "",
                "before_net_profit": "",
                "after_net_profit": "",
                "before_return_percent": "",
                "after_return_percent": "",
                "before_win_rate": "",
                "after_win_rate": "",
                "before_max_drawdown": "",
                "after_max_drawdown": "",
                "geometry_fields_available": "false",
                "uses_profit_curve_tuning": "false",
                "paper_gate_evidence_now": "false",
                "notes": "Visual case evidence exists, but required geometry labels are not executable from OHLCV without a new detector or manual labeling.",
            }
        )
    validate_metrics_rows(rows)
    return rows


def validate_metrics_rows(rows: list[dict[str, str]]) -> None:
    strategy_ids = {row["strategy_id"] for row in rows}
    if strategy_ids != set(TARGET_IDS):
        raise ValueError(f"M12.10 scope drift: {sorted(strategy_ids)}")
    if any(row["uses_profit_curve_tuning"] != "false" for row in rows):
        raise ValueError("M12.10 must not tune definitions from profit curve")
    if any(row["paper_gate_evidence_now"] != "false" for row in rows):
        raise ValueError("M12.10 must not create paper gate evidence")
    for strategy_id in VISUAL_DEFINITION_IDS:
        rows_for_strategy = [row for row in rows if row["strategy_id"] == strategy_id]
        if len(rows_for_strategy) != 1:
            raise ValueError(f"{strategy_id} should have exactly one downgrade row")
        if rows_for_strategy[0]["after_trade_count"]:
            raise ValueError(f"{strategy_id} must not receive fake retest metrics")


def build_summary(
    config: M1210Config,
    generated_at: str,
    geometry_events: list[GeometryEvent],
    deferred_geometry: list[dict[str, str]],
    field_ledger: dict[str, Any],
    metrics_rows: list[dict[str, str]],
    m10_9_summary: dict[str, Any],
) -> dict[str, Any]:
    rows_by_strategy = {row["strategy_id"]: row for row in field_ledger["strategy_rows"]}
    pa005_metrics = [row for row in metrics_rows if row["strategy_id"] == PA005_ID]
    return {
        "schema_version": "m12.10.definition-fix-retest-summary.v1",
        "stage": "M12.10.definition_fix_and_retest",
        "run_id": config.run_id,
        "generated_at": generated_at,
        "strategy_ids": list(TARGET_IDS),
        "paper_simulated_only": True,
        "paper_trading_approval": False,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "uses_profit_curve_tuning": False,
        "pa005_geometry_fields_available": True,
        "pa005_geometry_event_count": len(geometry_events),
        "pa005_geometry_event_id_unique": True,
        "pa005_geometry_deferred_count": len(deferred_geometry),
        "pa005_previous_definition_cleared": bool(m10_9_summary["definition_cleared"]),
        "pa005_decision": rows_by_strategy[PA005_ID]["definition_decision"],
        "visual_definition_decisions": {
            strategy_id: rows_by_strategy[strategy_id]["definition_decision"]
            for strategy_id in VISUAL_DEFINITION_IDS
        },
        "priority_visual_gate_guard": field_ledger["priority_visual_gate_guard"],
        "metrics_rows": pa005_metrics,
        "source_refs": {
            "m10_4_dataset_inventory": project_path(config.m10_4_dataset_inventory_path),
            "m10_9_metrics": project_path(config.m10_9_before_after_metrics_path),
            "m10_9_summary": project_path(config.m10_9_summary_path),
            "m12_9_visual_closure": project_path(config.m12_9_visual_closure_index_path),
            "m12_9_case_review_ledger": project_path(config.m12_9_case_review_ledger_path),
        },
        "artifacts": {
            "field_ledger": project_path(config.output_dir / "m12_10_definition_field_ledger.json"),
            "geometry_events": project_path(config.output_dir / "m12_10_pa005_geometry_events.csv"),
            "metrics_csv": project_path(config.output_dir / "m12_10_before_after_metrics.csv"),
            "summary_json": project_path(config.output_dir / "m12_10_retest_summary.json"),
            "definition_fix_report": project_path(config.output_dir / "m12_10_definition_fix_report.md"),
            "client_summary": project_path(config.output_dir / "m12_10_retest_client_summary.md"),
            "handoff": project_path(config.output_dir / "m12_10_handoff.md"),
        },
    }


def write_geometry_events(path: Path, events: list[GeometryEvent]) -> None:
    fields = [
        "event_id",
        "strategy_id",
        "symbol",
        "timeframe",
        "direction",
        "signal_timestamp",
        "entry_timestamp",
        "range_high",
        "range_low",
        "range_height",
        "breakout_edge",
        "breakout_timestamp",
        "reentry_close",
        "reentry_timestamp",
        "failed_breakout_extreme",
        "entry_price",
        "stop_price",
        "target_price",
        "risk_per_share",
        "setup_notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for event in events:
            writer.writerow({field: str(getattr(event, field)) for field in fields})


def write_metrics(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "strategy_id",
        "timeframe",
        "status",
        "before_trade_count",
        "after_trade_count",
        "before_net_profit",
        "after_net_profit",
        "before_return_percent",
        "after_return_percent",
        "before_win_rate",
        "after_win_rate",
        "before_max_drawdown",
        "after_max_drawdown",
        "geometry_fields_available",
        "uses_profit_curve_tuning",
        "paper_gate_evidence_now",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_report(summary: dict[str, Any], metrics_rows: list[dict[str, str]]) -> str:
    lines = [
        "# M12.10 Definition Fix and Retest Report",
        "",
        "## 摘要",
        "",
        "- 范围只覆盖 `M10-PA-005 / M10-PA-004 / M10-PA-007`。",
        "- `M10-PA-005` 已重新从本地 OHLCV 计算并落盘交易区间几何字段：range high/low/height、breakout edge、re-entry close、failed breakout extreme。",
        "- `M10-PA-005` geometry ledger 现在按 distinct failed-breakout geometry candidate 生成唯一 `event_id`，不会把同一 signal 下的不同 breakout geometry 混成同一记录。",
        "- `M10-PA-004 / M10-PA-007` 仍无法在无人工通道/腿部标签的情况下稳定量化，本阶段正式降级为 visual-only / manual-labeling，不生成假回测。",
        "- `M10-PA-008 / M10-PA-009` 的图例仍未被用户确认，继续不得计入 paper gate evidence。",
        "- 本阶段不接 broker、不接账户、不下单，也不批准 paper trading。",
        "",
        f"- `M10-PA-005` geometry event count: `{summary['pa005_geometry_event_count']}`",
        f"- `M10-PA-005` geometry deferred count: `{summary['pa005_geometry_deferred_count']}`",
        "",
        "## M10-PA-005 复测口径",
        "",
        "| Timeframe | Before Trades | After Trades | After Net Profit | After Return % | After Win Rate | After Max DD | Decision |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in [item for item in metrics_rows if item["strategy_id"] == PA005_ID]:
        lines.append(
            f"| {row['timeframe']} | {row['before_trade_count']} | {row['after_trade_count']} | "
            f"{row['after_net_profit']} | {row['after_return_percent']} | {row['after_win_rate']} | "
            f"{row['after_max_drawdown']} | `{row['status']}` |"
        )
    lines.extend(
        [
            "",
            "## M10-PA-004 / M10-PA-007 降级结论",
            "",
            "| Strategy | Decision | Reason |",
            "|---|---|---|",
        ]
    )
    for row in [item for item in metrics_rows if item["strategy_id"] in VISUAL_DEFINITION_IDS]:
        lines.append(f"| {row['strategy_id']} | `{row['status']}` | {row['notes']} |")
    lines.extend(
        [
            "",
            "## 甲方可读结论",
            "",
            "`M10-PA-005` 已补齐结构字段，但历史复测仍不足以进入自动观察或 paper gate；当前结论是 `reject_for_now_after_geometry_review`。`M10-PA-004/007` 不再悬空等待自动回测，正式降级为需要人工标签或新检测器后再讨论。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_client_summary(summary: dict[str, Any], metrics_rows: list[dict[str, str]]) -> str:
    pa005_rows = [row for row in metrics_rows if row["strategy_id"] == PA005_ID]
    lines = [
        "# M12.10 客户复测摘要",
        "",
        "这一步把三个定义问题策略做了明确处理：一个补齐字段后保留复测数字，两个正式降级，不再占用自动回测队列。",
        "",
        "## 有复测数字的策略",
        "",
        "| 策略 | 周期 | 修正后交易数 | 修正后净利润 | 修正后胜率 | 当前结论 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in pa005_rows:
        lines.append(
            f"| {row['strategy_id']} | {row['timeframe']} | {row['after_trade_count']} | "
            f"{row['after_net_profit']} | {row['after_win_rate']} | `{row['status']}` |"
        )
    lines.extend(
        [
            "",
            "## 正式降级的策略",
            "",
            "- `M10-PA-004`：宽通道边界反转需要人工通道边界/触碰标签，暂不适合自动回测。",
            "- `M10-PA-007`：第二腿陷阱需要人工腿部/陷阱确认标签，暂不适合自动回测。",
            "",
            "当前仍不批准 paper trading；后续重点转向只读看板、真实观察窗口和 universe cache 补齐。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_handoff(config: M1210Config, summary: dict[str, Any]) -> str:
    return f"""task_id: M12.10 Definition Fix and Retest
role: main_agent
branch_or_worktree: feature/m12-10-definition-fix-and-retest
objective: Persist M10-PA-005 range geometry fields, reuse traceable retest metrics, and formally downgrade M10-PA-004/007 when executable labels are absent.
status: success
files_changed:
  - README.md
  - docs/acceptance.md
  - docs/status.md
  - plans/active-plan.md
  - reports/strategy_lab/README.md
  - config/examples/m12_10_definition_fix_and_retest.json
  - scripts/m12_10_definition_fix_retest_lib.py
  - scripts/run_m12_10_definition_fix_retest.py
  - tests/unit/test_m12_10_definition_fix_retest.py
  - reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_10_definition_fix_and_retest/
interfaces_changed:
  - Added M12.10 definition fix artifacts and runner.
commands_run:
  - python scripts/run_m12_10_definition_fix_retest.py
tests_run:
  - python scripts/validate_kb.py
  - python scripts/validate_kb_coverage.py
  - python scripts/validate_knowledge_atoms.py
  - python -m unittest tests/unit/test_m12_10_definition_fix_retest.py -v
  - python -m unittest tests/unit/test_m12_definition_fix_and_retest.py -v
  - python -m unittest discover -s tests/unit -v
  - python -m unittest discover -s tests/reliability -v
  - git diff --check
assumptions:
  - M10-PA-005 retest metrics remain sourced from M10.9; M12.10 adds geometry field persistence and decision clarity.
  - M10-PA-005 event_id is row-level for each distinct failed-breakout geometry candidate, not signal-level.
  - M10-PA-004/007 cannot be honestly retested without manual labels or a new detector.
risks:
  - M10-PA-005 remains reject_for_now after geometry review; do not route it into automatic observation.
qa_focus:
  - Confirm M10-PA-005 geometry fields are present.
  - Confirm M10-PA-004/007 have no fake trade metrics.
  - Confirm M10-PA-008/009 remain excluded from paper gate evidence.
rollback_notes:
  - Revert M12.10 commit or remove {project_path(config.output_dir)} artifacts.
next_recommended_action: Continue M12.11 read-only trading dashboard and keep M12.8 cache fetch plan as a separate controlled data task.
needs_user_decision: false
user_decision_needed:
summary:
  pa005_geometry_event_count: {summary['pa005_geometry_event_count']}
  pa005_decision: {summary['pa005_decision']}
  visual_definition_decisions: {summary['visual_definition_decisions']}
"""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def assert_no_forbidden_output(output_dir: Path) -> None:
    combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in output_dir.glob("m12_10_*") if path.is_file())
    lowered = combined.lower()
    for forbidden in FORBIDDEN_TEXT:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden M12.10 output text found: {forbidden}")


def main() -> int:
    summary = run_m12_10_definition_fix_and_retest(load_m12_10_config())
    print(
        "M12.10 definition fix and retest complete: "
        f"pa005_geometry_events={summary['pa005_geometry_event_count']} / "
        f"pa005_decision={summary['pa005_decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
