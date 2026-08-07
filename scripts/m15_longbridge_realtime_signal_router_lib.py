#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
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
    LONG_BRIDGE_ALLOWED_REPAIR_RUNTIME_IDS,
    LONG_BRIDGE_ALLOWED_SHADOW_RUNTIME_IDS,
    PAPER_SHORT_RUNTIME_IDS,
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
from scripts.m15_full_strategy_detectors_lib import (
    pa001_daily_long,
    pa002_five_minute_long,
    pa012_five_minute_long,
)
from scripts.m15_strategy_contracts_lib import load_contracts_cached


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_signal_router.json"
DEFAULT_MARKET_EVENTS = DEFAULT_OUTPUT_DIR / "m15_realtime_market_events.jsonl"
DEFAULT_SIGNAL_EVENTS = DEFAULT_OUTPUT_DIR / "m15_realtime_signal_events.jsonl"
DEFAULT_EPOCH_STATE = DEFAULT_OUTPUT_DIR / "m15_longbridge_virtual_account_epoch.json"
SUMMARY_JSON = "m15_longbridge_realtime_signal_router.json"
LEDGER_JSONL = "m15_longbridge_realtime_signal_router_ledger.jsonl"
REPORT_MD = "m15_longbridge_realtime_signal_router.md"
SHORT_DIAGNOSTICS_JSON = "m15_longbridge_short_signal_diagnostics.json"
SHORT_DIAGNOSTIC_ROW_LIMIT = 2000
STRATEGY_DIAGNOSTICS_JSON = "m15_longbridge_strategy_signal_diagnostics.json"
STRATEGY_DIAGNOSTIC_ROW_LIMIT = 10000
ZERO = Decimal("0")
HUNDRED = Decimal("100")
CONFLUENCE_MAX_MULTIPLIER = Decimal("1.75")
NEW_YORK = ZoneInfo("America/New_York")
PRICE_ACTION_REALTIME_DETECTOR = "price_action_realtime_v1"
SEMICONDUCTOR_RELATIVE_STRENGTH_SYMBOLS = {
    "AMD",
    "AMAT",
    "ARM",
    "ASML",
    "AVGO",
    "INTC",
    "KLAC",
    "LRCX",
    "MCHP",
    "MPWR",
    "MRVL",
    "MU",
    "NVDA",
    "NXPI",
    "ON",
    "QCOM",
    "SMH",
    "SOXX",
    "TSM",
    "TXN",
}
PRICE_ACTION_RUNTIME_SPECS = {
    "M10-PA-001-1d": {
        "strategy_id": "M10-PA-001",
        "timeframe": "1d",
        "rule": "pa001_daily_contract_v1",
        "target_r": Decimal("2.00"),
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
        "rule": "pa002_5m_contract_v1",
        "target_r": Decimal("2.00"),
        "min_close_position": Decimal("0.60"),
        "max_risk_percent": Decimal("2.50"),
    },
    "M10-PA-002-5m-repaired-v1": {
        "strategy_id": "M10-PA-002",
        "timeframe": "5m",
        "rule": "breakout_followthrough_repair",
        "target_r": Decimal("1.30"),
        "min_close_position": Decimal("0.60"),
        "max_risk_percent": Decimal("2.50"),
        "require_latest_confirms_entry": True,
        "cooldown_after_losses": 2,
        "next_market_day_timeout": True,
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
        "rule": "pa012_5m_contract_v1",
        "target_r": Decimal("2.00"),
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
        "min_close_position": Decimal("0.70"),
        "min_close_to_close_percent": Decimal("1.70"),
        "min_volume_ratio": Decimal("1.15"),
        "require_market_confirmation": True,
        "max_risk_percent": Decimal("6.00"),
    },
    "M12-FTD-001-loss-streak-guard-1d": {
        "strategy_id": "M12-FTD-001",
        "timeframe": "1d",
        "rule": "follow_through_day",
        "target_r": Decimal("1.50"),
        "min_close_position": Decimal("0.75"),
        "min_close_to_close_percent": Decimal("2.00"),
        "min_volume_ratio": Decimal("1.25"),
        "require_market_confirmation": True,
        "max_risk_percent": Decimal("6.00"),
    },
    "M12-FTD-001-pullback-guard-confirm-1d": {
        "strategy_id": "M12-FTD-001",
        "timeframe": "1d",
        "rule": "ftd_pullback_guard_confirm_v1",
        "target_r": Decimal("2.00"),
        "max_pullback_bars": 20,
        "follow_through_window_bars": 2,
        "max_risk_percent": Decimal("6.00"),
    },
    "M10-PA-002-5m-short": {
        "strategy_id": "M10-PA-002",
        "timeframe": "5m",
        "rule": "bearish_breakdown",
        "target_r": Decimal("2.00"),
        "max_risk_percent": Decimal("1.50"),
        "max_close_position": Decimal("0.25"),
        "max_close_to_close_percent": Decimal("-0.60"),
        "min_volume_ratio": Decimal("1.30"),
        "minimum_net_profit_after_fees": Decimal("12"),
        "minimum_reward_r": Decimal("2.00"),
        "minimum_quality_score": Decimal("85"),
        "market_confirmation_requirement": "either",
    },
    "M10-PA-013-5m-short": {
        "strategy_id": "M10-PA-013",
        "timeframe": "5m",
        "rule": "bearish_false_breakout",
        "target_r": Decimal("2.00"),
        "max_risk_percent": Decimal("1.50"),
        "max_close_position": Decimal("0.30"),
        "max_close_to_close_percent": Decimal("-0.50"),
        "min_volume_ratio": Decimal("1.20"),
        "minimum_net_profit_after_fees": Decimal("12"),
        "minimum_reward_r": Decimal("2.00"),
        "minimum_quality_score": Decimal("85"),
        "market_confirmation_requirement": "either",
    },
    "M10-PA-011-ORB-R1-5m-short": {
        "strategy_id": "M10-PA-011",
        "timeframe": "5m",
        "rule": "opening_range_breakdown",
        "target_r": Decimal("2.25"),
        "max_risk_percent": Decimal("1.25"),
        "max_close_position": Decimal("0.20"),
        "max_close_to_close_percent": Decimal("-0.75"),
        "min_volume_ratio": Decimal("1.50"),
        "minimum_net_profit_after_fees": Decimal("15"),
        "minimum_reward_r": Decimal("2.25"),
        "minimum_quality_score": Decimal("90"),
        "market_confirmation_requirement": "both",
    },
}


@dataclass(frozen=True, slots=True)
class RealtimeSignalRouterConfig:
    stage: str
    title: str
    market_events_path: Path
    signal_events_path: Path
    test_epoch_state_path: Path
    capital_bucket_migration_state_path: Path | None
    output_dir: Path
    session_started_at: str
    allowed_runtime_ids: tuple[str, ...]
    enabled_detectors: tuple[str, ...]
    max_signal_events_per_run: int
    max_market_event_rows_per_hot_run: int
    paper_short_testing_enabled: bool
    paper_short_runtime_ids: tuple[str, ...]
    short_test_epoch_id: str
    short_test_started_at: str
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
    strategy_contracts_dir: Path
    require_strategy_contracts: bool
    auxiliary_modules_contract_path: Path | None
    hard_boundaries: dict[str, bool]

    def __post_init__(self) -> None:
        validate_config(self)


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    absolute = path if path.is_absolute() else ROOT / path
    try:
        return absolute.relative_to(ROOT).as_posix()
    except ValueError:
        return str(absolute)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RealtimeSignalRouterConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    router = payload.get("realtime_signal_router", {})
    strategy_contracts = payload.get("strategy_contracts", {})
    account_model = payload.get("paper_account_model", {})
    short_testing = payload.get("paper_short_testing", {})
    fee_model = payload.get("fee_model", {})
    virtual_buckets, runtime_bucket_map = parse_virtual_capital_buckets(payload, account_model)
    return RealtimeSignalRouterConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_signal_router")),
        title=str(payload.get("title", "长桥模拟账户实时信号路由器")),
        market_events_path=resolve_repo_path(inputs.get("market_events", DEFAULT_MARKET_EVENTS)),
        signal_events_path=resolve_repo_path(inputs.get("signal_events", DEFAULT_SIGNAL_EVENTS)),
        test_epoch_state_path=resolve_repo_path(inputs.get("test_epoch_state", DEFAULT_EPOCH_STATE)),
        capital_bucket_migration_state_path=(
            resolve_repo_path(inputs["capital_bucket_migration_state"])
            if inputs.get("capital_bucket_migration_state")
            else None
        ),
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
        max_market_event_rows_per_hot_run=int(router.get("max_market_event_rows_per_hot_run", 4096)),
        paper_short_testing_enabled=bool(short_testing.get("enabled", False)),
        paper_short_runtime_ids=tuple(str(item) for item in short_testing.get("runtime_ids", []) if str(item)),
        short_test_epoch_id=str(short_testing.get("test_epoch_id") or ""),
        short_test_started_at=str(short_testing.get("test_started_at") or ""),
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
        strategy_contracts_dir=resolve_repo_path(
            strategy_contracts.get("directory", "config/m15_strategy_contracts")
        ),
        require_strategy_contracts=bool(strategy_contracts.get("required", False)),
        auxiliary_modules_contract_path=(
            resolve_repo_path(payload["auxiliary_modules_contract"])
            if payload.get("auxiliary_modules_contract")
            else None
        ),
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
    if config.max_market_event_rows_per_hot_run <= 0:
        raise ValueError("M15 realtime signal router market event hot window must be positive")
    if config.normal_minimum_net_profit_after_fees < config.minimum_net_profit_after_fees:
        raise ValueError("M15 realtime signal router normal profit threshold must be >= minimum threshold")
    if config.minimum_reward_r < ZERO:
        raise ValueError("M15 realtime signal router minimum reward/R cannot be negative")
    if config.allow_fractional_shares:
        raise ValueError("M15 realtime signal router forbids fractional shares")
    if config.allow_short_selling:
        if not config.paper_short_testing_enabled:
            raise ValueError("M15 realtime signal router short selling needs explicit paper_short_testing.enabled")
        if not config.paper_short_runtime_ids:
            raise ValueError("M15 realtime signal router short selling needs an explicit runtime whitelist")
        if not config.short_test_epoch_id or not config.short_test_started_at:
            raise ValueError("M15 realtime signal router short selling needs an independent short test epoch")
        parse_utc_datetime(config.short_test_started_at)
        invalid_short_runtimes = set(config.paper_short_runtime_ids) - set(PAPER_SHORT_RUNTIME_IDS)
        if invalid_short_runtimes:
            raise ValueError(
                "M15 realtime signal router short runtime is not approved: "
                f"{sorted(invalid_short_runtimes)}"
            )
        if not set(config.paper_short_runtime_ids).issubset(set(config.allowed_runtime_ids)):
            raise ValueError("M15 realtime signal router short runtime is not in the main whitelist")
        for runtime_id in config.paper_short_runtime_ids:
            bucket_id = config.runtime_capital_bucket_map.get(runtime_id, "")
            bucket = config.virtual_capital_buckets.get(bucket_id)
            if bucket is None or bucket.position_direction != "short":
                raise ValueError(f"M15 realtime signal router short runtime missing short bucket: {runtime_id}")
        if config.hard_boundaries.get("short_selling") is not True:
            raise ValueError("M15 realtime signal router short selling needs paper-only boundary")
    elif config.paper_short_testing_enabled or config.paper_short_runtime_ids:
        raise ValueError("M15 realtime signal router short test configuration requires allow_short_selling")
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
    if config.require_strategy_contracts:
        contracts = load_contracts_cached(str(config.strategy_contracts_dir))
        missing = set(config.allowed_runtime_ids) - set(contracts)
        if missing:
            raise ValueError(f"M15 realtime signal router runtime contract missing: {sorted(missing)}")
        non_executable = {
            runtime_id: contracts[runtime_id]["stage"]
            for runtime_id in config.allowed_runtime_ids
            if contracts[runtime_id]["stage"] not in {"paper-v1", "full-v1"}
        }
        if non_executable:
            raise ValueError(f"M15 realtime signal router contract is not executable: {non_executable}")
        validate_auxiliary_modules_contract(config.auxiliary_modules_contract_path)


