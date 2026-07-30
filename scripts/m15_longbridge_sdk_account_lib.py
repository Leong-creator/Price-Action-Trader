#!/usr/bin/env python3
"""SDK-only account snapshots for the M15 paper runtime.

This module deliberately has no CLI imports.  Its normalized payload retains
the fields consumed by the existing execution and position-management code,
while the live source is the persistent Longbridge SDK client.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from scripts.m15_longbridge_realtime_execution_lib import to_iso
from scripts.m15_longbridge_sdk_account_worker_lib import AccountWorkerConfig, SpawnAccountSnapshotWorker


def sdk_plain(value: Any) -> Any:
    """Convert PyO3 SDK responses to stable JSON-compatible data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return to_iso(value.astimezone(UTC))
    if isinstance(value, (list, tuple)):
        return [sdk_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): sdk_plain(item) for key, item in value.items()}
    result: dict[str, Any] = {}
    for key in (
        "account_type", "account_channel", "currency", "cash", "cash_infos", "available_cash", "withdraw_cash",
        "frozen_cash", "settling_cash", "total_cash", "net_assets", "buying_power", "buy_power", "channels", "positions", "symbol",
        "name", "market", "quantity", "available_quantity", "available", "cost_price", "side",
        "status", "order_id", "submitted_quantity", "executed_quantity", "submitted_price", "price",
        "executed_price", "submitted_at", "updated_at", "executed_at", "trade_done_at", "trade_id", "remark", "order_type",
        "last_done", "last_price", "market_price", "current_price", "close", "pre_close",
        "sum_profit", "sum_profit_rate", "current_total_asset", "profits", "items", "sublist", "profit", "stock_items",
    ):
        if hasattr(value, key):
            result[key] = sdk_plain(getattr(value, key))
    return result or str(value)


def rows(value: Any) -> list[dict[str, Any]]:
    plain = sdk_plain(value)
    if isinstance(plain, list):
        return [item for item in plain if isinstance(item, dict)]
    if isinstance(plain, dict):
        for key in ("items", "list", "orders", "executions", "positions", "cash_infos"):
            items = plain.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return [plain]
    return []


def decimal_text(value: Any) -> str:
    try:
        return format(Decimal(str(value or "0")), "f")
    except Exception:
        return "0"


