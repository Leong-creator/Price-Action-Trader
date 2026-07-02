#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.longbridge_cli_env import build_longbridge_cli_env
from scripts.m12_readonly_auth_preflight_lib import clean_cli_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DAILY_DIR = (
    ROOT
    / "reports"
    / "strategy_lab"
    / "m10_price_action_strategy_refresh"
    / "daily_observation"
)
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_execution.json"
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_SIGNAL_EVENTS = DEFAULT_OUTPUT_DIR / "m15_realtime_signal_events.jsonl"
DEFAULT_ACCOUNT_STATE = (
    DEFAULT_OUTPUT_DIR
    / "m15_longbridge_realtime_account_state.json"
)
DEFAULT_EPOCH_STATE = DEFAULT_OUTPUT_DIR / "m15_longbridge_virtual_account_epoch.json"
SUMMARY_JSON = "m15_longbridge_realtime_execution.json"
LEDGER_JSONL = "m15_longbridge_realtime_execution_ledger.jsonl"
REPORT_MD = "m15_longbridge_realtime_execution.md"
MONEY = Decimal("0.01")
ZERO = Decimal("0")
FLATTEN_CURRENT_PRICE_SELL_LIMIT_MULTIPLIER = Decimal("0.995")
FLATTEN_FALLBACK_COST_SELL_LIMIT_MULTIPLIER = Decimal("0.95")
OPTION_SYMBOL_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")
NEW_YORK = ZoneInfo("America/New_York")

DEFAULT_REALTIME_RUNTIME_IDS = (
    "M10-PA-004-long-1d",
    "M10-PA-002-1d",
    "M10-PA-002-5m",
    "M10-PA-004-MBF-1d",
    "M10-PA-004-MBF-QC-1d",
    "M10-PA-013-1d",
    "M10-PA-013-5m",
    "M10-PA-005-1d",
    "M10-PA-005-5m",
    "M10-PA-008-1d",
    "M10-PA-012-5m",
    "M12-FTD-001-baseline-1d",
    "M12-FTD-001-loss-streak-guard-1d",
    "M10-PA-001-1d",
    "M10-PA-011-ORB-R1-5m",
)

EXPERIMENT_CAPITAL_BUCKET_RUNTIME_IDS = (
    "M10-PA-002-1d",
    "M10-PA-013-1d",
    "M10-PA-005-1d",
    "M10-PA-005-5m",
    "M10-PA-008-1d",
    "M10-PA-012-5m",
    "M10-PA-001-1d",
)

SINGLE_STRATEGY_CAPITAL_BUCKET_SPECS = (
    ("pa004_long", "PA004-long单仓", "M10-PA-004-long-1d"),
    ("pa002_5m", "PA002-5m单仓", "M10-PA-002-5m"),
    ("ftd_baseline", "FTD原版单仓", "M12-FTD-001-baseline-1d"),
    ("ftd_loss_streak", "FTD连亏保护单仓", "M12-FTD-001-loss-streak-guard-1d"),
    ("pa004_mbf", "PA004-MBF单仓", "M10-PA-004-MBF-1d"),
    ("pa004_mbf_qc", "PA004-MBF-QC单仓", "M10-PA-004-MBF-QC-1d"),
    ("pa013_5m", "PA013-5m单仓", "M10-PA-013-5m"),
    ("pa011_orb_r1", "PA011-ORB-R1单仓", "M10-PA-011-ORB-R1-5m"),
)

AUXILIARY_STRATEGY_IDS = {
    "M10-PA-003",
    "M10-PA-006",
    "M10-PA-010",
    "M10-PA-014",
    "M10-PA-015",
    "M10-PA-016",
    "AI-TRADER-EXTERNAL",
}

REPAIR_RUNTIME_IDS = {
    "M10-PA-001-5m",
    "M10-PA-007-1d",
    "M10-PA-009-1d",
    "M10-PA-011-5m",
}

SHADOW_RUNTIME_MARKERS = (
    "m14-modify",
    "broker-risk-cap-shadow",
    "target-stop-shadow",
    "loss-streak-guard",
    "target_stop_shadow",
    "risk_cap_shadow",
    "shadow",
    "repair",
)

LONG_BRIDGE_ALLOWED_LOSS_STREAK_RUNTIME_IDS = {
    "M12-FTD-001-loss-streak-guard-1d",
}

LONG_BRIDGE_ALLOWED_SHADOW_RUNTIME_IDS = {
    "M10-PA-004-MBF-1d",
    "M10-PA-004-MBF-QC-1d",
}


@dataclass(frozen=True, slots=True)
class QuantityNormalization:
    raw_quantity: Decimal
    submitted_quantity: Decimal
    rounded_down_quantity: Decimal
    status: str
    blocker: str


def normalize_whole_share_quantity(raw_quantity: Decimal, allow_fractional_shares: bool) -> QuantityNormalization:
    if allow_fractional_shares:
        return QuantityNormalization(
            raw_quantity=raw_quantity,
            submitted_quantity=raw_quantity,
            rounded_down_quantity=ZERO,
            status="fractional_allowed",
            blocker="",
        )
    if raw_quantity < Decimal("1"):
        return QuantityNormalization(
            raw_quantity=raw_quantity,
            submitted_quantity=ZERO,
            rounded_down_quantity=raw_quantity if raw_quantity > ZERO else ZERO,
            status="below_one_share_blocked",
            blocker="blocked_quantity_below_one_share",
        )
    submitted_quantity = raw_quantity.to_integral_value(rounding=ROUND_FLOOR)
    rounded_down_quantity = raw_quantity - submitted_quantity
    status = "rounded_down_to_whole_share" if rounded_down_quantity > ZERO else "whole_share"
    return QuantityNormalization(
        raw_quantity=raw_quantity,
        submitted_quantity=submitted_quantity,
        rounded_down_quantity=rounded_down_quantity,
        status=status,
        blocker="",
    )


@dataclass(frozen=True, slots=True)
class VirtualCapitalBucket:
    bucket_id: str
    label: str
    equity: Decimal
    max_total_exposure: Decimal
    max_symbol_exposure: Decimal
    max_risk_per_order: Decimal
    min_cash_reserve: Decimal
    daily_new_symbol_limit: int
    runtime_daily_new_symbol_limits: dict[str, int]
    runtime_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RealtimeExecutionConfig:
    stage: str
    title: str
    realtime_signal_events_path: Path
    paper_account_state_path: Path
    output_dir: Path
    required_account_channel: str
    cli_name: str
    cli_timeout_seconds: int
    time_in_force: str
    outside_rth: str
    execute_orders: bool
    paper_trading_approval: bool
    session_started_at: str
    allow_replay: bool
    watch_interval_seconds: int
    latency_target_ms: int
    latency_acceptable_ms: int
    max_delayed_signal_age_seconds: int
    allowed_runtime_ids: tuple[str, ...]
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
    daily_new_symbol_limit_by_strategy: dict[str, int]
    virtual_capital_buckets: dict[str, VirtualCapitalBucket]
    runtime_capital_bucket_map: dict[str, str]
    test_epoch_enabled: bool
    test_epoch_id: str
    test_epoch_state_path: Path
    flatten_existing_positions_before_new_epoch: bool
    archive_previous_records: bool
    hard_boundaries: dict[str, bool]

    def __post_init__(self) -> None:
        validate_config(self)


class NullRealtimePaperClient:
    def submit_order(self, order_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "submitted": False,
            "status": "dry_run_client_unavailable",
            "order_id": "",
            "order_payload": order_payload,
        }