def validate_auxiliary_modules_contract(path: Path | None) -> None:
    if path is None or not path.exists():
        raise ValueError("M15 realtime signal router requires auxiliary modules contract")
    payload = read_json(path)
    if payload.get("schema_version") != "m15-auxiliary-modules-contract-v1":
        raise ValueError("M15 auxiliary modules contract schema drift")
    modules = payload.get("modules")
    if not isinstance(modules, dict):
        raise ValueError("M15 auxiliary modules contract modules missing")
    required = {"M10-PA-003", "M10-PA-006", "M10-PA-010", "M10-PA-014", "M10-PA-015", "M10-PA-016"}
    if not required.issubset(modules):
        raise ValueError("M15 auxiliary modules contract is incomplete")
    if any(row.get("standalone_order_generation") is not False for row in modules.values() if isinstance(row, dict)):
        raise ValueError("M15 auxiliary module cannot generate standalone orders")
    if modules["M10-PA-015"].get("mode") != "mandatory":
        raise ValueError("M15 PA015 risk capability must remain mandatory")
    if modules["M10-PA-016"].get("mode") != "disabled":
        raise ValueError("M15 PA016 scaling capability must remain disabled")


def load_capital_bucket_migration_state(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    payload = read_json(path)
    states: dict[str, str] = {}
    candidates: list[dict[str, Any]] = []
    if isinstance(payload.get("capital_bucket_states"), dict):
        for bucket_id, row in dict(payload["capital_bucket_states"]).items():
            if isinstance(row, dict):
                candidates.append({"capital_bucket": bucket_id, **row})
            else:
                candidates.append({"capital_bucket": bucket_id, "status": row})
    if isinstance(payload.get("capital_buckets"), dict):
        for bucket_id, row in dict(payload["capital_buckets"]).items():
            if isinstance(row, dict):
                candidates.append({"capital_bucket": bucket_id, **row})
            else:
                candidates.append({"capital_bucket": bucket_id, "status": row})
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else payload.get("items")
    if isinstance(rows, list):
        candidates.extend(row for row in rows if isinstance(row, dict))
    for row in candidates:
        bucket_id = str(row.get("capital_bucket") or row.get("bucket_id") or "").strip()
        status = str(row.get("migration_status") or row.get("status") or row.get("state") or "").strip()
        if bucket_id and status:
            states[bucket_id] = status
    return states


def annotate_relative_strengths(
    market_events: list[dict[str, Any]],
    intents: list[dict[str, Any]],
) -> None:
    if not intents or not market_events:
        return
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    event_index: dict[str, dict[str, Any]] = {}
    for row in market_events:
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        event_id = str(row.get("event_id") or row.get("market_event_id") or "")
        if symbol and timeframe:
            grouped[(symbol, timeframe)].append(row)
        if event_id:
            event_index[event_id] = row
    for rows in grouped.values():
        rows.sort(key=market_event_sort_key)
    for intent in intents:
        metrics = relative_strength_metrics(intent, grouped, event_index)
        intent.update(metrics)


def relative_strength_metrics(
    intent: dict[str, Any],
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    event_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    symbol = str(intent.get("symbol") or "").upper()
    timeframe = str(intent.get("timeframe") or "")
    source_event_id = str(intent.get("source_market_event_id") or intent.get("market_event_id") or "")
    symbol_rows = grouped_events.get((symbol, timeframe), [])
    latest = event_index.get(source_event_id) if source_event_id else None
    if latest is None and symbol_rows:
        latest = symbol_rows[-1]
    candidate_return = relative_strength_return(symbol_rows, latest)
    market_returns = [
        benchmark_return(grouped_events, benchmark, timeframe, latest)
        for benchmark in ("SPY", "QQQ")
    ]
    market_values = [value for value in market_returns if value is not None]
    market_strength = average_decimal(market_values)
    sector_applicable = symbol in SEMICONDUCTOR_RELATIVE_STRENGTH_SYMBOLS
    sector_returns = [
        benchmark_return(grouped_events, benchmark, timeframe, latest)
        for benchmark in ("SMH", "SOXX")
    ] if sector_applicable else []
    sector_values = [value for value in sector_returns if value is not None]
    sector_strength = average_decimal(sector_values)
    stock_vs_market = candidate_return - market_strength if candidate_return is not None and market_strength is not None else None
    stock_vs_sector = candidate_return - sector_strength if candidate_return is not None and sector_strength is not None else None
    rank_score = ZERO
    if stock_vs_market is not None:
        rank_score += stock_vs_market
    if sector_strength is not None:
        rank_score += sector_strength / Decimal("2")
    if stock_vs_sector is not None:
        rank_score += stock_vs_sector / Decimal("2")
    audit_state = "complete" if stock_vs_market is not None and (sector_applicable is False or stock_vs_sector is not None) else "partial"
    return {
        "market_relative_strength_percent": fmt_decimal(stock_vs_market) if stock_vs_market is not None else "",
        "market_strength_percent": fmt_decimal(market_strength) if market_strength is not None else "",
        "sector_relative_strength_percent": fmt_decimal(stock_vs_sector) if stock_vs_sector is not None else "",
        "sector_strength_percent": fmt_decimal(sector_strength) if sector_strength is not None else "",
        "candidate_return_percent": fmt_decimal(candidate_return) if candidate_return is not None else "",
        "relative_strength_rank_score": fmt_decimal(rank_score),
        "relative_strength_audit_state": audit_state,
        "industry_strength_scope": "semiconductor" if sector_applicable else "market_only",
    }


def benchmark_return(
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    symbol: str,
    timeframe: str,
    target_row: dict[str, Any] | None,
) -> Decimal | None:
    rows = grouped_events.get((symbol, timeframe), [])
    return relative_strength_return(rows, target_row)


def relative_strength_return(
    rows: list[dict[str, Any]],
    target_row: dict[str, Any] | None,
) -> Decimal | None:
    if len(rows) < 2:
        return None
    latest_index = len(rows) - 1
    if target_row is not None:
        target_date = ny_event_date(target_row)
        target_time = parse_optional_utc_datetime(
            str(target_row.get("event_time") or target_row.get("bar_time") or target_row.get("timestamp") or "")
        )
        matched_index: int | None = None
        for index in range(len(rows) - 1, -1, -1):
            row = rows[index]
            if target_date and ny_event_date(row) != target_date:
                continue
            row_time = parse_optional_utc_datetime(
                str(row.get("event_time") or row.get("bar_time") or row.get("timestamp") or "")
            )
            if target_time and row_time and abs((row_time - target_time).total_seconds()) > 600:
                continue
            matched_index = index
            break
        if matched_index is not None:
            latest_index = matched_index
    if latest_index <= 0:
        return None
    return row_close_to_close_percent(rows[latest_index - 1], rows[latest_index])


def average_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def run_realtime_signal_router(
    config: RealtimeSignalRouterConfig | None = None,
    *,
    generated_at: str | None = None,
    market_events_override: list[dict[str, Any]] | None = None,
    active_market_event_ids: set[str] | None = None,
    emitted_signal_events: list[dict[str, Any]] | None = None,
    existing_signal_ids_override: set[str] | None = None,
    existing_structure_ids_override: set[str] | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    session_started_at = resolve_session_started_at(config.session_started_at, now)
    raw_market_events = (
        list(market_events_override)
        if market_events_override is not None
        else read_jsonl_tail(config.market_events_path, config.max_market_event_rows_per_hot_run)
    )
    market_events = realtime_relevant_market_events(raw_market_events, session_started_at)
    existing_signal_events = (
        []
        if existing_signal_ids_override is not None
        else read_jsonl(config.signal_events_path)
    )
    existing_signal_ids = (
        set(existing_signal_ids_override)
        if existing_signal_ids_override is not None
        else {
            str(row.get("signal_id"))
            for row in existing_signal_events
            if row.get("signal_id")
        }
    )
    existing_signal_event_count = len(existing_signal_ids)
    existing_structure_ids = (
        set(existing_structure_ids_override)
        if existing_structure_ids_override is not None
        else {
            str(row.get("structure_instance_id") or "")
            for row in existing_signal_events
            if str(row.get("structure_instance_id") or "")
        }
    )
    test_epoch_state = normalize_active_epoch_state(read_json(config.test_epoch_state_path))
    previous_summary = read_json(config.output_dir / SUMMARY_JSON)
    previous_daily_structure_state = (
        previous_summary.get("daily_structure_episode_state", {})
        if isinstance(previous_summary.get("daily_structure_episode_state"), dict)
        else {}
    )
    capital_bucket_migration_state = load_capital_bucket_migration_state(
        config.capital_bucket_migration_state_path
    )
    ledger_rows: list[dict[str, Any]] = []
    new_signal_events: list[dict[str, Any]] = []
    selected_bucket_exposure: dict[str, Decimal] = defaultdict(lambda: ZERO)
    selected_bucket_symbol_exposure: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)

    detector_attempts: list[dict[str, Any]] = []
    raw_intents = embedded_signal_intents(config, market_events)
    raw_intents.extend(
        detector_signal_candidates(
            config,
            market_events,
            generated_at=now,
            detector_attempts=detector_attempts,
        )
    )
    annotate_strategy_contracts(config, raw_intents)
    if active_market_event_ids is not None:
        raw_intents = [
            intent
            for intent in raw_intents
            if str(intent.get("source_market_event_id") or intent.get("market_event_id") or "")
            in active_market_event_ids
        ]
    daily_structure_episode_state = assign_daily_structure_episode_ids(
        raw_intents,
        detector_attempts,
        previous_daily_structure_state,
        generated_at=now,
        long_test_epoch_id=str(test_epoch_state.get("test_epoch_id") or ""),
        short_test_epoch_id=config.short_test_epoch_id,
        active_market_event_ids=active_market_event_ids,
    )
    raw_intents = expand_additional_bucket_routes(config, raw_intents)
    routed_intents, merged_support_intents = merge_confluence_intents(config, raw_intents)
    annotate_relative_strengths(market_events, routed_intents)
    annotate_relative_strengths(market_events, merged_support_intents)
    routed_intents = sorted(routed_intents, key=realtime_intent_sort_key)
    for support_intent in merged_support_intents:
        row, _signal = build_signal_from_intent(
            config=config,
            intent=support_intent,
            generated_at=now,
            session_started_at=session_started_at,
            test_epoch_state=test_epoch_state,
            capital_bucket_migration_state=capital_bucket_migration_state,
            existing_signal_ids=existing_signal_ids,
            existing_structure_ids=existing_structure_ids,
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
            capital_bucket_migration_state=capital_bucket_migration_state,
            existing_signal_ids=existing_signal_ids,
            existing_structure_ids=existing_structure_ids,
            selected_bucket_exposure=selected_bucket_exposure,
            selected_bucket_symbol_exposure=selected_bucket_symbol_exposure,
        )
        ledger_rows.append(row)
        if signal and len(new_signal_events) < config.max_signal_events_per_run:
            new_signal_events.append(signal)
            existing_signal_ids.add(signal["signal_id"])
            structure_instance_id = str(signal.get("structure_instance_id") or "")
            if structure_instance_id:
                existing_structure_ids.add(structure_instance_id)
            bucket_id = str(signal.get("capital_bucket") or "")
            symbol = str(signal["symbol"])
            selected_bucket_exposure[bucket_id] += decimal(signal.get("notional", "0"))
            selected_bucket_symbol_exposure[(bucket_id, symbol)] += decimal(signal.get("notional", "0"))

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.signal_events_path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(config.signal_events_path, new_signal_events)
    write_jsonl(config.output_dir / LEDGER_JSONL, ledger_rows)
    short_diagnostics = update_short_signal_diagnostics(
        config,
        ledger_rows,
        generated_at_iso,
        detector_attempts=[
            row for row in detector_attempts
            if str(row.get("runtime_id") or "") in set(config.paper_short_runtime_ids)
        ],
    )
    strategy_diagnostics = update_strategy_signal_diagnostics(
        config,
        ledger_rows,
        generated_at_iso,
        test_epoch_id=str(test_epoch_state.get("test_epoch_id") or ""),
        detector_attempts=detector_attempts,
    )
    if emitted_signal_events is not None:
        emitted_signal_events.extend(new_signal_events)
    summary = {
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at_iso,
        "source_mode": "longbridge_realtime_market_events",
        "local_simulation_isolated": True,
        "local_ledger_input_ref": "",
        "legacy_fast_queue_used": False,
        "raw_market_event_count": len(raw_market_events),
        "market_event_read_mode": "tail_window",
        "market_event_input_mode": "direct_event_window" if market_events_override is not None else "jsonl_tail",
        "active_market_event_count": len(active_market_event_ids or ()),
        "market_event_hot_window_limit": config.max_market_event_rows_per_hot_run,
        "current_session_market_event_count": current_session_market_event_count(raw_market_events, session_started_at),
        "relevant_market_event_count": len(market_events),
        "stale_market_event_ignored_count": max(0, len(raw_market_events) - len(market_events)),
        "market_event_count": len(market_events),
        "embedded_intent_count": sum(len(event_intents(row)) for row in market_events),
        "router_decision_count": len(ledger_rows),
        "new_signal_event_count": len(new_signal_events),
        "existing_signal_event_count": existing_signal_event_count,
        "signal_event_total_count": existing_signal_event_count + len(new_signal_events),
        "test_epoch_id": str(test_epoch_state.get("test_epoch_id") or ""),
        "test_epoch_status": str(test_epoch_state.get("status") or ""),
        "test_started_at": str(test_epoch_state.get("test_started_at") or ""),
        "daily_structure_episode_state": daily_structure_episode_state,
        "epoch_rebuilt_signal_count": sum(1 for signal in new_signal_events if signal.get("realtime_rebuilt_after_epoch_activation")),
        "confluence_primary_count": sum(1 for intent in routed_intents if decimal(intent.get("confluence_multiplier", "1")) > Decimal("1")),
        "confluence_merged_support_count": len(merged_support_intents),
        "quality_sorted_candidate_count": len(routed_intents),
        "market_confirmation_blocked_count": sum(
            1 for row in ledger_rows if "blocked_market_confirmation_missing" in row.get("blockers", [])
        ),
        "quality_gate_blocked_count": sum(
            1
            for row in ledger_rows
            if any(
                reason in row.get("blockers", [])
                for reason in (
                    "blocked_close_position_below_runtime_minimum",
                    "blocked_volume_ratio_below_runtime_minimum",
                    "blocked_close_to_close_below_runtime_minimum",
                )
            )
        ),
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
        "paper_short_diagnostics": short_diagnostics.get("summary", {}),
        "strategy_signal_diagnostics": strategy_diagnostics.get("summary", {}),
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
            "capital_bucket_migration_state": (
                project_path(config.capital_bucket_migration_state_path)
                if config.capital_bucket_migration_state_path is not None
                else ""
            ),
            "local_simulation_ledger": "",
            "fast_signal_queue": "",
        },
        "outputs": {
            "signal_events": project_path(config.signal_events_path),
            "router_summary": project_path(config.output_dir / SUMMARY_JSON),
            "router_ledger": project_path(config.output_dir / LEDGER_JSONL),
            "paper_short_diagnostics": project_path(config.output_dir / SHORT_DIAGNOSTICS_JSON),
            "strategy_signal_diagnostics": project_path(config.output_dir / STRATEGY_DIAGNOSTICS_JSON),
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


def annotate_strategy_contracts(
    config: RealtimeSignalRouterConfig,
    intents: list[dict[str, Any]],
) -> None:
    if not config.require_strategy_contracts:
        return
    contracts = load_contracts_cached(str(config.strategy_contracts_dir))
    for intent in intents:
        runtime_id = str(intent.get("runtime_id") or "")
        contract = contracts.get(runtime_id)
        if contract is None:
            intent.setdefault("pre_gate_blockers", []).append("blocked_strategy_contract_missing")
            continue
        intent["strategy_contract_hash"] = str(contract["contract_hash"])
        intent["strategy_contract_stage"] = str(contract["stage"])
        intent["strategy_contract_stage_zh"] = str(contract["stage_zh"])
        intent["strategy_contract_schema_version"] = str(contract["schema_version"])
        if contract["stage"] not in {"paper-v1", "full-v1"}:
            intent.setdefault("pre_gate_blockers", []).append("blocked_strategy_contract_not_executable")


def update_short_signal_diagnostics(
    config: RealtimeSignalRouterConfig,
    ledger_rows: list[dict[str, Any]],
    generated_at: str,
    *,
    detector_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist unique short candidates so a later empty cycle cannot hide them."""
    path = config.output_dir / SHORT_DIAGNOSTICS_JSON
    previous = read_json(path)
    if str(previous.get("test_epoch_id") or "") != config.short_test_epoch_id:
        previous = {}

    existing_rows = previous.get("decision_rows")
    decisions_by_id = {
        str(row.get("signal_id")): row
        for row in existing_rows
        if isinstance(existing_rows, list)
        and isinstance(row, dict)
        and str(row.get("signal_id") or "")
    } if isinstance(existing_rows, list) else {}

    short_runtime_ids = set(config.paper_short_runtime_ids)
    for row in ledger_rows:
        runtime_id = str(row.get("runtime_id") or "")
        if runtime_id not in short_runtime_ids and str(row.get("direction") or "").lower() != "short":
            continue
        signal_id = str(row.get("signal_id") or "")
        if not signal_id:
            continue
        decisions_by_id[signal_id] = {
            "signal_id": signal_id,
            "detector_attempted": True,
            "no_candidate_reason": "",
            "created_at": str(row.get("created_at") or ""),
            "processed_at": str(row.get("processed_at") or generated_at),
            "runtime_id": runtime_id,
            "symbol": str(row.get("symbol") or ""),
            "router_decision_status": str(row.get("router_decision_status") or ""),
            "blockers": list(row.get("blockers") or []),
            "submitted_quantity": str(row.get("submitted_quantity") or "0"),
            "notional": str(row.get("notional") or "0"),
            "risk_amount": str(row.get("risk_amount") or "0"),
            "net_profit_after_fees_at_target": str(row.get("net_profit_after_fees_at_target") or "0"),
            "minimum_net_profit_after_fees": str(row.get("minimum_net_profit_after_fees") or "0"),
            "reward_r": str(row.get("reward_r") or "0"),
            "minimum_reward_r": str(row.get("minimum_reward_r") or "0"),
            "quality_score": str(row.get("quality_score") or "0"),
            "minimum_quality_score": str(row.get("minimum_quality_score") or "0"),
            "source_market_event_id": str(row.get("source_market_event_id") or ""),
        }

    decision_rows = sorted(
        decisions_by_id.values(),
        key=lambda row: (str(row.get("created_at") or ""), str(row.get("signal_id") or "")),
    )[-SHORT_DIAGNOSTIC_ROW_LIMIT:]
    previous_attempt_rows = previous.get("detector_attempt_rows")
    attempts_by_id = {
        str(row.get("attempt_id")): row
        for row in previous_attempt_rows
        if isinstance(previous_attempt_rows, list)
        and isinstance(row, dict)
        and str(row.get("attempt_id") or "")
    } if isinstance(previous_attempt_rows, list) else {}
    for row in detector_attempts or []:
        attempt_id = str(row.get("attempt_id") or "")
        if attempt_id:
            attempts_by_id[attempt_id] = dict(row)
    detector_attempt_rows = sorted(
        attempts_by_id.values(),
        key=lambda row: (str(row.get("market_event_time") or ""), str(row.get("attempt_id") or "")),
    )[-SHORT_DIAGNOSTIC_ROW_LIMIT:]
    runtime_summaries: list[dict[str, Any]] = []
    total_blockers: Counter[str] = Counter()
    for runtime_id in config.paper_short_runtime_ids:
        runtime_rows = [row for row in decision_rows if row.get("runtime_id") == runtime_id]
        runtime_attempts = [
            row for row in detector_attempt_rows if row.get("runtime_id") == runtime_id
        ]
        blockers: Counter[str] = Counter()
        no_candidate_reasons = Counter(
            str(row.get("no_candidate_reason") or "")
            for row in runtime_attempts
            if str(row.get("no_candidate_reason") or "")
        )
        for row in runtime_rows:
            blockers.update(str(item) for item in row.get("blockers", []) if str(item))
        total_blockers.update(blockers)
        runtime_summaries.append(
            {
                "runtime_id": runtime_id,
                "detector_attempted": bool(runtime_attempts),
                "detector_attempted_count": len(runtime_attempts),
                "no_candidate_count": sum(
                    1 for row in runtime_attempts if row.get("no_candidate_reason")
                ),
                "no_candidate_reasons": dict(no_candidate_reasons.most_common()),
                "candidate_count": len(runtime_rows),
                "signal_ready_count": sum(
                    1 for row in runtime_rows if row.get("router_decision_status") == "signal_event_ready"
                ),
                "blocked_count": sum(1 for row in runtime_rows if row.get("blockers")),
                "blockers": dict(blockers.most_common()),
                "last_candidate_at": max(
                    (str(row.get("created_at") or "") for row in runtime_rows),
                    default="",
                ),
            }
        )

    payload = {
        "schema_version": "m15.longbridge-short-signal-diagnostics.v2",
        "stage": "M15.longbridge_short_signal_diagnostics",
        "generated_at": generated_at,
        "test_epoch_id": config.short_test_epoch_id,
        "test_started_at": config.short_test_started_at,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "summary": {
            "runtime_count": len(config.paper_short_runtime_ids),
            "detector_attempted_count": len(detector_attempt_rows),
            "no_candidate_count": sum(
                1 for row in detector_attempt_rows if row.get("no_candidate_reason")
            ),
            "candidate_count": len(decision_rows),
            "signal_ready_count": sum(
                1 for row in decision_rows if row.get("router_decision_status") == "signal_event_ready"
            ),
            "blocked_count": sum(1 for row in decision_rows if row.get("blockers")),
            "top_blockers": dict(total_blockers.most_common(10)),
        },
        "runtime_summaries": runtime_summaries,
        "detector_attempt_rows": detector_attempt_rows,
        "decision_rows": decision_rows,
    }
    write_json(path, payload)
    return payload


def update_strategy_signal_diagnostics(
    config: RealtimeSignalRouterConfig,
    ledger_rows: list[dict[str, Any]],
    generated_at: str,
    *,
    test_epoch_id: str,
    detector_attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist the detector-to-router funnel for every executable contract."""
    path = config.output_dir / STRATEGY_DIAGNOSTICS_JSON
    previous = read_json(path)
    contracts = (
        load_contracts_cached(str(config.strategy_contracts_dir))
        if config.require_strategy_contracts
        else {}
    )
    contract_hashes = {
        runtime_id: str((contracts.get(runtime_id) or {}).get("contract_hash") or "")
        for runtime_id in config.allowed_runtime_ids
    }
    contract_signature = sha256(
        json.dumps(sorted(contract_hashes.items()), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    epoch_key = f"{test_epoch_id}|{config.short_test_epoch_id}|contracts={contract_signature}"
    if str(previous.get("epoch_key") or "") != epoch_key:
        previous = {}
    attempts_by_id = {
        str(row.get("attempt_id")): row
        for row in previous.get("detector_attempt_rows", [])
        if isinstance(row, dict) and str(row.get("attempt_id") or "")
    }
    for row in detector_attempts:
        attempt_id = str(row.get("attempt_id") or "")
        if attempt_id:
            runtime_id = str(row.get("runtime_id") or "")
            attempts_by_id[attempt_id] = {
                **dict(row),
                "strategy_contract_hash": contract_hashes.get(runtime_id, ""),
            }
    attempt_rows = sorted(
        attempts_by_id.values(),
        key=lambda row: (str(row.get("market_event_time") or ""), str(row.get("attempt_id") or "")),
    )[-STRATEGY_DIAGNOSTIC_ROW_LIMIT:]
    decisions_by_id = {
        str(row.get("signal_id")): row
        for row in previous.get("decision_rows", [])
        if isinstance(row, dict) and str(row.get("signal_id") or "")
    }
    for row in ledger_rows:
        signal_id = str(row.get("signal_id") or "")
        if signal_id:
            decisions_by_id[signal_id] = {
                "signal_id": signal_id,
                "runtime_id": str(row.get("runtime_id") or ""),
                "strategy_contract_hash": str(
                    row.get("strategy_contract_hash")
                    or contract_hashes.get(str(row.get("runtime_id") or ""), "")
                ),
                "symbol": str(row.get("symbol") or ""),
                "created_at": str(row.get("created_at") or ""),
                "router_decision_status": str(row.get("router_decision_status") or ""),
                "blockers": list(row.get("blockers") or []),
            }
    decision_rows = sorted(
        decisions_by_id.values(),
        key=lambda row: (str(row.get("created_at") or ""), str(row.get("signal_id") or "")),
    )[-STRATEGY_DIAGNOSTIC_ROW_LIMIT:]
    runtime_summaries: list[dict[str, Any]] = []
    for runtime_id in config.allowed_runtime_ids:
        runtime_attempts = [row for row in attempt_rows if row.get("runtime_id") == runtime_id]
        runtime_decisions = [row for row in decision_rows if row.get("runtime_id") == runtime_id]
        no_candidate_reasons = Counter(
            str(row.get("no_candidate_reason") or "")
            for row in runtime_attempts
            if str(row.get("no_candidate_reason") or "")
        )
        blockers = Counter(
            str(blocker)
            for row in runtime_decisions
            for blocker in row.get("blockers", [])
            if str(blocker)
        )
        runtime_summaries.append(
            {
                "runtime_id": runtime_id,
                "strategy_contract_hash": contract_hashes.get(runtime_id, ""),
                "detector_attempted_count": len(runtime_attempts),
                "no_candidate_count": sum(1 for row in runtime_attempts if row.get("no_candidate_reason")),
                "no_candidate_reasons": dict(no_candidate_reasons.most_common()),
                "candidate_count": len(runtime_decisions),
                "signal_ready_count": sum(
                    1 for row in runtime_decisions
                    if row.get("router_decision_status") == "signal_event_ready"
                ),
                "router_blocked_count": sum(1 for row in runtime_decisions if row.get("blockers")),
                "router_blockers": dict(blockers.most_common()),
                "broker_order_and_fill_source": "m15_longbridge_order_reconciliation",
            }
        )
    payload = {
        "schema_version": "m15.longbridge-strategy-signal-diagnostics.v1",
        "stage": "M15.longbridge_strategy_signal_diagnostics",
        "generated_at": generated_at,
        "epoch_key": epoch_key,
        "strategy_contract_hashes": contract_hashes,
        "strategy_contract_signature": contract_signature,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "summary": {
            "runtime_count": len(config.allowed_runtime_ids),
            "detector_attempted_count": len(attempt_rows),
            "no_candidate_count": sum(1 for row in attempt_rows if row.get("no_candidate_reason")),
            "candidate_count": len(decision_rows),
            "signal_ready_count": sum(
                1 for row in decision_rows
                if row.get("router_decision_status") == "signal_event_ready"
            ),
            "router_blocked_count": sum(1 for row in decision_rows if row.get("blockers")),
        },
        "runtime_summaries": runtime_summaries,
        "detector_attempt_rows": attempt_rows,
        "decision_rows": decision_rows,
    }
    write_json(path, payload)
    return payload


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
        timeframe = key[1]
        history_limit = 60 if timeframe == "1d" else 78 if timeframe == "5m" else 20
        for idx, _row in group_rows[-history_limit:]:
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
    is_short = direction == "short"
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
    detector_attempts: list[dict[str, Any]] | None = None,
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
    enabled_detectors = set(config.enabled_detectors)
    if "pa004_followthrough_long" in enabled_detectors:
        for (symbol, timeframe), rows in grouped.items():
            if timeframe != "1d" or len(rows) < 2:
                continue
            signal = pa004_followthrough_long_signal(symbol, rows[-2], rows[-1], generated_at=generated_at)
            if signal:
                signal["runtime_id"] = "M10-PA-004-long-1d"
                signal["strategy_id"] = "M10-PA-004"
                signal["timeframe"] = timeframe
                candidates.append(signal)
    if "pa004_momentum_variants" in enabled_detectors or "pa004_followthrough_long" in enabled_detectors:
        pa004_variants = {
            "M10-PA-004-MBF-1d": {
                "strategy_id": "M10-PA-004-MBF",
                "min_close_to_close_percent": Decimal("3.00"),
                "min_gap_percent": Decimal("2.50"),
                "min_gap_close_to_close_percent": Decimal("1.50"),
                "min_close_position": Decimal("0.25"),
                "max_risk_percent": ZERO,
                "target_r": Decimal("2.00"),
            },
            "M10-PA-004-MBF-QC-1d": {
                "strategy_id": "M10-PA-004-MBF-QC",
                "min_close_to_close_percent": Decimal("4.00"),
                "min_gap_percent": Decimal("3.00"),
                "min_gap_close_to_close_percent": Decimal("2.50"),
                "min_close_position": Decimal("0.60"),
                "min_volume_ratio": Decimal("1.10"),
                "require_next_bar_quote": True,
                "max_risk_percent": Decimal("4.00"),
                "target_r": Decimal("1.50"),
            },
        }
        for runtime_id, thresholds in pa004_variants.items():
            if runtime_id not in set(config.allowed_runtime_ids):
                continue
            for (symbol, timeframe), rows in grouped.items():
                if timeframe != "1d" or len(rows) < 2:
                    continue
                signal = pa004_momentum_variant_signal(
                    symbol,
                    rows[-2],
                    rows[-1],
                    thresholds=thresholds,
                    generated_at=generated_at,
                )
                if detector_attempts is not None:
                    detector_attempts.append(
                        detector_attempt_row(
                            runtime_id,
                            symbol,
                            timeframe,
                            rows,
                            signal,
                            no_candidate_reason=(
                                "pa004_momentum_quality_contract_not_met"
                                if signal is None else ""
                            ),
                        )
                    )
                if signal:
                    signal["runtime_id"] = runtime_id
                    signal["strategy_id"] = str(thresholds["strategy_id"])
                    signal["timeframe"] = timeframe
                    candidates.append(signal)
    if PRICE_ACTION_REALTIME_DETECTOR in set(config.enabled_detectors):
        candidates.extend(
            price_action_realtime_candidates(
                config,
                grouped,
                generated_at=generated_at,
                detector_attempts=detector_attempts,
            )
        )
    return candidates


def price_action_realtime_candidates(
    config: RealtimeSignalRouterConfig,
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    generated_at: datetime,
    detector_attempts: list[dict[str, Any]] | None = None,
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
                grouped_events=grouped_events,
                generated_at=generated_at,
            )
            if detector_attempts is not None:
                rule = str(spec.get("rule") or "")
                reason = ""
                if signal is None:
                    reason = (
                        short_no_candidate_reason(rule, rows)
                        if runtime_id in PAPER_SHORT_RUNTIME_IDS
                        else long_no_candidate_reason(runtime_id, rows)
                    )
                detector_attempts.append(
                    detector_attempt_row(
                        runtime_id,
                        symbol,
                        timeframe,
                        rows,
                        signal,
                        no_candidate_reason=reason,
                    )
                )
            if signal:
                candidates.append(signal)
    return candidates


def short_no_candidate_reason(rule: str, rows: list[dict[str, Any]]) -> str:
    """Classify a detector miss without changing any strategy gate."""
    minimum_rows = 7 if rule == "opening_range_breakdown" else 3
    if len(rows) < minimum_rows:
        return "insufficient_history"
    latest = rows[-1]
    if min(
        decimal(latest.get("high", "0")),
        decimal(latest.get("low", "0")),
        decimal(latest.get("close", "0")),
    ) <= ZERO:
        return "invalid_price_geometry"
    if rule == "bearish_breakdown":
        prior_low = min(decimal(rows[-3].get("low", "0")), decimal(rows[-2].get("low", "0")))
        if decimal(latest.get("close", "0")) > prior_low * Decimal("0.998"):
            return "bearish_structure_not_met"
    elif rule == "bearish_false_breakout":
        resistance = max(decimal(rows[-3].get("high", "0")), decimal(rows[-2].get("high", "0")))
        if decimal(latest.get("high", "0")) < resistance * Decimal("1.0015") or decimal(
            latest.get("close", "0")
        ) >= resistance:
            return "bearish_structure_not_met"
    elif rule == "opening_range_breakdown":
        session_rows = latest_ny_session_rows(rows)
        if len(session_rows) <= 6:
            return "opening_range_incomplete"
        opening_low = min(decimal(row.get("low", "0")) for row in session_rows[:6])
        if decimal(session_rows[-2].get("close", "0")) < opening_low or decimal(
            session_rows[-1].get("close", "0")
        ) > opening_low * Decimal("0.9975"):
            return "bearish_structure_not_met"
    return "short_validation_filters_not_met"


def detector_attempt_row(
    runtime_id: str,
    symbol: str,
    timeframe: str,
    rows: list[dict[str, Any]],
    signal: dict[str, Any] | None,
    *,
    no_candidate_reason: str,
) -> dict[str, Any]:
    latest = rows[-1] if rows else {}
    source_event_id = str(
        latest.get("market_event_id")
        or latest.get("event_id")
        or latest.get("bar_id")
        or latest.get("event_time")
        or latest.get("bar_time")
        or latest.get("timestamp")
        or ""
    )
    return {
        "attempt_id": f"{runtime_id}:{symbol}:{source_event_id}",
        "runtime_id": runtime_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "detector_attempted": True,
        "candidate_emitted": signal is not None,
        "no_candidate_reason": no_candidate_reason,
        "source_market_event_id": source_event_id,
        "market_event_time": str(
            latest.get("event_time")
            or latest.get("bar_time")
            or latest.get("timestamp")
            or ""
        ),
    }


def five_minute_rows_are_contiguous(rows: list[dict[str, Any]]) -> bool:
    times: list[datetime] = []
    for row in rows:
        try:
            times.append(
                parse_utc_datetime(
                    str(row.get("event_time") or row.get("bar_time") or row.get("timestamp") or "")
                )
            )
        except ValueError:
            return False
    return all(
        int((current - previous).total_seconds()) == 300
        for previous, current in zip(times, times[1:])
    )


def long_no_candidate_reason(runtime_id: str, rows: list[dict[str, Any]]) -> str:
    if runtime_id == "M10-PA-001-1d":
        if len(rows) < 22:
            return "insufficient_daily_history"
    elif runtime_id == "M10-PA-002-5m":
        if len(rows) < 22:
            return "insufficient_five_minute_history"
        if not five_minute_rows_are_contiguous(rows[-23:]):
            return "non_contiguous_five_minute_context"
    elif runtime_id == "M10-PA-012-5m":
        session_rows = latest_ny_session_rows(rows)
        if session_rows:
            try:
                first_close = parse_utc_datetime(
                    str(
                        session_rows[0].get("event_time")
                        or session_rows[0].get("bar_time")
                        or session_rows[0].get("timestamp")
                        or ""
                    )
                ).astimezone(NEW_YORK)
            except ValueError:
                return "invalid_five_minute_event_time"
            if (first_close.hour, first_close.minute) != (9, 35):
                return "missing_opening_range_context_after_restart"
        if len(session_rows) < 8:
            return "opening_range_or_followthrough_incomplete"
        if not five_minute_rows_are_contiguous(session_rows):
            return "non_contiguous_five_minute_context"
    elif runtime_id == "M12-FTD-001-pullback-guard-confirm-1d" and len(rows) < 3:
        return "insufficient_daily_history"
    if rows and not str(rows[-1].get("next_bar_first_quote_at") or ""):
        return "next_bar_quote_unavailable"
    return "strategy_structure_not_met"


def price_action_signal_for_runtime(
    *,
    runtime_id: str,
    spec: dict[str, Any],
    symbol: str,
    rows: list[dict[str, Any]],
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if symbol in {"SQQQ", "TQQQ"}:
        return None
    rule = str(spec["rule"])
    signal: dict[str, Any] | None
    if rule == "pa001_daily_contract_v1":
        signal = pa001_daily_long(symbol, rows)
    elif rule == "pa002_5m_contract_v1":
        signal = pa002_five_minute_long(symbol, rows)
    elif rule == "pa012_5m_contract_v1":
        signal = pa012_five_minute_long(symbol, rows)
    elif rule == "trend_continuation":
        signal = trend_continuation_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "breakout_confirmation":
        signal = breakout_confirmation_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "breakout_followthrough_repair":
        signal = breakout_followthrough_repair_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "failed_breakdown_reclaim":
        signal = failed_breakdown_reclaim_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "reversal_followthrough":
        signal = reversal_followthrough_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "opening_range_breakout":
        signal = opening_range_breakout_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "support_resistance_failure":
        signal = support_resistance_failure_signal(symbol, rows, spec=spec, generated_at=generated_at)
    elif rule == "bearish_breakdown":
        signal = bearish_breakdown_signal(
            symbol,
            rows,
            spec=spec,
            grouped_events=grouped_events,
            generated_at=generated_at,
        )
    elif rule == "bearish_false_breakout":
        signal = bearish_false_breakout_signal(
            symbol,
            rows,
            spec=spec,
            grouped_events=grouped_events,
            generated_at=generated_at,
        )
    elif rule == "opening_range_breakdown":
        signal = opening_range_breakdown_signal(
            symbol,
            rows,
            spec=spec,
            grouped_events=grouped_events,
            generated_at=generated_at,
        )
    elif rule == "follow_through_day":
        signal = follow_through_day_signal(
            symbol,
            rows,
            spec=spec,
            grouped_events=grouped_events,
            generated_at=generated_at,
        )
    elif rule == "ftd_pullback_guard_confirm_v1":
        signal = ftd_pullback_guard_confirm_signal(
            symbol,
            rows,
            spec=spec,
            grouped_events=grouped_events,
            generated_at=generated_at,
        )
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


def breakout_followthrough_repair_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any] | None:
    """Replicate the old PA002 follow-through filter using only live SDK bars."""
    if len(rows) < 4:
        return None
    prior_rows = rows[-4:-2]
    breakout, latest = rows[-2], rows[-1]
    prior_high = max(decimal(row.get("high", "0")) for row in prior_rows)
    breakout_close = decimal(breakout.get("close", "0"))
    breakout_low = decimal(breakout.get("low", "0"))
    latest_close = decimal(latest.get("close", "0"))
    latest_low = decimal(latest.get("low", "0"))
    if min(prior_high, breakout_close, breakout_low, latest_close, latest_low) <= ZERO:
        return None
    if breakout_close <= prior_high or latest_close < breakout_close:
        return None
    if close_position(breakout) < decimal(spec.get("min_close_position", "0.60")):
        return None
    entry = latest_close
    stop = max(min(breakout_low, latest_low), prior_high - (breakout_close - prior_high))
    signal = build_price_action_long_signal(
        detector_id="pa002_breakout_followthrough_repair_realtime",
        symbol=symbol,
        latest=latest,
        entry=entry,
        stop=stop,
        target_r=decimal(spec.get("target_r", "1.30")),
        max_risk_percent=decimal(spec.get("max_risk_percent", "2.50")),
        order_type="trigger_limit",
        trigger_price=entry,
        generated_at=generated_at,
    )
    if signal is not None:
        signal["repair_rule_id"] = "pa002_false_breakout_confirmation_cooldown_v1"
        signal["source_breakout_entry_price"] = fmt_money(breakout_close)
        signal["latest_confirms_entry"] = True
        signal["next_market_day_timeout"] = True
    return signal


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


def bearish_breakdown_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if len(rows) < 3:
        return None
    prior, previous, latest = rows[-3], rows[-2], rows[-1]
    prior_low = min(decimal(prior.get("low", "0")), decimal(previous.get("low", "0")))
    latest_low = decimal(latest.get("low", "0"))
    latest_high = decimal(latest.get("high", "0"))
    entry = decimal(latest.get("close", "0"))
    if min(prior_low, latest_low, latest_high, entry) <= ZERO:
        return None
    if entry > prior_low * Decimal("0.998"):
        return None
    return build_validated_short_signal(
        detector_id="pa002_bearish_breakdown_realtime",
        symbol=symbol,
        previous=previous,
        latest=latest,
        entry=entry,
        stop=max(latest_high, prior_low),
        structure_low=latest_low,
        spec=spec,
        grouped_events=grouped_events,
        generated_at=generated_at,
    )


def bearish_false_breakout_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if len(rows) < 3:
        return None
    prior, previous, latest = rows[-3], rows[-2], rows[-1]
    resistance = max(decimal(prior.get("high", "0")), decimal(previous.get("high", "0")))
    latest_high = decimal(latest.get("high", "0"))
    latest_low = decimal(latest.get("low", "0"))
    entry = decimal(latest.get("close", "0"))
    if min(resistance, latest_high, latest_low, entry) <= ZERO:
        return None
    if latest_high < resistance * Decimal("1.0015") or entry >= resistance:
        return None
    return build_validated_short_signal(
        detector_id="pa013_bearish_false_breakout_realtime",
        symbol=symbol,
        previous=previous,
        latest=latest,
        entry=entry,
        stop=max(latest_high, resistance),
        structure_low=latest_low,
        spec=spec,
        grouped_events=grouped_events,
        generated_at=generated_at,
    )


def opening_range_breakdown_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    session_rows = latest_ny_session_rows(rows)
    opening_bars_required = 6
    if len(session_rows) <= opening_bars_required:
        return None
    opening = session_rows[:opening_bars_required]
    previous = session_rows[-2]
    latest = session_rows[-1]
    opening_high = max(decimal(row.get("high", "0")) for row in opening)
    opening_low = min(decimal(row.get("low", "0")) for row in opening)
    previous_close = decimal(previous.get("close", "0"))
    latest_low = decimal(latest.get("low", "0"))
    entry = decimal(latest.get("close", "0"))
    if min(opening_high, opening_low, previous_close, latest_low, entry) <= ZERO or opening_high <= opening_low:
        return None
    if previous_close < opening_low or entry > opening_low * Decimal("0.9975"):
        return None
    return build_validated_short_signal(
        detector_id="pa011_orb_r1_bearish_breakdown_realtime",
        symbol=symbol,
        previous=previous,
        latest=latest,
        entry=entry,
        stop=min(opening_high, max(decimal(latest.get("high", "0")), opening_low)),
        structure_low=latest_low,
        spec=spec,
        grouped_events=grouped_events,
        generated_at=generated_at,
    )


def build_validated_short_signal(
    *,
    detector_id: str,
    symbol: str,
    previous: dict[str, Any],
    latest: dict[str, Any],
    entry: Decimal,
    stop: Decimal,
    structure_low: Decimal,
    spec: dict[str, Any],
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    close_position_value = close_position(latest)
    close_to_close_percent = row_close_to_close_percent(previous, latest)
    volume_ratio = row_volume_ratio(previous, latest)
    if entry <= ZERO or stop <= entry or structure_low <= ZERO:
        return None
    if close_position_value > decimal(spec.get("max_close_position", "1")):
        return None
    if close_to_close_percent > decimal(spec.get("max_close_to_close_percent", "0")):
        return None
    if volume_ratio < decimal(spec.get("min_volume_ratio", "1")):
        return None
    risk_percent = (stop - entry) / entry * HUNDRED
    max_risk_percent = decimal(spec.get("max_risk_percent", "0"))
    if max_risk_percent > ZERO and risk_percent > max_risk_percent:
        return None
    market_confirmed, market_symbols = market_bearish_confirmed(
        grouped_events,
        latest,
        requirement=str(spec.get("market_confirmation_requirement") or "either"),
    )
    if not market_confirmed:
        return None
    target_r = decimal(spec.get("target_r", "2"))
    target = entry - (stop - entry) * target_r
    if target <= ZERO:
        return None
    quality_score = bearish_quality_score(
        close_position_value=close_position_value,
        close_to_close_percent=close_to_close_percent,
        volume_ratio=volume_ratio,
        reward_r=target_r,
        risk_percent=risk_percent,
        market_confirmed=market_confirmed,
    )
    if quality_score < decimal(spec.get("minimum_quality_score", "0")):
        return None
    signal = build_price_action_short_signal(
        detector_id=detector_id,
        symbol=symbol,
        latest=latest,
        entry=entry,
        stop=stop,
        target=target,
        generated_at=generated_at,
    )
    if not signal:
        return None
    signal.update(
        {
            "close_position": fmt_decimal(close_position_value),
            "close_to_close_percent": fmt_decimal(close_to_close_percent),
            "volume_ratio": fmt_decimal(volume_ratio),
            "market_confirmation_status": "confirmed",
            "market_confirmation_symbols": market_symbols,
            "quality_score": fmt_decimal(quality_score),
            "signal_quality_score": fmt_decimal(quality_score),
            "minimum_quality_score": fmt_decimal(decimal(spec.get("minimum_quality_score", "0"))),
            "minimum_reward_r": fmt_decimal(decimal(spec.get("minimum_reward_r", target_r))),
            "minimum_net_profit_after_fees": fmt_money(decimal(spec.get("minimum_net_profit_after_fees", "0"))),
            "short_structure_low": fmt_money(structure_low),
            "quality_score_components": {
                "close_position": fmt_decimal(close_position_value),
                "close_to_close_percent": fmt_decimal(close_to_close_percent),
                "volume_ratio": fmt_decimal(volume_ratio),
                "reward_r": fmt_decimal(target_r),
                "risk_percent": fmt_decimal(risk_percent),
                "market_confirmed": market_confirmed,
            },
            "high_quality_signal": True,
        }
    )
    return signal


def build_price_action_short_signal(
    *,
    detector_id: str,
    symbol: str,
    latest: dict[str, Any],
    entry: Decimal,
    stop: Decimal,
    target: Decimal,
    generated_at: datetime,
) -> dict[str, Any] | None:
    if entry <= ZERO or stop <= entry or target <= ZERO or target >= entry:
        return None
    return {
        "detector_id": detector_id,
        "symbol": symbol,
        "direction": "short",
        "side": "sell_short",
        "position_action": "open_short",
        "order_type": "limit",
        "limit_price": fmt_money(entry),
        "stop_price": fmt_money(stop),
        "target_price": fmt_money(target),
        "current_price": fmt_money(entry),
        "source_market_event_id": str(latest.get("event_id") or latest.get("market_event_id") or ""),
        "market_event_time": str(latest.get("event_time") or latest.get("bar_time") or latest.get("timestamp") or ""),
        "created_at": str(latest.get("received_at") or to_iso(generated_at)),
    }


def market_bearish_confirmed(
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    latest: dict[str, Any],
    *,
    requirement: str,
) -> tuple[bool, str]:
    target_date = ny_event_date(latest)
    target_time = parse_optional_utc_datetime(
        str(latest.get("event_time") or latest.get("bar_time") or latest.get("timestamp") or "")
    )
    weak_symbols: list[str] = []
    for symbol in ("SPY", "QQQ"):
        rows = grouped_events.get((symbol, "5m"), [])
        if len(rows) < 2:
            continue
        previous, market_latest = rows[-2], rows[-1]
        if target_date and ny_event_date(market_latest) != target_date:
            continue
        market_time = parse_optional_utc_datetime(
            str(market_latest.get("event_time") or market_latest.get("bar_time") or market_latest.get("timestamp") or "")
        )
        if target_time and market_time and abs((market_time - target_time).total_seconds()) > 600:
            continue
        if row_close_to_close_percent(previous, market_latest) <= Decimal("-0.25"):
            weak_symbols.append(symbol)
    required_count = 2 if requirement == "both" else 1
    return len(weak_symbols) >= required_count, ",".join(weak_symbols)


def bearish_quality_score(
    *,
    close_position_value: Decimal,
    close_to_close_percent: Decimal,
    volume_ratio: Decimal,
    reward_r: Decimal,
    risk_percent: Decimal,
    market_confirmed: bool,
) -> Decimal:
    score = ZERO
    score += min(max(Decimal("1") - close_position_value, ZERO), Decimal("1")) * Decimal("35")
    score += min(max(-close_to_close_percent, ZERO), Decimal("2")) / Decimal("2") * Decimal("20")
    score += min(max(volume_ratio - Decimal("1"), ZERO), Decimal("1")) * Decimal("15")
    score += min(max(reward_r - Decimal("1"), ZERO), Decimal("2")) / Decimal("2") * Decimal("10")
    if risk_percent > ZERO:
        score += max(Decimal("0"), Decimal("10") - min(risk_percent, Decimal("10")))
    if market_confirmed:
        score += Decimal("10")
    return min(score, Decimal("100"))


def follow_through_day_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if len(rows) < 2:
        return None
    previous, latest = rows[-2], rows[-1]
    previous_close = decimal(previous.get("close", "0"))
    latest_close = decimal(latest.get("close", "0"))
    latest_low = decimal(latest.get("low", "0"))
    if min(previous_close, latest_close, latest_low) <= ZERO:
        return None
    close_to_close_percent = row_close_to_close_percent(previous, latest)
    volume_ratio = row_volume_ratio(previous, latest)
    latest_close_position = close_position(latest)
    min_close_to_close = decimal(spec.get("min_close_to_close_percent", "1.25"))
    min_volume_ratio = decimal(spec.get("min_volume_ratio", "1.00"))
    min_close_position = decimal(spec.get("min_close_position", "0.55"))
    target_date = ny_event_date(latest)
    market_confirmed, market_symbols = market_follow_through_confirmed(grouped_events, target_date)
    pre_gate_blockers: list[str] = []
    if spec.get("require_market_confirmation") and not market_confirmed:
        pre_gate_blockers.append("blocked_market_confirmation_missing")
    if close_to_close_percent < min_close_to_close:
        pre_gate_blockers.append("blocked_close_to_close_below_runtime_minimum")
    if volume_ratio < min_volume_ratio:
        pre_gate_blockers.append("blocked_volume_ratio_below_runtime_minimum")
    if latest_close_position < min_close_position:
        pre_gate_blockers.append("blocked_close_position_below_runtime_minimum")
    target_r = decimal(spec.get("target_r", "1.5"))
    signal = build_price_action_long_signal(
        detector_id="ftd001_follow_through_day_realtime",
        symbol=symbol,
        latest=latest,
        entry=latest_close,
        stop=latest_low,
        target_r=target_r,
        max_risk_percent=decimal(spec.get("max_risk_percent", "0")),
        order_type="limit",
        generated_at=generated_at,
    )
    if not signal:
        return None
    risk_percent = (latest_close - latest_low) / latest_close * HUNDRED
    quality_score = base_quality_score(
        close_position_value=latest_close_position,
        close_to_close_percent=close_to_close_percent,
        volume_ratio=volume_ratio,
        reward_r=target_r,
        net_profit=(latest_close - latest_low) * target_r,
        risk_percent=risk_percent,
        market_confirmed=market_confirmed,
    )
    signal.update(
        {
            "close_position": fmt_decimal(latest_close_position),
            "close_to_close_percent": fmt_decimal(close_to_close_percent),
            "volume_ratio": fmt_decimal(volume_ratio),
            "market_confirmation_status": "confirmed" if market_confirmed else "not_required",
            "market_confirmation_symbols": market_symbols,
            "pre_gate_blockers": pre_gate_blockers,
            "quality_score": fmt_decimal(quality_score),
            "signal_quality_score": fmt_decimal(quality_score),
            "quality_score_components": {
                "close_position": fmt_decimal(latest_close_position),
                "close_to_close_percent": fmt_decimal(close_to_close_percent),
                "volume_ratio": fmt_decimal(volume_ratio),
                "reward_r": fmt_decimal(target_r),
                "risk_percent": fmt_decimal(risk_percent),
                "market_confirmed": market_confirmed,
            },
            "high_quality_signal": quality_score >= Decimal("80"),
        }
    )
    return signal


def ftd_pullback_guard_confirm_signal(
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    spec: dict[str, Any],
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    generated_at: datetime,
) -> dict[str, Any] | None:
    """Unique FTD contract: long-pullback guard plus 1-2 bar confirmation.

    Market context and higher-timeframe quality remain audit fields.  They are
    intentionally not hidden blockers in this first isolated contract.
    """
    if len(rows) < 24:
        return None
    latest = rows[-1]
    entry = decimal(latest.get("next_bar_first_quote_price", "0"))
    entry_at = str(latest.get("next_bar_first_quote_at") or "")
    if entry <= ZERO or not entry_at:
        return None
    signal_bar: dict[str, Any] | None = None
    confirmation_count = 0
    for lag in (1, 2):
        signal_index = len(rows) - 1 - lag
        if signal_index < 21:
            continue
        candidate = rows[signal_index]
        previous = rows[signal_index - 1]
        gain = row_close_to_close_percent(previous, candidate)
        volume_ratio = row_volume_ratio(previous, candidate)
        if gain < Decimal("1.70") or volume_ratio < Decimal("1.15") or close_position(candidate) < Decimal("0.70"):
            continue
        follow = rows[signal_index + 1:]
        candidate_close = decimal(candidate.get("close", "0"))
        if any(decimal(row.get("close", "0")) < candidate_close for row in follow):
            continue
        if lag == 2 and decimal(follow[0].get("close", "0")) < candidate_close:
            continue
        signal_bar = candidate
        confirmation_count = lag
        break
    if signal_bar is None:
        return None
    signal_index = rows.index(signal_bar)
    preceding = rows[:signal_index]
    recent_high_index = max(
        range(max(0, len(preceding) - 60), len(preceding)),
        key=lambda index: decimal(preceding[index].get("high", "0")),
    )
    pullback_bars = signal_index - recent_high_index
    if pullback_bars > int(spec.get("max_pullback_bars", 20)):
        return None
    stop = decimal(signal_bar.get("low", "0"))
    signal = build_price_action_long_signal(
        detector_id="ftd001_pullback_guard_confirm_contract_v1",
        symbol=symbol,
        latest=latest,
        entry=entry,
        stop=stop,
        target_r=Decimal("2.00"),
        max_risk_percent=decimal(spec.get("max_risk_percent", "0")),
        order_type="limit",
        generated_at=generated_at,
    )
    if not signal:
        return None
    target_date = ny_event_date(latest)
    market_confirmed, market_symbols = market_follow_through_confirmed(grouped_events, target_date)
    signal.update(
        {
            "created_at": entry_at,
            "entry_timing": "next_bar_first_quote",
            "entry_price_source": str(latest.get("next_bar_entry_source") or "longbridge_sdk_first_quote_after_bar_close"),
            "contract_evidence": {
                "signal_bar_event_id": str(signal_bar.get("event_id") or ""),
                "pullback_bar_count": pullback_bars,
                "maximum_pullback_bars": int(spec.get("max_pullback_bars", 20)),
                "follow_through_bar_count": confirmation_count,
                "signal_bar_stop": fmt_money(stop),
                "target_model": "2R",
                "market_context_audit": "confirmed" if market_confirmed else "not_confirmed",
                "market_context_symbols": market_symbols,
                "market_context_is_blocker": False,
            },
            "market_confirmation_status": "audit_confirmed" if market_confirmed else "audit_not_confirmed",
            "market_confirmation_symbols": market_symbols,
            "pre_gate_blockers": [],
        }
    )
    return signal


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


def row_volume_ratio(previous: dict[str, Any], latest: dict[str, Any]) -> Decimal:
    previous_volume = decimal(previous.get("volume", "0"))
    latest_volume = decimal(latest.get("volume", "0"))
    if previous_volume <= ZERO or latest_volume <= ZERO:
        return ZERO
    return latest_volume / previous_volume


def row_close_to_close_percent(previous: dict[str, Any], latest: dict[str, Any]) -> Decimal:
    previous_close = decimal(previous.get("close", "0"))
    latest_close = decimal(latest.get("close", "0"))
    if previous_close <= ZERO or latest_close <= ZERO:
        return ZERO
    return (latest_close - previous_close) / previous_close * HUNDRED


def market_follow_through_confirmed(
    grouped_events: dict[tuple[str, str], list[dict[str, Any]]],
    target_date: str,
) -> tuple[bool, str]:
    confirmed: list[str] = []
    for symbol in ("SPY", "QQQ"):
        rows = grouped_events.get((symbol, "1d"), [])
        if len(rows) < 2:
            continue
        previous, latest = rows[-2], rows[-1]
        if target_date and ny_event_date(latest) != target_date:
            continue
        if (
            row_close_to_close_percent(previous, latest) >= Decimal("1.25")
            and row_volume_ratio(previous, latest) > Decimal("1.00")
            and close_position(latest) >= Decimal("0.60")
        ):
            confirmed.append(symbol)
    return bool(confirmed), ",".join(confirmed)


def base_quality_score(
    *,
    close_position_value: Decimal,
    close_to_close_percent: Decimal,
    volume_ratio: Decimal,
    reward_r: Decimal = ZERO,
    net_profit: Decimal = ZERO,
    risk_percent: Decimal = ZERO,
    market_confirmed: bool = False,
) -> Decimal:
    score = ZERO
    score += min(max(close_position_value, ZERO), Decimal("1")) * Decimal("35")
    score += min(max(close_to_close_percent, ZERO), Decimal("5")) / Decimal("5") * Decimal("20")
    score += min(max(volume_ratio - Decimal("1"), ZERO), Decimal("1")) * Decimal("15")
    score += min(max(reward_r - Decimal("1"), ZERO), Decimal("2")) / Decimal("2") * Decimal("10")
    score += min(max(net_profit, ZERO), Decimal("40")) / Decimal("40") * Decimal("10")
    if risk_percent > ZERO:
        score += max(Decimal("0"), Decimal("10") - min(risk_percent, Decimal("10")))
    if market_confirmed:
        score += Decimal("10")
    return min(score, Decimal("100"))


def realtime_intent_sort_key(intent: dict[str, Any]) -> tuple[int, str, Decimal, Decimal, Decimal, Decimal, str]:
    side = str(intent.get("side") or intent.get("direction") or "").lower()
    sell_priority = 0 if side in {"sell", "close", "exit_long", "stop_loss", "take_profit"} else 1
    return (
        sell_priority,
        str(intent.get("capital_bucket") or ""),
        -decimal(intent.get("relative_strength_rank_score", "0")),
        -decimal(intent.get("quality_score", intent.get("signal_quality_score", "0"))),
        -decimal(intent.get("net_profit_after_fees_at_target", "0")),
        -decimal(intent.get("reward_r", "0")),
        str(intent.get("symbol") or ""),
    )


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
    volume_ratio = row_volume_ratio(previous, latest)
    strong_followthrough = close_to_close_percent >= Decimal("3.00")
    strong_gap_hold = gap_percent >= Decimal("2.50") and close_to_close_percent >= Decimal("1.50")
    if not (strong_followthrough or strong_gap_hold):
        return None
    min_close_position = Decimal("0.65") if strong_gap_hold and not strong_followthrough else Decimal("0.60")
    pre_gate_blockers: list[str] = []
    if close_position < min_close_position:
        pre_gate_blockers.append("blocked_close_position_below_runtime_minimum")
    if volume_ratio < Decimal("1.10"):
        pre_gate_blockers.append("blocked_volume_ratio_below_runtime_minimum")
    entry = close
    risk = max(entry - low, entry * Decimal("0.025"))
    if risk <= ZERO:
        return None
    stop = entry - risk
    target = entry + risk * Decimal("2")
    risk_percent = risk / entry * HUNDRED
    quality_score = base_quality_score(
        close_position_value=close_position,
        close_to_close_percent=close_to_close_percent,
        volume_ratio=volume_ratio,
        reward_r=Decimal("2"),
        net_profit=target - entry,
        risk_percent=risk_percent,
        market_confirmed=False,
    )
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
        "close_position": fmt_decimal(close_position),
        "close_to_close_percent": fmt_decimal(close_to_close_percent),
        "gap_percent": fmt_decimal(gap_percent),
        "volume_ratio": fmt_decimal(volume_ratio),
        "market_confirmation_status": "not_required",
        "market_confirmation_symbols": "",
        "pre_gate_blockers": pre_gate_blockers,
        "quality_score": fmt_decimal(quality_score),
        "signal_quality_score": fmt_decimal(quality_score),
        "quality_score_components": {
            "close_position": fmt_decimal(close_position),
            "close_to_close_percent": fmt_decimal(close_to_close_percent),
            "gap_percent": fmt_decimal(gap_percent),
            "volume_ratio": fmt_decimal(volume_ratio),
            "reward_r": "2",
            "risk_percent": fmt_decimal(risk_percent),
            "volume_requirement": "1.10",
            "minimum_close_position": fmt_decimal(min_close_position),
        },
        "high_quality_signal": quality_score >= Decimal("80"),
    }


def pa004_momentum_variant_signal(
    symbol: str,
    previous: dict[str, Any],
    latest: dict[str, Any],
    *,
    thresholds: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if symbol in {"SQQQ", "TQQQ"}:
        return None
    previous_close = decimal(previous.get("close", "0"))
    open_price = decimal(latest.get("open", "0"))
    high = decimal(latest.get("high", "0"))
    low = decimal(latest.get("low", "0"))
    close = decimal(latest.get("close", "0"))
    if min(previous_close, open_price, high, low, close) <= ZERO or high <= low:
        return None
    close_to_close_percent = (close - previous_close) / previous_close * HUNDRED
    gap_percent = (open_price - previous_close) / previous_close * HUNDRED
    close_position_value = (close - low) / (high - low)
    strong_followthrough = close_to_close_percent >= decimal(thresholds["min_close_to_close_percent"])
    strong_gap_hold = (
        gap_percent >= decimal(thresholds["min_gap_percent"])
        and close_to_close_percent >= decimal(thresholds["min_gap_close_to_close_percent"])
    )
    if not (strong_followthrough or strong_gap_hold):
        return None
    if close_position_value < decimal(thresholds["min_close_position"]):
        return None
    next_quote = decimal(latest.get("next_bar_first_quote_price", "0"))
    next_quote_at = str(latest.get("next_bar_first_quote_at") or "")
    if thresholds.get("require_next_bar_quote") and (next_quote <= ZERO or not next_quote_at):
        return None
    entry = next_quote if next_quote > ZERO else close
    entry_at = next_quote_at or str(latest.get("received_at") or to_iso(generated_at))
    volume_ratio = row_volume_ratio(previous, latest)
    minimum_volume_ratio = decimal(thresholds.get("min_volume_ratio", "0"))
    if minimum_volume_ratio > ZERO and volume_ratio < minimum_volume_ratio:
        return None
    risk = max(entry - low, entry * Decimal("0.025"))
    if risk <= ZERO:
        return None
    risk_percent = risk / entry * HUNDRED
    max_risk_percent = decimal(thresholds.get("max_risk_percent", "0"))
    if max_risk_percent > ZERO and risk_percent > max_risk_percent:
        return None
    target_r = decimal(thresholds["target_r"])
    quality_score = base_quality_score(
        close_position_value=close_position_value,
        close_to_close_percent=close_to_close_percent,
        volume_ratio=volume_ratio,
        reward_r=target_r,
        net_profit=risk * target_r,
        risk_percent=risk_percent,
        market_confirmed=False,
    )
    strategy_id = str(thresholds["strategy_id"])
    return {
        "detector_id": (
            "pa004_momentum_breakout_quality_confirmed_realtime"
            if strategy_id.endswith("-QC")
            else "pa004_momentum_breakout_followthrough_realtime"
        ),
        "symbol": symbol,
        "direction": "long",
        "side": "buy",
        "order_type": "limit",
        "limit_price": fmt_money(entry),
        "stop_price": fmt_money(entry - risk),
        "target_price": fmt_money(entry + risk * target_r),
        "current_price": fmt_money(entry),
        "source_market_event_id": str(latest.get("event_id") or latest.get("market_event_id") or ""),
        "market_event_time": str(latest.get("event_time") or latest.get("bar_time") or latest.get("timestamp") or ""),
        "created_at": entry_at,
        "entry_timing": "next_bar_first_quote",
        "entry_price_source": str(latest.get("next_bar_entry_source") or "longbridge_sdk_first_quote_after_bar_close"),
        "signal_validity_seconds": "900",
        "close_position": fmt_decimal(close_position_value),
        "close_to_close_percent": fmt_decimal(close_to_close_percent),
        "gap_percent": fmt_decimal(gap_percent),
        "volume_ratio": fmt_decimal(volume_ratio),
        "quality_score": fmt_decimal(quality_score),
        "signal_quality_score": fmt_decimal(quality_score),
        "high_quality_signal": quality_score >= Decimal("80"),
        "market_confirmation_status": "not_required",
        "pre_gate_blockers": [],
        "contract_evidence": {
            "strong_followthrough": strong_followthrough,
            "strong_gap_hold": strong_gap_hold,
            "close_position": fmt_decimal(close_position_value),
            "volume_ratio": fmt_decimal(volume_ratio),
            "volume_mode": "audit_only",
            "maximum_risk_percent": fmt_decimal(max_risk_percent),
            "target_model": "1.5R",
            "entry_order_ttl_seconds": 900,
        },
    }


def build_signal_from_intent(
    *,
    config: RealtimeSignalRouterConfig,
    intent: dict[str, Any],
    generated_at: datetime,
    session_started_at: str,
    test_epoch_state: dict[str, Any],
    capital_bucket_migration_state: dict[str, str],
    existing_signal_ids: set[str],
    existing_structure_ids: set[str],
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
    direction = normalize_direction(intent.get("direction") or intent.get("side"))
    is_short = direction == "short"
    effective_epoch_state = short_test_epoch_state(config) if is_short else test_epoch_state
    epoch_id = str(effective_epoch_state.get("test_epoch_id") or "")
    structure_instance_id = realtime_structure_instance_id(
        intent,
        runtime_id=runtime_id,
        symbol=symbol,
        direction=str(intent.get("direction") or intent.get("side") or ""),
        created_at=created_at,
        source_event_id=source_event_id,
    )
    if epoch_id:
        structure_instance_id = f"{structure_instance_id}-{epoch_id}"
    epoch_started_at = parse_epoch_started_at(effective_epoch_state)
    original_created_dt = parse_optional_utc_datetime(original_created_at)
    if (
        epoch_id
        and str(effective_epoch_state.get("status") or "") in {"active", "activated"}
        and epoch_started_at is not None
        and original_created_dt is not None
        and original_created_dt < epoch_started_at
        and generated_at >= epoch_started_at
    ):
        if is_short:
            # Short test rows are never rebuilt from a pre-baseline event.
            # A new bar must produce the fresh short intent itself.
            pass
        else:
            signal_id = f"{base_signal_id}-{epoch_id}"
            created_at = to_iso(generated_at)
            rebuilt_after_epoch_activation = True
    if epoch_id and epoch_started_at is not None and original_created_dt is not None:
        structure_phase = (
            "active"
            if generated_at >= epoch_started_at
            else "prebaseline"
        )
        structure_instance_id = f"{structure_instance_id}-{structure_phase}"
    side = "buy" if direction == "long" else "sell_short"
    order_type = normalize_order_type(intent.get("order_type"))
    entry = decimal(intent.get("limit_price", intent.get("entry_price", intent.get("current_price", "0"))))
    stop = decimal(intent.get("stop_price", "0"))
    target = decimal(intent.get("target_price", "0"))
    current = decimal(intent.get("current_price", entry))
    blockers = strategy_isolation_blockers(runtime_id, strategy_id, config.allowed_runtime_ids)
    if isinstance(intent.get("pre_gate_blockers"), list):
        blockers.extend(str(item) for item in intent.get("pre_gate_blockers", []) if str(item))
    if not source_event_id:
        blockers.append("missing_source_market_event_id")
    if not runtime_id:
        blockers.append("missing_runtime_id")
    if not bucket:
        blockers.append("blocked_missing_capital_bucket")
    if not symbol:
        blockers.append("missing_symbol")
    if signal_id in existing_signal_ids:
        blockers.append("duplicate_signal_event")
    if structure_instance_id and structure_instance_id in existing_structure_ids:
        blockers.append("duplicate_structure_instance")
    try:
        session_started_dt = parse_utc_datetime(session_started_at)
        if parse_utc_datetime(created_at) < session_started_dt:
            blockers.append("blocked_replay_market_event_before_session_start")
        if original_created_dt is not None and original_created_dt < session_started_dt:
            blockers.append("blocked_replay_market_event_before_session_start")
    except ValueError:
        blockers.append("invalid_signal_created_at")
    if is_short and (
        not config.allow_short_selling
        or not config.paper_short_testing_enabled
        or runtime_id not in set(config.paper_short_runtime_ids)
    ):
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
    if (not is_short and target <= entry) or (is_short and target >= entry):
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
    gross_profit = ((entry - target) if is_short else (target - entry)) * quantity
    fees = config.commission_per_order_side * Decimal("2") + config.regulatory_fee_per_sell_order
    net_profit = gross_profit - fees
    reward_r = short_reward_r_ratio(entry, stop, target) if is_short else reward_r_ratio(entry, stop, target)
    intent_quality_score = decimal(intent.get("quality_score", intent.get("signal_quality_score", "0")))
    relative_strength_rank_score = decimal(intent.get("relative_strength_rank_score", "0"))
    minimum_reward_r = runtime_minimum_reward_r(config, runtime_id, strategy_id)
    minimum_net_profit = runtime_minimum_net_profit(config, runtime_id, strategy_id)
    minimum_quality_score = decimal(intent.get("minimum_quality_score", "0")) if is_short else ZERO
    profit_gate_status = profit_quality_gate(config, intent, net_profit, runtime_id, strategy_id)
    capital_bucket_migration_status = capital_bucket_migration_state.get(capital_bucket, "")
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
    if is_short and intent_quality_score < minimum_quality_score:
        blockers.append("blocked_short_quality_score_below_minimum")
    if (
        capital_bucket_migration_status == "pending_cleanup"
        and capital_bucket in {"pa004_mbf", "pa004_mbf_qc"}
        and intent_is_open_entry(intent)
    ):
        blockers.append("blocked_capital_bucket_pending_cleanup")
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
        "structure_instance_id": structure_instance_id,
        "created_at": created_at,
        "processed_at": to_iso(generated_at),
        "detector_id": str(intent.get("detector_id") or "embedded_signal_intent"),
        "strategy_contract_hash": str(intent.get("strategy_contract_hash") or ""),
        "strategy_contract_stage": str(intent.get("strategy_contract_stage") or ""),
        "strategy_contract_stage_zh": str(intent.get("strategy_contract_stage_zh") or ""),
        "strategy_contract_schema_version": str(intent.get("strategy_contract_schema_version") or ""),
        "entry_timing": str(intent.get("entry_timing") or ""),
        "entry_price_source": str(intent.get("entry_price_source") or ""),
        "contract_evidence": dict(intent.get("contract_evidence") or {})
        if isinstance(intent.get("contract_evidence"), dict)
        else {},
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
        "quality_score": fmt_decimal(intent_quality_score),
        "signal_quality_score": fmt_decimal(intent_quality_score),
        "relative_strength_rank_score": fmt_decimal(relative_strength_rank_score),
        "market_relative_strength_percent": str(intent.get("market_relative_strength_percent") or ""),
        "market_strength_percent": str(intent.get("market_strength_percent") or ""),
        "sector_relative_strength_percent": str(intent.get("sector_relative_strength_percent") or ""),
        "sector_strength_percent": str(intent.get("sector_strength_percent") or ""),
        "candidate_return_percent": str(intent.get("candidate_return_percent") or ""),
        "relative_strength_audit_state": str(intent.get("relative_strength_audit_state") or ""),
        "industry_strength_scope": str(intent.get("industry_strength_scope") or ""),
        "quality_score_components": intent.get("quality_score_components", {})
        if isinstance(intent.get("quality_score_components"), dict)
        else {},
        "market_confirmation_status": str(intent.get("market_confirmation_status") or ""),
        "market_confirmation_symbols": str(intent.get("market_confirmation_symbols") or ""),
        "repair_rule_id": str(intent.get("repair_rule_id") or ""),
        "source_breakout_entry_price": str(intent.get("source_breakout_entry_price") or ""),
        "latest_confirms_entry": bool(intent.get("latest_confirms_entry", False)),
        "next_market_day_timeout": bool(intent.get("next_market_day_timeout", False)),
        "close_position": str(intent.get("close_position") or ""),
        "close_to_close_percent": str(intent.get("close_to_close_percent") or ""),
        "gap_percent": str(intent.get("gap_percent") or ""),
        "volume_ratio": str(intent.get("volume_ratio") or ""),
        "minimum_reward_r": fmt_decimal(minimum_reward_r),
        "minimum_net_profit_after_fees": fmt_money(minimum_net_profit),
        "minimum_quality_score": fmt_decimal(minimum_quality_score),
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
        "capital_bucket_migration_status": capital_bucket_migration_status,
        "additional_bucket_route": bool(intent.get("additional_bucket_route", False)),
        "primary_capital_bucket": str(intent.get("primary_capital_bucket") or ""),
        "test_epoch_id": epoch_id,
        "test_epoch_status": str(effective_epoch_state.get("status") or ""),
        "test_started_at": str(effective_epoch_state.get("test_started_at") or ""),
        "original_signal_created_at": original_created_at if rebuilt_after_epoch_activation else "",
        "realtime_rebuilt_after_epoch_activation": rebuilt_after_epoch_activation,
        "local_simulation_ignored": True,
        "direction": direction,
        "position_action": str(intent.get("position_action") or ("open_short" if is_short else "open_long")),
        "fast_queue_used": False,
    }
    if blockers:
        return row, None
    signal = {
        "signal_id": signal_id,
        "structure_instance_id": structure_instance_id,
        "created_at": created_at,
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "strategy_contract_hash": str(intent.get("strategy_contract_hash") or ""),
        "strategy_contract_stage": str(intent.get("strategy_contract_stage") or ""),
        "strategy_contract_stage_zh": str(intent.get("strategy_contract_stage_zh") or ""),
        "strategy_contract_schema_version": str(intent.get("strategy_contract_schema_version") or ""),
        "capital_bucket": capital_bucket,
        "capital_bucket_label": bucket_label,
        "test_epoch_id": epoch_id,
        "test_epoch_status": str(effective_epoch_state.get("status") or ""),
        "test_started_at": str(effective_epoch_state.get("test_started_at") or ""),
        "original_signal_created_at": original_created_at if rebuilt_after_epoch_activation else "",
        "realtime_rebuilt_after_epoch_activation": rebuilt_after_epoch_activation,
        "symbol": symbol,
        "timeframe": str(intent.get("timeframe") or ""),
        "direction": direction,
        "side": side,
        "position_action": str(intent.get("position_action") or ("open_short" if is_short else "open_long")),
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
        "quality_score": fmt_decimal(intent_quality_score),
        "signal_quality_score": fmt_decimal(intent_quality_score),
        "relative_strength_rank_score": fmt_decimal(relative_strength_rank_score),
        "market_relative_strength_percent": str(intent.get("market_relative_strength_percent") or ""),
        "market_strength_percent": str(intent.get("market_strength_percent") or ""),
        "sector_relative_strength_percent": str(intent.get("sector_relative_strength_percent") or ""),
        "sector_strength_percent": str(intent.get("sector_strength_percent") or ""),
        "candidate_return_percent": str(intent.get("candidate_return_percent") or ""),
        "relative_strength_audit_state": str(intent.get("relative_strength_audit_state") or ""),
        "industry_strength_scope": str(intent.get("industry_strength_scope") or ""),
        "quality_score_components": intent.get("quality_score_components", {})
        if isinstance(intent.get("quality_score_components"), dict)
        else {},
        "market_confirmation_status": str(intent.get("market_confirmation_status") or ""),
        "market_confirmation_symbols": str(intent.get("market_confirmation_symbols") or ""),
        "repair_rule_id": str(intent.get("repair_rule_id") or ""),
        "source_breakout_entry_price": str(intent.get("source_breakout_entry_price") or ""),
        "latest_confirms_entry": bool(intent.get("latest_confirms_entry", False)),
        "next_market_day_timeout": bool(intent.get("next_market_day_timeout", False)),
        "close_position": str(intent.get("close_position") or ""),
        "close_to_close_percent": str(intent.get("close_to_close_percent") or ""),
        "gap_percent": str(intent.get("gap_percent") or ""),
        "volume_ratio": str(intent.get("volume_ratio") or ""),
        "minimum_reward_r": fmt_decimal(minimum_reward_r),
        "minimum_net_profit_after_fees": fmt_money(minimum_net_profit),
        "minimum_quality_score": fmt_decimal(minimum_quality_score),
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
        "capital_bucket_migration_status": capital_bucket_migration_status,
        "additional_bucket_route": bool(intent.get("additional_bucket_route", False)),
        "primary_capital_bucket": str(intent.get("primary_capital_bucket") or ""),
        "source_market_event_id": source_event_id,
        "market_event_time": str(intent.get("market_event_time") or ""),
        "entry_timing": str(intent.get("entry_timing") or ""),
        "entry_price_source": str(intent.get("entry_price_source") or ""),
        "contract_evidence": dict(intent.get("contract_evidence") or {})
        if isinstance(intent.get("contract_evidence"), dict)
        else {},
        "short_structure_low": str(intent.get("short_structure_low") or ""),
        "signal_validity_seconds": str(intent.get("signal_validity_seconds") or "5"),
        "local_simulation_source": False,
        "fast_queue_source": False,
    }
    return row, signal


def strategy_isolation_blockers(runtime_id: str, strategy_id: str, allowed_runtime_ids: tuple[str, ...]) -> list[str]:
    lowered = runtime_id.lower()
    repair_allowed = runtime_id in LONG_BRIDGE_ALLOWED_REPAIR_RUNTIME_IDS and runtime_id in set(
        allowed_runtime_ids
    )
    if runtime_id in REPAIR_RUNTIME_IDS and not repair_allowed:
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
        and not repair_allowed
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


def realtime_structure_instance_id(
    intent: dict[str, Any],
    *,
    runtime_id: str,
    symbol: str,
    direction: str,
    created_at: str,
    source_event_id: str,
) -> str:
    """Identify one executable structure independently from polling events.

    Daily contracts normally receive an explicit episode identity from
    ``assign_daily_structure_episode_ids``. The date-level fallback is only a
    conservative compatibility path. Intraday contracts keep the source event
    identity.
    """
    explicit = str(intent.get("structure_instance_id") or "").strip()
    if explicit:
        return explicit
    timeframe = str(intent.get("timeframe") or "").strip().lower()
    if timeframe == "1d":
        created = parse_optional_utc_datetime(created_at)
        trading_date = (
            created.astimezone(NEW_YORK).date().isoformat()
            if created is not None
            else created_at[:10]
        )
        material = f"daily|{runtime_id}|{symbol}|{direction}|{trading_date}"
    else:
        material = f"intraday|{runtime_id}|{symbol}|{direction}|{source_event_id}|{created_at}"
    return f"m15-structure-{sha256(material.encode('utf-8')).hexdigest()[:20]}"


def assign_daily_structure_episode_ids(
    intents: list[dict[str, Any]],
    detector_attempts: list[dict[str, Any]],
    previous_state: dict[str, Any],
    *,
    generated_at: datetime,
    long_test_epoch_id: str,
    short_test_epoch_id: str,
    active_market_event_ids: set[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Keep one id while a daily setup remains true, then re-arm after reset.

    A later five-minute poll is not a new setup by itself. A daily detector must
    first report no candidate on a completed evaluation cycle; if the setup
    subsequently becomes valid again, that transition starts a new episode and
    may trade again subject to normal position, order and exposure checks.
    """
    current_date = generated_at.astimezone(NEW_YORK).date().isoformat()
    previous = {
        str(key): dict(value)
        for key, value in previous_state.items()
        if isinstance(value, dict)
        and str(value.get("trading_date") or "") == current_date
    }
    next_state = dict(previous)

    reset_keys: set[str] = set()
    for attempt in detector_attempts:
        if str(attempt.get("timeframe") or "").lower() != "1d":
            continue
        if attempt.get("candidate_emitted") is not False:
            continue
        source_event_id = str(attempt.get("source_market_event_id") or "")
        if (
            active_market_event_ids is not None
            and source_event_id not in active_market_event_ids
        ):
            continue
        runtime_id = str(attempt.get("runtime_id") or "")
        symbol = str(attempt.get("symbol") or "").upper()
        if not runtime_id or not symbol:
            continue
        epoch_id = long_test_epoch_id
        reset_keys.add(
            daily_structure_episode_key(
                epoch_id=epoch_id,
                runtime_id=runtime_id,
                symbol=symbol,
                direction="long",
                trading_date=current_date,
            )
        )
    for key in reset_keys:
        next_state.pop(key, None)

    for intent in intents:
        if str(intent.get("timeframe") or "").strip().lower() != "1d":
            continue
        runtime_id = str(intent.get("runtime_id") or "")
        symbol = str(intent.get("symbol") or "").upper()
        direction = normalize_direction(intent.get("direction") or intent.get("side"))
        if not runtime_id or not symbol or direction not in {"long", "short"}:
            continue
        created_at = str(intent.get("created_at") or to_iso(generated_at))
        created = parse_optional_utc_datetime(created_at)
        trading_date = (
            created.astimezone(NEW_YORK).date().isoformat()
            if created is not None
            else current_date
        )
        epoch_id = short_test_epoch_id if direction == "short" else long_test_epoch_id
        key = daily_structure_episode_key(
            epoch_id=epoch_id,
            runtime_id=runtime_id,
            symbol=symbol,
            direction=direction,
            trading_date=trading_date,
        )
        existing = previous.get(key, {})
        structure_instance_id = str(existing.get("structure_instance_id") or "")
        if not structure_instance_id:
            source_event_id = str(
                intent.get("source_market_event_id")
                or intent.get("market_event_id")
                or ""
            )
            material = (
                f"daily-episode|{key}|{source_event_id}|{created_at}"
            )
            structure_instance_id = (
                f"m15-structure-{sha256(material.encode('utf-8')).hexdigest()[:20]}"
            )
        intent["structure_instance_id"] = structure_instance_id
        next_state[key] = {
            "structure_instance_id": structure_instance_id,
            "test_epoch_id": epoch_id,
            "runtime_id": runtime_id,
            "symbol": symbol,
            "direction": direction,
            "trading_date": trading_date,
            "episode_started_at": str(
                existing.get("episode_started_at") or created_at
            ),
            "latest_source_market_event_id": str(
                intent.get("source_market_event_id")
                or intent.get("market_event_id")
                or ""
            ),
        }
    return next_state


def daily_structure_episode_key(
    *,
    epoch_id: str,
    runtime_id: str,
    symbol: str,
    direction: str,
    trading_date: str,
) -> str:
    return "|".join(
        (epoch_id, runtime_id, symbol, direction, trading_date)
    )


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
    if str(epoch_state.get("status") or "") not in {"active", "activated"}:
        return None
    return parse_optional_utc_datetime(str(epoch_state.get("test_started_at") or epoch_state.get("activated_at") or ""))


def normalize_active_epoch_state(epoch_state: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(epoch_state) if isinstance(epoch_state, dict) else {}
    if str(normalized.get("status") or "") == "activated":
        normalized["status"] = "active"
    if str(normalized.get("status") or "") == "active" and not normalized.get("test_started_at"):
        activated_at = str(normalized.get("activated_at") or "")
        if parse_optional_utc_datetime(activated_at):
            normalized["test_started_at"] = activated_at
    return normalized


def short_test_epoch_state(config: RealtimeSignalRouterConfig) -> dict[str, Any]:
    return {
        "enabled": config.paper_short_testing_enabled,
        "status": "active" if config.paper_short_testing_enabled else "disabled",
        "test_epoch_id": config.short_test_epoch_id,
        "test_started_at": config.short_test_started_at,
        "position_direction": "short",
    }


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


def short_reward_r_ratio(entry: Decimal, stop: Decimal, target: Decimal) -> Decimal:
    risk = stop - entry
    reward = entry - target
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
    if ZERO < score <= Decimal("1"):
        return score >= Decimal("0.8")
    return score >= Decimal("80")


def intent_is_open_entry(intent: dict[str, Any]) -> bool:
    position_action = str(intent.get("position_action") or "").strip().lower()
    if position_action:
        return position_action.startswith("open")
    side = str(intent.get("side") or "").strip().lower()
    if side in {"sell", "close", "exit_long", "stop_loss", "take_profit"}:
        return False
    return True


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


def read_jsonl_tail(path: Path, count: int, *, block_size: int = 65536) -> list[dict[str, Any]]:
    """Parse only the newest JSONL rows used by the realtime router."""
    if not path.exists() or count <= 0:
        return []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        chunks: list[bytes] = []
        newline_count = 0
        while position > 0 and newline_count <= count:
            read_size = min(block_size, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")
    lines = b"".join(reversed(chunks)).decode("utf-8", errors="replace").splitlines()
    return [json.loads(line) for line in lines[-count:] if line.strip()]


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


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.touch(exist_ok=True)
        return
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(json_ready(row), ensure_ascii=False, sort_keys=True)
                + "\n"
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
