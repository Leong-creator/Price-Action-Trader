#!/usr/bin/env python3
"""Persistent, SDK-only M15 paper runtime.

The quote connection lives in a child process because a native SDK subscribe
call may block indefinitely.  Quote callbacks only aggregate bars and send
completed bars to the parent; the parent owns routing, risk and paper orders.
"""
from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import multiprocessing as mp
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import partial
from importlib.metadata import PackageNotFoundError, version as package_version
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
from scripts.m15_longbridge_sdk_runtime_lib import (
    DEFAULT_CONFIG_PATH, QUOTE_SNAPSHOT_JSON, ConfirmedBoundaryBatchGate, ConfirmedCandlestickBarBuilder, FiveMinuteBarBuilder, MarketEventContext, SdkRealtimePaperClient,
    append_market_events, attach_next_bar_first_quotes, build_status, compact_market_events, config_fingerprint, configured_symbols,
    configured_trading_symbols, daily_context_covers_symbols, daily_context_is_complete,
    daily_context_row_count_for_symbols, floor_bar_open, fresh_market_events, load_config,
    load_valid_daily_context_cache, read_client_id,
    load_current_sdk_intraday_context, load_formal_test_marker, readonly_gate_passed, record_readonly_session,
    symbols_missing_contiguous_intraday_context,
    market_event_is_tradable, trading_market_events,
    sdk_config_from_oauth, sdk_object_to_dict, sdk_order_maintenance_actions, summarize_latency_samples, write_daily_context_cache,
    subscribe_quote_and_trades, to_iso, five_minute_session_coverage,
    unix_to_utc, warm_quote_context,
)
from scripts.m15_sdk_validation_flatten_lib import (
    activate_formal_epoch_payload,
    build_flatten_plan,
    flatten_confirmation,
    in_regular_session,
    latest_flatten_prices,
    market_date,
    runtime_flatten_order_payload,
    runtime_flatten_retry_order_payload,
)
from scripts.prepare_m15_sdk_dns_override import (
    DEFAULT_CACHE_DIR as SDK_DNS_OVERRIDE_CACHE_DIR,
    DEFAULT_ENV_FILE as SDK_DNS_OVERRIDE_ENV_FILE,
    environment_without_m15_dns_override,
    prepare as prepare_sdk_dns_override,
    process_local_environment,
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
LEGACY_CLI_PID_FILE = "m15_longbridge_realtime_session_supervisor.pid"
EXECUTION_LEDGER_FILE = "m15_longbridge_realtime_execution_ledger.jsonl"
ORDER_MAINTENANCE_FILE = "m15_sdk_order_maintenance.json"
MARKET_DATA_HEALTH_JSON = "m15_sdk_market_data_health.json"
MARKET_DATA_HEALTH_LEDGER_JSONL = "m15_sdk_market_data_health_ledger.jsonl"
POSTCLOSE_RECOVERY_STATE_JSON = "m15_sdk_postclose_recovery_state.json"
PENDING_RUNTIME_RELOAD_JSON = "m15_sdk_pending_runtime_reload.json"
AUTHORIZED_ACCOUNT_EXIT_FILE = "m15_authorized_account_exit.json"
CAPITAL_BUCKET_MIGRATION_FILE = "m15_capital_bucket_migration_state.json"
REALTIME_ACCOUNT_STATE_FILE = "m15_longbridge_realtime_account_state.json"
TRADE_CONTEXT_HEALTHCHECK_INTERVAL_SECONDS = 60
TRADE_CONTEXT_RETRY_SECONDS = 5
SNAPSHOT_FALLBACK_HANDOFF_COOLDOWN_SECONDS = 30
INTRADAY_CONTEXT_BACKFILL_TOTAL_DEADLINE_SECONDS = 300
POSTCLOSE_INTRADAY_RECOVERY_DEADLINE_SECONDS = 120
HISTORICAL_CANDLESTICK_REQUEST_INTERVAL_SECONDS = 0.60
MINIMUM_LONGBRIDGE_SDK_VERSION = (4, 5, 0)
PATCHED_LONGBRIDGE_SDK_MARKER = (
    ROOT / ".venv" / ".m15-longbridge-sdk-no-first-push.json"
)
PATCHED_LONGBRIDGE_SDK_PATCH = (
    ROOT / "patches" / "longbridge-4.5.0-disable-subscribe-first-push.patch"
)
PATCHED_LONGBRIDGE_SDK_COMMIT = "266d9230c05208e2b9b6f0e1ebba7eb34fc7e8a2"
REALTIME_INTRADAY_HISTORY_BACKFILL_ENABLED = False
RUNTIME_LOG_ROTATE_BYTES = 10 * 1024 * 1024
RUNTIME_SOURCE_FILES = (
    Path(__file__).resolve(),
    ROOT / "scripts" / "m15_longbridge_sdk_runtime_lib.py",
    ROOT / "scripts" / "m15_longbridge_sdk_account_lib.py",
    ROOT / "scripts" / "m15_longbridge_realtime_signal_router_lib.py",
    ROOT / "scripts" / "m15_longbridge_realtime_execution_lib.py",
    ROOT / "scripts" / "m15_longbridge_realtime_position_manager_lib.py",
)


def runtime_source_fingerprint() -> str:
    """Fingerprint the code actually loaded by a newly started runtime."""
    digest = hashlib.sha256()
    for path in RUNTIME_SOURCE_FILES:
        digest.update(str(path.relative_to(ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


LOADED_RUNTIME_SOURCE_FINGERPRINT = runtime_source_fingerprint()


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


def runtime_deployment_is_frozen(now: datetime | None = None) -> bool:
    """Keep a healthy loaded runtime stable through the full US session."""
    observed = (now or datetime.now(UTC)).astimezone(NEW_YORK)
    if observed.weekday() >= 5:
        return False
    minutes = observed.hour * 60 + observed.minute
    return (9 * 60 + 25) <= minutes <= (16 * 60 + 5)


def pending_flatten_test_epoch_id(marker: dict[str, Any]) -> str:
    """Keep validation cleanup outside the next formal performance epoch."""
    if (
        str(marker.get("activation_blocker") or "")
        == "validation_session_ended_account_flatten_required"
        and str(marker.get("last_validation_test_epoch_id") or "")
    ):
        return str(marker["last_validation_test_epoch_id"])
    return str(marker.get("test_epoch_id") or "")


def append_account_flatten_submission_audit(
    config: Any,
    payload: dict[str, Any],
    response: dict[str, Any],
    *,
    now: datetime,
) -> None:
    order_id = str(response.get("order_id") or "")
    if not order_id:
        return
    row = {
        "stage": "M15.sdk_runtime_auto_flatten",
        "created_at": to_iso(now),
        "processed_at": to_iso(now),
        "submitted_at": to_iso(now),
        "submission_status": "submitted",
        "execute_orders": True,
        "paper_trading_approval": True,
        "account_flatten_allocation": True,
        "market_exit_no_reprice": True,
        "exit_only_position_signal": True,
        "order_id": order_id,
        "broker_order_id": order_id,
        "longbridge_order_id": order_id,
        "signal_id": str(payload.get("signal_id") or ""),
        "client_request_id": str(payload.get("client_request_id") or ""),
        "runtime_id": "M15-LONGBRIDGE-SDK-AUTO-FLATTEN",
        "strategy_id": "M15-LONGBRIDGE-SDK-AUTO-FLATTEN",
        "capital_bucket": "account_validation_flatten",
        "test_epoch_id": str(payload.get("test_epoch_id") or ""),
        "symbol": str(payload.get("symbol") or "").upper().replace(".US", ""),
        "side": str(payload.get("side") or "").lower(),
        "direction": str(payload.get("direction") or ""),
        "position_action": str(payload.get("position_action") or ""),
        "order_type": str(payload.get("order_type") or "market"),
        "quantity": str(payload.get("quantity") or ""),
        "response": dict(response),
        "local_simulation_ignored": True,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
    }
    path = config.output_dir / EXECUTION_LEDGER_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the persistent Longbridge SDK paper runtime.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--check", action="store_true", help="Check SDK/OAuth interfaces without connecting.")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--dispatch", action="store_true", help="Request paper dispatch after the readonly gate passes.")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--replace-cli-supervisor", action="store_true")
    return parser.parse_args()


def require_sdk_contract() -> Any:
    import longbridge.openapi as lb
    try:
        installed = package_version("longbridge")
    except PackageNotFoundError as exc:
        raise RuntimeError("longbridge_sdk_not_installed") from exc
    numeric_version = tuple(
        int(part) for part in installed.split("+", 1)[0].split(".")[:3]
    )
    if numeric_version < MINIMUM_LONGBRIDGE_SDK_VERSION:
        raise RuntimeError(
            "longbridge_sdk_too_old:"
            f"installed={installed}:required=4.5.0"
        )
    try:
        marker = json.loads(
            PATCHED_LONGBRIDGE_SDK_MARKER.read_text(encoding="utf-8")
        )
        installed_patch_sha256 = str(marker.get("patch_sha256") or "")
        expected_patch_sha256 = hashlib.sha256(
            PATCHED_LONGBRIDGE_SDK_PATCH.read_bytes()
        ).hexdigest()
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("longbridge_sdk_first_push_patch_missing") from exc
    if (
        str(marker.get("sdk_version") or "") != installed
        or str(marker.get("upstream_commit") or "")
        != PATCHED_LONGBRIDGE_SDK_COMMIT
        or installed_patch_sha256 != expected_patch_sha256
    ):
        raise RuntimeError("longbridge_sdk_first_push_patch_mismatch")
    missing = [
        name
        for name in (
            "QuoteContext",
            "TradeContext",
            "PortfolioContext",
            "PushCandlestickMode",
        )
        if not getattr(lb, name, None)
    ]
    if missing:
        raise RuntimeError(f"sdk_contract_missing:{','.join(missing)}")
    for method in ("set_on_quote", "set_on_trades", "subscribe", "subscriptions"):
        if not hasattr(lb.QuoteContext, method):
            raise RuntimeError(f"sdk_quote_contract_missing:{method}")
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
        runtime_status_matches_config(config, runtime_status)
        and process_alive(int(runtime_status.get("runtime_pid") or 0))
    )


def runtime_status_matches_config(config: Any, runtime_status: dict[str, Any]) -> bool:
    """Identify the production runtime even during a bounded process handoff."""
    return bool(
        str(runtime_status.get("config_fingerprint") or "")
        == config_fingerprint(config)
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
) -> bool:
    return bool(
        dispatch_requested
        and paper_client_ready
        and trade_context_ready
        and market_data_ready
        and trading_daily_context_ready
        and not flatten_blocks_new_entries
        and account_snapshot_ready
    )


def runtime_dispatch_block_reason(
    *,
    paper_order_dispatch_enabled: bool,
    readonly_gate_blocked: bool,
    paper_client_ready: bool,
    trade_context_ready: bool,
    market_data_ready: bool,
    flatten_blocks_new_entries: bool,
    account_snapshot_ready: bool,
    trading_daily_context_ready: bool,
    formal_activation_waiting: bool = False,
    authorized_cleanup_waiting: bool = False,
) -> str:
    if not paper_order_dispatch_enabled:
        return "paper_order_dispatch_disabled"
    if readonly_gate_blocked:
        return "two_day_readonly_gate"
    if not paper_client_ready or not trade_context_ready:
        return "trade_context_recovering"
    if not market_data_ready:
        return "market_data_recovering"
    if flatten_blocks_new_entries:
        if authorized_cleanup_waiting:
            return "pending_authorized_bucket_cleanup"
        return (
            "waiting_for_formal_test_activation"
            if formal_activation_waiting
            else "pending_account_flatten"
        )
    if not account_snapshot_ready:
        return "account_snapshot_recovering"
    if not trading_daily_context_ready:
        return "trading_daily_context_incomplete"
    return ""


def trade_context_health_requires_rebuild(health: dict[str, Any]) -> bool:
    return bool(
        health.get("trade_context_refresh_required")
        or str(health.get("status") or "") == "trade_context_missing"
    )


def run_sdk_preflight(config: Any) -> dict[str, Any]:
    """Verify every SDK endpoint used by M15 without sending an order."""
    sdk = require_sdk_contract()
    oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
    trade = sdk.TradeContext(sdk_config_from_oauth(sdk, oauth, config.trade_region))
    portfolio = sdk.PortfolioContext(sdk_config_from_oauth(sdk, oauth, config.trade_region))
    provider = SdkAccountStateProvider(trade, portfolio, request_gate=SdkTradeRequestGate())
    account = provider.refresh()
    quote_error = ""
    quote_probe_source = "direct_sdk_quote_probe"
    try:
        runtime_status = json.loads(config.runtime_status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        runtime_status = {}
    runtime_status_matches = runtime_status_matches_config(config, runtime_status)
    if runtime_status_matches:
        quote_probe_source = "active_sdk_runtime_status"
        if not process_alive(int(runtime_status.get("runtime_pid") or 0)):
            quote_error = "sdk_quote_runtime_process_not_alive"
        elif runtime_status.get("sdk_connected") is not True:
            quote_error = "sdk_quote_runtime_not_connected"
    else:
        try:
            quote = sdk.QuoteContext(sdk_config_from_oauth(sdk, oauth, config.quote_region))
            quote.quote([configured_symbols(config)[0]])
        except Exception as exc:
            quote_error = f"sdk_quote_probe_failed:{type(exc).__name__}:{exc}"
    errors = list(account.get("errors") or [])
    if quote_error:
        errors.append(quote_error)
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
        # Sell-side estimates are dedicated US short-sale queries. The project
        # deliberately uses only the cash-backed quantity and keeps margin
        # financing disabled.
        short_capacity = short_capacity_cash
    except Exception as exc:
        short_capacity_error = f"sdk_short_capacity_probe_failed:{type(exc).__name__}:{exc}"
        errors.append(short_capacity_error)
    return {
        "quote_ok": not quote_error,
        "quote_probe_source": quote_probe_source,
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
            not short_capacity_error and Decimal(short_capacity_cash) > 0
        ),
        "short_capacity_probe_symbol": short_capacity_probe_symbol,
        "short_capacity_probe_price_is_connectivity_only": True,
        "short_capacity_probe_quantity": short_capacity,
        "short_capacity_probe_cash_quantity": short_capacity_cash,
        "short_capacity_probe_margin_quantity": short_capacity_margin,
        "short_capacity_probe_basis": "cash_max_qty_for_sell_short_no_margin_financing",
        "errors": errors,
    }


WORKER_MESSAGES_ALLOWED_TO_DROP = {
    "heartbeat",
    "quote_states",
    "subscription_progress",
}


def emit_worker(queue_out: Any, payload: dict[str, Any]) -> bool:
    """Deliver trading inputs reliably while allowing telemetry to coalesce.

    A full multiprocessing queue used to silently discard complete bars and
    snapshot batches.  That made an otherwise healthy 300-symbol cycle lose a
    whole five-minute boundary.  Heartbeats, subscription progress and a
    coalesced quote-state batch may be superseded by a newer update; bars,
    snapshots and lifecycle messages may not.
    """
    kind = str(payload.get("kind") or "")
    if kind in WORKER_MESSAGES_ALLOWED_TO_DROP:
        try:
            queue_out.put_nowait(payload)
            return True
        except queue.Full:
            return False
    put = getattr(queue_out, "put", None)
    if not callable(put):
        # Lightweight test/in-process queues may expose only put_nowait. The
        # production multiprocessing queue always takes the bounded blocking
        # branch below.
        queue_out.put_nowait(payload)
        return True
    try:
        put(payload, block=True, timeout=5)
        return True
    except queue.Full as exc:
        raise RuntimeError(
            f"critical_worker_message_queue_saturated:{kind or 'unknown'}"
        ) from exc


def emit_daily_context_result(queue_out: Any, payload: dict[str, Any]) -> None:
    """Flush the one critical daily-context result before the child exits."""
    queue_out.put(payload, block=True, timeout=5)
    close = getattr(queue_out, "close", None)
    if callable(close):
        close()
    join_thread = getattr(queue_out, "join_thread", None)
    if callable(join_thread):
        join_thread()


def event_rows_to_daily(symbol: str, candles: Any, received_at: datetime) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for candle in candles if isinstance(candles, list) else []:
        row = sdk_object_to_dict(candle)
        timestamp = row.get("timestamp")
        try:
            if isinstance(timestamp, datetime):
                # The Python SDK currently returns a naive datetime in the
                # machine's local timezone for Candlestick.timestamp.  Going
                # through timestamp() preserves the actual instant instead
                # of incorrectly treating that local wall time as UTC.
                source_at = datetime.fromtimestamp(timestamp.timestamp(), UTC)
            else:
                source_at = datetime.fromtimestamp(int(timestamp), UTC)
        except (TypeError, ValueError, OSError):
            continue
        close = str(row.get("close") or row.get("last_done") or "0")
        if close in {"", "0", "0.0"}:
            continue
        event_id = f"sdk-1d|{symbol}|{to_iso(source_at)}"
        result.append({
            "schema_version": "m15.realtime-market-event.v2",
            "event_id": event_id,
            "symbol": symbol.replace(".US", ""),
            "timeframe": "1d",
            "event_time": to_iso(source_at),
            "bar_open_at": to_iso(source_at),
            "bar_close_at": to_iso(source_at),
            "source_event_at": to_iso(source_at),
            "received_at": to_iso(received_at),
            "source_delivery_age_ms": 0,
            "bar_final": True,
            "source_mode": "longbridge_sdk_daily_context",
            "open": str(row.get("open") or close),
            "high": str(row.get("high") or close),
            "low": str(row.get("low") or close),
            "close": close,
            "volume": str(row.get("volume") or "0"),
            "local_simulation_ignored": True,
        })
    return result


def event_rows_to_intraday_context(
    symbol: str,
    candles: Any,
    received_at: datetime,
    *,
    bar_minutes: int,
    session_started_at: datetime,
    expected_last_close: datetime,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    session_start = session_started_at.astimezone(UTC)
    expected_close = expected_last_close.astimezone(UTC)
    for candle in candles if isinstance(candles, list) else []:
        row = sdk_object_to_dict(candle)
        timestamp = row.get("timestamp")
        try:
            if isinstance(timestamp, datetime):
                bar_open_at = datetime.fromtimestamp(timestamp.timestamp(), UTC)
            else:
                bar_open_at = datetime.fromtimestamp(int(timestamp), UTC)
        except (TypeError, ValueError, OSError):
            continue
        bar_close_at = bar_open_at + timedelta(minutes=bar_minutes)
        if bar_open_at < session_start or bar_close_at > expected_close:
            continue
        bar_open_ny = bar_open_at.astimezone(NEW_YORK)
        if bar_open_ny.weekday() >= 5 or bar_open_ny.date() != session_start.astimezone(NEW_YORK).date():
            continue
        if not (
            (bar_open_ny.hour > 9 or (bar_open_ny.hour == 9 and bar_open_ny.minute >= 30))
            and bar_open_ny.hour < 16
        ):
            continue
        close = str(row.get("close") or row.get("last_done") or "0")
        if close in {"", "0", "0.0"}:
            continue
        result.append(
            {
                "schema_version": "m15.realtime-market-event.v2",
                "event_id": f"sdk-5m|{symbol}|{to_iso(bar_close_at)}",
                "symbol": symbol.replace(".US", ""),
                "timeframe": "5m",
                "event_time": to_iso(bar_close_at),
                "bar_open_at": to_iso(bar_open_at),
                "bar_close_at": to_iso(bar_close_at),
                "source_event_at": to_iso(bar_close_at),
                "received_at": to_iso(received_at),
                "source_delivery_age_ms": 0,
                "bar_final": True,
                "source_mode": "longbridge_sdk_intraday_context",
                "open": str(row.get("open") or close),
                "high": str(row.get("high") or close),
                "low": str(row.get("low") or close),
                "close": close,
                "volume": str(row.get("volume") or "0"),
                "market_data_blocked_reason": "",
                "context_only": True,
                "local_simulation_ignored": True,
            }
        )
    return result


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
            blocked_reason = "quote_timestamp_regressed"
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
        "prev_close": str(
            payload.get("prev_close")
            or (previous or {}).get("prev_close")
            or ""
        ),
        "volume": volume,
        "market_data_blocked_reason": blocked_reason,
    }
    state_by_symbol[normalized_symbol] = state
    return state


def build_sdk_quote_snapshot(
    state_by_symbol: dict[str, dict[str, Any]],
    *,
    generated_at: datetime,
) -> dict[str, Any]:
    """Publish broker-native prices for slow App-metric reconciliation."""
    rows: list[dict[str, Any]] = []
    for symbol, state in sorted(state_by_symbol.items()):
        current_price = str(state.get("close") or "")
        previous_close = str(state.get("prev_close") or "")
        rows.append(
            {
                "symbol": f"{symbol.removesuffix('.US')}.US",
                "current_price": current_price,
                "prev_close": previous_close,
                "price_phase": "regular",
                "source_event_at": str(state.get("source_event_at") or ""),
                "received_at": str(state.get("received_at") or ""),
                "source_mode": str(state.get("source_mode") or ""),
                "market_data_blocked_reason": str(
                    state.get("market_data_blocked_reason") or ""
                ),
            }
        )
    latest_quote_received_at = max(
        (str(row.get("received_at") or "") for row in rows),
        default="",
    )
    return {
        "schema_version": "m15.longbridge-sdk-quote-snapshot.v1",
        "metric_contract_id": "longbridge_app_asset_daily_pnl_v1",
        "generated_at": to_iso(generated_at),
        "market_date": generated_at.astimezone(NEW_YORK).date().isoformat(),
        "source": "longbridge_sdk_runtime_single_quote_connection",
        "latest_quote_received_at": latest_quote_received_at,
        "row_count": len(rows),
        "rows": rows,
    }


def write_trusted_sdk_quote_snapshot(
    path: Path,
    state_by_symbol: dict[str, dict[str, Any]],
    *,
    generated_at: datetime,
    required_symbols: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    """Replace the canonical quote snapshot only with complete broker data."""
    snapshot = build_sdk_quote_snapshot(
        state_by_symbol,
        generated_at=generated_at,
    )
    valid_symbols: set[str] = set()
    for row in snapshot["rows"]:
        try:
            current_price = Decimal(str(row.get("current_price") or "0"))
            previous_close = Decimal(str(row.get("prev_close") or "0"))
        except (InvalidOperation, ValueError):
            continue
        if (
            current_price > 0
            and previous_close > 0
            and str(row.get("received_at") or "")
        ):
            valid_symbols.add(str(row.get("symbol") or "").upper())
    expected_symbols = {
        str(symbol).upper()
        if str(symbol).upper().endswith(".US")
        else f"{str(symbol).upper()}.US"
        for symbol in required_symbols
    }
    missing_symbols = sorted(expected_symbols - valid_symbols)
    if missing_symbols:
        return {
            "written": False,
            "row_count": int(snapshot.get("row_count") or 0),
            "required_symbol_count": len(expected_symbols),
            "missing_symbols": missing_symbols,
        }

    # Keep same-day quotes for symbols that were held or traded earlier in the
    # session but are no longer part of the active subscription targets.  The
    # App daily-PNL reconciliation still needs their previous close after an
    # intraday exit.  Current required symbols must be complete before these
    # retained rows are considered, so stale data can never mask a feed gap.
    retained_row_count = 0
    if path.exists():
        try:
            previous_snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            previous_snapshot = {}
        if (
            str(previous_snapshot.get("metric_contract_id") or "")
            == str(snapshot.get("metric_contract_id") or "")
            and str(previous_snapshot.get("market_date") or "")
            == str(snapshot.get("market_date") or "")
        ):
            current_symbols = {
                str(row.get("symbol") or "").upper()
                for row in snapshot["rows"]
            }
            for previous_row in previous_snapshot.get("rows", []):
                symbol = str(previous_row.get("symbol") or "").upper()
                if not symbol or symbol in current_symbols:
                    continue
                try:
                    current_price = Decimal(
                        str(previous_row.get("current_price") or "0")
                    )
                    previous_close = Decimal(
                        str(previous_row.get("prev_close") or "0")
                    )
                except (InvalidOperation, ValueError):
                    continue
                if current_price <= 0 or previous_close <= 0:
                    continue
                retained_row = dict(previous_row)
                retained_row["retained_after_intraday_exit"] = True
                snapshot["rows"].append(retained_row)
                current_symbols.add(symbol)
                retained_row_count += 1
            snapshot["rows"].sort(key=lambda row: str(row.get("symbol") or ""))
            snapshot["row_count"] = len(snapshot["rows"])
            snapshot["latest_quote_received_at"] = max(
                (
                    str(row.get("received_at") or "")
                    for row in snapshot["rows"]
                ),
                default="",
            )
    snapshot["retained_same_day_row_count"] = retained_row_count
    write_json_atomic(path, snapshot)
    return {
        "written": True,
        "row_count": int(snapshot.get("row_count") or 0),
        "required_symbol_count": len(expected_symbols),
        "missing_symbols": [],
        "retained_same_day_row_count": retained_row_count,
    }


def fetch_daily_context_rows(
    quote: Any,
    sdk: Any,
    symbols: tuple[str, ...],
    bars: int,
    *,
    request_interval_seconds: float = 0,
) -> tuple[list[dict[str, Any]], list[str]]:
    failures: list[str] = []
    all_rows: list[dict[str, Any]] = []
    for index, symbol in enumerate(symbols):
        try:
            candles = quote.candlesticks(symbol, sdk.Period.Day, bars, sdk.AdjustType.NoAdjust)
            all_rows.extend(event_rows_to_daily(symbol, list(candles), datetime.now(UTC)))
        except Exception:
            failures.append(symbol)
        if request_interval_seconds and index + 1 < len(symbols):
            time.sleep(request_interval_seconds)
    return all_rows, failures


def load_daily_context(
    quote: Any,
    sdk: Any,
    symbols: tuple[str, ...],
    bars: int,
    queue_out: Any,
    *,
    task_id: str = "",
) -> list[str]:
    all_rows, failures = fetch_daily_context_rows(quote, sdk, symbols, bars)
    emit_worker(queue_out, {"kind": "daily_context", "task_id": task_id, "rows": all_rows, "failures": failures})
    return failures


def subscription_symbols(value: Any) -> set[str]:
    if isinstance(value, (list, tuple)):
        return set().union(*(subscription_symbols(item) for item in value)) if value else set()
    row = sdk_object_to_dict(value)
    if isinstance(row, dict):
        symbol = str(row.get("symbol") or "").upper()
        result = {symbol} if symbol else set()
        for item in row.values():
            result.update(subscription_symbols(item))
        return result
    return set()


def account_position_symbols(config: Any) -> tuple[str, ...]:
    """Return broker-held US symbols that require quote and exit monitoring."""
    path = config.output_dir / REALTIME_ACCOUNT_STATE_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ()
    symbols: set[str] = set()
    for row in payload.get("positions") or []:
        if not isinstance(row, dict):
            continue
        try:
            quantity = Decimal(str(row.get("quantity") or "0"))
        except (InvalidOperation, ValueError):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if quantity == 0 or not symbol.endswith(f".{config.market}"):
            continue
        symbols.add(symbol)
    return tuple(sorted(symbols))


def quote_subscription_targets(
    config: Any,
    now: datetime,
    *,
    position_symbols: tuple[str, ...] | list[str] | None = None,
) -> tuple[str, ...]:
    """Monitor held positions without adding them to the strategy universe."""
    base = (
        configured_trading_symbols(config)
        if in_regular_session(now)
        else configured_symbols(config)
    )
    held = (
        tuple(position_symbols)
        if position_symbols is not None
        else account_position_symbols(config)
    )
    return tuple(dict.fromkeys((*base, *held)))


def should_use_snapshot_fallback(
    subscription_failures: int,
    failure_threshold: int,
) -> bool:
    return int(subscription_failures) >= int(failure_threshold)


def snapshot_poll_cycle_is_healthy(
    covered_count: int,
    expected_count: int,
    elapsed_ms: int,
    maximum_elapsed_ms: int,
) -> bool:
    return bool(
        int(covered_count) == int(expected_count)
        and int(elapsed_ms) <= int(maximum_elapsed_ms)
    )


def snapshot_poll_should_idle(ready_emitted: bool, now: datetime) -> bool:
    """Do not hammer the quote endpoint after a complete off-hours probe."""
    return bool(ready_emitted and not in_regular_session(now))


def regular_session_close_flush_action(
    now: datetime,
    attempted_business_dates: set[str],
    *,
    maximum_finalization_delay_ms: int,
) -> tuple[str, str]:
    """Return the one-shot action for the 15:55-16:00 New York bar.

    Snapshot polling intentionally idles at 16:00. Without a parent-owned
    timer, the last open bar has no later quote with which to finalize itself.
    A late wake-up is recorded instead of routing a stale bar as executable.
    """
    now_utc = now.astimezone(UTC)
    now_ny = now_utc.astimezone(NEW_YORK)
    business_date = now_ny.date().isoformat()
    if now_ny.weekday() >= 5 or business_date in attempted_business_dates:
        return business_date, "not_due"
    close_ny = now_ny.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_ny < close_ny:
        return business_date, "not_due"
    deadline = close_ny + timedelta(
        milliseconds=max(0, int(maximum_finalization_delay_ms))
    )
    return (
        business_date,
        "flush" if now_ny <= deadline else "missed_deadline",
    )


def restored_postclose_recovery_state(
    previous_runtime_status: dict[str, Any],
) -> tuple[set[str], dict[str, Any]]:
    """Preserve one terminal post-close recovery attempt across restarts."""
    previous = dict(
        previous_runtime_status.get("postclose_intraday_recovery") or {}
    )
    business_date = str(previous.get("business_date") or "")
    status = str(previous.get("status") or "")
    terminal_statuses = {
        "completed",
        "completed_with_failures",
        "completed_incomplete_data",
    }
    if business_date and status in terminal_statuses:
        return {business_date}, previous
    return set(), {
        "status": "not_started",
        "recovered_row_count": 0,
        "failed_symbols": [],
        "historical_signal_replayed": False,
        "historical_order_replayed": False,
    }


def validated_snapshot_poll_is_reusable(
    previous_status: dict[str, Any],
    expected_symbol_count: int,
    *,
    now: datetime | None = None,
) -> bool:
    """Reuse snapshot fallback off-hours; retry push at every regular-session start."""
    current = now or datetime.now(UTC)
    return bool(
        not in_regular_session(current)
        and previous_status.get("market_data_mode") == "sdk_snapshot_poll"
        and previous_status.get("market_data_fallback_validated") is True
        and int(previous_status.get("snapshot_poll_covered_count") or 0)
        == int(expected_symbol_count)
        and int(previous_status.get("snapshot_poll_missing_count") or 0) == 0
    )


MARKET_DATA_PROGRESS_KINDS = frozenset(
    {
        "subscription_progress",
        "ready",
        "quote_state",
        "quote_states",
        "snapshots",
        "bars",
        "heartbeat",
    }
)


def buffer_pending_market_data_progress(
    message_queue: Any,
    deferred_messages: deque[dict[str, Any]],
    *,
    now_monotonic: float,
    maximum_messages: int = 64,
) -> float:
    """Buffer queued worker output before deciding its heartbeat is stale."""
    progress_seen = False
    for _ in range(maximum_messages):
        try:
            message = message_queue.get_nowait()
        except queue.Empty:
            break
        deferred_messages.append(message)
        if str(message.get("kind") or "") in MARKET_DATA_PROGRESS_KINDS:
            progress_seen = True
    return now_monotonic if progress_seen else 0.0


def pop_deferred_worker_error(
    deferred_messages: deque[dict[str, Any]],
) -> dict[str, Any] | None:
    """Remove one worker error while preserving all other queued messages."""
    worker_error: dict[str, Any] | None = None
    remaining: deque[dict[str, Any]] = deque()
    while deferred_messages:
        message = deferred_messages.popleft()
        if worker_error is None and str(message.get("kind") or "") == "error":
            worker_error = message
        else:
            remaining.append(message)
    deferred_messages.extend(remaining)
    return worker_error


def effective_worker_progress(
    queued_progress_monotonic: float,
    shared_progress_monotonic: float,
) -> float:
    return max(float(queued_progress_monotonic), float(shared_progress_monotonic))


def preserve_partial_bar_suppression(
    current_value: str,
    worker_value: str,
    *,
    market_data_mode: str,
) -> str:
    """Keep the original snapshot-bar boundary across worker recovery."""
    if market_data_mode == "sdk_snapshot_poll" and current_value:
        return current_value
    return worker_value


def rollover_snapshot_cycle(
    current_cycle_id: str,
    next_cycle_id: str,
    buffered_completed_bars: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Carry finalized bars forward when an SDK poll cycle is interrupted."""
    if next_cycle_id == current_cycle_id:
        return current_cycle_id, buffered_completed_bars, []
    return next_cycle_id, [], list(buffered_completed_bars)


def market_data_mode_qualifies_for_subscription_gate(mode: str) -> bool:
    return str(mode) == "sdk_subscription"


def market_data_ready_for_dispatch(
    *,
    worker_ready: bool,
    market_data_mode: str,
    snapshot_fallback_validated: bool,
) -> bool:
    """Require either SDK push or a currently validated SDK snapshot cycle."""
    return bool(
        worker_ready
        and (
            market_data_mode_qualifies_for_subscription_gate(market_data_mode)
            or (
                market_data_mode == "sdk_snapshot_poll"
                and snapshot_fallback_validated
            )
        )
    )


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


def recent_restart_count(
    restart_times: deque[float],
    now_monotonic: float,
    window_seconds: float,
) -> int:
    cutoff = float(now_monotonic) - float(window_seconds)
    while restart_times and float(restart_times[0]) < cutoff:
        restart_times.popleft()
    return len(restart_times)


def clear_restart_burst_after_stable_polls(
    restart_times: deque[float],
    successful_fast_polls: int,
    *,
    stable_poll_threshold: int = 3,
) -> bool:
    """End recovery backoff after the replacement worker proves stable."""
    if int(successful_fast_polls) < int(stable_poll_threshold):
        return False
    if not restart_times:
        return False
    restart_times.clear()
    return True


def adaptive_market_data_deadline_seconds(
    base_deadline_seconds: float,
    recovery_deadline_seconds: float,
    recent_restarts: int,
    now: datetime,
    bar_minutes: int,
) -> float:
    """Let the SDK return its timeout without admitting stale market events."""
    del now, bar_minutes
    # Longbridge's native quote request can remain blocked for roughly 30
    # seconds. Killing the isolated worker at the five-second signal freshness
    # limit creates a reconnect storm. Bar delivery still has its own strict
    # maximum_bar_finalization_delay_ms gate before routing or dispatch.
    base = max(float(base_deadline_seconds), 45.0)
    if int(recent_restarts) < 3:
        return base
    return max(base, float(recovery_deadline_seconds))


def active_market_data_progress_deadline_seconds(
    market_data_mode: str,
    worker_ready: bool,
    *,
    base_deadline_seconds: float,
    recovery_deadline_seconds: float,
    recent_restarts: int,
    now: datetime,
    bar_minutes: int,
    snapshot_dispatch_max_elapsed_ms: int,
) -> float:
    """Bound a ready snapshot request independently from connection recovery.

    A snapshot worker may need a long startup/recovery window, but once it has
    declared ready, one native quote request must not occupy an entire bar-close
    deadline. The parent can terminate the isolated worker and retain its bar
    state while a fresh worker reconnects.
    """
    if worker_ready and market_data_mode == "sdk_snapshot_poll":
        return max(
            float(base_deadline_seconds),
            float(snapshot_dispatch_max_elapsed_ms) / 1000.0,
        )
    return adaptive_market_data_deadline_seconds(
        base_deadline_seconds,
        recovery_deadline_seconds,
        recent_restarts,
        now,
        bar_minutes,
    )


def market_data_worker_startup_deadline_seconds(
    snapshot_fallback_active: bool,
    subscription_deadline_seconds: float,
    snapshot_poll_recovery_deadline_seconds: float,
    *,
    snapshot_was_previously_ready: bool = False,
    snapshot_dispatch_max_elapsed_ms: int = 0,
) -> float:
    """Keep SDK connection startup separate from the realtime heartbeat SLA."""
    if snapshot_fallback_active:
        if snapshot_was_previously_ready and snapshot_dispatch_max_elapsed_ms > 0:
            return max(
                5.0,
                float(snapshot_dispatch_max_elapsed_ms) / 1000.0,
            )
        return max(
            float(subscription_deadline_seconds),
            float(snapshot_poll_recovery_deadline_seconds),
        )
    return float(subscription_deadline_seconds)


def primary_subscription_reprobe_date(
    snapshot_fallback_active: bool,
    attempted_business_dates: set[str],
    now: datetime,
) -> str:
    """Request one push-subscription retry before each US regular session."""
    if not snapshot_fallback_active:
        return ""
    now_ny = now.astimezone(NEW_YORK)
    if now_ny.weekday() >= 5:
        return ""
    session_probe_start = now_ny.replace(
        hour=9, minute=25, second=0, microsecond=0
    )
    session_probe_end = now_ny.replace(
        hour=9, minute=35, second=0, microsecond=0
    )
    business_date = now_ny.date().isoformat()
    if (
        session_probe_start <= now_ny < session_probe_end
        and business_date not in attempted_business_dates
    ):
        return business_date
    return ""


def subscription_quote_stream_is_stale(
    worker_ready_since_monotonic: float,
    last_quote_monotonic: float,
    now_monotonic: float,
    deadline_seconds: float,
) -> bool:
    if float(worker_ready_since_monotonic) <= 0:
        return False
    last_real_quote = max(
        float(worker_ready_since_monotonic),
        float(last_quote_monotonic),
    )
    return float(now_monotonic) - last_real_quote > float(deadline_seconds)


def subscription_quote_stream_deadline_seconds(
    market_data_heartbeat_deadline_seconds: float,
) -> float:
    """Keep transport liveness independent from the five-second bar SLA."""
    return max(float(market_data_heartbeat_deadline_seconds), 45.0)


def partition_subscription_targets(
    symbols: list[str],
    shard_count: int,
) -> list[list[str]]:
    """Spread liquid symbols across a bounded number of SDK connections."""
    if shard_count <= 0:
        raise ValueError("subscription shard count must be positive")
    if not symbols:
        return []
    count = min(int(shard_count), len(symbols))
    return [symbols[index::count] for index in range(count)]


def deferred_intraday_context_after_mid_session_start(
    symbols: list[str],
    *,
    suppressed_until: str,
) -> tuple[list[str], dict[str, Any]]:
    affected = sorted(str(symbol) for symbol in symbols if str(symbol))
    return affected, {
        "status": "deferred_until_clean_session",
        "reason": (
            "live_sdk_history_repair_would_compete_with_realtime_market_data"
        ),
        "suppressed_until": suppressed_until,
        "row_count": 0,
        "failed_symbols": affected,
        "historical_signal_replayed": False,
        "historical_order_replayed": False,
    }


def silence_sdk_worker_console() -> None:
    """Keep repeated SDK connection banners out of the runtime log.

    Worker failures still reach the parent through structured queue messages.
    """
    null_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null_fd, 1)
        os.dup2(null_fd, 2)
    finally:
        os.close(null_fd)


def quote_worker(
    config_path: str,
    queue_out: Any,
    stop_event: Any,
    progress_value: Any | None = None,
) -> None:
    """Own one raw SDK stream and aggregate exact five-minute bars in Python.

    The patched native candlestick aggregator stalls once the local symbol set
    grows beyond roughly one hundred instruments.  Raw Trade pushes remain
    healthy for the complete universe, so callbacks only enqueue plain payloads
    and this worker's main loop performs the deterministic aggregation.
    """
    quote_contexts: list[Any] = []
    try:
        config = load_config(config_path)
        silence_sdk_worker_console()
        sdk = require_sdk_contract()
        pending_market_events: deque[tuple[str, str, dict[str, Any], datetime]] = deque()
        pending_quote_states: dict[str, dict[str, Any]] = {}

        aggregation_started_at = datetime.now(UTC)
        first_complete_bar_open = floor_bar_open(
            aggregation_started_at,
            config.bar_minutes,
        ) + timedelta(minutes=config.bar_minutes)
        builder = FiveMinuteBarBuilder(
            config.bar_minutes,
            complete_bar_open_not_before=first_complete_bar_open,
        )
        boundary_gate: ConfirmedBoundaryBatchGate | None = None

        def on_trades(symbol: str, event: Any) -> None:
            pending_market_events.append(
                ("trade", symbol, sdk_object_to_dict(event), datetime.now(UTC))
            )

        def report_subscription_progress(completed: int, total: int) -> None:
            if progress_value is not None:
                progress_value.value = time.monotonic()
            emit_worker(
                queue_out,
                {
                    "kind": "subscription_progress",
                    "completed": completed,
                    "total": total,
                },
            )

        subscription_targets = list(
            quote_subscription_targets(config, datetime.now(UTC))
        )
        all_symbols = list(subscription_targets)
        trading_symbols = list(configured_trading_symbols(config))
        boundary_gate = ConfirmedBoundaryBatchGate(
            trading_symbols,
            maximum_source_delivery_age_ms=config.maximum_source_delivery_age_ms,
            maximum_finalization_delay_ms=(
                config.maximum_bar_finalization_delay_ms
            ),
        )
        heartbeat_symbols = [
            symbol
            for symbol in ("SPY.US", "QQQ.US")
            if symbol in set(trading_symbols)
        ]
        monitoring_symbols = list(dict.fromkeys([
            *heartbeat_symbols,
            *(symbol for symbol in all_symbols if symbol not in set(trading_symbols)),
        ]))
        oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
        quote = sdk.QuoteContext(
            sdk_config_from_oauth(sdk, oauth, config.quote_region)
        )
        quote_contexts = [quote]
        warmup = {
            "status": "raw_trade_aggregation_context_ready",
            "attempt_count": 1,
            "symbol": "ALL",
            "row_count": 0,
            "elapsed_ms": 0,
            "subscription_shard": 0,
            "subscription_symbol_count": len(all_symbols),
        }
        emit_worker(queue_out, {"kind": "quote_context_warmup", **warmup})

        quote.set_on_trades(on_trades)
        trade_failed = subscribe_quote_and_trades(
            quote,
            all_symbols,
            [sdk.SubType.Trade],
            batch_size=config.subscription_batch_size,
            retry_count=config.subscription_retry_count,
            progress_callback=report_subscription_progress,
            request_interval_seconds=config.subscription_request_interval_seconds,
            retry_backoff_seconds=config.subscription_retry_backoff_seconds,
            recover_failed_batch_symbols=True,
        )
        failed = sorted(set(trade_failed))
        expected = set(all_symbols)
        trading_expected = set(trading_symbols)
        subscribed_trade: set[str] = set()
        for item in quote.subscriptions():
            symbol = str(getattr(item, "symbol", "") or "").upper()
            subscription_types = {
                str(value) for value in (getattr(item, "sub_types", None) or [])
            }
            if symbol and "SubType.Trade" in subscription_types:
                subscribed_trade.add(symbol)
        missing = sorted((expected - subscribed_trade) | set(failed))

        emit_worker(queue_out, {
            "kind": "ready", "subscribed_symbols": sorted(expected - set(missing)),
            "subscription_failed_symbols": missing, "daily_context_failed_symbols": [],
            "trading_subscription_failed_symbols": sorted(trading_expected & set(missing)),
            "partial_bar_suppressed_until": to_iso(first_complete_bar_open.astimezone(UTC)),
            "subscription_target_count": len(subscription_targets),
            "initial_quote_callbacks_enabled": False,
            "initial_trade_callbacks_enabled": True,
            "confirmed_candlestick_callbacks_enabled": False,
            "confirmed_candlestick_target_count": len(all_symbols),
            "confirmed_candlestick_failed_symbols": missing,
            "confirmed_candlestick_coverage": (
                f"{len(all_symbols) - len(set(missing))}"
                f"/{len(all_symbols)}"
            ),
            "market_data_aggregation_mode": "python_raw_trade_push",
            "monitoring_quote_failed_symbols": [],
            "initial_snapshot_seed_count": 0,
            "initial_snapshot_seed_symbol_count": 0,
            "quote_context_warmups": [warmup],
            "quote_subscription_shard_count": 1,
        })
        worker_ready_monotonic = time.monotonic()
        regular_session_started_monotonic = 0.0
        regular_session_business_date = ""
        last_market_monotonic = 0.0
        last_heartbeat = 0.0
        while not stop_event.is_set():
            now_utc = datetime.now(UTC)
            monotonic_now = time.monotonic()
            rows: list[dict[str, Any]] = []
            processed_events = 0
            while pending_market_events and processed_events < 20000:
                kind, symbol, payload, received_at = pending_market_events.popleft()
                processed_events += 1
                last_market_monotonic = monotonic_now
                if kind == "trade":
                    rows.extend(builder.on_trade(symbol, payload, received_at=received_at))
            builder.ensure_zero_trade_bars(now_utc)
            rows.extend(builder.flush(now_utc))
            batches = boundary_gate.add(rows, now=now_utc) if rows and boundary_gate else []
            for batch in batches:
                emit_worker(queue_out, {"kind": "bars", **batch})
            expired_batches = boundary_gate.flush_expired(now=now_utc) if boundary_gate else []
            for batch in expired_batches:
                emit_worker(queue_out, {"kind": "bars", **batch})
            quote_state_batch = list(pending_quote_states.values())
            if in_regular_session(now_utc):
                business_date = market_date(now_utc)
                if business_date != regular_session_business_date:
                    regular_session_business_date = business_date
                    regular_session_started_monotonic = monotonic_now
                silent = monotonic_now - max(
                    regular_session_started_monotonic,
                    worker_ready_monotonic,
                    last_market_monotonic,
                ) > subscription_quote_stream_deadline_seconds(
                    config.market_data_heartbeat_deadline_seconds
                )
            else:
                regular_session_started_monotonic = 0.0
                regular_session_business_date = ""
                silent = False
            if silent:
                raise RuntimeError(
                    "sdk_raw_trade_stream_silent:0"
                )
            if quote_state_batch:
                delivered = emit_worker(
                    queue_out,
                    {"kind": "quote_states", "rows": quote_state_batch},
                )
                if delivered:
                    for row in quote_state_batch:
                        symbol = str(row.get("symbol") or "").upper()
                        latest = pending_quote_states.get(symbol)
                        if latest is not None and latest.get("received_at") == row.get("received_at"):
                            pending_quote_states.pop(symbol, None)
            now = time.monotonic()
            if now - last_heartbeat >= 1:
                if progress_value is not None:
                    progress_value.value = now
                emit_worker(queue_out, {"kind": "heartbeat", "at": to_iso(now_utc)})
                last_heartbeat = now
            stop_event.wait(0.2)
    except BaseException as exc:
        emit_worker(queue_out, {"kind": "error", "reason": f"sdk_quote_worker_failed:{type(exc).__name__}:{exc}"})
    finally:
        for quote in quote_contexts:
            close = getattr(quote, "close", None)
            if callable(close):
                close()


def quote_snapshot_worker(
    config_path: str,
    queue_out: Any,
    stop_event: Any,
    progress_value: Any | None = None,
) -> None:
    """Fetch bounded SDK snapshots; the parent owns bar state across worker restarts."""
    try:
        config = load_config(config_path)
        silence_sdk_worker_console()
        sdk = require_sdk_contract()
        worker_started_at = datetime.now(UTC)
        first_complete_bar_open = floor_bar_open(
            worker_started_at, config.bar_minutes
        ) + timedelta(minutes=config.bar_minutes)
        target_symbols = list(
            quote_subscription_targets(config, datetime.now(UTC))
        )
        all_symbols = set(target_symbols)
        trading_symbols = set(configured_trading_symbols(config))
        consecutive_failures = 0
        consecutive_slow_polls = 0
        successful_fast_polls = 0
        total_poll_count = 0
        failed_poll_count = 0
        last_success_at = ""
        last_failure_at = ""
        last_first_batch_returned_at = ""
        last_first_batch_latency_ms = 0
        last_first_batch_symbol_count = 0
        ready_emitted = False
        while not stop_event.is_set():
            idle_now = datetime.now(UTC)
            if snapshot_poll_should_idle(ready_emitted, idle_now):
                progress_now = time.monotonic()
                if progress_value is not None:
                    progress_value.value = progress_now
                emit_worker(
                    queue_out,
                    {
                        "kind": "heartbeat",
                        "at": to_iso(idle_now),
                        "market_data_mode": "sdk_snapshot_poll",
                        "poll_elapsed_ms": 0,
                        "poll_is_fast_and_complete": True,
                        "poll_covered_count": len(target_symbols),
                        "poll_missing_count": 0,
                        "successful_fast_polls": successful_fast_polls,
                        "total_poll_count": total_poll_count,
                        "failed_poll_count": failed_poll_count,
                        "consecutive_failures": consecutive_failures,
                        "last_success_at": last_success_at,
                        "last_failure_at": last_failure_at,
                        "first_batch_returned_at": last_first_batch_returned_at,
                        "first_batch_latency_ms": last_first_batch_latency_ms,
                        "first_batch_symbol_count": last_first_batch_symbol_count,
                        "off_hours_idle": True,
                    },
                )
                stop_event.wait(1)
                continue
            became_ready_this_cycle = False
            poll_started = time.monotonic()
            received_at = datetime.now(UTC)
            poll_cycle_id = to_iso(received_at)
            total_poll_count += 1
            quote = None
            oauth = None
            try:
                # In this environment a reused QuoteContext commonly stalls on
                # its second full-universe quote request. Keep each request in
                # the already isolated worker but give it a fresh SDK context;
                # the parent enforces an independent liveness cutoff. The
                # tighter dispatch target remains a performance metric and
                # does not kill an otherwise healthy SDK process.
                oauth = sdk.OAuthBuilder(read_client_id(config)).build(
                    lambda _url: None
                )
                quote = sdk.QuoteContext(
                    sdk_config_from_oauth(sdk, oauth, config.quote_region)
                )
                snapshot_rows = []
                for index in range(
                    0,
                    len(target_symbols),
                    config.snapshot_poll_request_batch_size,
                ):
                    batch_rows = list(
                        quote.quote(
                            target_symbols[
                                index:index
                                + config.snapshot_poll_request_batch_size
                            ]
                        )
                    )
                    snapshot_rows.extend(batch_rows)
                    if index == 0:
                        last_first_batch_returned_at = to_iso(datetime.now(UTC))
                        last_first_batch_latency_ms = int(
                            (time.monotonic() - poll_started) * 1000
                        )
                        last_first_batch_symbol_count = len(batch_rows)
                    if progress_value is not None:
                        progress_value.value = time.monotonic()
                    # After the full-universe fallback has been validated,
                    # deliver each successful batch immediately. If a later
                    # SDK request blocks, the parent still retains the fresh
                    # rows and bar state from the completed batches.
                    if ready_emitted and batch_rows:
                        cycle_complete = (
                            index + config.snapshot_poll_request_batch_size
                            >= len(target_symbols)
                        )
                        emit_worker(
                            queue_out,
                            {
                                "kind": "snapshots",
                                "poll_cycle_id": poll_cycle_id,
                                "cycle_complete": cycle_complete,
                                "received_at": to_iso(datetime.now(UTC)),
                                "rows": [
                                    {
                                        "symbol": str(
                                            getattr(row, "symbol", "") or ""
                                        ).upper(),
                                        "payload": sdk_object_to_dict(row),
                                    }
                                    for row in batch_rows
                                ],
                            },
                        )
                    if (
                        config.snapshot_poll_request_interval_seconds
                        and index + config.snapshot_poll_request_batch_size
                        < len(target_symbols)
                    ):
                        stop_event.wait(
                            config.snapshot_poll_request_interval_seconds
                        )
                consecutive_failures = 0
                last_success_at = to_iso(datetime.now(UTC))
            except Exception as exc:
                consecutive_failures += 1
                failed_poll_count += 1
                last_failure_at = to_iso(datetime.now(UTC))
                failure_at = time.monotonic()
                if progress_value is not None:
                    progress_value.value = failure_at
                emit_worker(
                    queue_out,
                    {
                        "kind": "snapshot_poll_failure",
                        "consecutive_failures": consecutive_failures,
                        "total_poll_count": total_poll_count,
                        "failed_poll_count": failed_poll_count,
                        "last_success_at": last_success_at,
                        "last_failure_at": last_failure_at,
                        "first_batch_returned_at": last_first_batch_returned_at,
                        "first_batch_latency_ms": last_first_batch_latency_ms,
                        "first_batch_symbol_count": last_first_batch_symbol_count,
                        "reason": (
                            "sdk_quote_snapshot_poll_failed:"
                            f"{type(exc).__name__}:{exc}"
                        ),
                    },
                )
                emit_worker(
                    queue_out,
                    {
                        "kind": "heartbeat",
                        "at": to_iso(datetime.now(UTC)),
                        "market_data_mode": "sdk_snapshot_poll",
                        "snapshot_retry_in_progress": True,
                        "consecutive_failures": consecutive_failures,
                        "total_poll_count": total_poll_count,
                        "failed_poll_count": failed_poll_count,
                        "last_success_at": last_success_at,
                        "last_failure_at": last_failure_at,
                        "first_batch_returned_at": last_first_batch_returned_at,
                        "first_batch_latency_ms": last_first_batch_latency_ms,
                        "first_batch_symbol_count": last_first_batch_symbol_count,
                    },
                )
                # The parent retains bar state and replaces this isolated
                # worker with another clean connection.
                raise
            finally:
                close_quote = getattr(quote, "close", None)
                if callable(close_quote):
                    try:
                        close_quote()
                    except Exception:
                        pass
            rows_by_symbol = {
                str(getattr(row, "symbol", "") or "").upper(): row
                for row in snapshot_rows
            }
            covered = set(rows_by_symbol)
            missing = sorted(set(target_symbols) - covered)
            poll_elapsed_ms = int((time.monotonic() - poll_started) * 1000)
            poll_is_fast_and_complete = snapshot_poll_cycle_is_healthy(
                len(covered),
                len(target_symbols),
                poll_elapsed_ms,
                config.snapshot_poll_dispatch_max_elapsed_ms,
            )
            if poll_is_fast_and_complete:
                successful_fast_polls += 1
                consecutive_slow_polls = 0
            else:
                successful_fast_polls = 0
                consecutive_slow_polls += 1
            if not ready_emitted:
                emit_worker(
                    queue_out,
                    {
                        "kind": "subscription_progress",
                        "completed": len(covered),
                        "total": len(target_symbols),
                    },
                )
                if (
                    successful_fast_polls
                    >= config.snapshot_poll_min_successful_cycles
                ):
                    emit_worker(
                        queue_out,
                        {
                            "kind": "ready",
                            "market_data_mode": "sdk_snapshot_poll",
                            "market_data_fallback_validated": True,
                            "market_data_symbols": sorted(covered),
                            "subscribed_symbols": [],
                            "subscription_failed_symbols": sorted(
                                all_symbols - covered
                            ),
                            "daily_context_failed_symbols": [],
                            "trading_subscription_failed_symbols": [],
                            "market_data_failed_symbols": missing,
                            "trading_market_data_failed_symbols": sorted(
                                trading_symbols - covered
                            ),
                            "partial_bar_suppressed_until": to_iso(
                                first_complete_bar_open.astimezone(UTC)
                            ),
                            "subscription_target_count": len(target_symbols),
                            "validation_cycle_count": successful_fast_polls,
                            "poll_elapsed_ms": poll_elapsed_ms,
                        },
                    )
                    ready_emitted = True
                    became_ready_this_cycle = True
            elif consecutive_slow_polls >= 3:
                raise RuntimeError(
                    "sdk_snapshot_poll_latency_or_coverage_unhealthy:"
                    f"elapsed_ms={poll_elapsed_ms}:missing={len(missing)}"
                )
            received_at = datetime.now(UTC)
            # The first validated cycle was fetched while ready_emitted was
            # false, so emit it once as a full cycle. Later cycles are already
            # emitted batch-by-batch above.
            if became_ready_this_cycle:
                emit_worker(
                    queue_out,
                        {
                            "kind": "snapshots",
                            "poll_cycle_id": poll_cycle_id,
                            "cycle_complete": True,
                            "received_at": to_iso(received_at),
                        "rows": [
                            {
                                "symbol": symbol,
                                "payload": sdk_object_to_dict(row),
                            }
                            for symbol, row in rows_by_symbol.items()
                        ],
                    },
                )
            emit_worker(
                queue_out,
                {
                    "kind": "heartbeat",
                    "at": to_iso(received_at),
                    "market_data_mode": "sdk_snapshot_poll",
                    "poll_elapsed_ms": poll_elapsed_ms,
                    "poll_is_fast_and_complete": poll_is_fast_and_complete,
                    "poll_covered_count": len(covered),
                    "poll_missing_count": len(missing),
                    "successful_fast_polls": successful_fast_polls,
                    "total_poll_count": total_poll_count,
                    "failed_poll_count": failed_poll_count,
                    "consecutive_failures": consecutive_failures,
                    "last_success_at": last_success_at,
                    "last_failure_at": last_failure_at,
                    "first_batch_returned_at": last_first_batch_returned_at,
                    "first_batch_latency_ms": last_first_batch_latency_ms,
                    "first_batch_symbol_count": last_first_batch_symbol_count,
                },
            )
            remaining = (
                config.snapshot_poll_interval_seconds
                - (time.monotonic() - poll_started)
            )
            if remaining > 0:
                # The parent uses progress_value to distinguish a blocked SDK
                # call from a healthy worker.  Keep that progress fresh while
                # this worker is intentionally sleeping between polls; once the
                # next quote() starts, updates stop and the independent
                # liveness deadline still terminates a blocked native call.
                wait_deadline = time.monotonic() + remaining
                while not stop_event.is_set():
                    wait_remaining = wait_deadline - time.monotonic()
                    if wait_remaining <= 0:
                        break
                    if progress_value is not None:
                        progress_value.value = time.monotonic()
                    stop_event.wait(min(wait_remaining, 0.5))
    except BaseException as exc:
        emit_worker(
            queue_out,
            {
                "kind": "error",
                "reason": (
                    "sdk_quote_snapshot_worker_failed:"
                    f"{type(exc).__name__}:{exc}"
                ),
            },
        )


def daily_context_worker(config_path: str, symbols: list[str], task_id: str, queue_out: Any) -> None:
    """Fetch SDK daily bars outside the quote subscription process.

    Historical requests occasionally wait on a native SDK call.  Keeping them
    in a separate process means a timeout can be recovered without stopping
    the WebSocket feed or delaying a newly completed five-minute bar.
    """
    silence_sdk_worker_console()
    last_error: BaseException | None = None
    for connection_attempt, delay_seconds in enumerate((0, 2, 5), start=1):
        if delay_seconds:
            time.sleep(delay_seconds)
        try:
            config = load_config(config_path)
            sdk = require_sdk_contract()
            oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
            quote = sdk.QuoteContext(sdk_config_from_oauth(sdk, oauth, config.quote_region))
            rows, failures = fetch_daily_context_rows(
                quote,
                sdk,
                tuple(symbols),
                config.daily_context_bars,
                request_interval_seconds=(
                    HISTORICAL_CANDLESTICK_REQUEST_INTERVAL_SECONDS
                ),
            )
            for retry_delay in (2, 5):
                if not failures:
                    break
                time.sleep(retry_delay)
                retry_rows, failures = fetch_daily_context_rows(
                    quote,
                    sdk,
                    tuple(failures),
                    config.daily_context_bars,
                    request_interval_seconds=(
                        HISTORICAL_CANDLESTICK_REQUEST_INTERVAL_SECONDS
                    ),
                )
                rows.extend(retry_rows)
            emit_daily_context_result(
                queue_out,
                {
                    "kind": "daily_context_task_complete",
                    "task_id": task_id,
                    "rows": rows,
                    "failures": failures,
                    "connection_attempt": connection_attempt,
                },
            )
            return
        except BaseException as exc:
            last_error = exc
    emit_daily_context_result(
        queue_out,
        {
            "kind": "daily_context_error",
            "task_id": task_id,
            "symbols": symbols,
            "reason": (
                "sdk_daily_context_failed_after_backoff:"
                f"{type(last_error).__name__}:{last_error}"
            ),
        },
    )


def schedule_daily_context_retry(
    symbols: list[str],
    retry_counts: dict[str, int],
    retry_limit: int,
    pending: deque[list[str]],
    failed: list[str],
) -> None:
    retry_batch: list[str] = []
    for symbol in symbols:
        retry_counts[symbol] = retry_counts.get(symbol, 0) + 1
        if retry_counts[symbol] <= retry_limit:
            retry_batch.append(symbol)
        elif symbol not in failed:
            failed.append(symbol)
    if retry_batch:
        pending.append(retry_batch)


def daily_context_retry_cycle_due(
    state: str,
    failed_symbols: list[str] | tuple[str, ...],
    retry_not_before_monotonic: float,
    now_monotonic: float,
) -> bool:
    """Retry a failed daily batch without requiring a process restart."""
    return bool(
        state == "failed"
        and failed_symbols
        and float(now_monotonic) >= float(retry_not_before_monotonic)
    )


def intraday_context_worker(
    config_path: str,
    symbols: list[str],
    task_id: str,
    session_started_at: str,
    expected_last_close: str,
    queue_out: Any,
) -> None:
    """Fetch completed SDK five-minute bars as restart context only."""
    try:
        silence_sdk_worker_console()
        config = load_config(config_path)
        sdk = require_sdk_contract()
        oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
        quote = sdk.QuoteContext(sdk_config_from_oauth(sdk, oauth, config.quote_region))
        received_at = datetime.now(UTC)
        session_start = datetime.fromisoformat(session_started_at.replace("Z", "+00:00")).astimezone(UTC)
        expected_close = datetime.fromisoformat(expected_last_close.replace("Z", "+00:00")).astimezone(UTC)
        requested_bars = min(
            80,
            max(1, int((expected_close - session_start).total_seconds() // 300) + 2),
        )
        failures: list[str] = []
        for index, symbol in enumerate(symbols):
            symbol_rows: list[dict[str, Any]] = []
            symbol_failures: list[str] = []
            try:
                candles = quote.candlesticks(
                    symbol,
                    sdk.Period.Min_5,
                    requested_bars,
                    sdk.AdjustType.NoAdjust,
                )
                symbol_rows.extend(
                    event_rows_to_intraday_context(
                        symbol,
                        list(candles),
                        received_at,
                        bar_minutes=config.bar_minutes,
                        session_started_at=session_start,
                        expected_last_close=expected_close,
                    )
                )
            except Exception:
                failures.append(symbol)
                symbol_failures.append(symbol)
            emit_worker(
                queue_out,
                {
                    "kind": "intraday_context",
                    "task_id": task_id,
                    "rows": symbol_rows,
                    "failures": symbol_failures,
                    "completed_symbol": symbol,
                },
            )
            if index + 1 < len(symbols):
                time.sleep(HISTORICAL_CANDLESTICK_REQUEST_INTERVAL_SECONDS)
        emit_worker(
            queue_out,
            {
                "kind": "intraday_context_task_complete",
                "task_id": task_id,
                "failures": failures,
            },
        )
    except BaseException as exc:
        emit_worker(
            queue_out,
            {
                "kind": "intraday_context_error",
                "task_id": task_id,
                "symbols": symbols,
                "reason": f"sdk_intraday_context_failed:{type(exc).__name__}:{exc}",
            },
        )


def fetch_intraday_context_backfill(
    config: Any,
    process_context: Any,
    symbols: list[str],
    *,
    session_started_at: datetime,
    expected_last_close: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not symbols:
        return [], []
    queue_out: Any = process_context.Queue(maxsize=2048)
    pending: deque[list[str]] = deque([symbol] for symbol in symbols)
    active: dict[str, tuple[mp.Process, float, list[str]]] = {}
    rows: list[dict[str, Any]] = []
    failures: set[str] = set()
    completed: set[str] = set()
    completed_symbols: set[str] = set()
    # Longbridge permits one quote long connection per account. Each child owns
    # one QuoteContext, so history restoration must remain strictly serial.
    maximum_workers = 1
    overall_started_at = time.monotonic()
    try:
        while pending or active:
            if (
                time.monotonic() - overall_started_at
                > INTRADAY_CONTEXT_BACKFILL_TOTAL_DEADLINE_SECONDS
            ):
                failures.update(symbol for batch in pending for symbol in batch)
                failures.update(
                    symbol
                    for _process, _started_at, batch in active.values()
                    for symbol in batch
                )
                break
            while pending and len(active) < maximum_workers:
                batch = pending.popleft()
                task_id = f"intraday-{len(completed) + len(active):03d}-{batch[0]}"
                process = process_context.Process(
                    target=intraday_context_worker,
                    args=(
                        str(config.config_path),
                        batch,
                        task_id,
                        to_iso(session_started_at),
                        to_iso(expected_last_close),
                        queue_out,
                    ),
                    daemon=True,
                )
                process.start()
                active[task_id] = (process, time.monotonic(), batch)
            try:
                message = queue_out.get(timeout=0.2)
            except queue.Empty:
                message = {}
            kind = str(message.get("kind") or "")
            task_id = str(message.get("task_id") or "")
            if kind == "intraday_context":
                rows.extend(list(message.get("rows") or []))
                failures.update(str(value) for value in (message.get("failures") or []))
                completed_symbol = str(message.get("completed_symbol") or "")
                if completed_symbol:
                    completed_symbols.add(completed_symbol)
            elif kind == "intraday_context_task_complete":
                task = active.pop(task_id, None)
                if task is not None:
                    stop_spawned_process(task[0], graceful=True)
                completed.add(task_id)
            elif kind == "intraday_context_error":
                task = active.pop(task_id, None)
                task_symbols = task[2] if task is not None else list(message.get("symbols") or [])
                if task is not None:
                    stop_spawned_process(task[0], graceful=False)
                failures.update(str(value) for value in task_symbols)
                completed.add(task_id)
            for current_task_id, (process, started_at, task_symbols) in list(active.items()):
                if time.monotonic() - started_at <= config.daily_context_deadline_seconds:
                    continue
                stop_spawned_process(process, graceful=False)
                active.pop(current_task_id, None)
                failures.update(set(task_symbols) - completed_symbols)
                completed.add(current_task_id)
    finally:
        for process, _started_at, _symbols in active.values():
            stop_spawned_process(process, graceful=False)
        close_spawn_queue(queue_out)
    unique_rows = {
        str(row.get("event_id") or ""): row
        for row in rows
        if str(row.get("event_id") or "")
    }
    return sorted(
        unique_rows.values(),
        key=lambda row: (str(row.get("event_time") or ""), str(row.get("symbol") or "")),
    ), sorted(failures)


def verified_postclose_recovery_rows(
    fetched_rows: list[dict[str, Any]],
    existing_rows: list[dict[str, Any]],
    *,
    business_date: str,
) -> list[dict[str, Any]]:
    """Return missing SDK history rows for audit recovery, never dispatch.

    Recovered rows remain context-only.  They can prove that the stored OHLCV
    dataset is complete after close, but they never count as realtime stream
    evidence and must never be passed to the strategy router.
    """
    valid_existing_keys = {
        (
            str(row.get("symbol") or "").upper().removesuffix(".US"),
            str(row.get("event_time") or ""),
        )
        for row in existing_rows
        if str(row.get("timeframe") or "") == "5m"
        and row.get("bar_final") is True
        and not str(row.get("market_data_blocked_reason") or "")
        and (
            str(row.get("source_mode") or "")
            in {
                "longbridge_sdk_push",
                "longbridge_sdk_confirmed_candlestick",
                "longbridge_sdk_snapshot_poll",
            }
            or (
                row.get("context_only") is True
                and row.get("recovery_verified") is True
                and str(row.get("source_mode") or "")
                == "longbridge_sdk_intraday_recovery"
            )
        )
    }
    existing_ids = {
        str(row.get("event_id") or "")
        for row in existing_rows
        if str(row.get("event_id") or "")
    }
    recovered: list[dict[str, Any]] = []
    for row in fetched_rows:
        event_id = str(row.get("event_id") or "")
        key = (
            str(row.get("symbol") or "").upper().removesuffix(".US"),
            str(row.get("event_time") or ""),
        )
        recovery_event_id = f"{event_id}|recovery"
        if (
            not event_id
            or key in valid_existing_keys
            or recovery_event_id in existing_ids
        ):
            continue
        try:
            event_date = datetime.fromisoformat(
                str(row.get("event_time") or "").replace("Z", "+00:00")
            ).astimezone(NEW_YORK).date().isoformat()
        except ValueError:
            continue
        if event_date != business_date or row.get("context_only") is not True:
            continue
        recovered_row = dict(row)
        recovered_row.update(
            {
                "event_id": recovery_event_id,
                "recovery_source_event_id": event_id,
                "source_mode": "longbridge_sdk_intraday_recovery",
                "recovery_verified": True,
                "recovery_business_date": business_date,
                "recovery_reason": "postclose_session_gap_reconciliation",
                "strategy_dispatch_eligible": False,
                "historical_signal_replayed": False,
                "historical_order_replayed": False,
            }
        )
        recovered.append(recovered_row)
        existing_ids.add(recovery_event_id)
        valid_existing_keys.add(key)
    return sorted(
        recovered,
        key=lambda row: (str(row.get("event_time") or ""), str(row.get("symbol") or "")),
    )


def account_age_seconds(snapshot: dict[str, Any], *, now: datetime | None = None) -> int | None:
    value = str(snapshot.get("generated_at") or "")
    try:
        created = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    current = now or datetime.now(UTC)
    return max(0, int((current - created.astimezone(UTC)).total_seconds()))


def account_snapshot_ready_for_orders(
    snapshot: dict[str, Any],
    *,
    maximum_age_seconds: int,
    now: datetime | None = None,
) -> bool:
    age = account_age_seconds(snapshot, now=now)
    return bool(
        age is not None
        and age <= maximum_age_seconds
        and snapshot.get("paper_account_verified") is True
        and snapshot.get("positions_ok") is True
        and snapshot.get("orders_ok") is True
        and not snapshot.get("worker_circuit_open")
    )


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


def append_runtime_health_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())


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
    account_ready = account_snapshot_ready_for_orders(
        snapshot,
        maximum_age_seconds=config.maximum_account_snapshot_age_seconds,
        now=now,
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

    if not in_regular_session(now):
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
    if marker_status in {"active", "validation_active"}:
        validation_end_at = parse_utc_datetime(str(marker.get("validation_end_at") or ""))
        if (
            marker_status == "validation_active"
            and marker.get("validation_session") is True
            and validation_end_at is not None
            and now.astimezone(UTC) >= validation_end_at
        ):
            validation_test_epoch_id = str(
                marker.pop("validation_test_epoch_id", "") or ""
            )
            validation_short_test_epoch_id = str(
                marker.pop("validation_short_test_epoch_id", "") or ""
            )
            validation_test_started_at = str(
                marker.pop("validation_test_started_at", "") or ""
            )
            marker.update(
                {
                    "status": "pending_flatten",
                    "activation_blocker": "validation_session_ended_account_flatten_required",
                    "blocks_new_entries": True,
                    "validation_session": False,
                    "validation_completed_at": to_iso(now),
                    "last_validation_end_at": to_iso(validation_end_at),
                    "last_validation_test_epoch_id": validation_test_epoch_id,
                    "last_validation_short_test_epoch_id": validation_short_test_epoch_id,
                    "last_validation_test_started_at": validation_test_started_at,
                }
            )
            write_json_atomic(config.formal_test_marker_path, marker)
            marker_status = "pending_flatten"
        else:
            state = read_json_object(config.formal_test_epoch_state_path)
            if marker.get("blocks_new_entries") is not False:
                marker["blocks_new_entries"] = False
                marker["activation_blocker"] = ""
                write_json_atomic(config.formal_test_marker_path, marker)
            if marker_status == "validation_active":
                active_test_epoch_id = str(
                    marker.get("validation_test_epoch_id") or ""
                )
                active_short_test_epoch_id = str(
                    marker.get("validation_short_test_epoch_id") or ""
                )
                active_test_started_at = str(
                    marker.get("validation_test_started_at") or ""
                )
            else:
                active_test_epoch_id = str(marker.get("test_epoch_id") or "")
                active_short_test_epoch_id = str(
                    marker.get("short_test_epoch_id") or ""
                )
                active_test_started_at = str(marker.get("test_started_at") or "")
            canonical = {
                "test_epoch_id": active_test_epoch_id,
                "short_test_epoch_id": active_short_test_epoch_id,
                "status": marker_status,
                "test_started_at": active_test_started_at,
                "activated_at": str(
                    marker.get("validation_activated_at")
                    or marker.get("activated_at")
                    or active_test_started_at
                    or ""
                ),
                "blocks_new_entries": False,
                "validation_session": marker_status == "validation_active",
                "validation_business_date": str(marker.get("validation_business_date") or ""),
                "validation_end_at": str(marker.get("validation_end_at") or ""),
            }
            if canonical["test_started_at"] and any(state.get(key) != value for key, value in canonical.items()):
                state.update(canonical)
                state.setdefault("schema_version", "m15.sdk-runtime-auto-flatten.v1")
                state.setdefault("stage", "M15.sdk_runtime_auto_flatten")
                state["updated_at"] = to_iso(now)
                write_json_atomic(config.formal_test_epoch_state_path, state)
            return {
                "status": "preactivation_validation_active" if marker_status == "validation_active" else "inactive",
                "blocks_new_entries": False,
                "validation_end_at": str(marker.get("validation_end_at") or ""),
            }
    if marker_status != "pending_flatten":
        return {"status": "inactive", "blocks_new_entries": False}

    epoch_id = pending_flatten_test_epoch_id(marker)
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
    if not in_regular_session(now):
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
        snapshot.get("account_channel") == "lb_papertrading"
        and snapshot.get("paper_account_verified") is True
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
        validation_business_date = str(getattr(config, "validation_business_date", "") or "")
        validation_end_at = parse_utc_datetime(
            str(getattr(config, "validation_end_at", "") or "")
        )
        validation_window_open = (
            bool(validation_business_date)
            and validation_end_at is not None
            and market_date(now) == validation_business_date
            and in_regular_session(now)
            and now.astimezone(UTC) < validation_end_at
        )
        if validation_window_open:
            validation_suffix = validation_business_date.replace("-", "")
            validation_test_epoch_id = f"m15-sdk-validation-{validation_suffix}"
            validation_short_test_epoch_id = (
                f"m15-sdk-validation-short-{validation_suffix}"
            )
            active_marker = dict(marker)
            active_marker.update(
                {
                    "status": "validation_active",
                    "validation_session": True,
                    "validation_business_date": validation_business_date,
                    "validation_end_at": to_iso(validation_end_at),
                    "validation_test_epoch_id": validation_test_epoch_id,
                    "validation_short_test_epoch_id": validation_short_test_epoch_id,
                    "validation_test_started_at": to_iso(now),
                    "validation_activated_at": to_iso(now),
                    "activation_condition_met": "validation_session_auto_activated_after_flat_account",
                    "blocks_new_entries": False,
                }
            )
            write_json_atomic(config.formal_test_marker_path, active_marker)
            state["status"] = "validation_active"
            state["test_epoch_id"] = validation_test_epoch_id
            state["short_test_epoch_id"] = validation_short_test_epoch_id
            state["test_started_at"] = active_marker["validation_test_started_at"]
            state["activated_at"] = active_marker["validation_activated_at"]
            state["blocks_new_entries"] = False
            state["validation_session"] = True
            state["validation_business_date"] = validation_business_date
            state["validation_end_at"] = active_marker["validation_end_at"]
            write_json_atomic(config.formal_test_epoch_state_path, state)
            return {
                "status": "preactivation_validation_active",
                "blocks_new_entries": False,
                "validation_business_date": validation_business_date,
                "validation_end_at": active_marker["validation_end_at"],
            }
        activate_not_before = parse_utc_datetime(str(marker.get("activate_not_before") or ""))
        if activate_not_before is not None and now.astimezone(UTC) < activate_not_before:
            state["status"] = "waiting_for_activation_window"
            state["activate_not_before"] = to_iso(activate_not_before)
            state["blocks_new_entries"] = True
            state["last_flatten_test_epoch_id"] = epoch_id
            state["test_epoch_id"] = str(marker.get("test_epoch_id") or "")
            state["short_test_epoch_id"] = str(marker.get("short_test_epoch_id") or "")
            marker["activation_blocker"] = "waiting_for_configured_activation_time"
            marker["blocks_new_entries"] = True
            write_json_atomic(config.formal_test_marker_path, marker)
            write_json_atomic(config.formal_test_epoch_state_path, state)
            return state
        active_marker = activate_formal_epoch_payload(marker, activated_at=now)
        write_json_atomic(config.formal_test_marker_path, active_marker)
        state["status"] = active_marker["status"]
        state["test_epoch_id"] = str(active_marker.get("test_epoch_id") or "")
        state["short_test_epoch_id"] = str(active_marker.get("short_test_epoch_id") or "")
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

    broker_orders_by_id = {
        str(row.get("order_id") or row.get("id") or ""): row
        for key in ("orders", "historical_orders")
        for row in (snapshot.get(key) or [])
        if isinstance(row, dict) and str(row.get("order_id") or row.get("id") or "")
    }

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
            original_attempt = submissions[request_id]
            if not isinstance(original_attempt, dict):
                continue
            original_order_id = str(original_attempt.get("order_id") or "")
            broker_order = broker_orders_by_id.get(original_order_id, {})
            broker_status = str(broker_order.get("status") or "").strip().lower()
            if "." in broker_status:
                broker_status = broker_status.rsplit(".", 1)[-1]
            broker_symbol = str(broker_order.get("symbol") or "").upper()
            if broker_symbol and "." not in broker_symbol:
                broker_symbol = f"{broker_symbol}.US"
            executed_quantity: Decimal | None
            try:
                executed_quantity = Decimal(
                    str(
                        broker_order.get(
                            "executed_quantity",
                            broker_order.get("filled_quantity", broker_order.get("filled_qty")),
                        )
                    )
                )
            except (ArithmeticError, TypeError, ValueError):
                executed_quantity = None
            retry_allowed = (
                original_order_id
                and broker_status in {"canceled", "cancelled", "expired"}
                and executed_quantity == Decimal("0")
                and broker_symbol == str(payload.get("symbol") or "").upper()
                and not original_attempt.get("broker_terminal_retry_request_id")
            )
            if not retry_allowed:
                continue
            retry_payload = runtime_flatten_retry_order_payload(
                intent,
                test_epoch_id=epoch_id,
                retry_index=1,
            )
            retry_request_id = str(retry_payload["client_request_id"])
            original_attempt.update(
                {
                    "broker_terminal_status": broker_status,
                    "broker_terminal_order_id": original_order_id,
                    "broker_terminal_retry_request_id": retry_request_id,
                    "broker_terminal_retry_started_at": to_iso(now),
                }
            )
            retry_attempt = {
                "status": "market_submission_started",
                "started_at": to_iso(now),
                "symbol": retry_payload["symbol"],
                "side": retry_payload["side"],
                "quantity": retry_payload["quantity"],
                "signal_id": retry_payload["signal_id"],
                "client_request_id": retry_request_id,
                "fallback_attempted": False,
                "broker_terminal_retry_index": 1,
                "retried_from_order_id": original_order_id,
            }
            submissions[retry_request_id] = retry_attempt
            write_json_atomic(config.formal_test_epoch_state_path, state)
            try:
                retry_response = flatten_client.submit_order(retry_payload)
            except Exception as exc:
                retry_attempt.update(
                    {
                        "status": "submission_state_unknown",
                        "error": f"{type(exc).__name__}:{exc}"[:500],
                    }
                )
                state["status"] = "submission_state_unknown_waiting_reconciliation"
                write_json_atomic(config.formal_test_epoch_state_path, state)
                return state
            retry_order_id = str(retry_response.get("order_id") or "")
            retry_attempt.update(
                {
                    "status": str(retry_response.get("status") or "market_submission_unknown"),
                    "order_id": retry_order_id,
                    "primary_response": retry_response,
                }
            )
            append_account_flatten_submission_audit(
                config,
                retry_payload,
                retry_response,
                now=now,
            )
            submitted_now += 1
            if not retry_order_id:
                retry_attempt["status"] = "submission_state_unknown"
            write_json_atomic(config.formal_test_epoch_state_path, state)
            continue
        attempt = {
            "status": "market_submission_started",
            "started_at": to_iso(now),
            "symbol": payload["symbol"],
            "side": payload["side"],
            "quantity": payload["quantity"],
            "signal_id": payload["signal_id"],
            "client_request_id": request_id,
            "fallback_attempted": False,
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
        append_account_flatten_submission_audit(
            config,
            payload,
            response,
            now=now,
        )
        submitted_now += 1
        if response.get("explicit_reject") is True and not order_id:
            quote_age_ms = int(intent.get("fallback_quote_age_ms", -1) or -1)
            fallback_price = Decimal(str(intent.get("fallback_limit_price") or "0"))
            if 0 <= quote_age_ms <= 2000 and fallback_price > 0:
                fallback_payload = {
                    **payload,
                    "order_type": "limit",
                    "limit_price": str(intent["fallback_limit_price"]),
                }
                attempt["fallback_attempted"] = True
                attempt["fallback_status"] = "submission_started"
                write_json_atomic(config.formal_test_epoch_state_path, state)
                try:
                    fallback_response = flatten_client.submit_order(fallback_payload)
                except Exception as exc:
                    attempt.update({
                        "status": "fallback_state_unknown",
                        "fallback_status": "fallback_state_unknown",
                        "fallback_error": f"{type(exc).__name__}:{exc}"[:500],
                    })
                    state["status"] = "fallback_state_unknown_waiting_reconciliation"
                    write_json_atomic(config.formal_test_epoch_state_path, state)
                    return state
                fallback_order_id = str(fallback_response.get("order_id") or "")
                attempt.update({
                    "status": str(fallback_response.get("status") or "fallback_submission_unknown"),
                    "order_id": fallback_order_id,
                    "fallback_status": str(fallback_response.get("status") or "fallback_submission_unknown"),
                    "fallback_response": fallback_response,
                })
                append_account_flatten_submission_audit(
                    config,
                    fallback_payload,
                    fallback_response,
                    now=now,
                )
            else:
                attempt["status"] = "explicit_reject_without_fresh_fallback_quote"
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
        quote_state = quote_state_by_symbol.get(symbol) or {}
        boundary_state = {
            "open": latest.get("session_open_at_bar_close"),
            "high": latest.get("session_high_at_bar_close"),
            "low": latest.get("session_low_at_bar_close"),
            "close": latest.get("session_close_at_bar_close"),
            "volume": latest.get("session_volume_at_bar_close"),
            "source_event_at": latest.get("session_quote_source_at_bar_close"),
            "received_at": latest.get("received_at"),
            "session_date": session_date,
            "market_data_blocked_reason": latest.get("market_data_blocked_reason"),
        }
        use_boundary_state = all(
            boundary_state.get(key) not in (None, "")
            for key in ("open", "high", "low", "close", "source_event_at")
        )
        selected_state = boundary_state if use_boundary_state else quote_state
        if not selected_state or str(selected_state.get("market_data_blocked_reason") or ""):
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
                str(selected_state.get("source_event_at") or "").replace("Z", "+00:00")
            ).astimezone(UTC)
        except ValueError:
            continue
        if str(selected_state.get("session_date") or "") != session_date:
            continue
        if quote_source_at < latest_bar_open_at or quote_source_at > latest_bar_close_at:
            continue
        open_price = Decimal(str(selected_state.get("open") or "0"))
        high = Decimal(str(selected_state.get("high") or "0"))
        low = Decimal(str(selected_state.get("low") or "0"))
        close = Decimal(str(selected_state.get("close") or "0"))
        volume = int(str(selected_state.get("volume") or "0"))
        if min(open_price, high, low, close) <= 0 or volume < 0:
            continue
        daily_rows.append({
            "schema_version": "m15.realtime-market-event.v2",
            "event_id": f"sdk-1d-live|{symbol}|{session_date}|{latest_event_time}",
            "symbol": symbol,
            "timeframe": "1d",
            "event_time": latest_event_time,
            "received_at": str(selected_state.get("received_at") or latest.get("received_at") or to_iso(generated_at)),
            "source_event_at": str(selected_state.get("source_event_at") or latest.get("source_event_at") or latest_event_time),
            "bar_final": False,
            "current_session_confirmation": True,
            "source_mode": "longbridge_sdk_live_daily_confirmation",
            "daily_confirmation_snapshot": "completed_five_minute_bar_boundary" if use_boundary_state else "live_quote_state_fallback",
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


def active_event_ids_excluding_intraday_gaps(
    rows: list[dict[str, Any]],
    blocked_symbols: set[str] | None,
) -> set[str]:
    """Keep current events active while detectors enforce runtime-specific gaps.

    A single symbol-level block used to disable every five-minute runtime even
    after shorter-lookback strategies rebuilt valid context.  The compatibility
    argument remains for status reporting; each detector now owns its exact
    continuity requirement.
    """
    del blocked_symbols
    return {
        str(row.get("event_id") or "")
        for row in rows
        if str(row.get("event_id") or "")
    }


def five_minute_contract_context_status(
    rows: list[dict[str, Any]],
    symbols: tuple[str, ...] | list[str],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Summarize the exact continuity available to each five-minute contract."""
    expected = {
        str(symbol).upper().split(".")[0]
        for symbol in symbols
        if str(symbol)
    }
    current_date = now.astimezone(NEW_YORK).date()
    times_by_symbol: dict[str, set[datetime]] = {symbol: set() for symbol in expected}
    for row in rows:
        if str(row.get("timeframe") or "") != "5m" or row.get("bar_final") is not True:
            continue
        symbol = str(row.get("symbol") or "").upper().split(".")[0]
        if symbol not in expected:
            continue
        try:
            event_at = datetime.fromisoformat(
                str(row.get("event_time") or "").replace("Z", "+00:00")
            ).astimezone(UTC)
        except ValueError:
            continue
        if event_at.astimezone(NEW_YORK).date() == current_date:
            times_by_symbol[symbol].add(event_at)

    def trailing_count(values: list[datetime]) -> int:
        if not values:
            return 0
        count = 1
        for previous, current in zip(reversed(values[:-1]), reversed(values[1:])):
            if current - previous != timedelta(minutes=5):
                break
            count += 1
        return count

    pa002_ready = 0
    basic_short_ready = 0
    opening_range_ready = 0
    pa002_recovery_times: list[datetime] = []
    latest_bar_at = ""
    for values_set in times_by_symbol.values():
        values = sorted(values_set)
        trailing = trailing_count(values)
        if trailing >= 23:
            pa002_ready += 1
        if trailing >= 3:
            basic_short_ready += 1
        opening_contiguous = len(values) >= 6 and all(
            current - previous == timedelta(minutes=5)
            for previous, current in zip(values[:6], values[1:6])
        )
        trigger_context_contiguous = trailing >= 3
        first_ny = values[0].astimezone(NEW_YORK) if values else None
        if (
            len(values) >= 7
            and opening_contiguous
            and trigger_context_contiguous
            and first_ny is not None
            and (first_ny.hour, first_ny.minute) == (9, 35)
        ):
            opening_range_ready += 1
        if values:
            latest_bar_at = max(latest_bar_at, to_iso(values[-1]))
            pa002_recovery_times.append(
                values[-1] + timedelta(minutes=max(0, 23 - trailing) * 5)
            )

    total = len(expected)
    recovery_at = (
        to_iso(max(pa002_recovery_times))
        if pa002_ready < total and len(pa002_recovery_times) == total
        else ""
    )
    return {
        "generated_at": to_iso(now),
        "latest_complete_bar_at": latest_bar_at,
        "symbol_count": total,
        "pa002_5m_long": {
            "ready_symbol_count": pa002_ready,
            "required_symbol_count": total,
            "status": "ready" if pa002_ready == total else "recovering_contiguous_context",
            "minimum_contiguous_bars": 23,
            "expected_full_recovery_at": recovery_at,
        },
        "pa002_and_pa013_5m_short": {
            "ready_symbol_count": basic_short_ready,
            "required_symbol_count": total,
            "status": "ready" if basic_short_ready == total else "recovering_contiguous_context",
            "minimum_contiguous_bars": 3,
        },
        "pa012_5m_long_and_pa011_orb_short": {
            "ready_symbol_count": opening_range_ready,
            "required_symbol_count": total,
            "status": (
                "ready"
                if opening_range_ready == total
                else "recovering_opening_and_trigger_context"
            ),
            "requires_full_session_from_0935_new_york": False,
            "required_opening_contiguous_bars": 6,
            "required_trigger_contiguous_bars": 3,
        },
    }


def dispatch_completed_rows(
    config: Any,
    rows: list[dict[str, Any]],
    market_context: MarketEventContext,
    account_coordinator: SdkAccountCoordinator,
    paper_client: SdkRealtimePaperClient | None,
    *,
    daily_context_rows: list[dict[str, Any]] | None = None,
    live_quote_session_state: dict[str, dict[str, Any]] | None = None,
    signal_event_cache: list[dict[str, Any]] | None = None,
    signal_id_cache: set[str] | None = None,
    execution_ledger_cache: list[dict[str, Any]] | None = None,
    fill_attribution_state_cache: dict[str, Any] | None = None,
    intraday_context_blocked_symbols: set[str] | None = None,
    allow_new_entries: bool = True,
) -> dict[str, Any]:
    stage_started = time.perf_counter()
    ignored_context_rows = [
        row
        for row in rows
        if row.get("context_only") is True
        or row.get("strategy_dispatch_eligible") is False
    ]
    rows = [
        row
        for row in rows
        if row.get("context_only") is not True
        and row.get("strategy_dispatch_eligible") is not False
    ]
    if not rows:
        return {
            "event_count": 0,
            "signal_count": 0,
            "execution": {"submitted_count": 0},
            "ignored_context_only_count": len(ignored_context_rows),
        }
    rows = attach_next_bar_first_quotes(rows, live_quote_session_state or {})
    fresh = fresh_market_events(
        rows,
        config.maximum_source_delivery_age_ms,
        maximum_finalization_delay_ms=(
            getattr(config, "maximum_bar_finalization_delay_ms", 5000)
        ),
    )
    append_market_events(config.market_events_path, fresh, config.event_keep_lines)
    new_rows = market_context.append(fresh)
    if not new_rows:
        return {"event_count": 0, "signal_count": 0, "execution": {}}
    new_trading_rows = trading_market_events(config, new_rows)
    from scripts.m15_longbridge_realtime_signal_router_lib import load_config as load_router_config, run_realtime_signal_router
    from scripts.m15_longbridge_realtime_position_manager_lib import load_config as load_position_config, run_realtime_position_manager
    from scripts.m15_longbridge_realtime_execution_lib import load_config as load_execution_config, run_realtime_execution

    now = str(new_rows[-1]["received_at"])
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    formal_marker = load_formal_test_marker(config)
    marker_status = str(formal_marker.get("status") or "")
    validation_end_at = parse_utc_datetime(
        str(formal_marker.get("validation_end_at") or "")
    )
    validation_cutoff_reached = (
        marker_status == "validation_active"
        and validation_end_at is not None
        and now_dt.astimezone(UTC) >= validation_end_at
    )
    if marker_status == "pending_flatten" or validation_cutoff_reached:
        return {
            "event_count": len(fresh),
            "trading_event_count": len(new_trading_rows),
            "monitoring_only_event_count": len(new_rows) - len(new_trading_rows),
            "signal_count": 0,
            "live_daily_confirmation_count": 0,
            "router": {
                "status": (
                    "suppressed_validation_session_ended"
                    if validation_cutoff_reached
                    else "suppressed_pending_formal_epoch"
                )
            },
            "execution": {
                "status": (
                    "blocked_validation_session_ended"
                    if validation_cutoff_reached
                    else "blocked_pending_account_flatten"
                ),
                "submitted_count": 0,
            },
            "formal_test_epoch_id": str(formal_marker.get("test_epoch_id") or ""),
            "stage_latency_ms": {
                "router": 0,
                "position_manager": 0,
                "execution": 0,
                "total": int((time.perf_counter() - stage_started) * 1000),
            },
        }
    monitoring_market_rows = market_context.rows()
    trading_market_rows = trading_market_events(config, monitoring_market_rows)
    active_ids = active_event_ids_excluding_intraday_gaps(
        new_trading_rows,
        intraday_context_blocked_symbols,
    )
    live_daily_rows = build_live_daily_confirmation_rows(
        trading_market_rows,
        generated_at=now_dt,
        live_quote_session_state=live_quote_session_state,
        active_five_minute_event_ids={
            str(row.get("event_id") or "")
            for row in new_trading_rows
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
    if marker_status == "validation_active":
        active_test_epoch_id = str(
            formal_marker.get("validation_test_epoch_id") or ""
        )
        active_short_test_epoch_id = str(
            formal_marker.get("validation_short_test_epoch_id") or ""
        )
        active_test_started_at = str(
            formal_marker.get("validation_test_started_at") or ""
        )
    else:
        active_test_epoch_id = str(formal_marker.get("test_epoch_id") or "")
        active_short_test_epoch_id = str(
            formal_marker.get("short_test_epoch_id") or ""
        )
        active_test_started_at = str(formal_marker.get("test_started_at") or "")
    if formal_marker:
        router = replace(
            router,
            short_test_epoch_id=active_short_test_epoch_id,
            short_test_started_at=active_test_started_at,
        )
    emitted: list[dict[str, Any]] = []
    router_started = time.perf_counter()
    if allow_new_entries:
        router_payload = run_realtime_signal_router(
            router, generated_at=now, market_events_override=router_market_rows,
            active_market_event_ids=active_ids, emitted_signal_events=emitted,
            existing_signal_ids_override=signal_id_cache,
            existing_structure_ids_override={
                str(row.get("structure_instance_id") or "")
                for row in signal_event_cache
                if str(row.get("structure_instance_id") or "")
            },
        )
    else:
        router_payload = {
            "status": "blocked_incomplete_or_late_market_data_batch",
            "emitted_signal_count": 0,
        }
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
            test_epoch_id=active_test_epoch_id,
            test_started_at=active_test_started_at,
            short_test_epoch_id=active_short_test_epoch_id,
        )
    position_started = time.perf_counter()
    positions = run_realtime_position_manager(
        position_config,
        generated_at=now,
        account_state_override=snapshot,
        market_events_override=monitoring_market_rows,
        execution_rows_override=execution_ledger_cache,
        signal_events_override=signal_event_cache,
        fill_attribution_state_cache=fill_attribution_state_cache,
    )
    position_elapsed_ms = int((time.perf_counter() - position_started) * 1000)
    execution: dict[str, Any] = {}
    flatten_pending = str(formal_marker.get("status") or "") == "pending_flatten"
    dispatch_in_regular_session = in_regular_session(now_dt)
    exit_signals = list(positions.get("emitted_exit_signal_events", []))
    if exit_signals:
        signal_event_cache.extend(exit_signals)
        signal_id_cache.update(
            str(row.get("signal_id") or "")
            for row in exit_signals
            if row.get("signal_id")
        )
    execution_signals = emitted + exit_signals
    out_of_scope_signals = [
        signal
        for signal in execution_signals
        if not (
            signal.get("exit_only_position_signal") is True
            or signal.get("longbridge_position_exit_source") is True
        )
        if not market_event_is_tradable(config, signal)
    ]
    if out_of_scope_signals:
        execution = {
            "status": "blocked_signal_symbol_outside_trading_universe",
            "submitted_count": 0,
            "blocked_signal_count": len(out_of_scope_signals),
            "blocked_symbols": sorted({
                str(signal.get("symbol") or "")
                for signal in out_of_scope_signals
            }),
        }
    elif (
        paper_client is not None
        and not flatten_pending
        and dispatch_in_regular_session
        and execution_signals
    ):
        execution_config = load_execution_config(config.execution_config_path)
        if formal_marker:
            execution_config = replace(
                execution_config,
                test_epoch_id=active_test_epoch_id,
                short_test_epoch_id=active_short_test_epoch_id,
                short_test_started_at=active_test_started_at,
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
        execution_account_snapshot["fill_attributed_order_states"] = dict(
            positions.get("fill_attributed_order_states") or {}
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
        execution_ledger_cache.extend(execution_rows_emitted)
    elif paper_client is not None and not flatten_pending and dispatch_in_regular_session:
        execution = {
            "status": "no_new_realtime_signal",
            "submitted_count": 0,
            "blocked_signal_count": 0,
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
        "trading_event_count": len(new_trading_rows),
        "monitoring_only_event_count": len(new_rows) - len(new_trading_rows),
        "signal_count": len(emitted),
        "live_daily_confirmation_count": len(live_daily_rows),
        "router": router_payload,
        "execution": execution,
        "formal_test_epoch_id": str(formal_marker.get("test_epoch_id") or ""),
        "active_test_epoch_id": active_test_epoch_id,
        "new_entry_market_data_gate": {
            "eligible": allow_new_entries,
            "status": (
                "complete_timely"
                if allow_new_entries
                else "blocked_incomplete_or_late_market_data_batch"
            ),
        },
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
        "source_mode": "longbridge_sdk_only",
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


def process_resource_snapshot(pid: int | None = None) -> dict[str, int]:
    """Return bounded Linux process-resource telemetry for restart diagnostics."""
    target_pid = int(pid or os.getpid())
    fd_root = Path(f"/proc/{target_pid}/fd")
    try:
        fd_count = sum(1 for _ in fd_root.iterdir())
    except OSError:
        fd_count = -1
    child_count = 0
    resource_tracker_count = 0
    try:
        proc_entries = list(Path("/proc").iterdir())
    except OSError:
        proc_entries = []
    for entry in proc_entries:
        if not entry.name.isdigit():
            continue
        try:
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
        except (OSError, StopIteration, ValueError):
            continue
        if parent_pid != target_pid:
            continue
        child_count += 1
        try:
            command = (entry / "cmdline").read_text(
                encoding="utf-8", errors="ignore"
            ).replace("\x00", " ")
        except OSError:
            command = ""
        if "multiprocessing.resource_tracker" in command:
            resource_tracker_count += 1
    return {
        "fd_count": fd_count,
        "child_process_count": child_count,
        "resource_tracker_child_count": resource_tracker_count,
    }


def session_requires_postclose_recovery(coverage: dict[str, Any]) -> bool:
    """Recover missing data, not an otherwise complete but late realtime session."""
    return bool(
        int(coverage.get("missing_boundary_count") or 0) > 0
        or int(coverage.get("partial_boundary_count") or 0) > 0
        or int(coverage.get("invalid_row_count") or 0) > 0
    )


def finalize_postclose_recovery_status(
    recovery_status: dict[str, Any],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    """Finalize recovery without hiding worker failures or inventing realtime evidence."""
    result = dict(recovery_status)
    complete = bool(coverage.get("data_complete_after_recovery"))
    result["data_complete_after_recovery"] = complete
    result["residual_missing_boundary_count"] = int(
        coverage.get("recovered_missing_boundary_count") or 0
    )
    result["residual_partial_boundary_count"] = int(
        coverage.get("recovered_partial_boundary_count") or 0
    )
    result["recovery_counts_as_realtime_evidence"] = False
    if complete:
        if result.get("failed_symbols"):
            result["worker_failures_after_complete_coverage"] = list(
                result.get("failed_symbols") or []
            )
        result["status"] = "completed"
    else:
        result["status"] = "completed_incomplete_data"
    return result


def request_runtime_shutdown(
    pid: int,
    *,
    timeout_seconds: float = 5.0,
    force_timeout_seconds: float = 2.0,
) -> bool:
    """Stop the SDK runtime, escalating only for the expected runtime process."""
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
    """Identify a live runtime whose own health outputs have stopped advancing."""
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
    try:
        recent_market_data_restarts = int(
            status.get("market_data_worker_recent_restart_count") or 0
        )
    except (TypeError, ValueError):
        recent_market_data_restarts = 0
    snapshot_recovery_has_progress = bool(
        str(status.get("market_data_mode") or "") == "sdk_snapshot_poll"
        and (
            int(status.get("snapshot_poll_successful_fast_polls") or 0) > 0
            or int(status.get("snapshot_poll_covered_count") or 0) > 0
            or int(status.get("snapshot_row_count") or 0) > 0
        )
    )
    if (
        str(status.get("status") or "")
        in {"connecting", "reconnecting_market_data_circuit"}
        and status.get("sdk_connected") is False
        and recent_market_data_restarts >= 3
        and not snapshot_recovery_has_progress
    ):
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


def completed_postclose_refresh_dates(
    cached_daily_rows: list[dict[str, Any]],
    now_ny: datetime,
) -> set[str]:
    """Avoid throwing away a validated current-session cache after a restart."""
    if (
        cached_daily_rows
        and now_ny.weekday() < 5
        and (now_ny.hour, now_ny.minute) >= (16, 10)
    ):
        return {now_ny.date().isoformat()}
    return set()


def latest_completed_intraday_close(now_ny: datetime, bar_minutes: int) -> datetime:
    """Return zero session progress outside a weekday US session."""
    session_start = now_ny.replace(
        hour=9, minute=30, second=0, microsecond=0
    ).astimezone(UTC)
    if now_ny.weekday() >= 5 or (now_ny.hour, now_ny.minute) < (9, 30):
        return session_start
    session_end = now_ny.replace(
        hour=16, minute=0, second=0, microsecond=0
    ).astimezone(UTC)
    return min(
        floor_bar_open(now_ny, bar_minutes).astimezone(UTC),
        session_end,
    )


def run_watch(config: Any, *, dispatch_requested: bool) -> int:
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
    process_resource_baseline = process_resource_snapshot()
    sdk = require_sdk_contract()
    run_id = f"sdk-{uuid.uuid4().hex[:12]}"
    loaded_config_fingerprint = config_fingerprint(config)
    loaded_source_fingerprint = LOADED_RUNTIME_SOURCE_FINGERPRINT
    previous_runtime_status = read_json_object(config.runtime_status_path)
    readonly_gate_passed_now, readonly_sessions_passed, readonly_sessions_required = readonly_gate_passed(config.readonly_gate_path)
    expansion_gate_path = config.output_dir / "m15_sdk_expansion_readonly_gate.json"
    expansion_gate_passed, expansion_sessions_passed, expansion_sessions_required = readonly_gate_passed(
        expansion_gate_path,
        required_sessions=1,
    )
    dispatch_enabled = bool(
        dispatch_requested
        and config.paper_order_dispatch_enabled
        and (not config.two_day_readonly_gate or readonly_gate_passed_now)
    )
    build_status(
        config,
        status="starting_context_restore",
        reason="restoring_sdk_daily_and_intraday_context",
        sdk_installed=True,
        oauth_client_id_present=True,
        extra={
            "run_id": run_id,
            "runtime_pid": os.getpid(),
            "dispatch_enabled": False,
            "dispatch_requested": dispatch_requested,
            "config_fingerprint": loaded_config_fingerprint,
            "runtime_source_fingerprint": loaded_source_fingerprint,
            "startup_context_restore_in_progress": True,
        },
    )

    def publish_startup_stage(stage: str) -> None:
        build_status(
            config,
            status="starting_context_restore",
            reason=stage,
            sdk_installed=True,
            oauth_client_id_present=True,
            extra={
                "run_id": run_id,
                "runtime_pid": os.getpid(),
                "dispatch_enabled": False,
                "dispatch_requested": dispatch_requested,
                "config_fingerprint": loaded_config_fingerprint,
                "runtime_source_fingerprint": loaded_source_fingerprint,
                "startup_context_restore_in_progress": True,
                "startup_stage": stage,
            },
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

    # PyO3 SDK contexts must not be inherited through fork.  Use spawned
    # workers for both historical context recovery and the live quote owner.
    process_context = mp.get_context("spawn")
    market_data_worker_progress = process_context.Value("d", time.monotonic())

    publish_startup_stage("starting_account_context")
    account = SdkAccountProcessCoordinator(
        partial(build_sdk_account_provider_for_worker, str(config.config_path)),
        config.output_dir / "m15_longbridge_realtime_account_state.json",
        interval_seconds=config.account_snapshot_interval_seconds,
        refresh_deadline_seconds=config.account_snapshot_refresh_deadline_seconds,
        circuit_retry_cooldown_seconds=config.account_snapshot_circuit_retry_seconds,
    )
    account.start()
    publish_startup_stage("starting_trade_context")
    # Keep the full 60-day cache for all subscribed symbols plus a bounded
    # intraday tail.  The old 4096-row cap silently discarded daily context
    # before the daily strategies could consume it.
    cached_daily_rows = load_valid_daily_context_cache(config.daily_context_path, config, datetime.now(UTC))
    now_ny = datetime.now(NEW_YORK)
    session_started_at = now_ny.replace(hour=9, minute=30, second=0, microsecond=0).astimezone(UTC)
    cached_intraday_rows = load_current_sdk_intraday_context(
        config.market_events_path,
        session_started_at,
    )
    latest_completed_close = latest_completed_intraday_close(
        now_ny,
        config.bar_minutes,
    )
    completed_bar_count = max(
        0,
        int((latest_completed_close - session_started_at).total_seconds() // (config.bar_minutes * 60)),
    )
    required_intraday_bars = min(78, completed_bar_count)
    intraday_backfill_requested_symbols: list[str] = []
    intraday_backfill_failed_symbols: list[str] = []
    intraday_backfill_row_count = 0
    if required_intraday_bars > 0:
        intraday_backfill_requested_symbols = symbols_missing_contiguous_intraday_context(
            cached_intraday_rows,
            configured_trading_symbols(config),
            expected_last_close=latest_completed_close,
            required_bars=required_intraday_bars,
        )
        intraday_backfill_failed_symbols = list(
            intraday_backfill_requested_symbols
        )
    residual_intraday_context_gaps = (
        symbols_missing_contiguous_intraday_context(
            cached_intraday_rows,
            configured_trading_symbols(config),
            expected_last_close=latest_completed_close,
            required_bars=required_intraday_bars,
        )
        if required_intraday_bars > 0
        else []
    )
    execution_trade, paper_client, flatten_client = build_sdk_trade_clients(
        config,
        sdk,
        execution_request_gate,
        account.note_submission,
        dispatch_enabled=dispatch_enabled,
    )
    publish_startup_stage("restoring_market_data_context")
    context = MarketEventContext(
        maximum_rows=(
            len(configured_trading_symbols(config)) * config.daily_context_bars
        )
        + (len(configured_trading_symbols(config)) * 78)
        + 4096
    )
    context.append(trading_market_events(config, cached_daily_rows))
    context.append(trading_market_events(config, cached_intraday_rows))
    five_minute_strategy_context = five_minute_contract_context_status(
        context.rows(),
        configured_trading_symbols(config),
        now=datetime.now(UTC),
    )
    intraday_context_event_ids = {
        str(row.get("event_id") or "")
        for row in cached_intraday_rows
        if str(row.get("event_id") or "")
    }
    live_quote_session_state: dict[str, dict[str, Any]] = {}
    last_quote_snapshot_write = 0.0
    process_resource_current = process_resource_baseline
    last_process_resource_snapshot = 0.0
    # The live quote WebSocket also owns a fresh native runtime.
    message_queue: Any = process_context.Queue(maxsize=2048)
    stop_event: Any = process_context.Event()
    worker: mp.Process | None = None
    attempts = 0
    worker_ready = False
    worker_started = 0.0
    worker_last_progress = 0.0
    worker_ready_since = 0.0
    subscription_progress_completed = 0
    subscription_progress_total = len(
        quote_subscription_targets(config, datetime.now(UTC))
    )
    quote_context_warmups: list[dict[str, Any]] = []
    restored_latency_samples, restored_last_result, restored_last_event_at = restore_pipeline_observability(
        config.runtime_status_path,
        now=datetime.now(UTC),
    )
    last_event_at = restored_last_event_at
    last_compaction = 0.0
    last_order_maintenance = 0.0
    last_trade_context_healthcheck = time.monotonic()
    next_trade_context_retry = 0.0
    trade_context_health: dict[str, Any] = {
        "ok": paper_client is not None,
        "status": (
            "trade_context_initialized"
            if paper_client is not None
            else "trade_context_missing"
        ),
        "trade_context_refresh_required": paper_client is None,
    }
    last_result: dict[str, Any] = restored_last_result
    confirmed_boundary_gate: dict[str, Any] = {
        "status": "not_applicable_outside_regular_session",
        "boundary": "",
        "required_symbol_count": len(configured_trading_symbols(config)),
        "received_symbol_count": 0,
        "missing_symbols": [],
        "new_position_submission_enabled": None,
    }
    order_maintenance: dict[str, Any] = {}
    flatten_transition: dict[str, Any] = {}
    authorized_account_exit: dict[str, Any] = {}
    capital_bucket_migration: dict[str, Any] = {}
    pipeline_latency_samples: deque[int] = deque(restored_latency_samples, maxlen=200)
    daily_rows: list[dict[str, Any]] = list(cached_daily_rows)
    subscription_failed: list[str] = []
    trading_subscription_failed: list[str] = []
    confirmed_candlestick_failed: list[str] = []
    confirmed_candlestick_coverage = (
        f"0/{len(quote_subscription_targets(config, datetime.now(UTC)))}"
    )
    daily_failed: list[str] = []
    daily_workers: dict[str, tuple[mp.Process, float, list[str]]] = {}
    daily_pending: deque[list[str]] = deque()
    daily_completed: set[str] = set()
    daily_retry_counts: dict[str, int] = {}
    daily_task_failures: dict[str, list[str]] = {}
    daily_context_state = "complete" if cached_daily_rows else "waiting_for_subscription"
    daily_context_cache_reused = bool(cached_daily_rows)
    daily_context_persisted = bool(cached_daily_rows)
    daily_context_retry_cycle_count = 0
    daily_context_retry_not_before_monotonic = 0.0
    observed_regular_sessions: set[str] = set()
    observed_expansion_sessions: set[str] = set()
    postclose_daily_refresh_dates = completed_postclose_refresh_dates(cached_daily_rows, now_ny)
    persisted_postclose_recovery = read_json_object(
        config.output_dir / POSTCLOSE_RECOVERY_STATE_JSON
    )
    postclose_recovery_source = previous_runtime_status
    if persisted_postclose_recovery:
        postclose_recovery_source = {
            "postclose_intraday_recovery": persisted_postclose_recovery
        }
    (
        postclose_recovery_attempted_dates,
        postclose_recovery_status,
    ) = restored_postclose_recovery_state(postclose_recovery_source)
    last_persisted_postclose_recovery = (
        json.dumps(
            persisted_postclose_recovery,
            sort_keys=True,
            separators=(",", ":"),
        )
        if persisted_postclose_recovery
        else ""
    )
    postclose_recovery_workers: dict[str, tuple[mp.Process, float, list[str]]] = {}
    postclose_recovery_pending: deque[list[str]] = deque()
    postclose_recovery_task_sequence = 0

    def start_next_postclose_recovery_batch() -> bool:
        nonlocal postclose_recovery_task_sequence
        if postclose_recovery_workers or not postclose_recovery_pending:
            return False
        batch = postclose_recovery_pending.popleft()
        session_started_at = parse_utc_datetime(
            str(postclose_recovery_status.get("session_started_at") or "")
        )
        expected_last_close = parse_utc_datetime(
            str(postclose_recovery_status.get("expected_last_close") or "")
        )
        if session_started_at is None or expected_last_close is None:
            postclose_recovery_status["status"] = "completed_with_failures"
            postclose_recovery_status["last_error"] = (
                "postclose_recovery_session_boundary_missing"
            )
            return False
        postclose_recovery_task_sequence += 1
        task_id = (
            f"postclose-recovery-"
            f"{postclose_recovery_status.get('business_date') or 'unknown'}-"
            f"{postclose_recovery_task_sequence:02d}"
        )
        recovery_worker = process_context.Process(
            target=intraday_context_worker,
            args=(
                str(config.config_path),
                batch,
                task_id,
                to_iso(session_started_at),
                to_iso(expected_last_close),
                message_queue,
            ),
            daemon=True,
        )
        recovery_worker.start()
        postclose_recovery_workers[task_id] = (
            recovery_worker,
            time.monotonic(),
            batch,
        )
        postclose_recovery_status["active_task_id"] = task_id
        postclose_recovery_status["pending_batch_count"] = len(
            postclose_recovery_pending
        )
        return True

    def advance_postclose_recovery() -> None:
        if postclose_recovery_workers:
            return
        if postclose_recovery_pending:
            start_next_postclose_recovery_batch()
            return
        failed_symbols = sorted(
            set(postclose_recovery_status.get("failed_symbols") or [])
        )
        if (
            failed_symbols
            and int(postclose_recovery_status.get("retry_round") or 0) < 1
        ):
            postclose_recovery_status["retry_round"] = 1
            postclose_recovery_pending.extend(
                [symbol]
                for symbol in failed_symbols
            )
            start_next_postclose_recovery_batch()
            return
        postclose_recovery_status["status"] = (
            "completed_with_failures" if failed_symbols else "completed"
        )
        postclose_recovery_status["completed_at"] = to_iso(datetime.now(UTC))
        postclose_recovery_status["active_task_id"] = ""
        postclose_recovery_status["pending_batch_count"] = 0
    deferred_messages: deque[dict[str, Any]] = deque()
    partial_bar_suppressed_until = ""
    last_subscription_failure_reason = ""
    snapshot_fallback_active = bool(
        config.allow_snapshot_poll_fallback
        and (
            config.prefer_snapshot_poll
            or validated_snapshot_poll_is_reusable(
                previous_runtime_status,
                len(quote_subscription_targets(config, datetime.now(UTC))),
                now=datetime.now(UTC),
            )
        )
    )
    market_data_mode = (
        "sdk_snapshot_poll" if snapshot_fallback_active else "sdk_subscription"
    )
    subscription_recovery_failures = 0
    market_data_symbols: set[str] = set()
    market_data_failed: list[str] = []
    trading_market_data_failed: list[str] = []
    snapshot_poll_elapsed_ms = 0
    market_data_fallback_validated = snapshot_fallback_active
    snapshot_bar_builder: FiveMinuteBarBuilder | None = None
    snapshot_boundary_gate: ConfirmedBoundaryBatchGate | None = None
    snapshot_batch_count = 0
    snapshot_row_count = 0
    snapshot_completed_bar_count = 0
    snapshot_poll_cycle_id = ""
    snapshot_poll_cycle_completed_bars: list[dict[str, Any]] = []
    snapshot_poll_covered_count = 0
    snapshot_poll_missing_count = 0
    snapshot_poll_successful_fast_polls = 0
    snapshot_poll_is_fast_and_complete = False
    snapshot_poll_total_count = 0
    snapshot_poll_failure_count = 0
    snapshot_poll_consecutive_failures = 0
    snapshot_poll_last_success_at = ""
    snapshot_poll_last_failure_at = ""
    snapshot_poll_first_batch_returned_at = ""
    snapshot_poll_first_batch_latency_ms = 0
    snapshot_poll_first_batch_symbol_count = 0
    snapshot_was_previously_ready = False
    session_close_flush_dates: set[str] = set()
    session_close_flush_status: dict[str, Any] = {
        "status": "waiting_for_session_close",
        "historical_signal_replayed": False,
        "historical_order_replayed": False,
    }
    last_market_data_worker_error = ""
    market_data_worker_restart_events: deque[dict[str, Any]] = deque(maxlen=20)
    market_data_worker_restart_times: deque[float] = deque(maxlen=100)
    market_data_worker_restart_total = 0
    market_data_worker_recent_restart_count = 0
    last_market_data_health_signature = ""
    market_data_applied_heartbeat_deadline_seconds = float(
        config.market_data_heartbeat_deadline_seconds
    )
    last_subscription_quote_monotonic = 0.0
    subscription_quote_silence_fallback_count = 0
    primary_subscription_reprobe_dates: set[str] = set()
    last_primary_subscription_reprobe_at = ""
    snapshot_fallback_not_before_monotonic = 0.0

    def record_market_data_worker_restart(
        reason: str,
        *,
        exit_code: int | None = None,
    ) -> None:
        nonlocal market_data_worker_restart_total
        market_data_worker_restart_total += 1
        market_data_worker_restart_times.append(time.monotonic())
        event = {
            "schema_version": "m15.sdk-market-data-health.v1",
            "event_type": "market_data_worker_restart",
            "at": to_iso(datetime.now(UTC)),
            "run_id": run_id,
            "runtime_pid": os.getpid(),
            "reason": reason,
            "exit_code": exit_code,
            "market_data_mode": market_data_mode,
        }
        market_data_worker_restart_events.append(event)
        append_runtime_health_event(
            config.output_dir / MARKET_DATA_HEALTH_LEDGER_JSONL,
            event,
        )
    publish_startup_stage("starting_market_data_worker")
    intraday_repair_status: dict[str, Any] = {
        "status": "not_required",
        "row_count": 0,
        "failed_symbols": [],
    }
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
    shutdown_requested = False

    def stop_requested(_signum: int, _frame: Any) -> None:
        nonlocal shutdown_requested
        shutdown_requested = True

    signal.signal(signal.SIGTERM, stop_requested)
    try:
        while not shutdown_requested:
            gate_now = datetime.now(UTC)
            gate_now_ny = gate_now.astimezone(NEW_YORK)
            gate_boundary = str(confirmed_boundary_gate.get("boundary") or "")
            try:
                gate_boundary_date = (
                    datetime.fromisoformat(gate_boundary.replace("Z", "+00:00"))
                    .astimezone(NEW_YORK)
                    .date()
                    .isoformat()
                )
            except ValueError:
                gate_boundary_date = ""
            if not in_regular_session(gate_now):
                confirmed_boundary_gate = {
                    "status": "not_applicable_outside_regular_session",
                    "boundary": "",
                    "required_symbol_count": len(
                        configured_trading_symbols(config)
                    ),
                    "received_symbol_count": 0,
                    "missing_symbols": [],
                    "new_position_submission_enabled": None,
                }
            elif gate_boundary_date != gate_now_ny.date().isoformat():
                confirmed_boundary_gate = {
                    "status": "waiting_for_first_complete_boundary",
                    "boundary": "",
                    "required_symbol_count": len(
                        configured_trading_symbols(config)
                    ),
                    "received_symbol_count": 0,
                    "missing_symbols": [],
                    "new_position_submission_enabled": None,
                }
            reprobe_business_date = (
                ""
                if config.prefer_snapshot_poll
                else primary_subscription_reprobe_date(
                    snapshot_fallback_active,
                    primary_subscription_reprobe_dates,
                    datetime.now(UTC),
                )
            )
            if reprobe_business_date:
                primary_subscription_reprobe_dates.add(reprobe_business_date)
                last_primary_subscription_reprobe_at = to_iso(datetime.now(UTC))
                append_runtime_health_event(
                    config.output_dir / MARKET_DATA_HEALTH_LEDGER_JSONL,
                    {
                        "schema_version": "m15.sdk-market-data-health.v1",
                        "event_type": "primary_subscription_reprobe",
                        "at": last_primary_subscription_reprobe_at,
                        "business_date": reprobe_business_date,
                        "run_id": run_id,
                        "runtime_pid": os.getpid(),
                    },
                )
                if worker is not None:
                    stop_spawned_process(worker, graceful=False)
                worker = None
                worker_ready = False
                worker_ready_since = 0.0
                snapshot_fallback_active = False
                snapshot_bar_builder = None
                snapshot_boundary_gate = None
                market_data_mode = "sdk_subscription"
                market_data_fallback_validated = False
                attempts = 0
                continue
            if (
                postclose_recovery_status.get("status") != "running"
                and daily_context_state == "complete"
                and (worker is None or not worker.is_alive())
            ):
                if (
                    snapshot_fallback_active
                    and time.monotonic() < snapshot_fallback_not_before_monotonic
                ):
                    stop_event.wait(
                        min(
                            1.0,
                            snapshot_fallback_not_before_monotonic
                            - time.monotonic(),
                        )
                    )
                    continue
                if worker is not None:
                    worker.join(timeout=0.2)
                    buffer_pending_market_data_progress(
                        message_queue,
                        deferred_messages,
                        now_monotonic=time.monotonic(),
                    )
                    worker_error = pop_deferred_worker_error(deferred_messages)
                    worker_exit_reason = str(
                        (worker_error or {}).get("reason")
                        or "worker_process_exited"
                    )
                    record_market_data_worker_restart(
                        worker_exit_reason,
                        exit_code=worker.exitcode,
                    )
                    last_subscription_failure_reason = worker_exit_reason
                    if worker_error is not None:
                        last_market_data_worker_error = worker_exit_reason
                    attempts += 1
                if (
                    not snapshot_fallback_active
                    and config.allow_snapshot_poll_fallback
                    and should_use_snapshot_fallback(
                        attempts,
                        config.subscription_failures_before_snapshot_fallback,
                    )
                ):
                    snapshot_fallback_active = True
                    snapshot_fallback_not_before_monotonic = (
                        time.monotonic()
                        + SNAPSHOT_FALLBACK_HANDOFF_COOLDOWN_SECONDS
                    )
                    subscription_recovery_failures += attempts
                    attempts = 0
                if attempts >= config.maximum_consecutive_subscription_failures:
                    if snapshot_fallback_active:
                        build_status(
                            config,
                            status="reconnecting_market_data_circuit",
                            reason="sdk_snapshot_recovery_cooldown",
                            sdk_installed=True,
                            oauth_client_id_present=True,
                            extra={
                                "run_id": run_id,
                                "runtime_pid": os.getpid(),
                                "dispatch_enabled": False,
                                "dispatch_requested": dispatch_requested,
                                "config_fingerprint": loaded_config_fingerprint,
                                "runtime_source_fingerprint": loaded_source_fingerprint,
                                "worker_attempts": attempts,
                                "last_subscription_failure_reason": last_subscription_failure_reason,
                                "market_data_mode": "sdk_snapshot_poll",
                                "market_data_circuit_open": True,
                                "market_data_retry_after_seconds": (
                                    config.account_snapshot_circuit_retry_seconds
                                ),
                            },
                        )
                        stop_event.wait(
                            config.account_snapshot_circuit_retry_seconds
                        )
                        attempts = 0
                        continue
                    build_status(
                        config,
                        status="halted_subscription_failures",
                        reason="sdk_subscription_recovery_limit_reached",
                        sdk_installed=True,
                        oauth_client_id_present=True,
                        extra={
                            "run_id": run_id,
                            "runtime_pid": os.getpid(),
                            "dispatch_enabled": False,
                            "dispatch_requested": dispatch_requested,
                            "config_fingerprint": loaded_config_fingerprint,
                            "runtime_source_fingerprint": loaded_source_fingerprint,
                            "worker_attempts": attempts,
                            "last_subscription_failure_reason": last_subscription_failure_reason,
                        },
                    )
                    return 2
                if snapshot_fallback_active and snapshot_bar_builder is None:
                    snapshot_started_at = datetime.now(UTC)
                    snapshot_first_complete_bar_open = floor_bar_open(
                        snapshot_started_at, config.bar_minutes
                    ) + timedelta(minutes=config.bar_minutes)
                    snapshot_bar_builder = FiveMinuteBarBuilder(
                        config.bar_minutes,
                        complete_bar_open_not_before=snapshot_first_complete_bar_open,
                    )
                    snapshot_boundary_gate = ConfirmedBoundaryBatchGate(
                        configured_trading_symbols(config),
                        maximum_source_delivery_age_ms=(
                            config.maximum_source_delivery_age_ms
                        ),
                        maximum_finalization_delay_ms=(
                            config.maximum_bar_finalization_delay_ms
                        ),
                    )
                    partial_bar_suppressed_until = to_iso(
                        snapshot_first_complete_bar_open.astimezone(UTC)
                    )
                    if in_regular_session(snapshot_started_at):
                        (
                            residual_intraday_context_gaps,
                            intraday_repair_status,
                        ) = deferred_intraday_context_after_mid_session_start(
                            residual_intraday_context_gaps,
                            suppressed_until=partial_bar_suppressed_until,
                        )
                worker_ready = False
                worker_started = time.monotonic()
                worker_last_progress = worker_started
                last_subscription_quote_monotonic = 0.0
                subscription_progress_completed = 0
                subscription_progress_total = len(
                    quote_subscription_targets(config, datetime.now(UTC))
                )
                worker_target = (
                    quote_snapshot_worker
                    if snapshot_fallback_active
                    else quote_worker
                )
                worker_args: tuple[Any, ...] = (
                    str(config.config_path),
                    message_queue,
                    stop_event,
                    market_data_worker_progress,
                )
                worker = process_context.Process(
                    target=worker_target,
                    args=worker_args,
                    daemon=True,
                )
                market_data_worker_progress.value = time.monotonic()
                worker.start()
                worker_ready_since = 0.0
            if postclose_recovery_status.get("status") == "running":
                # A bounded post-close history repair intentionally owns the
                # only quote context.  Do not classify the absent realtime
                # worker as a startup or heartbeat failure during this phase.
                worker_last_progress = time.monotonic()
            queued_progress_at = buffer_pending_market_data_progress(
                message_queue,
                deferred_messages,
                now_monotonic=time.monotonic(),
            )
            if queued_progress_at:
                worker_last_progress = queued_progress_at
            worker_last_progress = effective_worker_progress(
                worker_last_progress,
                market_data_worker_progress.value,
            )
            market_data_worker_recent_restart_count = recent_restart_count(
                market_data_worker_restart_times,
                time.monotonic(),
                120,
            )
            market_data_applied_heartbeat_deadline_seconds = (
                active_market_data_progress_deadline_seconds(
                    market_data_mode,
                    worker_ready,
                    base_deadline_seconds=(
                        config.market_data_heartbeat_deadline_seconds
                    ),
                    recovery_deadline_seconds=(
                        config.snapshot_poll_recovery_deadline_seconds
                    ),
                    recent_restarts=market_data_worker_recent_restart_count,
                    now=datetime.now(UTC),
                    bar_minutes=config.bar_minutes,
                    snapshot_dispatch_max_elapsed_ms=(
                        config.snapshot_poll_dispatch_max_elapsed_ms
                    ),
                )
            )
            startup_deadline_seconds = market_data_worker_startup_deadline_seconds(
                snapshot_fallback_active,
                config.subscription_deadline_seconds,
                config.snapshot_poll_recovery_deadline_seconds,
                snapshot_was_previously_ready=snapshot_was_previously_ready,
                snapshot_dispatch_max_elapsed_ms=(
                    config.snapshot_poll_dispatch_max_elapsed_ms
                ),
            )
            if (
                worker is not None
                and not worker_ready
                and time.monotonic() - worker_last_progress
                > startup_deadline_seconds
            ):
                last_subscription_failure_reason = (
                    "sdk_quote_subscription_deadline_exceeded:"
                    f"{startup_deadline_seconds}s_without_progress:"
                    f"{subscription_progress_completed}/{subscription_progress_total}"
                )
                record_market_data_worker_restart(
                    last_subscription_failure_reason,
                    exit_code=worker.exitcode if worker else None,
                )
                attempts += 1
                stop_spawned_process(worker, graceful=False)
                worker = None
                if (
                    not snapshot_fallback_active
                    and config.allow_snapshot_poll_fallback
                    and should_use_snapshot_fallback(
                        attempts,
                        config.subscription_failures_before_snapshot_fallback,
                    )
                ):
                    snapshot_fallback_active = True
                    snapshot_fallback_not_before_monotonic = (
                        time.monotonic()
                        + SNAPSHOT_FALLBACK_HANDOFF_COOLDOWN_SECONDS
                    )
                    subscription_recovery_failures += attempts
                    attempts = 0
                continue
            if (
                worker_ready
                and market_data_mode == "sdk_subscription"
                and in_regular_session(datetime.now(UTC))
                and subscription_quote_stream_is_stale(
                    worker_ready_since,
                    last_subscription_quote_monotonic,
                    time.monotonic(),
                    subscription_quote_stream_deadline_seconds(
                        config.market_data_heartbeat_deadline_seconds
                    ),
                )
            ):
                quote_stream_deadline_seconds = (
                    subscription_quote_stream_deadline_seconds(
                        config.market_data_heartbeat_deadline_seconds
                    )
                )
                last_subscription_failure_reason = (
                    "sdk_quote_stream_silent_after_acknowledged_subscription:"
                    f"{quote_stream_deadline_seconds}s"
                )
                record_market_data_worker_restart(
                    last_subscription_failure_reason,
                    exit_code=worker.exitcode if worker else None,
                )
                subscription_quote_silence_fallback_count += 1
                attempts += 1
                snapshot_fallback_active = bool(
                    config.allow_snapshot_poll_fallback
                    and should_use_snapshot_fallback(
                        attempts,
                        config.subscription_failures_before_snapshot_fallback,
                    )
                )
                market_data_fallback_validated = False
                worker_ready = False
                worker_ready_since = 0.0
                stop_spawned_process(worker, graceful=False)
                worker = None
                continue
            if (
                worker_ready
                and market_data_heartbeat_grace_elapsed(
                    worker_ready_since,
                    time.monotonic(),
                    (
                        market_data_applied_heartbeat_deadline_seconds
                        if market_data_mode == "sdk_snapshot_poll"
                        else config.subscription_deadline_seconds
                    ),
                )
                and market_data_heartbeat_is_stale(
                    worker_last_progress,
                    time.monotonic(),
                    market_data_applied_heartbeat_deadline_seconds,
                )
            ):
                worker_ready = False
                worker_ready_since = 0.0
                last_subscription_failure_reason = (
                    "sdk_market_data_heartbeat_deadline_exceeded:"
                    f"{market_data_applied_heartbeat_deadline_seconds:g}s"
                )
                record_market_data_worker_restart(
                    last_subscription_failure_reason,
                    exit_code=worker.exitcode if worker else None,
                )
                attempts += 1
                stop_spawned_process(worker, graceful=False)
                worker = None
                continue
            if daily_context_state == "waiting_for_subscription":
                symbols = list(configured_symbols(config))
                daily_pending = deque(
                    symbols[index:index + config.daily_context_batch_size]
                    for index in range(0, len(symbols), config.daily_context_batch_size)
                )
                daily_context_state = "loading"
            if daily_context_retry_cycle_due(
                daily_context_state,
                daily_failed,
                daily_context_retry_not_before_monotonic,
                time.monotonic(),
            ):
                retry_symbols = list(dict.fromkeys(daily_failed))
                daily_failed = []
                for symbol in retry_symbols:
                    daily_retry_counts[symbol] = 0
                daily_pending.extend(
                    retry_symbols[index:index + config.daily_context_batch_size]
                    for index in range(
                        0,
                        len(retry_symbols),
                        config.daily_context_batch_size,
                    )
                )
                daily_context_state = "loading"
                daily_context_retry_cycle_count += 1
            if daily_context_state == "loading":
                while daily_pending and len(daily_workers) < config.daily_context_parallel_workers:
                    symbols = daily_pending.popleft()
                    task_id = f"daily-{len(daily_completed) + len(daily_workers):03d}-{symbols[0]}"
                    daily_worker = process_context.Process(
                        target=daily_context_worker,
                        args=(str(config.config_path), symbols, task_id, message_queue),
                        daemon=True,
                    )
                    daily_worker.start()
                    daily_workers[task_id] = (daily_worker, time.monotonic(), symbols)
                for task_id, (daily_worker, started_at, symbols) in list(daily_workers.items()):
                    if time.monotonic() - started_at > config.daily_context_deadline_seconds:
                        stop_spawned_process(daily_worker, graceful=False)
                        daily_workers.pop(task_id, None)
                        daily_completed.add(task_id)
                        schedule_daily_context_retry(
                            symbols,
                            daily_retry_counts,
                            config.daily_context_retry_count,
                            daily_pending,
                            daily_failed,
                        )
                if not daily_pending and not daily_workers and daily_context_state == "loading":
                    daily_context_state = "complete" if daily_rows and not daily_failed else "failed"
                    if daily_context_state == "failed":
                        daily_context_retry_not_before_monotonic = (
                            time.monotonic()
                            + config.daily_context_retry_cycle_seconds
                        )
                if daily_context_is_complete(config, daily_context_state, len(daily_rows), daily_failed) and not daily_context_persisted:
                    write_daily_context_cache(config.daily_context_path, daily_rows)
                    daily_context_persisted = True
                    postclose_daily_refresh_dates.update(
                        completed_postclose_refresh_dates(
                            daily_rows,
                            datetime.now(NEW_YORK),
                        )
                    )
            close_flush_date, close_flush_action = regular_session_close_flush_action(
                datetime.now(UTC),
                session_close_flush_dates,
                maximum_finalization_delay_ms=(
                    config.maximum_bar_finalization_delay_ms
                ),
            )
            close_flush_rows: list[dict[str, Any]] = []
            if (
                snapshot_bar_builder is not None
                and close_flush_action in {"flush", "missed_deadline"}
            ):
                close_flush_now = datetime.now(UTC)
                close_flush_rows = snapshot_bar_builder.flush(close_flush_now)
                session_close_flush_dates.add(close_flush_date)
                if close_flush_action == "flush":
                    snapshot_completed_bar_count += len(close_flush_rows)
                    session_close_flush_status = {
                        "status": (
                            "completed"
                            if close_flush_rows
                            else "completed_without_open_bars"
                        ),
                        "business_date": close_flush_date,
                        "flushed_at": to_iso(close_flush_now),
                        "row_count": len(close_flush_rows),
                        "historical_signal_replayed": False,
                        "historical_order_replayed": False,
                    }
                else:
                    close_flush_status = (
                        "missed_finalization_deadline"
                        if close_flush_rows
                        else "not_applicable_no_open_bars"
                    )
                    session_close_flush_status = {
                        "status": close_flush_status,
                        "business_date": close_flush_date,
                        "detected_at": to_iso(close_flush_now),
                        "discarded_stale_row_count": len(close_flush_rows),
                        "historical_signal_replayed": False,
                        "historical_order_replayed": False,
                    }
                    close_flush_rows = []
            if close_flush_rows:
                message = {
                    "kind": "bars",
                    "rows": close_flush_rows,
                    "session_close_timer_flush": True,
                }
            else:
                try:
                    message = deferred_messages.popleft() if deferred_messages else message_queue.get(timeout=config.heartbeat_interval_seconds)
                except queue.Empty:
                    message = {"kind": "idle"}
            kind = str(message.get("kind") or "")
            if (
                kind == "snapshots"
                and worker_ready
                and snapshot_bar_builder is not None
            ):
                snapshot_batch_count += 1
                try:
                    snapshot_received_at = datetime.fromisoformat(
                        str(message.get("received_at") or "").replace("Z", "+00:00")
                    ).astimezone(UTC)
                except (TypeError, ValueError):
                    snapshot_received_at = datetime.now(UTC)
                completed_snapshot_bars: list[dict[str, Any]] = []
                snapshot_rows = list(message.get("rows") or [])
                snapshot_row_count += len(snapshot_rows)
                message_cycle_id = str(
                    message.get("poll_cycle_id") or message.get("received_at") or ""
                )
                (
                    snapshot_poll_cycle_id,
                    snapshot_poll_cycle_completed_bars,
                    interrupted_cycle_bars,
                ) = rollover_snapshot_cycle(
                    snapshot_poll_cycle_id,
                    message_cycle_id,
                    snapshot_poll_cycle_completed_bars,
                )
                completed_snapshot_bars.extend(interrupted_cycle_bars)
                for snapshot_row in snapshot_rows:
                    update_live_quote_session_state(
                        live_quote_session_state,
                        str(snapshot_row.get("symbol") or ""),
                        dict(snapshot_row.get("payload") or {}),
                        received_at=snapshot_received_at,
                        source_mode="longbridge_sdk_snapshot_poll",
                    )
                    snapshot_poll_cycle_completed_bars.extend(
                        snapshot_bar_builder.on_snapshot(
                            str(snapshot_row.get("symbol") or ""),
                            dict(snapshot_row.get("payload") or {}),
                            received_at=snapshot_received_at,
                        )
                    )
                if bool(message.get("cycle_complete", True)):
                    snapshot_poll_cycle_completed_bars.extend(
                        snapshot_bar_builder.flush(snapshot_received_at)
                    )
                    completed_snapshot_bars.extend(
                        snapshot_poll_cycle_completed_bars
                    )
                    snapshot_poll_cycle_completed_bars = []
                snapshot_completed_bar_count += len(completed_snapshot_bars)
                if completed_snapshot_bars:
                    boundary_batches = (
                        snapshot_boundary_gate.add(
                            completed_snapshot_bars,
                            now=snapshot_received_at,
                        )
                        if snapshot_boundary_gate is not None
                        else []
                    )
                    if boundary_batches:
                        first_batch, *remaining_batches = boundary_batches
                        for batch in reversed(remaining_batches):
                            deferred_messages.appendleft(
                                {"kind": "bars", **batch}
                            )
                        message = {"kind": "bars", **first_batch}
                        kind = "bars"
                    else:
                        kind = "snapshot_batch"
                else:
                    kind = "snapshot_batch"
            if kind == "subscription_progress":
                worker_last_progress = time.monotonic()
                subscription_progress_completed = int(message.get("completed") or 0)
                subscription_progress_total = int(
                    message.get("total") or subscription_progress_total
                )
            elif kind in {"quote_state", "quote_states"}:
                last_subscription_quote_monotonic = time.monotonic()
                quote_rows = (
                    list(message.get("rows") or [])
                    if kind == "quote_states"
                    else [message]
                )
                for quote_row in quote_rows:
                    try:
                        quote_received_at = datetime.fromisoformat(
                            str(quote_row.get("received_at") or "").replace("Z", "+00:00")
                        ).astimezone(UTC)
                    except ValueError:
                        quote_received_at = datetime.now(UTC)
                    update_live_quote_session_state(
                        live_quote_session_state,
                        str(quote_row.get("symbol") or ""),
                        dict(quote_row.get("payload") or {}),
                        received_at=quote_received_at,
                        source_mode=str(
                            quote_row.get("source_mode")
                            or "longbridge_sdk_push"
                        ),
                    )
            elif kind == "ready":
                quote_context_warmups = list(
                    message.get("quote_context_warmups") or []
                )
                subscription_failed = list(message.get("subscription_failed_symbols") or [])
                trading_subscription_failed = list(message.get("trading_subscription_failed_symbols") or [])
                confirmed_candlestick_failed = list(
                    message.get("confirmed_candlestick_failed_symbols") or []
                )
                confirmed_candlestick_coverage = str(
                    message.get("confirmed_candlestick_coverage") or ""
                )
                market_data_mode = str(
                    message.get("market_data_mode") or "sdk_subscription"
                )
                market_data_fallback_validated = bool(
                    message.get("market_data_fallback_validated")
                    or market_data_mode == "sdk_subscription"
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
                partial_bar_suppressed_until = preserve_partial_bar_suppression(
                    partial_bar_suppressed_until,
                    str(message.get("partial_bar_suppressed_until") or ""),
                    market_data_mode=market_data_mode,
                )
                worker_ready = (
                    not trading_market_data_failed
                    and not trading_subscription_failed
                    and not daily_failed
                )
                if not worker_ready:
                    worker_ready_since = 0.0
                    last_subscription_failure_reason = (
                        "sdk_quote_subscription_incomplete:"
                        + ",".join(trading_subscription_failed or daily_failed)
                    )
                    record_market_data_worker_restart(
                        last_subscription_failure_reason,
                        exit_code=worker.exitcode if worker else None,
                    )
                    attempts += 1
                    stop_spawned_process(worker, graceful=False)
                    worker = None
                    continue
                attempts = 0
                if market_data_mode == "sdk_snapshot_poll":
                    snapshot_was_previously_ready = True
                    last_subscription_failure_reason = (
                        "sdk_subscription_unavailable_using_snapshot_poll"
                    )
                else:
                    last_subscription_failure_reason = ""
                worker_last_progress = time.monotonic()
                worker_ready_since = worker_last_progress
            elif kind == "intraday_context" and str(message.get("task_id") or "").startswith("postclose-recovery-"):
                task_id = str(message.get("task_id") or "")
                recovered_rows = verified_postclose_recovery_rows(
                    list(message.get("rows") or []),
                    context.rows(),
                    business_date=str(postclose_recovery_status.get("business_date") or ""),
                )
                if recovered_rows:
                    append_market_events(
                        config.market_events_path,
                        recovered_rows,
                        config.event_keep_lines,
                    )
                    context.append(recovered_rows)
                    postclose_recovery_status["recovered_row_count"] = int(
                        postclose_recovery_status.get("recovered_row_count") or 0
                    ) + len(recovered_rows)
                completed_symbol = str(message.get("completed_symbol") or "")
                if completed_symbol:
                    completed_symbols = set(
                        postclose_recovery_status.get("completed_symbols") or []
                    )
                    completed_symbols.add(completed_symbol)
                    postclose_recovery_status["completed_symbols"] = sorted(
                        completed_symbols
                    )
                    postclose_recovery_status["completed_symbol_count"] = len(
                        completed_symbols
                    )
                    postclose_recovery_status["last_progress_at"] = to_iso(
                        datetime.now(UTC)
                    )
                failed_symbols = set(
                    postclose_recovery_status.get("failed_symbols") or []
                )
                message_failures = {
                    str(value) for value in (message.get("failures") or [])
                }
                failed_symbols.update(message_failures)
                if completed_symbol and completed_symbol not in message_failures:
                    failed_symbols.discard(completed_symbol)
                postclose_recovery_status["failed_symbols"] = sorted(
                    failed_symbols
                )
            elif kind == "intraday_context_task_complete" and str(message.get("task_id") or "").startswith("postclose-recovery-"):
                task_id = str(message.get("task_id") or "")
                task = postclose_recovery_workers.pop(task_id, None)
                if task is not None:
                    stop_spawned_process(task[0], graceful=True)
                postclose_recovery_status.setdefault("completed_tasks", []).append(task_id)
                postclose_recovery_status["failed_symbols"] = sorted(
                    set(postclose_recovery_status.get("failed_symbols") or [])
                    | {str(value) for value in (message.get("failures") or [])}
                )
                advance_postclose_recovery()
            elif kind == "intraday_context_error" and str(message.get("task_id") or "").startswith("postclose-recovery-"):
                task_id = str(message.get("task_id") or "")
                task = postclose_recovery_workers.pop(task_id, None)
                task_symbols = task[2] if task is not None else list(message.get("symbols") or [])
                if task is not None:
                    stop_spawned_process(task[0], graceful=False)
                postclose_recovery_status["failed_symbols"] = sorted(
                    set(postclose_recovery_status.get("failed_symbols") or [])
                    | {str(value) for value in task_symbols}
                )
                postclose_recovery_status["last_error"] = str(message.get("reason") or "")
                advance_postclose_recovery()
            elif kind == "daily_context":
                rows = list(message.get("rows") or [])
                daily_rows.extend(rows)
                task_id = str(message.get("task_id") or "")
                daily_task_failures[task_id] = [str(value) for value in (message.get("failures") or [])]
                context.append(trading_market_events(config, rows))
            elif kind == "daily_context_task_complete":
                task_id = str(message.get("task_id") or "")
                rows = list(message.get("rows") or [])
                if rows:
                    daily_rows.extend(rows)
                    context.append(trading_market_events(config, rows))
                if task_id in daily_workers:
                    daily_worker, _started_at, _symbols = daily_workers.pop(task_id)
                    stop_spawned_process(daily_worker, graceful=True)
                daily_completed.add(task_id)
                failures = daily_task_failures.pop(task_id, [str(value) for value in (message.get("failures") or [])])
                schedule_daily_context_retry(
                    failures,
                    daily_retry_counts,
                    config.daily_context_retry_count,
                    daily_pending,
                    daily_failed,
                )
            elif kind == "daily_context_error":
                task_id = str(message.get("task_id") or "")
                task = daily_workers.pop(task_id, None)
                if task is not None:
                    daily_worker, _started_at, symbols = task
                    stop_spawned_process(daily_worker, graceful=True)
                else:
                    symbols = [str(value) for value in (message.get("symbols") or [])]
                daily_completed.add(task_id)
                schedule_daily_context_retry(
                    symbols,
                    daily_retry_counts,
                    config.daily_context_retry_count,
                    daily_pending,
                    daily_failed,
                )
            elif kind == "bars" and worker_ready:
                rows = list(message.get("rows") or [])
                confirmed_boundary_gate = dict(
                    message.get("confirmed_boundary_gate") or {}
                )
                entry_batch_eligible = bool(
                    message.get("entry_batch_eligible") is True
                )
                started = time.perf_counter()
                trading_daily_context_ready = daily_context_covers_symbols(
                    config, daily_rows, configured_trading_symbols(config), daily_failed
                )
                # Re-evaluate the validation/flatten gate before every closed-bar
                # batch.  This prevents a 15:45 cutoff from waiting for the slower
                # maintenance cadence while a new-entry batch is already running.
                if dispatch_enabled and bool(trade_context_health.get("ok")):
                    flatten_transition = run_pending_flatten_cycle(
                        config,
                        account,
                        flatten_client,
                        context.rows(),
                        now=datetime.now(UTC),
                    )
                active_client = paper_client if trading_daily_context_ready else None
                if bool(flatten_transition.get("blocks_new_entries")):
                    active_client = None
                if (
                    market_data_mode == "sdk_snapshot_poll"
                    and not market_data_fallback_validated
                ):
                    active_client = None
                last_result = dispatch_completed_rows(
                    config,
                    rows,
                    context,
                    account,
                    active_client,
                    daily_context_rows=daily_rows,
                    live_quote_session_state=live_quote_session_state,
                    signal_event_cache=signal_event_cache,
                    signal_id_cache=signal_id_cache,
                    execution_ledger_cache=execution_ledger_cache,
                    fill_attribution_state_cache=fill_attribution_state_cache,
                    intraday_context_blocked_symbols=set(
                        residual_intraday_context_gaps
                    ),
                    allow_new_entries=entry_batch_eligible,
                )
                five_minute_strategy_context = five_minute_contract_context_status(
                    context.rows(),
                    configured_trading_symbols(config),
                    now=datetime.now(UTC),
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
                expected_symbols = {
                    f"{symbol.upper().replace('.US', '')}.US"
                    for symbol in configured_trading_symbols(config)
                }
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
                worker_last_progress = time.monotonic()
                snapshot_poll_elapsed_ms = int(
                    message.get("poll_elapsed_ms") or snapshot_poll_elapsed_ms
                )
                snapshot_poll_covered_count = int(
                    message.get("poll_covered_count") or snapshot_poll_covered_count
                )
                snapshot_poll_missing_count = int(
                    message.get("poll_missing_count") or 0
                )
                snapshot_poll_successful_fast_polls = int(
                    message.get("successful_fast_polls") or 0
                )
                if "total_poll_count" in message:
                    snapshot_poll_total_count = int(
                        message.get("total_poll_count") or 0
                    )
                if "failed_poll_count" in message:
                    snapshot_poll_failure_count = int(
                        message.get("failed_poll_count") or 0
                    )
                if "consecutive_failures" in message:
                    snapshot_poll_consecutive_failures = int(
                        message.get("consecutive_failures") or 0
                    )
                if message.get("last_success_at"):
                    snapshot_poll_last_success_at = str(
                        message.get("last_success_at")
                    )
                if message.get("last_failure_at"):
                    snapshot_poll_last_failure_at = str(
                        message.get("last_failure_at")
                    )
                if message.get("first_batch_returned_at"):
                    snapshot_poll_first_batch_returned_at = str(
                        message.get("first_batch_returned_at")
                    )
                if "first_batch_latency_ms" in message:
                    snapshot_poll_first_batch_latency_ms = int(
                        message.get("first_batch_latency_ms") or 0
                    )
                if "first_batch_symbol_count" in message:
                    snapshot_poll_first_batch_symbol_count = int(
                        message.get("first_batch_symbol_count") or 0
                    )
                snapshot_poll_is_fast_and_complete = bool(
                    message.get("poll_is_fast_and_complete")
                )
                if (
                    market_data_mode == "sdk_snapshot_poll"
                    and message.get("poll_is_fast_and_complete") is True
                ):
                    market_data_fallback_validated = True
                    last_subscription_failure_reason = (
                        "sdk_subscription_unavailable_using_snapshot_poll"
                    )
            elif kind == "snapshot_poll_failure":
                snapshot_poll_is_fast_and_complete = False
                snapshot_poll_successful_fast_polls = 0
                market_data_fallback_validated = False
                snapshot_poll_total_count = int(
                    message.get("total_poll_count") or snapshot_poll_total_count
                )
                snapshot_poll_failure_count = int(
                    message.get("failed_poll_count") or snapshot_poll_failure_count
                )
                snapshot_poll_consecutive_failures = int(
                    message.get("consecutive_failures") or 0
                )
                snapshot_poll_last_success_at = str(
                    message.get("last_success_at")
                    or snapshot_poll_last_success_at
                )
                snapshot_poll_last_failure_at = str(
                    message.get("last_failure_at")
                    or snapshot_poll_last_failure_at
                )
                snapshot_poll_first_batch_returned_at = str(
                    message.get("first_batch_returned_at")
                    or snapshot_poll_first_batch_returned_at
                )
                snapshot_poll_first_batch_latency_ms = int(
                    message.get("first_batch_latency_ms")
                    or snapshot_poll_first_batch_latency_ms
                )
                snapshot_poll_first_batch_symbol_count = int(
                    message.get("first_batch_symbol_count")
                    or snapshot_poll_first_batch_symbol_count
                )
                last_subscription_failure_reason = str(
                    message.get("reason")
                    or "sdk_quote_snapshot_poll_transient_failure"
                )
            elif kind == "error":
                worker_ready = False
                worker_ready_since = 0.0
                last_subscription_failure_reason = str(
                    message.get("reason") or "sdk_quote_worker_failed"
                )
                last_market_data_worker_error = last_subscription_failure_reason
                record_market_data_worker_restart(
                    last_subscription_failure_reason,
                    exit_code=worker.exitcode if worker else None,
                )
                subscription_failed = [last_subscription_failure_reason]
                attempts += 1
                if worker is not None:
                    stop_spawned_process(worker, graceful=False)
                    worker = None
            if time.monotonic() - last_compaction >= 60:
                compact_market_events(config.market_events_path, config.event_keep_lines)
                last_compaction = time.monotonic()
            if time.monotonic() - last_process_resource_snapshot >= 60:
                process_resource_current = process_resource_snapshot()
                last_process_resource_snapshot = time.monotonic()
            maintenance_now = datetime.now(UTC)
            near_five_minute_boundary = (
                maintenance_now.minute % 5 == 0
                and maintenance_now.second <= 2
            )
            monotonic_now = time.monotonic()
            healthcheck_due = (
                dispatch_enabled
                and paper_client is None
                and not near_five_minute_boundary
                and (
                    monotonic_now - last_trade_context_healthcheck
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
                migration_input = read_json_object(migration_path)
                migration_account_snapshot = account.snapshot()
                if account_snapshot_ready_for_orders(
                    migration_account_snapshot,
                    maximum_age_seconds=config.maximum_account_snapshot_age_seconds,
                    now=maintenance_now,
                ):
                    capital_bucket_migration = advance_cleanup_state(
                        migration_input,
                        migration_account_snapshot,
                        paper_client,
                        now=maintenance_now,
                        execution_ledger_path=(
                            hot_execution_config.output_dir / EXECUTION_LEDGER_FILE
                        ),
                    )
                else:
                    capital_bucket_migration = migration_input
                if capital_bucket_migration.get("status") != "inactive":
                    write_json_atomic(migration_path, capital_bucket_migration)
                authorized_account_exit = run_authorized_account_exit_cycle(
                    config,
                    account,
                    flatten_client,
                    now=maintenance_now,
                )
            authorized_cleanup_waiting = bool(
                capital_bucket_migration.get("blocks_new_entries")
            )
            flatten_blocks_new_entries = bool(
                flatten_transition.get("blocks_new_entries")
                or authorized_cleanup_waiting
            )
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
            pre_recovery_coverage = five_minute_session_coverage(
                context.rows(),
                configured_trading_symbols(config),
                now=datetime.now(UTC),
                minutes=config.bar_minutes,
            )
            if (
                now_ny.weekday() < 5
                and (now_ny.hour, now_ny.minute) >= (16, 5)
                and daily_context_state == "complete"
                and not daily_workers
                and not daily_pending
                and session_date not in postclose_recovery_attempted_dates
                and session_requires_postclose_recovery(pre_recovery_coverage)
            ):
                # Recovery is deliberately post-close and context-only.  It
                # repairs the audit dataset without reopening an SDK history
                # connection in the realtime trading path or replaying signals.
                postclose_recovery_attempted_dates.add(session_date)
                stop_spawned_process(worker, graceful=True)
                worker = None
                worker_ready = False
                worker_ready_since = 0.0
                recovery_session_start = now_ny.replace(
                    hour=9, minute=30, second=0, microsecond=0
                ).astimezone(UTC)
                recovery_session_close = now_ny.replace(
                    hour=16, minute=0, second=0, microsecond=0
                ).astimezone(UTC)
                recovery_symbols = list(configured_trading_symbols(config))
                postclose_recovery_status = {
                    "status": "running",
                    "business_date": session_date,
                    "started_at": to_iso(datetime.now(UTC)),
                    "session_started_at": to_iso(recovery_session_start),
                    "expected_last_close": to_iso(recovery_session_close),
                    "requested_symbol_count": len(recovery_symbols),
                    "recovered_row_count": 0,
                    "failed_symbols": [],
                    "completed_symbols": [],
                    "completed_symbol_count": 0,
                    "retry_round": 0,
                    "historical_signal_replayed": False,
                    "historical_order_replayed": False,
                    "recovery_counts_as_realtime_evidence": False,
                }
                postclose_recovery_pending.clear()
                postclose_recovery_pending.extend(
                    [symbol] for symbol in recovery_symbols
                )
                start_next_postclose_recovery_batch()
            for task_id, (recovery_worker, started_at, task_symbols) in list(
                postclose_recovery_workers.items()
            ):
                if (
                    time.monotonic() - started_at
                    <= POSTCLOSE_INTRADAY_RECOVERY_DEADLINE_SECONDS
                ):
                    continue
                stop_spawned_process(recovery_worker, graceful=False)
                postclose_recovery_workers.pop(task_id, None)
                completed_symbols = set(
                    postclose_recovery_status.get("completed_symbols") or []
                )
                postclose_recovery_status["failed_symbols"] = sorted(
                    set(postclose_recovery_status.get("failed_symbols") or [])
                    | (set(task_symbols) - completed_symbols)
                )
                postclose_recovery_status["last_error"] = (
                    "postclose_intraday_recovery_deadline_exceeded"
                )
            if (
                postclose_recovery_status.get("status") == "running"
                and not postclose_recovery_workers
            ):
                advance_postclose_recovery()
            if (
                worker_ready
                and daily_context_ready
                and now_ny.weekday() < 5
                and (now_ny.hour, now_ny.minute) >= (16, 10)
                and session_date not in postclose_daily_refresh_dates
                and postclose_recovery_status.get("status") != "running"
            ):
                # Refresh the completed daily bar after close so tomorrow's
                # session never starts with yesterday's stale context.
                postclose_daily_refresh_dates.add(session_date)
                stop_spawned_process(worker, graceful=True)
                worker = None
                worker_ready = False
                worker_ready_since = 0.0
                retained_intraday_rows = [
                    row
                    for row in context.rows()
                    if str(row.get("timeframe") or "") == "5m"
                ]
                context = MarketEventContext(
                    maximum_rows=(
                        len(configured_trading_symbols(config))
                        * config.daily_context_bars
                    )
                    + (len(configured_trading_symbols(config)) * 78)
                    + 4096
                )
                context.append(retained_intraday_rows)
                daily_rows = []
                daily_failed = []
                daily_workers = {}
                daily_pending = deque()
                daily_completed = set()
                daily_retry_counts = {}
                daily_task_failures = {}
                daily_context_state = "waiting_for_subscription"
                daily_context_cache_reused = False
                daily_context_persisted = False
                daily_context_ready = False
            is_after_regular_session = now_ny.weekday() < 5 and (now_ny.hour >= 16)
            if (
                config.two_day_readonly_gate
                and is_after_regular_session
                and session_date not in observed_regular_sessions
                and worker_ready
                and daily_context_state == "complete"
                and not daily_failed
                and age is not None
                and age <= config.maximum_account_snapshot_age_seconds
                and last_event_at
            ):
                gate = record_readonly_session(config.readonly_gate_path, session_date, {
                    "subscription_coverage": (
                        f"{len(configured_symbols(config))}/{len(configured_symbols(config))}"
                    ),
                    "daily_context_row_count": len(daily_rows),
                    "last_event_at": last_event_at,
                    "account_snapshot_age_seconds": age,
                    "runtime_engine": "sdk",
                }) if market_data_mode_qualifies_for_subscription_gate(
                    market_data_mode
                ) else {
                    "passed": False,
                    "completed_sessions": [],
                }
                readonly_gate_passed_now = bool(gate.get("passed"))
                readonly_sessions_passed = len(gate.get("completed_sessions", []))
                observed_regular_sessions.add(session_date)
                if dispatch_requested and config.paper_order_dispatch_enabled and readonly_gate_passed_now and paper_client is None:
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
            configured_symbol_set = set(configured_symbols(config))
            trading_symbol_set = set(configured_trading_symbols(config))
            monitoring_target_set = set(
                quote_subscription_targets(config, datetime.now(UTC))
            )
            position_monitoring_symbol_set = (
                monitoring_target_set - trading_symbol_set
            )
            configured_subscription_failed = sorted(
                configured_symbol_set & set(subscription_failed)
            )
            position_monitoring_failed = sorted(
                position_monitoring_symbol_set & set(subscription_failed)
            )
            expansion_symbol_count = (
                len(configured_symbols(config)) - len(configured_trading_symbols(config))
            )
            expansion_subscription_failed = sorted(
                (configured_symbol_set - trading_symbol_set)
                & set(subscription_failed)
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
                    required_sessions=1,
                )
                expansion_gate_passed = bool(expansion_gate.get("passed"))
                expansion_sessions_passed = len(expansion_gate.get("completed_sessions", []))
                observed_expansion_sessions.add(session_date)
            if expansion_symbol_count <= 0:
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
            if (
                live_quote_session_state
                and time.monotonic() - last_quote_snapshot_write >= 15
            ):
                quote_snapshot_generated_at = datetime.now(UTC)
                write_trusted_sdk_quote_snapshot(
                    config.output_dir / QUOTE_SNAPSHOT_JSON,
                    live_quote_session_state,
                    generated_at=quote_snapshot_generated_at,
                    required_symbols=quote_subscription_targets(
                        config, quote_snapshot_generated_at
                    ),
                )
                last_quote_snapshot_write = time.monotonic()
            session_coverage = five_minute_session_coverage(
                context.rows(),
                configured_trading_symbols(config),
                now=datetime.now(UTC),
                minutes=config.bar_minutes,
                maximum_finalization_delay_ms=(
                    config.maximum_bar_finalization_delay_ms
                ),
            )
            if (
                str(postclose_recovery_status.get("business_date") or "")
                == str(session_coverage.get("business_date") or "")
                and str(postclose_recovery_status.get("status") or "").startswith(
                    "completed"
                )
            ):
                postclose_recovery_status = finalize_postclose_recovery_status(
                    postclose_recovery_status,
                    session_coverage,
                )
            postclose_recovery_signature = json.dumps(
                postclose_recovery_status,
                sort_keys=True,
                separators=(",", ":"),
            )
            if (
                str(postclose_recovery_status.get("status") or "")
                in {
                    "completed",
                    "completed_with_failures",
                    "completed_incomplete_data",
                }
                and postclose_recovery_signature
                != last_persisted_postclose_recovery
            ):
                write_json_atomic(
                    config.output_dir / POSTCLOSE_RECOVERY_STATE_JSON,
                    postclose_recovery_status,
                )
                last_persisted_postclose_recovery = (
                    postclose_recovery_signature
                )
            market_data_health = {
                "schema_version": "m15.sdk-market-data-health.v1",
                "generated_at": to_iso(datetime.now(UTC)),
                "run_id": run_id,
                "runtime_pid": os.getpid(),
                "market_data_mode": market_data_mode,
                "actual_market_data_coverage": (
                    f"{len(set(configured_trading_symbols(config)) & market_data_symbols)}"
                    f"/{len(configured_trading_symbols(config))}"
                    if worker_ready
                    else f"0/{len(configured_trading_symbols(config))}"
                ),
                "sdk_push_subscription_coverage": (
                    f"{len(configured_trading_symbols(config)) - len(trading_subscription_failed)}"
                    f"/{len(configured_trading_symbols(config))}"
                    if worker_ready and market_data_mode == "sdk_subscription"
                    else f"0/{len(configured_trading_symbols(config))}"
                ),
                "worker_ready": worker_ready,
                "quote_subscription_connection_count": (
                    config.subscription_shard_count
                    if worker_ready and market_data_mode == "sdk_subscription"
                    else 0
                ),
                "worker_restart_count_this_run": market_data_worker_restart_total,
                "worker_recent_restart_count": market_data_worker_recent_restart_count,
                "last_worker_error": last_market_data_worker_error,
                "snapshot_poll_total_count": snapshot_poll_total_count,
                "snapshot_poll_failure_count": snapshot_poll_failure_count,
                "snapshot_poll_consecutive_failures": (
                    snapshot_poll_consecutive_failures
                ),
                "snapshot_poll_last_success_at": snapshot_poll_last_success_at,
                "snapshot_poll_last_failure_at": snapshot_poll_last_failure_at,
                "snapshot_poll_first_batch_returned_at": (
                    snapshot_poll_first_batch_returned_at
                ),
                "snapshot_poll_first_batch_latency_ms": (
                    snapshot_poll_first_batch_latency_ms
                ),
                "snapshot_poll_first_batch_symbol_count": (
                    snapshot_poll_first_batch_symbol_count
                ),
                "session_close_flush": session_close_flush_status,
                "five_minute_session_coverage": session_coverage,
                "confirmed_boundary_gate": confirmed_boundary_gate,
            }
            current_market_data_targets = set(
                quote_subscription_targets(config, datetime.now(UTC))
            )
            write_json_atomic(
                config.output_dir / MARKET_DATA_HEALTH_JSON,
                market_data_health,
            )
            health_signature = json.dumps(
                {
                    "run_id": run_id,
                    "mode": market_data_mode,
                    "ready": worker_ready,
                    "restart_count": market_data_worker_restart_total,
                    "business_date": session_coverage["business_date"],
                    "expected": session_coverage["expected_boundary_count_so_far"],
                    "complete": session_coverage["complete_boundary_count"],
                    "partial": session_coverage["partial_boundary_count"],
                    "missing": session_coverage["missing_boundary_times"],
                    "late_finalization": session_coverage[
                        "late_finalization_row_count"
                    ],
                    "recovered_rows": session_coverage["recovered_row_count"],
                    "data_complete_after_recovery": session_coverage[
                        "data_complete_after_recovery"
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            if health_signature != last_market_data_health_signature:
                append_runtime_health_event(
                    config.output_dir / MARKET_DATA_HEALTH_LEDGER_JSONL,
                    {
                        **market_data_health,
                        "event_type": "five_minute_session_coverage_changed",
                    },
                )
                last_market_data_health_signature = health_signature
            build_status(
                config,
                status="running" if worker_ready else "connecting",
                reason="" if worker_ready else "waiting_for_full_sdk_subscription",
                connected=worker_ready,
                last_event_at=last_event_at,
                sdk_installed=True,
                oauth_client_id_present=True,
                pipeline_metrics=latency_metrics,
                subscription_failed_symbols=subscription_failed,
                extra={
                    "run_id": run_id, "runtime_pid": os.getpid(), "quote_worker_pid": worker.pid if worker else "",
                    "quote_subscription_worker_count": 1 if worker is not None and worker.is_alive() else 0,
                    "quote_subscription_connection_count": (
                        config.subscription_shard_count
                        if worker is not None
                        and worker.is_alive()
                        and market_data_mode == "sdk_subscription"
                        else 0
                    ),
                    "quote_context_warmups": quote_context_warmups,
                    "last_subscription_failure_reason": last_subscription_failure_reason,
                    "subscription_progress": (
                        f"{subscription_progress_completed}/{subscription_progress_total}"
                    ),
                    "worker_attempts": attempts,
                    "subscription_recovery_failures": subscription_recovery_failures,
                    "market_data_mode": market_data_mode,
                    "market_data_fallback_validated": market_data_fallback_validated,
                    "source_mode": (
                        "longbridge_sdk_snapshot_poll"
                        if market_data_mode == "sdk_snapshot_poll"
                        else "longbridge_sdk_confirmed_candlestick"
                    ),
                    "snapshot_poll_interval_seconds": (
                        config.snapshot_poll_interval_seconds
                        if market_data_mode == "sdk_snapshot_poll"
                        else 0
                    ),
                    "snapshot_poll_elapsed_ms": snapshot_poll_elapsed_ms,
                    "snapshot_poll_covered_count": snapshot_poll_covered_count,
                    "snapshot_poll_missing_count": snapshot_poll_missing_count,
                    "snapshot_poll_successful_fast_polls": snapshot_poll_successful_fast_polls,
                    "snapshot_poll_is_fast_and_complete": snapshot_poll_is_fast_and_complete,
                    "snapshot_poll_total_count": snapshot_poll_total_count,
                    "snapshot_poll_failure_count": snapshot_poll_failure_count,
                    "snapshot_poll_consecutive_failures": (
                        snapshot_poll_consecutive_failures
                    ),
                    "snapshot_poll_last_success_at": snapshot_poll_last_success_at,
                    "snapshot_poll_last_failure_at": snapshot_poll_last_failure_at,
                    "snapshot_poll_first_batch_returned_at": (
                        snapshot_poll_first_batch_returned_at
                    ),
                    "snapshot_poll_first_batch_latency_ms": (
                        snapshot_poll_first_batch_latency_ms
                    ),
                    "snapshot_poll_first_batch_symbol_count": (
                        snapshot_poll_first_batch_symbol_count
                    ),
                    "session_close_flush": session_close_flush_status,
                    "last_market_data_worker_error": last_market_data_worker_error,
                    "market_data_worker_restart_count": (
                        market_data_worker_restart_total
                    ),
                    "market_data_worker_recent_restart_count": (
                        market_data_worker_recent_restart_count
                    ),
                    "market_data_applied_heartbeat_deadline_seconds": (
                        market_data_applied_heartbeat_deadline_seconds
                    ),
                    "snapshot_poll_recovery_deadline_seconds": (
                        config.snapshot_poll_recovery_deadline_seconds
                    ),
                    "subscription_quote_silence_fallback_count": (
                        subscription_quote_silence_fallback_count
                    ),
                    "last_primary_subscription_reprobe_at": (
                        last_primary_subscription_reprobe_at
                    ),
                    "subscription_quote_stream_age_seconds": (
                        max(
                            0,
                            int(
                                time.monotonic()
                                - last_subscription_quote_monotonic
                            ),
                        )
                        if last_subscription_quote_monotonic > 0
                        else None
                    ),
                    "market_data_worker_restart_events": list(
                        market_data_worker_restart_events
                    ),
                    "snapshot_batch_count": snapshot_batch_count,
                    "snapshot_row_count": snapshot_row_count,
                    "snapshot_open_bar_count": (
                        snapshot_bar_builder.open_bar_count
                        if snapshot_bar_builder is not None
                        else 0
                    ),
                    "snapshot_completed_bar_count": snapshot_completed_bar_count,
                    "orphaned_runtime_children_cleaned": orphaned_runtime_children_cleaned,
                    "process_resource_baseline": process_resource_baseline,
                    "process_resource_current": process_resource_current,
                    "config_fingerprint": loaded_config_fingerprint,
                    "runtime_source_fingerprint": loaded_source_fingerprint,
                    "subscription_symbol_count": len(configured_symbols(config)),
                    "subscription_coverage": f"{len(configured_symbols(config)) - len(configured_subscription_failed) if worker_ready else 0}/{len(configured_symbols(config))}",
                    "trading_symbol_count": len(configured_trading_symbols(config)),
                    "trading_subscription_coverage": (
                        f"{len(configured_trading_symbols(config)) - len(trading_subscription_failed) if worker_ready and market_data_mode == 'sdk_subscription' else 0}"
                        f"/{len(configured_trading_symbols(config))}"
                    ),
                    "confirmed_candlestick_coverage": (
                        confirmed_candlestick_coverage
                    ),
                    "confirmed_candlestick_failed_symbols": (
                        confirmed_candlestick_failed
                    ),
                    "market_data_coverage": (
                        f"{len(current_market_data_targets & market_data_symbols)}/{len(current_market_data_targets)}"
                        if worker_ready
                        else f"0/{len(current_market_data_targets)}"
                    ),
                    "trading_market_data_coverage": (
                        f"{len(set(configured_trading_symbols(config)) & market_data_symbols)}"
                        f"/{len(configured_trading_symbols(config))}"
                        if worker_ready
                        else f"0/{len(configured_trading_symbols(config))}"
                    ),
                    "market_data_failed_symbols": market_data_failed,
                    "trading_market_data_failed_symbols": trading_market_data_failed,
                    "position_monitoring_symbol_count": len(
                        position_monitoring_symbol_set
                    ),
                    "position_monitoring_symbols": sorted(
                        position_monitoring_symbol_set
                    ),
                    "position_monitoring_coverage": (
                        f"{len(position_monitoring_symbol_set) - len(position_monitoring_failed)}"
                        f"/{len(position_monitoring_symbol_set)}"
                        if worker_ready
                        else f"0/{len(position_monitoring_symbol_set)}"
                    ),
                    "position_monitoring_failed_symbols": (
                        position_monitoring_failed
                    ),
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
                    "daily_context_retry_cycle_count": (
                        daily_context_retry_cycle_count
                    ),
                    "daily_context_retry_cycle_seconds": (
                        config.daily_context_retry_cycle_seconds
                    ),
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
                    "intraday_context_required_bars_per_symbol": required_intraday_bars,
                    "intraday_context_backfill_requested_symbol_count": len(intraday_backfill_requested_symbols),
                    "intraday_context_backfill_row_count": intraday_backfill_row_count,
                    "intraday_context_backfill_failed_symbols": intraday_backfill_failed_symbols,
                    "intraday_context_residual_gap_symbols": residual_intraday_context_gaps,
                    "intraday_context_ready": not residual_intraday_context_gaps,
                    "intraday_context_repair": intraday_repair_status,
                    "intraday_context_gap_blocks_only_affected_five_minute_symbols": True,
                    "intraday_context_gap_blocks_new_entries_globally": False,
                    "five_minute_strategy_context": five_minute_strategy_context,
                    "five_minute_session_coverage": session_coverage,
                    "confirmed_boundary_gate": confirmed_boundary_gate,
                    "new_position_market_data_gate_ready": (
                        confirmed_boundary_gate.get(
                            "new_position_submission_enabled"
                        )
                    ),
                    "postclose_intraday_recovery": postclose_recovery_status,
                    "partial_bar_suppressed_until": partial_bar_suppressed_until,
                    "daily_context_worker_pids": [worker.pid for worker, _started_at, _symbols in daily_workers.values()],
                    "account_snapshot_age_seconds": age,
                    "account_snapshot_healthy": account_snapshot_ready,
                    "account_snapshot_worker_pid": snapshot.get("worker_pid"),
                    "account_snapshot_worker_generation": snapshot.get("worker_generation"),
                    "account_snapshot_worker_status": snapshot.get("worker_refresh_status"),
                    "account_snapshot_worker_elapsed_seconds": snapshot.get("worker_refresh_elapsed_seconds"),
                    "account_snapshot_worker_restart_count": snapshot.get("worker_restart_count"),
                    "account_snapshot_worker_timeout_count": snapshot.get("worker_consecutive_timeouts"),
                    "account_snapshot_circuit_open": bool(snapshot.get("worker_circuit_open")),
                    "dispatch_enabled": effective_runtime_dispatch_enabled(
                        dispatch_requested=dispatch_enabled,
                        paper_client_ready=paper_client is not None,
                        trade_context_ready=bool(trade_context_health.get("ok")),
                        market_data_ready=(
                            market_data_ready_for_dispatch(
                                worker_ready=worker_ready,
                                market_data_mode=market_data_mode,
                                snapshot_fallback_validated=(
                                    market_data_fallback_validated
                                ),
                            )
                            and confirmed_boundary_gate.get(
                                "new_position_submission_enabled"
                            ) is True
                        ),
                        trading_daily_context_ready=trading_daily_context_ready,
                        flatten_blocks_new_entries=flatten_blocks_new_entries,
                        account_snapshot_ready=account_snapshot_ready,
                    ),
                    "dispatch_requested": dispatch_requested,
                    "trade_context_health": trade_context_health,
                    "dispatch_block_reason": runtime_dispatch_block_reason(
                        paper_order_dispatch_enabled=config.paper_order_dispatch_enabled,
                        readonly_gate_blocked=(
                            config.two_day_readonly_gate
                            and not readonly_gate_passed_now
                        ),
                        paper_client_ready=paper_client is not None,
                        trade_context_ready=bool(trade_context_health.get("ok")),
                        market_data_ready=(
                            market_data_ready_for_dispatch(
                                worker_ready=worker_ready,
                                market_data_mode=market_data_mode,
                                snapshot_fallback_validated=(
                                    market_data_fallback_validated
                                ),
                            )
                            and confirmed_boundary_gate.get(
                                "new_position_submission_enabled"
                            ) is True
                        ),
                        flatten_blocks_new_entries=flatten_blocks_new_entries,
                        account_snapshot_ready=account_snapshot_ready,
                        trading_daily_context_ready=trading_daily_context_ready,
                        formal_activation_waiting=bool(
                            str(flatten_transition.get("status") or "")
                            == "waiting_for_regular_session"
                            and isinstance(flatten_transition.get("confirmation"), dict)
                            and flatten_transition["confirmation"].get("complete") is True
                            and int(
                                flatten_transition["confirmation"].get(
                                    "remaining_position_count"
                                )
                                or 0
                            )
                            == 0
                            and int(
                                flatten_transition["confirmation"].get("open_order_count")
                                or 0
                            )
                            == 0
                            and int(
                                flatten_transition["confirmation"].get(
                                    "pending_confirmation_count"
                                )
                                or 0
                            )
                            == 0
                        ),
                        authorized_cleanup_waiting=authorized_cleanup_waiting,
                    ),
                    "two_day_readonly_gate": config.two_day_readonly_gate,
                    "readonly_gate_path": str(config.readonly_gate_path),
                    "readonly_sessions_passed": readonly_sessions_passed,
                    "readonly_sessions_required": readonly_sessions_required,
                    "readonly_gate_passed": readonly_gate_passed_now,
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
        # Restore the previous handler before waking child processes.  A second
        # SIGTERM during Event.set() must not interrupt multiprocessing cleanup
        # and leave a misleading shutdown traceback in the runtime log.
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
        stop_event.set()
        stop_spawned_process(worker, graceful=True)
        for daily_worker, _started_at, _symbols in daily_workers.values():
            stop_spawned_process(daily_worker, graceful=False)
        for recovery_worker, _started_at, _symbols in postclose_recovery_workers.values():
            stop_spawned_process(recovery_worker, graceful=False)
        close_spawn_queue(message_queue)
        account.stop()
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


def process_age_seconds(pid: int) -> float | None:
    """Return Linux process age without spawning another command."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        start_ticks = int(fields[21])
        uptime_seconds = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        clock_ticks = int(os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, IndexError):
        return None
    return max(0.0, uptime_seconds - (start_ticks / clock_ticks))


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


def stop_legacy_cli_supervisor(config: Any) -> None:
    path = config.output_dir / LEGACY_CLI_PID_FILE
    pid = read_pid(path)
    if not pid or not process_alive(pid):
        path.unlink(missing_ok=True)
        return
    command = Path(f"/proc/{pid}/cmdline").read_text(encoding="utf-8", errors="ignore")
    if "run_m15_longbridge_realtime_session_supervisor.py" not in command:
        raise RuntimeError("refusing_to_stop_unrecognised_process")
    os.killpg(pid, signal.SIGTERM)
    path.unlink(missing_ok=True)


def rotate_runtime_log(
    path: Path,
    *,
    maximum_bytes: int = RUNTIME_LOG_ROTATE_BYTES,
) -> Path | None:
    """Compress an oversized stopped-runtime log before opening a new one."""
    try:
        if path.stat().st_size <= maximum_bytes:
            return None
    except OSError:
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archived = path.with_name(f"{path.stem}.{stamp}.archived.log")
    path.replace(archived)
    compressed = Path(f"{archived}.gz")
    try:
        with archived.open("rb") as source, gzip.open(compressed, "wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        archived.unlink()
        return compressed
    except OSError:
        compressed.unlink(missing_ok=True)
        return archived


def sdk_runtime_daemon_environment(config: Any) -> dict[str, str]:
    """Prepare the same child-only DNS environment for every daemon entrypoint."""
    environment = dict(os.environ)
    if any(
        str(environment.get(key) or "").strip()
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        )
    ):
        # The user's configured proxy is already the selected network route.
        # A fixed-address fallback would have to add Longbridge to NO_PROXY,
        # silently bypassing that route and reproducing the daemon-only timeout.
        return environment_without_m15_dns_override(environment)
    if str(getattr(config, "quote_region", "")).lower() != "cn":
        return environment
    config_path = Path(getattr(config, "config_path", DEFAULT_CONFIG_PATH))
    payload = prepare_sdk_dns_override(
        SDK_DNS_OVERRIDE_CACHE_DIR,
        SDK_DNS_OVERRIDE_ENV_FILE,
        runtime_config_path=config_path,
    )
    return process_local_environment(payload, base_environment=environment)


def start_runtime_daemon(args: argparse.Namespace, config: Any) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    GLOBAL_RUNTIME_START_LOCK.parent.mkdir(parents=True, exist_ok=True)
    # DNS preparation can involve bounded network probes.  Do it before taking
    # the global process lock so a simultaneous boot/watchdog recovery cannot
    # wait behind unrelated network setup and time out.
    child_environment = sdk_runtime_daemon_environment(config)
    with GLOBAL_RUNTIME_START_LOCK.open("a+", encoding="utf-8") as start_lock:
        try:
            fcntl.flock(start_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(
                "SDK 实时运行层已有启动或恢复操作正在进行；"
                "本次不重复等待，后台看护将在下一轮复查。"
            )
            return 0
        global_owner = read_pid(GLOBAL_QUOTE_SUBSCRIPTION_LOCK)
        local_owner = read_pid(config.output_dir / RUN_LOCK_FILE)
        lock_owner = global_owner or local_owner
        existing = lock_owner if lock_owner and process_alive(lock_owner) else read_pid(pid_path(config))
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
            try:
                status = json.loads(config.runtime_status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                status = {}
            expected_fingerprint = config_fingerprint(config)
            expected_source_fingerprint = runtime_source_fingerprint()
            same_invocation = bool(status.get("dispatch_requested", False)) == bool(args.dispatch)
            same_source = (
                str(status.get("runtime_source_fingerprint") or "")
                == expected_source_fingerprint
            )
            status_runtime_pid = str(status.get("runtime_pid") or "")
            startup_age = process_age_seconds(existing)
            # A full 147-symbol SDK history refresh is deliberately serialized
            # to honor the broker's single quote-connection boundary. Allow it
            # to finish instead of restarting a healthy, progressing loader.
            startup_grace_seconds = max(
                3600,
                int(getattr(config, "daily_context_deadline_seconds", 75)) * 8,
            )
            health_replacement_required = runtime_requires_health_replacement(
                status,
                config,
            )
            if (
                status_runtime_pid != str(existing)
                and startup_age is not None
                and startup_age < startup_grace_seconds
                and not health_replacement_required
            ):
                print(
                    "SDK 实时运行层正在恢复上下文，"
                    f"PID={existing}，启动 {int(startup_age)} 秒；不使用旧状态误杀新进程。"
                )
                return 0
            if (
                status_runtime_pid == str(existing)
                and str(status.get("status") or "")
                in {"starting", "starting_context_restore", "connecting"}
                and startup_age is not None
                and startup_age < startup_grace_seconds
                and not health_replacement_required
            ):
                print(
                    "SDK 实时运行层仍在有界启动阶段，"
                    f"PID={existing}，状态={status.get('status')}，"
                    f"启动 {int(startup_age)} 秒；等待其完成而不重启。"
                )
                return 0
            if (
                str(status.get("config_fingerprint") or "") == expected_fingerprint
                and same_source
                and same_invocation
                and not health_replacement_required
            ):
                print(f"SDK 实时运行层已在运行，PID={existing}")
                return 0
            if runtime_deployment_is_frozen() and not health_replacement_required:
                write_json_atomic(
                    config.output_dir / PENDING_RUNTIME_RELOAD_JSON,
                    {
                        "schema_version": "m15.sdk-pending-runtime-reload.v1",
                        "status": "deferred_until_postclose",
                        "generated_at": to_iso(datetime.now(UTC)),
                        "runtime_pid": existing,
                        "loaded_config_fingerprint": str(
                            status.get("config_fingerprint") or ""
                        ),
                        "expected_config_fingerprint": expected_fingerprint,
                        "loaded_runtime_source_fingerprint": str(
                            status.get("runtime_source_fingerprint") or ""
                        ),
                        "expected_runtime_source_fingerprint": (
                            expected_source_fingerprint
                        ),
                        "same_runtime_source": same_source,
                        "same_dispatch_invocation": same_invocation,
                        "health_replacement_required": False,
                        "new_entries_still_use_loaded_runtime_contract": True,
                    },
                )
                print(
                    "SDK 实时运行层处于交易时段部署冻结，"
                    f"PID={existing}；新版本将在盘后重载。"
                )
                return 0
            if not request_runtime_shutdown(existing):
                raise RuntimeError("sdk_runtime_shutdown_escalation_failed")
            pid_path(config).unlink(missing_ok=True)
        stop_legacy_cli_supervisor(config)
        rotate_runtime_log(config.output_dir / LOG_FILE)
        command = [sys.executable, str(Path(__file__).resolve()), "--watch", "--config", str(args.config)]
        if args.dispatch:
            command.append("--dispatch")
        with (config.output_dir / LOG_FILE).open("a", encoding="utf-8") as handle:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=handle,
                stderr=handle,
                start_new_session=True,
                env=child_environment,
            )
        pid_path(config).write_text(f"{process.pid}\n", encoding="utf-8")
        (config.output_dir / PENDING_RUNTIME_RELOAD_JSON).unlink(missing_ok=True)
        print(f"SDK 实时运行层已启动，PID={process.pid}")
    return 0


def _read_runtime_status(config: Any) -> dict[str, Any]:
    try:
        payload = json.loads(config.runtime_status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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
        alive = bool(pid and process_alive(pid))
        payload.update({
            "runtime_process_alive": alive,
            "runtime_pid": pid or "",
            "expected_config_fingerprint": config_fingerprint(config),
            "expected_runtime_source_fingerprint": runtime_source_fingerprint(),
        })
        if not alive:
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
        return 0
    try:
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
