#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def us_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    return value if "." in value else f"{value}.US"


def load_symbols(universe_path: str | Path, limit: int) -> list[str]:
    payload = json.loads(Path(universe_path).read_text(encoding="utf-8"))
    rows = payload.get("symbols", []) if isinstance(payload, dict) else payload
    symbols = [us_symbol(str(item)) for item in rows]
    if limit <= 0 or limit > len(symbols):
        raise ValueError(f"invalid_symbol_limit:{limit}/{len(symbols)}")
    return symbols[:limit]


def process_resources() -> dict[str, int]:
    rss_kb = 0
    try:
        for row in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if row.startswith("VmRSS:"):
                rss_kb = int(row.split()[1])
                break
    except (OSError, ValueError, IndexError):
        pass
    try:
        file_descriptors = len(list(Path("/proc/self/fd").iterdir()))
    except OSError:
        file_descriptors = 0
    return {
        "threads": threading.active_count(),
        "file_descriptors": file_descriptors,
        "rss_kb": rss_kb,
    }


@dataclass(slots=True)
class EventRecorder:
    symbols: list[str]
    _lock: threading.Lock = field(init=False, repr=False)
    _counts: dict[str, dict[str, int]] = field(init=False, repr=False)
    _first: dict[str, dict[str, str]] = field(init=False, repr=False)
    _last: dict[str, dict[str, str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, dict[str, int]] = {
            symbol: {"quote": 0, "trade": 0} for symbol in self.symbols
        }
        self._first: dict[str, dict[str, str]] = defaultdict(dict)
        self._last: dict[str, dict[str, str]] = defaultdict(dict)

    def record(self, symbol: str, event_type: str) -> None:
        normalized = us_symbol(symbol)
        if normalized not in self._counts or event_type not in {"quote", "trade"}:
            return
        now = utc_now()
        with self._lock:
            self._counts[normalized][event_type] += 1
            self._first[normalized].setdefault(event_type, now)
            self._last[normalized][event_type] = now

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            rows = {
                symbol: {
                    "quote_events": values["quote"],
                    "trade_events": values["trade"],
                    "first_quote_at": self._first[symbol].get("quote", ""),
                    "last_quote_at": self._last[symbol].get("quote", ""),
                    "first_trade_at": self._first[symbol].get("trade", ""),
                    "last_trade_at": self._last[symbol].get("trade", ""),
                }
                for symbol, values in self._counts.items()
            }
        return {
            "symbols": rows,
            "symbols_with_quote_events": sum(row["quote_events"] > 0 for row in rows.values()),
            "symbols_with_trade_events": sum(row["trade_events"] > 0 for row in rows.values()),
            "quote_event_count": sum(row["quote_events"] for row in rows.values()),
            "trade_event_count": sum(row["trade_events"] for row in rows.values()),
        }


def subscription_symbols(rows: Any) -> set[str]:
    result: set[str] = set()
    for row in rows or []:
        if isinstance(row, dict):
            symbol = row.get("symbol")
        else:
            symbol = getattr(row, "symbol", None)
        if symbol:
            result.add(us_symbol(str(symbol)))
    return result


def run_sdk_canary(
    *,
    sdk: Any,
    sdk_config: Any,
    symbols: list[str],
    fields: tuple[str, ...],
    duration_seconds: float,
    batch_size: int = 50,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    recorder = EventRecorder(symbols)
    context = sdk.QuoteContext(sdk_config)
    if "quote" in fields:
        context.set_on_quote(lambda symbol, _event: recorder.record(str(symbol), "quote"))
    if "trade" in fields:
        context.set_on_trades(lambda symbol, _event: recorder.record(str(symbol), "trade"))
    sub_types = []
    if "quote" in fields:
        sub_types.append(sdk.SubType.Quote)
    if "trade" in fields:
        sub_types.append(sdk.SubType.Trade)
    started = utc_now()
    subscribe_receipts: list[dict[str, Any]] = []
    for offset in range(0, len(symbols), batch_size):
        batch = symbols[offset : offset + batch_size]
        before = time.monotonic()
        try:
            context.subscribe(batch, sub_types)
        except Exception as exc:  # SDK raises a native OpenApiException type.
            subscribe_receipts.append({
                "symbols": batch,
                "elapsed_ms": round((time.monotonic() - before) * 1000, 3),
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            continue
        subscribe_receipts.append({
            "symbols": batch,
            "elapsed_ms": round((time.monotonic() - before) * 1000, 3),
            "status": "subscribed",
        })
    try:
        actual = subscription_symbols(context.subscriptions())
        subscription_query_error = ""
    except Exception as exc:
        actual = set()
        subscription_query_error = f"{type(exc).__name__}:{exc}"
    initial_resources = process_resources()
    sleep(duration_seconds)
    final_resources = process_resources()
    events = recorder.snapshot()
    return {
        "schema_version": "m15.quote-transport-canary.v1",
        "transport": "official_sdk",
        "started_at": started,
        "finished_at": utc_now(),
        "duration_seconds": duration_seconds,
        "requested_fields": list(fields),
        "requested_symbol_count": len(symbols),
        "actual_subscription_count": len(actual & set(symbols)),
        "missing_subscriptions": sorted(set(symbols) - actual),
        "subscribe_receipts": subscribe_receipts,
        "subscription_query_error": subscription_query_error,
        "events": events,
        "resources_start": initial_resources,
        "resources_end": final_resources,
        "resource_delta": {
            key: final_resources[key] - initial_resources[key]
            for key in initial_resources
        },
    }


def run_cli_serve_canary(
    *,
    binary: str | Path,
    symbols: list[str],
    fields: tuple[str, ...],
    duration_seconds: float,
) -> dict[str, Any]:
    process = subprocess.Popen(
        [str(binary), "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if process.stdin is None or process.stdout is None:
        raise RuntimeError("longbridge_serve_pipe_unavailable")
    messages: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100_000)
    reader_errors: list[str] = []

    def reader() -> None:
        try:
            for line in process.stdout:
                try:
                    messages.put_nowait(json.loads(line))
                except (json.JSONDecodeError, queue.Full) as exc:
                    reader_errors.append(type(exc).__name__)
        except OSError as exc:
            reader_errors.append(str(exc))

    thread = threading.Thread(target=reader, name="longbridge-serve-reader", daemon=True)
    thread.start()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "quote.subscribe",
        "params": {"symbols": symbols, "fields": list(fields)},
    }
    process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
    process.stdin.flush()
    recorder = EventRecorder(symbols)
    subscribed: set[str] = set()
    started = utc_now()
    deadline = time.monotonic() + duration_seconds
    while time.monotonic() < deadline:
        try:
            message = messages.get(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if message.get("id") == 1:
            for row in (message.get("result") or {}).get("subscribed", []):
                if row.get("symbol"):
                    subscribed.add(us_symbol(str(row["symbol"])))
        method = str(message.get("method") or "")
        params = message.get("params") or {}
        symbol = str(params.get("symbol") or "")
        if method == "quote.updated":
            recorder.record(symbol, "quote")
        elif method == "quote.trades":
            recorder.record(symbol, "trade")
    try:
        process.stdin.write('{"jsonrpc":"2.0","id":2,"method":"shutdown"}\n')
        process.stdin.flush()
    except (BrokenPipeError, OSError):
        reader_errors.append("serve_stdin_closed_before_shutdown")
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)
    stderr_tail = ""
    if process.stderr is not None:
        try:
            stderr_tail = process.stderr.read()[-2000:]
        except OSError:
            pass
    return {
        "schema_version": "m15.quote-transport-canary.v1",
        "transport": "longbridge_serve",
        "started_at": started,
        "finished_at": utc_now(),
        "duration_seconds": duration_seconds,
        "requested_fields": list(fields),
        "requested_symbol_count": len(symbols),
        "actual_subscription_count": len(subscribed & set(symbols)),
        "missing_subscriptions": sorted(set(symbols) - subscribed),
        "events": recorder.snapshot(),
        "reader_errors": reader_errors,
        "stderr_tail": stderr_tail,
        "process_returncode": process.returncode,
    }
