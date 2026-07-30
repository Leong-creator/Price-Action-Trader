#!/usr/bin/env python3
"""Spawn-managed SDK account snapshot worker for the M15 runtime.

This module isolates persistent SDK account polling in a spawned subprocess so
the parent can terminate or kill the child when a single refresh hangs past a
bounded deadline.  The parent keeps the last trusted snapshot and preserves its
original timestamp across refresh failures.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import queue
import signal
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable


def to_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat().replace("+00:00", "Z")


def plain_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def close_spawn_queue(queue_out: Any) -> None:
    close = getattr(queue_out, "close", None)
    if callable(close):
        close()
    join_thread = getattr(queue_out, "join_thread", None)
    if callable(join_thread):
        join_thread()


@dataclass(slots=True)
class AccountWorkerConfig:
    refresh_total_deadline_seconds: float = 5.0
    startup_total_deadline_seconds: float = 1.0
    stop_timeout_seconds: float = 1.0
    terminate_timeout_seconds: float = 0.5
    kill_timeout_seconds: float = 0.5
    circuit_breaker_consecutive_timeouts: int = 2
    circuit_recovery_consecutive_successes: int = 2
    circuit_retry_cooldown_seconds: float = 0.0


def _worker_main(
    command_queue: Any,
    response_queue: Any,
    provider_factory: Callable[[], Any],
    generation: int,
) -> None:
    provider = provider_factory()
    try:
        while True:
            command = command_queue.get()
            kind = str(command.get("kind") or "")
            request_id = str(command.get("request_id") or "")
            if kind == "refresh":
                started = time.monotonic()
                try:
                    snapshot = provider.refresh()
                    response_queue.put(
                        {
                            "kind": "refresh_result",
                            "request_id": request_id,
                            "generation": generation,
                            "pid": os.getpid(),
                            "elapsed_seconds": max(0.0, time.monotonic() - started),
                            "snapshot": plain_copy(snapshot),
                            "refreshed_at": to_iso(),
                        }
                    )
                except BaseException as exc:  # pragma: no cover - defensive path
                    response_queue.put(
                        {
                            "kind": "refresh_error",
                            "request_id": request_id,
                            "generation": generation,
                            "pid": os.getpid(),
                            "elapsed_seconds": max(0.0, time.monotonic() - started),
                            "error": f"{type(exc).__name__}:{exc}",
                            "refreshed_at": to_iso(),
                        }
                    )
            elif kind == "stop":
                break
    finally:
        stop = getattr(provider, "stop", None)
        if callable(stop):
            stop()


class SpawnAccountSnapshotWorker:
    """Manage a persistent spawned worker that refreshes SDK account snapshots."""

    def __init__(
        self,
        provider_factory: Callable[[], Any],
        *,
        config: AccountWorkerConfig | None = None,
        trust_predicate: Callable[[dict[str, Any]], bool] | None = None,
        mp_context: Any | None = None,
    ) -> None:
        self._provider_factory = provider_factory
        self._config = config or AccountWorkerConfig()
        self._trust_predicate = trust_predicate or self._default_trust_predicate
        self._ctx = mp_context or mp.get_context("spawn")
        self._process: Any = None
        self._command_queue: Any = None
        self._response_queue: Any = None
        self._worker_generation = 0
        self._restart_count = 0
        self._consecutive_timeouts = 0
        self._consecutive_untrusted_results = 0
        self._consecutive_successes = 0
        self._circuit_open = False
        self._circuit_opened_at_monotonic = 0.0
        self._circuit_reason = ""
        self._last_refresh_elapsed_seconds = 0.0
        self._last_refresh_timeout_seconds = self._config.refresh_total_deadline_seconds
        self._last_refresh_timed_out = False
        self._last_refresh_status = "not_started"
        self._last_refresh_error = ""
        self._last_restart_reason = ""
        self._last_trusted_snapshot: dict[str, Any] | None = None
        self._worker_needs_startup_grace = False
        self._published_snapshot: dict[str, Any] = self._base_snapshot(status="not_started")

    @staticmethod
    def _default_trust_predicate(snapshot: dict[str, Any]) -> bool:
        if "trusted" in snapshot:
            return bool(snapshot.get("trusted"))
        if snapshot.get("paper_account_verified") is True and not snapshot.get("critical_errors"):
            return True
        return not snapshot.get("critical_errors") and not snapshot.get("worker_error")

    def start(self) -> dict[str, Any]:
        if self._process is not None and self._process.is_alive():
            return self.request_snapshot()
        self._start_worker(reason="manual_start")
        self._last_refresh_status = "worker_started"
        self._publish_runtime_state({})
        return self.request_snapshot()

    def stop(self) -> dict[str, Any]:
        summary = self._stop_worker(graceful=True, reason="manual_stop")
        self._last_refresh_status = "worker_stopped"
        self._publish_runtime_state(
            {
                "worker_running": False,
                "stop_summary": summary,
            }
        )
        return summary

    def refresh(
        self,
        *,
        total_deadline_seconds: float | None = None,
        _allow_restart_retry: bool = True,
    ) -> dict[str, Any]:
        deadline_seconds = (
            float(total_deadline_seconds)
            if total_deadline_seconds is not None
            else float(self._config.refresh_total_deadline_seconds)
        )
        if not self._worker_available_for_refresh():
            snapshot = self._publish_failure_snapshot(
                status="circuit_open_skip",
                error=self._circuit_reason or "refresh_circuit_open",
                refresh_elapsed_seconds=0.0,
                timed_out=False,
            )
            return plain_copy(snapshot)
        if self._process is None or not self._process.is_alive():
            self._start_worker(reason="refresh_start")
        if self._worker_needs_startup_grace and self._config.startup_total_deadline_seconds > 0:
            deadline_seconds = max(deadline_seconds, float(self._config.startup_total_deadline_seconds))
        self._last_refresh_timeout_seconds = max(0.001, deadline_seconds)
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        assert self._command_queue is not None
        assert self._response_queue is not None
        self._command_queue.put({"kind": "refresh", "request_id": request_id})
        while True:
            remaining = deadline_seconds - (time.monotonic() - started)
            if remaining <= 0:
                result = self._handle_refresh_timeout(
                    refresh_elapsed_seconds=max(0.0, time.monotonic() - started)
                )
                if _allow_restart_retry and not self._circuit_open:
                    retry = self.refresh(
                        total_deadline_seconds=total_deadline_seconds,
                        _allow_restart_retry=False,
                    )
                    retry["worker_retried_after_restart"] = True
                    return plain_copy(retry)
                return plain_copy(result)
            try:
                response = self._response_queue.get(timeout=min(remaining, 0.05))
            except queue.Empty:
                if self._process is not None and not self._process.is_alive():
                    result = self._handle_refresh_timeout(
                        refresh_elapsed_seconds=max(0.0, time.monotonic() - started)
                    )
                    if _allow_restart_retry and not self._circuit_open:
                        retry = self.refresh(
                            total_deadline_seconds=total_deadline_seconds,
                            _allow_restart_retry=False,
                        )
                        retry["worker_retried_after_restart"] = True
                        return plain_copy(retry)
                    return plain_copy(result)
                continue
            if str(response.get("request_id") or "") != request_id:
                continue
            elapsed = max(0.0, float(response.get("elapsed_seconds") or 0.0))
            if response.get("kind") == "refresh_result":
                self._worker_needs_startup_grace = False
                return plain_copy(self._handle_refresh_success(response, elapsed))
            error = str(response.get("error") or "worker_refresh_failed")
            self._worker_needs_startup_grace = False
            return plain_copy(self._handle_refresh_error(response, elapsed, error))

    def request_snapshot(self) -> dict[str, Any]:
        return plain_copy(self._published_snapshot)

    def _worker_available_for_refresh(self) -> bool:
        if not self._circuit_open:
            return True
        cooldown = max(0.0, float(self._config.circuit_retry_cooldown_seconds))
        return (time.monotonic() - self._circuit_opened_at_monotonic) >= cooldown

    def _start_worker(self, *, reason: str) -> None:
        self._worker_generation += 1
        self._last_restart_reason = reason
        self._command_queue = self._ctx.Queue()
        self._response_queue = self._ctx.Queue()
        self._process = self._ctx.Process(
            target=_worker_main,
            args=(self._command_queue, self._response_queue, self._provider_factory, self._worker_generation),
            daemon=True,
        )
        self._process.start()
        self._worker_needs_startup_grace = True
        if self._worker_generation > 1:
            self._restart_count += 1

    def _stop_worker(self, *, graceful: bool, reason: str) -> dict[str, Any]:
        process = self._process
        command_queue = self._command_queue
        response_queue = self._response_queue
        summary = {
            "worker_generation": self._worker_generation,
            "worker_pid": process.pid if process is not None else None,
            "requested_graceful": graceful,
            "terminate_sent": False,
            "kill_sent": False,
            "stopped": True,
            "reason": reason,
        }
        if process is not None:
            if graceful and process.is_alive() and command_queue is not None:
                try:
                    command_queue.put({"kind": "stop", "request_id": uuid.uuid4().hex})
                except Exception:
                    pass
                process.join(timeout=self._config.stop_timeout_seconds)
            if process.is_alive():
                summary["terminate_sent"] = True
                process.terminate()
                process.join(timeout=self._config.terminate_timeout_seconds)
            if process.is_alive():
                summary["kill_sent"] = True
                kill = getattr(process, "kill", None)
                if callable(kill):
                    kill()
                    process.join(timeout=self._config.kill_timeout_seconds)
            summary["stopped"] = not process.is_alive()
        if command_queue is not None:
            close_spawn_queue(command_queue)
        if response_queue is not None:
            close_spawn_queue(response_queue)
        self._process = None
        self._command_queue = None
        self._response_queue = None
        return summary

    def _handle_refresh_success(self, response: dict[str, Any], elapsed: float) -> dict[str, Any]:
        snapshot = plain_copy(response.get("snapshot") or {})
        if not self._trust_predicate(snapshot):
            return self._handle_untrusted_snapshot(snapshot, elapsed)
        self._consecutive_timeouts = 0
        self._consecutive_untrusted_results = 0
        self._last_refresh_elapsed_seconds = elapsed
        self._last_refresh_timed_out = False
        self._last_refresh_error = ""
        if self._circuit_open:
            self._consecutive_successes += 1
            if self._consecutive_successes >= self._config.circuit_recovery_consecutive_successes:
                self._circuit_open = False
                self._circuit_reason = ""
                self._last_refresh_status = "healthy_circuit_recovered"
            else:
                self._last_refresh_status = "healthy_circuit_probe"
        else:
            self._consecutive_successes = 0
            self._last_refresh_status = "healthy"
        self._last_trusted_snapshot = plain_copy(snapshot)
        self._publish_runtime_state(snapshot)
        return self._published_snapshot

    def _handle_untrusted_snapshot(
        self,
        snapshot: dict[str, Any],
        elapsed: float,
    ) -> dict[str, Any]:
        errors = snapshot.get("critical_errors") or snapshot.get("worker_error") or [
            "account_snapshot_failed_trust_check"
        ]
        if isinstance(errors, list):
            error = ";".join(str(item) for item in errors if str(item))
        else:
            error = str(errors)
        self._consecutive_untrusted_results += 1
        self._consecutive_timeouts = 0
        self._consecutive_successes = 0
        self._last_refresh_elapsed_seconds = elapsed
        self._last_refresh_timed_out = False
        self._last_refresh_error = error
        self._last_refresh_status = "untrusted_snapshot_preserved_last_good"
        restart_summary = self._stop_worker(
            graceful=False,
            reason="untrusted_snapshot",
        )
        if (
            self._consecutive_untrusted_results
            >= self._config.circuit_breaker_consecutive_timeouts
        ):
            self._circuit_open = True
            self._circuit_opened_at_monotonic = time.monotonic()
            self._circuit_reason = (
                "untrusted_snapshot_circuit_open_after_"
                f"{self._consecutive_untrusted_results}_consecutive_results"
            )
        else:
            self._start_worker(reason="untrusted_snapshot_restart")
        return self._publish_failure_snapshot(
            status=(
                "untrusted_snapshot_circuit_open"
                if self._circuit_open
                else "untrusted_snapshot_preserved_last_good"
            ),
            error=self._circuit_reason if self._circuit_open else error,
            refresh_elapsed_seconds=elapsed,
            timed_out=False,
            extra={
                "worker_stop_summary": restart_summary,
                "rejected_snapshot_generated_at": snapshot.get("generated_at"),
                "rejected_snapshot_critical_errors": snapshot.get("critical_errors") or [],
            },
        )

    def _handle_refresh_error(self, response: dict[str, Any], elapsed: float, error: str) -> dict[str, Any]:
        self._last_refresh_elapsed_seconds = elapsed
        self._last_refresh_timed_out = False
        self._last_refresh_error = error
        self._last_refresh_status = "worker_error"
        self._consecutive_successes = 0
        self._publish_failure_snapshot(
            status="worker_error",
            error=error,
            refresh_elapsed_seconds=elapsed,
            timed_out=False,
        )
        restart_summary = self._stop_worker(graceful=False, reason="worker_error")
        if not self._circuit_open:
            self._start_worker(reason="worker_error_restart")
            self._publish_runtime_state(
                {
                    "worker_restart_after_error": True,
                    "worker_stop_summary": restart_summary,
                }
            )
        return self._published_snapshot

    def _handle_refresh_timeout(self, *, refresh_elapsed_seconds: float) -> dict[str, Any]:
        self._consecutive_timeouts += 1
        self._consecutive_successes = 0
        self._last_refresh_elapsed_seconds = refresh_elapsed_seconds
        self._last_refresh_timed_out = True
        self._last_refresh_error = "refresh_timeout"
        self._last_refresh_status = "timeout"
        restart_summary = self._stop_worker(graceful=False, reason="refresh_timeout")
        if self._consecutive_timeouts >= self._config.circuit_breaker_consecutive_timeouts:
            self._circuit_open = True
            self._circuit_opened_at_monotonic = time.monotonic()
            self._circuit_reason = (
                f"refresh_timeout_circuit_open_after_{self._consecutive_timeouts}_consecutive_timeouts"
            )
        else:
            self._start_worker(reason="refresh_timeout_restart")
        self._publish_failure_snapshot(
            status=(
                "timeout_circuit_open"
                if self._circuit_open
                else "timeout_restarted_worker"
            ),
            error=self._circuit_reason if self._circuit_open else "refresh_timeout",
            refresh_elapsed_seconds=refresh_elapsed_seconds,
            timed_out=True,
            extra={
                "worker_stop_summary": restart_summary,
            },
        )
        return self._published_snapshot

    def _base_snapshot(self, *, status: str) -> dict[str, Any]:
        return {
            "schema_version": "m15.longbridge-sdk-account-worker.v1",
            "generated_at": to_iso(),
            "worker_refresh_status": status,
            "worker_generation": self._worker_generation,
            "worker_pid": None,
            "worker_running": False,
            "worker_refresh_elapsed_seconds": 0.0,
            "worker_refresh_timeout_seconds": float(self._config.refresh_total_deadline_seconds),
            "worker_last_refresh_timed_out": False,
            "worker_restart_count": 0,
            "worker_last_restart_reason": "",
            "worker_circuit_open": False,
            "worker_circuit_reason": "",
            "worker_consecutive_timeouts": 0,
            "worker_consecutive_successes": 0,
            "last_trusted_generated_at": None,
            "worker_error": "",
        }

    def _publish_failure_snapshot(
        self,
        *,
        status: str,
        error: str,
        refresh_elapsed_seconds: float,
        timed_out: bool,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._last_trusted_snapshot is not None:
            snapshot = plain_copy(self._last_trusted_snapshot)
        else:
            snapshot = self._base_snapshot(status=status)
        snapshot["worker_error"] = error
        snapshot["last_trusted_generated_at"] = (
            self._last_trusted_snapshot.get("generated_at")
            if self._last_trusted_snapshot is not None
            else None
        )
        snapshot["last_failed_refresh_at"] = to_iso()
        self._publish_runtime_state(
            snapshot,
            override_status=status,
            refresh_elapsed_seconds=refresh_elapsed_seconds,
            timed_out=timed_out,
            extra=extra,
        )
        return self._published_snapshot

    def _publish_runtime_state(
        self,
        snapshot: dict[str, Any],
        *,
        override_status: str | None = None,
        refresh_elapsed_seconds: float | None = None,
        timed_out: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = plain_copy(snapshot)
        payload["schema_version"] = "m15.longbridge-sdk-account-worker.v1"
        payload["worker_refresh_status"] = override_status or self._last_refresh_status
        payload["worker_generation"] = self._worker_generation
        payload["worker_pid"] = self._process.pid if self._process is not None else None
        payload["worker_running"] = bool(self._process is not None and self._process.is_alive())
        payload["worker_refresh_elapsed_seconds"] = (
            self._last_refresh_elapsed_seconds
            if refresh_elapsed_seconds is None
            else refresh_elapsed_seconds
        )
        payload["worker_refresh_timeout_seconds"] = self._last_refresh_timeout_seconds
        payload["worker_last_refresh_timed_out"] = (
            self._last_refresh_timed_out if timed_out is None else timed_out
        )
        payload["worker_restart_count"] = self._restart_count
        payload["worker_last_restart_reason"] = self._last_restart_reason
        payload["worker_circuit_open"] = self._circuit_open
        payload["worker_circuit_reason"] = self._circuit_reason
        payload["worker_consecutive_timeouts"] = self._consecutive_timeouts
        payload["worker_consecutive_untrusted_results"] = (
            self._consecutive_untrusted_results
        )
        payload["worker_consecutive_successes"] = self._consecutive_successes
        payload["last_trusted_generated_at"] = (
            self._last_trusted_snapshot.get("generated_at")
            if self._last_trusted_snapshot is not None
            else None
        )
        payload.setdefault("worker_error", self._last_refresh_error)
        if extra:
            payload.update(plain_copy(extra))
        self._published_snapshot = payload