class LongbridgeCliRealtimePaperClient:
    def __init__(
        self,
        config: RealtimeExecutionConfig,
        *,
        command_runner: Any | None = None,
        cli_path: str | None = None,
    ) -> None:
        self.config = config
        self.command_runner = command_runner or run_longbridge_command
        self.cli_path = cli_path or shutil.which(config.cli_name) or config.cli_name

    def submit_order(self, order_payload: dict[str, Any]) -> dict[str, Any]:
        command, blockers = longbridge_order_command(self.config, self.cli_path, order_payload)
        if blockers:
            return {
                "submitted": False,
                "status": "blocked_order_command",
                "blockers": blockers,
                "command": redact_command(command),
            }
        result = self.command_runner(command)
        returncode = int(getattr(result, "returncode", 1))
        stdout = str(getattr(result, "stdout", ""))
        stderr = clean_cli_text(str(getattr(result, "stderr", "")))
        if returncode != 0:
            return {
                "submitted": False,
                "status": "submit_failed",
                "error": (stderr or clean_cli_text(stdout))[:300],
                "command": redact_command(command),
            }
        response = parse_json(stdout)
        order_id = str(response.get("order_id", response.get("id", ""))) if isinstance(response, dict) else ""
        if not order_id:
            account_state_match = self.find_recent_matching_order(order_payload)
            if account_state_match:
                return {
                    "submitted": True,
                    "status": "submitted",
                    "confirmation_source": "account_state_lookup",
                    "order_id": str(account_state_match.get("order_id") or account_state_match.get("id") or ""),
                    "response": response,
                    "matched_order": account_state_match,
                    "command": redact_command(command),
                }
            return {
                "submitted": False,
                "status": "submit_unconfirmed_missing_order_id",
                "order_id": "",
                "response": response,
                "command": redact_command(command),
                "error": "Longbridge CLI returned success code but no order_id; treat as unconfirmed, not filled/submitted.",
            }
        return {
            "submitted": True,
            "status": "submitted",
            "order_id": order_id,
            "response": response,
            "command": redact_command(command),
        }

    def find_recent_matching_order(self, order_payload: dict[str, Any]) -> dict[str, Any]:
        command = [self.cli_path, "order", "--format", "json"]
        result = self.command_runner(command)
        if int(getattr(result, "returncode", 1)) != 0:
            return {}
        payload = parse_json(str(getattr(result, "stdout", "")))
        if not isinstance(payload, list):
            return {}
        symbol = longbridge_symbol(str(order_payload.get("symbol") or ""))
        side = str(order_payload.get("side") or "").strip().lower()
        quantity = decimal(order_payload.get("quantity", "0"))
        limit_price = decimal(order_payload.get("limit_price", "0"))
        candidates: list[dict[str, Any]] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            if str(row.get("order_id") or row.get("id") or "") == "":
                continue
            if str(row.get("symbol") or "") != symbol:
                continue
            if str(row.get("side") or "").strip().lower() != side:
                continue
            if decimal(row.get("quantity", "0")) != quantity:
                continue
            row_price = decimal(row.get("price", row.get("limit_price", row.get("executed_price", "0"))))
            if row_price != limit_price:
                continue
            if str(row.get("status") or "") in {"Canceled", "Rejected"}:
                continue
            candidates.append(row)
        candidates.sort(key=lambda row: str(row.get("created_at") or row.get("updated_at") or ""), reverse=True)
        return candidates[0] if candidates else {}


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RealtimeExecutionConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    realtime = payload.get("longbridge_realtime", {})
    account_model = payload.get("paper_account_model", {})
    virtual_buckets, runtime_bucket_map = parse_virtual_capital_buckets(payload, account_model)
    epoch = payload.get("test_epoch", {}) if isinstance(payload.get("test_epoch"), dict) else {}
    return RealtimeExecutionConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_execution")),
        title=str(payload.get("title", "长桥模拟账户实时执行链路")),
        realtime_signal_events_path=resolve_repo_path(
            inputs.get("realtime_signal_events", DEFAULT_SIGNAL_EVENTS)
        ),
        paper_account_state_path=resolve_repo_path(
            inputs.get("paper_account_state", DEFAULT_ACCOUNT_STATE)
        ),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        required_account_channel=str(realtime.get("required_account_channel", "lb_papertrading")),
        cli_name=str(realtime.get("cli_name", "longbridge")),
        cli_timeout_seconds=int(realtime.get("cli_timeout_seconds", 6)),
        time_in_force=str(realtime.get("time_in_force", "day")),
        outside_rth=str(realtime.get("outside_rth", "RTH_ONLY")),
        execute_orders=bool(realtime.get("execute_orders", False)),
        paper_trading_approval=bool(realtime.get("paper_trading_approval", False)),
        session_started_at=str(realtime.get("session_started_at", "")),
        allow_replay=bool(realtime.get("allow_replay", False)),
        watch_interval_seconds=int(realtime.get("watch_interval_seconds", 1)),
        latency_target_ms=int(realtime.get("latency_target_ms", 1000)),
        latency_acceptable_ms=int(realtime.get("latency_acceptable_ms", 5000)),
        max_delayed_signal_age_seconds=int(realtime.get("max_delayed_signal_age_seconds", 60)),
        allowed_runtime_ids=tuple(
            str(item)
            for item in realtime.get("allowed_runtime_ids", list(DEFAULT_REALTIME_RUNTIME_IDS))
        ),
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
        daily_new_symbol_limit_by_strategy={
            str(key): int(value)
            for key, value in (realtime.get("daily_new_symbol_limit_by_strategy") or {}).items()
        },
        virtual_capital_buckets=virtual_buckets,
        runtime_capital_bucket_map=runtime_bucket_map,
        test_epoch_enabled=bool(epoch.get("enabled", False)),
        test_epoch_id=str(epoch.get("test_epoch_id") or ""),
        test_epoch_state_path=resolve_repo_path(epoch.get("state_path", DEFAULT_EPOCH_STATE)),
        flatten_existing_positions_before_new_epoch=bool(
            epoch.get("flatten_existing_positions_before_activation", False)
        ),
        archive_previous_records=bool(epoch.get("archive_previous_records", True)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def parse_virtual_capital_buckets(
    payload: dict[str, Any],
    account_model: dict[str, Any],
) -> tuple[dict[str, VirtualCapitalBucket], dict[str, str]]:
    raw = payload.get("virtual_capital_buckets") or payload.get("capital_buckets") or {}
    if not raw:
        raw = {}
        for bucket_id, label, runtime_id in SINGLE_STRATEGY_CAPITAL_BUCKET_SPECS:
            raw[bucket_id] = {
                "label": label,
                "equity": "10000",
                "max_total_exposure": "6000",
                "max_symbol_exposure": "1500",
                "max_risk_per_order": account_model.get("max_risk_per_order", "20"),
                "min_cash_reserve": "4000",
                "runtime_ids": [runtime_id],
            }
        raw["experimental"] = {
            "label": "统一实验仓",
            "equity": "10000",
            "max_total_exposure": "6000",
            "max_symbol_exposure": "1000",
            "max_risk_per_order": account_model.get("max_risk_per_order", "20"),
            "min_cash_reserve": "4000",
            "daily_new_symbol_limit": 8,
            "runtime_ids": list(EXPERIMENT_CAPITAL_BUCKET_RUNTIME_IDS),
        }
    items = raw.items() if isinstance(raw, dict) else ((str(row.get("bucket_id") or row.get("id")), row) for row in raw if isinstance(row, dict))
    buckets: dict[str, VirtualCapitalBucket] = {}
    runtime_map: dict[str, str] = {}
    for bucket_id, row in items:
        if not isinstance(row, dict):
            continue
        key = str(bucket_id or row.get("bucket_id") or row.get("id") or "").strip()
        if not key:
            continue
        runtime_ids = tuple(str(item) for item in row.get("runtime_ids", []) if str(item))
        runtime_limits = {
            str(k): int(v)
            for k, v in dict(row.get("runtime_daily_new_symbol_limits", {})).items()
        }
        bucket = VirtualCapitalBucket(
            bucket_id=key,
            label=str(row.get("label") or key),
            equity=decimal(row.get("equity", account_model.get("equity", "10000"))),
            max_total_exposure=decimal(row.get("max_total_exposure", account_model.get("max_total_exposure", "6000"))),
            max_symbol_exposure=decimal(row.get("max_symbol_exposure", account_model.get("max_symbol_exposure", "1500"))),
            max_risk_per_order=decimal(row.get("max_risk_per_order", account_model.get("max_risk_per_order", "20"))),
            min_cash_reserve=decimal(row.get("min_cash_reserve", account_model.get("min_cash_reserve", "4000"))),
            daily_new_symbol_limit=int(row.get("daily_new_symbol_limit", 0) or 0),
            runtime_daily_new_symbol_limits=runtime_limits,
            runtime_ids=runtime_ids,
        )
        buckets[key] = bucket
        for runtime_id in runtime_ids:
            runtime_map.setdefault(runtime_id, key)
    return buckets, runtime_map


def validate_config(config: RealtimeExecutionConfig) -> None:
    if config.stage != "M15.longbridge_realtime_execution":
        raise ValueError("M15 realtime execution stage drift")
    if config.required_account_channel != "lb_papertrading":
        raise ValueError("M15 realtime execution requires Longbridge paper-trading channel")
    if config.cli_timeout_seconds <= 0:
        raise ValueError("M15 realtime execution CLI timeout must be positive")
    if config.time_in_force.lower() != "day":
        raise ValueError("M15 realtime execution first version only allows day orders")
    if config.outside_rth != "RTH_ONLY":
        raise ValueError("M15 realtime execution only allows regular-hours orders")
    if config.execute_orders and not config.paper_trading_approval:
        raise ValueError("M15 realtime execution needs explicit paper trading approval to submit")
    if not config.session_started_at:
        raise ValueError("M15 realtime execution requires session_started_at")
    if not session_start_is_auto(config.session_started_at):
        parse_utc_datetime(config.session_started_at)
    if config.watch_interval_seconds <= 0:
        raise ValueError("M15 realtime execution watch interval must be positive")
    if config.latency_target_ms <= 0:
        raise ValueError("M15 realtime execution latency target must be positive")
    if config.latency_acceptable_ms < config.latency_target_ms:
        raise ValueError("M15 realtime execution acceptable latency must be >= target")
    if config.max_delayed_signal_age_seconds <= 0:
        raise ValueError("M15 realtime execution max delayed signal age must be positive")
    if config.normal_minimum_net_profit_after_fees < config.minimum_net_profit_after_fees:
        raise ValueError("M15 realtime execution normal profit threshold must be >= minimum threshold")
    if config.minimum_reward_r < ZERO:
        raise ValueError("M15 realtime execution minimum reward/R cannot be negative")
    if not config.allowed_runtime_ids:
        raise ValueError("M15 realtime execution needs a runtime whitelist")
    if not config.virtual_capital_buckets:
        raise ValueError("M15 realtime execution needs virtual capital buckets")
    for runtime_id in config.allowed_runtime_ids:
        if runtime_id in REPAIR_RUNTIME_IDS:
            continue
        if runtime_id not in config.runtime_capital_bucket_map:
            raise ValueError(f"M15 realtime execution runtime missing capital bucket: {runtime_id}")
    if config.allow_fractional_shares:
        raise ValueError("M15 realtime execution forbids fractional shares")
    if config.allow_short_selling:
        raise ValueError("M15 realtime execution forbids short selling")
    if config.allow_options:
        raise ValueError("M15 realtime execution forbids options")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 realtime execution must stay paper/simulated only")
    if config.hard_boundaries.get("live_execution", False):
        raise ValueError("M15 realtime execution cannot enable live execution")
    if config.hard_boundaries.get("real_money_actions", False):
        raise ValueError("M15 realtime execution cannot enable real money actions")
    if config.hard_boundaries.get("local_simulation_as_order_source", False):
        raise ValueError("M15 realtime execution cannot use local simulation as order source")


def run_realtime_execution(
    config: RealtimeExecutionConfig | None = None,
    *,
    generated_at: str | None = None,
    broker_client: Any | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    session_started_at = resolve_session_started_at(config.session_started_at, now)
    account_state = read_json(config.paper_account_state_path)
    epoch_state = load_or_update_test_epoch_state(config, account_state, now)
    signal_events = read_jsonl(config.realtime_signal_events_path)
    existing_ledger = read_jsonl(config.output_dir / LEDGER_JSONL)
    current_epoch_ledger = ledger_rows_for_epoch(existing_ledger, epoch_state)
    existing_submitted_ids = {
        str(row.get("signal_id"))
        for row in current_epoch_ledger
        if row.get("signal_id") and row.get("submission_status") == "submitted"
    }
    existing_processed_ids = processed_signal_ids(current_epoch_ledger)
    if epoch_state.get("status") == "pending_flatten":
        signal_events_to_process = build_epoch_flatten_signals(config, account_state, now, epoch_state)
        suppressed_by_epoch = len(signal_events)
    else:
        signal_events_to_process = [
            event
            for event in signal_events
            if str(event.get("signal_id") or "") not in existing_processed_ids
            and signal_event_in_current_epoch(event, epoch_state)
        ]
        suppressed_by_epoch = sum(
            1
            for event in signal_events
            if str(event.get("signal_id") or "") not in existing_processed_ids
            and not signal_event_in_current_epoch(event, epoch_state)
        )
    existing_submitted_exposure = submitted_ledger_open_exposure_by_bucket(
        current_epoch_ledger,
        "1970-01-01T00:00:00Z",
        account_state=account_state,
    )
    existing_strategy_symbols = submitted_strategy_symbols_by_bucket_strategy(current_epoch_ledger, session_started_at)
    same_day_loss_exit_symbols = same_day_loss_exit_symbol_set(current_epoch_ledger, session_started_at)
    existing_submitted_sell_symbols = submitted_sell_symbol_set(
        current_epoch_ledger,
        session_started_at,
        generated_at=generated_at_iso,
    )
    broker_client = broker_client or (
        LongbridgeCliRealtimePaperClient(config) if config.execute_orders else NullRealtimePaperClient()
    )

    ledger_rows: list[dict[str, Any]] = []
    selected_bucket_exposure: dict[str, Decimal] = {}
    selected_bucket_symbol_exposure: dict[tuple[str, str], Decimal] = {}
    submitted_count = 0
    attempted_count = 0
    unconfirmed_count = 0
    ready_count = 0
    blocked_count = 0
    delayed_count = 0
    target_met_count = 0
    acceptable_count = 0
    submitted_signal_ids = set(existing_submitted_ids)
    selected_strategy_symbols: dict[str, set[str]] = {}

    for event in signal_events_to_process:
        decision = evaluate_signal_event(
            config=config,
            signal=event,
            account_state=account_state,
            epoch_state=epoch_state,
            generated_at=now,
            session_started_at=session_started_at,
            submitted_signal_ids=submitted_signal_ids,
            existing_submitted_exposure=existing_submitted_exposure,
            selected_bucket_exposure=selected_bucket_exposure,
            selected_bucket_symbol_exposure=selected_bucket_symbol_exposure,
            existing_strategy_symbols=existing_strategy_symbols,
            selected_strategy_symbols=selected_strategy_symbols,
            same_day_loss_exit_symbols=same_day_loss_exit_symbols,
            existing_submitted_sell_symbols=existing_submitted_sell_symbols,
        )
        row = decision["ledger_row"]
        if decision["ready"]:
            ready_count += 1
            order_payload = decision["order_payload"]
            if config.execute_orders:
                attempted_count += 1
                submission = broker_client.submit_order(order_payload)
                row["submission_response"] = submission
                if submission.get("submitted") and submission.get("order_id"):
                    row["submission_status"] = "submitted"
                    row["submitted_at"] = generated_at_iso
                    if row.get("side") == "sell":
                        row["exit_state"] = "submitted"
                    submitted_count += 1
                    submitted_signal_ids.add(str(row["signal_id"]))
                else:
                    row["submission_status"] = str(submission.get("status", "submit_failed"))
                    if row.get("side") == "sell":
                        row["exit_state"] = (
                            "unconfirmed"
                            if row["submission_status"] == "submit_unconfirmed_missing_order_id"
                            else "submit_failed"
                        )
                    if row["submission_status"] == "submit_unconfirmed_missing_order_id":
                        unconfirmed_count += 1
            else:
                row["submission_status"] = "dry_run_ready_not_submitted"
            if row.get("side") == "buy":
                symbol = str(row["symbol"])
                notional = decimal(row.get("notional", "0"))
                bucket_id = str(row.get("capital_bucket") or "")
                selected_bucket_exposure[bucket_id] = selected_bucket_exposure.get(bucket_id, ZERO) + notional
                selected_bucket_symbol_exposure[(bucket_id, symbol)] = (
                    selected_bucket_symbol_exposure.get((bucket_id, symbol), ZERO) + notional
                )
                strategy_key = parent_strategy_id(str(row.get("strategy_id") or row.get("runtime_id") or ""))
                selected_strategy_symbols.setdefault((bucket_id, strategy_key), set()).add(symbol)
        else:
            blocked_count += 1
            row["submission_status"] = "blocked_not_submitted"
            if row.get("side") == "sell":
                row["exit_state"] = "blocked"
        if row.get("latency_band") == "target_met":
            target_met_count += 1
        elif row.get("latency_band") == "acceptable":
            acceptable_count += 1
        elif row.get("latency_band") == "delayed_revalidated":
            delayed_count += 1
        ledger_rows.append(row)

    summary = {
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at_iso,
        "source_mode": "longbridge_realtime_signal_events",
        "local_simulation_isolated": True,
        "local_ledger_input_ref": "",
        "legacy_fast_queue_status": "audit_only_not_order_source",
        "execute_orders": config.execute_orders,
        "paper_trading_approval": config.paper_trading_approval,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "required_account_channel": config.required_account_channel,
        "account_channel": str(account_state.get("account_channel") or account_state.get("channel") or ""),
        "paper_account_verified": paper_account_verified(config, account_state),
        "session_started_at": session_started_at,
        "test_epoch": epoch_state,
        "virtual_capital_buckets": virtual_bucket_summary(
            config,
            current_epoch_ledger,
            selected_bucket_exposure,
            account_state=account_state,
        ),
        "epoch_pending_flatten_signal_input_suppressed_count": suppressed_by_epoch,
        "latency_target_ms": config.latency_target_ms,
        "latency_acceptable_ms": config.latency_acceptable_ms,
        "max_delayed_signal_age_seconds": config.max_delayed_signal_age_seconds,
        "latency_counts": {
            "target_met": target_met_count,
            "acceptable": acceptable_count,
            "delayed_revalidated": delayed_count,
        },
        "input_signal_event_count": len(signal_events),
        "signal_event_count": len(signal_events_to_process),
        "skipped_previously_processed_signal_count": (
            0
            if epoch_state.get("status") == "pending_flatten"
            else len(signal_events) - len(signal_events_to_process) - suppressed_by_epoch
        ),
        "ready_order_count": ready_count,
        "blocked_signal_count": blocked_count,
        "attempted_order_count": attempted_count,
        "submitted_count": submitted_count,
        "unconfirmed_submission_count": unconfirmed_count,
        "delayed_signal_age_blocked_count": sum(
            1 for row in ledger_rows if "blocked_delayed_signal_age_over_limit" in row.get("blockers", [])
        ),
        "delayed_rebuild_required_count": sum(
            1 for row in ledger_rows if "blocked_delayed_signal_requires_realtime_rebuild" in row.get("blockers", [])
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
        "same_day_loss_cooldown_blocked_count": sum(
            1 for row in ledger_rows if "blocked_same_day_loss_exit_cooldown" in row.get("blockers", [])
        ),
        "strategy_daily_limit_blocked_count": sum(
            1 for row in ledger_rows if "blocked_strategy_daily_new_symbol_limit" in row.get("blockers", [])
        ),
        "allowed_runtime_count": len(config.allowed_runtime_ids),
        "blocked_by_reason": count_by_reason(ledger_rows),
        "runtime_whitelist": list(config.allowed_runtime_ids),
        "repair_and_shadow_isolation": {
            "repair_runtimes_local_only": sorted(REPAIR_RUNTIME_IDS),
            "auxiliary_modules_local_only": sorted(AUXILIARY_STRATEGY_IDS),
            "shadow_markers_local_only": list(SHADOW_RUNTIME_MARKERS),
        },
        "inputs": {
            "realtime_signal_events": project_path(config.realtime_signal_events_path),
            "paper_account_state": project_path(config.paper_account_state_path),
            "test_epoch_state": project_path(config.test_epoch_state_path),
            "local_simulation_ledger": "",
            "fast_signal_queue": "",
        },
        "outputs": {
            "summary": project_path(config.output_dir / SUMMARY_JSON),
            "ledger": project_path(config.output_dir / LEDGER_JSONL),
            "report": project_path(config.output_dir / REPORT_MD),
        },
        "plain_language_result": plain_language_result(
            ready_count,
            blocked_count,
            submitted_count,
            config.execute_orders,
            attempted_count=attempted_count,
            unconfirmed_count=unconfirmed_count,
            epoch_state=epoch_state,
        ),
    }

    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / SUMMARY_JSON, summary)
    write_jsonl(config.output_dir / LEDGER_JSONL, existing_ledger + ledger_rows)
    (config.output_dir / REPORT_MD).write_text(render_report(summary, ledger_rows), encoding="utf-8")
    return summary


def evaluate_signal_event(
    *,
    config: RealtimeExecutionConfig,
    signal: dict[str, Any],
    account_state: dict[str, Any],
    epoch_state: dict[str, Any],
    generated_at: datetime,
    session_started_at: str,
    submitted_signal_ids: set[str],
    existing_submitted_exposure: dict[tuple[str, str], Decimal],
    selected_bucket_exposure: dict[str, Decimal],
    selected_bucket_symbol_exposure: dict[tuple[str, str], Decimal],
    existing_strategy_symbols: dict[tuple[str, str], set[str]],
    selected_strategy_symbols: dict[tuple[str, str], set[str]],
    same_day_loss_exit_symbols: set[tuple[str, str]],
    existing_submitted_sell_symbols: set[str],
) -> dict[str, Any]:
    signal_id = str(signal.get("signal_id") or "")
    runtime_id = str(signal.get("runtime_id") or "")
    strategy_id = str(signal.get("strategy_id") or parent_strategy_id(runtime_id))
    symbol = str(signal.get("symbol") or "").upper()
    order_type = normalize_order_type(signal.get("order_type"))
    position_action = normalize_position_action(signal.get("position_action") or signal.get("event_type") or signal.get("action"))
    side = normalize_side(signal.get("side") or signal.get("direction"), position_action=position_action)
    raw_quantity = decimal(signal.get("quantity", signal.get("suggested_quantity", "0")))
    quantity_normalization = normalize_whole_share_quantity(raw_quantity, config.allow_fractional_shares)
    quantity = quantity_normalization.submitted_quantity
    limit_price = decimal(signal.get("limit_price", signal.get("entry_price", "0")))
    trigger_price = decimal(signal.get("trigger_price", "0"))
    stop_price = decimal(signal.get("stop_price", "0"))
    target_price = decimal(signal.get("target_price", "0"))
    current_price = decimal(signal.get("current_price", signal.get("last_price", limit_price)))
    risk_per_share = abs(limit_price - stop_price) if limit_price > ZERO and stop_price > ZERO else ZERO
    risk_amount = risk_per_share * quantity if side == "buy" and risk_per_share > ZERO else decimal(signal.get("risk_amount", "0"))
    notional = quantity * limit_price if limit_price > ZERO else decimal(signal.get("notional", quantity * limit_price))
    capital_bucket = str(signal.get("capital_bucket") or capital_bucket_for_runtime(config, runtime_id, strategy_id) or "")
    bucket = config.virtual_capital_buckets.get(capital_bucket)
    bucket_label = bucket.label if bucket else ""
    net_profit = decimal(
        signal.get(
            "net_profit_after_fees_at_target",
            signal.get("expected_net_profit_after_fees", signal.get("net_profit_after_fees", "0")),
        )
    )
    if side == "buy" and target_price > ZERO and limit_price > ZERO:
        gross_profit = (target_price - limit_price) * quantity
        known_fees = (
            decimal(signal.get("estimated_entry_fees", "0"))
            + decimal(signal.get("estimated_exit_fees_at_target", "0"))
            + decimal(signal.get("estimated_regulatory_fees_at_target", "0"))
        )
        if known_fees > ZERO:
            net_profit = gross_profit - known_fees
    created_at = parse_signal_time(signal.get("created_at") or signal.get("generated_at") or signal.get("signal_time"))
    latency_ms = latency_millis(created_at, generated_at) if created_at else None
    latency_band = latency_band_for(config, latency_ms)
    signal_expires_at = parse_signal_time(
        signal.get("expires_at") or signal.get("valid_until") or signal.get("signal_expires_at")
    )
    age_limit_seconds, age_limit_source = signal_age_limit(config, signal, created_at, signal_expires_at)
    blockers: list[str] = []
    exit_only_position_signal = bool(signal.get("longbridge_position_exit_source"))

    if not signal_id:
        blockers.append("missing_signal_id")
    elif signal_id in submitted_signal_ids:
        blockers.append("duplicate_signal_already_submitted")
    if not symbol:
        blockers.append("missing_symbol")
    if not created_at:
        blockers.append("missing_signal_created_at")
    elif not config.allow_replay and created_at < parse_utc_datetime(session_started_at):
        blockers.append("blocked_replay_signal_before_session_start")
    if not paper_account_verified(config, account_state):
        blockers.append("blocked_non_paper_account")
    if not (side == "sell" and exit_only_position_signal):
        blockers.extend(strategy_isolation_blockers(runtime_id, strategy_id, config.allowed_runtime_ids))
    held_quantities = held_symbol_quantities(account_state)
    available_quantities = available_symbol_quantities(account_state)
    open_order_symbols = open_order_symbol_set(account_state)
    open_sell_order_quantities = open_order_quantities_by_side(account_state, "sell")
    if side == "sell_short":
        blockers.append("blocked_short_disabled")
    elif side == "sell":
        if position_action not in {"close_long", "exit_long", "stop_loss", "take_profit"}:
            blockers.append("blocked_short_disabled")
        elif held_quantities.get(symbol, ZERO) <= ZERO:
            blockers.append("blocked_close_without_long_position")
        elif quantity > held_quantities.get(symbol, ZERO):
            blockers.append("blocked_close_quantity_over_position")
        elif quantity > available_quantities.get(symbol, held_quantities.get(symbol, ZERO)):
            blockers.append("blocked_close_quantity_not_available")
        if open_sell_order_quantities.get(symbol, ZERO) > ZERO:
            blockers.append("blocked_existing_sell_open_order_same_symbol")
        if symbol in existing_submitted_sell_symbols:
            blockers.append("blocked_existing_submitted_sell_same_symbol")
    elif side != "buy":
        blockers.append("blocked_unknown_side")
    if side == "buy":
        if not bucket:
            blockers.append("blocked_missing_capital_bucket")
        bucket_symbol = (capital_bucket, symbol)
        if existing_submitted_exposure.get(bucket_symbol, ZERO) > ZERO:
            blockers.append("blocked_existing_submitted_order_same_bucket_symbol")
        if selected_bucket_symbol_exposure.get(bucket_symbol, ZERO) > ZERO:
            blockers.append("blocked_existing_selected_order_same_bucket_symbol")
        if bucket_symbol in same_day_loss_exit_symbols:
            blockers.append("blocked_same_day_loss_exit_cooldown")
        strategy_key = parent_strategy_id(strategy_id or runtime_id)
        bucket_limit = bucket.daily_new_symbol_limit if bucket else 0
        runtime_limit = bucket.runtime_daily_new_symbol_limits.get(runtime_id, 0) if bucket else 0
        config_limit = config.daily_new_symbol_limit_by_strategy.get(
            runtime_id,
            config.daily_new_symbol_limit_by_strategy.get(
                strategy_key,
                config.daily_new_symbol_limit_by_strategy.get(strategy_id, 0),
            ),
        )
        daily_limit = runtime_limit or config_limit or bucket_limit
        if daily_limit > 0:
            strategy_bucket_key = (capital_bucket, strategy_key)
            existing_symbols = existing_strategy_symbols.get(strategy_bucket_key, set())
            selected_symbols = selected_strategy_symbols.get(strategy_bucket_key, set())
            if symbol not in existing_symbols and symbol not in selected_symbols and len(existing_symbols | selected_symbols) >= daily_limit:
                blockers.append("blocked_strategy_daily_new_symbol_limit")
    if OPTION_SYMBOL_RE.match(symbol):
        blockers.append("blocked_options_disabled")
    if order_type not in {"limit", "trigger_limit"}:
        blockers.append("blocked_order_type")
    if order_type == "trigger_limit" and trigger_price <= ZERO:
        blockers.append("missing_trigger_price")
    if quantity_normalization.blocker:
        blockers.append(quantity_normalization.blocker)
    elif quantity <= ZERO:
        blockers.append("blocked_non_positive_quantity")
    if limit_price <= ZERO:
        blockers.append("missing_limit_price")
    if side == "buy" and (stop_price <= ZERO or target_price <= ZERO):
        blockers.append("missing_stop_or_target")
    if side == "buy" and current_price > ZERO:
        if stop_price >= current_price:
            blockers.append("blocked_invalid_stop_vs_current_price")
        if target_price <= current_price:
            blockers.append("blocked_invalid_target_vs_current_price")
    max_risk = min(config.max_risk_per_order, bucket.max_risk_per_order) if bucket else config.max_risk_per_order
    max_symbol_exposure = bucket.max_symbol_exposure if bucket else config.max_symbol_exposure
    max_total_exposure = bucket.max_total_exposure if bucket else config.max_total_exposure
    bucket_symbol_exposure = (
        existing_submitted_exposure.get((capital_bucket, symbol), ZERO)
        + selected_bucket_symbol_exposure.get((capital_bucket, symbol), ZERO)
    )
    bucket_total_exposure = sum(
        value for (row_bucket, _symbol), value in existing_submitted_exposure.items() if row_bucket == capital_bucket
    ) + selected_bucket_exposure.get(capital_bucket, ZERO)
    if side == "buy" and risk_amount > max_risk:
        blockers.append("blocked_risk_over_cap")
    if side == "buy" and notional > max_symbol_exposure:
        blockers.append("blocked_symbol_exposure_over_cap")
    if side == "buy" and bucket_symbol_exposure + notional > max_symbol_exposure:
        blockers.append("blocked_symbol_exposure_over_cap")
    if side == "buy" and bucket_total_exposure + notional > max_total_exposure:
        blockers.append("blocked_total_exposure_over_cap")
    if side == "buy" and available_cash(account_state) - notional < ZERO:
        blockers.append("blocked_cash_reserve")
    reward_r = reward_r_ratio(limit_price, stop_price, target_price) if side == "buy" else ZERO
    minimum_reward_r = runtime_minimum_reward_r(config, runtime_id, strategy_id) if side == "buy" else ZERO
    minimum_net_profit = runtime_minimum_net_profit(config, runtime_id, strategy_id) if side == "buy" else ZERO
    profit_gate_status = (
        profit_quality_gate(config, signal, net_profit, runtime_id, strategy_id) if side == "buy" else "not_applicable"
    )
    if profit_gate_status == "below_minimum":
        blockers.append("blocked_fee_profit_below_minimum")
    elif profit_gate_status == "requires_confluence_or_quality":
        blockers.append("blocked_fee_profit_requires_confluence")
    if side == "buy" and reward_r < minimum_reward_r:
        blockers.append("blocked_reward_r_below_minimum")
    if signal_expires_at and generated_at > signal_expires_at:
        blockers.append("blocked_realtime_signal_expired")
    if latency_ms is not None and latency_ms > config.latency_acceptable_ms:
        if age_limit_seconds > 0 and latency_ms > age_limit_seconds * 1000:
            blockers.append("blocked_delayed_signal_age_over_limit")
        if current_price <= ZERO or limit_price <= ZERO:
            blockers.append("blocked_delayed_signal_missing_revalidation_price")
        if not bool(signal.get("realtime_rebuilt_from_delayed_signal")):
            blockers.append("blocked_delayed_signal_requires_realtime_rebuild")

    status = "ready"
    if blockers:
        status = blockers[0]
    elif latency_band == "delayed_revalidated":
        status = "latency_delayed_revalidated_ready"
    elif latency_band == "target_met":
        status = "latency_target_met_ready"
    elif latency_band == "acceptable":
        status = "latency_acceptable_ready"

    order_payload = build_order_payload(signal, side, order_type, symbol, quantity, limit_price, trigger_price)
    order_payload.update(
        {
            "capital_bucket": capital_bucket,
            "capital_bucket_label": bucket_label,
            "test_epoch_id": str(epoch_state.get("test_epoch_id") or ""),
            "raw_suggested_quantity": fmt_decimal(quantity_normalization.raw_quantity),
            "submitted_quantity": fmt_decimal(quantity),
            "quantity_rounding_adjustment": fmt_decimal(quantity_normalization.rounded_down_quantity),
            "quantity_normalization_status": quantity_normalization.status,
        }
    )
    ledger_row = {
        "stage": config.stage,
        "signal_id": signal_id,
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "capital_bucket": capital_bucket,
        "capital_bucket_label": bucket_label,
        "test_epoch_id": str(epoch_state.get("test_epoch_id") or ""),
        "test_started_at": str(epoch_state.get("test_started_at") or ""),
        "test_epoch_status": str(epoch_state.get("status") or ""),
        "symbol": symbol,
        "timeframe": str(signal.get("timeframe") or ""),
        "direction": str(signal.get("direction") or ""),
        "position_action": position_action,
        "side": side,
        "order_type": order_type,
        "raw_suggested_quantity": fmt_decimal(quantity_normalization.raw_quantity),
        "submitted_quantity": fmt_decimal(quantity),
        "quantity_rounding_adjustment": fmt_decimal(quantity_normalization.rounded_down_quantity),
        "quantity_normalization_status": quantity_normalization.status,
        "quantity_normalization_blocker": quantity_normalization.blocker,
        "quantity": fmt_decimal(quantity),
        "limit_price": fmt_money(limit_price),
        "trigger_price": fmt_money(trigger_price) if trigger_price > ZERO else "",
        "stop_price": fmt_money(stop_price) if stop_price > ZERO else "",
        "target_price": fmt_money(target_price) if target_price > ZERO else "",
        "current_price": fmt_money(current_price) if current_price > ZERO else "",
        "risk_amount": fmt_money(risk_amount),
        "notional": fmt_money(notional),
        "net_profit_after_fees_at_target": fmt_money(net_profit),
        "profit_quality_gate": profit_gate_status,
        "reward_r": fmt_decimal(reward_r),
        "minimum_reward_r": fmt_decimal(minimum_reward_r),
        "minimum_net_profit_after_fees": fmt_money(minimum_net_profit),
        "bucket_equity": fmt_money(bucket.equity) if bucket else "",
        "bucket_max_total_exposure": fmt_money(max_total_exposure),
        "bucket_max_symbol_exposure": fmt_money(max_symbol_exposure),
        "bucket_max_risk_per_order": fmt_money(max_risk),
        "confluence_support_count": int_decimal(signal.get("confluence_support_count", "0")),
        "confluence_multiplier": fmt_decimal(decimal(signal.get("confluence_multiplier", "1"))),
        "high_quality_signal": signal_is_high_quality(signal),
        "source_market_event_id": str(signal.get("source_market_event_id") or signal.get("market_event_id") or ""),
        "created_at": to_iso(created_at) if created_at else "",
        "processed_at": to_iso(generated_at),
        "latency_ms": latency_ms if latency_ms is not None else "",
        "latency_band": latency_band,
        "signal_age_limit_seconds": age_limit_seconds,
        "signal_age_limit_source": age_limit_source,
        "signal_expires_at": to_iso(signal_expires_at) if signal_expires_at else "",
        "realtime_decision_status": status,
        "blockers": blockers,
        "order_payload": order_payload if not blockers else {},
        "local_simulation_ignored": True,
        "local_close_event_ignored": bool(signal.get("latest_close_event_time_after_open") or signal.get("local_close_event_id")),
        "longbridge_account_position_checked": True,
        "longbridge_account_open_orders_checked": True,
        "longbridge_realtime_submitted_ledger_checked": True,
        "m13_m14_gate_used_for_order": False,
        "fast_queue_used_for_order": False,
        "exit_state": "ready_to_submit" if side == "sell" and not blockers else ("blocked" if side == "sell" else ""),
        "exit_only_position_signal": exit_only_position_signal,
    }
    return {"ready": not blockers, "ledger_row": ledger_row, "order_payload": order_payload}


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


def build_order_payload(
    signal: dict[str, Any],
    side: str,
    order_type: str,
    symbol: str,
    quantity: Decimal,
    limit_price: Decimal,
    trigger_price: Decimal,
) -> dict[str, Any]:
    payload = {
        "source": "longbridge_realtime_signal_event",
        "signal_id": str(signal.get("signal_id") or ""),
        "runtime_id": str(signal.get("runtime_id") or ""),
        "strategy_id": str(signal.get("strategy_id") or ""),
        "position_action": str(signal.get("position_action") or signal.get("event_type") or signal.get("action") or ""),
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "quantity": int(quantity),
        "limit_price": fmt_money(limit_price),
        "time_in_force": str(signal.get("time_in_force") or "day"),
        "outside_rth": "RTH_ONLY",
    }
    if order_type == "trigger_limit":
        payload["trigger_price"] = fmt_money(trigger_price)
    return payload


def longbridge_order_command(config: RealtimeExecutionConfig, cli_path: str, order_payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    side = str(order_payload.get("side") or "")
    symbol = longbridge_symbol(str(order_payload.get("symbol") or ""))
    quantity = int(decimal(order_payload.get("quantity", "0")))
    limit_price = str(order_payload.get("limit_price") or "")
    order_type = str(order_payload.get("order_type") or "")
    trigger_price = str(order_payload.get("trigger_price") or "")
    signal_id = str(order_payload.get("signal_id") or "")
    blockers: list[str] = []
    if side not in {"buy", "sell"}:
        blockers.append("unsupported_longbridge_order_side")
    if not symbol:
        blockers.append("missing_symbol")
    if quantity <= 0:
        blockers.append("missing_quantity")
    if not limit_price:
        blockers.append("missing_limit_price")
    if order_type not in {"limit", "trigger_limit"}:
        blockers.append("unsupported_order_type")
    if order_type == "trigger_limit" and not trigger_price:
        blockers.append("missing_trigger_price")
    if blockers:
        return [], blockers
    remark = f"PAT-RT {signal_id} {order_payload.get('runtime_id', '')}"[:255]
    command = [
        cli_path,
        "order",
        side,
        symbol,
        str(quantity),
        "--price",
        limit_price,
        "--tif",
        config.time_in_force,
        "--outside-rth",
        config.outside_rth,
        "--remark",
        remark,
        "--yes",
        "--format",
        "json",
    ]
    if order_type == "limit":
        command.extend(["--order-type", "LO"])
    else:
        command.extend(["--order-type", "LIT", "--trigger-price", trigger_price])
    assert_submit_command(command)
    return command, []


def assert_submit_command(command: list[str]) -> None:
    if len(command) < 5:
        raise ValueError("Longbridge realtime order command is incomplete")
    args = command[1:]
    if args[0] != "order" or args[1] not in {"buy", "sell"}:
        raise ValueError(f"Longbridge realtime order command is not a buy/sell order: {args}")
    if "--yes" not in args or "--format" not in args:
        raise ValueError(f"Longbridge realtime order command is missing safety flags: {args}")


def run_longbridge_command(command: list[str]) -> Any:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=build_longbridge_cli_env(),
    )


def longbridge_symbol(symbol: str) -> str:
    if not symbol:
        return ""
    return symbol if "." in symbol else f"{symbol}.US"


def redact_command(command: list[str]) -> list[str]:
    return [item for item in command if item != "--yes"]


def paper_account_verified(config: RealtimeExecutionConfig, account_state: dict[str, Any]) -> bool:
    if not account_state:
        return False
    channel = str(account_state.get("account_channel") or account_state.get("channel") or "")
    if channel != config.required_account_channel:
        return False
    if account_state.get("paper_account_verified") is False:
        return False
    if account_state.get("live_execution") is True or account_state.get("real_money_actions") is True:
        return False
    return True


def capital_bucket_for_runtime(config: RealtimeExecutionConfig, runtime_id: str, strategy_id: str = "") -> str:
    if runtime_id in config.runtime_capital_bucket_map:
        return config.runtime_capital_bucket_map[runtime_id]
    parent = parent_strategy_id(strategy_id or runtime_id)
    for bucket_id, bucket in config.virtual_capital_buckets.items():
        if parent in bucket.runtime_ids:
            return bucket_id
    return ""


def load_or_update_test_epoch_state(
    config: RealtimeExecutionConfig,
    account_state: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    if not config.test_epoch_enabled:
        return {
            "enabled": False,
            "status": "legacy",
            "test_epoch_id": "legacy",
            "test_started_at": "",
            "archive_previous_records": False,
        }
    configured_epoch_id = config.test_epoch_id or f"m15-single-strategy-buckets-{now.astimezone(NEW_YORK).date().isoformat()}"
    current = read_json(config.test_epoch_state_path)
    if str(current.get("test_epoch_id") or "") != configured_epoch_id:
        has_positions = bool(held_symbol_quantities(account_state))
        status = "pending_flatten" if config.flatten_existing_positions_before_new_epoch and has_positions else "active"
        current = {
            "schema_version": "m15.longbridge-virtual-account-epoch.v1",
            "enabled": True,
            "test_epoch_id": configured_epoch_id,
            "status": status,
            "created_at": to_iso(now),
            "test_started_at": "" if status == "pending_flatten" else to_iso(now),
            "archive_before": to_iso(now),
            "archive_previous_records": config.archive_previous_records,
            "flatten_existing_positions_before_activation": config.flatten_existing_positions_before_new_epoch,
            "activation_blocker": "existing_longbridge_positions_need_flatten" if status == "pending_flatten" else "",
        }
    elif current.get("status") == "pending_flatten":
        has_positions = bool(held_symbol_quantities(account_state))
        has_sell_orders = bool(open_order_quantities_by_side(account_state, "sell"))
        if not has_positions and not has_sell_orders:
            current["status"] = "active"
            current["test_started_at"] = to_iso(now)
            current["activated_at"] = to_iso(now)
            current["activation_blocker"] = ""
        else:
            current["activation_blocker"] = (
                "waiting_for_flatten_sell_orders_to_finish"
                if has_sell_orders
                else "existing_longbridge_positions_need_flatten"
            )
            current["last_flatten_check_at"] = to_iso(now)
    config.test_epoch_state_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(config.test_epoch_state_path, current)
    return current


def signal_event_in_current_epoch(signal: dict[str, Any], epoch_state: dict[str, Any]) -> bool:
    if not epoch_state.get("enabled") or epoch_state.get("status") == "legacy":
        return True
    started_at = parse_signal_time(epoch_state.get("test_started_at"))
    if not started_at:
        return False
    created_at = parse_signal_time(signal.get("created_at") or signal.get("generated_at") or signal.get("signal_time"))
    return bool(created_at and created_at >= started_at)


def ledger_rows_for_epoch(rows: list[dict[str, Any]], epoch_state: dict[str, Any]) -> list[dict[str, Any]]:
    if not epoch_state.get("enabled") or epoch_state.get("status") == "legacy":
        return rows
    epoch_id = str(epoch_state.get("test_epoch_id") or "")
    started_at = parse_signal_time(epoch_state.get("test_started_at"))
    matched: list[dict[str, Any]] = []
    for row in rows:
        if epoch_id and str(row.get("test_epoch_id") or "") == epoch_id:
            matched.append(row)
            continue
        if not started_at:
            continue
        row_time = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if row_time and row_time >= started_at:
            matched.append(row)
    return matched


def build_epoch_flatten_signals(
    config: RealtimeExecutionConfig,
    account_state: dict[str, Any],
    now: datetime,
    epoch_state: dict[str, Any],
) -> list[dict[str, Any]]:
    positions = account_state.get("positions") if isinstance(account_state.get("positions"), list) else []
    signals: list[dict[str, Any]] = []
    for row in positions:
        if not isinstance(row, dict):
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        if not symbol:
            continue
        held_quantity = decimal(row.get("quantity", row.get("qty", "0")))
        available_quantity = decimal(
            row.get("available", row.get("available_quantity", row.get("sellable_quantity", held_quantity)))
        )
        quantity = min(held_quantity, available_quantity) if available_quantity > ZERO else held_quantity
        price, price_source = first_positive_decimal_with_key(
            row,
            ("market_price", "last_price", "current_price", "last_done", "price", "cost_price", "average_cost"),
        )
        if price > ZERO:
            if price_source in {"cost_price", "average_cost"}:
                price *= FLATTEN_FALLBACK_COST_SELL_LIMIT_MULTIPLIER
            else:
                price *= FLATTEN_CURRENT_PRICE_SELL_LIMIT_MULTIPLIER
        if quantity <= ZERO:
            continue
        signals.append(
            {
                "signal_id": f"{epoch_state.get('test_epoch_id')}-flatten-{symbol}-{int(now.timestamp())}",
                "created_at": to_iso(now),
                "runtime_id": "M15-LONGBRIDGE-EPOCH-FLATTEN",
                "strategy_id": "M15-LONGBRIDGE-EPOCH-FLATTEN",
                "symbol": symbol,
                "timeframe": "account",
                "direction": "long",
                "side": "sell",
                "position_action": "close_long",
                "order_type": "limit",
                "quantity": fmt_decimal(quantity.to_integral_value()),
                "limit_price": fmt_money(price) if price > ZERO else "",
                "current_price": fmt_money(price) if price > ZERO else "",
                "risk_amount": "0.00",
                "notional": fmt_money(quantity * price) if price > ZERO else "0.00",
                "net_profit_after_fees_at_target": "0.00",
                "flatten_limit_price_source": price_source,
                "source_market_event_id": "longbridge_epoch_flatten",
                "longbridge_position_exit_source": True,
                "test_epoch_id": str(epoch_state.get("test_epoch_id") or ""),
            }
        )
    return signals


def first_positive_decimal(row: dict[str, Any], keys: tuple[str, ...]) -> Decimal:
    value, _key = first_positive_decimal_with_key(row, keys)
    return value


def first_positive_decimal_with_key(row: dict[str, Any], keys: tuple[str, ...]) -> tuple[Decimal, str]:
    for key in keys:
        value = decimal(row.get(key, "0"))
        if value > ZERO:
            return value, key
    return ZERO, ""


def virtual_bucket_summary(
    config: RealtimeExecutionConfig,
    current_epoch_ledger: list[dict[str, Any]],
    selected_bucket_exposure: dict[str, Decimal],
    *,
    account_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    submitted = submitted_ledger_open_exposure_by_bucket(
        current_epoch_ledger,
        "1970-01-01T00:00:00Z",
        account_state=account_state,
    )
    rows: list[dict[str, Any]] = []
    for bucket_id, bucket in config.virtual_capital_buckets.items():
        submitted_exposure = sum(value for (row_bucket, _symbol), value in submitted.items() if row_bucket == bucket_id)
        selected_exposure = selected_bucket_exposure.get(bucket_id, ZERO)
        rows.append(
            {
                "capital_bucket": bucket_id,
                "label": bucket.label,
                "equity": fmt_money(bucket.equity),
                "max_total_exposure": fmt_money(bucket.max_total_exposure),
                "max_symbol_exposure": fmt_money(bucket.max_symbol_exposure),
                "used_exposure": fmt_money(submitted_exposure + selected_exposure),
                "runtime_ids": list(bucket.runtime_ids),
                "daily_new_symbol_limit": bucket.daily_new_symbol_limit,
                "runtime_daily_new_symbol_limits": bucket.runtime_daily_new_symbol_limits,
            }
        )
    return rows


def available_cash(account_state: dict[str, Any]) -> Decimal:
    for key in ("cash", "available_cash", "buying_power", "cash_available"):
        if key in account_state:
            return decimal(account_state.get(key, "0"))
    assets = account_state.get("assets")
    if isinstance(assets, dict):
        for key in ("cash", "available_cash", "buying_power"):
            if key in assets:
                return decimal(assets.get(key, "0"))
    return ZERO


def held_symbol_quantities(account_state: dict[str, Any]) -> dict[str, Decimal]:
    quantities: dict[str, Decimal] = {}
    positions = account_state.get("positions")
    if not isinstance(positions, list):
        positions = []
    for row in positions:
        if not isinstance(row, dict):
            continue
        symbol = base_symbol(str(row.get("symbol", "")))
        quantity = decimal(row.get("quantity", row.get("qty", "0")))
        if symbol and quantity > ZERO:
            quantities[symbol] = quantities.get(symbol, ZERO) + quantity
    for symbol in account_state.get("held_symbols", []) if isinstance(account_state.get("held_symbols"), list) else []:
        quantities.setdefault(base_symbol(str(symbol)), Decimal("1"))
    return quantities


def available_symbol_quantities(account_state: dict[str, Any]) -> dict[str, Decimal]:
    quantities: dict[str, Decimal] = {}
    positions = account_state.get("positions")
    if not isinstance(positions, list):
        positions = []
    for row in positions:
        if not isinstance(row, dict):
            continue
        symbol = base_symbol(str(row.get("symbol", "")))
        if not symbol:
            continue
        held_quantity = decimal(row.get("quantity", row.get("qty", "0")))
        available_value: Any = None
        for key in ("available", "available_quantity", "sellable_quantity", "available_qty", "sellable", "qty_available"):
            if key in row:
                available_value = row.get(key)
                break
        available_quantity = decimal(available_value) if available_value is not None else held_quantity
        if available_quantity > ZERO:
            quantities[symbol] = quantities.get(symbol, ZERO) + available_quantity
        else:
            quantities.setdefault(symbol, ZERO)
    if not quantities:
        for symbol in account_state.get("held_symbols", []) if isinstance(account_state.get("held_symbols"), list) else []:
            quantities.setdefault(base_symbol(str(symbol)), Decimal("1"))
    return quantities


def open_order_symbol_set(account_state: dict[str, Any]) -> set[str]:
    symbols: set[str] = set()
    orders = account_state.get("open_orders")
    if not isinstance(orders, list):
        orders = []
    for row in orders:
        if isinstance(row, dict) and row.get("symbol"):
            symbols.add(base_symbol(str(row.get("symbol"))))
    return symbols


def open_order_quantities_by_side(account_state: dict[str, Any], side_filter: str) -> dict[str, Decimal]:
    quantities: dict[str, Decimal] = {}
    orders = account_state.get("open_orders")
    if not isinstance(orders, list):
        orders = []
    expected_side = side_filter.lower()
    for row in orders:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        side = str(row.get("side") or row.get("order_side") or "").strip().lower()
        if expected_side == "sell" and not side.startswith("sell"):
            continue
        if expected_side == "buy" and not side.startswith("buy"):
            continue
        symbol = base_symbol(str(row.get("symbol")))
        quantity = decimal(row.get("quantity", row.get("qty", row.get("submitted_quantity", "0"))))
        executed_quantity = decimal(row.get("executed_quantity", row.get("filled_quantity", row.get("filled_qty", "0"))))
        remaining_quantity = decimal(row.get("remaining_quantity", row.get("remaining_qty", "")))
        if remaining_quantity <= ZERO and quantity > ZERO:
            remaining_quantity = quantity - executed_quantity
        if symbol and remaining_quantity > ZERO:
            quantities[symbol] = quantities.get(symbol, ZERO) + remaining_quantity
    return quantities


def account_symbol_exposure(account_state: dict[str, Any]) -> dict[str, Decimal]:
    exposures: dict[str, Decimal] = {}
    for key in ("position_notional_by_symbol", "open_order_notional_by_symbol"):
        payload = account_state.get(key)
        if not isinstance(payload, dict):
            continue
        for symbol, value in payload.items():
            base = base_symbol(str(symbol))
            exposures[base] = exposures.get(base, ZERO) + decimal(value)
    return exposures


def account_total_exposure(account_state: dict[str, Any]) -> Decimal:
    total = decimal(account_state.get("total_position_notional", "0"))
    total += decimal(account_state.get("total_open_order_notional", "0"))
    if total > ZERO:
        return total
    return sum(account_symbol_exposure(account_state).values(), ZERO)


def base_symbol(symbol: str) -> str:
    return symbol.upper().split(".")[0]


def count_by_reason(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        blockers = row.get("blockers")
        if isinstance(blockers, list) and blockers:
            reason = str(blockers[0])
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def profit_quality_gate(
    config: RealtimeExecutionConfig,
    signal: dict[str, Any],
    net_profit: Decimal,
    runtime_id: str,
    strategy_id: str,
) -> str:
    if net_profit < runtime_minimum_net_profit(config, runtime_id, strategy_id):
        return "below_minimum"
    if net_profit < config.normal_minimum_net_profit_after_fees:
        if config.conditional_net_profit_requires_confluence and not (
            signal_has_confluence(signal) or signal_is_high_quality(signal)
        ):
            return "requires_confluence_or_quality"
        return "conditional_profit_with_confluence_or_quality"
    return "normal_profit"


def runtime_minimum_net_profit(config: RealtimeExecutionConfig, runtime_id: str, strategy_id: str) -> Decimal:
    for key in (runtime_id, strategy_id, parent_strategy_id(runtime_id), parent_strategy_id(strategy_id)):
        if key in config.runtime_minimum_net_profit_after_fees:
            return max(config.minimum_net_profit_after_fees, config.runtime_minimum_net_profit_after_fees[key])
    return max(config.minimum_net_profit_after_fees, config.normal_minimum_net_profit_after_fees)


def runtime_minimum_reward_r(config: RealtimeExecutionConfig, runtime_id: str, strategy_id: str) -> Decimal:
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


def signal_has_confluence(signal: dict[str, Any]) -> bool:
    support_count = int_decimal(signal.get("confluence_support_count", "0"))
    multiplier = decimal(signal.get("confluence_multiplier", "1"))
    status = str(signal.get("confluence_status") or signal.get("confluence_role") or "").lower()
    return support_count > 0 or multiplier > Decimal("1") or "confluence" in status


def signal_is_high_quality(signal: dict[str, Any]) -> bool:
    if signal.get("high_quality_signal") is True:
        return True
    for key in ("quality_tier", "signal_quality", "quality_label"):
        value = str(signal.get(key) or "").strip().lower()
        if value in {"high", "strong", "excellent", "高质量", "强"}:
            return True
    score = decimal(signal.get("quality_score", signal.get("signal_quality_score", "0")))
    return score >= Decimal("0.8")


def submitted_ledger_open_exposure(
    rows: list[dict[str, Any]],
    session_started_at: str,
    account_state: dict[str, Any] | None = None,
) -> dict[str, Decimal]:
    session_start = parse_utc_datetime(session_started_at)
    account_state = account_state or {}
    materialized_symbols = set(held_symbol_quantities(account_state)) | open_order_symbol_set(account_state)
    quantities: dict[str, Decimal] = {}
    notionals: dict[str, Decimal] = {}
    for row in rows:
        if row.get("submission_status") != "submitted":
            continue
        submitted_at = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if submitted_at and submitted_at < session_start:
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        if not symbol:
            continue
        if symbol in materialized_symbols:
            continue
        quantity = decimal(row.get("quantity", "0"))
        notional = decimal(row.get("notional", "0"))
        side = str(row.get("side") or "").lower()
        if side == "buy":
            quantities[symbol] = quantities.get(symbol, ZERO) + quantity
            notionals[symbol] = notionals.get(symbol, ZERO) + notional
        elif side == "sell":
            quantities[symbol] = quantities.get(symbol, ZERO) - quantity
            if quantities[symbol] <= ZERO:
                quantities.pop(symbol, None)
                notionals.pop(symbol, None)
    return {symbol: notional for symbol, notional in notionals.items() if quantities.get(symbol, ZERO) > ZERO and notional > ZERO}


def submitted_ledger_open_exposure_by_bucket(
    rows: list[dict[str, Any]],
    session_started_at: str,
    account_state: dict[str, Any] | None = None,
) -> dict[tuple[str, str], Decimal]:
    session_start = parse_utc_datetime(session_started_at)
    account_state = account_state or {}
    order_by_id = latest_account_orders_by_id(account_state)
    materialized_symbols = set(held_symbol_quantities(account_state)) | open_order_symbol_set(account_state)
    quantities: dict[tuple[str, str], Decimal] = {}
    notionals: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        if row.get("submission_status") != "submitted":
            continue
        submitted_at = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if submitted_at and submitted_at < session_start:
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        bucket = str(row.get("capital_bucket") or "legacy")
        if not symbol:
            continue
        key = (bucket, symbol)
        quantity = decimal(row.get("quantity", "0"))
        notional = decimal(row.get("notional", "0"))
        side = str(row.get("side") or "").lower()
        if side == "buy":
            order_id = ledger_row_order_id(row)
            account_order = order_by_id.get(order_id) if order_id else None
            active_quantity, active_notional = submitted_buy_active_exposure(
                row,
                account_order,
                symbol_materialized=symbol in materialized_symbols,
            )
            if active_quantity <= ZERO or active_notional <= ZERO:
                continue
            quantities[key] = quantities.get(key, ZERO) + active_quantity
            notionals[key] = notionals.get(key, ZERO) + active_notional
        elif side == "sell":
            old_quantity = quantities.get(key, ZERO)
            if old_quantity <= ZERO:
                continue
            remaining_quantity = old_quantity - quantity
            if remaining_quantity <= ZERO:
                quantities.pop(key, None)
                notionals.pop(key, None)
            else:
                old_notional = notionals.get(key, ZERO)
                quantities[key] = remaining_quantity
                notionals[key] = old_notional * (remaining_quantity / old_quantity)
    return {key: notional for key, notional in notionals.items() if quantities.get(key, ZERO) > ZERO and notional > ZERO}


def ledger_row_order_id(row: dict[str, Any]) -> str:
    order_id = str(row.get("order_id") or "").strip()
    if order_id:
        return order_id
    response = row.get("submission_response")
    if not isinstance(response, dict):
        return ""
    order_id = str(response.get("order_id") or "").strip()
    if order_id:
        return order_id
    matched_order = response.get("matched_order")
    if isinstance(matched_order, dict):
        return str(matched_order.get("order_id") or "").strip()
    return ""


def latest_account_orders_by_id(account_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    orders_by_id: dict[str, dict[str, Any]] = {}
    for key in ("historical_orders", "orders", "open_orders"):
        rows = account_state.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            order_id = str(row.get("order_id") or row.get("id") or "").strip()
            if order_id:
                orders_by_id[order_id] = row
    return orders_by_id


def submitted_buy_active_exposure(
    ledger_row: dict[str, Any],
    account_order: dict[str, Any] | None,
    *,
    symbol_materialized: bool,
) -> tuple[Decimal, Decimal]:
    row_quantity = decimal(ledger_row.get("quantity", "0"))
    row_notional = decimal(ledger_row.get("notional", "0"))
    if row_quantity <= ZERO or row_notional <= ZERO:
        return ZERO, ZERO
    if account_order is None:
        # Rows without an order id predate the account-state matcher. If the
        # broker already reports the symbol as held/open, do not count that old
        # submitted row again as pending exposure.
        if symbol_materialized:
            return ZERO, ZERO
        return row_quantity, row_notional

    status = str(account_order.get("status") or "").strip().lower().replace(" ", "_")
    executed_quantity = decimal(account_order.get("executed_quantity", account_order.get("filled_quantity", "0")))
    executed_price = decimal(account_order.get("executed_price", account_order.get("avg_price", "0")))
    order_quantity = decimal(account_order.get("quantity", account_order.get("qty", row_quantity)))
    order_price = decimal(account_order.get("price", ledger_row.get("limit_price", "0")))
    terminal_without_position = {
        "canceled",
        "cancelled",
        "rejected",
        "expired",
        "withdrawn",
        "failed",
    }
    if status in terminal_without_position and executed_quantity <= ZERO:
        return ZERO, ZERO
    if executed_quantity > ZERO:
        if not symbol_materialized and status in {"filled", "done", "completed"}:
            return ZERO, ZERO
        notional = executed_quantity * executed_price if executed_price > ZERO else row_notional * (executed_quantity / row_quantity)
        return executed_quantity, notional
    open_statuses = {
        "new",
        "submitted",
        "pending",
        "wait_to_new",
        "partial_filled",
        "partially_filled",
    }
    if status in open_statuses:
        quantity = order_quantity if order_quantity > ZERO else row_quantity
        notional = quantity * order_price if order_price > ZERO else row_notional
        return quantity, notional
    if symbol_materialized:
        return row_quantity, row_notional
    return ZERO, ZERO


def submitted_strategy_symbols_by_bucket_strategy(
    rows: list[dict[str, Any]],
    session_started_at: str,
) -> dict[tuple[str, str], set[str]]:
    session_start = parse_utc_datetime(session_started_at)
    symbols_by_strategy: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        if row.get("submission_status") != "submitted":
            continue
        if str(row.get("side") or "").lower() != "buy":
            continue
        submitted_at = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if submitted_at and submitted_at < session_start:
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        bucket = str(row.get("capital_bucket") or "legacy")
        strategy_key = parent_strategy_id(str(row.get("strategy_id") or row.get("runtime_id") or ""))
        if symbol and strategy_key:
            symbols_by_strategy.setdefault((bucket, strategy_key), set()).add(symbol)
    return symbols_by_strategy


def same_day_loss_exit_symbol_set(rows: list[dict[str, Any]], session_started_at: str) -> set[tuple[str, str]]:
    session_start = parse_utc_datetime(session_started_at)
    symbols: set[tuple[str, str]] = set()
    loss_actions = {"stop_loss", "loss_exit", "risk_loss_exit"}
    for row in rows:
        if row.get("submission_status") != "submitted":
            continue
        if str(row.get("side") or "").lower() != "sell":
            continue
        submitted_at = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if submitted_at and submitted_at < session_start:
            continue
        action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        realized = decimal(row.get("realized_pnl", row.get("pnl", "0")))
        symbol = base_symbol(str(row.get("symbol") or ""))
        bucket = str(row.get("capital_bucket") or "legacy")
        if symbol and (action in loss_actions or realized < ZERO):
            symbols.add((bucket, symbol))
    return symbols


def submitted_sell_symbol_set(
    rows: list[dict[str, Any]],
    session_started_at: str,
    *,
    generated_at: str | None = None,
    duplicate_guard_seconds: int = 120,
) -> set[str]:
    session_start = parse_utc_datetime(session_started_at)
    generated_dt = parse_utc_datetime(generated_at) if generated_at else None
    symbols: set[str] = set()
    for row in rows:
        if row.get("submission_status") != "submitted":
            continue
        if str(row.get("side") or "").lower() != "sell":
            continue
        submitted_at = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if submitted_at and submitted_at < session_start:
            continue
        if generated_dt and submitted_at and (generated_dt - submitted_at).total_seconds() > duplicate_guard_seconds:
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        if symbol:
            symbols.add(symbol)
    return symbols


def processed_signal_ids(rows: list[dict[str, Any]]) -> set[str]:
    processed: set[str] = set()
    for row in rows:
        signal_id = str(row.get("signal_id") or "")
        if not signal_id:
            continue
        if row.get("processed_at") or row.get("submitted_at") or row.get("submission_status"):
            processed.add(signal_id)
    return processed


def latency_band_for(config: RealtimeExecutionConfig, latency_ms: int | None) -> str:
    if latency_ms is None:
        return "unknown"
    if latency_ms <= config.latency_target_ms:
        return "target_met"
    if latency_ms <= config.latency_acceptable_ms:
        return "acceptable"
    return "delayed_revalidated"


def latency_millis(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() * 1000))


def signal_age_limit(
    config: RealtimeExecutionConfig,
    signal: dict[str, Any],
    created_at: datetime | None,
    signal_expires_at: datetime | None,
) -> tuple[int, str]:
    configured_limit = config.max_delayed_signal_age_seconds
    raw_valid_for = signal.get("valid_for_seconds") or signal.get("ttl_seconds") or signal.get("signal_ttl_seconds")
    valid_for_limit = int_decimal(raw_valid_for)
    if valid_for_limit > 0:
        configured_limit = min(configured_limit, valid_for_limit)
    if created_at and signal_expires_at:
        expires_limit = max(0, int((signal_expires_at - created_at).total_seconds()))
        if expires_limit > 0:
            configured_limit = min(configured_limit, expires_limit)
            return configured_limit, "signal_expires_at"
    if valid_for_limit > 0:
        return configured_limit, "signal_valid_for_seconds"
    return configured_limit, "config_max_delayed_signal_age_seconds"


def int_decimal(value: Any) -> int:
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return 0


def normalize_side(value: Any, *, position_action: str = "") -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "long", "open_long", "bullish", "看涨", "买入", "做多"}:
        return "buy"
    if text in {"sell", "close_long", "sell_long", "平仓", "卖出平多"} or position_action in {
        "close_long",
        "exit_long",
        "stop_loss",
        "take_profit",
    }:
        return "sell"
    if text in {"short", "sell_short", "bearish", "看跌", "做空"}:
        return "sell_short"
    return text or "unknown"


def normalize_position_action(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"close", "exit", "close_position", "sell_long"}:
        return "close_long"
    if text in {"stop", "stoploss", "stop_loss"}:
        return "stop_loss"
    if text in {"target", "takeprofit", "take_profit"}:
        return "take_profit"
    if text in {"open", "open_long", "buy"}:
        return "open_long"
    return text


def normalize_order_type(value: Any) -> str:
    text = str(value or "limit").strip().lower().replace("-", "_")
    if text in {"stop_limit", "trigger_limit", "breakout_limit", "triggered_limit"}:
        return "trigger_limit"
    if text in {"limit", "limit_order"}:
        return "limit"
    return text


def parent_strategy_id(runtime_id: str) -> str:
    parts = runtime_id.split("-")
    if len(parts) >= 3 and parts[0] == "M10" and parts[1] == "PA":
        return "-".join(parts[:3])
    if runtime_id.startswith("M12-FTD-001"):
        return "M12-FTD-001"
    return runtime_id


def plain_language_result(
    ready_count: int,
    blocked_count: int,
    submitted_count: int,
    execute_orders: bool,
    *,
    attempted_count: int = 0,
    unconfirmed_count: int = 0,
    epoch_state: dict[str, Any] | None = None,
) -> str:
    epoch_state = epoch_state or {}
    if epoch_state.get("status") == "pending_flatten":
        return "长桥单策略仓新测试正在等待清空旧持仓；清仓成交确认前，单策略仓和统一实验仓不会接收新的买入信号。"
    if submitted_count:
        return f"长桥实时链路已确认提交 {submitted_count} 笔模拟订单；本地模拟没有参与下单判断。"
    if attempted_count and unconfirmed_count:
        return f"长桥实时链路发出 {attempted_count} 个模拟订单请求，但 {unconfirmed_count} 个未拿到长桥订单号；不按成交或已确认提交计算。"
    if ready_count and not execute_orders:
        return f"长桥实时链路有 {ready_count} 条实时信号通过风控，但当前是只读演练，未提交订单。"
    if ready_count:
        return f"长桥实时链路有 {ready_count} 条实时信号通过风控，等待纸账户提交结果。"
    if blocked_count:
        return "长桥实时链路已隔离本地模拟；当前实时信号都被纸账户风控或策略隔离规则挡住。"
    return "长桥实时链路已就绪；当前没有新的实时信号事件。"


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 长桥模拟账户实时执行链路",
        "",
        f"- 生成时间: `{summary['generated_at']}`",
        f"- 本地模拟隔离: `{summary['local_simulation_isolated']}`",
        f"- 旧快速队列: `{summary['legacy_fast_queue_status']}`",
        f"- 本轮处理信号 / 跳过已处理信号: `{summary['signal_event_count']} / {summary['skipped_previously_processed_signal_count']}`",
        f"- 通过数 / 阻断数 / 请求数 / 已确认提交数: `{summary['ready_order_count']} / {summary['blocked_signal_count']} / {summary.get('attempted_order_count', 0)} / {summary['submitted_count']}`",
        f"- 延迟目标: `{summary['latency_target_ms']}ms`，第一版可接受: `{summary['latency_acceptable_ms']}ms`",
        f"- 延迟信号最大年龄: `{summary['max_delayed_signal_age_seconds']}s`",
        f"- 当前测试基线: `{summary.get('test_epoch', {}).get('test_epoch_id', 'legacy')}` / `{summary.get('test_epoch', {}).get('status', 'legacy')}`",
        f"- 结论: {summary['plain_language_result']}",
        "",
        "## 最近实时信号",
        "",
        "| 信号 | 资金池 | 运行单元 | 标的 | 状态 | 延迟 | 数量 | 限价 | 原因 |",
        "|---|---|---|---:|---|---:|---:|---:|---|",
    ]
    for row in rows[:30]:
        blockers = ",".join(str(item) for item in row.get("blockers", []))
        lines.append(
            "| "
            f"`{row.get('signal_id', '')}` | `{row.get('capital_bucket_label') or row.get('capital_bucket', '')}` | "
            f"`{row.get('runtime_id', '')}` | `{row.get('symbol', '')}` | "
            f"`{row.get('realtime_decision_status', '')}` | `{row.get('latency_ms', '')}` | "
            f"`{row.get('quantity', '')}` | `{row.get('limit_price', '')}` | {blockers} |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 长桥模拟账户只看自己的现金、持仓、挂单、成交和订单编号。",
            "- 本地模拟账本、旧快速队列、本地平仓和 M13/M14 完整重算不参与实时下单决策。",
            "- 修复策略、影子变体、救援策略和辅助模块只留在本地模拟。",
            "- 继续不做碎股、不做空、不做期权，不触碰真实资金。",
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
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


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


def parse_json(text: str) -> Any:
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}


def decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value in (None, ""):
        return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def fmt_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f") if value == value.to_integral_value() else format(value, "f")


def fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY))


def parse_signal_time(value: Any) -> datetime | None:
    if not value:
        return None
    return parse_utc_datetime(str(value))


def parse_utc_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def session_start_is_auto(value: str) -> bool:
    return value.strip().lower() in {"auto", "auto_regular_session", "supervisor_managed"}


def resolve_session_started_at(value: str, generated_at: datetime) -> str:
    if not session_start_is_auto(value):
        return to_iso(parse_utc_datetime(value))
    market_dt = generated_at.astimezone(NEW_YORK)
    session_start = datetime.combine(market_dt.date(), datetime.strptime("09:30", "%H:%M").time(), tzinfo=NEW_YORK)
    return to_iso(session_start)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)