def symbol_text(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    return symbol if "." in symbol or not symbol else f"{symbol}.US"


def order_status_token(value: Any) -> str:
    return str(value or "").strip().split(".")[-1].lower().replace("_", "")


def terminal_order_status(value: Any) -> bool:
    return order_status_token(value) in {"filled", "cancelled", "canceled", "rejected", "expired"}


class SdkTradeRequestGate:
    """Serialize SDK trade calls and respect Longbridge's 30/30s limit."""

    def __init__(self, *, max_calls: int = 30, window_seconds: float = 30.0) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._lock = threading.RLock()
        self._calls: deque[float] = deque()

    def call(self, callback: Callable[[], Any]) -> Any:
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= self.window_seconds:
                self._calls.popleft()
            if len(self._calls) >= self.max_calls:
                wait_for = self.window_seconds - (now - self._calls[0])
                if wait_for > 0:
                    time.sleep(wait_for)
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.window_seconds:
                    self._calls.popleft()
            self._calls.append(time.monotonic())
            return callback()


class SdkAccountStateProvider:
    """Read the paper account through SDK contexts only."""

    def __init__(
        self,
        trade_context: Any,
        portfolio_context: Any,
        *,
        account_channel: str = "",
        request_gate: SdkTradeRequestGate | None = None,
        include_portfolio_analytics: bool = True,
    ) -> None:
        self.trade_context = trade_context
        self.portfolio_context = portfolio_context
        self.account_channel = account_channel
        self.request_gate = request_gate or SdkTradeRequestGate()
        self.include_portfolio_analytics = include_portfolio_analytics

    def refresh(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        errors: list[str] = []
        balances: list[dict[str, Any]] = []
        positions: list[dict[str, Any]] = []
        orders: list[dict[str, Any]] = []
        executions: list[dict[str, Any]] = []
        account_channel_verified_from_sdk = False
        pnl: Any = {}
        try:
            balances = [sdk_plain(item) for item in self.request_gate.call(lambda: self.trade_context.account_balance())]
        except Exception as exc:
            errors.append(f"sdk_account_balance_failed:{type(exc).__name__}:{exc}")
        try:
            position_response = sdk_plain(self.request_gate.call(lambda: self.trade_context.stock_positions()))
            channels = position_response.get("channels", []) if isinstance(position_response, dict) else []
            positions = [item for channel in channels if isinstance(channel, dict) for item in channel.get("positions", []) if isinstance(item, dict)]
            if not positions:
                positions = rows(position_response)
            account_channel = next((str(channel.get("account_channel") or "") for channel in channels if isinstance(channel, dict) and channel.get("account_channel")), "")
            if account_channel:
                self.account_channel = account_channel
                account_channel_verified_from_sdk = True
        except Exception as exc:
            errors.append(f"sdk_stock_positions_failed:{type(exc).__name__}:{exc}")
        try:
            orders = [row for row in rows(self.request_gate.call(lambda: self.trade_context.today_orders())) if symbol_text(row).endswith(".US")]
        except Exception as exc:
            errors.append(f"sdk_today_orders_failed:{type(exc).__name__}:{exc}")
        try:
            executions = rows(self.request_gate.call(lambda: self.trade_context.today_executions()))
        except Exception as exc:
            errors.append(f"sdk_today_executions_failed:{type(exc).__name__}:{exc}")
        if self.include_portfolio_analytics:
            try:
                # Portfolio analytics uses a separate SDK context and must never
                # hold the trade request gate needed by a time-sensitive order.
                pnl = sdk_plain(self.portfolio_context.profit_analysis_by_market(market="US"))
            except Exception as exc:
                errors.append(f"sdk_profit_analysis_failed:{type(exc).__name__}:{exc}")

        currency_cash: dict[str, dict[str, str]] = {}
        for balance in balances:
            if not isinstance(balance, dict):
                continue
            currency = str(balance.get("currency") or "USD").upper()
            cash_rows = balance.get("cash_infos") if isinstance(balance.get("cash_infos"), list) else [balance]
            for cash_info in cash_rows:
                if not isinstance(cash_info, dict):
                    continue
                currency = str(cash_info.get("currency") or currency).upper()
                currency_cash[currency] = {
                    "available_cash": decimal_text(cash_info.get("available_cash") or cash_info.get("cash")),
                    "total_cash": decimal_text(cash_info.get("total_cash") or cash_info.get("cash")),
                    "settling_cash": decimal_text(cash_info.get("settling_cash")),
                    "frozen_cash": decimal_text(cash_info.get("frozen_cash")),
                    "withdraw_cash": decimal_text(cash_info.get("withdraw_cash")),
                }
        normalized_positions = [
            {
                **row,
                "symbol": symbol_text(row),
                "quantity": decimal_text(row.get("quantity")),
                "available": decimal_text(row.get("available") or row.get("available_quantity")),
                "cost_price": decimal_text(row.get("cost_price")),
            }
            for row in positions
            if symbol_text(row)
        ]
        normalized_orders = [{**row, "symbol": symbol_text(row)} for row in orders if symbol_text(row)]
        critical_errors = [
            item
            for item in errors
            if item.startswith(("sdk_account_balance", "sdk_stock_positions", "sdk_today_orders"))
        ]
        analytics_errors = [item for item in errors if item not in critical_errors]
        usd = currency_cash.get("USD", {})
        portfolio_total_asset = first_value(pnl, "current_total_asset", "ending_asset_value", default="")
        balance_total_asset = first_value(balances, "net_assets", default="")
        if decimal_text(portfolio_total_asset) != "0" or not balance_total_asset:
            total_asset = decimal_text(portfolio_total_asset)
            total_asset_source = "longbridge_sdk_portfolio_profit_analysis_by_market"
            total_asset_currency = "USD" if portfolio_total_asset else ""
        else:
            total_asset = decimal_text(balance_total_asset)
            total_asset_source = "longbridge_sdk_account_balance.net_assets"
            total_asset_currency = str(first_value(balances, "currency", default=""))
        buying_power = decimal_text(first_value(balances, "buy_power", "buying_power", default="0"))
        state = {
            "schema_version": "m15.longbridge-sdk-account-state.v1",
            "stage": "M15.longbridge_sdk_account_state",
            "generated_at": to_iso(now),
            "source": (
                "longbridge_sdk_account_and_portfolio"
                if self.include_portfolio_analytics
                else "longbridge_sdk_trade_account_fast_snapshot"
            ),
            "account_channel": self.account_channel,
            "account_channel_verified_from_sdk": account_channel_verified_from_sdk,
            "paper_account_detected": account_channel_verified_from_sdk and self.account_channel == "lb_papertrading",
            "paper_account_verified": (
                account_channel_verified_from_sdk
                and self.account_channel == "lb_papertrading"
                and not critical_errors
            ),
            "live_execution": False,
            "real_money_actions": False,
            "local_simulation_isolated": True,
            "assets_ok": not any(item.startswith("sdk_account_balance") for item in errors),
            "positions_ok": not any(item.startswith("sdk_stock_positions") for item in errors),
            "orders_ok": not any(item.startswith("sdk_today_orders") for item in errors),
            "executions_ok": not any(item.startswith("sdk_today_executions") for item in errors),
            "portfolio_ok": (
                not any(item.startswith("sdk_profit_analysis") for item in errors)
                if self.include_portfolio_analytics
                else None
            ),
            "portfolio_deferred_to_slow_path": not self.include_portfolio_analytics,
            "errors": errors,
            "critical_errors": critical_errors,
            "analytics_errors": analytics_errors,
            "currency_cash": currency_cash,
            "cash": usd.get("available_cash", "0"),
            "usd_available_cash": usd.get("available_cash", "0"),
            "usd_total_cash": usd.get("total_cash", "0"),
            "usd_settling_cash": usd.get("settling_cash", "0"),
            "usd_frozen_cash": usd.get("frozen_cash", "0"),
            "account_total_equity_estimate": total_asset,
            "account_total_equity_source": total_asset_source,
            "account_total_equity_currency": total_asset_currency,
            "account_buying_power": buying_power,
            "account_buying_power_currency": str(first_value(balances, "currency", default="")),
            "positions": normalized_positions,
            "held_symbols": [symbol_text(row).replace(".US", "") for row in normalized_positions],
            "position_row_count": len(normalized_positions),
            "orders": normalized_orders,
            "open_orders": [row for row in normalized_orders if not terminal_order_status(row.get("status"))],
            "order_row_count": len(normalized_orders),
            "executions": executions,
            "execution_row_count": len(executions),
            "longbridge_sdk_profit_analysis": pnl,
            "longbridge_app_display_today_pnl": "等待长桥字段对齐",
        }
        state["open_order_count"] = len(state["open_orders"])
        return state


class SdkAccountCoordinator:
    """Own the latest SDK account snapshot without blocking quote callbacks."""

    def __init__(
        self,
        provider: SdkAccountStateProvider,
        output_path: Path,
        *,
        interval_seconds: int = 15,
        provider_factory: Callable[[], SdkAccountStateProvider] | None = None,
        provider_rebuild_cooldown_seconds: int = 60,
    ) -> None:
        self.provider = provider
        self.output_path = output_path
        self.interval_seconds = interval_seconds
        self.provider_factory = provider_factory
        self.provider_rebuild_cooldown_seconds = provider_rebuild_cooldown_seconds
        self._last_provider_rebuild = float("-inf")
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._snapshot: dict[str, Any] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="m15-sdk-account-snapshot", daemon=True)

    def start(self) -> None:
        self.refresh()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def refresh(self) -> dict[str, Any]:
        with self._refresh_lock:
            candidate = self.provider.refresh()
            now_monotonic = time.monotonic()
            if (
                candidate.get("critical_errors")
                and self.provider_factory is not None
                and now_monotonic - self._last_provider_rebuild >= self.provider_rebuild_cooldown_seconds
            ):
                self._last_provider_rebuild = now_monotonic
                failed_errors = list(candidate.get("critical_errors") or [])
                self.provider = self.provider_factory()
                candidate = self.provider.refresh()
                candidate["provider_rebuild_attempted"] = True
                candidate["provider_rebuild_trigger_errors"] = failed_errors
        with self._lock:
            previous = self._snapshot
            preserve_last_good = (
                bool(previous)
                and previous.get("paper_account_verified") is True
                and previous.get("assets_ok") is True
                and previous.get("positions_ok") is True
                and previous.get("orders_ok") is True
                and bool(candidate.get("critical_errors"))
                and str(candidate.get("account_channel") or "")
                == str(previous.get("account_channel") or "")
            )
            if preserve_last_good:
                # Keep the original generated_at so the executor's 45-second
                # freshness gate still stops entries if SDK failures persist.
                snapshot = json.loads(json.dumps(previous, ensure_ascii=False))
                snapshot["last_refresh_status"] = "critical_error_preserved_last_good"
                snapshot["last_failed_refresh_at"] = candidate.get("generated_at")
                snapshot["last_refresh_errors"] = list(candidate.get("critical_errors") or [])
            else:
                snapshot = candidate
                snapshot["last_refresh_status"] = "healthy" if not candidate.get("critical_errors") else "critical_error"
                snapshot.pop("last_failed_refresh_at", None)
                snapshot.pop("last_refresh_errors", None)
            pending = [row for row in previous.get("open_orders", []) if row.get("sdk_pending_confirmation")]
            known_ids = {str(row.get("order_id") or "") for row in snapshot.get("orders", [])}
            snapshot["open_orders"].extend(row for row in pending if str(row.get("order_id") or "") not in known_ids)
            snapshot["open_order_count"] = len(snapshot["open_orders"])
            self._snapshot = snapshot
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output_path.with_name(f".{self.output_path.name}.{id(self)}.tmp")
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.output_path)
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._snapshot, ensure_ascii=False))

    def note_submission(self, order_payload: dict[str, Any], response: dict[str, Any]) -> None:
        order_id = str(response.get("order_id") or "")
        if not order_id:
            return
        with self._lock:
            if not self._snapshot:
                return
            open_orders = self._snapshot.setdefault("open_orders", [])
            if not any(str(row.get("order_id") or "") == order_id for row in open_orders):
                open_orders.append({
                    "order_id": order_id,
                    "symbol": str(order_payload.get("symbol") or ""),
                    "side": str(order_payload.get("side") or ""),
                    "status": "Submitted",
                    "sdk_pending_confirmation": True,
                })
                self._snapshot["open_order_count"] = len(open_orders)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.refresh()
            except Exception:
                # The previous snapshot remains available. The executor applies
                # the configured maximum age before considering a new entry.
                continue


