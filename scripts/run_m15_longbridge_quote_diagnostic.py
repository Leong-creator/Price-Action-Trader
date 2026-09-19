#!/usr/bin/env python3
"""Bounded project quote diagnostics; not an independent official example or trading runner."""
from __future__ import annotations

import argparse
import ctypes
import asyncio
import json
import math
import multiprocessing as mp
from multiprocessing.reduction import DupFd
import os
import queue
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_marketdata_diagnostics_lib import (
    PipelineDiagnostics, acquire_quote_owner_lock, append_diagnostic_snapshot,
    assert_no_legacy_quote_processes, safe_exception_evidence,
)
from scripts.m15_longbridge_sdk_runtime_lib import (
    DEFAULT_CONFIG_PATH, configured_symbols, load_config, read_client_id,
    sdk_object_to_dict,
)
from scripts.m15_longbridge_sdk_quote_transport_lib import (
    _subscription_symbols, reject_quote_endpoint_overrides, validate_single_subscription_symbols,
)


def validate_output_dir(path: Path, production_dir: Path) -> Path:
    path = path.expanduser().resolve()
    if path == production_dir.resolve() or production_dir.resolve() in path.parents:
        raise ValueError("diagnostics_must_not_write_production_output")
    if path == ROOT or ROOT in path.parents:
        raise ValueError("diagnostics_output_must_be_outside_worktree")
    if path.exists() and any(path.iterdir()):
        raise ValueError("diagnostics_output_must_be_new_or_empty")
    return path


