"""Build fail-closed SDK-only paper-account cleanup orders for one validation session."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, ROUND_FLOOR
from typing import Any
from zoneinfo import ZoneInfo

from scripts.m15_longbridge_realtime_execution_lib import (
    decimal,
    fmt_decimal,
    is_short_position_row,
    stable_client_request_id,
)

NEW_YORK = ZoneInfo("America/New_York")
ZERO = Decimal("0")
SHORT_MARKERS = {"short", "sell_short", "sell", "bearish"}
LONG_MARKERS = {"long", "buy", "buy_long", "bullish"}


def in_regular_session(now: datetime) -> bool:
    local = now.astimezone(NEW_YORK)
    return local.weekday() < 5 and time(9, 30) <= local.time().replace(tzinfo=None) < time(16, 0)


def market_date(now: datetime) -> str:
    return now.astimezone(NEW_YORK).date().isoformat()


def next_regular_session_start(now: datetime) -> datetime:
    local = now.astimezone(NEW_YORK)
    day = local.date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, time(9, 30), tzinfo=NEW_YORK).astimezone(UTC)


def flatten_confirmation(account_state: dict[str, Any], order_ids: list[str]) -> dict[str, Any]:
    positions = [row for row in account_state.get("positions", []) if isinstance(row, dict)]
    open_orders = [row for row in account_state.get("open_orders", []) if isinstance(row, dict)]
    pending_confirmations = [
        row
        for row in account_state.get("pending_confirmations", [])
        if isinstance(row, dict)
    ] + [row for row in open_orders if row.get("sdk_pending_confirmation")]
    orders = [row for row in account_state.get("orders", []) if isinstance(row, dict)]
    known_ids = {str(row.get("order_id") or row.get("id") or "") for row in orders}
    remaining = [
        {
            "symbol": str(row.get("symbol") or ""),
            "quantity": fmt_decimal(abs(decimal(row.get("quantity", "0")))),
        }
        for row in positions
        if abs(decimal(row.get("quantity", "0"))) > ZERO
    ]
    return {
        "complete": not remaining and not open_orders and not pending_confirmations,
        "remaining_positions": remaining,
        "remaining_position_count": len(remaining),
        "open_order_ids": [str(row.get("order_id") or row.get("id") or "") for row in open_orders],
        "open_order_count": len(open_orders),
        "pending_confirmation_count": len(pending_confirmations),
        "broker_visible_order_ids": sorted(order_id for order_id in known_ids if order_id),
        "submitted_order_ids_not_yet_in_history": sorted(order_id for order_id in order_ids if order_id not in known_ids),
    }


def activate_formal_epoch_payload(marker: dict[str, Any], *, activated_at: datetime) -> dict[str, Any]:
    """Activate the existing epoch only after the SDK account is proven flat."""
    return {
        **marker,
        "status": "active",
        "test_started_at": activated_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "activated_at": activated_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "activation_blocker": "",
        "activation_condition_met": "positions_open_orders_pending_confirmations_zero",
    }


def formal_epoch_payload(
    *,
    test_epoch_id: str,
    short_test_epoch_id: str,
    test_started_at: datetime,
    prepared_at: datetime,
) -> dict[str, Any]:
    return {
        "stage": "M15.sdk_formal_test_epoch",
        "status": "scheduled",
        "test_epoch_id": test_epoch_id,
        "short_test_epoch_id": short_test_epoch_id,
        "test_started_at": test_started_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "prepared_at": prepared_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "activation_condition": "paper_account_flat_after_sdk_validation",
    }


def pending_formal_epoch_payload(
    *,
    test_epoch_id: str,
    short_test_epoch_id: str,
    prepared_at: datetime,
    reason: str,
) -> dict[str, Any]:
    return {
        "stage": "M15.sdk_formal_test_epoch",
        "status": "pending_flatten",
        "test_epoch_id": test_epoch_id,
        "short_test_epoch_id": short_test_epoch_id,
        "test_started_at": "",
        "prepared_at": prepared_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "activation_condition": "paper_account_flat_after_sdk_validation",
        "activation_blocker": reason,
    }


def position_direction(row: dict[str, Any]) -> str:
    """Classify the broker position without guessing an unfamiliar direction field."""
    if is_short_position_row(row):
        return "short"
    markers = [
        str(row.get(key) or "").strip().lower()
        for key in ("position_side", "side", "direction", "position_type", "holding_side")
        if str(row.get(key) or "").strip()
    ]
    if not markers or all(marker in LONG_MARKERS for marker in markers):
        return "long"
    if any(marker in SHORT_MARKERS for marker in markers):
        return "short"
    return "unknown"


def close_quantity(row: dict[str, Any], direction: str) -> Decimal:
    held = abs(decimal(row.get("quantity", row.get("qty", "0"))))
    if direction == "short":
        return held.to_integral_value(rounding=ROUND_FLOOR)
    available_value = row.get("available", row.get("available_quantity", row.get("sellable_quantity", held)))
    available = decimal(available_value)
    return min(held, available).to_integral_value(rounding=ROUND_FLOOR)


def quote_price(row: dict[str, Any], latest_prices: dict[str, Any]) -> tuple[Decimal, int]:
    symbol = str(row.get("symbol") or "").upper()
    quote_row = latest_prices.get(symbol)
    if isinstance(quote_row, dict):
        live_price = decimal(quote_row.get("price", "0"))
        quote_age_ms = int(quote_row.get("age_ms", -1))
    else:
        live_price = decimal(quote_row)
        quote_age_ms = -1
    if live_price > ZERO:
        return live_price, quote_age_ms
    return ZERO, -1


def build_flatten_plan(account_state: dict[str, Any], latest_prices: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Return either a complete close plan or blockers; never produce a partial plan."""
    positions = account_state.get("positions") if isinstance(account_state.get("positions"), list) else []
    plan: list[dict[str, Any]] = []
    blockers: list[str] = []
    for row in positions:
        if not isinstance(row, dict):
            blockers.append("invalid_position_row")
            continue
        symbol = str(row.get("symbol") or "").upper()
        direction = position_direction(row)
        quantity = close_quantity(row, direction)
        price, quote_age_ms = quote_price(row, latest_prices)
        if not symbol:
            blockers.append("position_missing_symbol")
            continue
        if direction == "unknown":
            blockers.append(f"unknown_position_direction:{symbol}")
            continue
        if quantity < Decimal("1"):
            blockers.append(f"position_quantity_not_available:{symbol}")
            continue
        if price <= ZERO:
            blockers.append(f"sdk_quote_missing:{symbol}")
            continue
        if direction == "long":
            side = "sell"
            action = "close_long"
        else:
            side = "buy"
            action = "close_short"
        plan.append(
            {
                "symbol": symbol,
                "direction": direction,
                "position_action": action,
                "side": side,
                "order_type": "market",
                "quantity": fmt_decimal(quantity),
                "limit_price": "",
                "reference_price": fmt_decimal(price),
                "reference_price_source": "official_sdk_quote",
                "reference_quote_age_ms": quote_age_ms,
            }
        )
    return ([], blockers) if blockers else (plan, [])


def latest_flatten_prices(
    market_events: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, dict[str, Any]]:
    """Return the newest SDK 5m close with a measured local delivery age."""
    latest: dict[str, tuple[datetime, Decimal]] = {}
    for row in market_events:
        if str(row.get("timeframe") or "") != "5m":
            continue
        if str(row.get("source_mode") or "") not in {
            "official_sdk_push",
            "official_sdk_trade_push",
        }:
            continue
        symbol = str(row.get("symbol") or "").upper()
        if symbol and "." not in symbol:
            symbol = f"{symbol}.US"
        price = decimal(row.get("close"))
        raw_timestamp = str(row.get("received_at") or row.get("event_time") or "")
        try:
            timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            continue
        if not symbol or price <= ZERO:
            continue
        if symbol not in latest or timestamp > latest[symbol][0]:
            latest[symbol] = (timestamp, price)
    current = now.astimezone(UTC)
    return {
        symbol: {
            "price": price,
            "age_ms": max(0, int((current - timestamp).total_seconds() * 1000)),
        }
        for symbol, (timestamp, price) in latest.items()
    }


def runtime_flatten_order_payload(intent: dict[str, Any], *, test_epoch_id: str) -> dict[str, Any]:
    symbol = str(intent.get("symbol") or "").upper()
    side = str(intent.get("side") or "").lower()
    action = str(intent.get("position_action") or "")
    signal_id = f"m15-sdk-account-flatten|{test_epoch_id}|{symbol}|{action}"
    return {
        **intent,
        "signal_id": signal_id,
        "runtime_id": "M15-LONGBRIDGE-SDK-AUTO-FLATTEN",
        "test_epoch_id": test_epoch_id,
        "client_request_id": stable_client_request_id(
            signal_id=signal_id,
            runtime_id="M15-LONGBRIDGE-SDK-AUTO-FLATTEN",
            symbol=symbol,
            side=side,
            position_action=action,
            test_epoch_id=test_epoch_id,
        ),
        "market_exit_no_reprice": True,
        "exit_only_position_signal": True,
    }