class SdkAccountProcessCoordinator:
    """Publish account snapshots from a killable spawned SDK worker."""

    def __init__(
        self,
        provider_factory: Callable[[], SdkAccountStateProvider],
        output_path: Path,
        *,
        interval_seconds: int = 15,
        refresh_deadline_seconds: float = 8.0,
        circuit_retry_cooldown_seconds: float = 15.0,
    ) -> None:
        self.output_path = output_path
        self.interval_seconds = interval_seconds
        self.refresh_deadline_seconds = refresh_deadline_seconds
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._snapshot: dict[str, Any] = {}
        self._pending_open_orders: dict[str, dict[str, Any]] = {}
        self._stop = threading.Event()
        self._worker = SpawnAccountSnapshotWorker(
            provider_factory,
            config=AccountWorkerConfig(
                refresh_total_deadline_seconds=refresh_deadline_seconds,
                startup_total_deadline_seconds=max(30.0, refresh_deadline_seconds),
                circuit_breaker_consecutive_timeouts=2,
                circuit_recovery_consecutive_successes=2,
                circuit_retry_cooldown_seconds=circuit_retry_cooldown_seconds,
            ),
        )
        self._thread = threading.Thread(target=self._run, name="m15-sdk-account-process-coordinator", daemon=True)

    def start(self) -> None:
        self._worker.start()
        self.refresh()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self.refresh_deadline_seconds + 1.0)
        self._worker.stop()

    def refresh(self) -> dict[str, Any]:
        with self._refresh_lock:
            candidate = self._worker.refresh(total_deadline_seconds=self.refresh_deadline_seconds)
        with self._lock:
            known_ids = {
                str(row.get("order_id") or "")
                for row in candidate.get("orders", [])
                if isinstance(row, dict)
            }
            for order_id in tuple(self._pending_open_orders):
                if order_id in known_ids:
                    self._pending_open_orders.pop(order_id, None)
            open_orders = [row for row in candidate.get("open_orders", []) if isinstance(row, dict)]
            open_ids = {str(row.get("order_id") or "") for row in open_orders}
            open_orders.extend(
                row
                for order_id, row in self._pending_open_orders.items()
                if order_id not in open_ids
            )
            candidate["open_orders"] = open_orders
            candidate["open_order_count"] = len(open_orders)
            self._snapshot = json.loads(json.dumps(candidate, ensure_ascii=False))
            snapshot = json.loads(json.dumps(self._snapshot, ensure_ascii=False))
        self._write_snapshot(snapshot)
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._snapshot, ensure_ascii=False))

    def note_submission(self, order_payload: dict[str, Any], response: dict[str, Any]) -> None:
        order_id = str(response.get("order_id") or "")
        if not order_id:
            return
        pending = {
            "order_id": order_id,
            "symbol": str(order_payload.get("symbol") or ""),
            "side": str(order_payload.get("side") or ""),
            "status": "Submitted",
            "sdk_pending_confirmation": True,
        }
        with self._lock:
            self._pending_open_orders[order_id] = pending
            if self._snapshot:
                open_orders = self._snapshot.setdefault("open_orders", [])
                if not any(str(row.get("order_id") or "") == order_id for row in open_orders):
                    open_orders.append(dict(pending))
                self._snapshot["open_order_count"] = len(open_orders)

    def _write_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output_path.with_name(f".{self.output_path.name}.{id(self)}.tmp")
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.output_path)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.refresh()
            except Exception:
                continue


def first_value(value: Any, *keys: str, default: Any = "") -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value and value[key] not in (None, ""):
                return value[key]
        for nested in value.values():
            found = first_value(nested, *keys, default=None)
            if found not in (None, ""):
                return found
    if isinstance(value, list):
        for nested in value:
            found = first_value(nested, *keys, default=None)
            if found not in (None, ""):
                return found
    return default