async def collect(config: Any, symbols: list[str], duration: float, output: Path, sdk: Any,
                  stop: asyncio.Event) -> dict[str, Any]:
    diagnostics = PipelineDiagnostics()
    events: queue.Queue = queue.Queue(maxsize=250_000)
    errors: queue.Queue = queue.Queue(maxsize=1)
    started = time.monotonic()
    deadline = started + duration
    quote = None
    def callback(kind: str, symbol: str, event: Any) -> None:
        symbol = str(symbol).upper()
        diagnostics.record("raw_callback", symbol, kind)
        try:
            normalized = sdk_object_to_dict(event)
            diagnostics.record("normalized", symbol, kind)
            events.put_nowait((kind, symbol, normalized))
            diagnostics.record("enqueued", symbol, kind)
        except Exception as exc:
            diagnostics.record("callback_error", symbol, kind)
            try:
                errors.put_nowait(type(exc).__name__)
            except queue.Full:
                pass
    result = {"mode": "isolated_raw_sdk_diagnostic", "symbols": symbols,
              "started_at": datetime.now(UTC).isoformat(), "duration_limit_seconds": duration,
              "account_access": False, "order_access": False, "production_acceptance": False,
              "bar_formation": "not_assessed_raw_callback_probe", "status": "collecting",
              "subscription_batches": [], "sdk_quote_context_api": "QuoteContext",
              "sdk_config_source": "Config.from_oauth_defaults",
              "independent_official_example": False}
    active_batch: dict[str, Any] | None = None
    active_batch_started = 0.0
    def stage(name: str, **details: Any) -> None:
        result["stage"] = name
        phase = {"stage": name, "at": datetime.now(UTC).isoformat(),
                 "process_id": os.getpid(), **details}
        (output / "phase.json").write_text(json.dumps(phase) + "\n", encoding="utf-8")
        append_diagnostic_snapshot(output / "phases.jsonl", phase)
    try:
        reject_quote_endpoint_overrides()
        validate_single_subscription_symbols(symbols)
        stage("oauth_build")
        oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
        stage("context_create")
        sdk_config = sdk.Config.from_oauth(oauth)
        reject_quote_endpoint_overrides()  # Official Config may load dotenv overrides.
        quote = sdk.QuoteContext(sdk_config)
        quote.set_on_quote(lambda symbol, event: callback("quote", symbol, event))
        quote.set_on_trades(lambda symbol, event: callback("trade", symbol, event))
        sub_types = [sdk.SubType.Quote, sdk.SubType.Trade]
        # Keep the historical subscription_batches report shape; there is now exactly one request.
        active_batch = {"batch_offset": 0, "batch_size": len(symbols),
            "total_symbols": len(symbols), "batch_symbols": symbols,
            "sub_types": ["Quote", "Trade"], "request_timeout_seconds": None,
            "native_request_timeout": "sdk_default", "external_total_duration_seconds": duration}
        active_batch_started = time.monotonic()
        stage("subscribe", outcome="started", **active_batch)
        if time.monotonic() >= deadline:
            raise TimeoutError("diagnostic_total_deadline_exceeded")
        quote.subscribe(symbols, sub_types)
        if not errors.empty():
            raise RuntimeError("callback_failure:" + errors.get_nowait())
        outcome = {**active_batch, "outcome": "success",
                   "elapsed_seconds": round(time.monotonic() - active_batch_started, 3)}
        result["subscription_batches"].append(outcome)
        stage("subscribe", **outcome)
        active_batch = None
        stage("subscriptions_verify")
        actual = _subscription_symbols(quote.subscriptions(), tuple(sub_types))
        result["missing_subscriptions"] = sorted(set(symbols) - actual)
        if result["missing_subscriptions"]:
            raise RuntimeError("subscription_coverage_incomplete")
        result["subscription_coverage"] = f"{len(symbols)}/{len(symbols)}"
        stage("collecting_callbacks")
        last_audit = 0.0
        while time.monotonic() < deadline and not stop.is_set():
            if not errors.empty():
                raise RuntimeError("callback_failure:" + errors.get_nowait())
            for _ in range(10_000):
                try:
                    kind, symbol, _payload = events.get_nowait()
                except queue.Empty:
                    break
                diagnostics.record("dequeued", symbol, kind)
            if time.monotonic() - last_audit >= 1:
                snapshot = diagnostics.snapshot(drain_samples=True)
                snapshot["queue_depth"] = events.qsize()
                append_diagnostic_snapshot(output / "pipeline.jsonl", snapshot)
                last_audit = time.monotonic()
            await asyncio.sleep(0.05)
        result["status"] = "operator_stopped" if stop.is_set() else "duration_completed"
    except Exception as exc:
        safe_error = safe_exception_evidence(exc)
        category = safe_error["error_category"]
        result.update(status="failed", error_type=type(exc).__name__, error_category=category,
                      safe_error=safe_error)
        if active_batch is not None:
            outcome = {**active_batch, "outcome": "failed", "error_category": category,
                       "error_type": type(exc).__name__, "safe_error": safe_error,
                       "elapsed_seconds": round(time.monotonic() - active_batch_started, 3)}
            result["subscription_batches"].append(outcome)
            stage("subscribe", **outcome)
        else:
            stage(str(result.get("stage", "unknown")), outcome="failed", error_category=category,
                  error_type=type(exc).__name__, safe_error=safe_error)
    finally:
        quote = None  # SDK has no public close; process exit is the cleanup boundary.
        result.update(finished_at=datetime.now(UTC).isoformat(),
                      elapsed_seconds=round(time.monotonic() - started, 3),
                      diagnostics=diagnostics.snapshot(drain_samples=True),
                      native_transport_close="unobservable_until_process_exit")
        append_diagnostic_snapshot(output / "pipeline.jsonl", result["diagnostics"])
        (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def _supervised_entry(target: Any, args: tuple, shared_lock: Any, expected_parent: int) -> None:
    """Keep ownership through native teardown, including abrupt parent death on Linux."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise RuntimeError("diagnostic_parent_death_guard_unavailable")
    if os.getppid() != expected_parent:
        raise RuntimeError("diagnostic_parent_already_exited")
    descriptor = shared_lock.detach() if shared_lock is not None else None
    try:
        if os.getppid() != expected_parent:
            raise RuntimeError("diagnostic_parent_exited_during_lock_transfer")
        target(*args)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _raw_probe_worker(config_path: str, symbols: list[str], duration: float, output_dir: str) -> None:
    import longbridge.openapi as sdk
    config = load_config(config_path)
    async def run():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
        return await collect(config, symbols, duration, Path(output_dir), sdk, stop)
    asyncio.run(run())


async def supervise_raw(config_path: str, symbols: list[str], duration: float, output: Path,
                        stop: asyncio.Event, *, worker_target=_raw_probe_worker,
                        owner_fd: int | None = None) -> dict[str, Any]:
    """Wall-clock parent stays responsive even if the native factory blocks the child loop."""
    context = mp.get_context("spawn")
    child = context.Process(target=_supervised_entry,
        args=(worker_target, (config_path, symbols, duration, str(output)),
              DupFd(owner_fd) if owner_fd is not None else None, os.getpid()), daemon=True)
    started = time.monotonic()
    child.start()
    timed_out = False
    forced = False
    try:
        while child.is_alive() and not stop.is_set():
            if time.monotonic() - started > duration + 5:
                timed_out = True
                break
            await asyncio.sleep(0.05)
    finally:
        if child.is_alive():
            forced = True
            child.terminate()
            child.join(timeout=1)
        if child.is_alive():
            child.kill()
        child.join(timeout=5)
    try:
        result = json.loads((output / "summary.json").read_text())
    except (OSError, ValueError):
        result = {"mode": "isolated_raw_sdk_diagnostic", "account_access": False,
            "order_access": False, "production_acceptance": False}
    try:
        phase = json.loads((output / "phase.json").read_text())
    except (OSError, ValueError):
        phase = {"stage": "child_startup"}
    result.update(worker_pid=child.pid, worker_exitcode=child.exitcode,
        worker_process_exited=not child.is_alive(), worker_forced_cleanup=forced,
        elapsed_seconds=round(time.monotonic() - started, 3),
        finished_at=datetime.now(UTC).isoformat(), last_phase=phase)
    if timed_out:
        result.update(status="failed", reason="diagnostic_wall_clock_deadline_exceeded",
                      supervisor_safe_error=safe_exception_evidence(TimeoutError()))
    elif stop.is_set():
        result.update(status="operator_stopped")
    elif child.exitcode != 0 or "status" not in result:
        result.update(status="failed", reason="diagnostic_worker_exited_without_completion")
    if child.is_alive():
        result.update(status="failed", reason="diagnostic_worker_cleanup_failed")
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


class PipelineProbeEvidence:
    """Reuse production boundary rules without initializing its runtime/clients."""

    def __init__(self, config: Any) -> None:
        from scripts import run_m15_longbridge_sdk_runtime as rules
        self.rules = rules
        self.config = config
        self.stage_deadline = rules.QuoteWorkerStageDeadline(config, time.monotonic())
        self.session = None
        self.ready_since = 0.0
        self.last_progress = time.monotonic()
        self.last_push: dict[str, float] = {}
        self.last_push_at: dict[str, str] = {}
        self.last_source: dict[str, str] = {}
        self.first_push: dict[str, float] = {}
        self.last_live: dict[str, float] = {}
        self.latest_diagnostics: dict[str, Any] = {}
        self.worker_safe_error: dict[str, Any] = {}
        self.message_counts: dict[str, int] = {}
        self.bar_count = 0

    def consume(self, message: dict[str, Any], now: datetime) -> None:
        kind = str(message.get("kind", "unknown"))
        self.stage_deadline.consume(message, time.monotonic())
        self.message_counts[kind] = self.message_counts.get(kind, 0) + 1
        if kind == "error":
            self.worker_safe_error = dict(message.get("safe_error") or {})
            self.latest_diagnostics = message.get("pipeline_diagnostics") or self.latest_diagnostics
            raise RuntimeError("quote_worker_reported_failure")
        if kind == "ready":
            self.ready_since = time.monotonic()
            self.last_progress = self.ready_since
            self.session = self.rules.MarketSessionEvidence(self.config, now,
                complete_bar_open_not_before=self.rules.strict_event_datetime(
                    message.get("partial_bar_suppressed_until")))
        if kind == "heartbeat":
            self.last_progress = time.monotonic()
            self.latest_diagnostics = dict(message.get("pipeline_diagnostics") or {})
        activities = message.get("raw_reference_activity") or []
        if kind == "market_activity":
            activities = [message]
        for activity in activities:
            self.rules.apply_reference_market_activity_message(activity,
                last_push_by_symbol=self.last_push, last_push_at_by_symbol=self.last_push_at,
                last_push_source_by_symbol=self.last_source, first_live_push_by_symbol=self.first_push,
                last_live_push_by_symbol=self.last_live, now=now)
        if kind == "bars":
            if self.session is None:
                raise RuntimeError("bars_before_ready")
            rows = list(message.get("rows") or [])
            fresh = not self.rules.active_reference_quotes_are_stale(self.last_push,
                now_monotonic=time.monotonic(), maximum_silence_seconds=self.config.active_symbol_silence_seconds)
            disposition = self.session.accept(rows, now, reference_quotes_fresh=fresh)
            if disposition == "duplicate":
                raise RuntimeError("duplicate_boundary")
            if disposition == "accepted":
                self.bar_count += len(rows)

    def check_deadlines(self, now: datetime) -> None:
        overdue = self.stage_deadline.overdue(time.monotonic())
        if overdue:
            raise RuntimeError("sdk_stage_deadline_exceeded:" + str(overdue["phase"]))
        if self.session is None:
            return
        missing = self.session.advance(now)
        if missing:
            raise RuntimeError("realtime_bar_boundary_deadline_exceeded:" + missing)
        if self.stage_deadline.phase != "streaming":
            return
        monotonic = time.monotonic()
        if (self.rules.market_data_heartbeat_grace_elapsed(self.ready_since, monotonic,
                self.config.subscription_deadline_seconds)
            and self.rules.market_data_heartbeat_is_stale(self.last_progress, monotonic,
                self.config.market_data_heartbeat_deadline_seconds)):
            raise RuntimeError("market_data_heartbeat_deadline_exceeded")
        if (self.rules.configured_regular_session(self.config, now)
            and self.rules.regular_session_open_grace_elapsed(now, self.config.active_symbol_silence_seconds)
            and self.rules.market_data_heartbeat_grace_elapsed(self.ready_since, monotonic,
                self.config.active_symbol_silence_seconds)
            and self.rules.active_reference_quotes_are_stale(self.last_push,
                now_monotonic=monotonic, maximum_silence_seconds=self.config.active_symbol_silence_seconds)):
            raise RuntimeError("reference_market_data_stalled")


async def collect_pipeline(config: Any, config_path: str, duration: float, output: Path,
                           stop: asyncio.Event, *, owner_fd: int | None = None) -> dict[str, Any]:
    from scripts.m15_longbridge_sdk_quote_transport_lib import official_sdk_quote_worker
    context = mp.get_context("spawn")
    messages = context.Queue(maxsize=4096)
    child_stop = context.Event()
    stage_ack = context.Event()
    child = context.Process(target=_supervised_entry,
        args=(official_sdk_quote_worker, (config_path, messages, child_stop, (), str(output), stage_ack),
              DupFd(owner_fd) if owner_fd is not None else None, os.getpid()), daemon=True)
    evidence = PipelineProbeEvidence(config)
    result: dict[str, Any] = {"mode": "isolated_pipeline_diagnostic",
        "started_at": datetime.now(UTC).isoformat(), "duration_limit_seconds": duration,
        "account_access": False, "order_access": False, "strategy_access": False,
        "production_acceptance": False, "status": "collecting"}
    started = time.monotonic()
    child_started = False
    try:
        child.start()
        child_started = True
        result["worker_pid"] = child.pid
        while time.monotonic() - started < duration and not stop.is_set():
            # Drain first; enqueued reference activities must not be hidden by heartbeat checks.
            for _ in range(4096):
                try:
                    message = messages.get_nowait()
                except queue.Empty:
                    break
                # Raw worker errors may contain vendor details. Save only their type/category;
                # diagnostics include timing and stages, never credential-bearing strings.
                audit = dict(message)
                if audit.get("kind") == "error":
                    audit["reason"] = str(audit.get("reason", "")).split(":", 2)[:2]
                append_diagnostic_snapshot(output / "worker_messages.jsonl", audit)
                evidence.consume(message, datetime.now(UTC))
                if message.get("kind") == "sdk_stage":
                    # consume validated the phase and fixed its absolute deadline before allowing SDK I/O.
                    if evidence.stage_deadline.overdue(time.monotonic()):
                        raise RuntimeError("sdk_stage_deadline_exceeded_before_ack")
                    stage_ack.set()
            evidence.check_deadlines(datetime.now(UTC))
            if not child.is_alive():
                raise RuntimeError("quote_worker_exited")
            await asyncio.sleep(0.05)
        result["status"] = "operator_stopped" if stop.is_set() else "duration_completed"
    except Exception as exc:
        result.update(status="failed", error_type=type(exc).__name__,
                      reason=str(exc) if isinstance(exc, (RuntimeError, ValueError)) else "pipeline_probe_error",
                      safe_error=evidence.worker_safe_error or safe_exception_evidence(exc))
    finally:
        child_stop.set()
        forced = False
        if child_started:
            # A worker can be waiting on a full pipe. Continue draining while it exits.
            deadline = time.monotonic() + 5
            while child.is_alive() and time.monotonic() < deadline:
                try:
                    message = messages.get(timeout=0.05)
                    if message.get("kind") != "error":
                        append_diagnostic_snapshot(output / "shutdown_messages.jsonl", message)
                except queue.Empty:
                    pass
                child.join(timeout=0.01)
            if child.is_alive():
                forced = True
                child.terminate()
                child.join(timeout=5)
            if child.is_alive():
                child.kill()
                child.join(timeout=5)
            result.update(worker_exitcode=child.exitcode, worker_process_exited=not child.is_alive(),
                          worker_forced_cleanup=forced)
            if child.is_alive():
                result.update(status="failed", reason="quote_worker_cleanup_failed")
        messages.cancel_join_thread()
        messages.close()
        result.update(finished_at=datetime.now(UTC).isoformat(),
            elapsed_seconds=round(time.monotonic() - started, 3),
            message_counts=evidence.message_counts, realtime_bar_count=evidence.bar_count,
            complete_boundary_count=evidence.session.complete_boundary_count if evidence.session else 0,
            diagnostics=evidence.latest_diagnostics)
        (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--mode", choices=("raw-sdk", "pipeline"), default="raw-sdk")
    universe = parser.add_mutually_exclusive_group(required=True)
    universe.add_argument("--symbols", help="Comma separated symbols, e.g. SPY.US,QQQ.US")
    universe.add_argument("--production-universe", action="store_true")
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.duration_seconds) or not 1 <= args.duration_seconds <= 86400:
        parser.error("duration must be finite, between 1 and 86400 seconds")
    if args.mode == "pipeline" and not args.production_universe:
        parser.error("pipeline mode requires --production-universe to keep production bar semantics")
    config = load_config(args.config)
    symbols = list(configured_symbols(config)) if args.production_universe else list(dict.fromkeys(
        value.strip().upper() for value in args.symbols.split(",") if value.strip()))
    if not symbols or any(symbol not in configured_symbols(config) for symbol in symbols):
        parser.error("symbols must be in the configured production universe")
    output = validate_output_dir(args.output_dir, config.output_dir)
    from scripts.m15_sdk_provenance_lib import verify_environment
    verification = verify_environment(ROOT)
    if not verification["verified"]:
        print(json.dumps({"status": "blocked_environment_provenance", "issues": verification["issues"]}))
        return 2
    owner = acquire_quote_owner_lock()
    try:
        assert_no_legacy_quote_processes()
        owner.seek(0)
        owner.truncate()
        owner.write(f"{os.getpid()}\n")
        owner.flush()
        os.environ["LONGBRIDGE_PRINT_QUOTE_PACKAGES"] = "false"
        output.mkdir(parents=True, exist_ok=True)
        (output / "environment.json").write_text(json.dumps(verification, indent=2) + "\n")
        async def run():
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signum, stop.set)
            try:
                if args.mode == "pipeline":
                    return await collect_pipeline(config, str(Path(args.config).resolve()),
                                                  args.duration_seconds, output, stop, owner_fd=owner.fileno())
                return await supervise_raw(str(Path(args.config).resolve()), symbols,
                                           args.duration_seconds, output, stop, owner_fd=owner.fileno())
            finally:
                for signum in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(signum)
        result = asyncio.run(run())
        print(json.dumps({"status": result["status"], "output_dir": str(output),
                          "production_acceptance": False}))
        return 0 if result["status"] != "failed" else 4
    finally:
        owner.close()


if __name__ == "__main__":
    raise SystemExit(main())
