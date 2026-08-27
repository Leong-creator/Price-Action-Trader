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
    {
        "initialize",
        "quote.subscribe",
        "quote.unsubscribe",
        "quote.subscriptions",
        "quote.quote",
        "shutdown",
    }
)
# Longbridge accepts the requests quickly when they are sent in small serial
# batches. Concurrent subscribe calls can leave later batches without a usable
# response while high-frequency push notifications are already arriving.
MAX_SERVE_INFLIGHT_REQUESTS = 1
REQUIRED_SUBSCRIPTION_TYPES = frozenset({1, 4})
QUOTE_STATE_FLUSH_INTERVAL_SECONDS = 0.25
MAX_NOTIFICATION_BATCH_MESSAGES = 2048
NOTIFICATION_TIME_SLICE_SECONDS = 0.05


def emit_worker(queue_out: Any, payload: dict[str, Any]) -> bool:
    try:
        queue_out.put_nowait(payload)
        return True
    except queue.Full:
        return False


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


def subscription_symbols_from_result(result: Any) -> set[str]:
    """Normalize both subscribe and quote.subscriptions response shapes."""
    rows: list[Any] = []
    if isinstance(result, dict):
        if isinstance(result.get("subscribed"), list):
            rows = list(result["subscribed"])
        elif isinstance(result.get("sub_list"), list):
            rows = list(result["sub_list"])
    elif isinstance(result, list):
        rows = list(result)
    subscribed: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = normalize_symbol(row.get("symbol"))
        fields = set(row.get("fields") or [])
        named_sub_types = {
            str(value).strip().lower()
            for value in row.get("sub_types") or []
            if str(value).strip()
        }
        sub_types = {
            int(value)
            for value in row.get("sub_type") or []
            if isinstance(value, (int, str)) and str(value).isdigit()
        }
        if symbol and (
            {"quote", "trades"}.issubset(fields)
            or {"quote", "trades"}.issubset(named_sub_types)
            or REQUIRED_SUBSCRIPTION_TYPES.issubset(sub_types)
        ):
            subscribed.add(symbol)
    return subscribed


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


