#!/usr/bin/env python3
"""Persistent, SDK-only M15 paper runtime.

The quote connection lives in a child process because a native SDK subscribe
call may block indefinitely.  Quote callbacks only aggregate bars and send
completed bars to the parent; the parent owns routing, risk and paper orders.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import queue
import signal
import subprocess
import sys
import time
import uuid
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_PYTHON.parent.parent.resolve():
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]], os.environ)

from scripts.m15_longbridge_sdk_account_lib import SdkAccountCoordinator, SdkAccountStateProvider, SdkTradeRequestGate
from scripts.m15_longbridge_sdk_runtime_lib import (
    DEFAULT_CONFIG_PATH, FiveMinuteBarBuilder, MarketEventContext, SdkRealtimePaperClient,
    append_market_events, build_status, compact_market_events, config_fingerprint, configured_symbols,
    daily_context_is_complete, floor_bar_open, fresh_market_events, load_config, load_valid_daily_context_cache, read_client_id,
    load_current_sdk_intraday_context, load_formal_test_marker, readonly_gate_passed, record_readonly_session,
    sdk_config_from_oauth, sdk_object_to_dict, sdk_order_maintenance_actions, summarize_latency_samples, write_daily_context_cache,
    subscribe_quote_and_trades, to_iso,
)
from scripts.m15_sdk_validation_flatten_lib import (
    activate_formal_epoch_payload,
    build_flatten_plan,
    flatten_confirmation,
    in_regular_session,
    latest_flatten_prices,
    runtime_flatten_order_payload,
)

NEW_YORK = ZoneInfo("America/New_York")
PID_FILE = "m15_longbridge_sdk_runtime.pid"
LOG_FILE = "m15_longbridge_sdk_runtime.log"
LEGACY_CLI_PID_FILE = "m15_longbridge_realtime_session_supervisor.pid"
EXECUTION_LEDGER_FILE = "m15_longbridge_realtime_execution_ledger.jsonl"
ORDER_MAINTENANCE_FILE = "m15_sdk_order_maintenance.json"


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
    missing = [name for name in ("QuoteContext", "TradeContext", "PortfolioContext") if not getattr(lb, name, None)]
    if missing:
        raise RuntimeError(f"sdk_contract_missing:{','.join(missing)}")
    return lb


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
    active_quote_runtime = bool(
        runtime_status.get("sdk_connected") is True
        and str(runtime_status.get("config_fingerprint") or "") == config_fingerprint(config)
        and process_alive(int(runtime_status.get("runtime_pid") or 0))
    )
    if active_quote_runtime:
        quote_probe_source = "active_sdk_runtime_status"
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
    try:
        response = trade.estimate_max_purchase_quantity(
            configured_symbols(config)[0],
            sdk.OrderType.LO,
            sdk.OrderSide.Sell,
            price=Decimal("1"),
        )
        short_capacity = str(getattr(response, "cash_max_qty", "0"))
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
        "short_capacity_probe_ok": not short_capacity_error,
        "short_capacity_probe_quantity": short_capacity,
        "errors": errors,
    }


def emit_worker(queue_out: Any, payload: dict[str, Any]) -> None:
    try:
        queue_out.put_nowait(payload)
    except queue.Full:
        # Bars are never replayed after a saturated queue: a later fresh event
        # is safer than an old order intent.
        return


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


def load_daily_context(
    quote: Any,
    sdk: Any,
    symbols: tuple[str, ...],
    bars: int,
    queue_out: Any,
    *,
    task_id: str = "",
) -> list[str]:
    failures: list[str] = []
    all_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            candles = quote.candlesticks(symbol, sdk.Period.Day, bars, sdk.AdjustType.NoAdjust)
            all_rows.extend(event_rows_to_daily(symbol, list(candles), datetime.now(UTC)))
        except Exception:
            failures.append(symbol)
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


def quote_worker(config_path: str, queue_out: Any, stop_event: Any) -> None:
    """Own the one SDK quote connection and never run history, routing or orders."""
    config = load_config(config_path)
    try:
        sdk = require_sdk_contract()
        oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
        quote = sdk.QuoteContext(sdk_config_from_oauth(sdk, oauth, config.quote_region))
        worker_started_at = datetime.now(UTC)
        first_complete_bar_open = floor_bar_open(worker_started_at, config.bar_minutes) + timedelta(
            minutes=config.bar_minutes
        )
        builder = FiveMinuteBarBuilder(
            config.bar_minutes,
            complete_bar_open_not_before=first_complete_bar_open,
        )

        def on_quote(symbol: str, event: Any) -> None:
            completed = builder.on_quote(symbol, sdk_object_to_dict(event), received_at=datetime.now(UTC))
            if completed:
                emit_worker(queue_out, {"kind": "bars", "rows": completed})

        quote.set_on_quote(on_quote)
        failed = subscribe_quote_and_trades(
            quote,
            list(configured_symbols(config)),
            [sdk.SubType.Quote],
            batch_size=config.subscription_batch_size,
            retry_count=config.subscription_retry_count,
        )
        expected = set(configured_symbols(config))
        # A failed subscription batch can make the SDK's query itself fail.
        # In that case the individual fallback above is the authoritative list.
        subscribed = expected - set(failed)
        if not failed:
            try:
                subscribed = subscription_symbols(quote.subscriptions())
            except Exception:
                subscribed = expected
        missing = sorted((expected - subscribed) | set(failed))
        emit_worker(queue_out, {
            "kind": "ready", "subscribed_symbols": sorted(expected - set(missing)),
            "subscription_failed_symbols": missing, "daily_context_failed_symbols": [],
            "partial_bar_suppressed_until": to_iso(first_complete_bar_open.astimezone(UTC)),
        })
        last_heartbeat = 0.0
        while not stop_event.is_set():
            completed = builder.flush(datetime.now(UTC))
            if completed:
                emit_worker(queue_out, {"kind": "bars", "rows": completed})
            now = time.monotonic()
            if now - last_heartbeat >= 1:
                emit_worker(queue_out, {"kind": "heartbeat", "at": to_iso(datetime.now(UTC))})
                last_heartbeat = now
            stop_event.wait(0.2)
    except BaseException as exc:
        emit_worker(queue_out, {"kind": "error", "reason": f"sdk_quote_worker_failed:{type(exc).__name__}:{exc}"})


def daily_context_worker(config_path: str, symbols: list[str], task_id: str, queue_out: Any) -> None:
    """Fetch SDK daily bars outside the quote subscription process.

    Historical requests occasionally wait on a native SDK call.  Keeping them
    in a separate process means a timeout can be recovered without stopping
    the WebSocket feed or delaying a newly completed five-minute bar.
    """
    try:
        config = load_config(config_path)
        sdk = require_sdk_contract()
        oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
        quote = sdk.QuoteContext(sdk_config_from_oauth(sdk, oauth, config.quote_region))
        failures = load_daily_context(quote, sdk, tuple(symbols), config.daily_context_bars, queue_out, task_id=task_id)
        emit_worker(queue_out, {"kind": "daily_context_task_complete", "task_id": task_id, "failures": failures})
    except BaseException as exc:
        emit_worker(queue_out, {
            "kind": "daily_context_error", "task_id": task_id, "symbols": symbols,
            "reason": f"sdk_daily_context_failed:{type(exc).__name__}:{exc}",
        })


def account_age_seconds(snapshot: dict[str, Any]) -> int | None:
    value = str(snapshot.get("generated_at") or "")
    try:
        created = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(UTC) - created.astimezone(UTC)).total_seconds()))


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


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
    for symbol, rows in grouped.items():
        rows.sort(key=lambda row: str(row.get("event_time") or ""))
        first, latest = rows[0], rows[-1]
        if (
            active_five_minute_event_ids is not None
            and str(latest.get("event_id") or "") not in active_five_minute_event_ids
        ):
            continue
        open_price = Decimal(str(first.get("open") or "0"))
        high = max(Decimal(str(row.get("high") or "0")) for row in rows)
        low = min(Decimal(str(row.get("low") or "0")) for row in rows)
        close = Decimal(str(latest.get("close") or "0"))
        volume = sum(max(0, int(Decimal(str(row.get("volume") or "0")))) for row in rows)
        if min(open_price, high, low, close) <= 0:
            continue
        latest_event_time = str(latest.get("event_time") or "")
        daily_rows.append({
            "schema_version": "m15.realtime-market-event.v2",
            "event_id": f"sdk-1d-live|{symbol}|{session_date}|{latest_event_time}",
            "symbol": symbol,
            "timeframe": "1d",
            "event_time": latest_event_time,
            "received_at": str(latest.get("received_at") or to_iso(generated_at)),
            "source_event_at": str(latest.get("source_event_at") or latest_event_time),
            "bar_final": False,
            "current_session_confirmation": True,
            "source_mode": "longbridge_sdk_live_daily_confirmation",
            "open": str(open_price),
            "high": str(high),
            "low": str(low),
            "close": str(close),
            "volume": str(volume),
            "local_simulation_ignored": True,
        })
    return daily_rows


def dispatch_completed_rows(
    config: Any,
    rows: list[dict[str, Any]],
    market_context: MarketEventContext,
    account_coordinator: SdkAccountCoordinator,
    paper_client: SdkRealtimePaperClient | None,
) -> dict[str, Any]:
    fresh = fresh_market_events(rows, config.maximum_source_delivery_age_ms)
    append_market_events(config.market_events_path, fresh, config.event_keep_lines)
    new_rows = market_context.append(fresh)
    if not new_rows:
        return {"event_count": 0, "signal_count": 0, "execution": {}}
    from scripts.m15_longbridge_realtime_signal_router_lib import load_config as load_router_config, run_realtime_signal_router
    from scripts.m15_longbridge_realtime_position_manager_lib import load_config as load_position_config, run_realtime_position_manager
    from scripts.m15_longbridge_realtime_execution_lib import load_config as load_execution_config, run_realtime_execution

    now = str(new_rows[-1]["received_at"])
    active_ids = {str(row["event_id"]) for row in new_rows}
    market_rows = market_context.rows()
    live_daily_rows = build_live_daily_confirmation_rows(
        market_rows,
        generated_at=datetime.fromisoformat(now.replace("Z", "+00:00")),
        active_five_minute_event_ids={
            str(row.get("event_id") or "")
            for row in new_rows
            if str(row.get("timeframe") or "") == "5m" and row.get("bar_final") is True
        },
    )
    active_ids.update(str(row.get("event_id") or "") for row in live_daily_rows)
    router_market_rows = market_rows + live_daily_rows
    router = load_router_config(config.router_config_path)
    formal_marker = load_formal_test_marker(config)
    if formal_marker:
        router = replace(
            router,
            short_test_epoch_id=str(formal_marker["short_test_epoch_id"]),
            short_test_started_at=str(formal_marker["test_started_at"]),
        )
    emitted: list[dict[str, Any]] = []
    router_payload = run_realtime_signal_router(
        router, generated_at=now, market_events_override=router_market_rows,
        active_market_event_ids=active_ids, emitted_signal_events=emitted,
    )
    snapshot = account_coordinator.snapshot()
    position_config = replace(load_position_config(config.position_manager_config_path), market_events_path=config.market_events_path)
    if formal_marker:
        position_config = replace(
            position_config,
            short_test_epoch_id=str(formal_marker["short_test_epoch_id"]),
        )
    positions = run_realtime_position_manager(
        position_config, generated_at=now, account_state_override=snapshot, market_events_override=market_context.rows(),
    )
    execution: dict[str, Any] = {}
    flatten_pending = str(formal_marker.get("status") or "") == "pending_flatten"
    if paper_client is not None and not flatten_pending:
        execution_config = load_execution_config(config.execution_config_path)
        if formal_marker:
            execution_config = replace(
                execution_config,
                test_epoch_id=str(formal_marker["test_epoch_id"]),
                short_test_epoch_id=str(formal_marker["short_test_epoch_id"]),
                short_test_started_at=str(formal_marker["test_started_at"]),
            )
        execution = run_realtime_execution(
            execution_config, generated_at=now, broker_client=paper_client,
            account_state_override=snapshot,
            signal_events_override=emitted + list(positions.get("emitted_exit_signal_events", [])),
        )
    elif flatten_pending:
        execution = {"status": "blocked_pending_account_flatten", "submitted_count": 0}
    return {
        "event_count": len(new_rows),
        "signal_count": len(emitted),
        "live_daily_confirmation_count": len(live_daily_rows),
        "router": router_payload,
        "execution": execution,
        "formal_test_epoch_id": str(formal_marker.get("test_epoch_id") or ""),
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


def request_runtime_shutdown(pid: int, *, timeout_seconds: float = 5.0) -> bool:
    """Ask the runtime parent to stop cleanly without killing its workers first."""
    if not process_alive(pid):
        return True
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not process_alive(pid)


def run_watch(config: Any, *, dispatch_requested: bool) -> int:
    sdk = require_sdk_contract()
    run_id = f"sdk-{uuid.uuid4().hex[:12]}"
    loaded_config_fingerprint = config_fingerprint(config)
    readonly_gate_passed_now, readonly_sessions_passed, readonly_sessions_required = readonly_gate_passed(config.readonly_gate_path)
    dispatch_enabled = bool(
        dispatch_requested
        and config.paper_order_dispatch_enabled
        and (not config.two_day_readonly_gate or readonly_gate_passed_now)
    )
    oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
    request_gate = SdkTradeRequestGate()
    trade = sdk.TradeContext(sdk_config_from_oauth(sdk, oauth, config.trade_region))
    portfolio = sdk.PortfolioContext(sdk_config_from_oauth(sdk, oauth, config.trade_region))
    account = SdkAccountCoordinator(
        SdkAccountStateProvider(trade, portfolio, request_gate=request_gate),
        config.output_dir / "m15_longbridge_realtime_account_state.json",
        interval_seconds=config.account_snapshot_interval_seconds,
    )
    account.start()
    paper_client = SdkRealtimePaperClient(trade, sdk, request_gate=request_gate, on_submission=account.note_submission) if dispatch_enabled else None
    flatten_client = SdkRealtimePaperClient(
        trade,
        sdk,
        request_gate=request_gate,
        on_submission=account.note_submission,
    )
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
    context = MarketEventContext(
        maximum_rows=(len(configured_symbols(config)) * config.daily_context_bars) + 4096
    )
    context.append(cached_daily_rows)
    context.append(cached_intraday_rows)
    # PyO3 SDK contexts must not be inherited through fork.  A fresh spawned
    # interpreter gives the quote WebSocket its own native runtime and makes
    # a blocked subscribe call safely terminable by the parent.
    process_context = mp.get_context("spawn")
    message_queue: Any = process_context.Queue(maxsize=2048)
    stop_event: Any = process_context.Event()
    worker: mp.Process | None = None
    attempts = 0
    worker_ready = False
    worker_started = 0.0
    last_event_at = ""
    last_compaction = 0.0
    last_order_maintenance = 0.0
    last_result: dict[str, Any] = {}
    order_maintenance: dict[str, Any] = {}
    flatten_transition: dict[str, Any] = {}
    pipeline_latency_samples: deque[int] = deque(maxlen=200)
    daily_rows: list[dict[str, Any]] = list(cached_daily_rows)
    subscription_failed: list[str] = []
    daily_failed: list[str] = []
    daily_workers: dict[str, tuple[mp.Process, float, list[str]]] = {}
    daily_pending: deque[list[str]] = deque()
    daily_completed: set[str] = set()
    daily_retry_counts: dict[str, int] = {}
    daily_task_failures: dict[str, list[str]] = {}
    daily_context_state = "complete" if cached_daily_rows else "waiting_for_subscription"
    daily_context_cache_reused = bool(cached_daily_rows)
    daily_context_persisted = bool(cached_daily_rows)
    observed_regular_sessions: set[str] = set()
    postclose_daily_refresh_dates: set[str] = set()
    deferred_messages: deque[dict[str, Any]] = deque()
    partial_bar_suppressed_until = ""
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def stop_requested(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_requested)
    try:
        while True:
            if worker is None or not worker.is_alive():
                if worker is not None:
                    worker.join(timeout=0.2)
                    attempts += 1
                if attempts >= config.maximum_consecutive_subscription_failures:
                    build_status(config, status="halted_subscription_failures", reason="sdk_subscription_recovery_limit_reached", sdk_installed=True, oauth_client_id_present=True, extra={"run_id": run_id, "dispatch_enabled": False, "worker_attempts": attempts})
                    return 2
                worker_ready = False
                worker_started = time.monotonic()
                worker = process_context.Process(target=quote_worker, args=(str(config.config_path), message_queue, stop_event), daemon=True)
                worker.start()
            if not worker_ready and time.monotonic() - worker_started > config.subscription_deadline_seconds:
                stop_spawned_process(worker, graceful=False)
                worker = None
                continue
            if worker_ready and daily_context_state == "waiting_for_subscription":
                symbols = list(configured_symbols(config))
                daily_pending = deque(
                    symbols[index:index + config.daily_context_batch_size]
                    for index in range(0, len(symbols), config.daily_context_batch_size)
                )
                daily_context_state = "loading"
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
                        for symbol in symbols:
                            daily_retry_counts[symbol] = daily_retry_counts.get(symbol, 0) + 1
                            if daily_retry_counts[symbol] <= 2:
                                daily_pending.append([symbol])
                            else:
                                daily_failed.append(symbol)
                if not daily_pending and not daily_workers and daily_context_state == "loading":
                    daily_context_state = "complete" if daily_rows and not daily_failed else "failed"
                if daily_context_is_complete(config, daily_context_state, len(daily_rows), daily_failed) and not daily_context_persisted:
                    write_daily_context_cache(config.daily_context_path, daily_rows)
                    daily_context_persisted = True
            try:
                message = deferred_messages.popleft() if deferred_messages else message_queue.get(timeout=config.heartbeat_interval_seconds)
            except queue.Empty:
                message = {"kind": "idle"}
            kind = str(message.get("kind") or "")
            if kind == "ready":
                subscription_failed = list(message.get("subscription_failed_symbols") or [])
                daily_failed = list(message.get("daily_context_failed_symbols") or [])
                partial_bar_suppressed_until = str(message.get("partial_bar_suppressed_until") or "")
                worker_ready = not subscription_failed and not daily_failed
                if not worker_ready:
                    stop_spawned_process(worker, graceful=False)
                    worker = None
                    continue
            elif kind == "daily_context":
                rows = list(message.get("rows") or [])
                daily_rows.extend(rows)
                task_id = str(message.get("task_id") or "")
                daily_task_failures[task_id] = [str(value) for value in (message.get("failures") or [])]
                context.append(rows)
            elif kind == "daily_context_task_complete":
                task_id = str(message.get("task_id") or "")
                if task_id in daily_workers:
                    daily_worker, _started_at, _symbols = daily_workers.pop(task_id)
                    stop_spawned_process(daily_worker, graceful=True)
                daily_completed.add(task_id)
                failures = daily_task_failures.pop(task_id, [str(value) for value in (message.get("failures") or [])])
                for symbol in failures:
                    daily_retry_counts[symbol] = daily_retry_counts.get(symbol, 0) + 1
                    if daily_retry_counts[symbol] <= 2:
                        daily_pending.append([symbol])
                    else:
                        daily_failed.append(symbol)
            elif kind == "daily_context_error":
                task_id = str(message.get("task_id") or "")
                task = daily_workers.pop(task_id, None)
                if task is not None:
                    daily_worker, _started_at, symbols = task
                    stop_spawned_process(daily_worker, graceful=True)
                else:
                    symbols = [str(value) for value in (message.get("symbols") or [])]
                daily_completed.add(task_id)
                for symbol in symbols:
                    daily_retry_counts[symbol] = daily_retry_counts.get(symbol, 0) + 1
                    if daily_retry_counts[symbol] <= 2:
                        daily_pending.append([symbol])
                    else:
                        daily_failed.append(symbol)
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
                daily_context_ready = daily_context_is_complete(
                    config, daily_context_state, len(daily_rows), daily_failed
                )
                active_client = paper_client if daily_context_ready else None
                last_result = dispatch_completed_rows(config, rows, context, account, active_client)
                elapsed = int((time.perf_counter() - started) * 1000)
                last_result["pipeline_elapsed_ms"] = elapsed
                pipeline_latency_samples.append(elapsed)
                expected_symbols = set(configured_symbols(config))
                batch_symbols = {
                    f"{str(row.get('symbol') or '').upper().replace('.US', '')}.US"
                    for row in rows
                    if str(row.get("symbol") or "")
                }
                last_result["bar_batch_symbol_count"] = len(batch_symbols)
                last_result["bar_batch_expected_symbol_count"] = len(expected_symbols)
                last_result["bar_batch_missing_symbols"] = sorted(expected_symbols - batch_symbols)
                last_event_at = str((rows or [{}])[-1].get("received_at") or last_event_at)
            elif kind == "error":
                worker_ready = False
                subscription_failed = [str(message.get("reason") or "sdk_quote_worker_failed")]
                if worker is not None:
                    stop_spawned_process(worker, graceful=False)
                    worker = None
            if time.monotonic() - last_compaction >= 60:
                compact_market_events(config.market_events_path, config.event_keep_lines)
                last_compaction = time.monotonic()
            maintenance_now = datetime.now(UTC)
            if dispatch_enabled:
                flatten_transition = run_pending_flatten_cycle(
                    config,
                    account,
                    flatten_client,
                    context.rows(),
                    now=maintenance_now,
                )
            else:
                flatten_transition = {
                    "status": "disabled_without_paper_order_dispatch",
                    "blocks_new_entries": True,
                }
            flatten_blocks_new_entries = bool(flatten_transition.get("blocks_new_entries"))
            near_five_minute_boundary = maintenance_now.minute % 5 == 0 and maintenance_now.second <= 2
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
            daily_context_ready = daily_context_is_complete(
                config, daily_context_state, len(daily_rows), daily_failed
            )
            now_ny = datetime.now(NEW_YORK)
            session_date = now_ny.date().isoformat()
            if (
                worker_ready
                and daily_context_ready
                and now_ny.weekday() < 5
                and (now_ny.hour, now_ny.minute) >= (16, 10)
                and session_date not in postclose_daily_refresh_dates
            ):
                # Refresh the completed daily bar after close so tomorrow's
                # session never starts with yesterday's stale context.
                postclose_daily_refresh_dates.add(session_date)
                context = MarketEventContext(
                    maximum_rows=(len(configured_symbols(config)) * config.daily_context_bars) + 4096
                )
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
                    "subscription_coverage": f"{len(configured_symbols(config))}/{len(configured_symbols(config))}",
                    "daily_context_row_count": len(daily_rows),
                    "last_event_at": last_event_at,
                    "account_snapshot_age_seconds": age,
                    "runtime_engine": "sdk",
                })
                readonly_gate_passed_now = bool(gate.get("passed"))
                readonly_sessions_passed = len(gate.get("completed_sessions", []))
                observed_regular_sessions.add(session_date)
                if dispatch_requested and config.paper_order_dispatch_enabled and readonly_gate_passed_now and paper_client is None:
                    paper_client = SdkRealtimePaperClient(trade, sdk, request_gate=request_gate, on_submission=account.note_submission)
                    dispatch_enabled = True
            build_status(
                config,
                status="running" if worker_ready else "connecting",
                reason="" if worker_ready else "waiting_for_full_sdk_subscription",
                connected=worker_ready,
                last_event_at=last_event_at,
                sdk_installed=True,
                oauth_client_id_present=True,
                pipeline_metrics=summarize_latency_samples(list(pipeline_latency_samples)),
                subscription_failed_symbols=subscription_failed,
                extra={
                    "run_id": run_id, "runtime_pid": os.getpid(), "quote_worker_pid": worker.pid if worker else "",
                    "config_fingerprint": loaded_config_fingerprint,
                    "subscription_coverage": f"{len(configured_symbols(config)) - len(subscription_failed) if worker_ready else 0}/{len(configured_symbols(config))}",
                    "daily_context_row_count": len(daily_rows), "daily_context_failed_symbols": daily_failed,
                    "daily_context_state": daily_context_state,
                    "daily_context_cache_reused": daily_context_cache_reused,
                    "intraday_context_cache_reused": bool(cached_intraday_rows),
                    "intraday_context_row_count": len(cached_intraday_rows),
                    "partial_bar_suppressed_until": partial_bar_suppressed_until,
                    "daily_context_worker_pids": [worker.pid for worker, _started_at, _symbols in daily_workers.values()],
                    "account_snapshot_age_seconds": age, "account_snapshot_healthy": age is not None and age <= config.maximum_account_snapshot_age_seconds,
                    "dispatch_enabled": bool(dispatch_enabled and daily_context_ready and not flatten_blocks_new_entries),
                    "dispatch_requested": dispatch_requested,
                    "dispatch_block_reason": (
                        "pending_account_flatten"
                        if flatten_blocks_new_entries
                        else "two_day_readonly_gate"
                        if config.two_day_readonly_gate and not readonly_gate_passed_now
                        else (
                            "paper_order_dispatch_disabled"
                            if not config.paper_order_dispatch_enabled
                            else ("daily_context_incomplete" if not daily_context_ready else "")
                        )
                    ),
                    "two_day_readonly_gate": config.two_day_readonly_gate,
                    "readonly_gate_path": str(config.readonly_gate_path),
                    "readonly_sessions_passed": readonly_sessions_passed,
                    "readonly_sessions_required": readonly_sessions_required,
                    "readonly_gate_passed": readonly_gate_passed_now,
                    "last_hot_pipeline": last_result,
                    "order_maintenance": order_maintenance,
                    "sdk_auto_flatten": flatten_transition,
                    "formal_test_transition": load_formal_test_marker(config),
                },
            )
    except KeyboardInterrupt:
        return 0
    finally:
        stop_event.set()
        stop_spawned_process(worker, graceful=True)
        for daily_worker, _started_at, _symbols in daily_workers.values():
            stop_spawned_process(daily_worker, graceful=False)
        close_spawn_queue(message_queue)
        account.stop()
        signal.signal(signal.SIGTERM, previous_sigterm_handler)


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


def start_runtime_daemon(args: argparse.Namespace, config: Any) -> int:
    existing = read_pid(pid_path(config))
    if existing and process_alive(existing):
        try:
            status = json.loads(config.runtime_status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            status = {}
        expected_fingerprint = config_fingerprint(config)
        same_invocation = bool(status.get("dispatch_requested", False)) == bool(args.dispatch)
        if str(status.get("config_fingerprint") or "") == expected_fingerprint and same_invocation:
            print(f"SDK 实时运行层已在运行，PID={existing}")
            return 0
        if not request_runtime_shutdown(existing):
            raise RuntimeError("sdk_runtime_graceful_shutdown_timed_out")
        pid_path(config).unlink(missing_ok=True)
    stop_legacy_cli_supervisor(config)
    command = [sys.executable, str(Path(__file__).resolve()), "--watch", "--config", str(args.config)]
    if args.dispatch:
        command.append("--dispatch")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    with (config.output_dir / LOG_FILE).open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(command, cwd=str(ROOT), stdout=handle, stderr=handle, start_new_session=True)
    pid_path(config).write_text(f"{process.pid}\n", encoding="utf-8")
    print(f"SDK 实时运行层已启动，PID={process.pid}")
    return 0


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
