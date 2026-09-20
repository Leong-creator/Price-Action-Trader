#!/usr/bin/env python3
"""Bounded project quote diagnostics; not an independent official example or trading runner."""
from __future__ import annotations

import argparse
import ctypes
from contextlib import contextmanager
from dataclasses import replace
from collections import Counter
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


@contextmanager
def quote_only_sdk_guard(sdk: Any):
    """Account/order context constructors are forbidden in this diagnostic process."""
    names = ("TradeContext", "AsyncTradeContext", "PortfolioContext", "AsyncPortfolioContext")
    saved = {name: getattr(sdk, name) for name in names if hasattr(sdk, name)}
    def forbidden(*args, **kwargs):
        raise RuntimeError("diagnostic_account_or_order_access_forbidden")
    try:
        for name in saved:
            setattr(sdk, name, forbidden)
        yield
    finally:
        for name, value in saved.items():
            setattr(sdk, name, value)


def _quote_only_pipeline_worker(*args):
    import longbridge.openapi as sdk
    from scripts.m15_longbridge_sdk_quote_transport_lib import official_sdk_quote_worker
    with quote_only_sdk_guard(sdk):
        official_sdk_quote_worker(*args)


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


class DiagnosticStrategyPipeline:
    """Real quote-state helpers and signal router, without account or execution flow."""

    def __init__(self, config: Any, rules: Any, output: Path) -> None:
        from scripts import m15_longbridge_realtime_signal_router_lib as router
        self.config, self.rules, self.router = config, rules, router
        self.output = output / "strategy"
        original = router.load_config(config.router_config_path)
        self.router_config = replace(original, output_dir=self.output,
            market_events_path=self.output / "market_events.jsonl",
            signal_events_path=self.output / "signal_events.jsonl")
        self.context = rules.MarketEventContext(maximum_rows=len(configured_symbols(config)) * config.daily_context_bars + 4096)
        self.quote_state: dict[str, dict[str, Any]] = {}
        self.daily_rows: list[dict[str, Any]] = []
        self.daily_source = "not_received"
        self.signal_ids: set[str] = set()
        self.evaluations = 0
        self.last_result: dict[str, Any] = {}

    def consume_inputs(self, message: dict[str, Any], now: datetime, evidence: Any) -> None:
        if message.get("kind") == "daily_context":
            self.daily_rows = list(message.get("rows") or [])
            self.daily_source = str(message.get("source_mode") or "unknown")
        if message.get("kind") in {"quote_state", "quote_state_batch"}:
            self.rules.apply_quote_state_worker_message(message,
                live_quote_session_state=self.quote_state,
                last_push_by_symbol=evidence.last_push, last_push_at_by_symbol=evidence.last_push_at,
                last_push_source_by_symbol=evidence.last_source, first_live_push_by_symbol=evidence.first_push,
                last_live_push_by_symbol=evidence.last_live, now=now)

    def runtime_context_report(self, market_rows: list[dict[str, Any]], emitted: list[dict[str, Any]]) -> list[dict[str, Any]]:
        reports = []
        for runtime_id in self.router_config.allowed_runtime_ids:
            contract_path = self.router_config.strategy_contracts_dir / (runtime_id + ".json")
            contract = json.loads(contract_path.read_text())
            timeframe = str(contract.get("timeframe") or "")
            rules = contract.get("entry_rules") or {}
            declared = max((int(rules[key]) for key in ("range_lookback_bars", "lookback_bars", "opening_range_bars")
                            if type(rules.get(key)) is int), default=0)
            counts = Counter(str(row.get("symbol") or "").upper().removesuffix(".US")
                             for row in market_rows if row.get("timeframe") == timeframe)
            expected = [symbol.removesuffix(".US") for symbol in configured_symbols(self.config)]
            insufficient = [symbol for symbol in expected if counts[symbol] < max(1, declared)]
            signals = sum(row.get("runtime_id") == runtime_id for row in emitted)
            reports.append({"runtime_id": runtime_id, "timeframe": timeframe,
                "declared_lookback_bars": declared or None,
                "observed_rows_min": min((counts[symbol] for symbol in expected), default=0),
                "symbols_missing_declared_context": insufficient,
                "input_status": "insufficient_declared_context" if insufficient else "declared_count_present_other_conditions_still_apply",
                "decision": "signal_observed_not_dispatched" if signals else "original_router_no_qualified_signal",
                "signal_count": signals, "full_acceptance": False})
        return reports

    def evaluate(self, rows: list[dict[str, Any]], now: datetime) -> None:
        rules = self.rules
        annotated = rules.attach_next_bar_first_quotes(rows, self.quote_state, now=now)
        fresh = rules.fresh_market_events(annotated, self.config.maximum_source_delivery_age_ms, now=now)
        if any(not row.get("market_data_blocked_reason") and row not in fresh for row in annotated):
            raise RuntimeError("diagnostic_stale_strategy_bar")
        new_rows = self.context.append(rules.trading_market_events(self.config, fresh))
        active_ids = {str(row.get("event_id") or "") for row in new_rows}
        live_daily = rules.build_live_daily_confirmation_rows(self.context.rows(), generated_at=now,
            live_quote_session_state=self.quote_state, active_five_minute_event_ids=active_ids)
        active_ids.update(str(row.get("event_id") or "") for row in live_daily)
        historical = rules.historical_daily_context_before_session(self.daily_rows, generated_at=now)
        market_rows = historical + self.context.rows() + live_daily
        emitted: list[dict[str, Any]] = []
        summary = self.router.run_realtime_signal_router(self.router_config, generated_at=now.isoformat(),
            market_events_override=market_rows, active_market_event_ids=active_ids,
            emitted_signal_events=emitted, existing_signal_ids_override=self.signal_ids)
        self.signal_ids.update(str(row.get("signal_id") or "") for row in emitted)
        self.evaluations += 1
        counts = Counter((str(row.get("symbol") or ""), str(row.get("timeframe") or "")) for row in market_rows)
        self.last_result = {"evaluated_at": now.isoformat(), "boundary_times": sorted({str(row.get("event_time") or "") for row in rows}),
            "historical_daily_rows": len(historical), "live_daily_rows": len(live_daily),
            "five_minute_rows": len(self.context.rows()), "quote_state_symbol_count": len(self.quote_state),
            "active_event_count": len(active_ids), "signal_count": len(emitted),
            "allowed_runtime_ids": list(self.router_config.allowed_runtime_ids),
            "blocked_by_reason": summary.get("blocked_by_reason", {}),
            "runtime_context": self.runtime_context_report(market_rows, emitted),
            "short_detector_diagnostics": summary.get("paper_short_diagnostics", {}),
            "decision": "signals_observed_not_dispatched" if emitted else "original_router_returned_no_qualified_signal",
            "input_rows_by_symbol_timeframe": {symbol+":"+period: count for (symbol, period), count in sorted(counts.items())},
            "context_limit": "only_observed_intraday_bars_no_backfilled_opening_range",
            "full_strategy_acceptance": False, "order_access": False}
        append_diagnostic_snapshot(self.output / "boundary_decisions.jsonl", self.last_result)
        append_diagnostic_snapshot(self.output / "router_history.jsonl", summary)

    def summary(self) -> dict[str, Any]:
        target_count = len(configured_symbols(self.config))
        complete_inputs = (len(self.quote_state) >= target_count and
                           len(self.daily_rows) == target_count * self.config.daily_context_bars)
        return {"strategy_evaluation_count": self.evaluations,
            "quote_state_symbol_count": len(self.quote_state), "daily_context_row_count": len(self.daily_rows),
            "daily_context_source": self.daily_source,
            "strategy_input_coverage_observed": complete_inputs,
            "strategy_status": "judgments_recorded_partial_intraday_context" if self.evaluations else "not_evaluated_no_accepted_boundary",
            "strategy_full_acceptance": False,
            "strategy_contract_inputs_status": (
                "insufficient_declared_context" if any(row["input_status"] == "insufficient_declared_context"
                    for row in self.last_result.get("runtime_context", []))
                else "full_contract_inputs_not_proven_by_short_window"),
            "last_strategy_result": self.last_result}


