"""Observability only: no freshness decisions, recovery, accounts or orders."""
from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class PipelineDiagnostics:
    """Independent callback-entry evidence; bounded metadata, never SDK payloads."""

    def __init__(self, sample_limit: int = 64) -> None:
        self._lock = threading.Lock()
        self._stages: dict[str, dict[str, Any]] = {}
        self._samples: deque[dict[str, Any]] = deque(maxlen=sample_limit)
        self._sample_overwritten = 0

    def record(self, stage: str, symbol: str = "", kind: str = "", count: int = 1) -> None:
        now = datetime.now(UTC).isoformat()
        monotonic = time.monotonic()
        key = f"{stage}:{symbol}:{kind}"
        with self._lock:
            row = self._stages.setdefault(key, {"stage": stage, "symbol": symbol,
                "kind": kind, "count": 0, "first_at": now})
            row.update(count=row["count"] + count, last_at=now, last_monotonic=monotonic)
            if len(self._samples) == self._samples.maxlen:
                self._sample_overwritten += 1
            self._samples.append({"stage": stage, "symbol": symbol, "kind": kind,
                                  "at": now, "monotonic": monotonic, "count": count})

    def snapshot(self, *, drain_samples: bool = False) -> dict[str, Any]:
        with self._lock:
            result = {"schema_version": "m15.marketdata-diagnostics.v1",
                "observed_at": datetime.now(UTC).isoformat(), "process_id": os.getpid(),
                "observed_monotonic": time.monotonic(),
                "native_reader_state": "unknown", "sdk_internal_reconnect_state": "unknown",
                "stages": {key: dict(row) for key, row in self._stages.items()},
                "samples": list(self._samples), "sample_overwritten_count": self._sample_overwritten}
            if drain_samples:
                self._samples.clear()
            return result


def append_diagnostic_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    """Caller must run outside callbacks. Failure must not silently hide evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(snapshot, sort_keys=True) + "\n")


def acquire_quote_owner_lock(path: Path | None = None):
    """Process lifetime lock shared by production worker and isolated probe."""
    path = path or Path.home() / ".cache/price-action-trader/m15_sdk_quote_subscription.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        stream.close()
        raise RuntimeError("another_quote_owner_is_active") from None
    return stream


def assert_no_legacy_quote_processes(proc_root: Path = Path("/proc")) -> None:
    """Fail closed on known runtime owners/orphan children; never terminate them."""
    owners = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            parts = (entry / "cmdline").read_bytes().decode(errors="replace").split("\0")
            executable = Path(parts[0]).name if parts else ""
            if executable == "longbridge" and set(parts) & {"serve", "quote", "quotes", "candlesticks", "subscribe"}:
                owners.append(int(entry.name))
                continue
            if "python" not in executable:
                continue
            runtime = any(Path(part).name == "run_m15_longbridge_sdk_runtime.py" for part in parts)
            diagnostic = any(Path(part).name == "run_m15_longbridge_quote_diagnostic.py" for part in parts)
            child = any("multiprocessing.spawn" in part for part in parts)
            log = os.readlink(entry / "fd/1") if child else ""
            if (runtime and not set(parts) & {"--status", "--stop", "--check", "--daemon"}) or diagnostic or (child and "m15_longbridge_sdk_runtime.log" in log):
                owners.append(int(entry.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            continue  # Other users are not this account's runtime.
        except OSError:
            continue
    if owners:
        raise RuntimeError("existing_quote_processes:" + ",".join(map(str, sorted(owners))))


def safe_exception_evidence(exc: BaseException) -> dict[str, Any]:
    """Preserve SDK codes and bounded causal types without message/trace/token text.

    Quote code mappings: https://open.longbridge.com/docs/quote/subscribe/subscribe
    Permission code: https://open.longbridge.com/docs/quote/pull/candlestick
    Keyword classification is explicitly heuristic; original text is never returned.
    """
    code_categories = {301600: "invalid_request", 301602: "server_error",
        301603: "no_quote", 301604: "permission_denied", 301605: "subscription_limit",
        301606: "rate_limited"}
    chain: list[dict[str, Any]] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and len(chain) < 8 and id(current) not in seen:
        seen.add(id(current))
        raw_code = getattr(current, "code", None)
        code = raw_code if type(raw_code) is int else None
        kind_text = str(getattr(current, "kind", ""))
        kind = {"Http": "Http", "ErrorKind.Http": "Http", "OpenApi": "OpenApi",
                "ErrorKind.OpenApi": "OpenApi", "Other": "Other", "ErrorKind.Other": "Other"}.get(kind_text)
        category, basis = "sdk_or_runtime_error", "unknown"
        if isinstance(current, TimeoutError):
            category, basis = "request_timeout", "exception_type"
        elif code in code_categories:
            category, basis = code_categories[code], "documented_quote_code"
        elif kind == "Http" and code in {401, 403, 408, 429, 504}:
            category = {401: "authentication_failed", 403: "permission_denied", 408: "request_timeout",
                        429: "rate_limited", 504: "request_timeout"}[code]
            basis = "http_status_code"
        else:
            message = getattr(current, "message", "")
            if isinstance(message, str):
                lowered = message[:4096].lower()
                if any(token in lowered for token in ("timeout", "timed out", "超时")):
                    category, basis = "request_timeout", "message_keyword_not_root_cause"
                elif any(token in lowered for token in ("rate limit", "too many requests", "限频")):
                    category, basis = "rate_limited", "message_keyword_not_root_cause"
                elif any(token in lowered for token in ("permission", "no access", "无权限")):
                    category, basis = "permission_denied", "message_keyword_not_root_cause"
        chain.append({"error_type": type(current).__name__, "error_code": code,
            "error_kind": kind, "error_category": category, "classification_basis": basis})
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    selected = next((row for row in chain if row["error_category"] != "sdk_or_runtime_error"),
                    next((row for row in chain if row["error_code"] is not None), chain[0]))
    return {**selected, "outer_error_type": type(exc).__name__, "causal_chain": chain}
