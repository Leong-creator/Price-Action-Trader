#!/usr/bin/env python3
from __future__ import annotations

import os
import queue
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.m15_longbridge_sdk_runtime_lib import (
    FiveMinuteBarBuilder,
    configured_symbols,
    configured_trading_symbols,
    daily_candlestick_event_rows,
    floor_bar_open,
    load_config,
    load_valid_daily_context_cache,
    required_daily_context_date,
    NEW_YORK,
    read_client_id,
    sdk_config_from_oauth,
    sdk_object_to_dict,
    to_iso,
)


CALLBACK_QUEUE_MAXSIZE = 250_000
CALLBACK_DRAIN_BATCH = 10_000
QUOTE_STATE_FLUSH_SECONDS = 0.25


class DailyContextRefresh:
    """Use the same context off-session without blocking callback draining."""

    def __init__(self, config: Any, symbols: list[str], completed_date: str) -> None:
        self.config = config
        self.symbols = symbols
        self.completed_date = completed_date
        self.target_date = ""
        self.rows: list[dict[str, Any]] = []
        self.index = 0
        self.deadline = 0.0
        self.result: queue.Queue[Any] = queue.Queue(maxsize=1)

    def _fetch(self, quote: Any, sdk: Any, now: datetime) -> None:
        try:
            rows: list[dict[str, Any]] = []
            for symbol in self.symbols:
                if time.monotonic() >= self.deadline:
                    raise RuntimeError("official_sdk_daily_refresh_deadline_exceeded")
                candles = quote.candlesticks(symbol, sdk.Period.Day, self.config.daily_context_bars,
                                           sdk.AdjustType.NoAdjust, sdk.TradeSessions.Intraday)
                current = daily_candlestick_event_rows(symbol, candles, now)
                dates = [datetime.fromisoformat(row["event_time"].replace("Z", "+00:00")).astimezone(NEW_YORK).date().isoformat()
                         for row in current]
                if len(current) != self.config.daily_context_bars or not dates or max(dates) != self.target_date:
                    raise RuntimeError(f"official_sdk_daily_refresh_incomplete:{symbol}:{self.target_date}")
                rows.extend(current)
            self.result.put_nowait(rows)
        except BaseException as exc:
            self.result.put_nowait(exc)

    def step(self, quote: Any, sdk: Any, now: datetime) -> list[dict[str, Any]] | None:
        required = required_daily_context_date(now, self.config.market_holidays)
        local = now.astimezone(NEW_YORK)
        regular = (local.weekday() < 5 and local.date().isoformat() not in self.config.market_holidays
                   and (9, 30) <= (local.hour, local.minute) < (16, 0))
        if required == self.completed_date and not self.target_date:
            return None
        if regular:
            raise RuntimeError("official_sdk_daily_context_stale_at_market_open")
        if not self.target_date:
            self.target_date = required
            self.deadline = time.monotonic() + self.config.daily_context_deadline_seconds
            threading.Thread(target=self._fetch, args=(quote, sdk, now), daemon=True,
                             name="official-sdk-daily-refresh").start()
        if time.monotonic() >= self.deadline:
            raise RuntimeError("official_sdk_daily_refresh_deadline_exceeded")
        try:
            completed = self.result.get_nowait()
        except queue.Empty:
            return None
        if isinstance(completed, BaseException):
            raise completed
        self.completed_date = self.target_date
        self.target_date, self.rows, self.index = "", [], 0
        return completed


def _emit(queue_out: Any, payload: dict[str, Any], *, critical: bool = False) -> bool:
    try:
        if critical:
            queue_out.put(payload, timeout=10)
        else:
            queue_out.put_nowait(payload)
        return True
    except queue.Full:
        return False


def _subscription_symbols(rows: Any, required_sub_types: tuple[Any, ...] = ()) -> set[str]:
    result: set[str] = set()
    for row in rows or []:
        value = row.get("symbol") if isinstance(row, dict) else getattr(row, "symbol", "")
        symbol = str(value or "").upper()
        sub_types = row.get("sub_types", []) if isinstance(row, dict) else getattr(row, "sub_types", [])
        if symbol and set(map(str, required_sub_types)) <= set(map(str, sub_types)):
            result.add(symbol)
    return result


