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
