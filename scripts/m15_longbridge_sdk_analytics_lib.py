#!/usr/bin/env python3
"""Refresh M15 reporting artifacts from Longbridge SDK data only."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import os
from pathlib import Path
import time
from typing import Any, Callable, TypeVar
from zoneinfo import ZoneInfo

from scripts.m15_longbridge_realtime_account_state_lib import (
    FILL_ATTRIBUTION_JSON,
    ORDER_RECONCILIATION_JSON,
    PNL_RECONCILIATION_JSON,
    REALTIME_EXECUTION_LEDGER_JSONL,
    STALE_ORDER_CLEANUP_LEDGER_JSONL,
    SUMMARY_JSON,
    TRUSTED_ORDER_HISTORY_JSON,
    UNFILLED_ORDER_DIAGNOSTICS_JSON,
    build_order_reconciliation,
    build_fill_attribution_v2,
    build_unfilled_order_diagnostics,
    enrich_order_reconciliation_with_stale_cleanup,
    load_config as load_account_config,
    read_json,
    read_jsonl,
    write_json,
)
from scripts.m15_longbridge_sdk_account_lib import sdk_plain
from scripts.m15_longbridge_sdk_runtime_lib import (
    QUOTE_SNAPSHOT_JSON,
    config_fingerprint,
    load_config as load_sdk_config,
    read_client_id,
    sdk_config_from_oauth,
)
from scripts.m15_longbridge_realtime_execution_lib import to_iso


MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS = 45
MIN_RUNTIME_STATUS_AGE_SECONDS = 15
NEW_YORK = ZoneInfo("America/New_York")
APP_DAILY_PNL_METRIC_ID = "longbridge_app_asset_daily_pnl_v1"
T = TypeVar("T")


def decimal_value(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def app_intraday_window_start(generated_at: datetime) -> datetime:
    """Return the latest 04:00 New York boundary used by the App without overnight quotes."""
    local = generated_at.astimezone(NEW_YORK)
    boundary = local.replace(hour=4, minute=0, second=0, microsecond=0)
    if local < boundary:
        boundary -= timedelta(days=1)
    return boundary.astimezone(UTC)


def normalize_app_quote(row: Any, generated_at: datetime) -> dict[str, str]:
    local = generated_at.astimezone(NEW_YORK)
    regular = decimal_value(getattr(row, "last_done", "0"))
    pre = getattr(row, "pre_market_quote", None)
    post = getattr(row, "post_market_quote", None)
    current = regular
    phase = "regular"
    minutes = local.hour * 60 + local.minute
    if 240 <= minutes < 570 and pre is not None:
        current = decimal_value(getattr(pre, "last_done", regular))
        phase = "pre_market"
    elif minutes >= 960 or minutes < 240:
        if post is not None:
            current = decimal_value(getattr(post, "last_done", regular))
            phase = "post_market"
    return {
        "symbol": str(getattr(row, "symbol", "")),
        "current_price": str(current),
        "prev_close": str(decimal_value(getattr(row, "prev_close", "0"))),
        "price_phase": phase,
    }


def load_runtime_quote_rows(
    runtime_config: Any,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    """Read the live runtime's quote snapshot without opening another SDK connection."""
    payload = read_json(runtime_config.output_dir / QUOTE_SNAPSHOT_JSON)
    if payload.get("metric_contract_id") != APP_DAILY_PNL_METRIC_ID:
        return []
    local = generated_at.astimezone(NEW_YORK)
    minutes = local.hour * 60 + local.minute
    is_regular_or_closing = local.weekday() < 5 and 570 <= minutes < 965
    is_same_day_postclose = (
        local.weekday() < 5
        and minutes >= 960
        and str(payload.get("market_date") or "") == local.date().isoformat()
    )
    latest_source_event_at = max(
        (
            str(row.get("source_event_at") or "")
            for row in (payload.get("rows") or [])
            if isinstance(row, dict)
        ),
        default="",
    )
    latest_quote_received_at = (
        latest_source_event_at
        or str(payload.get("latest_quote_received_at") or "")
    )
    try:
        latest_quote_date = datetime.fromisoformat(
            latest_quote_received_at.replace("Z", "+00:00")
        ).astimezone(NEW_YORK).date()
    except (TypeError, ValueError):
        latest_quote_date = None
    previous_market_date = (local.date() - timedelta(days=1))
    is_previous_day_overnight_postclose = bool(
        minutes < 240
        and previous_market_date.weekday() < 5
        and latest_quote_date == previous_market_date
    )
    if not (
        is_regular_or_closing
        or is_same_day_postclose
        or is_previous_day_overnight_postclose
    ):
        return []
    rows: list[dict[str, Any]] = []
    for source in payload.get("rows") or []:
        if not isinstance(source, dict):
            continue
        symbol = str(source.get("symbol") or "")
        current_price = decimal_value(source.get("current_price"))
        previous_close = decimal_value(source.get("prev_close"))
        try:
            received_at = datetime.fromisoformat(
                str(source.get("received_at") or "").replace("Z", "+00:00")
            ).astimezone(UTC)
        except (TypeError, ValueError):
            continue
        age_seconds = (generated_at.astimezone(UTC) - received_at).total_seconds()
        if (
            not symbol
            or current_price <= 0
            or previous_close <= 0
            or age_seconds < 0
            or (is_regular_or_closing and age_seconds > MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS)
        ):
            continue
        rows.append(dict(source))
    return rows


