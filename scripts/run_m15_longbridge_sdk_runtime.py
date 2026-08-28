#!/usr/bin/env python3
"""Persistent M15 Longbridge paper runtime using official SDK contexts only."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import multiprocessing as mp
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_PYTHON.parent.parent.resolve():
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]], os.environ)

from scripts.m15_longbridge_sdk_account_lib import (
    SdkAccountProcessCoordinator,
    SdkAccountStateProvider,
    SdkTradeRequestGate,
)
from scripts.m15_deployment_governance_lib import verify_manifest
from scripts.m15_longbridge_sdk_runtime_lib import (
    DEFAULT_CONFIG_PATH, MarketEventContext, SdkRealtimePaperClient,
    append_market_events, attach_next_bar_first_quotes, build_status, compact_market_events, config_fingerprint, configured_symbols,
    configured_trading_symbols, daily_candlestick_event_rows,
    daily_context_covers_symbols, daily_context_is_complete,
    daily_context_row_count_for_symbols, fresh_market_events, load_config,
    held_position_monitoring_symbols, new_held_position_monitoring_symbols,
    read_client_id,
    load_current_sdk_intraday_context, load_formal_test_marker, readonly_gate_passed, record_readonly_session,
    market_event_is_tradable, trading_market_events,
    sdk_config_from_oauth, sdk_order_maintenance_actions, summarize_latency_samples, write_daily_context_cache,
    to_iso,
    unix_to_utc,
    validate_market_data_transport_runtime,
)
from scripts.m15_longbridge_sdk_quote_transport_lib import official_sdk_quote_worker
from scripts.m15_sdk_validation_flatten_lib import (
    activate_formal_epoch_payload,
    build_flatten_plan,
    flatten_confirmation,
    latest_flatten_prices,
    runtime_flatten_order_payload,
)

NEW_YORK = ZoneInfo("America/New_York")
PID_FILE = "m15_longbridge_sdk_runtime.pid"
LOG_FILE = "m15_longbridge_sdk_runtime.log"
START_LOCK_FILE = "m15_longbridge_sdk_runtime.start.lock"
RUN_LOCK_FILE = "m15_longbridge_sdk_runtime.run.lock"
GLOBAL_RUNTIME_STATE_DIR = (
    Path.home() / ".cache" / "price-action-trader"
)
GLOBAL_QUOTE_SUBSCRIPTION_LOCK = (
    GLOBAL_RUNTIME_STATE_DIR / "m15_sdk_quote_subscription.lock"
)
GLOBAL_RUNTIME_START_LOCK = (
    GLOBAL_RUNTIME_STATE_DIR / "m15_sdk_runtime.start.lock"
)
EXECUTION_LEDGER_FILE = "m15_longbridge_realtime_execution_ledger.jsonl"
ORDER_MAINTENANCE_FILE = "m15_sdk_order_maintenance.json"
AUTHORIZED_ACCOUNT_EXIT_FILE = "m15_authorized_account_exit.json"
CAPITAL_BUCKET_MIGRATION_FILE = "m15_capital_bucket_migration_state.json"
TRADE_CONTEXT_HEALTHCHECK_INTERVAL_SECONDS = 60
TRADE_CONTEXT_RETRY_SECONDS = 5


def parse_utc_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the persistent Longbridge SDK paper runtime.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--check", action="store_true", help="Check SDK/OAuth interfaces without connecting.")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--dispatch", action="store_true", help="Request paper dispatch after the readonly gate passes.")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--stop", action="store_true")
    return parser.parse_args()


def require_sdk_contract() -> Any:
    import longbridge.openapi as lb
    missing = [name for name in ("QuoteContext", "TradeContext", "PortfolioContext") if not getattr(lb, name, None)]
    if missing:
        raise RuntimeError(f"sdk_contract_missing:{','.join(missing)}")
    return lb


def build_sdk_account_provider_for_worker(config_path: str) -> SdkAccountStateProvider:
    """Construct account-only SDK contexts inside the spawned worker."""
    config = load_config(config_path)
    sdk = require_sdk_contract()
    oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
    return SdkAccountStateProvider(
        sdk.TradeContext(sdk_config_from_oauth(sdk, oauth, config.trade_region)),
        sdk.PortfolioContext(sdk_config_from_oauth(sdk, oauth, config.trade_region)),
        request_gate=SdkTradeRequestGate(),
        include_portfolio_analytics=False,
    )


def build_sdk_trade_clients(
    config: Any,
    sdk: Any,
    request_gate: SdkTradeRequestGate,
    on_submission: Any,
    *,
    dispatch_enabled: bool,
) -> tuple[Any, SdkRealtimePaperClient | None, SdkRealtimePaperClient]:
    oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
    trade_context = sdk.TradeContext(
        sdk_config_from_oauth(sdk, oauth, config.trade_region)
    )
    paper_client = (
        SdkRealtimePaperClient(
            trade_context,
            sdk,
            request_gate=request_gate,
            on_submission=on_submission,
        )
        if dispatch_enabled
        else None
    )
    flatten_client = SdkRealtimePaperClient(
        trade_context,
        sdk,
        request_gate=request_gate,
        on_submission=on_submission,
    )
    return trade_context, paper_client, flatten_client


def runtime_owns_quote_connection(config: Any, runtime_status: dict[str, Any]) -> bool:
    """Treat a connecting live runtime as the sole owner of the quote channel."""
    return bool(
        str(runtime_status.get("config_fingerprint") or "")
        == config_fingerprint(config)
        and process_alive(int(runtime_status.get("runtime_pid") or 0))
    )


def effective_runtime_dispatch_enabled(
    *,
    dispatch_requested: bool,
    paper_client_ready: bool,
    trade_context_ready: bool,
    market_data_ready: bool,
    trading_daily_context_ready: bool,
    flatten_blocks_new_entries: bool,
    account_snapshot_ready: bool,
    deployment_ready: bool = True,
    position_monitoring_ready: bool = True,
) -> bool:
    return bool(
        dispatch_requested
        and paper_client_ready
        and trade_context_ready
        and market_data_ready
        and trading_daily_context_ready
        and not flatten_blocks_new_entries
        and account_snapshot_ready
        and deployment_ready
        and position_monitoring_ready
    )


def runtime_dispatch_block_reason(
    *,
    paper_order_dispatch_enabled: bool,
    complete_session_gate_blocked: bool,
    paper_client_ready: bool,
    trade_context_ready: bool,
    market_data_ready: bool,
    flatten_blocks_new_entries: bool,
    account_snapshot_ready: bool,
    trading_daily_context_ready: bool,
    deployment_ready: bool = True,
    position_monitoring_ready: bool = True,
    reference_market_data_stale: bool = False,
) -> str:
    if not paper_order_dispatch_enabled:
        return "paper_order_dispatch_disabled"
    if complete_session_gate_blocked:
        return "complete_market_session_gate"
    if not deployment_ready:
        return "deployment_manifest_invalid"
    if not position_monitoring_ready:
        return "position_monitoring_incomplete"
    if reference_market_data_stale:
        return "reference_market_data_stale"
    if not paper_client_ready or not trade_context_ready:
        return "trade_context_unavailable"
    if not market_data_ready:
        return "market_data_fault_halted"
    if flatten_blocks_new_entries:
        return "pending_account_flatten"
    if not account_snapshot_ready:
        return "account_snapshot_unavailable"
    if not trading_daily_context_ready:
        return "trading_daily_context_incomplete"
    return ""


def trade_context_health_requires_rebuild(health: dict[str, Any]) -> bool:
    return bool(
        health.get("trade_context_refresh_required")
        or str(health.get("status") or "") == "trade_context_missing"
    )


def run_market_data_preflight(
    config: Any,
) -> dict[str, Any]:
    """Inspect the sole runtime; never create a diagnostic quote connection."""
    quote_error = ""
    quote_probe_source = ""
    probe_details: dict[str, Any] = {}
    try:
        runtime_status = json.loads(config.runtime_status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        runtime_status = {}
    quote_connection_owned = runtime_owns_quote_connection(config, runtime_status)
    if quote_connection_owned:
        quote_probe_source = "active_runtime_status"
        expected_mode = configured_market_data_mode(config)
        if (
            runtime_status.get("sdk_connected") is not True
            or runtime_status.get("market_data_transport")
            != config.market_data_transport
            or runtime_status.get("market_data_mode") != expected_mode
        ):
            quote_error = "active_market_data_runtime_not_ready"
        probe_details = {
            "market_data_mode": str(runtime_status.get("market_data_mode") or ""),
            "subscription_coverage": str(
                runtime_status.get("subscription_coverage") or ""
            ),
        }
    else:
        quote_probe_source = "deferred_to_single_runtime"
        probe_details = {
            "market_data_mode": configured_market_data_mode(config),
            "runtime_started": False,
            "direct_probe_forbidden": True,
        }
    return {
        "quote_ok": bool(quote_connection_owned and not quote_error),
        "quote_runtime_verified": bool(quote_connection_owned and not quote_error),
        "quote_probe_source": quote_probe_source,
        "quote_error": quote_error,
        "market_data_transport": config.market_data_transport,
        "market_data_probe": probe_details,
    }


def run_sdk_preflight(config: Any) -> dict[str, Any]:
    """Verify every read-only transport and SDK endpoint without sending an order."""
    sdk = require_sdk_contract()
    oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
    trade = sdk.TradeContext(sdk_config_from_oauth(sdk, oauth, config.trade_region))
    portfolio = sdk.PortfolioContext(sdk_config_from_oauth(sdk, oauth, config.trade_region))
    provider = SdkAccountStateProvider(trade, portfolio, request_gate=SdkTradeRequestGate())
    account = provider.refresh()
    market_data = run_market_data_preflight(config)
    errors = list(account.get("errors") or [])
    if market_data["quote_error"]:
        errors.append(market_data["quote_error"])
    short_capacity_error = ""
    short_capacity = "0"
    short_capacity_cash = "0"
    short_capacity_margin = "0"
    short_capacity_probe_symbol = configured_symbols(config)[0]
    try:
        response = trade.estimate_max_purchase_quantity(
            short_capacity_probe_symbol,
            sdk.OrderType.LO,
            sdk.OrderSide.Sell,
            price=Decimal("1"),
        )
        short_capacity_cash = str(getattr(response, "cash_max_qty", "0"))
        short_capacity_margin = str(getattr(response, "margin_max_qty", "0"))
        short_capacity = short_capacity_margin
    except Exception as exc:
        short_capacity_error = f"sdk_short_capacity_probe_failed:{type(exc).__name__}:{exc}"
        errors.append(short_capacity_error)
    return {
        "quote_ok": market_data["quote_ok"],
        "quote_runtime_verified": market_data["quote_runtime_verified"],
        "quote_probe_source": market_data["quote_probe_source"],
        "market_data_transport": market_data["market_data_transport"],
        "market_data_probe": market_data["market_data_probe"],
        "assets_ok": bool(account.get("assets_ok")),
        "positions_ok": bool(account.get("positions_ok")),
        "orders_ok": bool(account.get("orders_ok")),
        "executions_ok": bool(account.get("executions_ok")),
        "portfolio_ok": bool(account.get("portfolio_ok")),
        "paper_account_verified": bool(account.get("paper_account_verified")),
        "account_channel": str(account.get("account_channel") or ""),
        "position_row_count": int(account.get("position_row_count", 0) or 0),
        "order_row_count": int(account.get("order_row_count", 0) or 0),
        "short_capacity_endpoint_ok": not short_capacity_error,
        "short_capacity_probe_ok": not short_capacity_error,
        "short_capacity_probe_has_borrow_capacity": (
            not short_capacity_error and Decimal(short_capacity_margin) > 0
        ),
        "short_capacity_probe_symbol": short_capacity_probe_symbol,
        "short_capacity_probe_price_is_connectivity_only": True,
        "short_capacity_probe_quantity": short_capacity,
        "short_capacity_probe_cash_quantity": short_capacity_cash,
        "short_capacity_probe_margin_quantity": short_capacity_margin,
        "short_capacity_probe_basis": "margin_max_qty_for_sell_short",
        "errors": errors,
    }


def emit_worker(queue_out: Any, payload: dict[str, Any]) -> None:
    try:
        queue_out.put_nowait(payload)
    except queue.Full:
        # Bars are never replayed after a saturated queue: a later fresh event
        # is safer than an old order intent.
        return


def event_rows_to_daily(
    symbol: str,
    candles: Any,
    received_at: datetime,
) -> list[dict[str, Any]]:
    """Compatibility wrapper for the canonical raw-candlestick converter."""
    return daily_candlestick_event_rows(symbol, candles, received_at)


def update_live_quote_session_state(
    state_by_symbol: dict[str, dict[str, Any]],
    symbol: str,
    payload: dict[str, Any],
    *,
    received_at: datetime,
    source_mode: str,
) -> dict[str, Any] | None:
    normalized_symbol = str(symbol or "").upper().removesuffix(".US")
    if not normalized_symbol:
        return None
    source_at = unix_to_utc(payload.get("timestamp"), received_at)
    previous = state_by_symbol.get(normalized_symbol)
    blocked_reason = ""
    if previous is not None:
        try:
            previous_source_at = datetime.fromisoformat(
                str(previous.get("source_event_at") or "").replace("Z", "+00:00")
            ).astimezone(UTC)
        except ValueError:
            previous_source_at = None
        if previous_source_at is not None and source_at < previous_source_at:
            return previous
    open_price = str(payload.get("open") or "")
    high = str(payload.get("high") or "")
    low = str(payload.get("low") or "")
    close = str(payload.get("last_done") or payload.get("close") or "")
    raw_volume = payload.get("volume")
    if not blocked_reason and raw_volume in (None, ""):
        blocked_reason = "quote_total_volume_missing"
    volume = "0" if raw_volume in (None, "") else str(max(0, int(Decimal(str(raw_volume)))))
    if previous is not None and not blocked_reason:
        previous_volume = int(previous.get("volume") or 0)
        if int(volume) < previous_volume:
            blocked_reason = "quote_total_volume_regressed"
    values = [Decimal(value) for value in (open_price, high, low, close) if value not in {"", "None"}]
    if len(values) != 4 or min(values) <= 0:
        blocked_reason = blocked_reason or "quote_ohlc_missing"
    elif not (Decimal(low) <= Decimal(open_price) <= Decimal(high) and Decimal(low) <= Decimal(close) <= Decimal(high)):
        blocked_reason = blocked_reason or "quote_ohlc_invalid"
    state = {
        "symbol": normalized_symbol,
        "source_mode": source_mode,
        "source_event_at": to_iso(source_at),
        "received_at": to_iso(received_at),
        "session_date": source_at.astimezone(NEW_YORK).date().isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "market_data_blocked_reason": blocked_reason,
    }
    state_by_symbol[normalized_symbol] = state
    return state


def apply_quote_state_worker_message(
    message: dict[str, Any],
    *,
    live_quote_session_state: dict[str, dict[str, Any]],
    last_push_by_symbol: dict[str, float],
    last_push_at_by_symbol: dict[str, str],
    last_push_source_by_symbol: dict[str, str],
    first_live_push_by_symbol: dict[str, float],
    last_live_push_by_symbol: dict[str, float],
    now_monotonic: float | None = None,
) -> int:
    kind = str(message.get("kind") or "")
    quote_state_rows = (
        [message]
        if kind == "quote_state"
        else list(message.get("rows") or [])
    )
    applied = 0
    for quote_state in quote_state_rows:
        try:
            quote_received_at = datetime.fromisoformat(
                str(quote_state.get("received_at") or "").replace(
                    "Z", "+00:00"
                )
            ).astimezone(UTC)
        except (TypeError, ValueError):
            quote_received_at = datetime.now(UTC)
        update_live_quote_session_state(
            live_quote_session_state,
            str(quote_state.get("symbol") or ""),
            dict(quote_state.get("payload") or {}),
            received_at=quote_received_at,
            source_mode=str(
                quote_state.get("source_mode") or "official_sdk_push"
            ),
        )
        normalized_push_symbol = str(quote_state.get("symbol") or "").upper()
        if not normalized_push_symbol:
            continue
        push_monotonic = (
            time.monotonic() if now_monotonic is None else now_monotonic
        )
        last_push_by_symbol[normalized_push_symbol] = push_monotonic
        last_push_at_by_symbol[normalized_push_symbol] = to_iso(quote_received_at)
        push_source = str(
            quote_state.get("source_mode") or "official_sdk_push"
        )
        last_push_source_by_symbol[normalized_push_symbol] = push_source
        if (
            normalized_push_symbol in {"SPY.US", "QQQ.US"}
            and push_source
            not in {
                "official_sdk_initial_snapshot",
                "official_sdk_initial_snapshot",
            }
        ):
            first_live_push_by_symbol.setdefault(
                normalized_push_symbol, push_monotonic
            )
            last_live_push_by_symbol[normalized_push_symbol] = push_monotonic
        applied += 1
    return applied


def quote_subscription_targets(config: Any, now: datetime) -> tuple[str, ...]:
    """Return the immutable subscription set for this runtime instance."""
    if configured_regular_session(config, now):
        return configured_trading_symbols(config)
    return configured_symbols(config)


def configured_regular_session(config: Any, now: datetime) -> bool:
    """Use the production market calendar instead of a hidden fixed schedule."""
    local = now.astimezone(ZoneInfo(config.market_timezone))
    if local.weekday() >= 5 or local.date().isoformat() in config.market_holidays:
        return False
    start_hour, start_minute = (
        int(value) for value in config.regular_session_start_time.split(":", 1)
    )
    end_hour, end_minute = (
        int(value) for value in config.regular_session_end_time.split(":", 1)
    )
    start = local.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0,
    )
    end = local.replace(
        hour=end_hour,
        minute=end_minute,
        second=0,
        microsecond=0,
    )
    return start <= local < end


def detect_position_monitoring_set_change(
    config: Any,
    account_snapshot: dict[str, Any],
    monitored_symbols: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    additions = new_held_position_monitoring_symbols(
        config,
        account_snapshot,
        monitored_symbols,
    )
    if not additions:
        return monitored_symbols, (), ""
    updated = tuple(sorted(set(monitored_symbols) | set(additions)))
    reason = "position_monitoring_set_changed_diagnosis_required:" + ",".join(
        additions
    )
    return updated, additions, reason


def quote_subscription_ready(
    trading_market_data_failed: list[str],
    trading_subscription_failed: list[str],
    daily_failed: list[str],
) -> bool:
    return not any((
        trading_market_data_failed,
        trading_subscription_failed,
        daily_failed,
    ))


def market_data_mode_qualifies_for_subscription_gate(mode: str) -> bool:
    return str(mode) == "official_sdk_subscription"


def configured_market_data_mode(config: Any) -> str:
    if config.market_data_transport != "official_sdk_persistent_websocket":
        raise RuntimeError("M15 production market data must use the official SDK")
    return "official_sdk_subscription"


def configured_quote_worker(config: Any) -> Any:
    configured_market_data_mode(config)
    return official_sdk_quote_worker


def market_data_heartbeat_is_stale(
    last_progress_monotonic: float,
    now_monotonic: float,
    deadline_seconds: float,
) -> bool:
    return (
        float(now_monotonic) - float(last_progress_monotonic)
        > float(deadline_seconds)
    )


def market_data_heartbeat_grace_elapsed(
    worker_ready_since_monotonic: float,
    now_monotonic: float,
    grace_seconds: float,
) -> bool:
    return bool(
        float(worker_ready_since_monotonic) > 0
        and float(now_monotonic) - float(worker_ready_since_monotonic)
        > float(grace_seconds)
    )


def active_reference_quotes_are_stale(
    last_push_by_symbol: dict[str, float],
    *,
    now_monotonic: float,
    maximum_silence_seconds: float,
    reference_symbols: tuple[str, ...] = ("SPY.US", "QQQ.US"),
) -> bool:
    timestamps = [last_push_by_symbol.get(symbol, 0.0) for symbol in reference_symbols]
    return bool(
        timestamps
        and all(
            timestamp <= 0
            or now_monotonic - timestamp > maximum_silence_seconds
            for timestamp in timestamps
        )
    )


def regular_session_open_grace_elapsed(
    now: datetime,
    grace_seconds: float,
) -> bool:
    """Avoid treating the normal pre-open-to-open lull as a dead connection."""
    local = now.astimezone(NEW_YORK)
    session_open = local.replace(hour=9, minute=30, second=0, microsecond=0)
    return local >= session_open + timedelta(seconds=float(grace_seconds))


def apply_reference_market_activity_message(
    message: dict[str, Any],
    *,
    last_push_by_symbol: dict[str, float],
    last_push_at_by_symbol: dict[str, str],
    last_push_source_by_symbol: dict[str, str],
    first_live_push_by_symbol: dict[str, float],
    last_live_push_by_symbol: dict[str, float],
    now_monotonic: float | None = None,
) -> None:
    try:
        activity_received_at = datetime.fromisoformat(
            str(message.get("received_at") or "").replace("Z", "+00:00")
        ).astimezone(UTC)
    except ValueError:
        activity_received_at = datetime.now(UTC)
    normalized_symbol = str(message.get("symbol") or "").upper()
    activity_monotonic = (
        float(now_monotonic)
        if now_monotonic is not None
        else time.monotonic()
    )
    last_push_by_symbol[normalized_symbol] = activity_monotonic
    last_push_at_by_symbol[normalized_symbol] = to_iso(activity_received_at)
    last_push_source_by_symbol[normalized_symbol] = str(
        message.get("source_mode") or "official_sdk_trade_push"
    )
    if normalized_symbol in {"SPY.US", "QQQ.US"}:
        first_live_push_by_symbol.setdefault(
            normalized_symbol,
            activity_monotonic,
        )
        last_live_push_by_symbol[normalized_symbol] = activity_monotonic


def signals_allowed_by_entry_gate(
    entry_signals: list[dict[str, Any]],
    exit_signals: list[dict[str, Any]],
    *,
    new_entry_submission_enabled: bool,
) -> list[dict[str, Any]]:
    return (
        list(entry_signals) if new_entry_submission_enabled else []
    ) + list(exit_signals)


def process_resource_snapshot() -> dict[str, int]:
    try:
        file_descriptors = len(list(Path("/proc/self/fd").iterdir()))
    except OSError:
        file_descriptors = -1
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        memory_kib = int(
            next(line.split()[1] for line in status.splitlines() if line.startswith("VmRSS:"))
        )
    except (OSError, StopIteration, ValueError):
        memory_kib = -1
    return {
        "thread_count": threading.active_count(),
        "file_descriptor_count": file_descriptors,
        "resident_memory_kib": memory_kib,
    }


def realtime_boundary_is_complete(
    rows: list[dict[str, Any]],
    expected_symbols: list[str] | tuple[str, ...],
    *,
    maximum_finalization_seconds: float = 5,
) -> bool:
    expected = {symbol.upper().removesuffix(".US") for symbol in expected_symbols}
    if not expected or not rows:
        return False
    expected_rows = [
        row
        for row in rows
        if str(row.get("symbol") or "").upper().removesuffix(".US") in expected
    ]
    boundary_times = {str(row.get("event_time") or "") for row in expected_rows}
    actual = {
        str(row.get("symbol") or "").upper().removesuffix(".US")
        for row in expected_rows
    }
    if len(boundary_times) != 1 or actual != expected:
        return False
    for row in expected_rows:
        if row.get("bar_final") is not True:
            return False
        try:
            boundary = datetime.fromisoformat(str(row["event_time"]).replace("Z", "+00:00"))
            received = datetime.fromisoformat(str(row["received_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            return False
        if (received - boundary).total_seconds() > maximum_finalization_seconds:
            return False
    return True


def realtime_boundary_is_trustworthy(
    *,
    boundary_complete: bool,
    reference_quotes_fresh: bool,
) -> bool:
    """Require both full symbol coverage and live reference-market evidence."""
    return bool(boundary_complete and reference_quotes_fresh)


def realtime_boundary_integrity_state(
    *,
    boundary_complete: bool,
    reference_quotes_fresh: bool,
) -> str:
    if not boundary_complete:
        return "structurally_incomplete"
    if not reference_quotes_fresh:
        return "reference_quotes_stale"
    return "trustworthy"


def boundary_execution_client(
    *,
    candidate_client: Any,
    boundary_complete: bool,
    trustworthy_boundary: bool,
) -> Any:
    if boundary_complete and trustworthy_boundary:
        return candidate_client
    return None


def account_age_seconds(snapshot: dict[str, Any], *, now: datetime | None = None) -> int | None:
    value = str(snapshot.get("generated_at") or "")
    try:
        created = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    current = now or datetime.now(UTC)
    return max(0, int((current - created.astimezone(UTC)).total_seconds()))


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def restore_pipeline_observability(
    status_path: Path,
    *,
    now: datetime,
) -> tuple[list[int], dict[str, Any], str]:
    """Restore same-session latency evidence after a safe runtime restart."""
    payload = read_json_object(status_path)
    last_event_at = str(payload.get("last_event_at") or "")
    if not last_event_at:
        return [], {}, ""
    try:
        event_at = datetime.fromisoformat(last_event_at.replace("Z", "+00:00"))
    except ValueError:
        return [], {}, ""
    if event_at.tzinfo is None:
        event_at = event_at.replace(tzinfo=UTC)
    if event_at.astimezone(NEW_YORK).date() != now.astimezone(NEW_YORK).date():
        return [], {}, ""

    samples: list[int] = []
    for value in payload.get("pipeline_latency_samples_ms") or []:
        try:
            sample = max(0, int(value))
        except (TypeError, ValueError):
            continue
        samples.append(sample)
    last_result = payload.get("last_hot_pipeline")
    return samples[-200:], dict(last_result) if isinstance(last_result, dict) else {}, last_event_at


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_authorized_account_exit_cycle(
    config: Any,
    account: Any,
    client: SdkRealtimePaperClient,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Execute one explicitly authorized, account-level paper position cleanup.

    This path is deliberately separate from strategy attribution.  It is used
    only when a broker position cannot be assigned safely to a virtual lot.
    """
    path = config.output_dir / AUTHORIZED_ACCOUNT_EXIT_FILE
    state = read_json_object(path)
    if not state or state.get("authorized") is not True:
        return {"status": "inactive"}
    if state.get("paper_simulated_only") is not True:
        state.update({"status": "blocked", "reason": "paper_only_boundary_missing", "updated_at": to_iso(now)})
        write_json_atomic(path, state)
        return state
    if str(state.get("status") or "") == "completed":
        return state

    symbol = str(state.get("symbol") or "").upper().replace(".US", "")
    maximum_quantity = Decimal(str(state.get("maximum_quantity") or "0"))
    if not symbol or maximum_quantity <= 0:
        state.update({"status": "blocked", "reason": "invalid_authorized_exit_request", "updated_at": to_iso(now)})
        write_json_atomic(path, state)
        return state

    snapshot = account.snapshot()
    age = account_age_seconds(snapshot, now=now)
    account_ready = bool(
        snapshot.get("paper_account_verified") is True
        and snapshot.get("positions_ok") is True
        and snapshot.get("orders_ok") is True
        and age is not None
        and age <= config.maximum_account_snapshot_age_seconds
    )
    if not account_ready:
        state.update({"status": "waiting_for_fresh_paper_account", "reason": "account_snapshot_not_verified", "updated_at": to_iso(now)})
        write_json_atomic(path, state)
        return state

    position = next(
        (
            row for row in snapshot.get("positions", [])
            if isinstance(row, dict) and str(row.get("symbol") or "").upper().replace(".US", "") == symbol
        ),
        None,
    )
    quantity = Decimal(str((position or {}).get("quantity") or "0"))
    available = Decimal(str((position or {}).get("available") or "0"))
    if quantity <= 0:
        state.update({
            "status": "completed",
            "reason": "broker_position_zero",
            "completed_at": to_iso(now),
            "remaining_quantity": "0",
            "exclude_from_strategy_performance": True,
        })
        write_json_atomic(path, state)
        return state

    order_id = str(state.get("order_id") or "")
    matching_open_orders = [
        row for row in snapshot.get("open_orders", [])
        if isinstance(row, dict)
        and str(row.get("symbol") or "").upper().replace(".US", "") == symbol
        and str(row.get("side") or "").split(".")[-1].lower() == "sell"
    ]
    if order_id or matching_open_orders:
        state.update({
            "status": "submitted_waiting_broker_fill",
            "remaining_quantity": format(quantity, "f"),
            "updated_at": to_iso(now),
        })
        write_json_atomic(path, state)
        return state

    if not configured_regular_session(config, now):
        state.update({
            "status": "authorized_waiting_regular_session",
            "reason": "us_paper_orders_rth_only",
            "verified_broker_quantity": format(quantity, "f"),
            "verified_available_quantity": format(available, "f"),
            "updated_at": to_iso(now),
        })
        write_json_atomic(path, state)
        return state
    if available <= 0:
        state.update({"status": "blocked", "reason": "broker_available_quantity_zero", "updated_at": to_iso(now)})
        write_json_atomic(path, state)
        return state

    submitted_quantity = min(quantity, available, maximum_quantity)
    request_id = str(state.get("request_id") or f"account-cleanup-{symbol}-{uuid.uuid4().hex[:12]}")
    state.update({
        "request_id": request_id,
        "status": "submission_started",
        "submitted_quantity": format(submitted_quantity, "f"),
        "submission_started_at": to_iso(now),
        "updated_at": to_iso(now),
    })
    write_json_atomic(path, state)
    response = client.submit_order({
        "signal_id": request_id,
        "client_request_id": request_id,
        "runtime_id": "M15-ACCOUNT-RECONCILIATION",
        "capital_bucket": "account-reconciliation-cleanup",
        "symbol": symbol,
        "side": "sell",
        "position_action": "close_long",
        "order_type": "market",
        "quantity": format(submitted_quantity, "f"),
        "test_epoch_id": str(state.get("test_epoch_id") or config.formal_test_epoch_id),
        "market_exit_no_reprice": True,
        "exclude_from_strategy_performance": True,
    })
    response_order_id = str(response.get("order_id") or "")
    if not response_order_id:
        state.update({
            "status": "blocked_submission_without_order_id",
            "reason": str(response.get("error") or response.get("status") or "broker_order_id_missing"),
            "response": response,
            "updated_at": to_iso(now),
        })
    else:
        state.update({
            "status": "submitted_waiting_broker_fill",
            "order_id": response_order_id,
            "response": response,
            "submitted_at": to_iso(now),
            "updated_at": to_iso(now),
        })
    write_json_atomic(path, state)
    return state


