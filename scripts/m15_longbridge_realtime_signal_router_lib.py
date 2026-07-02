#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.m15_longbridge_realtime_execution_lib import (
    AUXILIARY_STRATEGY_IDS,
    DEFAULT_DAILY_DIR,
    DEFAULT_REALTIME_RUNTIME_IDS,
    EXPERIMENT_CAPITAL_BUCKET_RUNTIME_IDS,
    REPAIR_RUNTIME_IDS,
    SHADOW_RUNTIME_MARKERS,
    LONG_BRIDGE_ALLOWED_LOSS_STREAK_RUNTIME_IDS,
    LONG_BRIDGE_ALLOWED_SHADOW_RUNTIME_IDS,
    VirtualCapitalBucket,
    capital_bucket_for_runtime,
    decimal,
    fmt_decimal,
    fmt_money,
    parent_strategy_id,
    parse_utc_datetime,
    parse_virtual_capital_buckets,
    resolve_session_started_at,
    session_start_is_auto,
    normalize_whole_share_quantity,
    to_iso,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_signal_router.json"
DEFAULT_MARKET_EVENTS = DEFAULT_OUTPUT_DIR / "m15_realtime_market_events.jsonl"
DEFAULT_SIGNAL_EVENTS = DEFAULT_OUTPUT_DIR / "m15_realtime_signal_events.jsonl"
DEFAULT_EPOCH_STATE = DEFAULT_OUTPUT_DIR / "m15_longbridge_virtual_account_epoch.json"
SUMMARY_JSON = "m15_longbridge_realtime_signal_router.json"
LEDGER_JSONL = "m15_longbridge_realtime_signal_router_ledger.jsonl"
REPORT_MD = "m15_longbridge_realtime_signal_router.md"
ZERO = Decimal("0")
HUNDRED = Decimal("100")
CONFLUENCE_MAX_MULTIPLIER = Decimal("1.75")
NEW_YORK = ZoneInfo("America/New_York")
PRICE_ACTION_REALTIME_DETECTOR = "price_action_realtime_v1"
PRICE_ACTION_RUNTIME_SPECS = {
    "M10-PA-001-1d": {
        "strategy_id": "M10-PA-001",
        "timeframe": "1d",
        "rule": "trend_continuation",
        "target_r": Decimal("1.60"),
        "min_close_position": Decimal("0.55"),
        "max_risk_percent": Decimal("6.00"),
    },
    "M10-PA-001-5m": {
        "strategy_id": "M10-PA-001",
        "timeframe": "5m",
        "rule": "trend_continuation",
        "target_r": Decimal("1.40"),
        "min_close_position": Decimal("0.55"),
        "max_risk_percent": Decimal("2.50"),
    },
    "M10-PA-002-1d": {
        "strategy_id": "M10-PA-002",
        "timeframe": "1d",
        "rule": "breakout_confirmation",
        "target_r": Decimal("2.00"),
        "min_close_position": Decimal("0.65"),
        "max_risk_percent": Decimal("6.00"),
    },
    "M10-PA-002-5m": {
        "strategy_id": "M10-PA-002",
        "timeframe": "5m",
        "rule": "breakout_confirmation",
        "target_r": Decimal("1.60"),
        "min_close_position": Decimal("0.60"),
        "max_risk_percent": Decimal("2.50"),
    },
    "M10-PA-005-1d": {
        "strategy_id": "M10-PA-005",
        "timeframe": "1d",
        "rule": "failed_breakdown_reclaim",
        "target_r": Decimal("1.50"),
        "min_close_position": Decimal("0.60"),
        "max_risk_percent": Decimal("6.00"),
    },
    "M10-PA-005-5m": {
        "strategy_id": "M10-PA-005",
        "timeframe": "5m",
        "rule": "failed_breakdown_reclaim",
        "target_r": Decimal("1.30"),
        "min_close_position": Decimal("0.60"),
        "max_risk_percent": Decimal("2.50"),
    },
    "M10-PA-008-1d": {
        "strategy_id": "M10-PA-008",
        "timeframe": "1d",
        "rule": "reversal_followthrough",
        "target_r": Decimal("1.60"),
        "min_close_position": Decimal("0.60"),
        "max_risk_percent": Decimal("6.00"),
    },
    "M10-PA-012-5m": {
        "strategy_id": "M10-PA-012",
        "timeframe": "5m",
        "rule": "opening_range_breakout",
        "target_r": Decimal("1.20"),
        "max_risk_percent": Decimal("2.50"),
    },
    "M10-PA-011-ORB-R1-5m": {
        "strategy_id": "M10-PA-011",
        "timeframe": "5m",
        "rule": "opening_range_breakout",
        "target_r": Decimal("1.20"),
        "max_risk_percent": Decimal("2.50"),
    },
    "M10-PA-013-1d": {
        "strategy_id": "M10-PA-013",
        "timeframe": "1d",
        "rule": "support_resistance_failure",
        "target_r": Decimal("1.60"),
        "min_close_position": Decimal("0.60"),
        "max_risk_percent": Decimal("6.00"),
    },
    "M10-PA-013-5m": {
        "strategy_id": "M10-PA-013",
        "timeframe": "5m",
        "rule": "support_resistance_failure",
        "target_r": Decimal("1.40"),
        "min_close_position": Decimal("0.60"),
        "max_risk_percent": Decimal("2.50"),
    },
    "M12-FTD-001-baseline-1d": {
        "strategy_id": "M12-FTD-001",
        "timeframe": "1d",
        "rule": "follow_through_day",
        "target_r": Decimal("1.50"),
        "min_close_position": Decimal("0.55"),
        "max_risk_percent": Decimal("6.00"),
    },
    "M12-FTD-001-loss-streak-guard-1d": {
        "strategy_id": "M12-FTD-001",
        "timeframe": "1d",
        "rule": "follow_through_day",
        "target_r": Decimal("1.50"),
        "min_close_position": Decimal("0.55"),
        "max_risk_percent": Decimal("6.00"),
    },
}