def longbridge_serve_environment(
    *,
    region: str,
    http_url: str,
    quote_ws_url: str,
    owner_value: str,
) -> dict[str, str]:
    """Pin official quote endpoints without changing the host proxy settings."""
    environment = {
        **os.environ,
        "LONGBRIDGE_REGION": region,
        SERVE_OWNER_ENV: owner_value,
    }
    if http_url:
        environment["LONGBRIDGE_HTTP_URL"] = http_url
    if quote_ws_url:
        environment["LONGBRIDGE_QUOTE_WS_URL"] = quote_ws_url
    return environment


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
        http_url: str = "",
        quote_ws_url: str = "",
        owner_value: str = SERVE_OWNER_VALUE,
    ) -> None:
        self.response_timeout_seconds = response_timeout_seconds
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100_000)
        self.responses: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10_000)
        self.pending_responses: dict[int, dict[str, Any]] = {}
        self.stderr_tail: deque[str] = deque(maxlen=200)
        self.reader_errors: deque[str] = deque(maxlen=20)
        self._quote_lock = threading.Lock()
        self._latest_quote_notifications: dict[str, dict[str, Any]] = {}
        self._raw_reference_activity: dict[str, str] = {}
        self._raw_notification_count = 0
        self._coalesced_quote_replacement_count = 0
        self.process = subprocess.Popen(
            [str(binary), "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
            env=longbridge_serve_environment(
                region=region,
                http_url=http_url,
                quote_ws_url=quote_ws_url,
                owner_value=owner_value,
            ),
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
                    self._route_stdout_message(json.loads(line))
                except json.JSONDecodeError:
                    self.reader_errors.append("invalid_json_stdout")
                except queue.Full:
                    self.reader_errors.append("stdout_queue_full")
        except OSError as exc:
            self.reader_errors.append(f"stdout_error:{exc}")

    def _route_stdout_message(self, message: dict[str, Any]) -> None:
        """Coalesce quote updates before they can congest the shared queue."""
        received_at = to_iso(datetime.now(UTC))
        message["_m15_received_at"] = received_at
        method = str(message.get("method") or "")
        if not method and isinstance(message.get("id"), int):
            try:
                self.responses.put_nowait(message)
            except queue.Full:
                self.reader_errors.append("response_queue_full")
            return
        params = message.get("params")
        symbol = normalize_symbol(
            params.get("symbol") if isinstance(params, dict) else ""
        )
        with self._quote_lock:
            self._raw_notification_count += int(bool(method))
            if method and is_reference_symbol(symbol):
                self._raw_reference_activity[symbol] = received_at
            if method == "quote.updated" and symbol:
                if symbol in self._latest_quote_notifications:
                    self._coalesced_quote_replacement_count += 1
                self._latest_quote_notifications[symbol] = message
                return
        self.messages.put_nowait(message)

    def drain_coalesced_quote_notifications(self) -> list[dict[str, Any]]:
        lock = getattr(self, "_quote_lock", None)
        if lock is None:
            return []
        with lock:
            rows = list(self._latest_quote_notifications.values())
            self._latest_quote_notifications.clear()
        return rows

    def transport_diagnostics(self) -> dict[str, Any]:
        lock = getattr(self, "_quote_lock", None)
        if lock is None:
            return {
                "coalesced_quote_pending_count": 0,
                "coalesced_quote_replacement_count": 0,
                "raw_notification_count": 0,
                "raw_reference_activity": [],
            }
        with lock:
            raw_reference_activity = [
                {
                    "symbol": symbol,
                    "received_at": received_at,
                    "source_mode": "longbridge_serve_raw_push",
                }
                for symbol, received_at in sorted(
                    self._raw_reference_activity.items()
                )
            ]
            self._raw_reference_activity.clear()
            return {
                "coalesced_quote_pending_count": len(
                    self._latest_quote_notifications
                ),
                "coalesced_quote_replacement_count": (
                    self._coalesced_quote_replacement_count
                ),
                "raw_notification_count": self._raw_notification_count,
                "notification_queue_depth": self.messages.qsize(),
                "response_queue_depth": self.responses.qsize(),
                "raw_reference_activity": raw_reference_activity,
            }

    def _join_reader_threads(self, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        current = threading.current_thread()
        for attribute in ("_stdout_thread", "_stderr_thread"):
            reader = getattr(self, attribute, None)
            if reader is None or reader is current or not reader.is_alive():
                continue
            reader.join(timeout=max(0.0, deadline - time.monotonic()))

    def process_exit_detail(self) -> str:
        self._join_reader_threads()
        stderr = "|".join(getattr(self, "stderr_tail", ())).strip()
        reader_errors = "|".join(getattr(self, "reader_errors", ())).strip()
        details = ":".join(
            value for value in (stderr[-1000:], reader_errors[-500:]) if value
        )
        return (
            f"longbridge_serve_process_exited:{self.process.returncode}"
            + (f":{details}" if details else "")
        )

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
            raise RuntimeError(self.process_exit_detail())
        self.process.stdin.write(
            json.dumps(request, ensure_ascii=True, separators=(",", ":")) + "\n"
        )
        self.process.stdin.flush()

    def wait_for_response(
        self,
        request_id: int,
        on_notification: Any,
    ) -> dict[str, Any]:
        responses = self.wait_for_responses(
            {request_id},
            on_notification,
            timeout_seconds=self.response_timeout_seconds,
        )
        if request_id in responses:
            return responses[request_id]
        raise TimeoutError(f"longbridge_serve_response_timeout:id={request_id}")

    def wait_for_responses(
        self,
        request_ids: set[int],
        on_notification: Any,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[int, dict[str, Any]]:
        """Collect concurrent JSON-RPC responses without losing out-of-order IDs."""
        waiting = set(request_ids)
        responses: dict[int, dict[str, Any]] = {}
        for request_id in tuple(waiting):
            cached = self.pending_responses.pop(request_id, None)
            if cached is not None:
                responses[request_id] = cached
                waiting.remove(request_id)
        deadline = time.monotonic() + float(
            self.response_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        while waiting and time.monotonic() < deadline:
            try:
                message = self.responses.get_nowait()
            except queue.Empty:
                message = None
            if message is not None:
                response_id = message.get("id")
                if response_id in waiting:
                    responses[response_id] = message
                    waiting.remove(response_id)
                elif isinstance(response_id, int):
                    self.pending_responses[response_id] = message
                continue
            for notification in self.drain_coalesced_quote_notifications():
                on_notification(notification)
            reader_errors = list(getattr(self, "reader_errors", ()))
            if reader_errors:
                raise RuntimeError(
                    "longbridge_serve_reader_failed:"
                    + "|".join(reader_errors)[-1000:]
                )
            if self.process.poll() is not None:
                raise RuntimeError(self.process_exit_detail())
            notification_deadline = min(deadline, time.monotonic() + 0.05)
            processed_notifications = 0
            while (
                processed_notifications < MAX_NOTIFICATION_BATCH_MESSAGES
                and time.monotonic() < notification_deadline
            ):
                try:
                    notification = self.messages.get_nowait()
                except queue.Empty:
                    break
                on_notification(notification)
                processed_notifications += 1
            if waiting:
                try:
                    message = self.responses.get(
                        timeout=min(0.05, max(0.01, deadline - time.monotonic()))
                    )
                except queue.Empty:
                    continue
                response_id = message.get("id")
                if response_id in waiting:
                    responses[response_id] = message
                    waiting.remove(response_id)
                elif isinstance(response_id, int):
                    self.pending_responses[response_id] = message
            if len(self.pending_responses) > 10_000:
                self.pending_responses.pop(next(iter(self.pending_responses)))
        for notification in self.drain_coalesced_quote_notifications():
            on_notification(notification)
        return responses

    def close(self, request_id: int) -> None:
        try:
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
        finally:
            self._join_reader_threads()


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
            http_url=getattr(config, "quote_http_url", ""),
            quote_ws_url=getattr(config, "quote_ws_url", ""),
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
        pending_quote_state_by_symbol: dict[str, dict[str, Any]] = {}
        pending_critical_messages: deque[dict[str, Any]] = deque()
        quote_pushed_symbols: set[str] = set()
        trade_pushed_symbols: set[str] = set()
        last_reference_activity_emit: dict[str, float] = {}
        last_quote_state_flush = 0.0

        def flush_critical_messages() -> None:
            while pending_critical_messages:
                if not emit_worker(queue_out, pending_critical_messages[0]):
                    return
                pending_critical_messages.popleft()

        def emit_critical(payload: dict[str, Any]) -> None:
            pending_critical_messages.append(payload)
            flush_critical_messages()

        def flush_quote_states(*, force: bool = False) -> None:
            nonlocal last_quote_state_flush
            if not pending_quote_state_by_symbol or pending_critical_messages:
                return
            now_monotonic = time.monotonic()
            if (
                not force
                and now_monotonic - last_quote_state_flush
                < QUOTE_STATE_FLUSH_INTERVAL_SECONDS
            ):
                return
            rows = [
                pending_quote_state_by_symbol[symbol]
                for symbol in sorted(pending_quote_state_by_symbol)
            ]
            if emit_worker(
                queue_out,
                {
                    "kind": "quote_state_batch",
                    "rows": rows,
                },
            ):
                pending_quote_state_by_symbol.clear()
                last_quote_state_flush = now_monotonic

        def emit_reference_activity(symbol: str, received_at: datetime) -> None:
            normalized = normalize_symbol(symbol)
            if not is_reference_symbol(normalized):
                return
            now_monotonic = time.monotonic()
            previous = last_reference_activity_emit.get(normalized, 0.0)
            if previous and now_monotonic - previous < 1.0:
                return
            emitted = emit_worker(
                queue_out,
                {
                    "kind": "market_activity",
                    "symbol": normalized,
                    "received_at": to_iso(received_at),
                    "source_mode": "longbridge_serve_trade_push",
                },
            )
            if emitted:
                last_reference_activity_emit[normalized] = now_monotonic

        def handle_quote_payload(
            payload: dict[str, Any],
            *,
            source_mode: str,
            received_at: datetime | None = None,
        ) -> None:
            symbol = normalize_symbol(payload.get("symbol"))
            if not symbol or symbol not in target_set:
                return
            received_at = received_at or datetime.now(UTC)
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
            initial_quote_symbols.add(symbol)
            builder.seed_quote(symbol, merged_payload, received_at=received_at)
            pending_quote_state_by_symbol[symbol] = {
                "symbol": symbol,
                "payload": merged_payload,
                "received_at": to_iso(received_at),
                "source_mode": effective_source_mode,
            }

        def handle_notification(message: dict[str, Any]) -> None:
            method = str(message.get("method") or "")
            payload = message.get("params")
            if not isinstance(payload, dict):
                return
            symbol = normalize_symbol(payload.get("symbol"))
            try:
                received_at = datetime.fromisoformat(
                    str(message.get("_m15_received_at") or "").replace(
                        "Z", "+00:00"
                    )
                ).astimezone(UTC)
            except (TypeError, ValueError):
                received_at = datetime.now(UTC)
            if method == "quote.updated":
                quote_pushed_symbols.add(symbol)
                if symbol in trade_pushed_symbols:
                    subscribed.add(symbol)
                handle_quote_payload(
                    payload,
                    source_mode="longbridge_serve_push",
                    received_at=received_at,
                )
                emit_reference_activity(symbol, received_at)
            elif method == "quote.trades":
                trade_pushed_symbols.add(symbol)
                if symbol in quote_pushed_symbols:
                    subscribed.add(symbol)
                emit_reference_activity(symbol, received_at)
                completed = builder.on_trade(
                    symbol,
                    {"trades": list(payload.get("trades") or [])},
                    received_at=received_at,
                )
                if completed:
                    emit_critical({"kind": "bars", "rows": completed})

        session = LongbridgeServeSession(
            config.longbridge_serve_binary,
            region=config.quote_region,
            http_url=getattr(config, "quote_http_url", ""),
            quote_ws_url=getattr(config, "quote_ws_url", ""),
            response_timeout_seconds=config.longbridge_serve_response_timeout_seconds,
        )
        session.send({"jsonrpc": "2.0", "id": request_id, "method": "initialize"})
        initialization = session.wait_for_response(request_id, handle_notification)
        if initialization.get("error"):
            raise RuntimeError(
                f"longbridge_serve_initialize_failed:{initialization['error']}"
            )

        request_interval_seconds = float(
            getattr(config, "subscription_request_interval_seconds", 0.0)
        )
        retry_count = int(getattr(config, "subscription_retry_count", 0))
        retry_backoff_seconds = float(
            getattr(config, "subscription_retry_backoff_seconds", 0.0)
        )
        progress_deadline_seconds = float(
            getattr(
                config,
                "subscription_progress_deadline_seconds",
                config.longbridge_serve_response_timeout_seconds,
            )
        )
        subscription_started = time.monotonic()

        def remaining_progress_seconds() -> float:
            return max(
                0.0,
                subscription_started + progress_deadline_seconds - time.monotonic(),
            )

        def apply_subscribe_response(response: dict[str, Any]) -> None:
            if response.get("error"):
                return
            result = response.get("result") or {}
            subscribed.update(subscription_symbols_from_result(result))
            quotes = result.get("quotes") if isinstance(result, dict) else []
            for quote in quotes or []:
                if isinstance(quote, dict):
                    handle_quote_payload(
                        quote,
                        source_mode="longbridge_serve_initial_snapshot",
                    )

        def apply_quote_response(response: dict[str, Any]) -> None:
            if response.get("error"):
                return
            result = response.get("result") or []
            for quote in result if isinstance(result, list) else []:
                if isinstance(quote, dict):
                    handle_quote_payload(
                        quote,
                        source_mode="longbridge_serve_initial_snapshot",
                    )

        def send_windowed_requests(
            method: str,
            batches: list[list[str]],
            response_handler: Any,
            *,
            subscription_fields: list[str] | None = None,
        ) -> None:
            nonlocal request_id
            for offset in range(0, len(batches), MAX_SERVE_INFLIGHT_REQUESTS):
                if remaining_progress_seconds() <= 0:
                    return
                request_ids: set[int] = set()
                for batch in batches[
                    offset : offset + MAX_SERVE_INFLIGHT_REQUESTS
                ]:
                    request_id += 1
                    params: dict[str, Any] = {"symbols": batch}
                    if method == "quote.subscribe":
                        params["fields"] = list(
                            subscription_fields or ["quote", "trades"]
                        )
                    session.send(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": method,
                            "params": params,
                        }
                    )
                    request_ids.add(request_id)
                    if request_interval_seconds > 0:
                        time.sleep(request_interval_seconds)
                responses = session.wait_for_responses(
                    request_ids,
                    handle_notification,
                    timeout_seconds=min(
                        float(config.longbridge_serve_response_timeout_seconds),
                        remaining_progress_seconds(),
                    ),
                )
                for response in responses.values():
                    response_handler(response)

        def query_active_subscriptions() -> None:
            nonlocal request_id
            if remaining_progress_seconds() <= 0:
                return
            request_id += 1
            query_id = request_id
            session.send(
                {
                    "jsonrpc": "2.0",
                    "id": query_id,
                    "method": "quote.subscriptions",
                }
            )
            responses = session.wait_for_responses(
                {query_id},
                handle_notification,
                timeout_seconds=min(
                    float(config.longbridge_serve_response_timeout_seconds),
                    remaining_progress_seconds(),
                ),
            )
            response = responses.get(query_id)
            if response and not response.get("error"):
                subscribed.update(
                    subscription_symbols_from_result(response.get("result"))
                )

        def subscribe_group(group_targets: list[str]) -> set[str]:
            expected = set(group_targets)
            for attempt in range(retry_count + 1):
                missing = sorted(expected - subscribed)
                if not missing or remaining_progress_seconds() <= 0:
                    break
                batches = symbol_batches(
                    missing, config.longbridge_serve_batch_size
                )
                # A combined 147-symbol quote+trades request can wait until the
                # CLI's 30-second timeout during the opening burst. Two field-
                # specific requests on the same connection return promptly and
                # preserve the one-account/one-long-link boundary.
                for fields in (["quote"], ["trades"]):
                    send_windowed_requests(
                        "quote.subscribe",
                        batches,
                        apply_subscribe_response,
                        subscription_fields=fields,
                    )
                if expected - subscribed:
                    query_active_subscriptions()
                emit_worker(
                    queue_out,
                    {
                        "kind": "subscription_progress",
                        "completed": len(subscribed & target_set),
                        "total": len(targets),
                    },
                )
                if expected <= subscribed:
                    break
                if attempt < retry_count and retry_backoff_seconds > 0:
                    time.sleep(
                        min(retry_backoff_seconds, remaining_progress_seconds())
                    )
            return expected - subscribed

        def fetch_initial_quotes(group_targets: list[str]) -> set[str]:
            expected = set(group_targets)
            missing = sorted(expected - initial_quote_symbols)
            if missing and remaining_progress_seconds() > 0:
                send_windowed_requests(
                    "quote.quote",
                    symbol_batches(missing, config.longbridge_serve_batch_size),
                    apply_quote_response,
                )
            return expected - initial_quote_symbols

        # Subscribe the strategy pool and held-position monitoring symbols in
        # the same two field-specific requests. Sending another pair after the
        # 147-symbol pool can time out even though all targets fit below the
        # broker's 500-symbol limit. Readiness still evaluates the strategy pool
        # and monitoring-only symbols independently below.
        subscribe_group(targets)
        fetch_initial_quotes(targets)

        base_expected = set(base_targets)
        monitoring_expected = set(monitoring_targets)
        missing = sorted(
            (base_expected - subscribed) | (base_expected - initial_quote_symbols)
        )
        monitoring_missing = sorted(
            (monitoring_expected - subscribed)
            | (monitoring_expected - initial_quote_symbols)
        )
        emit_critical(
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
        flush_critical_messages()
        flush_quote_states(force=True)

        last_heartbeat = 0.0
        while not stop_event.is_set():
            if session.process.poll() is not None:
                raise RuntimeError(session.process_exit_detail())
            reader_errors = list(getattr(session, "reader_errors", ()))
            if reader_errors:
                raise RuntimeError(
                    "longbridge_serve_reader_failed:" + "|".join(reader_errors)[-1000:]
                )
            quote_messages = session.drain_coalesced_quote_notifications()
            for message in quote_messages:
                if isinstance(message, dict) and "method" in message:
                    handle_notification(message)

            # Limit actual trade-notification handling time. Limiting only the
            # queue drain still lets a large opening batch starve heartbeats
            # and five-minute boundary completion while the batch is handled.
            notification_processing_started = time.monotonic()
            processed_notification_count = 0
            while (
                processed_notification_count < MAX_NOTIFICATION_BATCH_MESSAGES
                and time.monotonic() - notification_processing_started
                < NOTIFICATION_TIME_SLICE_SECONDS
            ):
                try:
                    if quote_messages or processed_notification_count:
                        message = session.messages.get_nowait()
                    else:
                        remaining = max(
                            0.001,
                            NOTIFICATION_TIME_SLICE_SECONDS
                            - (time.monotonic() - notification_processing_started),
                        )
                        message = session.messages.get(timeout=remaining)
                except queue.Empty:
                    break
                if isinstance(message, dict) and "method" in message:
                    handle_notification(message)
                processed_notification_count += 1
            flush_critical_messages()
            flush_quote_states()
            completed = builder.complete_boundary(targets, datetime.now(UTC))
            if completed:
                emit_critical({"kind": "bars", "rows": completed})
            now_monotonic = time.monotonic()
            if now_monotonic - last_heartbeat >= 1:
                transport_diagnostics = session.transport_diagnostics()
                emitted = emit_worker(
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
                        **transport_diagnostics,
                    },
                )
                if emitted:
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