def run_pending_flatten_cycle(
    config: Any,
    account: SdkAccountCoordinator,
    flatten_client: SdkRealtimePaperClient,
    market_events: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Advance the persisted SDK-only account flatten state machine once."""
    marker = load_formal_test_marker(config)
    marker_status = str(marker.get("status") or "")
    if marker_status == "active":
        state = read_json_object(config.formal_test_epoch_state_path)
        canonical = {
            "test_epoch_id": str(marker.get("test_epoch_id") or ""),
            "short_test_epoch_id": str(marker.get("short_test_epoch_id") or ""),
            "status": "active",
            "test_started_at": str(marker.get("test_started_at") or ""),
            "activated_at": str(marker.get("activated_at") or marker.get("test_started_at") or ""),
            "blocks_new_entries": False,
        }
        if canonical["test_started_at"] and any(state.get(key) != value for key, value in canonical.items()):
            state.update(canonical)
            state.setdefault("schema_version", "m15.sdk-runtime-auto-flatten.v1")
            state.setdefault("stage", "M15.sdk_runtime_auto_flatten")
            state["updated_at"] = to_iso(now)
            write_json_atomic(config.formal_test_epoch_state_path, state)
        return {"status": "inactive", "blocks_new_entries": False}
    if marker_status != "pending_flatten":
        return {"status": "inactive", "blocks_new_entries": False}

    epoch_id = str(marker.get("test_epoch_id") or "")
    state = read_json_object(config.formal_test_epoch_state_path)
    if str(state.get("test_epoch_id") or "") != epoch_id:
        state = {
            "schema_version": "m15.sdk-runtime-auto-flatten.v1",
            "stage": "M15.sdk_runtime_auto_flatten",
            "test_epoch_id": epoch_id,
            "short_test_epoch_id": str(marker.get("short_test_epoch_id") or ""),
            "cancel_attempts": {},
            "submissions": {},
        }
    state["updated_at"] = to_iso(now)
    state["blocks_new_entries"] = True

    snapshot = account.snapshot()
    confirmation = flatten_confirmation(
        snapshot,
        [
            str(row.get("order_id") or "")
            for row in state.get("submissions", {}).values()
            if isinstance(row, dict) and str(row.get("order_id") or "")
        ],
    )
    state["confirmation"] = confirmation
    if not configured_regular_session(config, now):
        account_reads_healthy = (
            snapshot.get("paper_account_verified") is True
            and snapshot.get("positions_ok") is True
            and snapshot.get("orders_ok") is True
        )
        if account_reads_healthy:
            state.pop("reason", None)
            state.pop("activation_blocker", None)
            if marker.get("activation_blocker"):
                marker["activation_blocker"] = ""
                write_json_atomic(config.formal_test_marker_path, marker)
        state["status"] = "waiting_for_regular_session"
        write_json_atomic(config.formal_test_epoch_state_path, state)
        return state

    try:
        snapshot_at = datetime.fromisoformat(
            str(snapshot.get("generated_at") or "").replace("Z", "+00:00")
        ).astimezone(UTC)
        snapshot_age_seconds = max(0, int((now.astimezone(UTC) - snapshot_at).total_seconds()))
    except ValueError:
        snapshot_age_seconds = -1
    state["account_snapshot_age_seconds"] = snapshot_age_seconds
    account_known = (
        snapshot.get("paper_account_verified") is True
        and snapshot.get("positions_ok") is True
        and snapshot.get("orders_ok") is True
        and 0 <= snapshot_age_seconds <= config.maximum_account_snapshot_age_seconds
    )
    if not account_known:
        state["status"] = "account_state_unknown"
        state["reason"] = "paper_account_or_positions_orders_not_verified"
        write_json_atomic(config.formal_test_epoch_state_path, state)
        return state

    if confirmation["complete"]:
        activate_not_before = parse_utc_datetime(str(marker.get("activate_not_before") or ""))
        if activate_not_before is not None and now.astimezone(UTC) < activate_not_before:
            state["status"] = "waiting_for_activation_window"
            state["activate_not_before"] = to_iso(activate_not_before)
            state["blocks_new_entries"] = True
            marker["activation_blocker"] = "waiting_for_configured_activation_time"
            marker["blocks_new_entries"] = True
            write_json_atomic(config.formal_test_marker_path, marker)
            write_json_atomic(config.formal_test_epoch_state_path, state)
            return state
        active_marker = activate_formal_epoch_payload(marker, activated_at=now)
        write_json_atomic(config.formal_test_marker_path, active_marker)
        state["status"] = active_marker["status"]
        state["test_started_at"] = active_marker["test_started_at"]
        state["activated_at"] = active_marker["activated_at"]
        state["blocks_new_entries"] = False
        write_json_atomic(config.formal_test_epoch_state_path, state)
        return state

    submissions = state.setdefault("submissions", {})
    submitted_order_ids = {
        str(row.get("order_id") or "")
        for row in submissions.values()
        if isinstance(row, dict) and str(row.get("order_id") or "")
    }
    open_orders = [row for row in snapshot.get("open_orders", []) if isinstance(row, dict)]
    cancel_attempts = state.setdefault("cancel_attempts", {})
    for order in open_orders:
        order_id = str(order.get("order_id") or order.get("id") or "")
        if order.get("sdk_pending_confirmation") or order_id in submitted_order_ids:
            continue
        if not order_id:
            state["status"] = "account_state_unknown"
            state["reason"] = "open_order_missing_order_id"
            write_json_atomic(config.formal_test_epoch_state_path, state)
            return state
        if order_id in cancel_attempts:
            continue
        cancel_attempts[order_id] = {"status": "cancel_started", "started_at": to_iso(now)}
        write_json_atomic(config.formal_test_epoch_state_path, state)
        try:
            response = flatten_client.cancel_order(order_id)
            cancel_attempts[order_id].update({"status": "cancel_requested", "response": response})
        except Exception as exc:
            cancel_attempts[order_id].update({
                "status": "cancel_state_unknown",
                "error": f"{type(exc).__name__}:{exc}"[:500],
            })
        write_json_atomic(config.formal_test_epoch_state_path, state)
    if open_orders:
        state["status"] = "waiting_for_open_orders_and_pending_confirmations"
        write_json_atomic(config.formal_test_epoch_state_path, state)
        return state

    plan, blockers = build_flatten_plan(
        snapshot,
        latest_flatten_prices(market_events, now=now),
    )
    if blockers:
        state["status"] = "flatten_plan_blocked"
        state["reason"] = ",".join(blockers)
        write_json_atomic(config.formal_test_epoch_state_path, state)
        return state

    submitted_now = 0
    for intent in plan:
        payload = runtime_flatten_order_payload(intent, test_epoch_id=epoch_id)
        request_id = str(payload["client_request_id"])
        if request_id in submissions:
            continue
        attempt = {
            "status": "market_submission_started",
            "started_at": to_iso(now),
            "symbol": payload["symbol"],
            "side": payload["side"],
            "quantity": payload["quantity"],
            "signal_id": payload["signal_id"],
            "client_request_id": request_id,
        }
        submissions[request_id] = attempt
        write_json_atomic(config.formal_test_epoch_state_path, state)
        try:
            response = flatten_client.submit_order(payload)
        except Exception as exc:
            attempt.update({
                "status": "submission_state_unknown",
                "error": f"{type(exc).__name__}:{exc}"[:500],
            })
            state["status"] = "submission_state_unknown_waiting_reconciliation"
            write_json_atomic(config.formal_test_epoch_state_path, state)
            return state
        order_id = str(response.get("order_id") or "")
        attempt.update({
            "status": str(response.get("status") or "market_submission_unknown"),
            "order_id": order_id,
            "primary_response": response,
        })
        submitted_now += 1
        if response.get("explicit_reject") is True and not order_id:
            attempt["status"] = "explicit_reject_no_retry"
            state["status"] = "flatten_order_rejected_manual_diagnosis_required"
            write_json_atomic(config.formal_test_epoch_state_path, state)
            return state
        elif not order_id:
            attempt["status"] = "submission_state_unknown"
        write_json_atomic(config.formal_test_epoch_state_path, state)

    state["status"] = (
        "waiting_for_broker_flatten_confirmation"
        if submitted_now
        else "flatten_attempts_exhausted_waiting_reconciliation"
    )
    state["submitted_this_cycle"] = submitted_now
    write_json_atomic(config.formal_test_epoch_state_path, state)
    return state


def build_live_daily_confirmation_rows(
    market_events: list[dict[str, Any]],
    *,
    generated_at: datetime,
    live_quote_session_state: dict[str, dict[str, Any]] | None = None,
    active_five_minute_event_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate current-session SDK bars without promoting stale symbols.

    Historical bars still provide the session OHLC context.  When active event
    IDs are supplied, however, a symbol is actionable only if its latest bar
    was completed in this dispatch.  A quiet or degraded quote feed therefore
    cannot turn an older price into a fresh daily confirmation merely because
    SPY or QQQ changed.
    """
    session_date = generated_at.astimezone(NEW_YORK).date().isoformat()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in market_events:
        if str(row.get("timeframe") or "") != "5m" or row.get("bar_final") is not True:
            continue
        try:
            event_date = datetime.fromisoformat(
                str(row.get("event_time") or "").replace("Z", "+00:00")
            ).astimezone(NEW_YORK).date().isoformat()
        except ValueError:
            continue
        if event_date != session_date:
            continue
        symbol = str(row.get("symbol") or "").upper().replace(".US", "")
        if symbol:
            grouped.setdefault(symbol, []).append(row)

    daily_rows: list[dict[str, Any]] = []
    quote_state_by_symbol = live_quote_session_state or {}
    for symbol, rows in grouped.items():
        rows.sort(key=lambda row: str(row.get("event_time") or ""))
        first, latest = rows[0], rows[-1]
        if (
            active_five_minute_event_ids is not None
            and str(latest.get("event_id") or "") not in active_five_minute_event_ids
        ):
            continue
        quote_state = quote_state_by_symbol.get(symbol)
        if not quote_state or str(quote_state.get("market_data_blocked_reason") or ""):
            continue
        try:
            latest_event_time = str(latest.get("event_time") or "")
            latest_bar_close_at = datetime.fromisoformat(
                latest_event_time.replace("Z", "+00:00")
            ).astimezone(UTC)
            latest_bar_open_at = datetime.fromisoformat(
                str(latest.get("bar_open_at") or "").replace("Z", "+00:00")
            ).astimezone(UTC)
            quote_source_at = datetime.fromisoformat(
                str(quote_state.get("source_event_at") or "").replace("Z", "+00:00")
            ).astimezone(UTC)
        except ValueError:
            continue
        if str(quote_state.get("session_date") or "") != session_date:
            continue
        if quote_source_at < latest_bar_open_at or quote_source_at > latest_bar_close_at:
            continue
        open_price = Decimal(str(quote_state.get("open") or "0"))
        high = Decimal(str(quote_state.get("high") or "0"))
        low = Decimal(str(quote_state.get("low") or "0"))
        close = Decimal(str(quote_state.get("close") or "0"))
        volume = int(str(quote_state.get("volume") or "0"))
        if min(open_price, high, low, close) <= 0 or volume < 0:
            continue
        daily_rows.append({
            "schema_version": "m15.realtime-market-event.v2",
            "event_id": f"sdk-1d-live|{symbol}|{session_date}|{latest_event_time}",
            "symbol": symbol,
            "timeframe": "1d",
            "event_time": latest_event_time,
            "received_at": str(quote_state.get("received_at") or latest.get("received_at") or to_iso(generated_at)),
            "source_event_at": str(quote_state.get("source_event_at") or latest.get("source_event_at") or latest_event_time),
            "bar_final": False,
            "current_session_confirmation": True,
            "source_mode": "official_sdk_live_daily_confirmation",
            "open": str(open_price),
            "high": str(high),
            "low": str(low),
            "close": str(close),
            "volume": str(volume),
            "next_bar_first_quote_price": str(latest.get("next_bar_first_quote_price") or ""),
            "next_bar_first_quote_at": str(latest.get("next_bar_first_quote_at") or ""),
            "next_bar_entry_source": str(latest.get("next_bar_entry_source") or ""),
            "local_simulation_ignored": True,
        })
    return daily_rows


def historical_daily_context_before_session(
    rows: list[dict[str, Any]],
    *,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    """Return only completed prior-session SDK daily bars for strategy context.

    These rows cannot become active signal events.  The current session's
    completed five-minute event and live daily aggregate remain the trigger.
    """
    session_date = generated_at.astimezone(NEW_YORK).date()
    result: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("timeframe") or "") != "1d" or row.get("bar_final") is not True:
            continue
        try:
            event_date = datetime.fromisoformat(
                str(row.get("event_time") or "").replace("Z", "+00:00")
            ).astimezone(NEW_YORK).date()
        except ValueError:
            continue
        if event_date >= session_date:
            continue
        result.append(dict(row))
    return result


def opening_signal_outside_trading_universe(
    config: Any,
    signal: dict[str, Any],
) -> bool:
    """Block only new positions outside the frozen strategy universe."""
    from scripts.m15_longbridge_realtime_execution_lib import ledger_row_opens_position

    return bool(
        ledger_row_opens_position(signal)
        and not market_event_is_tradable(config, signal)
    )


def dispatch_completed_rows(
    config: Any,
    rows: list[dict[str, Any]],
    market_context: MarketEventContext,
    account_coordinator: SdkAccountCoordinator,
    paper_client: SdkRealtimePaperClient | None,
    *,
    position_market_context: MarketEventContext | None = None,
    daily_context_rows: list[dict[str, Any]] | None = None,
    live_quote_session_state: dict[str, dict[str, Any]] | None = None,
    signal_event_cache: list[dict[str, Any]] | None = None,
    signal_id_cache: set[str] | None = None,
    execution_ledger_cache: list[dict[str, Any]] | None = None,
    fill_attribution_state_cache: dict[str, Any] | None = None,
    new_entry_submission_enabled: bool = True,
) -> dict[str, Any]:
    stage_started = time.perf_counter()
    rows = attach_next_bar_first_quotes(rows, live_quote_session_state or {})
    fresh = fresh_market_events(rows, config.maximum_source_delivery_age_ms)
    append_market_events(config.market_events_path, fresh, config.event_keep_lines)
    trading_fresh = trading_market_events(config, fresh)
    new_rows = market_context.append(trading_fresh)
    position_new_rows = (
        position_market_context.append(fresh)
        if position_market_context is not None
        else new_rows
    )
    if not new_rows and not position_new_rows:
        return {"event_count": 0, "signal_count": 0, "execution": {}}
    from scripts.m15_longbridge_realtime_signal_router_lib import load_config as load_router_config, run_realtime_signal_router
    from scripts.m15_longbridge_realtime_position_manager_lib import load_config as load_position_config, run_realtime_position_manager
    from scripts.m15_longbridge_realtime_execution_lib import load_config as load_execution_config, run_realtime_execution

    now = str((new_rows or position_new_rows)[-1]["received_at"])
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    trading_market_rows = market_context.rows()
    position_market_rows = (
        position_market_context.rows()
        if position_market_context is not None
        else trading_market_rows
    )
    active_ids = {str(row["event_id"]) for row in new_rows}
    live_daily_rows = build_live_daily_confirmation_rows(
        trading_market_rows,
        generated_at=now_dt,
        live_quote_session_state=live_quote_session_state,
        active_five_minute_event_ids={
            str(row.get("event_id") or "")
            for row in new_rows
            if str(row.get("timeframe") or "") == "5m" and row.get("bar_final") is True
        },
    )
    active_ids.update(str(row.get("event_id") or "") for row in live_daily_rows)
    historical_daily_rows = historical_daily_context_before_session(
        daily_context_rows or [],
        generated_at=now_dt,
    )
    router_market_rows = historical_daily_rows + trading_market_rows + live_daily_rows
    router = load_router_config(config.router_config_path)
    if signal_event_cache is None:
        signal_event_cache = read_jsonl_tail_rows(
            router.signal_events_path,
            maximum_rows=1_000_000,
        )
    if signal_id_cache is None:
        signal_id_cache = {
            str(row.get("signal_id") or "")
            for row in signal_event_cache
            if row.get("signal_id")
        }
    if execution_ledger_cache is None:
        execution_config = load_execution_config(config.execution_config_path)
        execution_ledger_cache = read_jsonl_tail_rows(
            execution_config.output_dir / EXECUTION_LEDGER_FILE,
            maximum_rows=1_000_000,
        )
    if fill_attribution_state_cache is None:
        fill_attribution_state_cache = {}
    formal_marker = load_formal_test_marker(config)
    if formal_marker:
        router = replace(
            router,
            short_test_epoch_id=str(formal_marker["short_test_epoch_id"]),
            short_test_started_at=str(formal_marker["test_started_at"]),
        )
    emitted: list[dict[str, Any]] = []
    router_started = time.perf_counter()
    router_payload = run_realtime_signal_router(
        router, generated_at=now, market_events_override=router_market_rows,
        active_market_event_ids=active_ids, emitted_signal_events=emitted,
        existing_signal_ids_override=signal_id_cache,
    )
    router_elapsed_ms = int((time.perf_counter() - router_started) * 1000)
    if emitted:
        signal_event_cache.extend(emitted)
        signal_id_cache.update(
            str(row.get("signal_id") or "")
            for row in emitted
            if row.get("signal_id")
        )
    snapshot = account_coordinator.snapshot()
    position_config = replace(load_position_config(config.position_manager_config_path), market_events_path=config.market_events_path)
    if formal_marker:
        position_config = replace(
            position_config,
            test_epoch_id=str(formal_marker["test_epoch_id"]),
            test_started_at=str(formal_marker["test_started_at"]),
            short_test_epoch_id=str(formal_marker["short_test_epoch_id"]),
        )
    position_started = time.perf_counter()
    positions = run_realtime_position_manager(
        position_config,
        generated_at=now,
        account_state_override=snapshot,
        market_events_override=position_market_rows,
        execution_rows_override=execution_ledger_cache,
        signal_events_override=signal_event_cache,
        fill_attribution_state_cache=fill_attribution_state_cache,
    )
    position_elapsed_ms = int((time.perf_counter() - position_started) * 1000)
    execution: dict[str, Any] = {}
    flatten_pending = str(formal_marker.get("status") or "") == "pending_flatten"
    dispatch_in_regular_session = configured_regular_session(config, now_dt)
    exit_signals = list(positions.get("emitted_exit_signal_events", []))
    if exit_signals:
        signal_event_cache.extend(exit_signals)
        signal_id_cache.update(
            str(row.get("signal_id") or "")
            for row in exit_signals
            if row.get("signal_id")
        )
    execution_signals = signals_allowed_by_entry_gate(
        emitted,
        exit_signals,
        new_entry_submission_enabled=new_entry_submission_enabled,
    )
    out_of_scope_signals = [
        signal
        for signal in execution_signals
        if opening_signal_outside_trading_universe(config, signal)
    ]
    execution_signals = [
        signal for signal in execution_signals if signal not in out_of_scope_signals
    ]
    if out_of_scope_signals:
        execution["scope_blocked_opening_signal_count"] = len(out_of_scope_signals)
        execution["scope_blocked_opening_symbols"] = sorted({
            str(signal.get("symbol") or "")
            for signal in out_of_scope_signals
        })
    if (
        paper_client is not None
        and not flatten_pending
        and dispatch_in_regular_session
        and execution_signals
    ):
        execution_config = load_execution_config(config.execution_config_path)
        if formal_marker:
            execution_config = replace(
                execution_config,
                test_epoch_id=str(formal_marker["test_epoch_id"]),
                short_test_epoch_id=str(formal_marker["short_test_epoch_id"]),
                short_test_started_at=str(formal_marker["test_started_at"]),
            )
        execution_account_snapshot = dict(snapshot)
        execution_account_snapshot["fill_attribution_frozen_symbols"] = list(
            positions.get("fill_attribution_mismatch_symbols", [])
        )
        execution_account_snapshot[
            "fill_attributed_open_exposure_by_bucket_symbol"
        ] = dict(
            positions.get("fill_attributed_open_exposure_by_bucket_symbol") or {}
        )
        execution_rows_emitted: list[dict[str, Any]] = []
        execution_started = time.perf_counter()
        execution = run_realtime_execution(
            execution_config, generated_at=now, broker_client=paper_client,
            account_state_override=execution_account_snapshot,
            signal_events_override=execution_signals,
            existing_ledger_override=execution_ledger_cache,
            emitted_ledger_rows=execution_rows_emitted,
        )
        execution["hot_path_elapsed_ms"] = int(
            (time.perf_counter() - execution_started) * 1000
        )
        if out_of_scope_signals:
            execution["scope_blocked_opening_signal_count"] = len(out_of_scope_signals)
            execution["scope_blocked_opening_symbols"] = sorted({
                str(signal.get("symbol") or "")
                for signal in out_of_scope_signals
            })
        execution_ledger_cache.extend(execution_rows_emitted)
    elif out_of_scope_signals and not execution_signals:
        execution = {
            "status": "blocked_signal_symbol_outside_trading_universe",
            "submitted_count": 0,
            "blocked_signal_count": len(out_of_scope_signals),
            "blocked_symbols": sorted({
                str(signal.get("symbol") or "")
                for signal in out_of_scope_signals
            }),
        }
    elif paper_client is not None and not flatten_pending and dispatch_in_regular_session:
        execution = {
            "status": (
                "blocked_new_entries_exit_path_ready"
                if emitted and not new_entry_submission_enabled
                else "no_new_realtime_signal"
            ),
            "submitted_count": 0,
            "blocked_signal_count": len(emitted) if not new_entry_submission_enabled else 0,
            "blocked_by_reason": (
                {"new_entry_gate_not_passed": len(emitted)}
                if emitted and not new_entry_submission_enabled
                else {}
            ),
            "hot_path_elapsed_ms": 0,
        }
    elif flatten_pending:
        execution = {"status": "blocked_pending_account_flatten", "submitted_count": 0}
    elif paper_client is not None and not dispatch_in_regular_session:
        execution = {
            "status": "blocked_outside_regular_session",
            "submitted_count": 0,
            "blocked_signal_count": len(execution_signals),
            "blocked_by_reason": {"not_us_regular_session": len(execution_signals)},
        }
    return {
        "event_count": len(fresh),
        "trading_event_count": len(new_rows),
        "position_monitoring_event_count": max(
            0, len(position_new_rows) - len(new_rows)
        ),
        "readonly_expansion_event_count": len(fresh) - len(trading_fresh),
        "signal_count": len(emitted),
        "live_daily_confirmation_count": len(live_daily_rows),
        "router": router_payload,
        "execution": execution,
        "formal_test_epoch_id": str(formal_marker.get("test_epoch_id") or ""),
        "stage_latency_ms": {
            "router": router_elapsed_ms,
            "position_manager": position_elapsed_ms,
            "execution": int(execution.get("hot_path_elapsed_ms") or 0),
            "total": int((time.perf_counter() - stage_started) * 1000),
        },
    }


def read_jsonl_tail_rows(path: Path, maximum_rows: int = 5000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=maximum_rows)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return list(rows)


def row_market_date(row: dict[str, Any]) -> str:
    for key in (
        "processed_at",
        "submitted_at",
        "created_at",
        "generated_at",
        "signal_time",
    ):
        value = str(row.get(key) or "")
        if not value:
            continue
        try:
            return (
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                .astimezone(NEW_YORK)
                .date()
                .isoformat()
            )
        except ValueError:
            continue
    return ""


def compact_hot_execution_rows(
    rows: list[dict[str, Any]],
    *,
    market_date: str,
) -> list[dict[str, Any]]:
    disposable_statuses = {
        "blocked_not_submitted",
        "dry_run_ready_not_submitted",
    }
    return [
        row
        for row in rows
        if str(row.get("submission_status") or "") not in disposable_statuses
        or row_market_date(row) == market_date
    ]


def compact_hot_signal_rows(
    rows: list[dict[str, Any]],
    execution_rows: list[dict[str, Any]],
    *,
    market_date: str,
) -> list[dict[str, Any]]:
    execution_signal_ids = {
        str(row.get("signal_id") or "")
        for row in execution_rows
        if row.get("signal_id")
    }
    return [
        row
        for row in rows
        if row_market_date(row) == market_date
        or str(row.get("signal_id") or "") in execution_signal_ids
    ]


def preserve_last_order_maintenance_action(
    summary: dict[str, Any],
    previous: dict[str, Any],
) -> dict[str, Any]:
    result = dict(summary)
    if int(summary.get("planned_action_count", 0) or 0) > 0:
        result["last_action"] = {
            "generated_at": summary.get("generated_at", ""),
            "status": summary.get("status", ""),
            "planned_action_count": summary.get("planned_action_count", 0),
            "completed_action_count": summary.get("completed_action_count", 0),
            "failed_action_count": summary.get("failed_action_count", 0),
            "actions": list(summary.get("actions", [])),
        }
    elif isinstance(previous.get("last_action"), dict):
        result["last_action"] = dict(previous["last_action"])
    elif int(previous.get("planned_action_count", 0) or 0) > 0:
        result["last_action"] = {
            "generated_at": previous.get("generated_at", ""),
            "status": previous.get("status", ""),
            "planned_action_count": previous.get("planned_action_count", 0),
            "completed_action_count": previous.get("completed_action_count", 0),
            "failed_action_count": previous.get("failed_action_count", 0),
            "actions": list(previous.get("actions", [])),
        }
    return result


def run_sdk_order_maintenance(
    config: Any,
    paper_client: SdkRealtimePaperClient,
    account: SdkAccountCoordinator,
    market_events: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    snapshot = account.snapshot()
    summary: dict[str, Any] = {
        "generated_at": to_iso(now),
        "source_mode": "official_sdk_only",
        "paper_simulated_only": True,
        "account_channel": str(snapshot.get("account_channel") or ""),
        "paper_account_verified": snapshot.get("paper_account_verified") is True,
        "planned_action_count": 0,
        "completed_action_count": 0,
        "failed_action_count": 0,
        "actions": [],
    }
    if summary["account_channel"] != "lb_papertrading" or not summary["paper_account_verified"]:
        summary["status"] = "blocked_paper_account_not_verified"
    else:
        actions = sdk_order_maintenance_actions(
            snapshot,
            read_jsonl_tail_rows(config.output_dir / EXECUTION_LEDGER_FILE),
            market_events,
            now=now,
            stale_entry_order_ttl_seconds=config.stale_entry_order_ttl_seconds,
            exit_order_reprice_seconds=config.exit_order_reprice_seconds,
        )[:20]
        summary["planned_action_count"] = len(actions)
        for action in actions:
            started = time.perf_counter()
            try:
                if action["action"] == "cancel":
                    response = paper_client.cancel_order(str(action["order_id"]))
                else:
                    response = paper_client.replace_order(
                        str(action["order_id"]),
                        Decimal(str(action["quantity"])),
                        Decimal(str(action["new_price"])),
                    )
                summary["completed_action_count"] += 1
                result_status = str(response.get("status") or "completed")
            except Exception as exc:
                response = {"error": f"{type(exc).__name__}:{exc}"}
                summary["failed_action_count"] += 1
                result_status = "failed"
            summary["actions"].append({
                **action,
                "result_status": result_status,
                "response": response,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            })
        if summary["completed_action_count"]:
            account.refresh()
        summary["status"] = (
            "partial_failure"
            if summary["failed_action_count"]
            else ("maintained" if summary["completed_action_count"] else "no_action_needed")
        )
    output_path = config.output_dir / ORDER_MAINTENANCE_FILE
    try:
        previous = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = {}
    summary = preserve_last_order_maintenance_action(summary, previous)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def stop_spawned_process(process: mp.Process | None, *, graceful: bool) -> None:
    """Join spawned SDK workers before forcing termination as a last resort."""
    if process is None:
        return
    if graceful:
        process.join(timeout=2)
    if process.is_alive():
        process.terminate()
    process.join(timeout=2)


def close_spawn_queue(queue_out: Any) -> None:
    """Release multiprocessing queue handles after all children have stopped."""
    close = getattr(queue_out, "close", None)
    if callable(close):
        close()
    join_thread = getattr(queue_out, "join_thread", None)
    if callable(join_thread):
        join_thread()


def request_runtime_shutdown(
    pid: int,
    *,
    timeout_seconds: float = 15.0,
    force_timeout_seconds: float = 2.0,
) -> bool:
    """Stop the SDK runtime after giving spawned SDK workers time to close."""
    if not process_alive(pid):
        return True
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if not process_alive(pid):
        return True
    if not is_expected_sdk_runtime_process(pid):
        return False
    try:
        process_group = os.getpgid(pid)
        os.killpg(process_group, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return not process_alive(pid)
    deadline = time.monotonic() + force_timeout_seconds
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if not process_alive(pid):
        return True
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        return True
    deadline = time.monotonic() + force_timeout_seconds
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not process_alive(pid)


def is_expected_sdk_runtime_process(pid: int) -> bool:
    try:
        command = Path(f"/proc/{pid}/cmdline").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "run_m15_longbridge_sdk_runtime.py" in command and "--watch" in command


def runtime_status_age_seconds(status: dict[str, Any], now: datetime | None = None) -> int | None:
    generated_at = str(status.get("generated_at") or "")
    if not generated_at:
        return None
    try:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return max(0, int((current - generated.astimezone(UTC)).total_seconds()))


def runtime_requires_health_replacement(status: dict[str, Any], config: Any) -> bool:
    """Identify terminal health states that require diagnosis, not replacement."""
    status_value = str(status.get("status") or "")
    if status_value in {
        "fault_halted",
        "halted_account_snapshot_circuit",
        "blocked_sdk_prerequisite",
    }:
        return True
    if status_value not in {"running", "connecting"}:
        return False
    status_age = runtime_status_age_seconds(status)
    account_age = status.get("account_snapshot_age_seconds")
    try:
        account_age_value = int(account_age) if account_age not in (None, "") else None
    except (TypeError, ValueError):
        account_age_value = None
    if status_age is not None and status_age > max(90, config.maximum_account_snapshot_age_seconds * 2):
        return True
    if account_age_value is not None and account_age_value > max(90, config.maximum_account_snapshot_age_seconds * 2):
        return True
    return False


def acquire_runtime_run_lock(output_dir: Path) -> Any | None:
    """Acquire the one process-wide SDK quote subscription lock."""
    del output_dir
    GLOBAL_QUOTE_SUBSCRIPTION_LOCK.parent.mkdir(parents=True, exist_ok=True)
    run_lock = GLOBAL_QUOTE_SUBSCRIPTION_LOCK.open("a+", encoding="utf-8")
    try:
        fcntl.flock(run_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        run_lock.close()
        return None
    return run_lock


def run_watch(config: Any, *, dispatch_requested: bool) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    run_lock = acquire_runtime_run_lock(config.output_dir)
    if run_lock is None:
        owner_pid = read_pid(GLOBAL_QUOTE_SUBSCRIPTION_LOCK)
        print(f"M15 SDK 实时运行层已有单实例持有运行锁，PID={owner_pid or 'unknown'}。", flush=True)
        return 0
    run_lock.seek(0)
    run_lock.truncate()
    run_lock.write(f"{os.getpid()}\n")
    run_lock.flush()
    pid_path(config).write_text(f"{os.getpid()}\n", encoding="utf-8")
    orphaned_runtime_children_cleaned = cleanup_orphaned_sdk_runtime_children(config)
    sdk = require_sdk_contract()
    run_id = f"sdk-{uuid.uuid4().hex[:12]}"
    runtime_started_at = to_iso(datetime.now(UTC))
    try:
        runtime_process_start_ticks = Path("/proc/self/stat").read_text(encoding="utf-8").split()[21]
    except (OSError, IndexError):
        runtime_process_start_ticks = ""
    loaded_config_fingerprint = config_fingerprint(config)
    complete_session_gate_passed_now, complete_sessions_passed, complete_sessions_required = readonly_gate_passed(
        config.readonly_gate_path,
        required_complete_sessions=config.required_complete_sessions,
    )
    expansion_gate_path = config.output_dir / "m15_sdk_expansion_readonly_gate.json"
    expansion_gate_passed, expansion_sessions_passed, expansion_sessions_required = readonly_gate_passed(
        expansion_gate_path,
        required_complete_sessions=1,
    )
    deployment = verify_manifest(config.config_path)
    deployment_ready = bool(deployment.get("verified"))
    dispatch_enabled = bool(
        dispatch_requested
        and config.paper_order_dispatch_enabled
        and (
            not config.complete_session_gate_enabled
            or complete_session_gate_passed_now
        )
        and deployment_ready
    )
    execution_request_gate = SdkTradeRequestGate()
    from scripts.m15_longbridge_realtime_signal_router_lib import (
        load_config as load_router_config,
    )
    from scripts.m15_longbridge_realtime_execution_lib import (
        load_config as load_execution_config,
    )

    hot_router_config = load_router_config(config.router_config_path)
    hot_execution_config = load_execution_config(config.execution_config_path)
    all_signal_events = read_jsonl_tail_rows(
        hot_router_config.signal_events_path,
        maximum_rows=1_000_000,
    )
    signal_id_cache = {
        str(row.get("signal_id") or "")
        for row in all_signal_events
        if row.get("signal_id")
    }
    all_execution_rows = read_jsonl_tail_rows(
        hot_execution_config.output_dir / EXECUTION_LEDGER_FILE,
        maximum_rows=1_000_000,
    )
    startup_market_date = datetime.now(NEW_YORK).date().isoformat()
    execution_ledger_cache = compact_hot_execution_rows(
        all_execution_rows,
        market_date=startup_market_date,
    )
    signal_event_cache = compact_hot_signal_rows(
        all_signal_events,
        execution_ledger_cache,
        market_date=startup_market_date,
    )
    fill_attribution_state_cache: dict[str, Any] = {}

    account = SdkAccountProcessCoordinator(
        partial(build_sdk_account_provider_for_worker, str(config.config_path)),
        config.output_dir / "m15_longbridge_realtime_account_state.json",
        interval_seconds=config.account_snapshot_interval_seconds,
        refresh_deadline_seconds=config.account_snapshot_refresh_deadline_seconds,
        circuit_retry_cooldown_seconds=config.account_snapshot_circuit_retry_seconds,
    )
    # Read one trusted account snapshot for paper-account and held-position
    # discovery. Account refresh remains independent from quote startup so a
    # quote retry cannot make the account state stale.
    account.start(background_refresh=True)
    startup_account_snapshot = account.snapshot()
    position_monitoring_symbols = held_position_monitoring_symbols(
        config,
        startup_account_snapshot,
    )
    execution_trade, paper_client, flatten_client = build_sdk_trade_clients(
        config,
        sdk,
        execution_request_gate,
        account.note_submission,
        dispatch_enabled=dispatch_enabled,
    )
    now_ny = datetime.now(NEW_YORK)
    session_started_at = now_ny.replace(hour=9, minute=30, second=0, microsecond=0).astimezone(UTC)
    cached_intraday_rows = load_current_sdk_intraday_context(
        config.market_events_path,
        session_started_at,
    )
    context = MarketEventContext(
        maximum_rows=(
            len(configured_trading_symbols(config)) * config.daily_context_bars
        )
        + 4096
    )
    context.append(trading_market_events(config, cached_intraday_rows))
    position_context = MarketEventContext(
        maximum_rows=(
            len(configured_trading_symbols(config))
            + len(position_monitoring_symbols)
        ) * 32
    )
    position_context.append(cached_intraday_rows)
    live_quote_session_state: dict[str, dict[str, Any]] = {}
    # PyO3 SDK contexts must not be inherited through fork.  A fresh spawned
    # interpreter gives the quote WebSocket its own native runtime and makes
    # a blocked subscribe call safely terminable by the parent.
    process_context = mp.get_context("spawn")
    message_queue: Any = process_context.Queue(maxsize=2048)
    stop_event: Any = process_context.Event()
    worker: mp.Process | None = None
    worker_ready = False
    worker_started = 0.0
    worker_last_progress = 0.0
    worker_ready_since = 0.0
    worker_generation = 0
    last_push_by_symbol: dict[str, float] = {}
    first_live_push_by_symbol: dict[str, float] = {}
    last_live_push_by_symbol: dict[str, float] = {}
    last_push_at_by_symbol: dict[str, str] = {}
    last_push_source_by_symbol: dict[str, str] = {}
    complete_boundary_count = 0
    incomplete_boundary_count = 0
    structural_incomplete_boundary_count = 0
    reference_stale_boundary_count = 0
    late_boundary_count = 0
    realtime_tradable_bar_count = 0
    no_trade_carry_forward_count = 0
    last_complete_boundary = ""
    last_incomplete_boundary = ""
    last_boundary_missing_symbols: list[str] = []
    reference_market_data_state = "healthy"
    subscription_progress_completed = 0
    subscription_progress_total = len(configured_symbols(config))
    daily_context_progress_completed = 0
    daily_context_progress_total = len(configured_symbols(config))
    restored_latency_samples, restored_last_result, restored_last_event_at = restore_pipeline_observability(
        config.runtime_status_path,
        now=datetime.now(UTC),
    )
    last_event_at = restored_last_event_at
    last_compaction = 0.0
    last_order_maintenance = 0.0
    last_trade_context_healthcheck = 0.0
    next_trade_context_retry = 0.0
    trade_context_health: dict[str, Any] = {
        "ok": False,
        "status": "waiting_for_first_healthcheck",
    }
    last_result: dict[str, Any] = restored_last_result
    order_maintenance: dict[str, Any] = {}
    flatten_transition: dict[str, Any] = {}
    authorized_account_exit: dict[str, Any] = {}
    capital_bucket_migration: dict[str, Any] = {}
    pipeline_latency_samples: deque[int] = deque(restored_latency_samples, maxlen=200)
    daily_rows: list[dict[str, Any]] = []
    subscription_failed: list[str] = []
    trading_subscription_failed: list[str] = []
    position_monitoring_subscribed: list[str] = []
    position_monitoring_failed: list[str] = []
    transport_child_pid = 0
    transport_queue_depth = 0
    transport_reader_errors: list[str] = []
    transport_resources: dict[str, int] = {}
    transport_coalesced_quote_pending_count = 0
    transport_coalesced_quote_replacement_count = 0
    transport_raw_notification_count = 0
    initial_snapshot_coverage = "0/0"
    position_monitoring_initial_snapshot_coverage = "0/0"
    daily_failed: list[str] = []
    daily_context_state = "waiting_for_official_sdk"
    daily_context_cache_reused = False
    daily_context_persisted = False
    observed_regular_sessions: set[str] = set()
    observed_expansion_sessions: set[str] = set()
    deferred_messages: deque[dict[str, Any]] = deque()
    partial_bar_suppressed_until = ""
    last_subscription_failure_reason = ""
    market_data_mode = configured_market_data_mode(config)
    market_data_symbols: set[str] = set()
    market_data_failed: list[str] = []
    trading_market_data_failed: list[str] = []
    last_market_data_worker_error = ""
    shutdown_requested = False
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def stop_requested(_signum: int, _frame: Any) -> None:
        nonlocal shutdown_requested
        shutdown_requested = True
        stop_event.set()

    def apply_transport_heartbeat_message(message: dict[str, Any]) -> None:
        nonlocal worker_last_progress
        nonlocal transport_queue_depth
        nonlocal transport_reader_errors
        nonlocal transport_resources
        nonlocal transport_coalesced_quote_pending_count
        nonlocal transport_coalesced_quote_replacement_count
        nonlocal transport_raw_notification_count
        worker_last_progress = time.monotonic()
        transport_queue_depth = int(
            message.get("transport_queue_depth") or 0
        )
        transport_reader_errors = [
            str(value)
            for value in message.get("transport_reader_errors") or []
        ]
        transport_resources = {
            str(key): int(value)
            for key, value in dict(
                message.get("transport_resources") or {}
            ).items()
        }
        transport_coalesced_quote_pending_count = int(
            message.get("coalesced_quote_pending_count") or 0
        )
        transport_coalesced_quote_replacement_count = int(
            message.get("coalesced_quote_replacement_count") or 0
        )
        transport_raw_notification_count = int(
            message.get("raw_notification_count") or 0
        )
        for activity in message.get("raw_reference_activity") or []:
            if isinstance(activity, dict):
                apply_market_activity_message(activity)

    def apply_market_activity_message(message: dict[str, Any]) -> None:
        apply_reference_market_activity_message(
            message,
            last_push_by_symbol=last_push_by_symbol,
            last_push_at_by_symbol=last_push_at_by_symbol,
            last_push_source_by_symbol=last_push_source_by_symbol,
            first_live_push_by_symbol=first_live_push_by_symbol,
            last_live_push_by_symbol=last_live_push_by_symbol,
        )

    def drain_pending_worker_health_messages() -> None:
        for _ in range(2048):
            try:
                pending = message_queue.get_nowait()
            except queue.Empty:
                return
            pending_kind = str(pending.get("kind") or "")
            if pending_kind == "heartbeat":
                apply_transport_heartbeat_message(pending)
            elif pending_kind in {"quote_state", "quote_state_batch"}:
                apply_quote_state_worker_message(
                    pending,
                    live_quote_session_state=live_quote_session_state,
                    last_push_by_symbol=last_push_by_symbol,
                    last_push_at_by_symbol=last_push_at_by_symbol,
                    last_push_source_by_symbol=last_push_source_by_symbol,
                    first_live_push_by_symbol=first_live_push_by_symbol,
                    last_live_push_by_symbol=last_live_push_by_symbol,
                )
            elif pending_kind == "market_activity":
                apply_market_activity_message(pending)
            else:
                deferred_messages.append(pending)

    def halt_market_data(reason: str, *, details: dict[str, Any] | None = None) -> int:
        """Persist a terminal market-data fault and stop without recovery."""
        nonlocal worker_ready
        nonlocal last_subscription_failure_reason
        nonlocal last_market_data_worker_error
        worker_ready = False
        last_subscription_failure_reason = reason
        last_market_data_worker_error = reason
        build_status(
            config,
            status="fault_halted",
            reason=reason,
            connected=False,
            last_event_at=last_event_at,
            sdk_installed=True,
            oauth_client_id_present=True,
            subscription_failed_symbols=subscription_failed,
            extra={
                "run_id": run_id,
                "runtime_pid": os.getpid(),
                "runtime_started_at": runtime_started_at,
                "runtime_process_start_ticks": runtime_process_start_ticks,
                "runtime_command_line": " ".join(sys.argv),
                "runtime_engine": "sdk",
                "market_data_mode": "official_sdk_subscription",
                "market_data_transport": config.market_data_transport,
                "market_data_fault_halted": True,
                "automatic_market_data_retry_enabled": False,
                "snapshot_fallback_enabled": False,
                "new_position_submission_enabled": False,
                "dispatch_enabled": False,
                "dispatch_requested": dispatch_requested,
                "paper_account_only": True,
                "config_fingerprint": loaded_config_fingerprint,
                "quote_worker_generation": worker_generation,
                "quote_worker_pid": worker.pid if worker is not None else "",
                "market_data_transport_child_pid": transport_child_pid,
                "subscription_progress": (
                    f"{subscription_progress_completed}/{subscription_progress_total}"
                ),
                "daily_context_progress": (
                    f"{daily_context_progress_completed}/{daily_context_progress_total}"
                ),
                "subscription_coverage": (
                    f"{len(market_data_symbols)}/{len(configured_symbols(config))}"
                ),
                "trading_subscription_coverage": (
                    f"{len(set(configured_trading_symbols(config)) & market_data_symbols)}"
                    f"/{len(configured_trading_symbols(config))}"
                ),
                "fault_details": details or {},
            },
        )
        stop_event.set()
        return 4

    signal.signal(signal.SIGTERM, stop_requested)
    try:
        while not shutdown_requested:
            if worker is None and worker_generation == 0:
                worker_ready = False
                worker_started = time.monotonic()
                worker_last_progress = worker_started
                transport_child_pid = 0
                transport_queue_depth = 0
                transport_reader_errors = []
                transport_resources = {}
                transport_coalesced_quote_pending_count = 0
                transport_coalesced_quote_replacement_count = 0
                transport_raw_notification_count = 0
                initial_snapshot_coverage = "0/0"
                position_monitoring_initial_snapshot_coverage = "0/0"
                subscription_failed = []
                trading_subscription_failed = []
                position_monitoring_subscribed = []
                position_monitoring_failed = []
                market_data_symbols = set()
                market_data_failed = []
                trading_market_data_failed = []
                subscription_progress_completed = 0
                daily_context_progress_completed = 0
                subscription_progress_total = len(
                    quote_subscription_targets(config, datetime.now(UTC))
                )
                worker = process_context.Process(
                    target=configured_quote_worker(config),
                    args=(
                        str(config.config_path),
                        message_queue,
                        stop_event,
                        position_monitoring_symbols,
                    ),
                    daemon=True,
                )
                worker.start()
                worker_generation += 1
                worker_ready_since = 0.0
                reference_market_data_state = "healthy"
                first_live_push_by_symbol.clear()
                last_live_push_by_symbol.clear()
            elif worker is None or not worker.is_alive():
                exit_code = worker.exitcode if worker is not None else None
                return halt_market_data(
                    "market_data_worker_exited",
                    details={"exit_code": exit_code},
                )
            if (
                not worker_ready
                and time.monotonic() - worker_started
                > (
                    config.daily_context_deadline_seconds
                    + config.subscription_deadline_seconds
                )
            ):
                return halt_market_data(
                    "market_data_subscription_deadline_exceeded",
                    details={
                        "deadline_seconds": (
                            config.daily_context_deadline_seconds
                            + config.subscription_deadline_seconds
                        ),
                        "subscription_progress": (
                            f"{subscription_progress_completed}/{subscription_progress_total}"
                        ),
                        "daily_context_progress": (
                            f"{daily_context_progress_completed}/{daily_context_progress_total}"
                        ),
                    },
                )
            if worker_ready:
                drain_pending_worker_health_messages()
            if worker_ready and transport_reader_errors:
                return halt_market_data(
                    "market_data_reader_error",
                    details={"reader_error": transport_reader_errors[-1]},
                )
            if (
                worker_ready
                and market_data_heartbeat_grace_elapsed(
                    worker_ready_since,
                    time.monotonic(),
                    config.subscription_deadline_seconds,
                )
                and market_data_heartbeat_is_stale(
                    worker_last_progress,
                    time.monotonic(),
                    config.market_data_heartbeat_deadline_seconds,
                )
            ):
                return halt_market_data(
                    "market_data_heartbeat_deadline_exceeded",
                    details={
                        "deadline_seconds": config.market_data_heartbeat_deadline_seconds
                    },
                )
            reference_check_now = datetime.now(UTC)
            reference_check_monotonic = time.monotonic()
            references_are_stale = bool(
                worker_ready
                and configured_regular_session(config, reference_check_now)
                and regular_session_open_grace_elapsed(
                    reference_check_now,
                    config.active_symbol_silence_seconds,
                )
                and market_data_heartbeat_grace_elapsed(
                    worker_ready_since,
                    reference_check_monotonic,
                    config.active_symbol_silence_seconds,
                )
                and active_reference_quotes_are_stale(
                    last_push_by_symbol,
                    now_monotonic=reference_check_monotonic,
                    maximum_silence_seconds=config.active_symbol_silence_seconds,
                )
            )
            if references_are_stale:
                return halt_market_data(
                    "reference_market_data_stalled",
                    details={
                        "symbols": ["SPY.US", "QQQ.US"],
                        "maximum_silence_seconds": config.active_symbol_silence_seconds,
                        "last_push_at": {
                            symbol: last_push_at_by_symbol.get(symbol, "")
                            for symbol in ("SPY.US", "QQQ.US")
                        },
                        "last_push_source": {
                            symbol: last_push_source_by_symbol.get(symbol, "")
                            for symbol in ("SPY.US", "QQQ.US")
                        },
                        "transport_raw_notification_count": (
                            transport_raw_notification_count
                        ),
                        "transport_callback_queue_depth": transport_queue_depth,
                        "transport_reader_errors": list(transport_reader_errors),
                        "transport_resources": dict(transport_resources),
                        "worker_heartbeat_age_seconds": round(
                            reference_check_monotonic - worker_last_progress,
                            3,
                        ),
                    },
                )
            reference_market_data_state = "healthy"
            try:
                message = deferred_messages.popleft() if deferred_messages else message_queue.get(timeout=config.heartbeat_interval_seconds)
            except queue.Empty:
                message = {"kind": "idle"}
            kind = str(message.get("kind") or "")
            if kind == "subscription_progress":
                worker_last_progress = time.monotonic()
                subscription_progress_completed = int(message.get("completed") or 0)
                subscription_progress_total = int(
                    message.get("total") or subscription_progress_total
                )
            elif kind == "daily_context_progress":
                worker_last_progress = time.monotonic()
                daily_context_progress_completed = int(
                    message.get("completed") or 0
                )
                daily_context_progress_total = int(
                    message.get("total") or daily_context_progress_total
                )
            elif kind in {"quote_state", "quote_state_batch"}:
                apply_quote_state_worker_message(
                    message,
                    live_quote_session_state=live_quote_session_state,
                    last_push_by_symbol=last_push_by_symbol,
                    last_push_at_by_symbol=last_push_at_by_symbol,
                    last_push_source_by_symbol=last_push_source_by_symbol,
                    first_live_push_by_symbol=first_live_push_by_symbol,
                    last_live_push_by_symbol=last_live_push_by_symbol,
                )
            elif kind == "market_activity":
                apply_market_activity_message(message)
            elif kind == "ready":
                transport_child_pid = 0
                initial_snapshot_coverage = str(
                    message.get("initial_snapshot_coverage") or "0/0"
                )
                position_monitoring_initial_snapshot_coverage = str(
                    message.get("position_monitoring_initial_snapshot_coverage")
                    or "0/0"
                )
                subscription_failed = list(message.get("subscription_failed_symbols") or [])
                trading_subscription_failed = list(message.get("trading_subscription_failed_symbols") or [])
                position_monitoring_subscribed = list(
                    message.get("position_monitoring_subscribed_symbols") or []
                )
                position_monitoring_failed = list(
                    message.get("position_monitoring_failed_symbols") or []
                )
                market_data_mode = str(
                    message.get("market_data_mode")
                    or configured_market_data_mode(config)
                )
                market_data_symbols = {
                    str(value)
                    for value in (
                        message.get("market_data_symbols")
                        or message.get("subscribed_symbols")
                        or []
                    )
                }
                market_data_failed = list(
                    message.get("market_data_failed_symbols") or []
                )
                trading_market_data_failed = list(
                    message.get("trading_market_data_failed_symbols") or []
                )
                daily_failed = list(message.get("daily_context_failed_symbols") or [])
                partial_bar_suppressed_until = str(message.get("partial_bar_suppressed_until") or "")
                worker_ready = quote_subscription_ready(
                    trading_market_data_failed,
                    trading_subscription_failed,
                    daily_failed,
                )
                if not worker_ready:
                    return halt_market_data(
                        "market_data_subscription_incomplete",
                        details={
                            "subscription_failed_symbols": subscription_failed,
                            "trading_subscription_failed_symbols": (
                                trading_subscription_failed
                            ),
                            "daily_context_failed_symbols": daily_failed,
                        },
                    )
                account.resume_background_refresh()
                last_subscription_failure_reason = ""
                worker_last_progress = time.monotonic()
                worker_ready_since = worker_last_progress
            elif kind == "daily_context":
                rows = list(message.get("rows") or [])
                daily_context_cache_reused = (
                    str(message.get("source_mode") or "")
                    == "official_sdk_daily_context_cache"
                )
                daily_failed = [
                    str(value) for value in (message.get("failures") or [])
                ]
                daily_rows = rows
                intraday_rows = [
                    row
                    for row in context.rows()
                    if str(row.get("timeframe") or "") != "1d"
                ]
                context = MarketEventContext(
                    maximum_rows=(
                        len(configured_trading_symbols(config))
                        * config.daily_context_bars
                    )
                    + 4096
                )
                context.append(trading_market_events(config, daily_rows))
                context.append(intraday_rows)
                daily_context_state = (
                    "complete"
                    if daily_context_is_complete(
                        config,
                        "complete",
                        len(daily_rows),
                        daily_failed,
                    )
                    else "failed"
                )
                if daily_context_state != "complete":
                    return halt_market_data(
                        "official_daily_context_incomplete",
                        details={
                            "row_count": len(daily_rows),
                            "failed_symbols": daily_failed,
                        },
                    )
                write_daily_context_cache(config.daily_context_path, daily_rows)
                daily_context_persisted = True
            elif kind == "bars" and worker_ready:
                # Quotes arrive one symbol at a time at a bar boundary.  Give
                # the queue a very short coalescing window, then evaluate all
                # just-closed bars together once instead of rerunning every
                # strategy for each of the 147 symbols.
                rows = list(message.get("rows") or [])
                time.sleep(0.15)
                while True:
                    try:
                        queued = message_queue.get_nowait()
                    except queue.Empty:
                        break
                    if str(queued.get("kind") or "") == "bars":
                        rows.extend(list(queued.get("rows") or []))
                    else:
                        deferred_messages.append(queued)
                started = time.perf_counter()
                trading_daily_context_ready = daily_context_covers_symbols(
                    config, daily_rows, configured_trading_symbols(config), daily_failed
                )
                active_client = (
                    paper_client
                    or (
                        flatten_client
                        if dispatch_requested and config.paper_order_dispatch_enabled
                        else None
                    )
                ) if trading_daily_context_ready else None
                if position_monitoring_failed:
                    active_client = (
                        flatten_client
                        if dispatch_requested and config.paper_order_dispatch_enabled
                        else None
                    )
                boundary_complete = realtime_boundary_is_complete(
                    rows,
                    configured_trading_symbols(config),
                )
                expected_boundary_symbols = {
                    symbol.upper().removesuffix(".US")
                    for symbol in configured_trading_symbols(config)
                }
                actual_boundary_symbols = {
                    str(row.get("symbol") or "").upper().removesuffix(".US")
                    for row in rows
                    if row.get("symbol")
                }
                boundary_name = str((rows or [{}])[0].get("event_time") or "")
                last_boundary_missing_symbols = sorted(
                    expected_boundary_symbols - actual_boundary_symbols
                )
                reference_fresh_for_boundary = not active_reference_quotes_are_stale(
                    last_push_by_symbol,
                    now_monotonic=time.monotonic(),
                    maximum_silence_seconds=config.active_symbol_silence_seconds,
                )
                trustworthy_boundary = realtime_boundary_is_trustworthy(
                    boundary_complete=boundary_complete,
                    reference_quotes_fresh=reference_fresh_for_boundary,
                )
                boundary_integrity_state = realtime_boundary_integrity_state(
                    boundary_complete=boundary_complete,
                    reference_quotes_fresh=reference_fresh_for_boundary,
                )
                if trustworthy_boundary:
                    complete_boundary_count += 1
                    last_complete_boundary = boundary_name
                else:
                    incomplete_boundary_count += 1
                    last_incomplete_boundary = boundary_name
                    if boundary_integrity_state == "reference_quotes_stale":
                        reference_stale_boundary_count += 1
                    else:
                        structural_incomplete_boundary_count += 1
                        if rows and not last_boundary_missing_symbols:
                            late_boundary_count += 1
                    return halt_market_data(
                        "realtime_bar_boundary_untrustworthy",
                        details={
                            "boundary": boundary_name,
                            "integrity_state": boundary_integrity_state,
                            "missing_symbols": last_boundary_missing_symbols,
                            "reference_quotes_fresh": reference_fresh_for_boundary,
                        },
                    )
                realtime_tradable_bar_count += sum(
                    not bool(row.get("market_data_blocked_reason"))
                    and str(row.get("symbol") or "").upper().removesuffix(".US")
                    in expected_boundary_symbols
                    for row in rows
                )
                no_trade_carry_forward_count += sum(
                    "no_trade_carry_forward"
                    in str(row.get("market_data_blocked_reason") or "")
                    and str(row.get("symbol") or "").upper().removesuffix(".US")
                    in expected_boundary_symbols
                    for row in rows
                )
                active_client = boundary_execution_client(
                    candidate_client=active_client,
                    boundary_complete=boundary_complete,
                    trustworthy_boundary=trustworthy_boundary,
                )
                if not market_data_mode_qualifies_for_subscription_gate(
                    market_data_mode
                ):
                    active_client = None
                last_result = dispatch_completed_rows(
                    config,
                    rows,
                    context,
                    account,
                    active_client,
                    position_market_context=position_context,
                    daily_context_rows=daily_rows,
                    live_quote_session_state=live_quote_session_state,
                    signal_event_cache=signal_event_cache,
                    signal_id_cache=signal_id_cache,
                    execution_ledger_cache=execution_ledger_cache,
                    fill_attribution_state_cache=fill_attribution_state_cache,
                    new_entry_submission_enabled=(
                        paper_client is not None
                        and not position_monitoring_failed
                    ),
                )
                current_market_date = (
                    datetime.now(NEW_YORK).date().isoformat()
                )
                execution_ledger_cache[:] = compact_hot_execution_rows(
                    execution_ledger_cache,
                    market_date=current_market_date,
                )
                signal_event_cache[:] = compact_hot_signal_rows(
                    signal_event_cache,
                    execution_ledger_cache,
                    market_date=current_market_date,
                )
                if paper_client is not None and paper_client.trade_context_refresh_required:
                    refresh_started_at = datetime.now(UTC)
                    refresh_reason = paper_client.trade_context_refresh_reason
                    try:
                        (
                            execution_trade,
                            candidate_paper_client,
                            flatten_client,
                        ) = build_sdk_trade_clients(
                            config,
                            sdk,
                            execution_request_gate,
                            account.note_submission,
                            dispatch_enabled=True,
                        )
                        candidate_health = candidate_paper_client.healthcheck()
                        if not bool(candidate_health.get("ok")):
                            raise RuntimeError(
                                str(
                                    candidate_health.get("error")
                                    or candidate_health.get("status")
                                )
                            )
                        paper_client = candidate_paper_client
                        trade_context_health = {
                            **candidate_health,
                            "status": "trade_context_rebuilt_and_healthy",
                            "refresh_reason": refresh_reason,
                            "refreshed_at": to_iso(datetime.now(UTC)),
                        }
                        last_trade_context_healthcheck = time.monotonic()
                        next_trade_context_retry = 0.0
                        last_result["trade_context_refresh"] = {
                            "status": "refreshed_for_next_realtime_signal",
                            "reason": refresh_reason,
                            "refreshed_at": to_iso(datetime.now(UTC)),
                            "old_signal_replayed": False,
                        }
                    except Exception as exc:
                        paper_client = None
                        trade_context_health = {
                            "ok": False,
                            "status": "trade_context_rebuild_failed",
                            "refresh_reason": refresh_reason,
                            "error": str(exc)[:500],
                            "attempted_at": to_iso(refresh_started_at),
                        }
                        next_trade_context_retry = (
                            time.monotonic() + TRADE_CONTEXT_RETRY_SECONDS
                        )
                        last_result["trade_context_refresh"] = {
                            "status": "failed_new_entries_disabled",
                            "reason": refresh_reason,
                            "refresh_error": str(exc)[:500],
                            "attempted_at": to_iso(refresh_started_at),
                            "old_signal_replayed": False,
                        }
                elapsed = int((time.perf_counter() - started) * 1000)
                last_result["pipeline_elapsed_ms"] = elapsed
                pipeline_latency_samples.append(elapsed)
                expected_symbols = set(
                    quote_subscription_targets(config, datetime.now(UTC))
                )
                batch_symbols = {
                    f"{str(row.get('symbol') or '').upper().replace('.US', '')}.US"
                    for row in rows
                    if str(row.get("symbol") or "")
                }
                last_result["bar_batch_symbol_count"] = len(batch_symbols)
                last_result["bar_batch_expected_symbol_count"] = len(expected_symbols)
                last_result["bar_batch_missing_symbols"] = sorted(expected_symbols - batch_symbols)
                last_event_at = str((rows or [{}])[-1].get("received_at") or last_event_at)
            elif kind == "heartbeat":
                apply_transport_heartbeat_message(message)
            elif kind == "error":
                return halt_market_data(
                    str(message.get("reason") or "market_data_worker_failed"),
                    details={
                        "worker_message": message,
                    },
                )
            if time.monotonic() - last_compaction >= 60:
                compact_market_events(config.market_events_path, config.event_keep_lines)
                last_compaction = time.monotonic()
            maintenance_now = datetime.now(UTC)
            near_five_minute_boundary = (
                maintenance_now.minute % 5 == 0
                and maintenance_now.second <= 2
            )
            monotonic_now = time.monotonic()
            healthcheck_due = (
                dispatch_enabled
                and not near_five_minute_boundary
                and (
                    paper_client is None
                    or monotonic_now - last_trade_context_healthcheck
                    >= TRADE_CONTEXT_HEALTHCHECK_INTERVAL_SECONDS
                )
                and monotonic_now >= next_trade_context_retry
            )
            if healthcheck_due:
                if paper_client is not None:
                    trade_context_health = paper_client.healthcheck()
                else:
                    trade_context_health = {
                        "ok": False,
                        "status": "trade_context_missing",
                        "trade_context_refresh_required": True,
                    }
                last_trade_context_healthcheck = monotonic_now
                if not bool(trade_context_health.get("ok")):
                    refresh_reason = str(
                        trade_context_health.get("error")
                        or trade_context_health.get("status")
                        or "trade_context_healthcheck_failed"
                    )
                    if not trade_context_health_requires_rebuild(
                        trade_context_health
                    ):
                        trade_context_health = {
                            **trade_context_health,
                            "ok": False,
                            "status": "trade_context_transient_healthcheck_failed",
                            "retry_after_seconds": TRADE_CONTEXT_RETRY_SECONDS,
                        }
                        # Keep the existing context, stop dispatch briefly, and
                        # retry the harmless read without creating more SDK
                        # contexts during a broker rate-limit window.
                        last_trade_context_healthcheck = (
                            monotonic_now
                            - TRADE_CONTEXT_HEALTHCHECK_INTERVAL_SECONDS
                        )
                        next_trade_context_retry = (
                            monotonic_now + TRADE_CONTEXT_RETRY_SECONDS
                        )
                        continue
                    try:
                        (
                            candidate_trade,
                            candidate_paper_client,
                            candidate_flatten_client,
                        ) = build_sdk_trade_clients(
                            config,
                            sdk,
                            execution_request_gate,
                            account.note_submission,
                            dispatch_enabled=True,
                        )
                        candidate_health = candidate_paper_client.healthcheck()
                        if not bool(candidate_health.get("ok")):
                            raise RuntimeError(
                                str(
                                    candidate_health.get("error")
                                    or candidate_health.get("status")
                                )
                            )
                        execution_trade = candidate_trade
                        paper_client = candidate_paper_client
                        flatten_client = candidate_flatten_client
                        trade_context_health = {
                            **candidate_health,
                            "status": "trade_context_rebuilt_and_healthy",
                            "refresh_reason": refresh_reason,
                            "refreshed_at": to_iso(maintenance_now),
                        }
                        next_trade_context_retry = 0.0
                    except Exception as exc:
                        paper_client = None
                        trade_context_health = {
                            "ok": False,
                            "status": "trade_context_rebuild_failed",
                            "refresh_reason": refresh_reason,
                            "error": str(exc)[:500],
                            "attempted_at": to_iso(maintenance_now),
                        }
                        next_trade_context_retry = (
                            monotonic_now + TRADE_CONTEXT_RETRY_SECONDS
                        )
            if dispatch_enabled and bool(trade_context_health.get("ok")):
                flatten_transition = run_pending_flatten_cycle(
                    config,
                    account,
                    flatten_client,
                    context.rows(),
                    now=maintenance_now,
                )
            else:
                flatten_transition = {
                    "status": (
                        "blocked_trade_context_unhealthy"
                        if dispatch_enabled
                        else "disabled_without_paper_order_dispatch"
                    ),
                    "blocks_new_entries": True,
                }
            if (
                dispatch_enabled
                and paper_client is not None
                and not bool(flatten_transition.get("blocks_new_entries"))
            ):
                from scripts.m15_pa004_overcap_cleanup_lib import (
                    advance_cleanup_state,
                )

                migration_path = config.output_dir / CAPITAL_BUCKET_MIGRATION_FILE
                capital_bucket_migration = advance_cleanup_state(
                    read_json_object(migration_path),
                    account.snapshot(),
                    paper_client,
                    now=maintenance_now,
                    execution_ledger_path=(
                        hot_execution_config.output_dir / EXECUTION_LEDGER_FILE
                    ),
                )
                if capital_bucket_migration.get("status") != "inactive":
                    write_json_atomic(migration_path, capital_bucket_migration)
                authorized_account_exit = run_authorized_account_exit_cycle(
                    config,
                    account,
                    flatten_client,
                    now=maintenance_now,
                )
            flatten_blocks_new_entries = bool(flatten_transition.get("blocks_new_entries"))
            if (
                paper_client is not None
                and not flatten_blocks_new_entries
                and worker_ready
                and daily_context_state == "complete"
                and time.monotonic() - last_order_maintenance >= config.account_maintenance_interval_seconds
                and not near_five_minute_boundary
            ):
                order_maintenance = run_sdk_order_maintenance(
                    config,
                    paper_client,
                    account,
                    context.rows(),
                    now=maintenance_now,
                )
                last_order_maintenance = time.monotonic()
            snapshot = account.snapshot()
            (
                updated_position_monitoring_symbols,
                new_position_monitoring_symbols,
                position_monitoring_recovery_reason,
            ) = detect_position_monitoring_set_change(
                config,
                snapshot,
                position_monitoring_symbols,
            )
            if new_position_monitoring_symbols:
                return halt_market_data(
                    "position_monitoring_subscription_set_changed",
                    details={
                        "new_symbols": list(new_position_monitoring_symbols),
                        "requested_subscription_set": list(
                            updated_position_monitoring_symbols
                        ),
                        "reason": position_monitoring_recovery_reason,
                    },
                )
            age = account_age_seconds(snapshot)
            account_snapshot_ready = bool(
                age is not None
                and age <= config.maximum_account_snapshot_age_seconds
                and snapshot.get("paper_account_verified") is True
                and snapshot.get("positions_ok") is True
                and snapshot.get("orders_ok") is True
                and not snapshot.get("worker_circuit_open")
            )
            daily_context_ready = daily_context_is_complete(
                config, daily_context_state, len(daily_rows), daily_failed
            )
            trading_daily_context_ready = daily_context_covers_symbols(
                config, daily_rows, configured_trading_symbols(config), daily_failed
            )
            now_ny = datetime.now(NEW_YORK)
            session_date = now_ny.date().isoformat()
            is_after_regular_session = now_ny.weekday() < 5 and (now_ny.hour >= 16)
            expected_regular_boundaries = 78
            expected_regular_bars = (
                len(configured_trading_symbols(config)) * expected_regular_boundaries
            )
            realtime_session_acceptance_ready = bool(
                complete_boundary_count == expected_regular_boundaries
                and incomplete_boundary_count == 0
                and late_boundary_count == 0
                and realtime_tradable_bar_count + no_trade_carry_forward_count
                == expected_regular_bars
                and worker_generation == 1
                and int(summarize_latency_samples(list(pipeline_latency_samples)).get("p95_ms") or 0)
                <= 1000
            )
            if (
                config.complete_session_gate_enabled
                and is_after_regular_session
                and session_date not in observed_regular_sessions
                and worker_ready
                and daily_context_state == "complete"
                and not daily_failed
                and age is not None
                and age <= config.maximum_account_snapshot_age_seconds
                and last_event_at
                and realtime_session_acceptance_ready
            ):
                gate = record_readonly_session(config.readonly_gate_path, session_date, {
                    "subscription_coverage": (
                        f"{len(configured_symbols(config))}/{len(configured_symbols(config))}"
                    ),
                    "daily_context_row_count": len(daily_rows),
                    "last_event_at": last_event_at,
                    "account_snapshot_age_seconds": age,
                    "runtime_engine": "sdk",
                    "complete_boundary_count": complete_boundary_count,
                    "expected_boundary_count": expected_regular_boundaries,
                    "realtime_bar_count": realtime_tradable_bar_count + no_trade_carry_forward_count,
                    "expected_realtime_bar_count": expected_regular_bars,
                    "incomplete_boundary_count": incomplete_boundary_count,
                    "late_boundary_count": late_boundary_count,
                    "quote_worker_generation": worker_generation,
                }, required_complete_sessions=config.required_complete_sessions) if market_data_mode_qualifies_for_subscription_gate(
                    market_data_mode
                ) else {
                    "passed": False,
                    "completed_sessions": [],
                }
                complete_session_gate_passed_now = bool(gate.get("passed"))
                complete_sessions_passed = len(gate.get("completed_sessions", []))
                observed_regular_sessions.add(session_date)
                if (
                    dispatch_requested
                    and config.paper_order_dispatch_enabled
                    and complete_session_gate_passed_now
                    and deployment_ready
                    and paper_client is None
                ):
                    (
                        execution_trade,
                        paper_client,
                        flatten_client,
                    ) = build_sdk_trade_clients(
                        config,
                        sdk,
                        execution_request_gate,
                        account.note_submission,
                        dispatch_enabled=True,
                    )
                    trade_context_health = paper_client.healthcheck()
                    if not bool(trade_context_health.get("ok")):
                        paper_client = None
                        next_trade_context_retry = (
                            time.monotonic() + TRADE_CONTEXT_RETRY_SECONDS
                        )
                    dispatch_enabled = True
            latency_metrics = summarize_latency_samples(list(pipeline_latency_samples))
            expansion_symbol_count = (
                len(configured_symbols(config)) - len(configured_trading_symbols(config))
            )
            expansion_subscription_failed = sorted(
                set(subscription_failed) - set(trading_subscription_failed)
            )
            expansion_daily_ready = daily_context_ready
            expansion_p95_ms = int(latency_metrics.get("p95_ms") or 0)
            expansion_session_healthy = bool(
                expansion_symbol_count > 0
                and worker_ready
                and market_data_mode_qualifies_for_subscription_gate(
                    market_data_mode
                )
                and not subscription_failed
                and expansion_daily_ready
                and account_snapshot_ready
                and last_event_at
                and expansion_p95_ms <= 1000
            )
            if (
                is_after_regular_session
                and session_date not in observed_expansion_sessions
                and expansion_session_healthy
            ):
                expansion_gate = record_readonly_session(
                    expansion_gate_path,
                    session_date,
                    {
                        "subscription_coverage": (
                            f"{len(configured_symbols(config))}/{len(configured_symbols(config))}"
                        ),
                        "trading_symbol_count": len(configured_trading_symbols(config)),
                        "readonly_expansion_symbol_count": expansion_symbol_count,
                        "daily_context_row_count": len(daily_rows),
                        "last_event_at": last_event_at,
                        "account_snapshot_age_seconds": age,
                        "pipeline_p95_ms": expansion_p95_ms,
                        "runtime_engine": "sdk",
                    },
                    required_complete_sessions=1,
                )
                expansion_gate_passed = bool(expansion_gate.get("passed"))
                expansion_sessions_passed = len(expansion_gate.get("completed_sessions", []))
                observed_expansion_sessions.add(session_date)
            if expansion_symbol_count <= 0:
                expansion_gate_passed = False
                expansion_sessions_passed = 0
                expansion_acceptance_status = "not_enabled"
            elif expansion_gate_passed:
                expansion_acceptance_status = "accepted_readonly"
            elif subscription_failed:
                expansion_acceptance_status = "subscription_incomplete"
            elif not expansion_daily_ready:
                expansion_acceptance_status = "daily_context_incomplete"
            elif expansion_p95_ms > 1000:
                expansion_acceptance_status = "latency_above_target"
            else:
                expansion_acceptance_status = "readonly_observing"
            subscription_set_hash = hashlib.sha256(
                "\n".join(sorted(
                    market_data_symbols | set(position_monitoring_subscribed)
                )).encode("utf-8")
            ).hexdigest()
            resources = process_resource_snapshot()
            build_status(
                config,
                status="running" if worker_ready else "connecting",
                reason=(
                    ""
                    if worker_ready
                    else "waiting_for_official_sdk_subscription"
                ),
                connected=worker_ready,
                last_event_at=last_event_at,
                sdk_installed=True,
                oauth_client_id_present=True,
                pipeline_metrics=latency_metrics,
                subscription_failed_symbols=subscription_failed,
                extra={
                    "run_id": run_id, "runtime_pid": os.getpid(), "quote_worker_pid": worker.pid if worker else "",
                    "runtime_started_at": runtime_started_at,
                    "runtime_process_start_ticks": runtime_process_start_ticks,
                    "runtime_command_line": " ".join(sys.argv),
                    "quote_subscription_worker_count": 1 if worker is not None and worker.is_alive() else 0,
                    "last_subscription_failure_reason": last_subscription_failure_reason,
                    "subscription_progress": (
                        f"{subscription_progress_completed}/{subscription_progress_total}"
                    ),
                    "daily_context_progress": (
                        f"{daily_context_progress_completed}/{daily_context_progress_total}"
                    ),
                    "quote_worker_generation": worker_generation,
                    "market_data_mode": market_data_mode,
                    "market_data_transport": config.market_data_transport,
                    "account_order_transport": "official_sdk_persistent_context",
                    "source_mode": "official_sdk_push",
                    "automatic_market_data_retry_enabled": False,
                    "snapshot_fallback_enabled": False,
                    "market_data_transport_child_pid": transport_child_pid,
                    "market_data_transport_queue_depth": transport_queue_depth,
                    "market_data_transport_reader_errors": transport_reader_errors,
                    "market_data_transport_resources": transport_resources,
                    "market_data_coalesced_quote_pending_count": (
                        transport_coalesced_quote_pending_count
                    ),
                    "market_data_coalesced_quote_replacement_count": (
                        transport_coalesced_quote_replacement_count
                    ),
                    "market_data_raw_notification_count": (
                        transport_raw_notification_count
                    ),
                    "initial_snapshot_coverage": initial_snapshot_coverage,
                    "position_monitoring_initial_snapshot_coverage": (
                        position_monitoring_initial_snapshot_coverage
                    ),
                    "last_market_data_worker_error": last_market_data_worker_error,
                    "subscription_set_sha256": subscription_set_hash,
                    "last_push_at_by_symbol": dict(sorted(last_push_at_by_symbol.items())),
                    "reference_push_heartbeat": {
                        symbol: last_push_at_by_symbol.get(symbol, "")
                        for symbol in ("SPY.US", "QQQ.US")
                    },
                    "reference_market_activity": {
                        symbol: {
                            "at": last_push_at_by_symbol.get(symbol, ""),
                            "source": last_push_source_by_symbol.get(symbol, ""),
                        }
                        for symbol in ("SPY.US", "QQQ.US")
                    },
                    "complete_boundary_count": complete_boundary_count,
                    "incomplete_boundary_count": incomplete_boundary_count,
                    "reference_stale_boundary_count": (
                        reference_stale_boundary_count
                    ),
                    "structural_incomplete_boundary_count": (
                        structural_incomplete_boundary_count
                    ),
                    "late_boundary_count": late_boundary_count,
                    "last_complete_boundary": last_complete_boundary,
                    "last_incomplete_boundary": last_incomplete_boundary,
                    "last_boundary_missing_symbols": last_boundary_missing_symbols,
                    "realtime_tradable_bar_count": realtime_tradable_bar_count,
                    "no_trade_carry_forward_count": no_trade_carry_forward_count,
                    "postclose_repair_bar_count": 0,
                    "realtime_order_evidence_only": True,
                    "realtime_session_acceptance_ready": realtime_session_acceptance_ready,
                    "expected_regular_boundary_count": expected_regular_boundaries,
                    "expected_regular_bar_count": expected_regular_bars,
                    **resources,
                    "orphaned_runtime_children_cleaned": orphaned_runtime_children_cleaned,
                    "config_fingerprint": loaded_config_fingerprint,
                    "deployment_manifest_verified": deployment_ready,
                    "deployment_manifest_issues": list(deployment.get("issues") or []),
                    "deployment_branch": str(deployment.get("branch") or ""),
                    "deployment_commit": str(deployment.get("head_sha") or ""),
                    "deployment_worktree_clean": bool(deployment.get("worktree_clean")),
                    "subscription_symbol_count": len(configured_symbols(config)),
                    "subscription_coverage": f"{len(configured_symbols(config)) - len(subscription_failed) if worker_ready else 0}/{len(configured_symbols(config))}",
                    "trading_symbol_count": len(configured_trading_symbols(config)),
                    "trading_subscription_coverage": (
                        f"{len(configured_trading_symbols(config)) - len(trading_subscription_failed) if worker_ready and market_data_mode_qualifies_for_subscription_gate(market_data_mode) else 0}"
                        f"/{len(configured_trading_symbols(config))}"
                    ),
                    "market_data_coverage": (
                        f"{len(market_data_symbols)}/{len(quote_subscription_targets(config, datetime.now(UTC)))}"
                        if worker_ready
                        else f"0/{len(quote_subscription_targets(config, datetime.now(UTC)))}"
                    ),
                    "trading_market_data_coverage": (
                        f"{len(set(configured_trading_symbols(config)) & market_data_symbols)}"
                        f"/{len(configured_trading_symbols(config))}"
                        if worker_ready
                        else f"0/{len(configured_trading_symbols(config))}"
                    ),
                    "position_monitoring_symbols": list(position_monitoring_symbols),
                    "position_monitoring_symbol_count": len(position_monitoring_symbols),
                    "position_monitoring_subscription_coverage": (
                        f"{len(position_monitoring_subscribed)}"
                        f"/{len(position_monitoring_symbols)}"
                    ),
                    "position_monitoring_failed_symbols": position_monitoring_failed,
                    "position_monitoring_new_entries_allowed": False,
                    "position_monitoring_exit_only": True,
                    "market_data_failed_symbols": market_data_failed,
                    "trading_market_data_failed_symbols": trading_market_data_failed,
                    "readonly_expansion_symbol_count": expansion_symbol_count,
                    "readonly_expansion_subscription_coverage": (
                        f"{max(0, expansion_symbol_count - len(expansion_subscription_failed))}"
                        f"/{expansion_symbol_count}"
                    ),
                    "readonly_expansion_failed_symbols": expansion_subscription_failed,
                    "readonly_expansion_daily_context_ready": expansion_daily_ready,
                    "readonly_expansion_acceptance_status": expansion_acceptance_status,
                    "readonly_expansion_gate_path": str(expansion_gate_path),
                    "readonly_expansion_sessions_passed": expansion_sessions_passed,
                    "readonly_expansion_sessions_required": expansion_sessions_required,
                    "readonly_expansion_gate_passed": expansion_gate_passed,
                    "daily_context_row_count": len(daily_rows), "daily_context_failed_symbols": daily_failed,
                    "daily_context_state": daily_context_state,
                    "trading_daily_context_ready": trading_daily_context_ready,
                    "trading_daily_context_row_count": daily_context_row_count_for_symbols(
                        config, daily_rows, configured_trading_symbols(config)
                    ),
                    "trading_daily_context_expected_row_count": (
                        len(configured_trading_symbols(config)) * config.daily_context_bars
                    ),
                    "daily_context_cache_reused": daily_context_cache_reused,
                    "intraday_context_cache_reused": bool(cached_intraday_rows),
                    "intraday_context_row_count": len(cached_intraday_rows),
                    "partial_bar_suppressed_until": partial_bar_suppressed_until,
                    "daily_context_worker_pids": [],
                    "account_snapshot_age_seconds": age,
                    "account_snapshot_healthy": account_snapshot_ready,
                    "account_snapshot_worker_pid": snapshot.get("worker_pid"),
                    "account_snapshot_worker_generation": snapshot.get("worker_generation"),
                    "account_snapshot_worker_status": snapshot.get("worker_refresh_status"),
                    "account_snapshot_worker_elapsed_seconds": snapshot.get("worker_refresh_elapsed_seconds"),
                    "account_snapshot_worker_restart_count": snapshot.get("worker_restart_count"),
                    "account_snapshot_worker_timeout_count": snapshot.get("worker_consecutive_timeouts"),
                    "account_snapshot_circuit_open": bool(snapshot.get("worker_circuit_open")),
                    "account_snapshot_background_refresh_enabled": (
                        account.background_refresh_enabled
                    ),
                    "reference_market_data_state": reference_market_data_state,
                    "dispatch_enabled": effective_runtime_dispatch_enabled(
                        dispatch_requested=dispatch_enabled,
                        paper_client_ready=paper_client is not None,
                        trade_context_ready=bool(trade_context_health.get("ok")),
                        market_data_ready=(
                            worker_ready
                            and reference_market_data_state == "healthy"
                        ),
                        trading_daily_context_ready=trading_daily_context_ready,
                        flatten_blocks_new_entries=flatten_blocks_new_entries,
                        account_snapshot_ready=account_snapshot_ready,
                        deployment_ready=deployment_ready,
                        position_monitoring_ready=not position_monitoring_failed,
                    ),
                    "dispatch_requested": dispatch_requested,
                    "trade_context_health": trade_context_health,
                    "dispatch_block_reason": runtime_dispatch_block_reason(
                        paper_order_dispatch_enabled=config.paper_order_dispatch_enabled,
                        complete_session_gate_blocked=(
                            config.complete_session_gate_enabled
                            and not complete_session_gate_passed_now
                        ),
                        paper_client_ready=paper_client is not None,
                        trade_context_ready=bool(trade_context_health.get("ok")),
                        market_data_ready=(
                            worker_ready
                            and reference_market_data_state == "healthy"
                        ),
                        flatten_blocks_new_entries=flatten_blocks_new_entries,
                        account_snapshot_ready=account_snapshot_ready,
                        trading_daily_context_ready=trading_daily_context_ready,
                        deployment_ready=deployment_ready,
                        position_monitoring_ready=not position_monitoring_failed,
                        reference_market_data_stale=(
                            reference_market_data_state != "healthy"
                        ),
                    ),
                    "complete_session_gate_enabled": (
                        config.complete_session_gate_enabled
                    ),
                    "complete_session_gate_path": str(config.readonly_gate_path),
                    "complete_sessions_passed": complete_sessions_passed,
                    "complete_sessions_required": complete_sessions_required,
                    "complete_session_gate_passed": (
                        complete_session_gate_passed_now
                    ),
                    "pipeline_latency_samples_ms": list(pipeline_latency_samples),
                    "hot_state": {
                        "signal_id_count": len(signal_id_cache),
                        "signal_row_count": len(signal_event_cache),
                        "execution_row_count": len(execution_ledger_cache),
                        "fill_attribution_cached": bool(
                            fill_attribution_state_cache
                        ),
                    },
                    "last_hot_pipeline": last_result,
                    "order_maintenance": order_maintenance,
                    "sdk_auto_flatten": flatten_transition,
                    "authorized_account_exit": authorized_account_exit,
                    "capital_bucket_migration": capital_bucket_migration,
                    "formal_test_transition": load_formal_test_marker(config),
                },
            )
    except KeyboardInterrupt:
        return 0
    finally:
        stop_event.set()
        stop_spawned_process(worker, graceful=True)
        close_spawn_queue(message_queue)
        account.stop()
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
        if read_pid(pid_path(config)) == os.getpid():
            pid_path(config).unlink(missing_ok=True)
        run_lock.seek(0)
        run_lock.truncate()
        run_lock.flush()
        fcntl.flock(run_lock.fileno(), fcntl.LOCK_UN)
        run_lock.close()


def pid_path(config: Any) -> Path:
    return config.output_dir / PID_FILE


def read_pid(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
        return value if value > 0 else None
    except (OSError, ValueError):
        return None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def process_start_ticks(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21]
    except (OSError, IndexError):
        return ""


def runtime_status_process_matches(pid: int, payload: dict[str, Any]) -> bool:
    return bool(
        pid > 0
        and process_alive(pid)
        and is_expected_sdk_runtime_process(pid)
        and str(payload.get("runtime_pid") or "") == str(pid)
        and str(payload.get("runtime_process_start_ticks") or "")
        == process_start_ticks(pid)
        and str(payload.get("config_fingerprint") or "")
    )


def is_orphaned_sdk_runtime_child(
    command: str,
    stdout_path: str,
    parent_command: str,
    expected_log_path: Path,
) -> bool:
    return bool(
        (
            "multiprocessing.spawn" in command
            or "multiprocessing.resource_tracker" in command
        )
        and Path(stdout_path).resolve() == expected_log_path.resolve()
        and "run_m15_longbridge_sdk_runtime.py" not in parent_command
    )


def cleanup_orphaned_sdk_runtime_children(config: Any) -> list[int]:
    """Remove only detached multiprocessing children from an old SDK runtime."""
    cleaned: list[int] = []
    expected_log_path = config.output_dir / LOG_FILE
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        try:
            command = (entry / "cmdline").read_text(
                encoding="utf-8", errors="ignore"
            ).replace("\x00", " ")
            stdout_path = os.readlink(entry / "fd" / "1")
            status_lines = (entry / "status").read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()
            parent_pid = int(
                next(
                    line.split(":", 1)[1].strip()
                    for line in status_lines
                    if line.startswith("PPid:")
                )
            )
            parent_command = Path(f"/proc/{parent_pid}/cmdline").read_text(
                encoding="utf-8", errors="ignore"
            ).replace("\x00", " ")
        except (OSError, StopIteration, ValueError):
            continue
        if not is_orphaned_sdk_runtime_child(
            command,
            stdout_path,
            parent_command,
            expected_log_path,
        ):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            cleaned.append(pid)
        except ProcessLookupError:
            continue
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and any(process_alive(pid) for pid in cleaned):
        time.sleep(0.05)
    for pid in cleaned:
        if process_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return cleaned


def start_runtime_daemon(args: argparse.Namespace, config: Any) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    GLOBAL_RUNTIME_START_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with GLOBAL_RUNTIME_START_LOCK.open("a+", encoding="utf-8") as start_lock:
        fcntl.flock(start_lock.fileno(), fcntl.LOCK_EX)
        global_owner = read_pid(GLOBAL_QUOTE_SUBSCRIPTION_LOCK)
        local_owner = read_pid(config.output_dir / RUN_LOCK_FILE)
        lock_owner = global_owner or local_owner
        existing = lock_owner if lock_owner and process_alive(lock_owner) else read_pid(pid_path(config))
        status = _read_runtime_status(config)
        expected_fingerprint = config_fingerprint(config)
        terminal_same_build = bool(
            str(status.get("config_fingerprint") or "") == expected_fingerprint
            and runtime_requires_health_replacement(status, config)
        )
        if terminal_same_build:
            raise RuntimeError(
                "m15_runtime_fault_latched_manual_diagnosis_required"
            )
        if existing and process_alive(existing):
            if not is_expected_sdk_runtime_process(existing):
                raise RuntimeError("sdk_runtime_pid_is_not_expected_process")
            if global_owner and global_owner == existing and not (
                read_pid(pid_path(config)) == existing
                or str(existing) == str(
                    _read_runtime_status(config).get("runtime_pid") or ""
                )
            ):
                print(
                    "SDK 实时运行层已有另一个配置持有全局单实例锁，"
                    f"PID={existing}；本次未启动第二个进程。"
                )
                return 0
            pid_path(config).write_text(f"{existing}\n", encoding="utf-8")
            same_invocation = bool(status.get("dispatch_requested", False)) == bool(args.dispatch)
            if (
                str(status.get("config_fingerprint") or "") == expected_fingerprint
                and same_invocation
                and runtime_status_process_matches(existing, status)
            ):
                print(f"SDK 实时运行层已在运行，PID={existing}")
                return 0
            if not request_runtime_shutdown(existing):
                raise RuntimeError("sdk_runtime_shutdown_escalation_failed")
            pid_path(config).unlink(missing_ok=True)
        command = [sys.executable, str(Path(__file__).resolve()), "--watch", "--config", str(args.config)]
        if args.dispatch:
            command.append("--dispatch")
        with (config.output_dir / LOG_FILE).open("a", encoding="utf-8") as handle:
            process = subprocess.Popen(command, cwd=str(ROOT), stdout=handle, stderr=handle, start_new_session=True)
        pid_path(config).write_text(f"{process.pid}\n", encoding="utf-8")
        print(f"SDK 实时运行层已启动，PID={process.pid}")
    return 0


def _read_runtime_status(config: Any) -> dict[str, Any]:
    try:
        payload = json.loads(config.runtime_status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def mark_runtime_operator_stopped(config: Any) -> dict[str, Any]:
    payload = _read_runtime_status(config)
    payload.update(
        {
            "generated_at": to_iso(datetime.now(UTC)),
            "status": "operator_stopped",
            "reason": "operator_requested_stop",
            "sdk_connected": False,
            "runtime_process_alive": False,
            "runtime_pid": "",
            "dispatch_enabled": False,
            "dispatch_requested": False,
            "config_fingerprint": config_fingerprint(config),
        }
    )
    config.runtime_status_path.parent.mkdir(parents=True, exist_ok=True)
    config.runtime_status_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if args.status:
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(config.runtime_status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        pid = read_pid(pid_path(config))
        alive = bool(pid and runtime_status_process_matches(pid, payload))
        payload.update({
            "runtime_process_alive": alive,
            "runtime_pid": pid or "",
            "expected_config_fingerprint": config_fingerprint(config),
        })
        if not alive:
            if pid and not process_alive(pid):
                pid_path(config).unlink(missing_ok=True)
            payload.update({
                "status": "stopped",
                "sdk_connected": False,
                "dispatch_enabled": False,
                "reason": "runtime_process_not_alive",
            })
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.stop:
        pid = read_pid(pid_path(config))
        if pid and process_alive(pid):
            if not request_runtime_shutdown(pid):
                print("SDK 实时运行层未能在安全超时内停止", file=sys.stderr)
                return 2
        pid_path(config).unlink(missing_ok=True)
        mark_runtime_operator_stopped(config)
        return 0
    try:
        validate_market_data_transport_runtime(config)
        require_sdk_contract()
        read_client_id(config)
    except Exception as exc:
        build_status(config, status="blocked_sdk_prerequisite", reason=str(exc), sdk_installed=False, oauth_client_id_present=False)
        print(f"SDK runtime blocked: {exc}")
        return 2
    if args.check:
        try:
            preflight = run_sdk_preflight(config)
        except Exception as exc:
            preflight = {"errors": [f"sdk_preflight_failed:{type(exc).__name__}:{exc}"]}
        preflight["generated_at"] = to_iso(datetime.now(UTC))
        preflight["stage"] = "M15.longbridge_sdk_endpoint_preflight"
        preflight_path = config.output_dir / "m15_sdk_endpoint_preflight.json"
        preflight_path.parent.mkdir(parents=True, exist_ok=True)
        preflight_path.write_text(json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if preflight.get("errors"):
            print(json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True))
            return 2
        print(json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.daemon:
        return start_runtime_daemon(args, config)
    return run_watch(config, dispatch_requested=args.dispatch)


if __name__ == "__main__":
    raise SystemExit(main())
