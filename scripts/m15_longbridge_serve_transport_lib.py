#!/usr/bin/env python3
"""Long-lived Longbridge CLI quote transport for the M15 paper runtime.

Only market data flows through ``longbridge serve``. Account state and every
order operation remain on the SDK clients owned by the parent runtime.
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.m15_longbridge_sdk_runtime_lib import (
    FiveMinuteBarBuilder,
    configured_symbols,
    configured_trading_symbols,
    floor_bar_open,
    load_config,
    to_iso,
    unix_to_utc,
)

SERVE_OWNER_ENV = "M15_LONGBRIDGE_SERVE_OWNER"
SERVE_OWNER_VALUE = "price-action-trader-m15"
ALLOWED_SERVE_METHODS = frozenset(
    {"initialize", "quote.subscribe", "quote.unsubscribe", "quote.quote", "shutdown"}
)


def emit_worker(queue_out: Any, payload: dict[str, Any]) -> None:
    try:
        if payload.get("kind") in {
            "bars",
            "ready",
            "error",
            "heartbeat",
            "market_activity",
            "subscription_progress",
        }:
            queue_out.put(payload, timeout=1)
        else:
            queue_out.put_nowait(payload)
    except queue.Full:
        return


def symbol_batches(symbols: list[str], batch_size: int) -> list[list[str]]:
    if batch_size <= 0:
        raise ValueError("longbridge_serve_batch_size_must_be_positive")
    return [
        symbols[offset : offset + batch_size]
        for offset in range(0, len(symbols), batch_size)
    ]


def normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        return ""
    return symbol if "." in symbol else f"{symbol}.US"


def is_reference_symbol(symbol: str) -> bool:
    return normalize_symbol(symbol) in {"SPY.US", "QQQ.US"}


def process_resource_snapshot(pid: int) -> dict[str, int]:
    """Read bounded Linux process health evidence without invoking a subprocess."""
    rss_kb = 0
    thread_count = 0
    try:
        for row in Path(f"/proc/{pid}/status").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if row.startswith("VmRSS:"):
                rss_kb = int(row.split()[1])
            elif row.startswith("Threads:"):
                thread_count = int(row.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    try:
        file_descriptor_count = sum(1 for _ in Path(f"/proc/{pid}/fd").iterdir())
    except OSError:
        file_descriptor_count = 0
    return {
        "rss_kb": rss_kb,
        "thread_count": thread_count,
        "file_descriptor_count": file_descriptor_count,
    }


def merge_quote_payload(
    previous: dict[str, Any] | None,
    incoming: dict[str, Any],
    *,
    received_at: datetime,
) -> tuple[dict[str, Any], bool]:
    """Fold a quote tick onto its snapshot while preserving the newest timestamp."""
    if not previous:
        return dict(incoming), False
    incoming_at = unix_to_utc(incoming.get("timestamp"), received_at)
    previous_at = unix_to_utc(previous.get("timestamp"), received_at)
    if incoming_at < previous_at:
        return {**incoming, **previous}, True
    return {**previous, **incoming}, False


class LongbridgeServeSession:
    """Small newline-delimited JSON-RPC client with one stdout reader."""

    def __init__(
        self,
        binary: Path,
        *,
        region: str,
        response_timeout_seconds: int,
    ) -> None:
        self.response_timeout_seconds = response_timeout_seconds
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100_000)
        self.stderr_tail: deque[str] = deque(maxlen=200)
        self.reader_errors: deque[str] = deque(maxlen=20)
        self.process = subprocess.Popen(
            [str(binary), "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
            env={
                **os.environ,
                "LONGBRIDGE_REGION": region,
                SERVE_OWNER_ENV: SERVE_OWNER_VALUE,
            },
        )
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("longbridge_serve_pipe_unavailable")
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            name="m15-longbridge-serve-stdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="m15-longbridge-serve-stderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put_nowait(json.loads(line))
                except json.JSONDecodeError:
                    self.reader_errors.append("invalid_json_stdout")
                except queue.Full:
                    self.reader_errors.append("stdout_queue_full")
        except OSError as exc:
            self.reader_errors.append(f"stdout_error:{exc}")

    def _read_stderr(self) -> None:
        if self.process.stderr is None:
            return
        try:
            for line in self.process.stderr:
                self.stderr_tail.append(line.rstrip())
        except OSError as exc:
            self.reader_errors.append(f"stderr_error:{exc}")

    def send(self, request: dict[str, Any]) -> None:
        method = str(request.get("method") or "")
        if method not in ALLOWED_SERVE_METHODS:
            raise ValueError(f"longbridge_serve_method_not_allowed:{method or 'missing'}")
        if self.process.poll() is not None or self.process.stdin is None:
            raise RuntimeError(
                f"longbridge_serve_process_exited:{self.process.returncode}"
            )
        self.process.stdin.write(
            json.dumps(request, ensure_ascii=True, separators=(",", ":")) + "\n"
        )
        self.process.stdin.flush()

    def wait_for_response(
        self,
        request_id: int,
        on_notification: Any,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.response_timeout_seconds
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"longbridge_serve_process_exited:{self.process.returncode}"
                )
            try:
                message = self.messages.get(
                    timeout=min(0.25, max(0.01, deadline - time.monotonic()))
                )
            except queue.Empty:
                continue
            if "method" in message:
                on_notification(message)
                continue
            if message.get("id") == request_id:
                return message
        raise TimeoutError(f"longbridge_serve_response_timeout:id={request_id}")

    def close(self, request_id: int) -> None:
        if self.process.poll() is not None:
            return
        try:
            self.send({"jsonrpc": "2.0", "id": request_id, "method": "shutdown"})
            self.process.wait(timeout=10)
        except (BrokenPipeError, OSError, RuntimeError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    return
                self.process.wait(timeout=5)


def cleanup_orphaned_longbridge_serve_processes() -> list[int]:
    """Terminate only serve processes explicitly marked as owned by M15."""
    cleaned: list[int] = []
    marker = f"{SERVE_OWNER_ENV}={SERVE_OWNER_VALUE}"
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            environment = (entry / "environ").read_bytes().decode(
                "utf-8", errors="ignore"
            ).split("\x00")
            command = (entry / "cmdline").read_bytes().decode(
                "utf-8", errors="ignore"
            ).replace("\x00", " ")
        except OSError:
            continue
        if marker not in environment or "longbridge serve" not in command:
            continue
        try:
            os.killpg(pid, signal.SIGTERM)
            cleaned.append(pid)
        except (ProcessLookupError, PermissionError):
            continue
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not any(Path(f"/proc/{pid}").exists() for pid in cleaned):
            break
        time.sleep(0.05)
    for pid in cleaned:
        if not Path(f"/proc/{pid}").exists():
            continue
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return cleaned


def probe_longbridge_serve_transport(
    config: Any,
    symbols: tuple[str, ...],
) -> dict[str, Any]:
    """Verify the configured read-only serve transport without starting M15."""
    targets = tuple(dict.fromkeys(normalize_symbol(symbol) for symbol in symbols))
    if not targets or any(not symbol for symbol in targets):
        raise ValueError("longbridge_serve_preflight_symbols_missing")
    session: LongbridgeServeSession | None = None
    request_id = 1
    pushed_symbols: set[str] = set()

    def observe_notification(message: dict[str, Any]) -> None:
        if str(message.get("method") or "") not in {"quote.updated", "quote.trades"}:
            return
        payload = message.get("params")
        if isinstance(payload, dict):
            symbol = normalize_symbol(payload.get("symbol"))
            if symbol:
                pushed_symbols.add(symbol)

    try:
        session = LongbridgeServeSession(
            config.longbridge_serve_binary,
            region=config.quote_region,
            response_timeout_seconds=config.longbridge_serve_response_timeout_seconds,
        )
        session.send({"jsonrpc": "2.0", "id": request_id, "method": "initialize"})
        initialized = session.wait_for_response(request_id, observe_notification)
        if initialized.get("error"):
            raise RuntimeError(
                f"longbridge_serve_preflight_initialize_failed:{initialized['error']}"
            )

        request_id += 1
        session.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "quote.subscribe",
                "params": {"symbols": list(targets), "fields": ["quote", "trades"]},
            }
        )
        response = session.wait_for_response(request_id, observe_notification)
        if response.get("error"):
            raise RuntimeError(
                f"longbridge_serve_preflight_subscribe_failed:{response['error']}"
            )
        result = response.get("result") or {}
        subscribed = {
            normalize_symbol(row.get("symbol"))
            for row in result.get("subscribed") or []
            if isinstance(row, dict)
            and {"quote", "trades"}.issubset(set(row.get("fields") or []))
        }
        quoted = {
            normalize_symbol(row.get("symbol"))
            for row in result.get("quotes") or []
            if isinstance(row, dict)
        }
        missing_quotes = sorted(set(targets) - quoted - pushed_symbols)
        if missing_quotes:
            request_id += 1
            session.send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "quote.quote",
                    "params": {"symbols": missing_quotes},
                }
            )
            quote_response = session.wait_for_response(
                request_id, observe_notification
            )
            if quote_response.get("error"):
                raise RuntimeError(
                    "longbridge_serve_preflight_quote_failed:"
                    f"{quote_response['error']}"
                )
            quoted.update(
                normalize_symbol(row.get("symbol"))
                for row in quote_response.get("result") or []
                if isinstance(row, dict)
            )
        missing_subscriptions = sorted(set(targets) - subscribed)
        missing_quotes = sorted(set(targets) - quoted - pushed_symbols)
        if missing_subscriptions or missing_quotes:
            raise RuntimeError(
                "longbridge_serve_preflight_incomplete:"
                f"subscriptions={','.join(missing_subscriptions)}:"
                f"quotes={','.join(missing_quotes)}"
            )
        return {
            "transport": "longbridge_serve_persistent_jsonrpc",
            "market_data_mode": "longbridge_serve_subscription",
            "requested_symbols": list(targets),
            "subscription_coverage": f"{len(subscribed)}/{len(targets)}",
            "initial_quote_coverage": (
                f"{len((quoted | pushed_symbols) & set(targets))}/{len(targets)}"
            ),
            "longbridge_serve_pid": session.process.pid,
        }
    finally:
        if session is not None:
            session.close(request_id + 1)


def longbridge_serve_quote_worker(
    config_path: str,
    queue_out: Any,
    stop_event: Any,
    position_monitoring_symbols: tuple[str, ...] = (),
) -> None:
    """Own the only live quote process and emit the existing worker contract."""
    config = load_config(config_path)
    session: LongbridgeServeSession | None = None
    request_id = 1
    try:
        worker_started_at = datetime.now(UTC)
        first_complete_bar_open = floor_bar_open(
            worker_started_at, config.bar_minutes
        ) + timedelta(minutes=config.bar_minutes)
        builder = FiveMinuteBarBuilder(
            config.bar_minutes,
            complete_bar_open_not_before=first_complete_bar_open,
            boundary_batch_mode=True,
            push_source_mode="longbridge_serve_push",
            no_trade_source_mode="longbridge_serve_no_trade_carry_forward",
            event_id_prefix="longbridge-serve-5m",
        )
        base_targets = list(configured_symbols(config))
        trading_targets = set(configured_trading_symbols(config))
        monitoring_targets = sorted(
            {
                normalize_symbol(symbol)
                for symbol in position_monitoring_symbols
                if normalize_symbol(symbol) not in set(base_targets)
            }
        )
        targets = list(dict.fromkeys(base_targets + monitoring_targets))
        target_set = set(targets)
        subscribed: set[str] = set()
        initial_quote_symbols: set[str] = set()
        quote_payload_by_symbol: dict[str, dict[str, Any]] = {}
        quote_source_by_symbol: dict[str, str] = {}
        last_reference_activity_emit: dict[str, float] = {}
        last_quote_state_emit: dict[str, float] = {}

        def emit_reference_activity(symbol: str, received_at: datetime) -> None:
            normalized = normalize_symbol(symbol)
            if not is_reference_symbol(normalized):
                return
            now_monotonic = time.monotonic()
            previous = last_reference_activity_emit.get(normalized, 0.0)
            if previous and now_monotonic - previous < 1.0:
                return
            last_reference_activity_emit[normalized] = now_monotonic
            emit_worker(
                queue_out,
                {
                    "kind": "market_activity",
                    "symbol": normalized,
                    "received_at": to_iso(received_at),
                    "source_mode": "longbridge_serve_trade_push",
                },
            )

        def handle_quote_payload(
            payload: dict[str, Any],
            *,
            source_mode: str,
        ) -> None:
            symbol = normalize_symbol(payload.get("symbol"))
            if not symbol or symbol not in target_set:
                return
            received_at = datetime.now(UTC)
            merged_payload, kept_newer = merge_quote_payload(
                quote_payload_by_symbol.get(symbol),
                payload,
                received_at=received_at,
            )
            effective_source_mode = (
                quote_source_by_symbol.get(symbol, source_mode)
                if kept_newer
                else source_mode
            )
            quote_payload_by_symbol[symbol] = merged_payload
            quote_source_by_symbol[symbol] = effective_source_mode
            builder.seed_quote(symbol, merged_payload, received_at=received_at)
            now_monotonic = time.monotonic()
            previous_emit = last_quote_state_emit.get(symbol, 0.0)
            if (
                source_mode == "longbridge_serve_push"
                and previous_emit
                and now_monotonic - previous_emit < 0.25
            ):
                return
            last_quote_state_emit[symbol] = now_monotonic
            emit_worker(
                queue_out,
                {
                    "kind": "quote_state",
                    "symbol": symbol,
                    "payload": merged_payload,
                    "received_at": to_iso(received_at),
                    "source_mode": effective_source_mode,
                },
            )

        def handle_notification(message: dict[str, Any]) -> None:
            method = str(message.get("method") or "")
            payload = message.get("params")
            if not isinstance(payload, dict):
                return
            symbol = normalize_symbol(payload.get("symbol"))
            received_at = datetime.now(UTC)
            if method == "quote.updated":
                handle_quote_payload(payload, source_mode="longbridge_serve_push")
                emit_reference_activity(symbol, received_at)
            elif method == "quote.trades":
                emit_reference_activity(symbol, received_at)
                completed = builder.on_trade(
                    symbol,
                    {"trades": list(payload.get("trades") or [])},
                    received_at=received_at,
                )
                if completed:
                    emit_worker(queue_out, {"kind": "bars", "rows": completed})

        session = LongbridgeServeSession(
            config.longbridge_serve_binary,
            region=config.quote_region,
            response_timeout_seconds=config.longbridge_serve_response_timeout_seconds,
        )
        session.send({"jsonrpc": "2.0", "id": request_id, "method": "initialize"})
        initialization = session.wait_for_response(request_id, handle_notification)
        if initialization.get("error"):
            raise RuntimeError(
                f"longbridge_serve_initialize_failed:{initialization['error']}"
            )

        for batch in symbol_batches(targets, config.longbridge_serve_batch_size):
            request_id += 1
            session.send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "quote.subscribe",
                    "params": {
                        "symbols": batch,
                        "fields": ["quote", "trades"],
                    },
                }
            )
            response = session.wait_for_response(request_id, handle_notification)
            if response.get("error"):
                raise RuntimeError(
                    f"longbridge_serve_subscribe_failed:{response['error']}"
                )
            result = response.get("result") or {}
            for row in result.get("subscribed") or []:
                if isinstance(row, dict):
                    symbol = normalize_symbol(row.get("symbol"))
                    fields = set(row.get("fields") or [])
                    if symbol and {"quote", "trades"}.issubset(fields):
                        subscribed.add(symbol)
            for quote in result.get("quotes") or []:
                if isinstance(quote, dict):
                    initial_symbol = normalize_symbol(quote.get("symbol"))
                    if initial_symbol:
                        initial_quote_symbols.add(initial_symbol)
                    handle_quote_payload(
                        quote,
                        source_mode="longbridge_serve_initial_snapshot",
                    )
            emit_worker(
                queue_out,
                {
                    "kind": "subscription_progress",
                    "completed": len(subscribed & target_set),
                    "total": len(targets),
                },
            )

        for batch in symbol_batches(
            sorted(target_set - initial_quote_symbols),
            config.longbridge_serve_batch_size,
        ):
            request_id += 1
            session.send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "quote.quote",
                    "params": {"symbols": batch},
                }
            )
            response = session.wait_for_response(request_id, handle_notification)
            if response.get("error"):
                raise RuntimeError(
                    f"longbridge_serve_initial_quote_failed:{response['error']}"
                )
            result = response.get("result") or []
            for quote in result if isinstance(result, list) else []:
                if not isinstance(quote, dict):
                    continue
                initial_symbol = normalize_symbol(quote.get("symbol"))
                if initial_symbol:
                    initial_quote_symbols.add(initial_symbol)
                handle_quote_payload(
                    quote,
                    source_mode="longbridge_serve_initial_snapshot",
                )

        base_expected = set(base_targets)
        monitoring_expected = set(monitoring_targets)
        missing = sorted(
            (base_expected - subscribed) | (base_expected - initial_quote_symbols)
        )
        monitoring_missing = sorted(
            (monitoring_expected - subscribed)
            | (monitoring_expected - initial_quote_symbols)
        )
        emit_worker(
            queue_out,
            {
                "kind": "ready",
                "market_data_mode": "longbridge_serve_subscription",
                "market_data_transport": "longbridge_serve_persistent_jsonrpc",
                "market_data_symbols": sorted(base_expected - set(missing)),
                "subscribed_symbols": sorted(base_expected - set(missing)),
                "subscription_failed_symbols": missing,
                "trading_subscription_failed_symbols": sorted(
                    trading_targets & set(missing)
                ),
                "position_monitoring_symbols": monitoring_targets,
                "position_monitoring_subscribed_symbols": sorted(
                    monitoring_expected - set(monitoring_missing)
                ),
                "position_monitoring_failed_symbols": monitoring_missing,
                "daily_context_failed_symbols": [],
                "partial_bar_suppressed_until": to_iso(
                    first_complete_bar_open.astimezone(UTC)
                ),
                "subscription_target_count": len(targets),
                "initial_snapshot_coverage": (
                    f"{len(initial_quote_symbols & base_expected)}/{len(base_expected)}"
                ),
                "position_monitoring_initial_snapshot_coverage": (
                    f"{len(initial_quote_symbols & monitoring_expected)}/"
                    f"{len(monitoring_expected)}"
                ),
                "longbridge_serve_pid": session.process.pid,
            },
        )

        last_heartbeat = 0.0
        while not stop_event.is_set():
            if session.process.poll() is not None:
                raise RuntimeError(
                    f"longbridge_serve_process_exited:{session.process.returncode}:"
                    + "|".join(session.stderr_tail)[-1000:]
                )
            reader_errors = list(getattr(session, "reader_errors", ()))
            if reader_errors:
                raise RuntimeError(
                    "longbridge_serve_reader_failed:" + "|".join(reader_errors)[-1000:]
                )
            messages: list[dict[str, Any]] = []
            try:
                messages.append(session.messages.get(timeout=0.05))
            except queue.Empty:
                pass
            while len(messages) < 10_000:
                try:
                    messages.append(session.messages.get_nowait())
                except queue.Empty:
                    break
            for message in messages:
                if isinstance(message, dict) and "method" in message:
                    handle_notification(message)
            completed = builder.complete_boundary(targets, datetime.now(UTC))
            if completed:
                emit_worker(queue_out, {"kind": "bars", "rows": completed})
            now_monotonic = time.monotonic()
            if now_monotonic - last_heartbeat >= 1:
                emit_worker(
                    queue_out,
                    {
                        "kind": "heartbeat",
                        "at": to_iso(datetime.now(UTC)),
                        "market_data_mode": "longbridge_serve_subscription",
                        "transport_queue_depth": session.messages.qsize(),
                        "transport_reader_errors": list(
                            getattr(session, "reader_errors", ())
                        ),
                        "transport_resources": process_resource_snapshot(
                            session.process.pid
                        ),
                    },
                )
                last_heartbeat = now_monotonic
    except BaseException as exc:
        emit_worker(
            queue_out,
            {
                "kind": "error",
                "reason": (
                    "longbridge_serve_quote_worker_failed:"
                    f"{type(exc).__name__}:{exc}"
                ),
            },
        )
    finally:
        if session is not None:
            session.close(request_id + 1)