@dataclass(frozen=True, slots=True)
class RealtimeSignalRouterConfig:
    stage: str
    title: str
    market_events_path: Path
    signal_events_path: Path
    test_epoch_state_path: Path
    output_dir: Path
    session_started_at: str
    allowed_runtime_ids: tuple[str, ...]
    enabled_detectors: tuple[str, ...]
    max_signal_events_per_run: int
    paper_account_equity: Decimal
    max_total_exposure: Decimal
    max_symbol_exposure: Decimal
    max_risk_per_order: Decimal
    min_cash_reserve: Decimal
    allow_fractional_shares: bool
    allow_short_selling: bool
    allow_options: bool
    minimum_net_profit_after_fees: Decimal
    normal_minimum_net_profit_after_fees: Decimal
    minimum_reward_r: Decimal
    runtime_minimum_net_profit_after_fees: dict[str, Decimal]
    runtime_minimum_reward_r: dict[str, Decimal]
    conditional_net_profit_requires_confluence: bool
    commission_per_order_side: Decimal
    regulatory_fee_per_sell_order: Decimal
    runtime_position_multipliers: dict[str, Decimal]
    virtual_capital_buckets: dict[str, VirtualCapitalBucket]
    runtime_capital_bucket_map: dict[str, str]
    additional_runtime_bucket_routes: dict[str, tuple[str, ...]]
    hard_boundaries: dict[str, bool]

    def __post_init__(self) -> None:
        validate_config(self)


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RealtimeSignalRouterConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    router = payload.get("realtime_signal_router", {})
    account_model = payload.get("paper_account_model", {})
    fee_model = payload.get("fee_model", {})
    virtual_buckets, runtime_bucket_map = parse_virtual_capital_buckets(payload, account_model)
    return RealtimeSignalRouterConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_signal_router")),
        title=str(payload.get("title", "长桥模拟账户实时信号路由器")),
        market_events_path=resolve_repo_path(inputs.get("market_events", DEFAULT_MARKET_EVENTS)),
        signal_events_path=resolve_repo_path(inputs.get("signal_events", DEFAULT_SIGNAL_EVENTS)),
        test_epoch_state_path=resolve_repo_path(inputs.get("test_epoch_state", DEFAULT_EPOCH_STATE)),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        session_started_at=str(router.get("session_started_at", "")),
        allowed_runtime_ids=tuple(str(item) for item in router.get("allowed_runtime_ids", list(DEFAULT_REALTIME_RUNTIME_IDS))),
        enabled_detectors=tuple(
            str(item)
            for item in router.get(
                "enabled_detectors",
                ["embedded_signal_intents", "pa004_followthrough_long", PRICE_ACTION_REALTIME_DETECTOR],
            )
        ),
        max_signal_events_per_run=int(router.get("max_signal_events_per_run", 50)),
        paper_account_equity=decimal(account_model.get("equity", "10000")),
        max_total_exposure=decimal(account_model.get("max_total_exposure", "6000")),
        max_symbol_exposure=decimal(account_model.get("max_symbol_exposure", "1500")),
        max_risk_per_order=decimal(account_model.get("max_risk_per_order", "20")),
        min_cash_reserve=decimal(account_model.get("min_cash_reserve", "4000")),
        allow_fractional_shares=bool(account_model.get("allow_fractional_shares", False)),
        allow_short_selling=bool(account_model.get("allow_short_selling", False)),
        allow_options=bool(account_model.get("allow_options", False)),
        minimum_net_profit_after_fees=decimal(account_model.get("minimum_net_profit_after_fees", "2")),
        normal_minimum_net_profit_after_fees=decimal(
            account_model.get("normal_minimum_net_profit_after_fees", "5")
        ),
        minimum_reward_r=decimal(account_model.get("minimum_reward_r", "0")),
        runtime_minimum_net_profit_after_fees={
            str(key): decimal(value)
            for key, value in dict(account_model.get("runtime_minimum_net_profit_after_fees", {})).items()
        },
        runtime_minimum_reward_r={
            str(key): decimal(value)
            for key, value in dict(account_model.get("runtime_minimum_reward_r", {})).items()
        },
        conditional_net_profit_requires_confluence=bool(
            account_model.get("conditional_net_profit_requires_confluence", True)
        ),
        commission_per_order_side=decimal(fee_model.get("commission_per_order_side", "1.99")),
        regulatory_fee_per_sell_order=decimal(fee_model.get("regulatory_fee_per_sell_order", "0.02")),
        runtime_position_multipliers={
            str(key): decimal(value)
            for key, value in dict(router.get("runtime_position_multipliers", {})).items()
        },
        virtual_capital_buckets=virtual_buckets,
        runtime_capital_bucket_map=runtime_bucket_map,
        additional_runtime_bucket_routes={
            str(key): tuple(str(item) for item in value if str(item))
            for key, value in dict(router.get("additional_runtime_bucket_routes", {})).items()
            if isinstance(value, list)
        },
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: RealtimeSignalRouterConfig) -> None:
    if config.stage != "M15.longbridge_realtime_signal_router":
        raise ValueError("M15 realtime signal router stage drift")
    if not config.session_started_at:
        raise ValueError("M15 realtime signal router requires session_started_at")
    if not session_start_is_auto(config.session_started_at):
        parse_utc_datetime(config.session_started_at)
    if not config.allowed_runtime_ids:
        raise ValueError("M15 realtime signal router needs a runtime whitelist")
    if not config.virtual_capital_buckets:
        raise ValueError("M15 realtime signal router needs virtual capital buckets")
    for runtime_id in config.allowed_runtime_ids:
        if runtime_id in REPAIR_RUNTIME_IDS:
            continue
        if runtime_id not in config.runtime_capital_bucket_map:
            raise ValueError(f"M15 realtime signal router runtime missing capital bucket: {runtime_id}")
    for runtime_id, bucket_ids in config.additional_runtime_bucket_routes.items():
        if runtime_id not in config.allowed_runtime_ids:
            raise ValueError(f"M15 realtime signal router additional bucket route runtime is not allowed: {runtime_id}")
        for bucket_id in bucket_ids:
            if bucket_id not in config.virtual_capital_buckets:
                raise ValueError(f"M15 realtime signal router additional bucket route missing bucket: {bucket_id}")
    if config.max_signal_events_per_run <= 0:
        raise ValueError("M15 realtime signal router max_signal_events_per_run must be positive")
    if config.normal_minimum_net_profit_after_fees < config.minimum_net_profit_after_fees:
        raise ValueError("M15 realtime signal router normal profit threshold must be >= minimum threshold")
    if config.minimum_reward_r < ZERO:
        raise ValueError("M15 realtime signal router minimum reward/R cannot be negative")
    if config.allow_fractional_shares:
        raise ValueError("M15 realtime signal router forbids fractional shares")
    if config.allow_short_selling:
        raise ValueError("M15 realtime signal router forbids short selling")
    if config.allow_options:
        raise ValueError("M15 realtime signal router forbids options")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 realtime signal router must stay paper/simulated only")
    if config.hard_boundaries.get("live_execution", False):
        raise ValueError("M15 realtime signal router cannot enable live execution")
    if config.hard_boundaries.get("real_money_actions", False):
        raise ValueError("M15 realtime signal router cannot enable real money actions")
    if config.hard_boundaries.get("local_simulation_as_signal_source", False):
        raise ValueError("M15 realtime signal router cannot use local simulation as signal source")