class PipelineProbeEvidence:
    """Reuse production boundary rules without initializing its runtime/clients."""

    def __init__(self, config: Any, output: Path | None = None) -> None:
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
        self.strategy = DiagnosticStrategyPipeline(config, rules, output) if output is not None else None

    def consume(self, message: dict[str, Any], now: datetime) -> None:
        kind = str(message.get("kind", "unknown"))
        self.stage_deadline.consume(message, time.monotonic())
        self.message_counts[kind] = self.message_counts.get(kind, 0) + 1
        if self.strategy is not None:
            self.strategy.consume_inputs(message, now, self)
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
                if self.strategy is not None:
                    self.strategy.evaluate(rows, now)

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


async def _collect_pipeline(config: Any, config_path: str, duration: float, output: Path,
                           stop: asyncio.Event, *, owner_fd: int | None = None,
                           window_end: datetime | None = None) -> dict[str, Any]:
    from scripts.m15_longbridge_sdk_quote_transport_lib import official_sdk_quote_worker
    context = mp.get_context("spawn")
    messages = context.Queue(maxsize=4096)
    child_stop = context.Event()
    stage_ack = context.Event()
    child = context.Process(target=_supervised_entry,
        args=(_quote_only_pipeline_worker, (config_path, messages, child_stop, (), str(output), stage_ack),
              DupFd(owner_fd) if owner_fd is not None else None, os.getpid()), daemon=True)
    evidence = PipelineProbeEvidence(config, output)
    result: dict[str, Any] = {"mode": "isolated_pipeline_diagnostic",
        "started_at": datetime.now(UTC).isoformat(), "duration_limit_seconds": duration,
        "account_access": False, "order_access": False, "strategy_access": True,
        "production_acceptance": False, "status": "collecting"}
    started = time.monotonic()
    deadline = started + min(duration, max(0, (window_end - datetime.now(UTC)).total_seconds())) if window_end else started + duration
    child_started = False
    try:
        if window_end is not None:
            validate_market_window("2026-09-21T13:50:00Z", "2026-09-21T13:51:00Z", window_end.isoformat())
        child.start()
        child_started = True
        result["worker_pid"] = child.pid
        while time.monotonic() < deadline and not stop.is_set():
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
            diagnostics=evidence.latest_diagnostics,
            window_end_utc=window_end.isoformat() if window_end else None,
            **(evidence.strategy.summary() if evidence.strategy else {}))
        result.update(pipeline_observation_flags(result, evidence))
        if result["status"] == "duration_completed" and not result["bounded_pipeline_observed"]:
            result.update(status="incomplete", reason="insufficient_observed_pipeline_inputs_or_boundaries")
        (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def pipeline_observation_flags(result: dict[str, Any], evidence: Any) -> dict[str, Any]:
    stages = evidence.latest_diagnostics.get("stages", {})
    def count(stage, kind):
        return sum(int(row.get("count", 0)) for row in stages.values()
                   if row.get("stage") == stage and row.get("kind") == kind)
    raw_trades, dequeued_trades = count("raw_callback", "trade"), count("dequeued", "trade")
    traded_bars = evidence.session.realtime_tradable_bar_count if evidence.session else 0
    carried_bars = evidence.session.no_trade_carry_forward_count if evidence.session else 0
    observed = bool(result["status"] == "duration_completed"
        and result.get("worker_process_exited") and result.get("worker_exitcode") == 0
        and not result.get("worker_forced_cleanup")
        and result.get("strategy_input_coverage_observed") and evidence.bar_count
        and result.get("strategy_evaluation_count") and raw_trades > 0 and dequeued_trades > 0 and traded_bars > 0)
    return {"bounded_pipeline_observed": observed, "raw_quote_callback_count": count("raw_callback", "quote"),
        "raw_trade_callback_count": raw_trades, "dequeued_trade_count": dequeued_trades,
        "traded_bar_count": traded_bars, "no_trade_carry_forward_bar_count": carried_bars,
        "full_session_acceptance": False}


async def collect_pipeline(config: Any, config_path: str, duration: float, output: Path,
                           stop: asyncio.Event, *, owner_fd: int | None = None,
                           window_end: datetime | None = None) -> dict[str, Any]:
    import longbridge.openapi as sdk
    with quote_only_sdk_guard(sdk):
        return await _collect_pipeline(config, config_path, duration, output, stop,
                                       owner_fd=owner_fd, window_end=window_end)


def validate_pipeline_paths(config: Any, output: Path) -> None:
    # Diagnostic config must explicitly relocate every potentially mutable runtime path.
    paths = (config.output_dir, config.market_events_path, config.runtime_status_path,
             config.readonly_gate_path, config.daily_context_path)
    for path in paths:
        resolved = Path(path).expanduser().resolve()
        if resolved == ROOT or ROOT in resolved.parents:
            raise ValueError("pipeline_config_must_use_external_paths")
    if config.paper_order_dispatch_enabled:
        raise ValueError("pipeline_config_must_disable_dispatch")


def validate_market_window(start: str | None, latest: str | None, end: str | None, *, now: datetime | None = None) -> datetime | None:
    if not any((start, latest, end)):
        return None
    if not all((start, latest, end)):
        raise ValueError("all_market_window_fields_required")
    values = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (start, latest, end)]
    if any(value.tzinfo is None for value in values):
        raise ValueError("market_window_timezone_required")
    beginning, latest_start, ending = values
    expected = [datetime(2026, 9, 21, 13, minute, tzinfo=UTC) for minute in (50, 51)] + [datetime(2026, 9, 21, 14, 20, tzinfo=UTC)]
    if values != expected or not beginning <= (now or datetime.now(UTC)) <= latest_start:
        raise ValueError("outside_authorized_market_window")
    return ending


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--quote-lock-fd", type=int)
    parser.add_argument("--window-start-utc")
    parser.add_argument("--latest-start-utc")
    parser.add_argument("--window-end-utc")
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
    window_end = validate_market_window(args.window_start_utc, args.latest_start_utc, args.window_end_utc)
    config = load_config(args.config)
    symbols = list(configured_symbols(config)) if args.production_universe else list(dict.fromkeys(
        value.strip().upper() for value in args.symbols.split(",") if value.strip()))
    if not symbols or any(symbol not in configured_symbols(config) for symbol in symbols):
        parser.error("symbols must be in the configured production universe")
    output = validate_output_dir(args.output_dir, config.output_dir)
    if args.mode == "pipeline":
        validate_pipeline_paths(config, output)
    elif window_end is not None:
        parser.error("scheduled_market_window_requires_pipeline_mode")
    from scripts.m15_sdk_provenance_lib import verify_environment
    verification = verify_environment(ROOT)
    if not verification["verified"]:
        print(json.dumps({"status": "blocked_environment_provenance", "issues": verification["issues"]}))
        return 2
    owner = acquire_quote_owner_lock(inherited_fd=args.quote_lock_fd)
    try:
        assert_no_legacy_quote_processes()
        validate_market_window(args.window_start_utc, args.latest_start_utc, args.window_end_utc)
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
                                                  args.duration_seconds, output, stop, owner_fd=owner.fileno(), window_end=window_end)
                return await supervise_raw(str(Path(args.config).resolve()), symbols,
                                           args.duration_seconds, output, stop, owner_fd=owner.fileno())
            finally:
                for signum in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(signum)
        result = asyncio.run(run())
        print(json.dumps({"status": result["status"], "output_dir": str(output),
                          "production_acceptance": False}))
        return 0 if result["status"] == "duration_completed" else 4
    finally:
        owner.close()


if __name__ == "__main__":
    raise SystemExit(main())
