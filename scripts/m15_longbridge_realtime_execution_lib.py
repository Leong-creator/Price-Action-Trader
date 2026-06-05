#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
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
SUMMARY_JSON = "m15_longbridge_realtime_execution.json"
LEDGER_JSONL = "m15_longbridge_realtime_execution_ledger.jsonl"
REPORT_MD = "m15_longbridge_realtime_execution.md"
MONEY = Decimal("0.01")
ZERO = Decimal("0")
OPTION_SYMBOL_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")
NEW_YORK = ZoneInfo("America/New_York")

DEFAULT_REALTIME_RUNTIME_IDS = (
    "M10-PA-004-long-1d",
    "M10-PA-013-1d",
    "M10-PA-001-1d",
    "M10-PA-001-5m",
    "M10-PA-002-1d",
    "M10-PA-005-1d",
    "M10-PA-005-5m",
    "M10-PA-008-1d",
    "M10-PA-012-5m",
    "M10-PA-013-5m",
    "M12-FTD-001-baseline-1d",
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
    "M10-PA-002-5m",
    "M10-PA-007-1d",
    "M10-PA-009-1d",
    "M10-PA-011-5m",
    "M10-PA-011-ORB-R1-5m",
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
        return {
            "submitted": True,
            "status": "submitted",
            "order_id": str(response.get("order_id", response.get("id", ""))) if isinstance(response, dict) else "",
            "response": response,
            "command": redact_command(command),
        }


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
        minimum_net_profit_after_fees=decimal(account_model.get("minimum_net_profit_after_fees", "0")),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


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
    if not config.allowed_runtime_ids:
        raise ValueError("M15 realtime execution needs a runtime whitelist")
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
    signal_events = read_jsonl(config.realtime_signal_events_path)
    existing_ledger = read_jsonl(config.output_dir / LEDGER_JSONL)
    existing_submitted_ids = {
        str(row.get("signal_id"))
        for row in existing_ledger
        if row.get("signal_id") and row.get("submission_status") == "submitted"
    }
    existing_submitted_exposure = submitted_ledger_open_exposure(existing_ledger, session_started_at, account_state)
    broker_client = broker_client or (
        LongbridgeCliRealtimePaperClient(config) if config.execute_orders else NullRealtimePaperClient()
    )

    ledger_rows: list[dict[str, Any]] = []
    selected_total_exposure = ZERO
    selected_symbol_exposure: dict[str, Decimal] = {}
    submitted_count = 0
    ready_count = 0
    blocked_count = 0
    delayed_count = 0
    target_met_count = 0
    acceptable_count = 0
    submitted_signal_ids = set(existing_submitted_ids)

    for event in signal_events:
        decision = evaluate_signal_event(
            config=config,
            signal=event,
            account_state=account_state,
            generated_at=now,
            session_started_at=session_started_at,
            submitted_signal_ids=submitted_signal_ids,
            existing_submitted_exposure=existing_submitted_exposure,
            selected_total_exposure=selected_total_exposure,
            selected_symbol_exposure=selected_symbol_exposure,
        )
        row = decision["ledger_row"]
        if decision["ready"]:
            ready_count += 1
            order_payload = decision["order_payload"]
            if config.execute_orders:
                submission = broker_client.submit_order(order_payload)
                row["submission_response"] = submission
                if submission.get("submitted") or submission.get("order_id"):
                    row["submission_status"] = "submitted"
                    row["submitted_at"] = generated_at_iso
                    submitted_count += 1
                    submitted_signal_ids.add(str(row["signal_id"]))
                else:
                    row["submission_status"] = str(submission.get("status", "submit_failed"))
            else:
                row["submission_status"] = "dry_run_ready_not_submitted"
            if row.get("side") == "buy":
                symbol = str(row["symbol"])
                notional = decimal(row.get("notional", "0"))
                selected_total_exposure += notional
                selected_symbol_exposure[symbol] = selected_symbol_exposure.get(symbol, ZERO) + notional
        else:
            blocked_count += 1
            row["submission_status"] = "blocked_not_submitted"
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
        "latency_target_ms": config.latency_target_ms,
        "latency_acceptable_ms": config.latency_acceptable_ms,
        "max_delayed_signal_age_seconds": config.max_delayed_signal_age_seconds,
        "latency_counts": {
            "target_met": target_met_count,
            "acceptable": acceptable_count,
            "delayed_revalidated": delayed_count,
        },
        "signal_event_count": len(signal_events),
        "ready_order_count": ready_count,
        "blocked_signal_count": blocked_count,
        "submitted_count": submitted_count,
        "delayed_signal_age_blocked_count": sum(
            1 for row in ledger_rows if "blocked_delayed_signal_age_over_limit" in row.get("blockers", [])
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
            "local_simulation_ledger": "",
            "fast_signal_queue": "",
        },
        "outputs": {
            "summary": project_path(config.output_dir / SUMMARY_JSON),
            "ledger": project_path(config.output_dir / LEDGER_JSONL),
            "report": project_path(config.output_dir / REPORT_MD),
        },
        "plain_language_result": plain_language_result(ready_count, blocked_count, submitted_count, config.execute_orders),
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
    generated_at: datetime,
    session_started_at: str,
    submitted_signal_ids: set[str],
    existing_submitted_exposure: dict[str, Decimal],
    selected_total_exposure: Decimal,
    selected_symbol_exposure: dict[str, Decimal],
) -> dict[str, Any]:
    signal_id = str(signal.get("signal_id") or "")
    runtime_id = str(signal.get("runtime_id") or "")
    strategy_id = str(signal.get("strategy_id") or parent_strategy_id(runtime_id))
    symbol = str(signal.get("symbol") or "").upper()
    order_type = normalize_order_type(signal.get("order_type"))
    position_action = normalize_position_action(signal.get("position_action") or signal.get("event_type") or signal.get("action"))
    side = normalize_side(signal.get("side") or signal.get("direction"), position_action=position_action)
    quantity = decimal(signal.get("quantity", signal.get("suggested_quantity", "0")))
    limit_price = decimal(signal.get("limit_price", signal.get("entry_price", "0")))
    trigger_price = decimal(signal.get("trigger_price", "0"))
    stop_price = decimal(signal.get("stop_price", "0"))
    target_price = decimal(signal.get("target_price", "0"))
    current_price = decimal(signal.get("current_price", signal.get("last_price", limit_price)))
    risk_amount = decimal(signal.get("risk_amount", "0"))
    notional = decimal(signal.get("notional", quantity * limit_price))
    net_profit = decimal(
        signal.get(
            "net_profit_after_fees_at_target",
            signal.get("expected_net_profit_after_fees", signal.get("net_profit_after_fees", "0")),
        )
    )
    created_at = parse_signal_time(signal.get("created_at") or signal.get("generated_at") or signal.get("signal_time"))
    latency_ms = latency_millis(created_at, generated_at) if created_at else None
    latency_band = latency_band_for(config, latency_ms)
    signal_expires_at = parse_signal_time(
        signal.get("expires_at") or signal.get("valid_until") or signal.get("signal_expires_at")
    )
    age_limit_seconds, age_limit_source = signal_age_limit(config, signal, created_at, signal_expires_at)
    blockers: list[str] = []

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
    blockers.extend(strategy_isolation_blockers(runtime_id, strategy_id, config.allowed_runtime_ids))
    held_quantities = held_symbol_quantities(account_state)
    open_order_symbols = open_order_symbol_set(account_state)
    account_symbol_exposure_map = account_symbol_exposure(account_state)
    existing_total_exposure = account_total_exposure(account_state)
    submitted_total_exposure = sum(existing_submitted_exposure.values(), ZERO)
    if side == "sell_short":
        blockers.append("blocked_short_disabled")
    elif side == "sell":
        if position_action not in {"close_long", "exit_long", "stop_loss", "take_profit"}:
            blockers.append("blocked_short_disabled")
        elif held_quantities.get(symbol, ZERO) <= ZERO:
            blockers.append("blocked_close_without_long_position")
        elif quantity > held_quantities.get(symbol, ZERO):
            blockers.append("blocked_close_quantity_over_position")
    elif side != "buy":
        blockers.append("blocked_unknown_side")
    if side == "buy":
        if held_quantities.get(symbol, ZERO) > ZERO:
            blockers.append("blocked_existing_position_same_symbol")
        if symbol in open_order_symbols:
            blockers.append("blocked_existing_open_order_same_symbol")
        if existing_submitted_exposure.get(symbol, ZERO) > ZERO:
            blockers.append("blocked_existing_submitted_order_same_symbol")
        if selected_symbol_exposure.get(symbol, ZERO) > ZERO:
            blockers.append("blocked_existing_selected_order_same_symbol")
    if OPTION_SYMBOL_RE.match(symbol):
        blockers.append("blocked_options_disabled")
    if order_type not in {"limit", "trigger_limit"}:
        blockers.append("blocked_order_type")
    if order_type == "trigger_limit" and trigger_price <= ZERO:
        blockers.append("missing_trigger_price")
    if quantity <= ZERO:
        blockers.append("blocked_non_positive_quantity")
    if not config.allow_fractional_shares and quantity != quantity.to_integral_value():
        blockers.append("blocked_fractional_disabled")
    if limit_price <= ZERO:
        blockers.append("missing_limit_price")
    if side == "buy" and (stop_price <= ZERO or target_price <= ZERO):
        blockers.append("missing_stop_or_target")
    if side == "buy" and current_price > ZERO:
        if stop_price >= current_price:
            blockers.append("blocked_invalid_stop_vs_current_price")
        if target_price <= current_price:
            blockers.append("blocked_invalid_target_vs_current_price")
    if side == "buy" and risk_amount > config.max_risk_per_order:
        blockers.append("blocked_risk_over_cap")
    if side == "buy" and notional > config.max_symbol_exposure:
        blockers.append("blocked_symbol_exposure_over_cap")
    if side == "buy" and (
        account_symbol_exposure_map.get(symbol, ZERO)
        + existing_submitted_exposure.get(symbol, ZERO)
        + selected_symbol_exposure.get(symbol, ZERO)
        + notional
        > config.max_symbol_exposure
    ):
        blockers.append("blocked_symbol_exposure_over_cap")
    if side == "buy" and existing_total_exposure + submitted_total_exposure + selected_total_exposure + notional > config.max_total_exposure:
        blockers.append("blocked_total_exposure_over_cap")
    if side == "buy" and available_cash(account_state) - notional < config.min_cash_reserve:
        blockers.append("blocked_cash_reserve")
    if side == "buy" and net_profit <= config.minimum_net_profit_after_fees:
        blockers.append("blocked_fee_profit_not_positive")
    if signal_expires_at and generated_at > signal_expires_at:
        blockers.append("blocked_realtime_signal_expired")
    if latency_ms is not None and latency_ms > config.latency_acceptable_ms:
        if age_limit_seconds > 0 and latency_ms > age_limit_seconds * 1000:
            blockers.append("blocked_delayed_signal_age_over_limit")
        if current_price <= ZERO or limit_price <= ZERO:
            blockers.append("blocked_delayed_signal_missing_revalidation_price")

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
    ledger_row = {
        "stage": config.stage,
        "signal_id": signal_id,
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "timeframe": str(signal.get("timeframe") or ""),
        "direction": str(signal.get("direction") or ""),
        "position_action": position_action,
        "side": side,
        "order_type": order_type,
        "quantity": fmt_decimal(quantity),
        "limit_price": fmt_money(limit_price),
        "trigger_price": fmt_money(trigger_price) if trigger_price > ZERO else "",
        "stop_price": fmt_money(stop_price) if stop_price > ZERO else "",
        "target_price": fmt_money(target_price) if target_price > ZERO else "",
        "current_price": fmt_money(current_price) if current_price > ZERO else "",
        "risk_amount": fmt_money(risk_amount),
        "notional": fmt_money(notional),
        "net_profit_after_fees_at_target": fmt_money(net_profit),
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
    if any(marker in lowered for marker in SHADOW_RUNTIME_MARKERS) or "-mbf" in lowered:
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


def open_order_symbol_set(account_state: dict[str, Any]) -> set[str]:
    symbols: set[str] = set()
    orders = account_state.get("open_orders")
    if not isinstance(orders, list):
        orders = []
    for row in orders:
        if isinstance(row, dict) and row.get("symbol"):
            symbols.add(base_symbol(str(row.get("symbol"))))
    return symbols


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


def plain_language_result(ready_count: int, blocked_count: int, submitted_count: int, execute_orders: bool) -> str:
    if submitted_count:
        return f"长桥实时链路已提交 {submitted_count} 笔模拟订单；本地模拟没有参与下单判断。"
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
        f"- 实时信号数 / 通过数 / 阻断数 / 已提交数: `{summary['signal_event_count']} / {summary['ready_order_count']} / {summary['blocked_signal_count']} / {summary['submitted_count']}`",
        f"- 延迟目标: `{summary['latency_target_ms']}ms`，第一版可接受: `{summary['latency_acceptable_ms']}ms`",
        f"- 延迟信号最大年龄: `{summary['max_delayed_signal_age_seconds']}s`",
        f"- 结论: {summary['plain_language_result']}",
        "",
        "## 最近实时信号",
        "",
        "| 信号 | 运行单元 | 标的 | 状态 | 延迟 | 数量 | 限价 | 原因 |",
        "|---|---|---:|---|---:|---:|---:|---|",
    ]
    for row in rows[:30]:
        blockers = ",".join(str(item) for item in row.get("blockers", []))
        lines.append(
            "| "
            f"`{row.get('signal_id', '')}` | `{row.get('runtime_id', '')}` | `{row.get('symbol', '')}` | "
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