def run_realtime_signal_router(
    config: RealtimeSignalRouterConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    session_started_at = resolve_session_started_at(config.session_started_at, now)
    raw_market_events = read_jsonl(config.market_events_path)
    market_events = realtime_relevant_market_events(raw_market_events, session_started_at)
    existing_signal_events = read_jsonl(config.signal_events_path)
    existing_signal_ids = {str(row.get("signal_id")) for row in existing_signal_events if row.get("signal_id")}
    test_epoch_state = read_json(config.test_epoch_state_path)
    ledger_rows: list[dict[str, Any]] = []
    new_signal_events: list[dict[str, Any]] = []
    selected_bucket_exposure: dict[str, Decimal] = defaultdict(lambda: ZERO)
    selected_bucket_symbol_exposure: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)

    raw_intents = embedded_signal_intents(config, market_events)
    raw_intents.extend(detector_signal_candidates(config, market_events, generated_at=now))
    raw_intents = expand_additional_bucket_routes(config, raw_intents)
    routed_intents, merged_support_intents = merge_confluence_intents(config, raw_intents)
    for support_intent in merged_support_intents:
        row, _signal = build_signal_from_intent(
            config=config,
            intent=support_intent,
            generated_at=now,
            session_started_at=session_started_at,
            test_epoch_state=test_epoch_state,
            existing_signal_ids=existing_signal_ids,
            selected_bucket_exposure=selected_bucket_exposure,
            selected_bucket_symbol_exposure=selected_bucket_symbol_exposure,
        )
        row["router_decision_status"] = "merged_into_confluence_primary"
        row["blockers"] = []
        row["merged_into_runtime_id"] = str(support_intent.get("merged_into_runtime_id", ""))
        row["confluence_group_key"] = str(support_intent.get("confluence_group_key", ""))
        ledger_rows.append(row)

    for intent in routed_intents:
        row, signal = build_signal_from_intent(
            config=config,
            intent=intent,
            generated_at=now,
            session_started_at=session_started_at,
            test_epoch_state=test_epoch_state,
            existing_signal_ids=existing_signal_ids,
            selected_bucket_exposure=selected_bucket_exposure,
            selected_bucket_symbol_exposure=selected_bucket_symbol_exposure,
        )
        ledger_rows.append(row)
        if signal and len(new_signal_events) < config.max_signal_events_per_run:
            new_signal_events.append(signal)
            existing_signal_ids.add(signal["signal_id"])
            bucket_id = str(signal.get("capital_bucket") or "")
            symbol = str(signal["symbol"])
            selected_bucket_exposure[bucket_id] += decimal(signal.get("notional", "0"))
            selected_bucket_symbol_exposure[(bucket_id, symbol)] += decimal(signal.get("notional", "0"))

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.signal_events_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(config.signal_events_path, existing_signal_events + new_signal_events)
    write_jsonl(config.output_dir / LEDGER_JSONL, ledger_rows)
    summary = {
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at_iso,
        "source_mode": "longbridge_realtime_market_events",
        "local_simulation_isolated": True,
        "local_ledger_input_ref": "",
        "legacy_fast_queue_used": False,
        "raw_market_event_count": len(raw_market_events),
        "current_session_market_event_count": current_session_market_event_count(raw_market_events, session_started_at),
        "relevant_market_event_count": len(market_events),
        "stale_market_event_ignored_count": max(0, len(raw_market_events) - len(market_events)),
        "market_event_count": len(market_events),
        "embedded_intent_count": sum(len(event_intents(row)) for row in market_events),
        "router_decision_count": len(ledger_rows),
        "new_signal_event_count": len(new_signal_events),
        "existing_signal_event_count": len(existing_signal_events),
        "signal_event_total_count": len(existing_signal_events) + len(new_signal_events),
        "test_epoch_id": str(test_epoch_state.get("test_epoch_id") or ""),
        "test_epoch_status": str(test_epoch_state.get("status") or ""),
        "test_started_at": str(test_epoch_state.get("test_started_at") or ""),
        "epoch_rebuilt_signal_count": sum(1 for signal in new_signal_events if signal.get("realtime_rebuilt_after_epoch_activation")),
        "confluence_primary_count": sum(1 for intent in routed_intents if decimal(intent.get("confluence_multiplier", "1")) > Decimal("1")),
        "confluence_merged_support_count": len(merged_support_intents),
        "low_profit_blocked_count": sum(
            1 for row in ledger_rows if "blocked_fee_profit_below_minimum" in row.get("blockers", [])
        ),
        "conditional_profit_blocked_count": sum(
            1 for row in ledger_rows if "blocked_fee_profit_requires_confluence" in row.get("blockers", [])
        ),
        "reward_r_blocked_count": sum(
            1 for row in ledger_rows if "blocked_reward_r_below_minimum" in row.get("blockers", [])
        ),
        "quantity_normalized_count": sum(
            1 for row in ledger_rows if row.get("quantity_normalization_status") == "rounded_down_to_whole_share"
        ),
        "quantity_below_one_blocked_count": sum(
            1 for row in ledger_rows if "blocked_quantity_below_one_share" in row.get("blockers", [])
        ),
        "short_disabled_count": sum(
            1 for row in ledger_rows if "blocked_short_disabled" in row.get("blockers", [])
        ),
        "quantity_normalized_risk_or_profit_blocked_count": sum(
            1
            for row in ledger_rows
            if row.get("quantity_normalization_status") == "rounded_down_to_whole_share"
            and any(
                reason in row.get("blockers", [])
                for reason in (
                    "blocked_risk_over_cap",
                    "blocked_symbol_exposure_over_cap",
                    "blocked_total_exposure_over_cap",
                    "blocked_fee_profit_below_minimum",
                    "blocked_fee_profit_requires_confluence",
                    "blocked_reward_r_below_minimum",
                )
            )
        ),
        "blocked_by_reason": count_blockers(ledger_rows),
        "enabled_detectors": list(config.enabled_detectors),
        "allowed_runtime_ids": list(config.allowed_runtime_ids),
        "virtual_capital_buckets": [
            {
                "capital_bucket": bucket_id,
                "label": bucket.label,
                "equity": fmt_money(bucket.equity),
                "max_total_exposure": fmt_money(bucket.max_total_exposure),
                "max_symbol_exposure": fmt_money(bucket.max_symbol_exposure),
                "runtime_ids": list(bucket.runtime_ids),
            }
            for bucket_id, bucket in config.virtual_capital_buckets.items()
        ],
        "additional_runtime_bucket_routes": {
            runtime_id: list(bucket_ids)
            for runtime_id, bucket_ids in config.additional_runtime_bucket_routes.items()
        },
        "session_started_at": session_started_at,
        "inputs": {
            "market_events": project_path(config.market_events_path),
            "test_epoch_state": project_path(config.test_epoch_state_path),
            "local_simulation_ledger": "",
            "fast_signal_queue": "",
        },
        "outputs": {
            "signal_events": project_path(config.signal_events_path),
            "router_summary": project_path(config.output_dir / SUMMARY_JSON),
            "router_ledger": project_path(config.output_dir / LEDGER_JSONL),
            "router_report": project_path(config.output_dir / REPORT_MD),
        },
        "plain_language_result": plain_language_result(len(market_events), len(new_signal_events), ledger_rows),
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
    }
    write_json(config.output_dir / SUMMARY_JSON, summary)
    (config.output_dir / REPORT_MD).write_text(render_report(summary, ledger_rows, new_signal_events), encoding="utf-8")
    return summary


def realtime_relevant_market_events(rows: list[dict[str, Any]], session_started_at: str) -> list[dict[str, Any]]:
    """Return bounded market events relevant to the realtime hot path.

    The router needs a small historical K-line context for price-action
    detectors, but it must not rescan weeks of archived events every cycle.
    Keep:
    - current-session received events;
    - a bounded lookback for symbol/timeframe groups that have current events;
    - embedded strategy-intent events so old/replayed intents are visibly
      blocked by the normal session gate instead of silently disappearing.
    """
    try:
        session_started_dt = parse_utc_datetime(session_started_at)
    except ValueError:
        return rows
    current_keys: set[tuple[str, str]] = set()
    keep_ids: set[int] = set()
    grouped: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for idx, row in enumerate(rows):
        if event_intents(row):
            keep_ids.add(idx)
        event_dt = market_event_received_at(row)
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        key = (symbol, timeframe)
        if symbol and timeframe:
            grouped[key].append((idx, row))
        if event_dt is None or event_dt >= session_started_dt:
            keep_ids.add(idx)
            if symbol and timeframe:
                current_keys.add(key)
    for key in current_keys:
        group_rows = grouped.get(key, [])
        group_rows.sort(key=lambda item: market_event_sort_key(item[1]))
        for idx, _row in group_rows[-20:]:
            keep_ids.add(idx)
    return [row for idx, row in enumerate(rows) if idx in keep_ids]


def current_session_market_event_count(rows: list[dict[str, Any]], session_started_at: str) -> int:
    try:
        session_started_dt = parse_utc_datetime(session_started_at)
    except ValueError:
        return len(rows)
    return sum(1 for row in rows if (market_event_received_at(row) or session_started_dt) >= session_started_dt)


def market_event_received_at(row: dict[str, Any]) -> datetime | None:
    for key in ("received_at", "created_at", "timestamp", "event_time", "bar_time"):
        raw_value = str(row.get(key) or "").strip()
        if not raw_value:
            continue
        try:
            return parse_utc_datetime(raw_value)
        except ValueError:
            continue
    return None


def market_event_sort_key(row: dict[str, Any]) -> str:
    return str(row.get("received_at") or row.get("event_time") or row.get("bar_time") or row.get("timestamp") or "")