def build_app_display_metrics(
    generated_at: datetime,
    account_state: dict[str, Any],
    historical_orders: list[dict[str, Any]],
    historical_executions: list[dict[str, Any]],
    quote_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reproduce the Longbridge asset-page values from broker positions, fills and quotes."""
    window_start = app_intraday_window_start(generated_at)
    orders_by_id = {str(row.get("order_id") or ""): row for row in historical_orders}
    buy_quantity: dict[str, Decimal] = {}
    sell_quantity: dict[str, Decimal] = {}
    buy_amount: dict[str, Decimal] = {}
    sell_amount: dict[str, Decimal] = {}
    for execution in historical_executions:
        raw_time = str(execution.get("trade_done_at") or "")
        try:
            executed_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        if executed_at.tzinfo is None:
            executed_at = executed_at.replace(tzinfo=UTC)
        if not window_start <= executed_at.astimezone(UTC) <= generated_at.astimezone(UTC):
            continue
        order = orders_by_id.get(str(execution.get("order_id") or ""), {})
        side = enum_token(order.get("side")).lower()
        if side not in {"buy", "sell"}:
            continue
        symbol = str(execution.get("symbol") or order.get("symbol") or "")
        quantity = decimal_value(execution.get("quantity"))
        amount = quantity * decimal_value(execution.get("price"))
        quantity_map = buy_quantity if side == "buy" else sell_quantity
        amount_map = buy_amount if side == "buy" else sell_amount
        quantity_map[symbol] = quantity_map.get(symbol, Decimal("0")) + quantity
        amount_map[symbol] = amount_map.get(symbol, Decimal("0")) + amount

    current_quantity = {
        str(row.get("symbol") or ""): decimal_value(row.get("quantity"))
        for row in account_state.get("positions", [])
        if str(row.get("symbol") or "")
    }
    quotes_by_symbol = {
        str(row.get("symbol") or ""): row
        for row in quote_rows
        if str(row.get("symbol") or "")
        and decimal_value(row.get("current_price")) > 0
        and decimal_value(row.get("prev_close")) > 0
    }
    symbols = sorted(set(current_quantity) | set(buy_quantity) | set(sell_quantity))
    missing_symbols = [symbol for symbol in symbols if symbol not in quotes_by_symbol]
    symbol_rows: list[dict[str, str]] = []
    today_profit = Decimal("0")
    market_value = Decimal("0")
    cent = Decimal("0.01")
    for symbol in symbols:
        quote = quotes_by_symbol.get(symbol)
        if not quote:
            continue
        current = current_quantity.get(symbol, Decimal("0"))
        opening = current - buy_quantity.get(symbol, Decimal("0")) + sell_quantity.get(symbol, Decimal("0"))
        latest = decimal_value(quote.get("current_price"))
        previous_close = decimal_value(quote.get("prev_close"))
        symbol_profit = (
            latest * current
            - previous_close * opening
            + sell_amount.get(symbol, Decimal("0"))
            - buy_amount.get(symbol, Decimal("0"))
        ).quantize(cent, rounding=ROUND_HALF_UP)
        today_profit += symbol_profit
        market_value += latest * current
        symbol_rows.append(
            {
                "symbol": symbol,
                "opening_quantity": str(opening),
                "current_quantity": str(current),
                "current_price": str(latest),
                "previous_close": str(previous_close),
                "buy_amount": str(buy_amount.get(symbol, Decimal("0"))),
                "sell_amount": str(sell_amount.get(symbol, Decimal("0"))),
                "today_pnl": str(symbol_profit),
                "price_phase": str(quote.get("price_phase") or "regular"),
            }
        )
    available_cash = decimal_value(account_state.get("usd_available_cash") or account_state.get("cash"))
    frozen_cash = decimal_value(account_state.get("usd_frozen_cash"))
    total_cash = available_cash + frozen_cash
    complete = not missing_symbols
    return {
        "metric_contract_id": APP_DAILY_PNL_METRIC_ID,
        "status": "fresh" if complete else "incomplete",
        "currency": "USD",
        "window_start": to_iso(window_start),
        "window_end": to_iso(generated_at),
        "today_pnl": str(today_profit.quantize(cent, rounding=ROUND_HALF_UP)) if complete else "",
        "total_cash": str(total_cash.quantize(cent, rounding=ROUND_HALF_UP)),
        "market_value": str(market_value.quantize(cent, rounding=ROUND_HALF_UP)) if complete else "",
        "total_asset": str((total_cash + market_value).quantize(cent, rounding=ROUND_HALF_UP)) if complete else "",
        "symbol_pnl_rows": symbol_rows,
        "missing_symbols": missing_symbols,
        "source": (
            "longbridge_sdk_app_asset_daily_pnl_formula_v1"
            if complete
            else "longbridge_sdk_app_daily_pnl_inputs_incomplete"
        ),
    }


def market_profit_query_dates(generated_at: datetime) -> tuple[str, str]:
    """Return the New York market date and the SDK cumulative end boundary."""
    market_day = generated_at.astimezone(NEW_YORK).date()
    return market_day.isoformat(), (market_day + timedelta(days=1)).isoformat()


def read_with_timeout_recovery(
    context: T,
    context_factory: Callable[[], T],
    callback: Callable[[T], Any],
) -> tuple[Any, T]:
    """Retry one transient read/connect timeout on a fresh SDK context."""
    try:
        return callback(context), context
    except Exception as exc:
        error_text = str(exc).lower()
        if not any(marker in error_text for marker in ("request timeout", "connect timeout")):
            raise
        time.sleep(0.25)
        replacement = context_factory()
        return callback(replacement), replacement


def is_sdk_timeout_error(exc: Exception) -> bool:
    error_text = str(exc).lower()
    return any(
        marker in error_text
        for marker in (
            "request timeout",
            "connect timeout",
            "client error (connect)",
            "error sending request",
        )
    )


def enum_token(value: Any) -> str:
    return str(value or "").strip().split(".")[-1]


def normalize_order(row: Any) -> dict[str, Any]:
    output = sdk_plain(row)
    if not isinstance(output, dict):
        return {}
    output = dict(output)
    output["side"] = enum_token(output.get("side"))
    output["status"] = enum_token(output.get("status"))
    output["order_type"] = enum_token(output.get("order_type"))
    return output


def normalize_execution(row: Any) -> dict[str, Any]:
    output = sdk_plain(row)
    return dict(output) if isinstance(output, dict) else {}


def merge_history_rows(
    cached_rows: list[dict[str, Any]],
    recent_rows: list[dict[str, Any]],
    *,
    identity_field: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for row in [*cached_rows, *recent_rows]:
        key = str(row.get(identity_field) or "")
        if key:
            merged[key] = dict(row)
        else:
            unkeyed.append(dict(row))
    return [*merged.values(), *unkeyed]


def current_history_rows(
    cached_rows: list[dict[str, Any]],
    snapshot_rows: list[Any],
    *,
    identity_field: str,
    normalizer: Callable[[Any], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Update trusted history from the fresh account snapshot without a slow history scan."""
    return merge_history_rows(
        cached_rows,
        [normalizer(row) for row in snapshot_rows],
        identity_field=identity_field,
    )


def incremental_history_start(
    full_start: datetime,
    generated_at: datetime,
    *,
    cached_row_count: int,
) -> datetime:
    if cached_row_count <= 0:
        return full_start
    return max(full_start, generated_at.astimezone(UTC) - timedelta(days=2))


def refresh_order_and_execution_history(
    trade: Any,
    build_trade: Callable[[], Any],
    *,
    start_at: datetime,
    generated_at: datetime,
    cached_orders: list[dict[str, Any]],
    cached_executions: list[dict[str, Any]],
    account_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Any, str]:
    """Refresh broker history with a two-day overlap after bootstrap."""
    if cached_orders or cached_executions:
        incremental_start = incremental_history_start(
            start_at,
            generated_at,
            cached_row_count=max(len(cached_orders), len(cached_executions)),
        )
        recent_order_rows: list[Any] = []
        recent_execution_rows: list[Any] = []
        stale_reasons: list[str] = []
        try:
            recent_order_rows, trade = read_with_timeout_recovery(
                trade,
                build_trade,
                lambda context: context.history_orders(start_at=incremental_start, end_at=generated_at),
            )
        except Exception as exc:
            if not is_sdk_timeout_error(exc):
                raise
            stale_reasons.append("history_orders_timeout")
        try:
            recent_execution_rows, trade = read_with_timeout_recovery(
                trade,
                build_trade,
                lambda context: context.history_executions(start_at=incremental_start, end_at=generated_at),
            )
        except Exception as exc:
            if not is_sdk_timeout_error(exc):
                raise
            stale_reasons.append("history_executions_timeout")
        orders = merge_history_rows(
            cached_orders,
            [normalize_order(row) for row in recent_order_rows],
            identity_field="order_id",
        )
        executions = merge_history_rows(
            cached_executions,
            [normalize_execution(row) for row in recent_execution_rows],
            identity_field="trade_id",
        )
        orders = current_history_rows(
            orders,
            list(account_state.get("orders") or []),
            identity_field="order_id",
            normalizer=normalize_order,
        )
        executions = current_history_rows(
            executions,
            list(account_state.get("executions") or []),
            identity_field="trade_id",
            normalizer=normalize_execution,
        )
        if stale_reasons:
            return (
                orders,
                executions,
                trade,
                "trusted_cache_plus_fresh_snapshot_statistics_stale_" + "_".join(stale_reasons),
            )
        return orders, executions, trade, "trusted_cache_plus_two_day_sdk_incremental_and_fresh_snapshot"
    order_rows, trade = read_with_timeout_recovery(
        trade,
        build_trade,
        lambda context: context.history_orders(start_at=start_at, end_at=generated_at),
    )
    execution_rows, trade = read_with_timeout_recovery(
        trade,
        build_trade,
        lambda context: context.history_executions(start_at=start_at, end_at=generated_at),
    )
    return (
        [normalize_order(row) for row in order_rows],
        [normalize_execution(row) for row in execution_rows],
        trade,
        "sdk_history_bootstrap",
    )


def require_fresh_paper_account(
    account_state: dict[str, Any],
    generated_at: datetime,
    *,
    max_age_seconds: int = MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS,
) -> None:
    if not account_state.get("paper_account_verified") or account_state.get("account_channel") != "lb_papertrading":
        raise RuntimeError("sdk_analytics_requires_verified_paper_account")
    raw_generated_at = str(account_state.get("generated_at") or "")
    try:
        snapshot_at = datetime.fromisoformat(raw_generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("sdk_analytics_requires_fresh_account_snapshot") from exc
    if snapshot_at.tzinfo is None:
        snapshot_at = snapshot_at.replace(tzinfo=UTC)
    age_seconds = (generated_at.astimezone(UTC) - snapshot_at.astimezone(UTC)).total_seconds()
    if age_seconds < -5 or age_seconds > max_age_seconds:
        raise RuntimeError("sdk_analytics_requires_fresh_account_snapshot")


def require_live_sdk_runtime(runtime_config: Any, generated_at: datetime) -> None:
    """Reject analytics refreshes unless the configured SDK runtime is live and fresh."""
    runtime_status = read_json(runtime_config.runtime_status_path)
    status = str(runtime_status.get("status") or "")
    runtime_engine_ready = runtime_status.get("runtime_engine") == "sdk"
    fully_connected = status == "running" and runtime_status.get("sdk_connected") is True
    quote_recovery_is_readonly_safe = (
        status in {"connecting", "reconnecting_market_data_circuit"}
        and runtime_status.get("market_data_mode") == "sdk_snapshot_poll"
        and runtime_status.get("paper_simulated_only") is True
        and runtime_status.get("real_money_actions") is False
    )
    if not runtime_engine_ready or not (fully_connected or quote_recovery_is_readonly_safe):
        raise RuntimeError("sdk_analytics_requires_live_sdk_runtime")
    if str(runtime_status.get("config_fingerprint") or "") != config_fingerprint(runtime_config):
        raise RuntimeError("sdk_analytics_requires_matching_runtime_config")
    try:
        runtime_pid = int(runtime_status.get("runtime_pid") or 0)
        os.kill(runtime_pid, 0)
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError("sdk_analytics_requires_live_sdk_runtime") from exc
    try:
        status_at = datetime.fromisoformat(str(runtime_status.get("generated_at") or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("sdk_analytics_requires_fresh_runtime_status") from exc
    if status_at.tzinfo is None:
        status_at = status_at.replace(tzinfo=UTC)
    maximum_age_seconds = max(
        MIN_RUNTIME_STATUS_AGE_SECONDS,
        int(runtime_config.heartbeat_interval_seconds) * 3,
    )
    age_seconds = (generated_at.astimezone(UTC) - status_at.astimezone(UTC)).total_seconds()
    if age_seconds < -5 or age_seconds > maximum_age_seconds:
        raise RuntimeError("sdk_analytics_requires_fresh_runtime_status")


def build_sdk_pnl_reconciliation(
    generated_at: str,
    account_state: dict[str, Any],
    profit_analysis: dict[str, Any],
    start_date: str,
    end_date: str,
    daily_profit_analysis: dict[str, Any] | None = None,
    app_display_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profit = str(profit_analysis.get("profit") or "")
    daily_profit = str((daily_profit_analysis or {}).get("profit") or "")
    stock_items = profit_analysis.get("stock_items") if isinstance(profit_analysis.get("stock_items"), list) else []
    daily_stock_items = (
        daily_profit_analysis.get("stock_items")
        if isinstance(daily_profit_analysis, dict) and isinstance(daily_profit_analysis.get("stock_items"), list)
        else []
    )
    return {
        "schema_version": "m15.longbridge-account-pnl-reconciliation.sdk.v1",
        "stage": "M15.longbridge_account_pnl_reconciliation",
        "generated_at": generated_at,
        "source_mode": "longbridge_sdk_profit_analysis_by_market",
        "pnl_reconciliation_ok": True,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "local_simulation_isolated": True,
        "query_range": {"start": start_date, "end": end_date},
        "account_pnl": {
            "currency": "USD",
            "current_total_asset": account_state.get("account_total_equity_estimate"),
            "sum_profit": profit,
            "source": "longbridge_sdk_us_market_profit_analysis",
        },
        "today_account_pnl": {
            "metric_contract_id": APP_DAILY_PNL_METRIC_ID,
            "sum_profit": str((app_display_metrics or {}).get("today_pnl") or ""),
            "source": str((app_display_metrics or {}).get("source") or ""),
            "status": str((app_display_metrics or {}).get("status") or "incomplete"),
            "symbol_pnl_rows": list((app_display_metrics or {}).get("symbol_pnl_rows") or []),
            "window_start": (app_display_metrics or {}).get("window_start"),
            "window_end": (app_display_metrics or {}).get("window_end"),
        },
        "market_day_profit_analysis": {
            "sum_profit": daily_profit,
            "source": "longbridge_sdk_us_market_profit_analysis_single_market_date",
            "status": "fresh" if daily_profit else "暂不可计算",
            "symbol_pnl_rows": daily_stock_items,
        },
        "trading_pnl": {
            "stock_total_pnl": profit,
            "source": "longbridge_sdk_profit_analysis_by_market_us",
        },
        "current_holdings": list(account_state.get("positions") or []),
        "symbol_pnl_rows": stock_items,
        "source_status": {
            "status": "fresh",
            "sdk_profit_analysis_ok": True,
            "today_account_pnl_available": bool((app_display_metrics or {}).get("today_pnl")),
            "market_day_profit_analysis_available": bool(daily_profit),
        },
    }


def build_sdk_account_summary(
    generated_at: str,
    account_state: dict[str, Any],
    order_reconciliation: dict[str, Any],
    daily_profit_analysis: dict[str, Any] | None = None,
    app_display_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    daily_profit = str((daily_profit_analysis or {}).get("profit") or "")
    app_today_profit = str((app_display_metrics or {}).get("today_pnl") or "")
    app_total_asset = str((app_display_metrics or {}).get("total_asset") or "")
    if app_total_asset:
        total_equity = app_total_asset
        total_equity_currency = (app_display_metrics or {}).get("currency")
        total_equity_source = (app_display_metrics or {}).get("source")
    else:
        total_equity = account_state.get("account_total_equity_estimate")
        total_equity_currency = account_state.get("account_total_equity_currency")
        total_equity_source = account_state.get("account_total_equity_source")
    return {
        "schema_version": "m15.longbridge-realtime-account-state-summary.sdk.v1",
        "stage": "M15.longbridge_realtime_account_state",
        "title": "长桥模拟账户 SDK 统计",
        "generated_at": generated_at,
        "source_mode": "longbridge_sdk_slow_analytics",
        "account_status": "paper_account_ready" if account_state.get("paper_account_verified") else "paper_account_unverified",
        "paper_account_verified": bool(account_state.get("paper_account_verified")),
        "account_channel": account_state.get("account_channel"),
        "buying_power": account_state.get("account_buying_power"),
        "cash": (app_display_metrics or {}).get("total_cash") or account_state.get("cash"),
        "available_cash": account_state.get("cash"),
        "account_total_equity_estimate": total_equity,
        "account_total_equity_currency": total_equity_currency,
        "account_total_equity_source": total_equity_source,
        "account_today_total_pnl": app_today_profit or "暂不可计算",
        "account_today_total_pnl_metric_id": APP_DAILY_PNL_METRIC_ID,
        "account_today_total_pnl_source": (
            str((app_display_metrics or {}).get("source"))
            if app_today_profit
            else "longbridge_app_formula_inputs_incomplete"
        ),
        "market_day_profit_analysis": daily_profit or "无法计算",
        "market_day_profit_analysis_source": "longbridge_sdk_us_market_profit_analysis_single_market_date",
        "position_row_count": int(account_state.get("position_row_count") or 0),
        "open_order_count": int(account_state.get("open_order_count") or 0),
        "held_symbols": list(account_state.get("held_symbols") or []),
        "order_reconciliation_summary": dict(order_reconciliation.get("summary") or {}),
        "local_simulation_isolated": True,
        "order_submit_or_cancel_command_used": False,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "plain_language_result": (
            "SDK 慢速统计已刷新；资产页当日盈亏按长桥官方持仓与成交公式计算。"
            if app_today_profit
            else "SDK 慢速统计已刷新；资产页当日盈亏输入不完整。"
        ),
    }


def write_sdk_analytics_outputs(
    *,
    account_config_path: str | Path,
    generated_at: datetime,
    account_state: dict[str, Any],
    historical_orders: list[dict[str, Any]],
    historical_executions: list[dict[str, Any]],
    profit_analysis: dict[str, Any],
    daily_profit_analysis: dict[str, Any] | None = None,
    app_display_metrics: dict[str, Any] | None = None,
    history_refresh_mode: str = "sdk_history_query",
    statistics_stale: bool = False,
) -> dict[str, Any]:
    config = load_account_config(account_config_path)
    generated_at_iso = to_iso(generated_at)
    market_date = generated_at.astimezone(NEW_YORK).date().isoformat()
    augmented = dict(account_state)
    augmented["historical_orders"] = historical_orders
    augmented["historical_executions"] = historical_executions
    augmented["historical_order_end_date"] = generated_at.date().isoformat()
    ledger = read_jsonl(config.output_dir / REALTIME_EXECUTION_LEDGER_JSONL)
    reconciliation = build_order_reconciliation(config, generated_at_iso, augmented, ledger)
    reconciliation["source_mode"] = "longbridge_sdk_historical_orders_plus_realtime_submission_attribution"
    reconciliation = enrich_order_reconciliation_with_stale_cleanup(
        reconciliation,
        read_jsonl(config.output_dir / STALE_ORDER_CLEANUP_LEDGER_JSONL),
    )
    diagnostics = build_unfilled_order_diagnostics(generated_at_iso, reconciliation)
    epoch_marker = read_json(config.output_dir / "m15_sdk_formal_test_epoch.json")
    epoch_started_at = str(epoch_marker.get("test_started_at") or "")
    test_started_at_by_epoch = {
        str(epoch_marker.get(key) or ""): epoch_started_at
        for key in ("test_epoch_id", "short_test_epoch_id")
        if str(epoch_marker.get(key) or "") and epoch_started_at
    }
    fill_attribution = build_fill_attribution_v2(
        augmented,
        reconciliation,
        account_reconciliation_adjustments=read_json(
            config.output_dir / "m15_account_reconciliation_adjustments.json"
        ),
        commission_per_order_side=config.commission_per_order_side,
        regulatory_fee_per_sell_order=config.regulatory_fee_per_sell_order,
        execution_rows_for_fault_days=ledger,
        fault_day_overrides=config.fault_day_registry_overrides,
        test_started_at_by_epoch=test_started_at_by_epoch,
    )
    pnl = build_sdk_pnl_reconciliation(
        generated_at_iso,
        account_state,
        profit_analysis,
        config.historical_order_start_date,
        market_date,
        daily_profit_analysis,
        app_display_metrics,
    )
    summary = build_sdk_account_summary(
        generated_at_iso,
        account_state,
        reconciliation,
        daily_profit_analysis,
        app_display_metrics,
    )
    summary["history_refresh_mode"] = history_refresh_mode
    summary["statistics_stale"] = statistics_stale
    summary["fill_attribution_summary"] = fill_attribution.get("summary", {})
    pnl["statistics_stale"] = statistics_stale
    if statistics_stale:
        summary["plain_language_result"] = (
            "SDK 交易核心正常；慢速历史或收益统计暂未刷新，"
            f"statistics_stale=true，原因={history_refresh_mode}。"
        )
        pnl["source_status"] = {
            **(pnl.get("source_status") or {}),
            "status": "statistics_stale",
            "statistics_stale": True,
        }
        if isinstance(pnl.get("market_day_profit_analysis"), dict):
            pnl["market_day_profit_analysis"]["status"] = "statistics_stale"
    reconciliation["history_refresh_mode"] = history_refresh_mode
    reconciliation["statistics_stale"] = statistics_stale
    trusted_history = {
        "schema_version": "m15.longbridge-trusted-order-history.sdk.v1",
        "generated_at": generated_at_iso,
        "history_refresh_mode": history_refresh_mode,
        "statistics_stale": statistics_stale,
        "historical_orders": historical_orders,
        "historical_executions": historical_executions,
    }
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / SUMMARY_JSON, summary)
    write_json(config.output_dir / PNL_RECONCILIATION_JSON, pnl)
    write_json(config.output_dir / ORDER_RECONCILIATION_JSON, reconciliation)
    write_json(config.output_dir / UNFILLED_ORDER_DIAGNOSTICS_JSON, diagnostics)
    write_json(config.output_dir / FILL_ATTRIBUTION_JSON, fill_attribution)
    write_json(config.output_dir / TRUSTED_ORDER_HISTORY_JSON, trusted_history)
    return {
        "generated_at": generated_at_iso,
        "historical_order_count": len(historical_orders),
        "historical_execution_count": len(historical_executions),
        "filled_order_count": int(reconciliation.get("summary", {}).get("filled_order_count", 0)),
        "fill_attribution_anomaly_count": int(fill_attribution.get("summary", {}).get("anomaly_count", 0)),
        "paper_account_verified": bool(account_state.get("paper_account_verified")),
        "statistics_stale": statistics_stale,
    }


def run_sdk_analytics(
    sdk_runtime_config_path: str | Path,
    account_config_path: str | Path,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    import longbridge.openapi as sdk

    generated_at = generated_at or datetime.now(UTC)
    runtime_config = load_sdk_config(sdk_runtime_config_path)
    account_config = load_account_config(account_config_path)
    require_live_sdk_runtime(runtime_config, generated_at)
    account_state = read_json(account_config.account_state_path)
    require_fresh_paper_account(account_state, generated_at)
    oauth = sdk.OAuthBuilder(read_client_id(runtime_config)).build(lambda _url: None)
    def build_trade() -> Any:
        return sdk.TradeContext(sdk_config_from_oauth(sdk, oauth, runtime_config.trade_region))

    def build_portfolio() -> Any:
        return sdk.PortfolioContext(sdk_config_from_oauth(sdk, oauth, runtime_config.trade_region))

    trade = build_trade()
    portfolio = build_portfolio()
    start_at = datetime.fromisoformat(account_config.historical_order_start_date).replace(tzinfo=UTC)
    trusted_history = read_json(account_config.output_dir / TRUSTED_ORDER_HISTORY_JSON)
    cached_orders = [dict(row) for row in trusted_history.get("historical_orders", []) if isinstance(row, dict)]
    cached_executions = [dict(row) for row in trusted_history.get("historical_executions", []) if isinstance(row, dict)]
    orders, executions, trade, history_refresh_mode = refresh_order_and_execution_history(
        trade,
        build_trade,
        start_at=start_at,
        generated_at=generated_at,
        cached_orders=cached_orders,
        cached_executions=cached_executions,
        account_state=account_state,
    )
    market_date, cumulative_end_date = market_profit_query_dates(generated_at)
    stale_reasons: list[str] = []
    try:
        profit_response, portfolio = read_with_timeout_recovery(
            portfolio,
            build_portfolio,
            lambda context: context.profit_analysis_by_market(
                page=1,
                size=100,
                market="US",
                start=start_at.date().isoformat(),
                end=cumulative_end_date,
            ),
        )
        profit = sdk_plain(profit_response)
    except Exception as exc:
        if not is_sdk_timeout_error(exc):
            raise
        profit = {}
        stale_reasons.append("cumulative_profit_analysis_timeout")
    try:
        daily_profit_response, portfolio = read_with_timeout_recovery(
            portfolio,
            build_portfolio,
            lambda context: context.profit_analysis_by_market(
                page=1,
                size=100,
                market="US",
                start=market_date,
                end=market_date,
            ),
        )
        daily_profit = sdk_plain(daily_profit_response)
    except Exception as exc:
        if not is_sdk_timeout_error(exc):
            raise
        daily_profit = {}
        stale_reasons.append("daily_profit_analysis_timeout")
    app_window_start = app_intraday_window_start(generated_at)
    daily_execution_rows = [
        row
        for row in executions
        if str(row.get("trade_done_at") or "") >= to_iso(app_window_start)
    ]
    daily_order_ids = {str(row.get("order_id") or "") for row in daily_execution_rows}
    daily_orders = [row for row in orders if str(row.get("order_id") or "") in daily_order_ids]
    # The live runtime owns the only quote connection and publishes a bounded
    # atomic snapshot for this slow App-metric reconciliation path.
    quote_rows = load_runtime_quote_rows(runtime_config, generated_at)
    app_display_metrics = build_app_display_metrics(
        generated_at,
        account_state,
        daily_orders,
        daily_execution_rows,
        quote_rows,
    )
    if stale_reasons:
        history_refresh_mode += "_statistics_stale_" + "_".join(stale_reasons)
    statistics_stale = "statistics_stale" in history_refresh_mode
    return write_sdk_analytics_outputs(
        account_config_path=account_config_path,
        generated_at=generated_at,
        account_state=account_state,
        historical_orders=[row for row in orders if row],
        historical_executions=[row for row in executions if row],
        profit_analysis=profit if isinstance(profit, dict) else {},
        daily_profit_analysis=daily_profit if isinstance(daily_profit, dict) else {},
        app_display_metrics=app_display_metrics,
        history_refresh_mode=history_refresh_mode,
        statistics_stale=statistics_stale,
    )