def _resources() -> dict[str, int]:
    try:
        file_descriptors = len(list(Path("/proc/self/fd").iterdir()))
    except OSError:
        file_descriptors = -1
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        memory_kib = int(
            next(
                line.split()[1]
                for line in status.splitlines()
                if line.startswith("VmRSS:")
            )
        )
    except (OSError, StopIteration, ValueError):
        memory_kib = -1
    return {
        "thread_count": threading.active_count(),
        "file_descriptor_count": file_descriptors,
        "resident_memory_kib": memory_kib,
    }


def official_sdk_quote_worker(
    config_path: str,
    queue_out: Any,
    stop_event: Any,
    position_monitoring_symbols: tuple[str, ...] = (),
) -> None:
    """Own exactly one official SDK async quote context for all market data."""
    config = load_config(config_path)
    quote = None
    try:
        os.environ["LONGBRIDGE_PRINT_QUOTE_PACKAGES"] = "false"
        import longbridge.openapi as sdk

        oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
        from scripts.m15_official_async_quote_lib import OfficialAsyncQuoteBridge

        quote = OfficialAsyncQuoteBridge(
            sdk_config_from_oauth(sdk, oauth, config.quote_region),
            sdk=sdk,
            init_timeout=min(30, config.subscription_deadline_seconds),
            request_timeout=config.subscription_deadline_seconds,
        )
        callback_events: queue.Queue[tuple[str, str, dict[str, Any], datetime]] = (
            queue.Queue(maxsize=CALLBACK_QUEUE_MAXSIZE)
        )
        callback_overflow = threading.Event()
        reference_activity_lock = threading.Lock()
        latest_reference_activity: dict[str, dict[str, str]] = {}

        def enqueue(kind: str, symbol: str, event: Any) -> None:
            normalized_symbol = str(symbol).upper()
            received_at = datetime.now(UTC)
            if normalized_symbol in {"SPY.US", "QQQ.US"}:
                with reference_activity_lock:
                    latest_reference_activity[normalized_symbol] = {
                        "kind": "market_activity",
                        "symbol": normalized_symbol,
                        "received_at": to_iso(received_at),
                        "source_mode": f"official_sdk_raw_{kind}_callback",
                    }
            try:
                callback_events.put_nowait(
                    (
                        kind,
                        normalized_symbol,
                        sdk_object_to_dict(event),
                        received_at,
                    )
                )
            except queue.Full:
                callback_overflow.set()

        # The SDK requires handlers to be registered before subscription. The
        # callbacks do no strategy work, file I/O, account access, or orders.
        quote.set_on_quote(lambda symbol, event: enqueue("quote", symbol, event))
        quote.set_on_trades(lambda symbol, event: enqueue("trade", symbol, event))

        base_targets = list(configured_symbols(config))
        trading_targets = set(configured_trading_symbols(config))
        monitoring_targets = sorted(
            {
                str(symbol).upper()
                for symbol in position_monitoring_symbols
                if str(symbol).upper() not in set(base_targets)
            }
        )
        targets = list(dict.fromkeys(base_targets + monitoring_targets))

        initial_daily_required = required_daily_context_date(datetime.now(UTC), config.market_holidays)
        daily_rows = load_valid_daily_context_cache(
            config.daily_context_path,
            config,
            datetime.now(UTC),
        )
        daily_failures: list[str] = []
        daily_deadline_exhausted: list[str] = []
        daily_source_mode = "official_sdk_daily_context_cache"
        if daily_rows:
            _emit(
                queue_out,
                {
                    "kind": "daily_context_progress",
                    "completed": len(base_targets),
                    "processed": len(base_targets),
                    "total": len(base_targets),
                },
            )
        else:
            daily_source_mode = "official_sdk_daily_context"
            daily_deadline = time.monotonic() + config.daily_context_deadline_seconds
            for index, symbol in enumerate(base_targets, start=1):
                if time.monotonic() >= daily_deadline:
                    daily_deadline_exhausted = list(base_targets[index - 1 :])
                    break
                try:
                    candles = quote.candlesticks(
                        symbol,
                        sdk.Period.Day,
                        config.daily_context_bars,
                        sdk.AdjustType.NoAdjust,
                        sdk.TradeSessions.Intraday,
                    )
                    rows = daily_candlestick_event_rows(
                        symbol, candles, datetime.now(UTC)
                    )
                except Exception:
                    rows = []
                if len(rows) != config.daily_context_bars:
                    daily_failures.append(symbol)
                else:
                    daily_rows.extend(rows)
                _emit(
                    queue_out,
                    {
                        "kind": "daily_context_progress",
                        "completed": index - len(daily_failures),
                        "processed": index,
                        "total": len(base_targets),
                    },
                )
        if daily_deadline_exhausted:
            raise RuntimeError(
                "official_sdk_daily_context_deadline_exceeded:"
                + ",".join(daily_deadline_exhausted)
            )
        if daily_failures:
            raise RuntimeError(
                "official_sdk_daily_context_incomplete:"
                + ",".join(daily_failures)
            )
        if not _emit(
            queue_out,
            {
                "kind": "daily_context",
                "rows": daily_rows,
                "failures": [],
                "source_mode": daily_source_mode,
            },
            critical=True,
        ):
            raise RuntimeError("official_sdk_daily_context_delivery_failed")

        subscribe_batch_size = config.sdk_subscribe_batch_size
        for offset in range(0, len(targets), subscribe_batch_size):
            batch = targets[offset : offset + subscribe_batch_size]
            quote.subscribe(batch, [sdk.SubType.Quote, sdk.SubType.Trade])
            _emit(
                queue_out,
                {
                    "kind": "subscription_progress",
                    "completed": min(offset + len(batch), len(targets)),
                    "total": len(targets),
                },
            )

        subscribed = _subscription_symbols(quote.subscriptions(), (sdk.SubType.Quote, sdk.SubType.Trade))
        missing_subscriptions = sorted(set(targets) - subscribed)
        if missing_subscriptions:
            raise RuntimeError(
                "official_sdk_subscription_incomplete:"
                + ",".join(missing_subscriptions)
            )

        initial_snapshot = list(quote.quote(targets))
        initial_snapshot_symbols: set[str] = set()
        builder = FiveMinuteBarBuilder(
            config.bar_minutes,
            complete_bar_open_not_before=(
                floor_bar_open(datetime.now(UTC), config.bar_minutes)
                + timedelta(minutes=config.bar_minutes)
            ),
            boundary_batch_mode=True,
            push_source_mode="official_sdk_push",
            no_trade_source_mode="official_sdk_no_trade_carry_forward",
            event_id_prefix="official-sdk-5m",
            market_holidays=config.market_holidays,
            boundary_settle_seconds=config.maximum_source_delivery_age_ms / 1000,
        )
        initial_quote_rows: list[dict[str, Any]] = []
        snapshot_received_at = datetime.now(UTC)
        for item in initial_snapshot:
            payload = sdk_object_to_dict(item)
            symbol = str(payload.get("symbol") or "").upper()
            if not symbol:
                continue
            initial_snapshot_symbols.add(symbol)
            builder.seed_quote(symbol, payload, received_at=snapshot_received_at)
            initial_quote_rows.append(
                {
                    "symbol": symbol,
                    "payload": payload,
                    "received_at": to_iso(snapshot_received_at),
                    "source_mode": "official_sdk_initial_snapshot",
                }
            )
        missing_snapshots = sorted(set(targets) - initial_snapshot_symbols)
        if missing_snapshots:
            raise RuntimeError(
                "official_sdk_initial_snapshot_incomplete:"
                + ",".join(missing_snapshots)
            )
        if not _emit(
            queue_out,
            {"kind": "quote_state_batch", "rows": initial_quote_rows},
            critical=True,
        ):
            raise RuntimeError("official_sdk_initial_snapshot_delivery_failed")
        if not _emit(
            queue_out,
            {
                "kind": "ready",
                "sdk_quote_context_api": "AsyncQuoteContext",
                "market_data_mode": "official_sdk_subscription",
                "market_data_transport": "official_sdk_persistent_websocket",
                "market_data_symbols": sorted(base_targets),
                "subscribed_symbols": sorted(base_targets),
                "subscription_failed_symbols": [],
                "trading_subscription_failed_symbols": [],
                "position_monitoring_symbols": monitoring_targets,
                "position_monitoring_subscribed_symbols": monitoring_targets,
                "position_monitoring_failed_symbols": [],
                "daily_context_failed_symbols": [],
                "partial_bar_suppressed_until": to_iso(
                    builder.complete_bar_open_not_before.astimezone(UTC)
                ),
                "subscription_target_count": len(targets),
                "initial_snapshot_coverage": (
                    f"{len(initial_snapshot_symbols & set(base_targets))}/{len(base_targets)}"
                ),
                "position_monitoring_initial_snapshot_coverage": (
                    f"{len(initial_snapshot_symbols & set(monitoring_targets))}/"
                    f"{len(monitoring_targets)}"
                ),
            },
            critical=True,
        ):
            raise RuntimeError("official_sdk_ready_delivery_failed")

        pending_quotes: dict[str, dict[str, Any]] = {}
        # Use the requirement at the actual fetch, not the later subscribe time:
        # initialization can straddle the 16:10 completed-session transition.
        daily_refresh = DailyContextRefresh(config, base_targets, initial_daily_required)
        last_quote_flush = 0.0
        last_heartbeat = 0.0
        last_reference_activity: dict[str, float] = {}
        raw_event_count = 0
        while not stop_event.is_set():
            quote.check_health()
            if callback_overflow.is_set():
                raise RuntimeError("official_sdk_callback_queue_overflow")
            processed = 0
            while processed < CALLBACK_DRAIN_BATCH:
                try:
                    kind, symbol, payload, received_at = callback_events.get_nowait()
                except queue.Empty:
                    break
                raw_event_count += 1
                processed += 1
                if kind == "quote":
                    builder.seed_quote(symbol, payload, received_at=received_at)
                    pending_quotes[symbol] = {
                        "symbol": symbol,
                        "payload": payload,
                        "received_at": to_iso(received_at),
                        "source_mode": "official_sdk_push",
                    }
                    continue
                if symbol in {"SPY.US", "QQQ.US"}:
                    now_monotonic = time.monotonic()
                    if now_monotonic - last_reference_activity.get(symbol, 0.0) >= 1:
                        _emit(
                            queue_out,
                            {
                                "kind": "market_activity",
                                "symbol": symbol,
                                "received_at": to_iso(received_at),
                                "source_mode": "official_sdk_trade_push",
                            },
                        )
                        last_reference_activity[symbol] = now_monotonic
                completed = builder.on_trade(symbol, payload, received_at=received_at)
                if completed and not _emit(queue_out, {"kind": "bars", "rows": completed}, critical=True):
                    raise RuntimeError("official_sdk_bar_delivery_failed")

            now_monotonic = time.monotonic()
            if pending_quotes and now_monotonic - last_quote_flush >= QUOTE_STATE_FLUSH_SECONDS:
                rows = [pending_quotes[symbol] for symbol in sorted(pending_quotes)]
                if _emit(queue_out, {"kind": "quote_state_batch", "rows": rows}):
                    pending_quotes.clear()
                    last_quote_flush = now_monotonic
            # Drain received trades before sealing a boundary; otherwise a
            # burst could turn an unprocessed symbol into a zero-volume bar.
            completed = builder.complete_boundary(targets, datetime.now(UTC)) if callback_events.empty() else []
            if completed and not _emit(queue_out, {"kind": "bars", "rows": completed}, critical=True):
                raise RuntimeError("official_sdk_bar_delivery_failed")
            if now_monotonic - last_heartbeat >= 1:
                with reference_activity_lock:
                    raw_reference_activity = [
                        dict(latest_reference_activity[symbol])
                        for symbol in sorted(latest_reference_activity)
                    ]
                _emit(
                    queue_out,
                    {
                        "kind": "heartbeat",
                        "at": to_iso(datetime.now(UTC)),
                        "transport_queue_depth": callback_events.qsize(),
                        "transport_reader_errors": [],
                        "transport_resources": _resources(),
                        "raw_notification_count": raw_event_count,
                        "raw_reference_activity": raw_reference_activity,
                    },
                )
                last_heartbeat = now_monotonic
            refreshed_daily = daily_refresh.step(quote, sdk, datetime.now(UTC))
            if refreshed_daily is not None and not _emit(
                queue_out,
                {"kind": "daily_context", "rows": refreshed_daily, "failures": [],
                 "source_mode": "official_sdk_post_session_daily_context"},
                critical=True,
            ):
                raise RuntimeError("official_sdk_daily_refresh_delivery_failed")
            stop_event.wait(0.05)
    except BaseException as exc:
        _emit(
            queue_out,
            {
                "kind": "error",
                "reason": f"official_sdk_quote_worker_failed:{type(exc).__name__}:{exc}",
            },
            critical=True,
        )
    finally:
        if quote is not None:
            try:
                quote.close()
            except Exception as exc:
                _emit(queue_out, {"kind": "error", "reason": f"official_sdk_quote_cleanup_failed:{type(exc).__name__}:{exc}"}, critical=True)