def embedded_signal_intents(config: RealtimeSignalRouterConfig, market_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if "embedded_signal_intents" not in set(config.enabled_detectors):
        return []
    intents: list[dict[str, Any]] = []
    for event in market_events:
        for intent in event_intents(event):
            merged = dict(intent)
            merged.setdefault("symbol", event.get("symbol"))
            merged.setdefault("timeframe", event.get("timeframe"))
            merged.setdefault("source_market_event_id", event.get("event_id") or event.get("market_event_id"))
            merged.setdefault("market_event_time", event.get("event_time") or event.get("bar_time") or event.get("timestamp"))
            merged.setdefault("current_price", event.get("close") or event.get("last_price"))
            merged.setdefault("created_at", event.get("received_at") or event.get("event_time") or event.get("timestamp"))
            intents.append(merged)
    return intents


def event_intents(event: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("strategy_signal_intents", "signal_intents", "signals"):
        value = event.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    return []


def merge_confluence_intents(
    config: RealtimeSignalRouterConfig,
    intents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    passthrough: list[dict[str, Any]] = []
    for intent in intents:
        runtime_id = str(intent.get("runtime_id") or "")
        strategy_id = str(intent.get("strategy_id") or parent_strategy_id(runtime_id))
        row = dict(intent)
        row.setdefault("capital_bucket", capital_bucket_for_runtime(config, runtime_id, strategy_id))
        if not confluence_eligible(config, row):
            passthrough.append(row)
            continue
        grouped[confluence_key(row)].append(row)
    routed = list(passthrough)
    merged_supports: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        if len(rows) == 1 or len({str(row.get("runtime_id", "")) for row in rows}) == 1:
            routed.extend(rows)
            continue
        primary = select_confluence_primary(rows)
        supports = [row for row in rows if row is not primary]
        multiplier = confluence_multiplier(rows)
        support_runtime_ids = sorted(str(row.get("runtime_id", "")) for row in supports)
        support_strategy_ids = sorted({parent_strategy_id(str(row.get("runtime_id", ""))) for row in supports})
        primary_intent = dict(primary)
        primary_intent["confluence_group_key"] = key
        primary_intent["confluence_multiplier"] = fmt_ratio(multiplier)
        primary_intent["confluence_support_runtime_ids"] = support_runtime_ids
        primary_intent["confluence_support_strategy_ids"] = support_strategy_ids
        primary_intent["confluence_support_count"] = str(len(supports))
        primary_intent["confluence_family_count"] = str(len({parent_strategy_id(str(row.get("runtime_id", ""))) for row in rows}))
        routed.append(primary_intent)
        for support in supports:
            support_intent = dict(support)
            support_intent["confluence_group_key"] = key
            support_intent["confluence_multiplier"] = fmt_ratio(multiplier)
            support_intent["merged_into_runtime_id"] = str(primary.get("runtime_id", ""))
            merged_supports.append(support_intent)
    return routed, merged_supports


def expand_additional_bucket_routes(
    config: RealtimeSignalRouterConfig,
    intents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for intent in intents:
        row = dict(intent)
        runtime_id = str(row.get("runtime_id") or "")
        strategy_id = str(row.get("strategy_id") or parent_strategy_id(runtime_id))
        default_bucket = str(row.get("capital_bucket") or capital_bucket_for_runtime(config, runtime_id, strategy_id) or "")
        row.setdefault("capital_bucket", default_bucket)
        expanded.append(row)
        for bucket_id in config.additional_runtime_bucket_routes.get(runtime_id, ()):
            if not bucket_id or bucket_id == default_bucket:
                continue
            duplicate = dict(row)
            duplicate["capital_bucket"] = bucket_id
            duplicate["additional_bucket_route"] = True
            duplicate["primary_capital_bucket"] = default_bucket
            if duplicate.get("signal_id"):
                duplicate["signal_id"] = f"{duplicate['signal_id']}-{bucket_id}"
            expanded.append(duplicate)
    return expanded


def confluence_eligible(config: RealtimeSignalRouterConfig, intent: dict[str, Any]) -> bool:
    runtime_id = str(intent.get("runtime_id") or "")
    strategy_id = str(intent.get("strategy_id") or parent_strategy_id(runtime_id))
    if is_ftd_runtime(runtime_id):
        return False
    if strategy_isolation_blockers(runtime_id, strategy_id, config.allowed_runtime_ids):
        return False
    if normalize_direction(intent.get("direction") or intent.get("side")) != "long":
        return False
    if normalize_order_type(intent.get("order_type")) not in {"limit", "trigger_limit"}:
        return False
    if not str(intent.get("symbol") or ""):
        return False
    if not str(intent.get("source_market_event_id") or intent.get("market_event_id") or ""):
        return False
    return True


def confluence_key(intent: dict[str, Any]) -> str:
    runtime_id = str(intent.get("runtime_id") or "")
    strategy_id = str(intent.get("strategy_id") or parent_strategy_id(runtime_id))
    bucket = str(intent.get("capital_bucket") or "")
    symbol = str(intent.get("symbol") or "").upper()
    direction = normalize_direction(intent.get("direction") or intent.get("side"))
    side = "buy" if direction == "long" else "sell_short"
    date_key = ny_date_from_intent(intent)
    return f"{date_key}|{bucket or parent_strategy_id(strategy_id or runtime_id)}|{symbol}|{direction}|{side}"


def is_ftd_runtime(runtime_id: str) -> bool:
    return runtime_id.startswith("M12-FTD-001")


def ny_date_from_intent(intent: dict[str, Any]) -> str:
    for key in ("market_event_time", "created_at"):
        value = str(intent.get(key) or "")
        if not value:
            continue
        try:
            return parse_utc_datetime(value).astimezone(NEW_YORK).date().isoformat()
        except ValueError:
            return value[:10]
    return ""


def select_confluence_primary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(rows, key=confluence_primary_key)[0]


def confluence_primary_key(row: dict[str, Any]) -> tuple[int, Decimal, Decimal, str]:
    entry = decimal(row.get("limit_price", row.get("entry_price", row.get("current_price", "0"))))
    stop = decimal(row.get("stop_price", "0"))
    target = decimal(row.get("target_price", "0"))
    risk = abs(entry - stop)
    reward_r = (target - entry) / risk if risk > ZERO else ZERO
    runtime_id = str(row.get("runtime_id", ""))
    return (runtime_priority(runtime_id), -reward_r, risk, runtime_id)


def runtime_priority(runtime_id: str) -> int:
    if runtime_id == "M10-PA-004-long-1d":
        return 0
    if runtime_id == "M10-PA-013-1d":
        return 1
    if runtime_id.endswith("-1d"):
        return 2
    if runtime_id.startswith("M12-FTD-001"):
        return 3
    return 4


def confluence_multiplier(rows: list[dict[str, Any]]) -> Decimal:
    families = [parent_strategy_id(str(row.get("runtime_id", ""))) for row in rows]
    unique_family_count = len(set(families))
    same_family_extra = max(0, len(rows) - unique_family_count)
    multiplier = Decimal("1.0")
    multiplier += Decimal("0.50") * Decimal(max(0, unique_family_count - 1))
    multiplier += Decimal("0.25") * Decimal(min(same_family_extra, 2))
    return min(multiplier, CONFLUENCE_MAX_MULTIPLIER)


def fmt_ratio(value: Decimal) -> str:
    return format(value.normalize(), "f")


def detector_signal_candidates(
    config: RealtimeSignalRouterConfig,
    market_events: list[dict[str, Any]],
    *,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in market_events:
        if str(event.get("event_type") or "bar_close") not in {"bar_close", "kline_close", "new_bar"}:
            continue
        symbol = str(event.get("symbol") or "").upper()
        timeframe = str(event.get("timeframe") or "")
        if symbol and timeframe:
            grouped[(symbol, timeframe)].append(event)
    for rows in grouped.values():
        rows.sort(key=lambda row: str(row.get("event_time") or row.get("bar_time") or row.get("timestamp") or ""))
    if "pa004_followthrough_long" in set(config.enabled_detectors):
        for (symbol, timeframe), rows in grouped.items():
            if timeframe != "1d" or len(rows) < 2:
                continue
            signal = pa004_followthrough_long_signal(symbol, rows[-2], rows[-1], generated_at=generated_at)
            if signal:
                signal["runtime_id"] = "M10-PA-004-long-1d"
                signal["strategy_id"] = "M10-PA-004"
                signal["timeframe"] = timeframe
                candidates.append(signal)
    if PRICE_ACTION_REALTIME_DETECTOR in set(config.enabled_detectors):
        candidates.extend(price_action_realtime_candidates(config, grouped, generated_at=generated_at))
    return candidates


def price_action_realtime_candidates(
    config: RealtimeSignalRouterConfig,
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    allowed = set(config.allowed_runtime_ids)
    for runtime_id, spec in PRICE_ACTION_RUNTIME_SPECS.items():
        if runtime_id not in allowed:
            continue
        timeframe = str(spec["timeframe"])
        for (symbol, grouped_timeframe), rows in grouped_events.items():
            if grouped_timeframe != timeframe:
                continue
            signal = price_action_signal_for_runtime(
                runtime_id=runtime_id,
                spec=spec,
                symbol=symbol,
                rows=rows,
                generated_at=generated_at,
            )
            if signal:
                candidates.append(signal)
    return candidates


def price_action_signal_for_runtime(
    *,
    runtime_id: str,
    spec: dict[str, Any],
    symbol: str,
    rows: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if symbol in {"SQQQ", "TQQQ"}:
        return None
    rule = str(spec["rule"])
    signal: dict[str, Any] | None
    if rule == "trend_continuation":
        signal = trend_continuation_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "breakout_confirmation":
        signal = breakout_confirmation_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "failed_breakdown_reclaim":
        signal = failed_breakdown_reclaim_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "reversal_followthrough":
        signal = reversal_followthrough_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "opening_range_breakout":
        signal = opening_range_breakout_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "support_resistance_failure":
        signal = support_resistance_failure_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "follow_through_day":
        signal = follow_through_day_signal(symbol, rows, spec=spec, generated_at=generated_at)
    else:
        signal = None
    if not signal:
        return None
    signal["runtime_id"] = runtime_id
    signal["strategy_id"] = str(spec["strategy_id"])
    signal["timeframe"] = str(spec["timeframe"])
    return signal


def trend_continuation_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if len(rows) < 3:
        return None
    prior, previous, latest = rows[-3], rows[-2], rows[-1]
    prior_close = decimal(prior.get("close", "0"))
    previous_close = decimal(previous.get("close", "0"))
    latest_close = decimal(latest.get("close", "0"))
    latest_high = decimal(latest.get("high", "0"))
    latest_low = decimal(latest.get("low", "0"))
    previous_low = decimal(previous.get("low", "0"))
    if min(prior_close, previous_close, latest_close, latest_high, latest_low, previous_low) <= ZERO:
        return None
    if latest_close <= previous_close or previous_close <= prior_close:
        return None
    if close_position(latest) < decimal(spec.get("min_close_position", "0.55")):
        return None
    stop = min(latest_low, previous_low)
    return build_price_action_long_signal(
        detector_id="pa001_trend_continuation_realtime",
        symbol=symbol,
        latest=latest,
        entry=latest_close,
        stop=stop,
        target_r=decimal(spec.get("target_r", "1.5")),
        max_risk_percent=decimal(spec.get("max_risk_percent", "0")),
        order_type="limit",
        generated_at=generated_at,
    )


def breakout_confirmation_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if len(rows) < 3:
        return None
    latest = rows[-1]
    previous_rows = rows[-3:-1]
    entry = decimal(latest.get("close", "0"))
    latest_low = decimal(latest.get("low", "0"))
    previous_high = max(decimal(row.get("high", "0")) for row in previous_rows)
    if entry <= ZERO or latest_low <= ZERO or previous_high <= ZERO:
        return None
    if entry <= previous_high:
        return None
    if close_position(latest) < decimal(spec.get("min_close_position", "0.65")):
        return None
    stop = max(latest_low, previous_high - (entry - previous_high))
    return build_price_action_long_signal(
        detector_id="pa002_breakout_confirmation_realtime",
        symbol=symbol,
        latest=latest,
        entry=entry,
        stop=stop,
        target_r=decimal(spec.get("target_r", "2.0")),
        max_risk_percent=decimal(spec.get("max_risk_percent", "0")),
        order_type="trigger_limit",
        trigger_price=entry,
        generated_at=generated_at,
    )


def failed_breakdown_reclaim_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if len(rows) < 2:
        return None
    previous, latest = rows[-2], rows[-1]
    previous_low = decimal(previous.get("low", "0"))
    previous_close = decimal(previous.get("close", "0"))
    latest_low = decimal(latest.get("low", "0"))
    latest_close = decimal(latest.get("close", "0"))
    if min(previous_low, previous_close, latest_low, latest_close) <= ZERO:
        return None
    if latest_low >= previous_low or latest_close <= previous_low or latest_close <= previous_close:
        return None
    if close_position(latest) < decimal(spec.get("min_close_position", "0.60")):
        return None
    return build_price_action_long_signal(
        detector_id="pa005_failed_breakdown_reclaim_realtime",
        symbol=symbol,
        latest=latest,
        entry=latest_close,
        stop=latest_low,
        target_r=decimal(spec.get("target_r", "1.5")),
        max_risk_percent=decimal(spec.get("max_risk_percent", "0")),
        order_type="limit",
        generated_at=generated_at,
    )


def reversal_followthrough_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if len(rows) < 3:
        return None
    prior, previous, latest = rows[-3], rows[-2], rows[-1]
    prior_close = decimal(prior.get("close", "0"))
    previous_close = decimal(previous.get("close", "0"))
    previous_low = decimal(previous.get("low", "0"))
    latest_low = decimal(latest.get("low", "0"))
    latest_close = decimal(latest.get("close", "0"))
    if min(prior_close, previous_close, previous_low, latest_low, latest_close) <= ZERO:
        return None
    if previous_close >= prior_close:
        return None
    if latest_low >= previous_low or latest_close <= previous_close:
        return None
    if close_position(latest) < decimal(spec.get("min_close_position", "0.60")):
        return None
    return build_price_action_long_signal(
        detector_id="pa008_reversal_followthrough_realtime",
        symbol=symbol,
        latest=latest,
        entry=latest_close,
        stop=latest_low,
        target_r=decimal(spec.get("target_r", "1.6")),
        max_risk_percent=decimal(spec.get("max_risk_percent", "0")),
        order_type="limit",
        generated_at=generated_at,
    )


def opening_range_breakout_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any] | None:
    session_rows = latest_ny_session_rows(rows)
    opening_bars_required = 6
    if len(session_rows) <= opening_bars_required:
        return None
    opening = session_rows[:opening_bars_required]
    latest = session_rows[-1]
    previous = session_rows[-2]
    opening_high = max(decimal(row.get("high", "0")) for row in opening)
    opening_low = min(decimal(row.get("low", "0")) for row in opening)
    previous_close = decimal(previous.get("close", "0"))
    entry = decimal(latest.get("close", "0"))
    latest_low = decimal(latest.get("low", "0"))
    if min(opening_high, opening_low, previous_close, entry, latest_low) <= ZERO or opening_high <= opening_low:
        return None
    if previous_close > opening_high or entry <= opening_high:
        return None
    stop = max(opening_low, latest_low)
    if stop >= entry:
        stop = opening_low
    return build_price_action_long_signal(
        detector_id="pa012_opening_range_breakout_realtime",
        symbol=symbol,
        latest=latest,
        entry=entry,
        stop=stop,
        target_r=decimal(spec.get("target_r", "1.2")),
        max_risk_percent=decimal(spec.get("max_risk_percent", "0")),
        order_type="trigger_limit",
        trigger_price=opening_high,
        generated_at=generated_at,
    )


def support_resistance_failure_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if len(rows) < 3:
        return None
    prior, previous, latest = rows[-3], rows[-2], rows[-1]
    support = min(decimal(prior.get("low", "0")), decimal(previous.get("low", "0")))
    previous_close = decimal(previous.get("close", "0"))
    latest_low = decimal(latest.get("low", "0"))
    latest_close = decimal(latest.get("close", "0"))
    if min(support, previous_close, latest_low, latest_close) <= ZERO:
        return None
    if latest_low >= support or latest_close <= support or latest_close <= previous_close:
        return None
    if close_position(latest) < decimal(spec.get("min_close_position", "0.60")):
        return None
    return build_price_action_long_signal(
        detector_id="pa013_support_resistance_failure_realtime",
        symbol=symbol,
        latest=latest,
        entry=latest_close,
        stop=latest_low,
        target_r=decimal(spec.get("target_r", "1.5")),
        max_risk_percent=decimal(spec.get("max_risk_percent", "0")),
        order_type="limit",
        generated_at=generated_at,
    )


def follow_through_day_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if len(rows) < 2:
        return None
    previous, latest = rows[-2], rows[-1]
    previous_close = decimal(previous.get("close", "0"))
    latest_close = decimal(latest.get("close", "0"))
    previous_volume = decimal(previous.get("volume", "0"))
    latest_volume = decimal(latest.get("volume", "0"))
    latest_low = decimal(latest.get("low", "0"))
    if min(previous_close, latest_close, previous_volume, latest_volume, latest_low) <= ZERO:
        return None
    close_to_close_percent = (latest_close - previous_close) / previous_close * HUNDRED
    if close_to_close_percent < Decimal("1.25") or latest_volume <= previous_volume:
        return None
    if close_position(latest) < decimal(spec.get("min_close_position", "0.55")):
        return None
    return build_price_action_long_signal(
        detector_id="ftd001_follow_through_day_realtime",
        symbol=symbol,
        latest=latest,
        entry=latest_close,
        stop=latest_low,
        target_r=decimal(spec.get("target_r", "1.5")),
        max_risk_percent=decimal(spec.get("max_risk_percent", "0")),
        order_type="limit",
        generated_at=generated_at,
    )


def build_price_action_long_signal(
    *,
    detector_id: str,
    symbol: str,
    latest: dict[str, Any],
    entry: Decimal,
    stop: Decimal,
    target_r: Decimal,
    max_risk_percent: Decimal,
    order_type: str,
    generated_at: datetime,
    trigger_price: Decimal = ZERO,
) -> dict[str, Any] | None:
    if entry <= ZERO or stop <= ZERO or stop >= entry or target_r <= ZERO:
        return None
    risk = entry - stop
    risk_percent = risk / entry * HUNDRED
    if max_risk_percent > ZERO and risk_percent > max_risk_percent:
        return None
    target = entry + risk * target_r
    return {
        "detector_id": detector_id,
        "symbol": symbol,
        "direction": "long",
        "side": "buy",
        "order_type": order_type,
        "trigger_price": fmt_money(trigger_price) if trigger_price > ZERO else "",
        "limit_price": fmt_money(entry),
        "stop_price": fmt_money(stop),
        "target_price": fmt_money(target),
        "current_price": fmt_money(entry),
        "source_market_event_id": str(latest.get("event_id") or latest.get("market_event_id") or ""),
        "market_event_time": str(latest.get("event_time") or latest.get("bar_time") or latest.get("timestamp") or ""),
        "created_at": str(latest.get("received_at") or to_iso(generated_at)),
    }


def close_position(row: dict[str, Any]) -> Decimal:
    high = decimal(row.get("high", "0"))
    low = decimal(row.get("low", "0"))
    close = decimal(row.get("close", "0"))
    if high <= low or close <= ZERO:
        return ZERO
    return (close - low) / (high - low)


def latest_ny_session_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    latest_date = ny_event_date(rows[-1])
    return [row for row in rows if ny_event_date(row) == latest_date]


def ny_event_date(row: dict[str, Any]) -> str:
    value = str(row.get("event_time") or row.get("bar_time") or row.get("timestamp") or "")
    if not value:
        return ""
    try:
        return parse_utc_datetime(value).astimezone(NEW_YORK).date().isoformat()
    except ValueError:
        return value[:10]


def pa004_followthrough_long_signal(
    symbol: str,
    previous: dict[str, Any],
    latest: dict[str, Any],
    *,
    generated_at: datetime,
) -> dict[str, Any] | None:
    if symbol in {"SQQQ", "TQQQ"}:
        return None
    previous_close = decimal(previous.get("close", "0"))
    open_price = decimal(latest.get("open", "0"))
    high = decimal(latest.get("high", "0"))
    low = decimal(latest.get("low", "0"))
    close = decimal(latest.get("close", "0"))
    if previous_close <= ZERO or open_price <= ZERO or high <= ZERO or low <= ZERO or close <= ZERO or high <= low:
        return None
    close_to_close_percent = (close - previous_close) / previous_close * HUNDRED
    gap_percent = (open_price - previous_close) / previous_close * HUNDRED
    close_position = (close - low) / (high - low)
    strong_followthrough = close_to_close_percent >= Decimal("3.00")
    strong_gap_hold = gap_percent >= Decimal("2.50") and close_to_close_percent >= Decimal("1.50")
    if not (strong_followthrough or strong_gap_hold):
        return None
    if close_position < Decimal("0.25"):
        return None
    entry = close
    risk = max(entry - low, entry * Decimal("0.025"))
    if risk <= ZERO:
        return None
    stop = entry - risk
    target = entry + risk * Decimal("2")
    return {
        "detector_id": "pa004_followthrough_long",
        "symbol": symbol,
        "direction": "long",
        "side": "buy",
        "order_type": "limit",
        "limit_price": fmt_money(entry),
        "stop_price": fmt_money(stop),
        "target_price": fmt_money(target),
        "current_price": fmt_money(close),
        "source_market_event_id": str(latest.get("event_id") or latest.get("market_event_id") or ""),
        "market_event_time": str(latest.get("event_time") or latest.get("bar_time") or latest.get("timestamp") or ""),
        "created_at": str(latest.get("received_at") or to_iso(generated_at)),
    }


def build_signal_from_intent(
    *,
    config: RealtimeSignalRouterConfig,
    intent: dict[str, Any],
    generated_at: datetime,
    session_started_at: str,
    test_epoch_state: dict[str, Any],
    existing_signal_ids: set[str],
    selected_bucket_exposure: dict[str, Decimal],
    selected_bucket_symbol_exposure: dict[tuple[str, str], Decimal],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    runtime_id = str(intent.get("runtime_id") or "")
    strategy_id = str(intent.get("strategy_id") or parent_strategy_id(runtime_id))
    symbol = str(intent.get("symbol") or "").upper()
    capital_bucket = str(intent.get("capital_bucket") or capital_bucket_for_runtime(config, runtime_id, strategy_id) or "")
    bucket = config.virtual_capital_buckets.get(capital_bucket)
    bucket_label = bucket.label if bucket else ""
    created_at = str(intent.get("created_at") or to_iso(generated_at))
    source_event_id = str(intent.get("source_market_event_id") or intent.get("market_event_id") or "")
    base_signal_id = str(intent.get("signal_id") or deterministic_signal_id(runtime_id, symbol, source_event_id, created_at))
    if intent.get("additional_bucket_route") and not str(intent.get("signal_id") or ""):
        base_signal_id = f"{base_signal_id}-{capital_bucket}"
    signal_id = base_signal_id
    original_created_at = created_at
    rebuilt_after_epoch_activation = False
    epoch_id = str(test_epoch_state.get("test_epoch_id") or "")
    epoch_started_at = parse_epoch_started_at(test_epoch_state)
    original_created_dt = parse_optional_utc_datetime(original_created_at)
    if (
        epoch_id
        and str(test_epoch_state.get("status") or "") == "active"
        and epoch_started_at is not None
        and original_created_dt is not None
        and original_created_dt < epoch_started_at
        and generated_at >= epoch_started_at
    ):
        signal_id = f"{base_signal_id}-{epoch_id}"
        created_at = to_iso(generated_at)
        rebuilt_after_epoch_activation = True
    direction = normalize_direction(intent.get("direction") or intent.get("side"))
    side = "buy" if direction == "long" else "sell_short"
    order_type = normalize_order_type(intent.get("order_type"))
    entry = decimal(intent.get("limit_price", intent.get("entry_price", intent.get("current_price", "0"))))
    stop = decimal(intent.get("stop_price", "0"))
    target = decimal(intent.get("target_price", "0"))
    current = decimal(intent.get("current_price", entry))
    blockers = strategy_isolation_blockers(runtime_id, strategy_id, config.allowed_runtime_ids)
    if not source_event_id:
        blockers.append("missing_source_market_event_id")
    if not runtime_id:
        blockers.append("missing_runtime_id")
    if side == "buy" and not bucket:
        blockers.append("blocked_missing_capital_bucket")
    if not symbol:
        blockers.append("missing_symbol")
    if signal_id in existing_signal_ids:
        blockers.append("duplicate_signal_event")
    try:
        session_started_dt = parse_utc_datetime(session_started_at)
        if parse_utc_datetime(created_at) < session_started_dt:
            blockers.append("blocked_replay_market_event_before_session_start")
        if original_created_dt is not None and original_created_dt < session_started_dt:
            blockers.append("blocked_replay_market_event_before_session_start")
    except ValueError:
        blockers.append("invalid_signal_created_at")
    if side != "buy":
        blockers.append("blocked_short_disabled")
    if order_type not in {"limit", "trigger_limit"}:
        blockers.append("blocked_order_type")
    trigger = decimal(intent.get("trigger_price", "0"))
    if order_type == "trigger_limit" and trigger <= ZERO:
        blockers.append("missing_trigger_price")
    if entry <= ZERO or stop <= ZERO or target <= ZERO:
        blockers.append("missing_price_geometry")
    risk_per_share = abs(entry - stop)
    if risk_per_share <= ZERO:
        blockers.append("blocked_invalid_risk_geometry")
    if target <= entry:
        blockers.append("blocked_invalid_target_geometry")
    raw_quantity = decimal(intent.get("quantity", "0"))
    multiplier = config.runtime_position_multipliers.get(runtime_id, Decimal("1.0"))
    confluence_boost = decimal(intent.get("confluence_multiplier", "1"))
    base_symbol_exposure = bucket.max_symbol_exposure if bucket else config.max_symbol_exposure
    base_total_exposure = bucket.max_total_exposure if bucket else config.max_total_exposure
    base_risk = min(config.max_risk_per_order, bucket.max_risk_per_order) if bucket else config.max_risk_per_order
    runtime_max_exposure = min(base_symbol_exposure, base_symbol_exposure * multiplier * confluence_boost)
    runtime_max_risk = min(base_risk, base_risk * multiplier * confluence_boost)
    if raw_quantity <= ZERO and entry > ZERO and risk_per_share > ZERO:
        exposure_qty = (runtime_max_exposure / entry).to_integral_value(rounding=ROUND_FLOOR)
        risk_qty = (runtime_max_risk / risk_per_share).to_integral_value(rounding=ROUND_FLOOR)
        raw_quantity = max(min(exposure_qty, risk_qty), ZERO)
    quantity_normalization = normalize_whole_share_quantity(raw_quantity, config.allow_fractional_shares)
    quantity = quantity_normalization.submitted_quantity
    if quantity_normalization.blocker:
        blockers.append(quantity_normalization.blocker)
    notional = entry * quantity
    risk_amount = risk_per_share * quantity
    gross_profit = (target - entry) * quantity
    fees = config.commission_per_order_side * Decimal("2") + config.regulatory_fee_per_sell_order
    net_profit = gross_profit - fees
    reward_r = reward_r_ratio(entry, stop, target)
    minimum_reward_r = runtime_minimum_reward_r(config, runtime_id, strategy_id)
    minimum_net_profit = runtime_minimum_net_profit(config, runtime_id, strategy_id)
    profit_gate_status = profit_quality_gate(config, intent, net_profit, runtime_id, strategy_id)
    if risk_amount > runtime_max_risk:
        blockers.append("blocked_risk_over_cap")
    bucket_symbol_key = (capital_bucket, symbol)
    if notional > base_symbol_exposure or selected_bucket_symbol_exposure.get(bucket_symbol_key, ZERO) + notional > base_symbol_exposure:
        blockers.append("blocked_symbol_exposure_over_cap")
    if selected_bucket_exposure.get(capital_bucket, ZERO) + notional > base_total_exposure:
        blockers.append("blocked_total_exposure_over_cap")
    if profit_gate_status == "below_minimum":
        blockers.append("blocked_fee_profit_below_minimum")
    elif profit_gate_status == "requires_confluence_or_quality":
        blockers.append("blocked_fee_profit_requires_confluence")
    if reward_r < minimum_reward_r:
        blockers.append("blocked_reward_r_below_minimum")
    status = "signal_event_ready" if not blockers else blockers[0]
    row = {
        "stage": config.stage,
        "signal_id": signal_id,
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "capital_bucket": capital_bucket,
        "capital_bucket_label": bucket_label,
        "symbol": symbol,
        "timeframe": str(intent.get("timeframe") or ""),
        "source_market_event_id": source_event_id,
        "created_at": created_at,
        "processed_at": to_iso(generated_at),
        "detector_id": str(intent.get("detector_id") or "embedded_signal_intent"),
        "router_decision_status": status,
        "blockers": blockers,
        "raw_suggested_quantity": fmt_decimal(quantity_normalization.raw_quantity),
        "submitted_quantity": fmt_decimal(quantity),
        "quantity_rounding_adjustment": fmt_decimal(quantity_normalization.rounded_down_quantity),
        "quantity_normalization_status": quantity_normalization.status,
        "quantity_normalization_blocker": quantity_normalization.blocker,
        "quantity": fmt_decimal(quantity),
        "limit_price": fmt_money(entry) if entry > ZERO else "",
        "stop_price": fmt_money(stop) if stop > ZERO else "",
        "target_price": fmt_money(target) if target > ZERO else "",
        "risk_amount": fmt_money(risk_amount),
        "notional": fmt_money(notional),
        "net_profit_after_fees_at_target": fmt_money(net_profit),
        "profit_quality_gate": profit_gate_status,
        "reward_r": fmt_decimal(reward_r),
        "minimum_reward_r": fmt_decimal(minimum_reward_r),
        "minimum_net_profit_after_fees": fmt_money(minimum_net_profit),
        "bucket_max_total_exposure": fmt_money(base_total_exposure),
        "bucket_max_symbol_exposure": fmt_money(base_symbol_exposure),
        "bucket_max_risk_per_order": fmt_money(runtime_max_risk),
        "high_quality_signal": intent_is_high_quality(intent),
        "confluence_group_key": str(intent.get("confluence_group_key") or ""),
        "confluence_multiplier": fmt_decimal(confluence_boost),
        "confluence_support_count": str(intent.get("confluence_support_count") or "0"),
        "confluence_support_runtime_ids": list(intent.get("confluence_support_runtime_ids", []))
        if isinstance(intent.get("confluence_support_runtime_ids"), list)
        else [],
        "additional_bucket_route": bool(intent.get("additional_bucket_route", False)),
        "primary_capital_bucket": str(intent.get("primary_capital_bucket") or ""),
        "test_epoch_id": epoch_id,
        "test_epoch_status": str(test_epoch_state.get("status") or ""),
        "test_started_at": str(test_epoch_state.get("test_started_at") or ""),
        "original_signal_created_at": original_created_at if rebuilt_after_epoch_activation else "",
        "realtime_rebuilt_after_epoch_activation": rebuilt_after_epoch_activation,
        "local_simulation_ignored": True,
        "fast_queue_used": False,
    }
    if blockers:
        return row, None
    signal = {
        "signal_id": signal_id,
        "created_at": created_at,
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "capital_bucket": capital_bucket,
        "capital_bucket_label": bucket_label,
        "test_epoch_id": epoch_id,
        "test_epoch_status": str(test_epoch_state.get("status") or ""),
        "test_started_at": str(test_epoch_state.get("test_started_at") or ""),
        "original_signal_created_at": original_created_at if rebuilt_after_epoch_activation else "",
        "realtime_rebuilt_after_epoch_activation": rebuilt_after_epoch_activation,
        "symbol": symbol,
        "timeframe": str(intent.get("timeframe") or ""),
        "direction": "long",
        "side": "buy",
        "order_type": order_type,
        "trigger_price": fmt_money(trigger) if trigger > ZERO else "",
        "limit_price": fmt_money(entry),
        "stop_price": fmt_money(stop),
        "target_price": fmt_money(target),
        "raw_suggested_quantity": fmt_decimal(quantity_normalization.raw_quantity),
        "submitted_quantity": fmt_decimal(quantity),
        "quantity_rounding_adjustment": fmt_decimal(quantity_normalization.rounded_down_quantity),
        "quantity_normalization_status": quantity_normalization.status,
        "quantity_normalization_blocker": quantity_normalization.blocker,
        "quantity": fmt_decimal(quantity),
        "risk_amount": fmt_money(risk_amount),
        "notional": fmt_money(notional),
        "current_price": fmt_money(current if current > ZERO else entry),
        "gross_profit_at_target": fmt_money(gross_profit),
        "estimated_entry_fees": fmt_money(config.commission_per_order_side),
        "estimated_exit_fees_at_target": fmt_money(config.commission_per_order_side),
        "estimated_regulatory_fees_at_target": fmt_money(config.regulatory_fee_per_sell_order),
        "net_profit_after_fees_at_target": fmt_money(net_profit),
        "profit_quality_gate": profit_gate_status,
        "reward_r": fmt_decimal(reward_r),
        "minimum_reward_r": fmt_decimal(minimum_reward_r),
        "minimum_net_profit_after_fees": fmt_money(minimum_net_profit),
        "bucket_max_total_exposure": fmt_money(base_total_exposure),
        "bucket_max_symbol_exposure": fmt_money(base_symbol_exposure),
        "bucket_max_risk_per_order": fmt_money(runtime_max_risk),
        "high_quality_signal": intent_is_high_quality(intent),
        "confluence_group_key": str(intent.get("confluence_group_key") or ""),
        "confluence_multiplier": fmt_decimal(confluence_boost),
        "confluence_support_count": str(intent.get("confluence_support_count") or "0"),
        "confluence_support_runtime_ids": list(intent.get("confluence_support_runtime_ids", []))
        if isinstance(intent.get("confluence_support_runtime_ids"), list)
        else [],
        "confluence_support_strategy_ids": list(intent.get("confluence_support_strategy_ids", []))
        if isinstance(intent.get("confluence_support_strategy_ids"), list)
        else [],
        "additional_bucket_route": bool(intent.get("additional_bucket_route", False)),
        "primary_capital_bucket": str(intent.get("primary_capital_bucket") or ""),
        "source_market_event_id": source_event_id,
        "market_event_time": str(intent.get("market_event_time") or ""),
        "signal_validity_seconds": str(intent.get("signal_validity_seconds") or "5"),
        "local_simulation_source": False,
        "fast_queue_source": False,
    }
    return row, signal


def strategy_isolation_blockers(runtime_id: str, strategy_id: str, allowed_runtime_ids: tuple[str, ...]) -> list[str]:
    lowered = runtime_id.lower()
    if runtime_id in REPAIR_RUNTIME_IDS:
        return ["blocked_repair_runtime_local_only"]
    if strategy_id in AUXILIARY_STRATEGY_IDS or runtime_id in AUXILIARY_STRATEGY_IDS:
        return ["blocked_auxiliary_module_local_only"]
    if runtime_id.startswith(tuple(AUXILIARY_STRATEGY_IDS)):
        return ["blocked_auxiliary_module_local_only"]
    loss_streak_allowed = runtime_id in LONG_BRIDGE_ALLOWED_LOSS_STREAK_RUNTIME_IDS and runtime_id in set(
        allowed_runtime_ids
    )
    shadow_allowed = runtime_id in LONG_BRIDGE_ALLOWED_SHADOW_RUNTIME_IDS and runtime_id in set(allowed_runtime_ids)
    if (
        not loss_streak_allowed
        and not shadow_allowed
        and any(marker in lowered for marker in SHADOW_RUNTIME_MARKERS)
    ) or ("-mbf" in lowered and not shadow_allowed):
        return ["blocked_shadow_runtime_local_only"]
    if runtime_id not in set(allowed_runtime_ids):
        return ["blocked_not_whitelisted_runtime"]
    return []


def normalize_direction(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "long", "open_long", "bullish", "看涨", "买入", "做多"}:
        return "long"
    if text in {"sell", "short", "sell_short", "bearish", "看跌", "卖出", "做空"}:
        return "short"
    return text or "unknown"


def normalize_order_type(value: Any) -> str:
    text = str(value or "limit").strip().lower().replace("-", "_")
    if text in {"stop_limit", "trigger_limit", "breakout_limit", "triggered_limit"}:
        return "trigger_limit"
    if text in {"limit", "limit_order"}:
        return "limit"
    return text


def deterministic_signal_id(runtime_id: str, symbol: str, source_event_id: str, created_at: str) -> str:
    digest = sha256(f"{runtime_id}|{symbol}|{source_event_id}|{created_at}".encode("utf-8")).hexdigest()[:16]
    return f"m15rt-{digest}"


def parse_optional_utc_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return parse_utc_datetime(value)
    except ValueError:
        return None


def parse_epoch_started_at(epoch_state: dict[str, Any]) -> datetime | None:
    if not isinstance(epoch_state, dict):
        return None
    if str(epoch_state.get("status") or "") != "active":
        return None
    return parse_optional_utc_datetime(str(epoch_state.get("test_started_at") or epoch_state.get("activated_at") or ""))


def count_blockers(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        blockers = row.get("blockers")
        if isinstance(blockers, list) and blockers:
            reason = str(blockers[0])
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def profit_quality_gate(
    config: RealtimeSignalRouterConfig,
    intent: dict[str, Any],
    net_profit: Decimal,
    runtime_id: str,
    strategy_id: str,
) -> str:
    if net_profit < runtime_minimum_net_profit(config, runtime_id, strategy_id):
        return "below_minimum"
    if net_profit < config.normal_minimum_net_profit_after_fees:
        if config.conditional_net_profit_requires_confluence and not (
            intent_has_confluence(intent) or intent_is_high_quality(intent)
        ):
            return "requires_confluence_or_quality"
        return "conditional_profit_with_confluence_or_quality"
    return "normal_profit"


def runtime_minimum_net_profit(config: RealtimeSignalRouterConfig, runtime_id: str, strategy_id: str) -> Decimal:
    for key in (runtime_id, strategy_id, parent_strategy_id(runtime_id), parent_strategy_id(strategy_id)):
        if key in config.runtime_minimum_net_profit_after_fees:
            return max(config.minimum_net_profit_after_fees, config.runtime_minimum_net_profit_after_fees[key])
    return max(config.minimum_net_profit_after_fees, config.normal_minimum_net_profit_after_fees)


def runtime_minimum_reward_r(config: RealtimeSignalRouterConfig, runtime_id: str, strategy_id: str) -> Decimal:
    for key in (runtime_id, strategy_id, parent_strategy_id(runtime_id), parent_strategy_id(strategy_id)):
        if key in config.runtime_minimum_reward_r:
            return max(config.minimum_reward_r, config.runtime_minimum_reward_r[key])
    return config.minimum_reward_r


def reward_r_ratio(entry: Decimal, stop: Decimal, target: Decimal) -> Decimal:
    risk = entry - stop
    reward = target - entry
    if risk <= ZERO or reward <= ZERO:
        return ZERO
    return reward / risk


def intent_has_confluence(intent: dict[str, Any]) -> bool:
    support_count = int_decimal(intent.get("confluence_support_count", "0"))
    multiplier = decimal(intent.get("confluence_multiplier", "1"))
    status = str(intent.get("confluence_status") or intent.get("confluence_role") or "").lower()
    return support_count > 0 or multiplier > Decimal("1") or "confluence" in status


def intent_is_high_quality(intent: dict[str, Any]) -> bool:
    if intent.get("high_quality_signal") is True:
        return True
    for key in ("quality_tier", "signal_quality", "quality_label"):
        value = str(intent.get(key) or "").strip().lower()
        if value in {"high", "strong", "excellent", "高质量", "强"}:
            return True
    score = decimal(intent.get("quality_score", intent.get("signal_quality_score", "0")))
    return score >= Decimal("0.8")


def int_decimal(value: Any) -> int:
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return 0


def plain_language_result(market_event_count: int, new_signal_count: int, rows: list[dict[str, Any]]) -> str:
    if new_signal_count:
        return f"实时信号路由器从 {market_event_count} 条行情事件生成 {new_signal_count} 条长桥实时信号；没有读取本地模拟账本。"
    if rows:
        return f"实时信号路由器处理了 {market_event_count} 条行情事件，但全部被策略隔离或风控挡住；没有读取本地模拟账本。"
    return "实时信号路由器已就绪；当前没有新的行情事件。"


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]], signals: list[dict[str, Any]]) -> str:
    lines = [
        "# 长桥模拟账户实时信号路由器",
        "",
        f"- 生成时间: `{summary['generated_at']}`",
        f"- 行情事件数: `{summary['market_event_count']}`",
        f"- 新增长桥实时信号: `{summary['new_signal_event_count']}`",
        f"- 本地模拟隔离: `{summary['local_simulation_isolated']}`",
        f"- 结论: {summary['plain_language_result']}",
        "",
        "## 新信号",
        "",
        "| 信号 | 运行单元 | 标的 | 数量 | 限价 | 止损 | 目标 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for signal in signals[:30]:
        lines.append(
            f"| `{signal['signal_id']}` | `{signal['runtime_id']}` | `{signal['symbol']}` | "
            f"`{signal['quantity']}` | `{signal['limit_price']}` | `{signal['stop_price']}` | `{signal['target_price']}` |"
        )
    lines.extend(["", "## 路由决策", "", "| 运行单元 | 标的 | 状态 | 原因 |", "|---|---:|---|---|"])
    for row in rows[:50]:
        blockers = ",".join(str(item) for item in row.get("blockers", []))
        lines.append(f"| `{row.get('runtime_id', '')}` | `{row.get('symbol', '')}` | `{row.get('router_decision_status', '')}` | {blockers} |")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 输入只允许实时行情/新K线事件，不读取本地模拟开仓、平仓或账本。",
            "- 修复策略、影子变体和辅助模块在信号生成阶段直接隔离。",
            "- 输出只进入长桥模拟账户实时执行链路；旧快速队列只作审计。",
            "",
        ]
    )
    return "\n".join(lines)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(json_ready(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        "".join(json.dumps(json_ready(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return fmt_decimal(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [json_ready(item) for item in value]
    return value


def decimal_or_zero(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO
