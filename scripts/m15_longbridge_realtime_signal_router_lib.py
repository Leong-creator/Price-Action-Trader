#!/usr/bin/env python3
from __future__ import annotations

import json
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
    REPAIR_RUNTIME_IDS,
    SHADOW_RUNTIME_MARKERS,
    decimal,
    fmt_decimal,
    fmt_money,
    parent_strategy_id,
    parse_utc_datetime,
    resolve_session_started_at,
    session_start_is_auto,
    to_iso,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_signal_router.json"
DEFAULT_MARKET_EVENTS = DEFAULT_OUTPUT_DIR / "m15_realtime_market_events.jsonl"
DEFAULT_SIGNAL_EVENTS = DEFAULT_OUTPUT_DIR / "m15_realtime_signal_events.jsonl"
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
}


@dataclass(frozen=True, slots=True)
class RealtimeSignalRouterConfig:
    stage: str
    title: str
    market_events_path: Path
    signal_events_path: Path
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
    commission_per_order_side: Decimal
    regulatory_fee_per_sell_order: Decimal
    runtime_position_multipliers: dict[str, Decimal]
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
    return RealtimeSignalRouterConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_signal_router")),
        title=str(payload.get("title", "长桥模拟账户实时信号路由器")),
        market_events_path=resolve_repo_path(inputs.get("market_events", DEFAULT_MARKET_EVENTS)),
        signal_events_path=resolve_repo_path(inputs.get("signal_events", DEFAULT_SIGNAL_EVENTS)),
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
        minimum_net_profit_after_fees=decimal(account_model.get("minimum_net_profit_after_fees", "0")),
        commission_per_order_side=decimal(fee_model.get("commission_per_order_side", "1.99")),
        regulatory_fee_per_sell_order=decimal(fee_model.get("regulatory_fee_per_sell_order", "0.02")),
        runtime_position_multipliers={
            str(key): decimal(value)
            for key, value in dict(router.get("runtime_position_multipliers", {})).items()
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
    if config.max_signal_events_per_run <= 0:
        raise ValueError("M15 realtime signal router max_signal_events_per_run must be positive")
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
    market_events = read_jsonl(config.market_events_path)
    existing_signal_events = read_jsonl(config.signal_events_path)
    existing_signal_ids = {str(row.get("signal_id")) for row in existing_signal_events if row.get("signal_id")}
    ledger_rows: list[dict[str, Any]] = []
    new_signal_events: list[dict[str, Any]] = []
    selected_total_exposure = ZERO
    selected_symbol_exposure: dict[str, Decimal] = defaultdict(lambda: ZERO)

    raw_intents = embedded_signal_intents(config, market_events)
    raw_intents.extend(detector_signal_candidates(config, market_events, generated_at=now))
    routed_intents, merged_support_intents = merge_confluence_intents(config, raw_intents)
    for support_intent in merged_support_intents:
        row, _signal = build_signal_from_intent(
            config=config,
            intent=support_intent,
            generated_at=now,
            session_started_at=session_started_at,
            existing_signal_ids=existing_signal_ids,
            selected_total_exposure=selected_total_exposure,
            selected_symbol_exposure=selected_symbol_exposure,
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
            existing_signal_ids=existing_signal_ids,
            selected_total_exposure=selected_total_exposure,
            selected_symbol_exposure=selected_symbol_exposure,
        )
        ledger_rows.append(row)
        if signal and len(new_signal_events) < config.max_signal_events_per_run:
            new_signal_events.append(signal)
            existing_signal_ids.add(signal["signal_id"])
            selected_total_exposure += decimal(signal.get("notional", "0"))
            selected_symbol_exposure[str(signal["symbol"])] += decimal(signal.get("notional", "0"))

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
        "market_event_count": len(market_events),
        "embedded_intent_count": sum(len(event_intents(row)) for row in market_events),
        "router_decision_count": len(ledger_rows),
        "new_signal_event_count": len(new_signal_events),
        "existing_signal_event_count": len(existing_signal_events),
        "signal_event_total_count": len(existing_signal_events) + len(new_signal_events),
        "confluence_primary_count": sum(1 for intent in routed_intents if decimal(intent.get("confluence_multiplier", "1")) > Decimal("1")),
        "confluence_merged_support_count": len(merged_support_intents),
        "blocked_by_reason": count_blockers(ledger_rows),
        "enabled_detectors": list(config.enabled_detectors),
        "allowed_runtime_ids": list(config.allowed_runtime_ids),
        "session_started_at": session_started_at,
        "inputs": {
            "market_events": project_path(config.market_events_path),
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
        if not confluence_eligible(config, intent):
            passthrough.append(intent)
            continue
        grouped[confluence_key(intent)].append(intent)
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


def confluence_eligible(config: RealtimeSignalRouterConfig, intent: dict[str, Any]) -> bool:
    runtime_id = str(intent.get("runtime_id") or "")
    strategy_id = str(intent.get("strategy_id") or parent_strategy_id(runtime_id))
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
    symbol = str(intent.get("symbol") or "").upper()
    direction = normalize_direction(intent.get("direction") or intent.get("side"))
    side = "buy" if direction == "long" else "sell_short"
    date_key = ny_date_from_intent(intent)
    return f"{date_key}|{symbol}|{direction}|{side}"


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
    existing_signal_ids: set[str],
    selected_total_exposure: Decimal,
    selected_symbol_exposure: dict[str, Decimal],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    runtime_id = str(intent.get("runtime_id") or "")
    strategy_id = str(intent.get("strategy_id") or parent_strategy_id(runtime_id))
    symbol = str(intent.get("symbol") or "").upper()
    created_at = str(intent.get("created_at") or to_iso(generated_at))
    source_event_id = str(intent.get("source_market_event_id") or intent.get("market_event_id") or "")
    signal_id = str(intent.get("signal_id") or deterministic_signal_id(runtime_id, symbol, source_event_id, created_at))
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
    if not symbol:
        blockers.append("missing_symbol")
    if signal_id in existing_signal_ids:
        blockers.append("duplicate_signal_event")
    try:
        if parse_utc_datetime(created_at) < parse_utc_datetime(session_started_at):
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
    quantity = decimal(intent.get("quantity", "0"))
    multiplier = config.runtime_position_multipliers.get(runtime_id, Decimal("1.0"))
    confluence_boost = decimal(intent.get("confluence_multiplier", "1"))
    runtime_max_exposure = min(config.max_symbol_exposure, config.max_symbol_exposure * multiplier * confluence_boost)
    runtime_max_risk = min(config.max_risk_per_order, config.max_risk_per_order * multiplier * confluence_boost)
    if quantity <= ZERO and entry > ZERO and risk_per_share > ZERO:
        exposure_qty = (runtime_max_exposure / entry).to_integral_value(rounding=ROUND_FLOOR)
        risk_qty = (runtime_max_risk / risk_per_share).to_integral_value(rounding=ROUND_FLOOR)
        quantity = max(min(exposure_qty, risk_qty), ZERO)
    if not config.allow_fractional_shares and quantity != quantity.to_integral_value():
        blockers.append("blocked_fractional_disabled")
    if quantity < Decimal("1"):
        blockers.append("blocked_quantity_below_one_share")
    notional = entry * quantity
    risk_amount = risk_per_share * quantity
    gross_profit = (target - entry) * quantity
    fees = config.commission_per_order_side * Decimal("2") + config.regulatory_fee_per_sell_order
    net_profit = gross_profit - fees
    if risk_amount > config.max_risk_per_order:
        blockers.append("blocked_risk_over_cap")
    if notional > config.max_symbol_exposure or selected_symbol_exposure.get(symbol, ZERO) + notional > config.max_symbol_exposure:
        blockers.append("blocked_symbol_exposure_over_cap")
    if selected_total_exposure + notional > config.max_total_exposure:
        blockers.append("blocked_total_exposure_over_cap")
    if net_profit <= config.minimum_net_profit_after_fees:
        blockers.append("blocked_fee_profit_not_positive")
    status = "signal_event_ready" if not blockers else blockers[0]
    row = {
        "stage": config.stage,
        "signal_id": signal_id,
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "timeframe": str(intent.get("timeframe") or ""),
        "source_market_event_id": source_event_id,
        "created_at": created_at,
        "processed_at": to_iso(generated_at),
        "detector_id": str(intent.get("detector_id") or "embedded_signal_intent"),
        "router_decision_status": status,
        "blockers": blockers,
        "quantity": fmt_decimal(quantity),
        "limit_price": fmt_money(entry) if entry > ZERO else "",
        "stop_price": fmt_money(stop) if stop > ZERO else "",
        "target_price": fmt_money(target) if target > ZERO else "",
        "risk_amount": fmt_money(risk_amount),
        "notional": fmt_money(notional),
        "net_profit_after_fees_at_target": fmt_money(net_profit),
        "confluence_group_key": str(intent.get("confluence_group_key") or ""),
        "confluence_multiplier": fmt_decimal(confluence_boost),
        "confluence_support_count": str(intent.get("confluence_support_count") or "0"),
        "confluence_support_runtime_ids": list(intent.get("confluence_support_runtime_ids", []))
        if isinstance(intent.get("confluence_support_runtime_ids"), list)
        else [],
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
        "symbol": symbol,
        "timeframe": str(intent.get("timeframe") or ""),
        "direction": "long",
        "side": "buy",
        "order_type": order_type,
        "trigger_price": fmt_money(trigger) if trigger > ZERO else "",
        "limit_price": fmt_money(entry),
        "stop_price": fmt_money(stop),
        "target_price": fmt_money(target),
        "quantity": fmt_decimal(quantity),
        "risk_amount": fmt_money(risk_amount),
        "notional": fmt_money(notional),
        "current_price": fmt_money(current if current > ZERO else entry),
        "gross_profit_at_target": fmt_money(gross_profit),
        "estimated_entry_fees": fmt_money(config.commission_per_order_side),
        "estimated_exit_fees_at_target": fmt_money(config.commission_per_order_side),
        "estimated_regulatory_fees_at_target": fmt_money(config.regulatory_fee_per_sell_order),
        "net_profit_after_fees_at_target": fmt_money(net_profit),
        "confluence_group_key": str(intent.get("confluence_group_key") or ""),
        "confluence_multiplier": fmt_decimal(confluence_boost),
        "confluence_support_count": str(intent.get("confluence_support_count") or "0"),
        "confluence_support_runtime_ids": list(intent.get("confluence_support_runtime_ids", []))
        if isinstance(intent.get("confluence_support_runtime_ids"), list)
        else [],
        "confluence_support_strategy_ids": list(intent.get("confluence_support_strategy_ids", []))
        if isinstance(intent.get("confluence_support_strategy_ids"), list)
        else [],
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
    if any(marker in lowered for marker in SHADOW_RUNTIME_MARKERS) or "-mbf" in lowered:
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


def count_blockers(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        blockers = row.get("blockers")
        if isinstance(blockers, list) and blockers:
            reason = str(blockers[0])
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


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
    path.write_text(json.dumps(json_ready(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(json_ready(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


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
