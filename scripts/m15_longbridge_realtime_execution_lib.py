#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import gzip
import hashlib
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
ORDER_RECONCILIATION_JSON = "m15_longbridge_order_reconciliation.json"
MAX_EXECUTION_LEDGER_BYTES = 50 * 1024 * 1024
MONEY = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
FRESH_FALLBACK_QUOTE_MAX_AGE_MS = 2000
FLATTEN_CURRENT_PRICE_SELL_LIMIT_MULTIPLIER = Decimal("0.995")
FLATTEN_FALLBACK_COST_SELL_LIMIT_MULTIPLIER = Decimal("0.95")
FLATTEN_CURRENT_PRICE_BUY_LIMIT_MULTIPLIER = Decimal("1.005")
FLATTEN_FALLBACK_COST_BUY_LIMIT_MULTIPLIER = Decimal("1.05")
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
    "M10-PA-002-5m-short",
    "M10-PA-013-5m-short",
    "M10-PA-011-ORB-R1-5m-short",
)

PAPER_SHORT_RUNTIME_IDS = (
    "M10-PA-002-5m-short",
    "M10-PA-013-5m-short",
    "M10-PA-011-ORB-R1-5m-short",
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
    ("pa004_long", "PA004-long单仓（M10-PA-004-long-1d）", "M10-PA-004-long-1d"),
    ("pa002_5m", "PA002-5m单仓（M10-PA-002-5m）", "M10-PA-002-5m"),
    ("ftd_baseline", "FTD原版单仓（M12-FTD-001-baseline-1d）", "M12-FTD-001-baseline-1d"),
    ("ftd_loss_streak", "FTD连亏保护单仓（M12-FTD-001-loss-streak-guard-1d）", "M12-FTD-001-loss-streak-guard-1d"),
    ("pa004_mbf", "PA004-MBF单仓（M10-PA-004-MBF-1d）", "M10-PA-004-MBF-1d"),
    ("pa004_mbf_qc", "PA004-MBF-QC单仓（M10-PA-004-MBF-QC-1d）", "M10-PA-004-MBF-QC-1d"),
    ("pa013_5m", "PA013-5m单仓（M10-PA-013-5m）", "M10-PA-013-5m"),
    ("pa011_orb_r1", "PA011-ORB-R1单仓（M10-PA-011-ORB-R1-5m）", "M10-PA-011-ORB-R1-5m"),
    ("pa002_5m_short", "PA002-5m做空测试仓（M10-PA-002-5m）", "M10-PA-002-5m-short"),
    ("pa013_5m_short", "PA013-5m做空测试仓（M10-PA-013-5m）", "M10-PA-013-5m-short"),
    ("pa011_orb_r1_short", "PA011-ORB-R1做空测试仓（M10-PA-011-ORB-R1-5m）", "M10-PA-011-ORB-R1-5m-short"),
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
    position_direction: str = "long"


@dataclass(frozen=True, slots=True)
class RealtimeExecutionConfig:
    stage: str
    title: str
    config_path: Path
    config_digest: str
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
    max_account_state_age_seconds: int
    allowed_runtime_ids: tuple[str, ...]
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
    allow_margin_financing: bool
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

    def max_short_quantity(self, symbol: str, limit_price: Decimal) -> dict[str, Any]:
        del symbol, limit_price
        return {
            "ok": False,
            "status": "short_capacity_unavailable_dry_run_client",
            "max_quantity": ZERO,
            "elapsed_ms": 0,
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
        result = self.run_command(command)
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
        order_id = response_order_id(response)
        if not order_id:
            return {
                "submitted": False,
                "status": "submit_unconfirmed_missing_order_id",
                "order_id": "",
                "confirmation_required": True,
                "response": response,
                "command": redact_command(command),
                "error": "Longbridge CLI returned success code but no order_id; defer confirmation to background reconciliation.",
            }
        return {
            "submitted": True,
            "status": "submitted",
            "order_id": order_id,
            "response": response,
            "command": redact_command(command),
        }

    def run_command(self, command: list[str]) -> Any:
        try:
            return self.command_runner(command, self.config.cli_timeout_seconds)
        except TypeError:
            # Unit-test runners and compatibility integrations historically
            # accepted only the command positional argument.
            return self.command_runner(command)

    def max_short_quantity(self, symbol: str, limit_price: Decimal) -> dict[str, Any]:
        command = [
            self.cli_path,
            "max-qty",
            longbridge_symbol(symbol),
            "--side",
            "sell",
            "--price",
            fmt_money(limit_price),
            "--format",
            "json",
        ]
        started = time.monotonic()
        result = self.run_command(command)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        returncode = int(getattr(result, "returncode", 1))
        stdout = str(getattr(result, "stdout", ""))
        stderr = clean_cli_text(str(getattr(result, "stderr", "")))
        if returncode != 0:
            return {
                "ok": False,
                "status": "short_capacity_query_failed",
                "max_quantity": ZERO,
                "elapsed_ms": elapsed_ms,
                "error": (stderr or clean_cli_text(stdout))[:300],
                "command": redact_command(command),
            }
        response = parse_json(stdout)
        max_quantity = response_max_sell_quantity(response)
        if max_quantity <= ZERO:
            return {
                "ok": False,
                "status": "short_capacity_zero_or_permission_denied",
                "max_quantity": ZERO,
                "elapsed_ms": elapsed_ms,
                "response": response,
                "command": redact_command(command),
            }
        return {
            "ok": True,
            "status": "short_capacity_confirmed",
            "max_quantity": max_quantity,
            "elapsed_ms": elapsed_ms,
            "response": response,
            "command": redact_command(command),
        }

def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    absolute = path if path.is_absolute() else ROOT / path
    try:
        return absolute.relative_to(ROOT).as_posix()
    except ValueError:
        return str(absolute)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RealtimeExecutionConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    realtime = payload.get("longbridge_realtime", {})
    account_model = payload.get("paper_account_model", {})
    short_testing = payload.get("paper_short_testing", {})
    virtual_buckets, runtime_bucket_map = parse_virtual_capital_buckets(payload, account_model)
    epoch = payload.get("test_epoch", {}) if isinstance(payload.get("test_epoch"), dict) else {}
    return RealtimeExecutionConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_execution")),
        title=str(payload.get("title", "长桥模拟账户实时执行链路")),
        config_path=config_path,
        config_digest=config_digest(config_path),
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
        max_account_state_age_seconds=int(realtime.get("max_account_state_age_seconds", 0)),
        allowed_runtime_ids=tuple(
            str(item)
            for item in realtime.get("allowed_runtime_ids", list(DEFAULT_REALTIME_RUNTIME_IDS))
        ),
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
        allow_margin_financing=bool(account_model.get("allow_margin_financing", False)),
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
            "label": "统一实验仓（M10-PA-002-1d/M10-PA-013-1d/M10-PA-008-1d/M10-PA-005-1d/M10-PA-005-5m/M10-PA-012-5m/M10-PA-001-1d）",
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
            position_direction=str(row.get("position_direction") or "long").strip().lower(),
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
    if config.max_account_state_age_seconds < 0:
        raise ValueError("M15 realtime execution max account-state age cannot be negative")
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
        if not config.paper_short_testing_enabled:
            raise ValueError("M15 realtime execution short selling needs explicit paper_short_testing.enabled")
        if not config.paper_short_runtime_ids:
            raise ValueError("M15 realtime execution short selling needs an explicit runtime whitelist")
        if not config.short_test_epoch_id or not config.short_test_started_at:
            raise ValueError("M15 realtime execution short selling needs an independent short test epoch")
        parse_utc_datetime(config.short_test_started_at)
        invalid_short_runtimes = set(config.paper_short_runtime_ids) - set(PAPER_SHORT_RUNTIME_IDS)
        if invalid_short_runtimes:
            raise ValueError(
                "M15 realtime execution short runtime is not an approved paper-short runtime: "
                f"{sorted(invalid_short_runtimes)}"
            )
        if not set(config.paper_short_runtime_ids).issubset(set(config.allowed_runtime_ids)):
            raise ValueError("M15 realtime execution short runtime is not in the main runtime whitelist")
        for runtime_id in config.paper_short_runtime_ids:
            bucket_id = config.runtime_capital_bucket_map.get(runtime_id, "")
            bucket = config.virtual_capital_buckets.get(bucket_id)
            if bucket is None or bucket.position_direction != "short":
                raise ValueError(f"M15 realtime execution short runtime missing a short capital bucket: {runtime_id}")
            if (
                bucket.equity != Decimal("10000")
                or bucket.max_total_exposure != Decimal("2000")
                or bucket.max_symbol_exposure != Decimal("750")
                or bucket.max_risk_per_order != Decimal("10")
            ):
                raise ValueError(f"M15 realtime execution short bucket risk limits drifted: {bucket_id}")
        if config.hard_boundaries.get("short_selling") is not True:
            raise ValueError("M15 realtime execution short selling needs explicit paper-only boundary")
    elif config.paper_short_testing_enabled or config.paper_short_runtime_ids:
        raise ValueError("M15 realtime execution short test configuration requires allow_short_selling")
    if config.allow_options:
        raise ValueError("M15 realtime execution forbids options")
    if config.allow_margin_financing:
        raise ValueError("M15 realtime execution forbids margin financing")
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
    signal_events_override: list[dict[str, Any]] | None = None,
    account_state_override: dict[str, Any] | None = None,
    existing_ledger_override: list[dict[str, Any]] | None = None,
    emitted_ledger_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    execution_cycle_started_monotonic = time.monotonic()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    session_started_at = resolve_session_started_at(config.session_started_at, now)
    execution_run_id = build_execution_run_id(config, now)
    session_run_id = build_session_run_id(config, session_started_at)
    # The SDK runtime owns a fresh in-memory account snapshot.  JSON remains
    # an audit/dashboard projection and must not delay a real-time order.
    account_state = dict(account_state_override) if account_state_override is not None else read_json(config.paper_account_state_path)
    epoch_state = load_or_update_test_epoch_state(config, account_state, now)
    signal_events = (
        list(signal_events_override)
        if signal_events_override is not None
        else read_jsonl(config.realtime_signal_events_path)
    )
    ledger_retention = (
        {
            "status": "runtime_memory_no_hot_path_compaction",
            "row_count": len(existing_ledger_override),
        }
        if existing_ledger_override is not None
        else compact_execution_ledger_if_needed(
            config.output_dir / LEDGER_JSONL,
            current_epoch_id=str(epoch_state.get("test_epoch_id") or ""),
            additional_current_epoch_ids=current_test_epoch_ids(config, epoch_state),
        )
    )
    raw_existing_ledger = (
        list(existing_ledger_override)
        if existing_ledger_override is not None
        else read_jsonl(config.output_dir / LEDGER_JSONL)
    )
    existing_ledger = hydrate_unconfirmed_execution_rows(
        raw_existing_ledger,
        account_state,
        read_json(config.output_dir / ORDER_RECONCILIATION_JSON),
    )
    current_epoch_ledger = ledger_rows_for_epoch(existing_ledger, epoch_state, config)
    existing_submitted_ids = {
        str(row.get("signal_id"))
        for row in current_epoch_ledger
        if row.get("signal_id") and row.get("submission_status") == "submitted"
    }
    existing_processed_ids = processed_signal_ids(current_epoch_ledger, config)
    if epoch_state.get("status") == "pending_flatten":
        signal_events_to_process = build_epoch_flatten_signals(config, account_state, now, epoch_state)
        suppressed_by_epoch = len(signal_events)
    else:
        signal_events_to_process = [
            event
            for event in signal_events
            if str(event.get("signal_id") or "") not in existing_processed_ids
            and signal_event_in_current_epoch(event, epoch_state, config)
        ]
        suppressed_by_epoch = sum(
            1
            for event in signal_events
            if str(event.get("signal_id") or "") not in existing_processed_ids
            and not signal_event_in_current_epoch(event, epoch_state, config)
        )
    signal_events_to_process = sorted(signal_events_to_process, key=realtime_execution_signal_sort_key)
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
    existing_submitted_long_open_symbols = submitted_open_long_symbol_set(current_epoch_ledger, session_started_at)
    tracked_short_open_order_ids = submitted_short_order_ids_by_symbol(
        current_epoch_ledger,
        session_started_at,
        position_action="open_short",
    )
    tracked_short_cover_order_ids = submitted_short_order_ids_by_symbol(
        current_epoch_ledger,
        session_started_at,
        position_action="close_short",
    )
    existing_submitted_short_cover_keys = submitted_short_cover_key_set(
        current_epoch_ledger,
        session_started_at,
        account_state=account_state,
    )
    existing_submitted_short_cover_symbols = submitted_short_cover_symbol_set(
        current_epoch_ledger,
        session_started_at,
        account_state=account_state,
    )
    tracked_short_positions_by_open_order = tracked_short_position_quantities_by_open_order(
        current_epoch_ledger,
        account_state,
    )
    short_reentry_low_by_key = confirmed_short_cover_structure_lows(current_epoch_ledger, account_state)
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
    selected_close_quantity_by_symbol: dict[str, Decimal] = {}

    for event in signal_events_to_process:
        decision = evaluate_signal_event(
            config=config,
            signal=event,
            account_state=account_state,
            epoch_state=epoch_state,
            generated_at=now,
            session_started_at=session_started_at,
            execution_run_id=execution_run_id,
            session_run_id=session_run_id,
            submitted_signal_ids=submitted_signal_ids,
            existing_submitted_exposure=existing_submitted_exposure,
            selected_bucket_exposure=selected_bucket_exposure,
            selected_bucket_symbol_exposure=selected_bucket_symbol_exposure,
            existing_strategy_symbols=existing_strategy_symbols,
            selected_strategy_symbols=selected_strategy_symbols,
            same_day_loss_exit_symbols=same_day_loss_exit_symbols,
            existing_submitted_sell_symbols=existing_submitted_sell_symbols,
            existing_submitted_long_open_symbols=existing_submitted_long_open_symbols,
            tracked_short_open_order_ids=tracked_short_open_order_ids,
            tracked_short_cover_order_ids=tracked_short_cover_order_ids,
            existing_submitted_short_cover_keys=existing_submitted_short_cover_keys,
            existing_submitted_short_cover_symbols=existing_submitted_short_cover_symbols,
            tracked_short_positions_by_open_order=tracked_short_positions_by_open_order,
            short_reentry_low_by_key=short_reentry_low_by_key,
            selected_close_quantity_by_symbol=selected_close_quantity_by_symbol,
            broker_client=broker_client,
        )
        row = decision["ledger_row"]
        ready_for_submission = bool(decision["ready"])
        if ready_for_submission and ledger_row_closes_position(row):
            close_symbol = base_symbol(str(row.get("symbol") or ""))
            selected_close_quantity_by_symbol[close_symbol] = (
                selected_close_quantity_by_symbol.get(close_symbol, ZERO)
                + decimal(row.get("submitted_quantity", row.get("quantity", "0")))
            )
        broker_request_started_at: datetime | None = None
        broker_request_started_monotonic = 0.0
        if ready_for_submission and config.execute_orders:
            broker_request_started_at = datetime.now(UTC)
            broker_request_started_monotonic = time.monotonic()
            execution_queue_delay_ms = max(
                0,
                int((broker_request_started_monotonic - execution_cycle_started_monotonic) * 1000),
            )
            initial_latency_ms = int_decimal(row.get("latency_ms", 0))
            signal_to_request_ms = initial_latency_ms + execution_queue_delay_ms
            row["broker_request_started_at"] = to_iso(broker_request_started_at)
            row["execution_queue_delay_ms"] = execution_queue_delay_ms
            row["signal_to_request_ms"] = signal_to_request_ms
            row["latency_ms"] = signal_to_request_ms
            row["latency_band"] = latency_band_for(config, signal_to_request_ms)
            if (
                initial_latency_ms <= config.latency_acceptable_ms
                and signal_to_request_ms > config.latency_acceptable_ms
                and not bool(event.get("realtime_rebuilt_from_delayed_signal"))
            ):
                row["blockers"] = list(row.get("blockers", [])) + [
                    "blocked_delayed_signal_requires_realtime_rebuild"
                ]
                row["realtime_decision_status"] = "blocked_execution_queue_latency_requires_rebuild"
                ready_for_submission = False

        if ready_for_submission:
            ready_count += 1
            order_payload = decision["order_payload"]
            if config.execute_orders:
                attempted_count += 1
                try:
                    submission = broker_client.submit_order(order_payload)
                except Exception as exc:
                    # A broker-side rejection belongs to this order only.  The
                    # persistent SDK runtime must remain available for later
                    # exits and fresh signals.
                    submission = {
                        "submitted": False,
                        "status": f"broker_submit_failed:{type(exc).__name__}",
                        "order_id": "",
                        "error": str(exc)[:500],
                    }
                if should_retry_market_exit_as_marketable_limit(row, submission, order_payload):
                    fallback_payload = marketable_limit_fallback_payload(order_payload)
                    row["fallback_attempted"] = True
                    row["fallback_order_payload"] = dict(fallback_payload)
                    try:
                        fallback_submission = broker_client.submit_order(fallback_payload)
                    except Exception as exc:
                        fallback_submission = {
                            "submitted": False,
                            "status": f"broker_submit_failed:{type(exc).__name__}",
                            "order_id": "",
                            "error": str(exc)[:500],
                        }
                    row["fallback_submission_status"] = str(fallback_submission.get("status") or "")
                    row["submission_response"] = {
                        "primary": submission,
                        "fallback": fallback_submission,
                    }
                    if fallback_submission.get("submitted") and fallback_submission.get("order_id"):
                        submission = dict(fallback_submission)
                        order_payload = fallback_payload
                        row["order_payload"] = dict(fallback_payload)
                        row["order_type"] = str(fallback_payload.get("order_type") or row.get("order_type") or "")
                        row["limit_price"] = str(fallback_payload.get("limit_price") or row.get("limit_price") or "")
                        row["submission_fallback_used"] = True
                    else:
                        submission = {
                            **submission,
                            "fallback_submission": fallback_submission,
                        }
                broker_response_at = datetime.now(UTC)
                row["broker_response_at"] = to_iso(broker_response_at)
                row["broker_request_elapsed_ms"] = max(
                    0,
                    int((time.monotonic() - broker_request_started_monotonic) * 1000),
                )
                row["submission_response"] = submission
                row["longbridge_order_id"] = str(submission.get("order_id") or "")
                row["broker_order_id"] = str(submission.get("order_id") or "")
                row["order_id"] = str(submission.get("order_id") or "")
                if submission.get("submitted") and submission.get("order_id"):
                    row["submission_status"] = "submitted"
                    row["submission_confirmation_state"] = "broker_order_id_received"
                    row["confirmation_required"] = False
                    row["submitted_at"] = generated_at_iso
                    if ledger_row_closes_position(row):
                        row["exit_state"] = "submitted"
                    if ledger_row_closes_short(row):
                        short_cover_key = submitted_short_cover_key_from_row(row)
                        if short_cover_key:
                            existing_submitted_short_cover_keys.add(short_cover_key)
                        existing_submitted_short_cover_symbols.add(base_symbol(str(row.get("symbol") or "")))
                    submitted_count += 1
                    submitted_signal_ids.add(str(row["signal_id"]))
                else:
                    row["submission_status"] = str(submission.get("status", "submit_failed"))
                    if row["submission_status"] == "submit_unconfirmed_missing_order_id":
                        row["submission_confirmation_state"] = "awaiting_broker_reconciliation"
                        row["confirmation_required"] = True
                    if ledger_row_closes_position(row):
                        row["exit_state"] = (
                            "unconfirmed"
                            if row["submission_status"] == "submit_unconfirmed_missing_order_id"
                            else "submit_failed"
                        )
                    if row["submission_status"] == "submit_unconfirmed_missing_order_id":
                        unconfirmed_count += 1
            else:
                row["submission_status"] = "dry_run_ready_not_submitted"
                row["submission_confirmation_state"] = "dry_run_not_sent"
                row["confirmation_required"] = False
                row["broker_request_started_at"] = ""
                row["broker_response_at"] = ""
                row["broker_request_elapsed_ms"] = 0
            if ledger_row_opens_position(row):
                symbol = str(row["symbol"])
                notional = decimal(row.get("notional", "0"))
                bucket_id = str(row.get("capital_bucket") or "")
                selected_bucket_exposure[bucket_id] = selected_bucket_exposure.get(bucket_id, ZERO) + notional
                selected_bucket_symbol_exposure[(bucket_id, symbol)] = (
                    selected_bucket_symbol_exposure.get((bucket_id, symbol), ZERO) + notional
                )
                if row.get("direction") != "short":
                    strategy_key = parent_strategy_id(str(row.get("strategy_id") or row.get("runtime_id") or ""))
                    selected_strategy_symbols.setdefault((bucket_id, strategy_key), set()).add(symbol)
        else:
            blocked_count += 1
            row["submission_status"] = "blocked_not_submitted"
            if ledger_row_closes_position(row):
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
        "signal_event_input_mode": "direct_runtime_events" if signal_events_override is not None else "jsonl_audit_stream",
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
        "runtime_identity": {
            "config_path": project_path(config.config_path),
            "config_digest": config.config_digest,
            "execution_run_id": execution_run_id,
            "session_run_id": session_run_id,
            "session_started_at": session_started_at,
        },
        "session_started_at": session_started_at,
        "test_epoch": epoch_state,
        "ledger_retention": ledger_retention,
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
        "execution_queue_delay_blocked_count": sum(
            1
            for row in ledger_rows
            if row.get("realtime_decision_status") == "blocked_execution_queue_latency_requires_rebuild"
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
        "quality_sorted_signal_count": len(signal_events_to_process),
        "bucket_pressure_quality_blocked_count": sum(
            1 for row in ledger_rows if "blocked_bucket_pressure_quality_below_threshold" in row.get("blockers", [])
        ),
        "same_day_loss_cooldown_blocked_count": sum(
            1 for row in ledger_rows if "blocked_same_day_loss_exit_cooldown" in row.get("blockers", [])
        ),
        "strategy_daily_limit_blocked_count": sum(
            1 for row in ledger_rows if "blocked_strategy_daily_new_symbol_limit" in row.get("blockers", [])
        ),
        "allowed_runtime_count": len(config.allowed_runtime_ids),
        "runtime_ids_seen_this_cycle": sorted({str(row.get("runtime_id") or "") for row in ledger_rows if row.get("runtime_id")}),
        "recent_execution_inputs": recent_execution_inputs(ledger_rows),
        "blocked_by_reason": count_by_reason(ledger_rows),
        "runtime_whitelist": list(config.allowed_runtime_ids),
        "repair_and_shadow_isolation": {
            "repair_runtimes_local_only": sorted(REPAIR_RUNTIME_IDS),
            "auxiliary_modules_local_only": sorted(AUXILIARY_STRATEGY_IDS),
            "shadow_markers_local_only": list(SHADOW_RUNTIME_MARKERS),
        },
        "inputs": {
            "execution_config": project_path(config.config_path),
            "realtime_signal_events": project_path(config.realtime_signal_events_path),
            "paper_account_state": project_path(config.paper_account_state_path),
            "test_epoch_state": project_path(config.test_epoch_state_path),
            "local_simulation_ledger": "",
            "fast_signal_queue": "",
        },
        "input_config_digests": {
            "execution_config": config.config_digest,
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
    append_jsonl(config.output_dir / LEDGER_JSONL, ledger_rows)
    if emitted_ledger_rows is not None:
        emitted_ledger_rows.extend(ledger_rows)
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
    execution_run_id: str,
    session_run_id: str,
    submitted_signal_ids: set[str],
    existing_submitted_exposure: dict[tuple[str, str], Decimal],
    selected_bucket_exposure: dict[str, Decimal],
    selected_bucket_symbol_exposure: dict[tuple[str, str], Decimal],
    existing_strategy_symbols: dict[tuple[str, str], set[str]],
    selected_strategy_symbols: dict[tuple[str, str], set[str]],
    same_day_loss_exit_symbols: set[tuple[str, str]],
    existing_submitted_sell_symbols: set[str],
    existing_submitted_long_open_symbols: set[str],
    tracked_short_open_order_ids: dict[str, set[str]],
    tracked_short_cover_order_ids: dict[str, set[str]],
    existing_submitted_short_cover_keys: set[tuple[str, str, str, str]],
    existing_submitted_short_cover_symbols: set[str],
    tracked_short_positions_by_open_order: dict[tuple[str, str, str, str], Decimal],
    short_reentry_low_by_key: dict[tuple[str, str, str], Decimal],
    selected_close_quantity_by_symbol: dict[str, Decimal],
    broker_client: Any,
) -> dict[str, Any]:
    risk_check_started_at = datetime.now(UTC)
    signal_id = str(signal.get("signal_id") or "")
    runtime_id = str(signal.get("runtime_id") or "")
    strategy_id = str(signal.get("strategy_id") or parent_strategy_id(runtime_id))
    symbol = str(signal.get("symbol") or "").upper()
    order_type = normalize_order_type(signal.get("order_type"))
    position_action = normalize_position_action(signal.get("position_action") or signal.get("event_type") or signal.get("action"))
    side = normalize_side(signal.get("side") or signal.get("direction"), position_action=position_action)
    opening_long = is_open_long(side, position_action)
    closing_long = is_close_long(side, position_action)
    opening_short = is_open_short(side, position_action)
    closing_short = is_close_short(side, position_action)
    direction = "short" if opening_short or closing_short or str(signal.get("direction") or "").lower() == "short" else "long"
    effective_epoch_state = test_epoch_state_for_direction(config, epoch_state, direction)
    raw_quantity = decimal(signal.get("quantity", signal.get("suggested_quantity", "0")))
    quantity_normalization = normalize_whole_share_quantity(raw_quantity, config.allow_fractional_shares)
    quantity = quantity_normalization.submitted_quantity
    limit_price = decimal(signal.get("limit_price", signal.get("entry_price", "0")))
    trigger_price = decimal(signal.get("trigger_price", "0"))
    stop_price = decimal(signal.get("stop_price", "0"))
    target_price = decimal(signal.get("target_price", "0"))
    current_price = decimal(signal.get("current_price", signal.get("last_price", limit_price)))
    original_order_type = order_type
    original_trigger_price = trigger_price
    order_type_adjustment_status = ""
    if (
        side == "buy"
        and order_type == "trigger_limit"
        and trigger_price > ZERO
        and current_price > ZERO
        and trigger_price <= current_price
    ):
        order_type = "limit"
        trigger_price = ZERO
        order_type_adjustment_status = "trigger_limit_downgraded_to_limit_trigger_already_reached"
    risk_per_share = abs(limit_price - stop_price) if limit_price > ZERO and stop_price > ZERO else ZERO
    risk_amount = (
        risk_per_share * quantity
        if (opening_long or opening_short) and risk_per_share > ZERO
        else decimal(signal.get("risk_amount", "0"))
    )
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
    quality_score = normalized_signal_quality_score(signal)
    known_fees = (
        decimal(signal.get("estimated_entry_fees", "0"))
        + decimal(signal.get("estimated_exit_fees_at_target", "0"))
        + decimal(signal.get("estimated_regulatory_fees_at_target", "0"))
    )
    if (opening_long or opening_short) and target_price > ZERO and limit_price > ZERO:
        gross_profit = (
            (target_price - limit_price) * quantity
            if opening_long
            else (limit_price - target_price) * quantity
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
    account_state_at = parse_signal_time(account_state.get("generated_at"))
    account_state_age_seconds = (
        max(0, int((generated_at - account_state_at).total_seconds())) if account_state_at else None
    )
    if config.max_account_state_age_seconds > 0 and (
        account_state_age_seconds is None or account_state_age_seconds > config.max_account_state_age_seconds
    ):
        blockers.append("blocked_account_state_stale")
    if not exit_only_position_signal:
        blockers.extend(strategy_isolation_blockers(runtime_id, strategy_id, config.allowed_runtime_ids))
    held_quantities = held_symbol_quantities(account_state)
    held_long_quantities = long_held_symbol_quantities(account_state)
    available_quantities = available_symbol_quantities(account_state)
    open_sell_order_quantities = open_order_quantities_by_side(account_state, "sell")
    open_buy_order_quantities = open_order_quantities_by_side(account_state, "buy")
    broker_short_quantities = account_short_position_quantities(account_state)
    short_position_key = (capital_bucket, runtime_id, symbol)
    source_open_order_id = str(signal.get("source_open_order_id") or "")
    source_open_trade_id = str(signal.get("source_open_trade_id") or "")
    source_open_remaining_quantity = decimal(signal.get("source_open_remaining_quantity", "0"))
    short_lot_key = (capital_bucket, runtime_id, symbol, source_open_order_id)
    tracked_short_quantity = tracked_short_positions_by_open_order.get(short_lot_key, ZERO)
    short_capacity_check: dict[str, Any] = {
        "status": "not_applicable",
        "max_quantity": ZERO,
        "elapsed_ms": 0,
    }
    if opening_short:
        if not config.allow_short_selling or not config.paper_short_testing_enabled:
            blockers.append("blocked_short_disabled")
        elif runtime_id not in set(config.paper_short_runtime_ids):
            blockers.append("blocked_short_runtime_not_whitelisted")
        elif not bucket or bucket.position_direction != "short":
            blockers.append("blocked_missing_short_capital_bucket")
        if held_long_quantities.get(symbol, ZERO) > ZERO:
            blockers.append("blocked_short_conflicts_with_existing_long_position")
        if symbol in existing_submitted_long_open_symbols or has_untracked_open_order(
            account_state,
            symbol,
            "buy",
            tracked_short_cover_order_ids,
        ):
            blockers.append("blocked_short_conflicts_with_pending_long_buy")
        if has_untracked_open_order(account_state, symbol, "sell", tracked_short_open_order_ids):
            blockers.append("blocked_unattributed_open_sell_order_same_symbol")
        if symbol in existing_submitted_short_cover_symbols:
            blockers.append("blocked_short_pending_cover_same_symbol")
        previous_cover_low = short_reentry_low_by_key.get(short_position_key, ZERO)
        current_structure_low = decimal(signal.get("short_structure_low", "0"))
        if previous_cover_low > ZERO and current_structure_low <= ZERO:
            blockers.append("blocked_short_reentry_structure_unavailable")
        elif previous_cover_low > ZERO and current_structure_low >= previous_cover_low:
            blockers.append("blocked_short_reentry_requires_new_structure_low")
    elif closing_long:
        exact_fill_identity_required = str(effective_epoch_state.get("test_epoch_id") or "").startswith(
            "m15-sdk-formal-"
        ) and not exit_only_position_signal
        if exact_fill_identity_required and (not source_open_order_id or not source_open_trade_id):
            blockers.append("blocked_close_long_missing_exact_open_fill_identity")
        elif exact_fill_identity_required and source_open_remaining_quantity <= ZERO:
            blockers.append("blocked_close_long_missing_open_batch_remaining_quantity")
        elif exact_fill_identity_required and quantity > source_open_remaining_quantity:
            blockers.append("blocked_close_long_quantity_over_open_fill_batch")
        if held_quantities.get(symbol, ZERO) <= ZERO:
            blockers.append("blocked_close_without_long_position")
        elif quantity > held_quantities.get(symbol, ZERO):
            blockers.append("blocked_close_quantity_over_position")
        elif quantity > available_quantities.get(symbol, held_quantities.get(symbol, ZERO)):
            blockers.append("blocked_close_quantity_not_available")
        elif quantity + selected_close_quantity_by_symbol.get(symbol, ZERO) > available_quantities.get(
            symbol, held_quantities.get(symbol, ZERO)
        ):
            blockers.append("blocked_close_quantity_over_available_after_reservations")
        if open_sell_order_quantities.get(symbol, ZERO) > ZERO:
            blockers.append("blocked_existing_sell_open_order_same_symbol")
        if symbol in existing_submitted_sell_symbols:
            blockers.append("blocked_existing_submitted_sell_same_symbol")
    elif closing_short:
        if exit_only_position_signal:
            if broker_short_quantities.get(symbol, ZERO) <= ZERO:
                blockers.append("blocked_short_position_state_unverified")
            elif quantity > broker_short_quantities.get(symbol, ZERO):
                blockers.append("blocked_close_short_quantity_over_position")
        elif not source_open_order_id:
            blockers.append("blocked_close_short_missing_source_open_order_id")
        elif tracked_short_quantity <= ZERO:
            blockers.append("blocked_close_short_without_verified_short_position")
        elif broker_short_quantities.get(symbol, ZERO) <= ZERO:
            blockers.append("blocked_short_position_state_unverified")
        elif quantity > tracked_short_quantity or quantity > broker_short_quantities.get(symbol, ZERO):
            blockers.append("blocked_close_short_quantity_over_position")
        if has_untracked_open_order(
            account_state,
            symbol,
            "buy",
            tracked_short_cover_order_ids,
        ):
            blockers.append("blocked_existing_buy_open_order_same_symbol")
        if short_lot_key in existing_submitted_short_cover_keys:
            blockers.append("blocked_existing_submitted_short_cover_same_short_lot")
    elif not opening_long:
        blockers.append("blocked_unknown_side")
    if opening_long or opening_short:
        frozen_symbols = {
            base_symbol(str(item))
            for item in account_state.get("fill_attribution_frozen_symbols", [])
            if str(item)
        }
        if symbol in frozen_symbols:
            blockers.append("blocked_fill_attribution_mismatch_symbol_frozen")
        if not bucket:
            blockers.append("blocked_missing_capital_bucket")
        bucket_symbol = (capital_bucket, symbol)
        if existing_submitted_exposure.get(bucket_symbol, ZERO) > ZERO:
            blockers.append("blocked_existing_submitted_order_same_bucket_symbol")
        if selected_bucket_symbol_exposure.get(bucket_symbol, ZERO) > ZERO:
            blockers.append("blocked_existing_selected_order_same_bucket_symbol")
        if opening_long and bucket_symbol in same_day_loss_exit_symbols:
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
        if opening_long and daily_limit > 0:
            strategy_bucket_key = (capital_bucket, strategy_key)
            existing_symbols = existing_strategy_symbols.get(strategy_bucket_key, set())
            selected_symbols = selected_strategy_symbols.get(strategy_bucket_key, set())
            if symbol not in existing_symbols and symbol not in selected_symbols and len(existing_symbols | selected_symbols) >= daily_limit:
                blockers.append("blocked_strategy_daily_new_symbol_limit")
    if OPTION_SYMBOL_RE.match(symbol):
        blockers.append("blocked_options_disabled")
    exit_market_allowed = (closing_long or closing_short) and (
        exit_only_position_signal or runtime_id == "M15-LONGBRIDGE-EPOCH-FLATTEN"
    )
    if order_type not in {"limit", "trigger_limit", "market"}:
        blockers.append("blocked_order_type")
    if order_type == "market" and not exit_market_allowed:
        blockers.append("blocked_market_order_entry_only_exit_supported")
    if order_type == "trigger_limit" and trigger_price <= ZERO:
        blockers.append("missing_trigger_price")
    if quantity_normalization.blocker:
        blockers.append(quantity_normalization.blocker)
    elif quantity <= ZERO:
        blockers.append("blocked_non_positive_quantity")
    if order_type != "market" and limit_price <= ZERO:
        blockers.append("missing_limit_price")
    if (opening_long or opening_short) and (stop_price <= ZERO or target_price <= ZERO):
        blockers.append("missing_stop_or_target")
    if (opening_long or opening_short) and current_price > ZERO:
        if opening_long:
            if stop_price >= current_price:
                blockers.append("blocked_invalid_stop_vs_current_price")
            if target_price <= current_price:
                blockers.append("blocked_invalid_target_vs_current_price")
        else:
            if stop_price <= current_price:
                blockers.append("blocked_invalid_short_stop_vs_current_price")
            if target_price >= current_price:
                blockers.append("blocked_invalid_short_target_vs_current_price")
    max_risk = min(config.max_risk_per_order, bucket.max_risk_per_order) if bucket else config.max_risk_per_order
    max_symbol_exposure = bucket.max_symbol_exposure if bucket else config.max_symbol_exposure
    max_total_exposure = bucket.max_total_exposure if bucket else config.max_total_exposure
    order_currency = order_currency_for_symbol(symbol)
    order_currency_cash = order_currency_available_cash(account_state, order_currency)
    order_currency_cash_after_order = order_currency_cash - notional if opening_long else order_currency_cash
    bucket_symbol_exposure = (
        existing_submitted_exposure.get((capital_bucket, symbol), ZERO)
        + selected_bucket_symbol_exposure.get((capital_bucket, symbol), ZERO)
    )
    bucket_total_exposure = sum(
        value for (row_bucket, _symbol), value in existing_submitted_exposure.items() if row_bucket == capital_bucket
    ) + selected_bucket_exposure.get(capital_bucket, ZERO)
    quantity_cap_adjustment_status = ""
    quantity_before_bucket_cap = quantity
    bucket_remaining_total_exposure = max_total_exposure - bucket_total_exposure
    bucket_remaining_symbol_exposure = max_symbol_exposure - bucket_symbol_exposure
    bucket_pressure_quality_threshold = bucket_pressure_minimum_quality(bucket_remaining_total_exposure)
    bucket_pressure_quality_status = "not_applicable"
    if (opening_long or opening_short) and bucket_pressure_quality_threshold > ZERO:
        bucket_pressure_quality_status = "passed"
        if quality_score < bucket_pressure_quality_threshold:
            bucket_pressure_quality_status = "blocked"
            blockers.append("blocked_bucket_pressure_quality_below_threshold")
    if (opening_long or opening_short) and limit_price > ZERO and quantity > ZERO and not quantity_normalization.blocker:
        remaining_exposure = min(bucket_remaining_total_exposure, bucket_remaining_symbol_exposure, max_symbol_exposure)
        if remaining_exposure <= ZERO:
            quantity_cap_adjustment_status = "blocked_no_bucket_exposure_remaining"
            quantity = ZERO
        elif notional > remaining_exposure:
            capped_quantity = (remaining_exposure / limit_price).to_integral_value(rounding=ROUND_FLOOR)
            if capped_quantity < quantity:
                quantity = max(capped_quantity, ZERO)
                quantity_cap_adjustment_status = "reduced_to_bucket_remaining_exposure"
        if quantity != quantity_before_bucket_cap:
            notional = quantity * limit_price if limit_price > ZERO else ZERO
            risk_amount = risk_per_share * quantity if risk_per_share > ZERO else risk_amount
            if target_price > ZERO and limit_price > ZERO and known_fees > ZERO:
                net_profit = (
                    (target_price - limit_price) * quantity
                    if opening_long
                    else (limit_price - target_price) * quantity
                ) - known_fees
    order_currency_cash_after_order = order_currency_cash - notional if opening_long else order_currency_cash
    if (opening_long or opening_short) and quantity_before_bucket_cap > ZERO and quantity <= ZERO and quantity_cap_adjustment_status:
        blockers.append("blocked_bucket_remaining_exposure_below_one_share")
    if (opening_long or opening_short) and risk_amount > max_risk:
        blockers.append("blocked_risk_over_cap")
    if (opening_long or opening_short) and notional > max_symbol_exposure:
        blockers.append("blocked_symbol_exposure_over_cap")
    if (opening_long or opening_short) and bucket_symbol_exposure + notional > max_symbol_exposure:
        blockers.append("blocked_symbol_exposure_over_cap")
    if (opening_long or opening_short) and bucket_total_exposure + notional > max_total_exposure:
        blockers.append("blocked_total_exposure_over_cap")
    if opening_long and available_cash(account_state) - notional < ZERO:
        blockers.append("blocked_cash_reserve")
    if opening_long and not config.allow_margin_financing and order_currency_cash_after_order < ZERO:
        blockers.append("blocked_margin_financing_disabled")
    reward_r = directional_reward_r_ratio(limit_price, stop_price, target_price, direction) if (opening_long or opening_short) else ZERO
    minimum_reward_r = runtime_minimum_reward_r(config, runtime_id, strategy_id) if (opening_long or opening_short) else ZERO
    minimum_net_profit = runtime_minimum_net_profit(config, runtime_id, strategy_id) if (opening_long or opening_short) else ZERO
    profit_gate_status = (
        profit_quality_gate(config, signal, net_profit, runtime_id, strategy_id) if (opening_long or opening_short) else "not_applicable"
    )
    if profit_gate_status == "below_minimum":
        blockers.append("blocked_fee_profit_below_minimum")
    elif profit_gate_status == "requires_confluence_or_quality":
        blockers.append("blocked_fee_profit_requires_confluence")
    if (opening_long or opening_short) and reward_r < minimum_reward_r:
        blockers.append("blocked_reward_r_below_minimum")
    if opening_short and not blockers and config.execute_orders:
        capacity_provider = getattr(broker_client, "max_short_quantity", None)
        if not callable(capacity_provider):
            blockers.append("blocked_short_capacity_query_unavailable")
            short_capacity_check = {
                "status": "short_capacity_query_unavailable",
                "max_quantity": ZERO,
                "elapsed_ms": 0,
            }
        else:
            short_capacity_check = capacity_provider(symbol, limit_price)
            broker_max_quantity = decimal(short_capacity_check.get("max_quantity", "0"))
            if not short_capacity_check.get("ok"):
                blockers.append("blocked_short_broker_capacity_unavailable")
            elif broker_max_quantity < quantity:
                blockers.append("blocked_short_broker_capacity_insufficient")
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

    risk_check_finished_at = datetime.now(UTC)
    order_payload = build_order_payload(
        signal,
        side,
        order_type,
        symbol,
        quantity,
        limit_price,
        trigger_price,
        position_action=position_action,
    )
    order_payload.update(
        {
            "capital_bucket": capital_bucket,
            "capital_bucket_label": bucket_label,
            "execution_run_id": execution_run_id,
            "execution_config_digest": config.config_digest,
            "session_run_id": session_run_id,
            "test_epoch_id": str(effective_epoch_state.get("test_epoch_id") or ""),
            "raw_suggested_quantity": fmt_decimal(quantity_normalization.raw_quantity),
            "submitted_quantity": fmt_decimal(quantity),
            "quantity_rounding_adjustment": fmt_decimal(quantity_normalization.rounded_down_quantity),
            "quantity_normalization_status": quantity_normalization.status,
            "quantity_cap_adjustment_status": quantity_cap_adjustment_status,
            "quantity_before_bucket_cap": fmt_decimal(quantity_before_bucket_cap),
            "order_type_adjustment_status": order_type_adjustment_status,
            "original_order_type": original_order_type,
            "original_trigger_price": fmt_money(original_trigger_price) if original_trigger_price > ZERO else "",
            "quality_score": fmt_decimal(quality_score),
            "bucket_pressure_quality_threshold": fmt_decimal(bucket_pressure_quality_threshold),
            "bucket_pressure_quality_status": bucket_pressure_quality_status,
            "short_capacity_check": short_capacity_check,
            "source_open_order_id": str(signal.get("source_open_order_id") or ""),
            "source_open_trade_id": source_open_trade_id,
            "source_open_remaining_quantity": fmt_decimal(source_open_remaining_quantity),
            "short_structure_low": str(signal.get("short_structure_low") or ""),
            "exit_reason": str(signal.get("exit_reason") or ""),
            "market_exit_no_reprice": bool(order_type == "market" and (closing_long or closing_short)),
            "fallback_quote_age_ms": fallback_quote_age_ms(signal, generated_at),
            "current_price": fmt_money(current_price) if current_price > ZERO else "",
        }
    )
    ledger_row = {
        "stage": config.stage,
        "execution_run_id": execution_run_id,
        "execution_config_path": project_path(config.config_path),
        "execution_config_digest": config.config_digest,
        "session_run_id": session_run_id,
        "signal_id": signal_id,
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "capital_bucket": capital_bucket,
        "capital_bucket_label": bucket_label,
        "test_epoch_id": str(effective_epoch_state.get("test_epoch_id") or ""),
        "test_started_at": str(effective_epoch_state.get("test_started_at") or ""),
        "test_epoch_status": str(effective_epoch_state.get("status") or ""),
        "symbol": symbol,
        "timeframe": str(signal.get("timeframe") or ""),
        "direction": direction,
        "position_action": position_action,
        "side": side,
        "order_type": order_type,
        "original_order_type": original_order_type,
        "order_type_adjustment_status": order_type_adjustment_status,
        "raw_suggested_quantity": fmt_decimal(quantity_normalization.raw_quantity),
        "submitted_quantity": fmt_decimal(quantity),
        "quantity_rounding_adjustment": fmt_decimal(quantity_normalization.rounded_down_quantity),
        "quantity_normalization_status": quantity_normalization.status,
        "quantity_normalization_blocker": quantity_normalization.blocker,
        "quantity_cap_adjustment_status": quantity_cap_adjustment_status,
        "quantity_before_bucket_cap": fmt_decimal(quantity_before_bucket_cap),
        "bucket_remaining_total_exposure_before_order": fmt_money(bucket_remaining_total_exposure),
        "bucket_remaining_symbol_exposure_before_order": fmt_money(bucket_remaining_symbol_exposure),
        "quantity": fmt_decimal(quantity),
        "limit_price": fmt_money(limit_price),
        "trigger_price": fmt_money(trigger_price) if trigger_price > ZERO else "",
        "original_trigger_price": fmt_money(original_trigger_price) if original_trigger_price > ZERO else "",
        "stop_price": fmt_money(stop_price) if stop_price > ZERO else "",
        "target_price": fmt_money(target_price) if target_price > ZERO else "",
        "current_price": fmt_money(current_price) if current_price > ZERO else "",
        "risk_amount": fmt_money(risk_amount),
        "notional": fmt_money(notional),
        "net_profit_after_fees_at_target": fmt_money(net_profit),
        "profit_quality_gate": profit_gate_status,
        "reward_r": fmt_decimal(reward_r),
        "quality_score": fmt_decimal(quality_score),
        "signal_quality_score": fmt_decimal(quality_score),
        "market_confirmation_status": str(signal.get("market_confirmation_status") or ""),
        "market_confirmation_symbols": str(signal.get("market_confirmation_symbols") or ""),
        "close_position": str(signal.get("close_position") or ""),
        "close_to_close_percent": str(signal.get("close_to_close_percent") or ""),
        "volume_ratio": str(signal.get("volume_ratio") or ""),
        "bucket_pressure_quality_threshold": fmt_decimal(bucket_pressure_quality_threshold),
        "bucket_pressure_quality_status": bucket_pressure_quality_status,
        "short_capacity_check_status": str(short_capacity_check.get("status") or ""),
        "short_capacity_check_underlying_status": str(
            short_capacity_check.get("underlying_status") or ""
        ),
        "short_capacity_source": str(short_capacity_check.get("capacity_source") or ""),
        "short_capacity_cache_age_seconds": short_capacity_check.get(
            "cache_age_seconds"
        ),
        "short_capacity_max_quantity": fmt_decimal(decimal(short_capacity_check.get("max_quantity", "0"))),
        "short_capacity_cash_max_quantity": fmt_decimal(
            decimal(short_capacity_check.get("cash_max_quantity", "0"))
        ),
        "short_capacity_margin_max_quantity": fmt_decimal(
            decimal(short_capacity_check.get("margin_max_quantity", "0"))
        ),
        "short_capacity_basis": str(
            short_capacity_check.get("capacity_basis") or ""
        ),
        "short_capacity_query_ms": int_decimal(short_capacity_check.get("elapsed_ms", 0)),
        "short_position_verified_quantity": fmt_decimal(tracked_short_quantity),
        "minimum_reward_r": fmt_decimal(minimum_reward_r),
        "minimum_net_profit_after_fees": fmt_money(minimum_net_profit),
        "bucket_equity": fmt_money(bucket.equity) if bucket else "",
        "bucket_max_total_exposure": fmt_money(max_total_exposure),
        "bucket_max_symbol_exposure": fmt_money(max_symbol_exposure),
        "bucket_max_risk_per_order": fmt_money(max_risk),
        "order_currency": order_currency,
        "order_currency_available_cash": fmt_money(order_currency_cash),
        "order_currency_cash_after_order": fmt_money(order_currency_cash_after_order),
        "margin_financing_allowed": config.allow_margin_financing,
        "confluence_support_count": int_decimal(signal.get("confluence_support_count", "0")),
        "confluence_multiplier": fmt_decimal(decimal(signal.get("confluence_multiplier", "1"))),
        "high_quality_signal": signal_is_high_quality(signal),
        "source_market_event_id": str(signal.get("source_market_event_id") or signal.get("market_event_id") or ""),
        "source_open_signal_id": str(signal.get("source_open_signal_id") or ""),
        "source_open_order_id": str(signal.get("source_open_order_id") or ""),
        "source_open_trade_id": source_open_trade_id,
        "source_open_remaining_quantity": fmt_decimal(source_open_remaining_quantity),
        "short_structure_low": str(signal.get("short_structure_low") or ""),
        "exit_reason": str(signal.get("exit_reason") or ""),
        "execute_orders": config.execute_orders,
        "paper_trading_approval": config.paper_trading_approval,
        "created_at": to_iso(created_at) if created_at else "",
        "processed_at": to_iso(generated_at),
        "market_event_time": str(signal.get("market_event_time") or ""),
        "account_state_at": to_iso(account_state_at) if account_state_at else "",
        "account_state_age_seconds": account_state_age_seconds,
        "risk_check_started_at": to_iso(risk_check_started_at),
        "risk_check_finished_at": to_iso(risk_check_finished_at),
        "risk_check_elapsed_ms": max(0, int((risk_check_finished_at - risk_check_started_at).total_seconds() * 1000)),
        "latency_ms": latency_ms if latency_ms is not None else "",
        "latency_band": latency_band,
        "signal_to_request_ms": "",
        "execution_queue_delay_ms": "",
        "signal_age_limit_seconds": age_limit_seconds,
        "signal_age_limit_source": age_limit_source,
        "signal_expires_at": to_iso(signal_expires_at) if signal_expires_at else "",
        "realtime_decision_status": status,
        "blockers": blockers,
        "order_payload": order_payload if not blockers else {},
        "longbridge_order_id": "",
        "broker_order_id": "",
        "order_id": "",
        "submission_confirmation_state": "not_attempted",
        "confirmation_required": False,
        "local_simulation_ignored": True,
        "local_close_event_ignored": bool(signal.get("latest_close_event_time_after_open") or signal.get("local_close_event_id")),
        "longbridge_account_position_checked": True,
        "longbridge_account_open_orders_checked": True,
        "longbridge_realtime_submitted_ledger_checked": True,
        "m13_m14_gate_used_for_order": False,
        "fast_queue_used_for_order": False,
        "exit_state": (
            "ready_to_submit"
            if (closing_long or closing_short) and not blockers
            else ("blocked" if (closing_long or closing_short) else "")
        ),
        "exit_only_position_signal": exit_only_position_signal,
        "client_request_id": str(order_payload.get("client_request_id") or ""),
        "market_exit_no_reprice": bool(order_payload.get("market_exit_no_reprice")),
        "fallback_quote_age_ms": int_decimal(order_payload.get("fallback_quote_age_ms", -1)),
        "fallback_attempted": False,
        "fallback_submission_status": "",
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
    *,
    position_action: str = "",
) -> dict[str, Any]:
    signal_id = str(signal.get("signal_id") or "")
    runtime_id = str(signal.get("runtime_id") or "")
    client_request_id = stable_client_request_id(
        signal_id=signal_id,
        runtime_id=runtime_id,
        symbol=symbol,
        side=side,
        position_action=position_action,
        test_epoch_id=str(signal.get("test_epoch_id") or ""),
    )
    payload = {
        "source": "longbridge_realtime_signal_event",
        "signal_id": signal_id,
        "runtime_id": runtime_id,
        "strategy_id": str(signal.get("strategy_id") or ""),
        "position_action": position_action
        or str(signal.get("position_action") or signal.get("event_type") or signal.get("action") or ""),
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "client_request_id": client_request_id,
        "quantity": int(quantity),
        "time_in_force": str(signal.get("time_in_force") or "day"),
        "outside_rth": "RTH_ONLY",
    }
    if order_type != "market":
        payload["limit_price"] = fmt_money(limit_price)
    if order_type == "trigger_limit":
        payload["trigger_price"] = fmt_money(trigger_price)
    return payload


def longbridge_order_command(config: RealtimeExecutionConfig, cli_path: str, order_payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    side = str(order_payload.get("side") or "")
    position_action = normalize_position_action(order_payload.get("position_action"))
    broker_side = longbridge_broker_side(side, position_action)
    symbol = longbridge_symbol(str(order_payload.get("symbol") or ""))
    quantity = int(decimal(order_payload.get("quantity", "0")))
    limit_price = str(order_payload.get("limit_price") or "")
    order_type = str(order_payload.get("order_type") or "")
    trigger_price = str(order_payload.get("trigger_price") or "")
    signal_id = str(order_payload.get("signal_id") or "")
    blockers: list[str] = []
    if not broker_side:
        blockers.append("unsupported_longbridge_order_side")
    if side == "sell_short" and position_action != "open_short":
        blockers.append("invalid_open_short_position_action")
    if position_action == "close_short" and broker_side != "buy":
        blockers.append("invalid_close_short_broker_side")
    if not symbol:
        blockers.append("missing_symbol")
    if quantity <= 0:
        blockers.append("missing_quantity")
    if order_type != "market" and not limit_price:
        blockers.append("missing_limit_price")
    if order_type not in {"limit", "trigger_limit", "market"}:
        blockers.append("unsupported_order_type")
    if order_type == "trigger_limit" and not trigger_price:
        blockers.append("missing_trigger_price")
    if blockers:
        return [], blockers
    remark = (
        f"PAT-RT {signal_id} {order_payload.get('client_request_id', '')} {order_payload.get('runtime_id', '')} "
        f"{position_action or 'open_long'} {order_payload.get('capital_bucket', '')}"
    )[:255]
    command = [
        cli_path,
        "order",
        broker_side,
        symbol,
        str(quantity),
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
    if order_type == "market":
        command.extend(["--order-type", "MO"])
    elif order_type == "limit":
        command.extend(["--price", limit_price, "--order-type", "LO"])
    else:
        command.extend(["--price", limit_price, "--order-type", "LIT", "--trigger-price", trigger_price])
    assert_submit_command(command)
    return command, []


def longbridge_broker_side(side: str, position_action: str) -> str:
    normalized_side = str(side or "").strip().lower()
    if normalized_side == "sell_short" and position_action == "open_short":
        return "sell"
    if normalized_side == "buy" and position_action == "close_short":
        return "buy"
    if normalized_side in {"buy", "sell"}:
        return normalized_side
    return ""


def assert_submit_command(command: list[str]) -> None:
    if len(command) < 5:
        raise ValueError("Longbridge realtime order command is incomplete")
    args = command[1:]
    if args[0] != "order" or args[1] not in {"buy", "sell"}:
        raise ValueError(f"Longbridge realtime order command is not a buy/sell order: {args}")
    if "--yes" not in args or "--format" not in args:
        raise ValueError(f"Longbridge realtime order command is missing safety flags: {args}")


def run_longbridge_command(command: list[str], timeout_seconds: int = 30) -> Any:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
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
        has_positions, has_open_orders, has_pending_confirmations = epoch_activation_state(account_state)
        needs_flatten = has_positions or has_open_orders or has_pending_confirmations
        status = "pending_flatten" if config.flatten_existing_positions_before_new_epoch and needs_flatten else "active"
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
            "activation_blocker": epoch_activation_blocker(
                has_positions=has_positions,
                has_open_orders=has_open_orders,
                has_pending_confirmations=has_pending_confirmations,
            ) if status == "pending_flatten" else "",
        }
    elif current.get("status") == "pending_flatten":
        has_positions, has_open_orders, has_pending_confirmations = epoch_activation_state(account_state)
        if not has_positions and not has_open_orders and not has_pending_confirmations:
            current["status"] = "active"
            current["test_started_at"] = to_iso(now)
            current["activated_at"] = to_iso(now)
            current["activation_blocker"] = ""
        else:
            current["activation_blocker"] = epoch_activation_blocker(
                has_positions=has_positions,
                has_open_orders=has_open_orders,
                has_pending_confirmations=has_pending_confirmations,
            )
            current["last_flatten_check_at"] = to_iso(now)
    elif current.get("status") in {"active", "activated"}:
        if not current.get("test_started_at"):
            # SDK flatten activation historically wrote activated_at without
            # copying it into the execution epoch. Recover only from that
            # durable timestamp so pre-activation signals remain excluded.
            activated_at = str(current.get("activated_at") or "")
            if parse_signal_time(activated_at):
                current["test_started_at"] = activated_at
        if current.get("status") == "activated" and current.get("test_started_at"):
            current["status"] = "active"
    config.test_epoch_state_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(config.test_epoch_state_path, current)
    return current


def epoch_activation_state(account_state: dict[str, Any]) -> tuple[bool, bool, bool]:
    has_positions = bool(held_symbol_quantities(account_state))
    open_orders = account_state.get("open_orders") if isinstance(account_state.get("open_orders"), list) else []
    has_open_orders = any(isinstance(row, dict) for row in open_orders)
    has_pending_confirmations = any(
        isinstance(row, dict) and bool(row.get("sdk_pending_confirmation"))
        for key in ("open_orders", "orders", "historical_orders")
        for row in (account_state.get(key) if isinstance(account_state.get(key), list) else [])
    )
    return has_positions, has_open_orders, has_pending_confirmations


def epoch_activation_blocker(
    *,
    has_positions: bool,
    has_open_orders: bool,
    has_pending_confirmations: bool,
) -> str:
    if has_positions:
        return "existing_longbridge_positions_need_flatten"
    if has_open_orders:
        return "waiting_for_flatten_exit_orders_to_finish"
    if has_pending_confirmations:
        return "waiting_for_flatten_pending_confirmations_to_clear"
    return ""


def test_epoch_state_for_direction(
    config: RealtimeExecutionConfig,
    primary_epoch_state: dict[str, Any],
    direction: str,
) -> dict[str, Any]:
    if direction != "short":
        return primary_epoch_state
    return {
        "enabled": config.paper_short_testing_enabled,
        "status": "active" if config.paper_short_testing_enabled else "disabled",
        "test_epoch_id": config.short_test_epoch_id,
        "test_started_at": config.short_test_started_at,
        "archive_previous_records": True,
        "position_direction": "short",
    }


def current_test_epoch_ids(config: RealtimeExecutionConfig, epoch_state: dict[str, Any]) -> set[str]:
    ids = {str(epoch_state.get("test_epoch_id") or "")}
    if config.paper_short_testing_enabled:
        ids.add(config.short_test_epoch_id)
    return {item for item in ids if item}


def signal_event_in_current_epoch(
    signal: dict[str, Any],
    epoch_state: dict[str, Any],
    config: RealtimeExecutionConfig,
) -> bool:
    position_action = normalize_position_action(signal.get("position_action") or signal.get("event_type") or signal.get("action"))
    side = normalize_side(signal.get("side") or signal.get("direction"), position_action=position_action)
    direction = "short" if is_open_short(side, position_action) or is_close_short(side, position_action) else "long"
    effective_epoch = test_epoch_state_for_direction(config, epoch_state, direction)
    if not effective_epoch.get("enabled") or effective_epoch.get("status") == "legacy":
        return True
    started_at = parse_signal_time(effective_epoch.get("test_started_at"))
    if not started_at:
        return False
    created_at = parse_signal_time(signal.get("created_at") or signal.get("generated_at") or signal.get("signal_time"))
    return bool(created_at and created_at >= started_at)


def ledger_rows_for_epoch(
    rows: list[dict[str, Any]],
    epoch_state: dict[str, Any],
    config: RealtimeExecutionConfig,
) -> list[dict[str, Any]]:
    if not epoch_state.get("enabled") or epoch_state.get("status") == "legacy":
        return rows
    epoch_ids = current_test_epoch_ids(config, epoch_state)
    epoch_id = str(epoch_state.get("test_epoch_id") or "")
    started_at = parse_signal_time(epoch_state.get("test_started_at"))
    matched: list[dict[str, Any]] = []
    for row in rows:
        row_epoch_id = str(row.get("test_epoch_id") or "")
        if row_epoch_id and row_epoch_id in epoch_ids:
            matched.append(row)
            continue
        if row_epoch_id == config.short_test_epoch_id:
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
        short_position = is_short_position_row(row)
        price, price_source = first_positive_decimal_with_key(
            row,
            ("market_price", "last_price", "current_price", "last_done", "price", "cost_price", "average_cost"),
        )
        if price > ZERO:
            if price_source in {"cost_price", "average_cost"}:
                price *= (
                    FLATTEN_FALLBACK_COST_BUY_LIMIT_MULTIPLIER
                    if short_position
                    else FLATTEN_FALLBACK_COST_SELL_LIMIT_MULTIPLIER
                )
            else:
                price *= (
                    FLATTEN_CURRENT_PRICE_BUY_LIMIT_MULTIPLIER
                    if short_position
                    else FLATTEN_CURRENT_PRICE_SELL_LIMIT_MULTIPLIER
                )
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
                "direction": "short" if short_position else "long",
                "side": "buy" if short_position else "sell",
                "position_action": "close_short" if short_position else "close_long",
                "order_type": "market",
                "quantity": fmt_decimal(quantity.to_integral_value()),
                "limit_price": "",
                "current_price": fmt_money(price) if price > ZERO else "",
                "risk_amount": "0.00",
                "notional": fmt_money(quantity * price) if price > ZERO else "0.00",
                "net_profit_after_fees_at_target": "0.00",
                "flatten_limit_price_source": price_source,
                "fallback_quote_age_ms": -1,
                "flatten_position_direction": "short" if short_position else "long",
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
        used_exposure = submitted_exposure + selected_exposure
        remaining_exposure = max(bucket.max_total_exposure - used_exposure, ZERO)
        rows.append(
            {
                "capital_bucket": bucket_id,
                "label": bucket.label,
                "equity": fmt_money(bucket.equity),
                "max_total_exposure": fmt_money(bucket.max_total_exposure),
                "max_symbol_exposure": fmt_money(bucket.max_symbol_exposure),
                "used_exposure": fmt_money(used_exposure),
                "remaining_exposure": fmt_money(remaining_exposure),
                "over_exposure_cap": used_exposure > bucket.max_total_exposure,
                "exposure_source": (
                    "longbridge_filled_batches_plus_pending_orders"
                    if fill_attributed_open_exposure_by_bucket_symbol(
                        account_state or {}
                    )
                    is not None
                    else "legacy_submission_ledger"
                ),
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


def order_currency_for_symbol(symbol: str) -> str:
    text = str(symbol or "").upper()
    if text.endswith(".HK"):
        return "HKD"
    if text.endswith(".SG"):
        return "SGD"
    return "USD"


def order_currency_available_cash(account_state: dict[str, Any], currency: str) -> Decimal:
    currency_key = str(currency or "USD").upper()
    currency_cash = account_state.get("currency_cash")
    if isinstance(currency_cash, dict):
        row = currency_cash.get(currency_key)
        if isinstance(row, dict):
            for key in ("available_cash", "withdraw_cash", "cash", "total_cash"):
                if key in row:
                    return decimal(row.get(key, "0"))
    direct_key = f"{currency_key.lower()}_available_cash"
    if direct_key in account_state:
        return decimal(account_state.get(direct_key, "0"))
    if currency_key == "USD":
        for key in ("usd_cash", "usd_total_cash"):
            if key in account_state:
                return decimal(account_state.get(key, "0"))
    return available_cash(account_state)


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


def is_short_position_row(row: dict[str, Any]) -> bool:
    if bool(row.get("is_short")):
        return True
    for key in ("position_side", "side", "direction", "position_type", "holding_side"):
        value = str(row.get(key) or "").strip().lower()
        if value in {"short", "sell_short", "sell", "bearish"}:
            return True
    return decimal(row.get("quantity", row.get("qty", "0"))) < ZERO


def long_held_symbol_quantities(account_state: dict[str, Any]) -> dict[str, Decimal]:
    quantities: dict[str, Decimal] = {}
    positions = account_state.get("positions") if isinstance(account_state.get("positions"), list) else []
    for row in positions:
        if not isinstance(row, dict) or is_short_position_row(row):
            continue
        symbol = base_symbol(str(row.get("symbol", "")))
        quantity = decimal(row.get("quantity", row.get("qty", "0")))
        if symbol and quantity > ZERO:
            quantities[symbol] = quantities.get(symbol, ZERO) + quantity
    return quantities


def account_short_position_quantities(account_state: dict[str, Any]) -> dict[str, Decimal]:
    quantities: dict[str, Decimal] = {}
    positions = account_state.get("positions") if isinstance(account_state.get("positions"), list) else []
    for row in positions:
        if not isinstance(row, dict) or not is_short_position_row(row):
            continue
        symbol = base_symbol(str(row.get("symbol", "")))
        quantity = abs(decimal(row.get("quantity", row.get("qty", "0"))))
        if symbol and quantity > ZERO:
            quantities[symbol] = quantities.get(symbol, ZERO) + quantity
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


def directional_reward_r_ratio(entry: Decimal, stop: Decimal, target: Decimal, direction: str) -> Decimal:
    if direction == "short":
        risk = stop - entry
        reward = entry - target
        if risk <= ZERO or reward <= ZERO:
            return ZERO
        return reward / risk
    return reward_r_ratio(entry, stop, target)


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
    if ZERO < score <= Decimal("1"):
        return score >= Decimal("0.8")
    return score >= Decimal("80")


def normalized_signal_quality_score(signal: dict[str, Any]) -> Decimal:
    score = decimal(signal.get("quality_score", signal.get("signal_quality_score", "0")))
    if ZERO < score <= Decimal("1"):
        return score * HUNDRED
    return score


def bucket_pressure_minimum_quality(bucket_remaining_total_exposure: Decimal) -> Decimal:
    if bucket_remaining_total_exposure < Decimal("750"):
        return Decimal("90")
    if bucket_remaining_total_exposure < Decimal("1500"):
        return Decimal("80")
    return ZERO


def realtime_execution_signal_sort_key(signal: dict[str, Any]) -> tuple[int, str, Decimal, Decimal, Decimal, str]:
    position_action = normalize_position_action(signal.get("position_action") or signal.get("event_type") or signal.get("action"))
    side = normalize_side(signal.get("side") or signal.get("direction"), position_action=position_action)
    if position_action == "stop_loss":
        execution_priority = 0
    elif (
        is_close_long(side, position_action)
        or is_close_short(side, position_action)
    ):
        execution_priority = 1
    elif is_open_short(side, position_action):
        execution_priority = 2
    else:
        execution_priority = 3
    return (
        execution_priority,
        str(signal.get("capital_bucket") or ""),
        -normalized_signal_quality_score(signal),
        -decimal(signal.get("net_profit_after_fees_at_target", "0")),
        -decimal(signal.get("reward_r", "0")),
        str(signal.get("symbol") or ""),
    )


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
        position_action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        side = normalize_side(row.get("side"), position_action=position_action)
        if is_open_long(side, position_action) or is_open_short(side, position_action):
            quantities[symbol] = quantities.get(symbol, ZERO) + quantity
            notionals[symbol] = notionals.get(symbol, ZERO) + notional
        elif is_close_long(side, position_action) or is_close_short(side, position_action):
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
    attributed_exposure = fill_attributed_open_exposure_by_bucket_symbol(
        account_state
    )
    if attributed_exposure is not None:
        return add_pending_open_order_exposure(
            attributed_exposure,
            rows,
            session_start,
            account_state,
        )
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
        position_action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        side = normalize_side(row.get("side"), position_action=position_action)
        opening_short = is_open_short(side, position_action)
        if is_open_long(side, position_action) or opening_short:
            order_id = ledger_row_order_id(row)
            account_order = broker_order_for_ledger_row(row, order_by_id)
            active_quantity, active_notional = submitted_open_active_exposure(
                row,
                account_order,
                symbol_materialized=symbol in materialized_symbols,
                opening_short=opening_short,
            )
            if active_quantity <= ZERO or active_notional <= ZERO:
                continue
            quantities[key] = quantities.get(key, ZERO) + active_quantity
            notionals[key] = notionals.get(key, ZERO) + active_notional
        elif is_close_long(side, position_action) or is_close_short(side, position_action):
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


def fill_attributed_open_exposure_by_bucket_symbol(
    account_state: dict[str, Any],
) -> dict[tuple[str, str], Decimal] | None:
    payload = account_state.get(
        "fill_attributed_open_exposure_by_bucket_symbol"
    )
    if not isinstance(payload, dict):
        return None
    exposure: dict[tuple[str, str], Decimal] = {}
    for bucket, symbol_rows in payload.items():
        if not isinstance(symbol_rows, dict):
            continue
        for symbol, value in symbol_rows.items():
            notional = decimal(value)
            key = (str(bucket), base_symbol(str(symbol)))
            if key[0] and key[1] and notional > ZERO:
                exposure[key] = exposure.get(key, ZERO) + notional
    return exposure


def add_pending_open_order_exposure(
    attributed_exposure: dict[tuple[str, str], Decimal],
    rows: list[dict[str, Any]],
    session_start: datetime,
    account_state: dict[str, Any],
) -> dict[tuple[str, str], Decimal]:
    """Add only the unfilled part of broker orders to actual fill exposure."""
    exposure = dict(attributed_exposure)
    order_by_id = latest_account_orders_by_id(account_state)
    materialized_symbols = (
        set(held_symbol_quantities(account_state))
        | open_order_symbol_set(account_state)
    )
    seen_order_ids: set[str] = set()
    for row in rows:
        if row.get("submission_status") != "submitted":
            continue
        submitted_at = parse_signal_time(
            row.get("submitted_at")
            or row.get("processed_at")
            or row.get("created_at")
        )
        if submitted_at and submitted_at < session_start:
            continue
        position_action = normalize_position_action(
            row.get("position_action") or row.get("exit_reason")
        )
        side = normalize_side(row.get("side"), position_action=position_action)
        if not (is_open_long(side, position_action) or is_open_short(side, position_action)):
            continue
        bucket = str(row.get("capital_bucket") or "legacy")
        symbol = base_symbol(str(row.get("symbol") or ""))
        if not bucket or not symbol:
            continue
        order_id = ledger_row_order_id(row)
        if order_id and order_id in seen_order_ids:
            continue
        if order_id:
            seen_order_ids.add(order_id)
        account_order = broker_order_for_ledger_row(row, order_by_id)
        if account_order is None:
            # Confirmed historical orders are already represented by the
            # fill-attribution baseline. Only an unconfirmed request without
            # a broker id may still need a temporary reservation.
            if order_id or symbol in materialized_symbols:
                continue
            pending_notional = decimal(row.get("notional", "0"))
        else:
            status = str(account_order.get("status") or "").strip().lower().replace(" ", "_")
            if status in {"filled", "done", "completed", "canceled", "cancelled", "rejected", "expired", "withdrawn", "failed"}:
                continue
            order_quantity = decimal(
                account_order.get(
                    "quantity",
                    account_order.get("qty", row.get("quantity", "0")),
                )
            )
            executed_quantity = decimal(
                account_order.get(
                    "executed_quantity",
                    account_order.get("filled_quantity", "0"),
                )
            )
            remaining_quantity = max(order_quantity - executed_quantity, ZERO)
            order_price = decimal(
                account_order.get(
                    "price",
                    row.get("limit_price", row.get("current_price", "0")),
                )
            )
            pending_notional = remaining_quantity * order_price
        if pending_notional > ZERO:
            key = (bucket, symbol)
            exposure[key] = exposure.get(key, ZERO) + pending_notional
    return exposure


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


def hydrate_unconfirmed_execution_rows(
    rows: list[dict[str, Any]],
    account_state: dict[str, Any],
    order_reconciliation: dict[str, Any],
) -> list[dict[str, Any]]:
    """Overlay exact broker reconciliation on immutable local request rows.

    The realtime ledger records the original CLI response and is intentionally
    append-only.  If a successful response omitted an order id, the hot account
    snapshot or background reconciliation can later prove the broker order from
    its exact ``PAT-RT <signal_id>`` remark.  Consumers receive that confirmed
    identity in memory without racing a concurrent execution append.
    """
    direct_by_signal = exact_account_orders_by_signal_id(account_state)
    reconciled_by_signal = exact_reconciled_orders_by_signal_id(order_reconciliation)
    hydrated: list[dict[str, Any]] = []
    for source_row in rows:
        row = dict(source_row)
        if str(row.get("submission_status") or "") != "submit_unconfirmed_missing_order_id":
            hydrated.append(row)
            continue
        signal_id = str(row.get("signal_id") or "")
        broker_order = direct_by_signal.get(signal_id) or reconciled_by_signal.get(signal_id)
        order_id = str(broker_order.get("order_id") or broker_order.get("id") or "") if broker_order else ""
        if not signal_id or not order_id:
            hydrated.append(row)
            continue
        broker_status = str(broker_order.get("canonical_status") or broker_order.get("status") or "unknown")
        terminal = broker_order_is_terminal({"status": broker_status})
        row.update(
            {
                "order_id": order_id,
                "longbridge_order_id": order_id,
                "broker_order_id": order_id,
                "submission_status": "submitted",
                "submission_confirmation_state": (
                    "broker_reconciled_terminal" if terminal else "broker_reconciled_open"
                ),
                "confirmation_required": False,
                "broker_reconciliation_status": broker_status,
                "broker_reconciliation_match_method": str(
                    broker_order.get("attribution_match_method") or "account_order_remark_signal_id"
                ),
                "_broker_order_from_reconciliation": dict(broker_order),
            }
        )
        hydrated.append(row)
    return hydrated


def exact_account_orders_by_signal_id(account_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, dict[str, Any]]] = {}
    for key in ("historical_orders", "orders", "open_orders"):
        rows = account_state.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            signal_id = realtime_signal_id_from_order_remark(row)
            order_id = str(row.get("order_id") or row.get("id") or "")
            if signal_id and order_id:
                candidates.setdefault(signal_id, {})[order_id] = row
    return {
        signal_id: next(iter(orders.values()))
        for signal_id, orders in candidates.items()
        if len(orders) == 1
    }


def exact_reconciled_orders_by_signal_id(order_reconciliation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = order_reconciliation.get("rows") if isinstance(order_reconciliation.get("rows"), list) else []
    candidates: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("attribution_status") != "matched_m15_realtime_ledger":
            continue
        if row.get("attribution_match_method") != "remark_signal_id":
            continue
        signal_id = str(row.get("signal_id") or "")
        order_id = str(row.get("order_id") or "")
        if signal_id and order_id:
            candidates.setdefault(signal_id, {})[order_id] = row
    return {
        signal_id: next(iter(orders.values()))
        for signal_id, orders in candidates.items()
        if len(orders) == 1
    }


def realtime_signal_id_from_order_remark(order: dict[str, Any]) -> str:
    for key in ("remark", "note", "message"):
        text = str(order.get(key) or "")
        match = re.search(r"(?:^|\s)PAT-RT\s+(\S+)", text)
        if match:
            return match.group(1)
    return ""


def broker_order_for_ledger_row(
    row: dict[str, Any],
    order_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    order_id = ledger_row_order_id(row)
    if order_id and order_id in order_by_id:
        return order_by_id[order_id]
    reconciled = row.get("_broker_order_from_reconciliation")
    return reconciled if isinstance(reconciled, dict) else None


def submitted_open_active_exposure(
    ledger_row: dict[str, Any],
    account_order: dict[str, Any] | None,
    *,
    symbol_materialized: bool,
    opening_short: bool = False,
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
        if opening_short:
            notional = (
                executed_quantity * executed_price
                if executed_price > ZERO
                else row_notional * (executed_quantity / row_quantity)
            )
            return executed_quantity, notional
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


def submitted_open_long_symbol_set(rows: list[dict[str, Any]], session_started_at: str) -> set[str]:
    session_start = parse_utc_datetime(session_started_at)
    symbols: set[str] = set()
    for row in rows:
        if row.get("submission_status") != "submitted":
            continue
        submitted_at = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if submitted_at and submitted_at < session_start:
            continue
        position_action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        side = normalize_side(row.get("side"), position_action=position_action)
        if not is_open_long(side, position_action):
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        if symbol:
            symbols.add(symbol)
    return symbols


def submitted_short_order_ids_by_symbol(
    rows: list[dict[str, Any]],
    session_started_at: str,
    *,
    position_action: str,
) -> dict[str, set[str]]:
    """Return broker order ids already attributed to a controlled paper short action.

    The broker only exposes Buy/Sell, so this local attribution prevents a
    tracked buy-to-cover from being mistaken for a pending long buy and allows
    separate short buckets to keep their own pending short opens. Unknown
    broker orders deliberately remain blockers.
    """
    session_start = parse_utc_datetime(session_started_at)
    output: dict[str, set[str]] = {}
    for row in rows:
        if row.get("submission_status") != "submitted":
            continue
        submitted_at = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if submitted_at and submitted_at < session_start:
            continue
        action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        if action != position_action:
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        order_id = ledger_row_order_id(row)
        if symbol and order_id:
            output.setdefault(symbol, set()).add(order_id)
    return output


def submitted_short_cover_symbol_set(
    rows: list[dict[str, Any]],
    session_started_at: str,
    *,
    account_state: dict[str, Any],
) -> set[str]:
    session_start = parse_utc_datetime(session_started_at)
    order_by_id = latest_account_orders_by_id(account_state)
    symbols: set[str] = set()
    for row in rows:
        if not short_cover_submission_is_pending(row, order_by_id):
            continue
        action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        if action != "close_short":
            continue
        submitted_at = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if submitted_at and submitted_at < session_start:
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        if symbol:
            symbols.add(symbol)
    return symbols


def submitted_short_cover_key_from_row(row: dict[str, Any]) -> tuple[str, str, str, str] | None:
    bucket = str(row.get("capital_bucket") or "")
    runtime_id = str(row.get("runtime_id") or "")
    symbol = base_symbol(str(row.get("symbol") or ""))
    source_open_order_id = str(row.get("source_open_order_id") or "")
    if not all((bucket, runtime_id, symbol, source_open_order_id)):
        return None
    return bucket, runtime_id, symbol, source_open_order_id


def submitted_short_cover_key_set(
    rows: list[dict[str, Any]],
    session_started_at: str,
    *,
    account_state: dict[str, Any],
) -> set[tuple[str, str, str, str]]:
    session_start = parse_utc_datetime(session_started_at)
    order_by_id = latest_account_orders_by_id(account_state)
    keys: set[tuple[str, str, str, str]] = set()
    for row in rows:
        if not short_cover_submission_is_pending(row, order_by_id):
            continue
        action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        if action != "close_short":
            continue
        submitted_at = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if submitted_at and submitted_at < session_start:
            continue
        key = submitted_short_cover_key_from_row(row)
        if key:
            keys.add(key)
    return keys


def short_cover_submission_is_pending(
    row: dict[str, Any],
    order_by_id: dict[str, dict[str, Any]],
) -> bool:
    """Keep a short lot blocked until its cover order reaches a broker terminal state.

    A time-based guard can expire while a day order is still open.  That would
    allow a fresh exit signal to buy-to-cover the same original short twice.
    Missing broker state is also deliberately treated as unresolved until the
    background reconciliation proves that the cover order became terminal.
    """
    submission_status = str(row.get("submission_status") or "")
    if submission_status not in {"submitted", "submit_unconfirmed_missing_order_id"}:
        return False
    action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
    if action != "close_short":
        return False
    order_id = ledger_row_order_id(row)
    if not order_id:
        return True
    broker_order = broker_order_for_ledger_row(row, order_by_id)
    if not broker_order:
        return True
    return not broker_order_is_terminal(broker_order)


def broker_order_is_terminal(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").strip().lower().replace(" ", "_")
    return status in {
        "filled",
        "executed",
        "done",
        "completed",
        "canceled",
        "cancelled",
        "rejected",
        "expired",
        "withdrawn",
        "failed",
    }


def has_untracked_open_order(
    account_state: dict[str, Any],
    symbol: str,
    side_filter: str,
    known_order_ids_by_symbol: dict[str, set[str]],
) -> bool:
    """Treat any broker order without an exact controlled-short id as unsafe.

    This keeps a real pending long buy or an externally created sell from being
    netted with the virtual short slices, while allowing separately attributed
    short buckets to share a symbol in the single paper account.
    """
    expected_symbol = base_symbol(symbol)
    expected_side = side_filter.lower()
    known_ids = known_order_ids_by_symbol.get(expected_symbol, set())
    open_orders = account_state.get("open_orders") if isinstance(account_state.get("open_orders"), list) else []
    for row in open_orders:
        if not isinstance(row, dict) or base_symbol(str(row.get("symbol") or "")) != expected_symbol:
            continue
        side = str(row.get("side") or row.get("order_side") or "").strip().lower()
        if expected_side == "buy" and not side.startswith("buy"):
            continue
        if expected_side == "sell" and not side.startswith("sell"):
            continue
        order_id = str(row.get("order_id") or row.get("id") or row.get("orderId") or "")
        if not order_id or order_id not in known_ids:
            return True
    return False


def order_has_confirmed_fill(account_order: dict[str, Any] | None) -> bool:
    if not isinstance(account_order, dict):
        return False
    status = str(account_order.get("status") or "").strip().lower().replace(" ", "_")
    if status in {"filled", "executed", "done", "completed", "partially_filled", "partial_filled"}:
        return True
    return decimal(account_order.get("executed_quantity", account_order.get("filled_quantity", "0"))) > ZERO


def confirmed_order_quantity(account_order: dict[str, Any], fallback: Decimal) -> Decimal:
    quantity = decimal(
        account_order.get(
            "executed_quantity",
            account_order.get("filled_quantity", account_order.get("filled_qty", fallback)),
        )
    )
    return quantity if quantity > ZERO else fallback


def tracked_short_position_quantities_by_open_order(
    rows: list[dict[str, Any]],
    account_state: dict[str, Any],
) -> dict[tuple[str, str, str, str], Decimal]:
    """Return only short lots whose broker order is confirmed as filled.

    Local submissions are intentionally insufficient: a buy-to-cover is allowed
    only against a short opening that is present in Longbridge order state.
    """
    order_by_id = latest_account_orders_by_id(account_state)
    quantities: dict[tuple[str, str, str, str], Decimal] = {}
    for row in sorted(rows, key=lambda item: str(item.get("submitted_at") or item.get("processed_at") or "")):
        if row.get("submission_status") != "submitted":
            continue
        position_action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        side = normalize_side(row.get("side"), position_action=position_action)
        symbol = base_symbol(str(row.get("symbol") or ""))
        runtime_id = str(row.get("runtime_id") or "")
        bucket = str(row.get("capital_bucket") or "")
        if not symbol or not runtime_id or not bucket:
            continue
        order_id = ledger_row_order_id(row)
        account_order = broker_order_for_ledger_row(row, order_by_id)
        if not order_has_confirmed_fill(account_order):
            continue
        quantity = confirmed_order_quantity(account_order, decimal(row.get("quantity", row.get("submitted_quantity", "0"))))
        if quantity <= ZERO:
            continue
        if is_open_short(side, position_action):
            if not order_id:
                continue
            key = (bucket, runtime_id, symbol, order_id)
            quantities[key] = quantities.get(key, ZERO) + quantity
        elif is_close_short(side, position_action):
            source_open_order_id = str(row.get("source_open_order_id") or "")
            if not source_open_order_id:
                continue
            key = (bucket, runtime_id, symbol, source_open_order_id)
            remaining = quantities.get(key, ZERO) - quantity
            if remaining > ZERO:
                quantities[key] = remaining
            else:
                quantities.pop(key, None)
    return quantities


def tracked_short_position_quantities(
    rows: list[dict[str, Any]],
    account_state: dict[str, Any],
) -> dict[tuple[str, str, str], Decimal]:
    """Compatibility aggregate; close-short validation uses the exact-lot helper."""
    aggregate: dict[tuple[str, str, str], Decimal] = {}
    for (bucket, runtime_id, symbol, _order_id), quantity in tracked_short_position_quantities_by_open_order(
        rows,
        account_state,
    ).items():
        key = (bucket, runtime_id, symbol)
        aggregate[key] = aggregate.get(key, ZERO) + quantity
    return aggregate


def confirmed_short_cover_structure_lows(
    rows: list[dict[str, Any]],
    account_state: dict[str, Any],
) -> dict[tuple[str, str, str], Decimal]:
    order_by_id = latest_account_orders_by_id(account_state)
    lows: dict[tuple[str, str, str], Decimal] = {}
    for row in rows:
        if row.get("submission_status") != "submitted":
            continue
        position_action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        side = normalize_side(row.get("side"), position_action=position_action)
        if not is_close_short(side, position_action):
            continue
        order_id = ledger_row_order_id(row)
        if not order_has_confirmed_fill(broker_order_for_ledger_row(row, order_by_id)):
            continue
        key = (
            str(row.get("capital_bucket") or ""),
            str(row.get("runtime_id") or ""),
            base_symbol(str(row.get("symbol") or "")),
        )
        structure_low = decimal(row.get("short_structure_low", "0"))
        if all(key) and structure_low > ZERO:
            lows[key] = structure_low
    return lows


def processed_signal_ids(rows: list[dict[str, Any]], config: RealtimeExecutionConfig) -> set[str]:
    processed: set[str] = set()
    for row in rows:
        signal_id = str(row.get("signal_id") or "")
        if not signal_id:
            continue
        if row_is_permanently_processed(row, config):
            processed.add(signal_id)
    return processed


def row_is_permanently_processed(row: dict[str, Any], config: RealtimeExecutionConfig) -> bool:
    submission_status = str(row.get("submission_status") or "")
    if submission_status == "submit_failed":
        return False
    if submission_status == "dry_run_ready_not_submitted":
        previous_execute_orders = bool(row.get("execute_orders"))
        if config.execute_orders and not previous_execute_orders:
            return False
        return True
    return bool(row.get("processed_at") or row.get("submitted_at") or submission_status)


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
    if position_action == "close_short":
        return "buy"
    if position_action == "open_short":
        return "sell_short"
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
    if text in {"open_short", "sell_short", "short", "开空", "做空"}:
        return "open_short"
    if text in {"close_short", "buy_to_cover", "cover_short", "平空", "回补"}:
        return "close_short"
    return text


def is_open_long(side: str, position_action: str) -> bool:
    return side == "buy" and position_action != "close_short"


def is_close_long(side: str, position_action: str) -> bool:
    return side == "sell" and position_action in {"close_long", "exit_long", "stop_loss", "take_profit"}


def is_open_short(side: str, position_action: str) -> bool:
    return side == "sell_short" or (side == "sell" and position_action == "open_short")


def is_close_short(side: str, position_action: str) -> bool:
    return side == "buy" and position_action == "close_short"


def ledger_row_opens_position(row: dict[str, Any]) -> bool:
    position_action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
    side = normalize_side(row.get("side"), position_action=position_action)
    return is_open_long(side, position_action) or is_open_short(side, position_action)


def ledger_row_closes_position(row: dict[str, Any]) -> bool:
    position_action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
    side = normalize_side(row.get("side"), position_action=position_action)
    return is_close_long(side, position_action) or is_close_short(side, position_action)


def ledger_row_closes_short(row: dict[str, Any]) -> bool:
    position_action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
    side = normalize_side(row.get("side"), position_action=position_action)
    return is_close_short(side, position_action)


def normalize_order_type(value: Any) -> str:
    text = str(value or "limit").strip().lower().replace("-", "_")
    if text in {"stop_limit", "trigger_limit", "breakout_limit", "triggered_limit"}:
        return "trigger_limit"
    if text in {"market", "market_order"}:
        return "market"
    if text in {"limit", "limit_order"}:
        return "limit"
    return text


def stable_client_request_id(
    *,
    signal_id: str,
    runtime_id: str,
    symbol: str,
    side: str,
    position_action: str,
    test_epoch_id: str,
) -> str:
    seed = "|".join(
        [
            signal_id.strip(),
            runtime_id.strip(),
            symbol.strip().upper(),
            side.strip().lower(),
            position_action.strip().lower(),
            test_epoch_id.strip(),
        ]
    )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]
    return f"m15rt-{digest}"


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
        return "长桥单策略仓新测试正在等待清空旧持仓；多头卖出和空头回补成交确认前，单策略仓和统一实验仓不会接收新的开仓信号。"
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


def fallback_quote_age_ms(signal: dict[str, Any], generated_at: datetime) -> int:
    explicit = signal.get("fallback_quote_age_ms")
    if explicit not in (None, ""):
        return max(-1, int_decimal(explicit))
    for key in ("market_event_time", "quote_time", "current_price_time", "source_event_at", "created_at"):
        quote_time = parse_signal_time(signal.get(key))
        if quote_time is not None:
            return max(0, int((generated_at - quote_time).total_seconds() * 1000))
    return -1


def should_retry_market_exit_as_marketable_limit(
    row: dict[str, Any],
    submission: dict[str, Any],
    order_payload: dict[str, Any],
) -> bool:
    if not row.get("exit_only_position_signal"):
        return False
    if str(order_payload.get("order_type") or "") != "market":
        return False
    if row.get("fallback_attempted"):
        return False
    if str(submission.get("order_id") or "").strip():
        return False
    if not bool(submission.get("explicit_reject")):
        return False
    if decimal(order_payload.get("current_price", "0")) <= ZERO:
        return False
    quote_age_ms = int_decimal(order_payload.get("fallback_quote_age_ms", row.get("fallback_quote_age_ms", -1)))
    if quote_age_ms < 0 or quote_age_ms > FRESH_FALLBACK_QUOTE_MAX_AGE_MS:
        return False
    return True


def marketable_limit_fallback_payload(order_payload: dict[str, Any]) -> dict[str, Any]:
    side = str(order_payload.get("side") or "").lower()
    current_price = decimal(order_payload.get("current_price", order_payload.get("fallback_quote_price", "0")))
    if current_price <= ZERO:
        return dict(order_payload)
    multiplier = FLATTEN_CURRENT_PRICE_BUY_LIMIT_MULTIPLIER if side == "buy" else FLATTEN_CURRENT_PRICE_SELL_LIMIT_MULTIPLIER
    fallback = dict(order_payload)
    fallback["order_type"] = "limit"
    fallback["limit_price"] = fmt_money(current_price * multiplier)
    fallback.pop("trigger_price", None)
    return fallback


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
            "- 不做真正碎股、期权或真实资金；做空仅限三条受限纸面短仓，且必须按原开空订单号回补。",
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


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(json_ready(row), ensure_ascii=False, sort_keys=True) + "\n")


def compact_execution_ledger_if_needed(
    path: Path,
    *,
    current_epoch_id: str,
    additional_current_epoch_ids: set[str] | None = None,
    max_bytes: int = MAX_EXECUTION_LEDGER_BYTES,
) -> dict[str, Any]:
    if max_bytes <= 0 or not path.exists():
        return {"compacted": False, "reason": "missing_or_disabled"}
    before_bytes = path.stat().st_size
    if before_bytes <= max_bytes:
        return {"compacted": False, "reason": "below_threshold", "bytes": before_bytes}

    current_epoch_ids = {current_epoch_id} if current_epoch_id else set()
    current_epoch_ids.update(item for item in (additional_current_epoch_ids or set()) if item)
    retained_lines: list[str] = []
    archived_lines: list[str] = []
    malformed_lines: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines.append(line)
            continue
        if str(row.get("test_epoch_id") or "") in current_epoch_ids:
            retained_lines.append(line)
        else:
            archived_lines.append(line)

    if not archived_lines and not malformed_lines:
        return {
            "compacted": False,
            "reason": "threshold_exceeded_but_all_rows_current_epoch",
            "bytes": before_bytes,
            "current_epoch_ids": sorted(current_epoch_ids),
            "retained_rows": len(retained_lines),
        }

    archive_dir = path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = archive_dir / f"{path.stem}.{timestamp}.archived.jsonl.gz"
    archived_payload = "\n".join(archived_lines + malformed_lines)
    write_gzip_text_atomic(archive_path, archived_payload + ("\n" if archived_payload else ""))
    write_text_atomic(path, "\n".join(retained_lines) + ("\n" if retained_lines else ""))
    after_bytes = path.stat().st_size if path.exists() else 0
    return {
        "compacted": True,
        "reason": "archived_non_current_epoch_rows",
        "current_epoch_ids": sorted(current_epoch_ids),
        "before_bytes": before_bytes,
        "after_bytes": after_bytes,
        "archived_rows": len(archived_lines),
        "malformed_archived_rows": len(malformed_lines),
        "retained_rows": len(retained_lines),
        "archive_path": project_path(archive_path),
    }


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def write_gzip_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with gzip.open(tmp_path, "wt", encoding="utf-8") as handle:
        handle.write(text)
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


def response_order_id(response: Any) -> str:
    """Extract a broker order id without a hot-path account-history scan."""
    if isinstance(response, dict):
        for key in ("order_id", "orderId", "id"):
            value = str(response.get(key) or "").strip()
            if value:
                return value
        for key in ("data", "result", "order"):
            nested = response.get(key)
            order_id = response_order_id(nested)
            if order_id:
                return order_id
        # Longbridge CLI occasionally emits table rows even with --format json.
        # Accept only the explicit Order ID row, never an arbitrary display value.
        field = " ".join(str(response.get("field") or "").lower().replace("_", " ").split())
        if field in {"order id", "order_id", "orderid"}:
            value = str(response.get("value") or "").strip()
            if value:
                return value
    if isinstance(response, list):
        for item in response:
            order_id = response_order_id(item)
            if order_id:
                return order_id
    return ""


def response_max_sell_quantity(response: Any) -> Decimal:
    if isinstance(response, dict):
        for key in ("cash_max_qty", "short_max_qty", "sell_max_qty", "max_sell_quantity", "max_qty"):
            quantity = decimal(response.get(key, "0"))
            if quantity > ZERO:
                return quantity
        # `longbridge max-qty --format json` currently returns CLI table rows
        # such as {"field": "Cash Max Qty", "value": "903"}, rather than a
        # keyed API object. Only consume explicitly cash/short sell capacity;
        # margin capacity stays excluded because margin financing is disabled.
        field = str(response.get("field") or "").strip().lower().replace("_", " ")
        field = " ".join(field.split())
        if field in {
            "cash max qty",
            "cash max quantity",
            "short max qty",
            "short max quantity",
            "sell max qty",
            "sell max quantity",
            "max sell quantity",
        }:
            quantity = decimal(response.get("value", "0"))
            if quantity > ZERO:
                return quantity
        for key in ("data", "result", "max_quantity"):
            quantity = response_max_sell_quantity(response.get(key))
            if quantity > ZERO:
                return quantity
    if isinstance(response, list):
        for item in response:
            quantity = response_max_sell_quantity(item)
            if quantity > ZERO:
                return quantity
    return ZERO


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


def config_digest(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_execution_run_id(config: RealtimeExecutionConfig, now: datetime) -> str:
    return f"{to_iso(now)}|cfg={config.config_digest[:12]}|mono={monotonic_ms()}"


def build_session_run_id(config: RealtimeExecutionConfig, session_started_at: str) -> str:
    return f"{session_started_at}|cfg={config.config_digest[:12]}"


def recent_execution_inputs(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    recent_rows = rows[-limit:]
    return [
        {
            "signal_id": str(row.get("signal_id") or ""),
            "runtime_id": str(row.get("runtime_id") or ""),
            "symbol": str(row.get("symbol") or ""),
            "side": str(row.get("side") or ""),
            "position_action": str(row.get("position_action") or ""),
            "created_at": str(row.get("created_at") or ""),
            "processed_at": str(row.get("processed_at") or ""),
            "exit_only_position_signal": bool(row.get("exit_only_position_signal")),
            "source_market_event_id": str(row.get("source_market_event_id") or ""),
        }
        for row in recent_rows
    ]
