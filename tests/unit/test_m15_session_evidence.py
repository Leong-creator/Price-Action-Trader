from __future__ import annotations

from dataclasses import replace
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import queue
import unittest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from scripts import run_m15_longbridge_sdk_runtime as runtime


NY = ZoneInfo("America/New_York")


def at(day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, second, tzinfo=NY)


def bars(close: datetime, symbols: tuple[str, ...], *, carry: bool = False) -> list[dict]:
    return [
        {
            "symbol": symbol.removesuffix(".US"),
            "event_id": f"offline|{symbol}|{close.isoformat()}",
            "timeframe": "5m",
            "event_time": runtime.to_iso(close),
            "bar_open_at": runtime.to_iso(close - timedelta(minutes=5)),
            "bar_close_at": runtime.to_iso(close),
            "received_at": runtime.to_iso(close + timedelta(seconds=1)),
            "bar_final": True,
            "source_mode": "official_sdk_no_trade_carry_forward" if carry else "official_sdk_push",
            "market_data_blocked_reason": "no_trade_carry_forward" if carry else "",
            "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1",
        }
        for symbol in symbols
    ]


def audit_success(rows: list[dict]) -> dict:
    return {"audit_status": "written", "audit_event_count": len(rows),
            "fresh_event_count": len(rows), "stale_event_count": 0,
            "stale_tradable_event_count": 0}


class CallbackEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = dict(
            last_push_by_symbol={}, last_push_at_by_symbol={},
            last_push_source_by_symbol={}, first_live_push_by_symbol={},
            last_live_push_by_symbol={},
        )

    def activity(self, received: str, now: datetime, tick: float) -> None:
        with patch.object(runtime, "datetime") as clock:
            clock.now.return_value = now
            clock.fromisoformat.side_effect = datetime.fromisoformat
            runtime.apply_reference_market_activity_message(
                {"symbol": "SPY.US", "received_at": received,
                 "source_mode": "official_sdk_raw_quote_callback"},
                now_monotonic=tick, **self.state,
            )

    def test_replayed_callback_does_not_renew_freshness(self) -> None:
        self.activity(at(7, 9, 0).isoformat(), at(7, 9, 0), 100)
        self.activity(at(7, 9, 0).isoformat(), at(8, 9, 0), 86500)
        self.assertEqual(self.state["last_push_by_symbol"]["SPY.US"], 100)
        self.assertTrue(runtime.active_reference_quotes_are_stale(
            self.state["last_push_by_symbol"], now_monotonic=86500, maximum_silence_seconds=30))

    def test_backlogged_first_callback_is_already_stale(self) -> None:
        self.activity(at(8, 9, 30).isoformat(), at(8, 9, 31), 100)
        self.assertEqual(self.state["last_push_by_symbol"]["SPY.US"], 40)

    def test_invalid_naive_future_and_out_of_order_callbacks_do_not_renew(self) -> None:
        self.activity(at(8, 9, 30).isoformat(), at(8, 9, 30), 100)
        for value in ["bad", "2026-09-08T09:31:00", at(8, 9, 32).isoformat(), at(8, 9, 29).isoformat()]:
            self.activity(value, at(8, 9, 31), 160)
        self.assertEqual(self.state["last_push_by_symbol"]["SPY.US"], 100)

    def test_quote_batch_uses_callback_age_and_snapshot_is_not_activity(self) -> None:
        for mode in ["official_sdk_initial_snapshot", "official_sdk_push", "official_sdk_push"]:
            with patch.object(runtime, "datetime") as clock:
                clock.now.return_value = at(8, 9, 31)
                clock.fromisoformat.side_effect = datetime.fromisoformat
                runtime.apply_quote_state_worker_message(
                    {"kind": "quote_state", "symbol": "SPY.US", "payload": {},
                     "received_at": at(8, 9, 30).isoformat(), "source_mode": mode},
                    live_quote_session_state={}, now_monotonic=160, **self.state,
                )
            if mode == "official_sdk_initial_snapshot":
                self.assertEqual(self.state["last_push_by_symbol"], {})
        self.assertEqual(self.state["last_push_by_symbol"]["SPY.US"], 100)

    def test_volume_resets_only_on_new_session(self) -> None:
        state = {}
        def quote(day: int, volume: int) -> dict:
            return runtime.update_live_quote_session_state(
                state, "SPY.US", {"timestamp": at(day, 9, 31).isoformat(),
                "open": "100", "high": "101", "low": "99", "last_done": "100", "volume": volume},
                received_at=at(day, 9, 31), source_mode="official_sdk_push")
        quote(4, 1000000)
        self.assertEqual(quote(8, 100)["market_data_blocked_reason"], "")
        self.assertEqual(quote(8, 90)["market_data_blocked_reason"], "quote_total_volume_regressed")


class SessionEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = runtime.load_config()
        self.symbols = runtime.configured_trading_symbols(self.config)
        self.assertEqual(len(self.symbols), 147)

    def evidence(self, now: datetime, not_before: datetime | None = None):
        return runtime.MarketSessionEvidence(self.config, now, complete_bar_open_not_before=not_before)

    def feed(self, evidence, day: int, start: int = 1, stop: int = 79) -> None:
        for index in range(start, stop):
            close = at(day, 9, 30) + timedelta(minutes=5 * index)
            now = close + timedelta(seconds=1)
            self.assertEqual(evidence.advance(now), "")
            self.assertEqual(evidence.accept(bars(close, self.symbols), now), "accepted")
            rows = bars(close, self.symbols)
            self.assertEqual(evidence.record_audit(rows, audit_success(rows)), "")

    def test_holiday_then_full_day_then_next_full_day(self) -> None:
        evidence = self.evidence(at(7, 8, 0))
        self.assertEqual(evidence.accept(bars(at(7, 9, 35), self.symbols), at(7, 9, 35, 1)), "ignored")
        self.assertEqual(evidence.advance(at(7, 16, 1)), "")
        self.assertFalse(evidence.complete(at(7, 16, 1), [100] * 78, 1))
        for day in (8, 9, 10):
            self.assertEqual(evidence.advance(at(day, 9, 29)), "")
            self.assertEqual(evidence.complete_boundary_count, 0)
            self.feed(evidence, day)
            self.assertEqual(evidence.realtime_tradable_bar_count, 11466)
            self.assertTrue(evidence.complete(at(day, 16, 0, 2), [100] * 78, 1))
            self.assertFalse(evidence.complete(at(day + 1, 16, 1), [100] * 78, 1))

    def test_partial_77_does_not_poison_next_full_day(self) -> None:
        evidence = self.evidence(at(8, 9, 31), at(8, 9, 35))
        self.feed(evidence, 8, start=2)
        self.assertEqual(evidence.complete_boundary_count, 77)
        self.assertFalse(evidence.complete(at(8, 16, 1), [100] * 77, 1))
        self.assertEqual(evidence.advance(at(9, 9, 29)), "")
        self.feed(evidence, 9)
        self.assertTrue(evidence.complete(at(9, 16, 1), [100] * 78, 1))

    def test_missing_first_and_last_boundary_fault_after_five_seconds(self) -> None:
        for missing in (1, 40, 78):
            evidence = self.evidence(at(8, 9, 29))
            self.feed(evidence, 8, stop=missing)
            close = at(8, 9, 30) + timedelta(minutes=5 * missing)
            self.assertEqual(evidence.advance(close + timedelta(seconds=5)), "")
            self.assertEqual(evidence.advance(close + timedelta(seconds=6)), runtime.to_iso(close))
            self.assertFalse(evidence.complete(at(8, 16, 1), [100] * 78, 1))

    def test_missing_previous_tail_is_not_erased_by_midnight(self) -> None:
        evidence = self.evidence(at(8, 9, 29))
        self.feed(evidence, 8, stop=78)
        self.assertEqual(evidence.advance(at(9, 0, 0)), runtime.to_iso(at(8, 16, 0)))

    def test_duplicate_early_late_and_non_session_rows(self) -> None:
        evidence = self.evidence(at(8, 9, 29))
        close = at(8, 9, 35)
        rows = bars(close, self.symbols)
        for candidate, now in [(rows + [rows[0]], close + timedelta(seconds=1)),
                               (rows, close - timedelta(seconds=1)),
                               (rows, close + timedelta(seconds=6))]:
            with self.assertRaises(ValueError):
                evidence.accept(candidate, now)
        self.assertEqual(evidence.accept(rows, close + timedelta(seconds=1)), "accepted")
        self.assertEqual(evidence.accept(rows, close + timedelta(seconds=2)), "duplicate")
        self.assertEqual(evidence.complete_boundary_count, 1)
        for close in (at(7, 9, 35), at(8, 9, 30), at(8, 16, 5)):
            self.assertEqual(evidence.accept(bars(close, self.symbols), close + timedelta(seconds=1)), "ignored")

    def test_zero_trade_bars_count_but_missing_latency_and_restarts_never_pass(self) -> None:
        evidence = self.evidence(at(8, 9, 29))
        for i in range(1, 79):
            close = at(8, 9, 30) + timedelta(minutes=5 * i)
            evidence.accept(bars(close, self.symbols, carry=True), close + timedelta(seconds=1))
            rows = bars(close, self.symbols, carry=True)
            evidence.record_audit(rows, audit_success(rows))
        self.assertEqual(evidence.no_trade_carry_forward_count, 11466)
        self.assertTrue(evidence.complete(at(8, 16, 1), [100] * 78, 1))
        for latency, generation in [([], 1), ([100] * 77, 1), ([1100] * 78, 1), ([100] * 78, 2)]:
            self.assertFalse(evidence.complete(at(8, 16, 1), latency, generation))

    def test_daily_qualification_expires_without_fetching_anything(self) -> None:
        rows = [{"symbol": s.removesuffix(".US"), "timeframe": "1d",
                 "event_time": runtime.to_iso(at(4, 16, 0) - timedelta(days=i))}
                for s in self.symbols for i in range(60)]
        self.assertTrue(runtime.daily_context_is_current(self.config, rows, self.symbols, [], at(8, 9, 29)))
        self.assertFalse(runtime.daily_context_is_current(self.config, rows, self.symbols, [], at(9, 9, 29)))
        self.assertFalse(runtime.daily_context_is_current(self.config, rows[:-1], self.symbols, [], at(8, 9, 29)))
        self.assertFalse(runtime.daily_context_is_current(self.config, rows, self.symbols, [self.symbols[0]], at(8, 9, 29)))

    def test_boundary_validator_rejects_future_duplicate_and_early_rows(self) -> None:
        close = at(8, 16, 0)
        rows = bars(close, self.symbols)
        self.assertTrue(runtime.realtime_boundary_is_complete(rows, self.symbols, now=close + timedelta(seconds=5)))
        self.assertFalse(runtime.realtime_boundary_is_complete(rows, self.symbols, now=close - timedelta(seconds=1)))
        self.assertFalse(runtime.realtime_boundary_is_complete(rows + [rows[0]], self.symbols, now=close + timedelta(seconds=5)))
        rows[0]["received_at"] = runtime.to_iso(close - timedelta(seconds=1))
        self.assertFalse(runtime.realtime_boundary_is_complete(rows, self.symbols, now=close + timedelta(seconds=5)))

    def test_volume_only_carry_forward_is_evidence_not_entry(self) -> None:
        evidence = self.evidence(at(8, 9, 29))
        rows = bars(at(8, 9, 35), self.symbols, carry=True)
        for row in rows:
            row["market_data_blocked_reason"] = "no_price_forming_trade,no_trade_carry_forward"
        self.assertEqual(evidence.accept(rows, at(8, 9, 35, 2)), "accepted")
        self.assertEqual(evidence.realtime_tradable_bar_count, 0)
        self.assertEqual(evidence.no_trade_carry_forward_count, 147)
        self.assertEqual(runtime.trading_market_events(self.config, rows), [])

    def test_stale_reference_cannot_mutate_accepted_evidence(self) -> None:
        evidence = self.evidence(at(8, 9, 29))
        with self.assertRaisesRegex(ValueError, "reference_quotes_stale"):
            evidence.accept(bars(at(8, 9, 35), self.symbols), at(8, 9, 35, 2), reference_quotes_fresh=False)
        self.assertEqual(evidence.complete_boundary_count, 0)
        self.assertEqual(evidence.realtime_tradable_bar_count, 0)


class WatchLoopTest(unittest.TestCase):
    """Run the real parent loop with no SDK, subprocess, order or broker I/O."""

    def watch(self, start: datetime, events: list[tuple[datetime, dict | None]], *, dispatch: bool = False,
              gate_passed: bool = False, validation_approved: bool = False,
              flatten_blocks_new_entries: bool = True, audit_case: str | None = None):
        clock = [start]
        statuses, gates, dispatched = [], [], []
        config = runtime.load_config()
        real_dispatch = runtime.dispatch_completed_rows
        symbols = runtime.configured_trading_symbols(config)
        daily_rows = [{"symbol": s.removesuffix(".US"), "timeframe": "1d",
                       "event_time": runtime.to_iso(at(4, 16, 0) - timedelta(days=i)),
                       "event_id": f"daily|{s}|{i}"}
                      for s in symbols for i in range(60)]
        schedule = [(start, {"kind": "daily_context", "rows": daily_rows}),
                    (start, {"kind": "ready", "market_data_symbols": symbols,
                             "partial_bar_suppressed_until": runtime.to_iso(start)})] + list(events)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock[0].astimezone(tz or UTC)

        class Queue:
            def get_nowait(self):
                if not schedule or schedule[0][0] > clock[0] or schedule[0][1] is None:
                    raise queue.Empty
                return schedule.pop(0)[1]

            def get(self, timeout=None):
                if not schedule:
                    raise KeyboardInterrupt
                when, message = schedule.pop(0)
                clock[0] = when
                if message is None:
                    raise queue.Empty
                return message

        account = MagicMock()
        account.snapshot.side_effect = lambda: {"generated_at": runtime.to_iso(clock[0]),
            "paper_account_verified": True, "positions_ok": True, "orders_ok": True}
        process_context = MagicMock()
        process_context.Queue.return_value = Queue()
        process_context.Process.return_value.is_alive.return_value = True
        process_context.Process.return_value.pid = 123456
        paper = MagicMock()
        paper.trade_context_refresh_required = False
        paper.healthcheck.return_value = {"ok": True}
        paper.submission_journal_health.return_value = {"ok": True, "unresolved_submission_count": 0}
        trade_context = MagicMock()
        trade_context.check_health.return_value = None
        trade_context.maximum_request_wait_seconds = 2.0

        def build_clients(*args, dispatch_enabled, **kwargs):
            return trade_context, paper if dispatch_enabled else None, paper

        def record(path, day, evidence, **kwargs):
            gates.append({"session_date": day, **evidence})
            return {"passed": True, "completed_sessions": list(gates)}

        def process_rows(*args, **kwargs):
            dispatched.append((clock[0], args[1], kwargs["new_entry_submission_enabled"], args[4]))
            if audit_case is not None:
                return real_dispatch(*args, **kwargs)
            return {"event_count": len(args[1]), **audit_success(args[1])}

        with TemporaryDirectory() as directory, ExitStack() as stack:
            config = replace(config, output_dir=Path(directory),
                             runtime_status_path=Path(directory) / "status.json",
                             market_events_path=Path(directory) / "events.jsonl",
                             daily_context_path=Path(directory) / "daily.jsonl",
                             readonly_gate_path=Path(directory) / "gate.json",
                             paper_validation_approved=validation_approved,
                             paper_validation_market_date="2026-09-08")
            mocks = {
                "acquire_runtime_run_lock": {"return_value": MagicMock()},
                "cleanup_orphaned_sdk_runtime_children": {"return_value": []},
                "require_sdk_contract": {"return_value": object()},
                "config_fingerprint": {"return_value": "offline"},
                "readonly_gate_passed": {"return_value": (gate_passed, int(gate_passed), 1)},
                "verify_manifest": {"return_value": {"verified": True}},
                "read_jsonl_tail_rows": {"return_value": []},
                "SdkAccountProcessCoordinator": {"return_value": account},
                "held_position_monitoring_symbols": {"return_value": ()},
                "detect_position_monitoring_set_change": {"return_value": ((), (), "")},
                "build_sdk_trade_clients": {"side_effect": build_clients},
                "load_current_sdk_intraday_context": {"return_value": []},
                "restore_pipeline_observability": {"return_value": ([], {}, "")},
                "write_daily_context_cache": {},
                "compact_market_events": {},
                "dispatch_completed_rows": {"side_effect": process_rows},
                "record_readonly_session": {"side_effect": record},
                "build_status": {"side_effect": lambda cfg, **kw: statuses.append(kw)},
                "process_resource_snapshot": {"return_value": {}},
                "load_formal_test_marker": {"return_value": {}},
                "stop_spawned_process": {}, "close_spawn_queue": {},
                "run_pending_flatten_cycle": {"return_value": {"blocks_new_entries": flatten_blocks_new_entries}},
                "run_authorized_account_exit_cycle": {"return_value": {"status": "inactive"}},
                "run_sdk_order_maintenance": {"return_value": {"status": "no_actions"}},
            }
            mocked = {}
            for name, kwargs in mocks.items():
                mocked[name] = stack.enter_context(patch.object(runtime, name, **kwargs))
            stack.enter_context(patch.object(runtime, "checked_runtime_boot_startup", create=True,
                                             return_value={"action": "no_boot_recovery"}))
            stack.enter_context(patch("scripts.m15_pa004_overcap_cleanup_lib.advance_cleanup_state",
                                      return_value={"status": "inactive"}))
            if audit_case == "write_failure":
                stack.enter_context(patch.object(runtime, "append_market_events", side_effect=OSError("disk full")))
            stack.enter_context(patch.object(runtime, "datetime", Clock))
            stack.enter_context(patch.object(runtime.mp, "get_context", return_value=process_context))
            stack.enter_context(patch.object(runtime.signal, "signal"))
            stack.enter_context(patch.object(runtime.fcntl, "flock"))
            stack.enter_context(patch.object(runtime.time, "monotonic", side_effect=lambda: 1000 + (clock[0] - start).total_seconds()))
            stack.enter_context(patch.object(runtime.time, "perf_counter", return_value=100))
            result = runtime.run_watch(config, dispatch_requested=dispatch)
        self.assertEqual(process_context.Process.call_count, 1)
        self.assertEqual(process_context.Process.return_value.start.call_count, 1)
        self.assertEqual(mocked["build_sdk_trade_clients"].call_count, 1)
        return result, statuses, gates, dispatched

    @staticmethod
    def heartbeat(now: datetime, callback: datetime | None = None) -> dict:
        return {"kind": "heartbeat", "at": runtime.to_iso(now), "raw_reference_activity": [
            {"symbol": s, "received_at": runtime.to_iso(callback or now),
             "source_mode": "official_sdk_raw_trade_callback"} for s in ("SPY.US", "QQQ.US")
        ]}

    def day_events(self, day: int, start: int = 1, stop: int = 79):
        symbols = runtime.configured_trading_symbols(runtime.load_config())
        events = []
        for i in range(start, stop):
            close = at(day, 9, 30) + timedelta(minutes=5 * i)
            settled = close + timedelta(seconds=2)
            events.extend([(settled, self.heartbeat(settled)), (settled, {"kind": "bars", "rows": bars(close, symbols)})])
        return events

    @staticmethod
    def refresh_daily(day: int):
        symbols = runtime.configured_trading_symbols(runtime.load_config())
        rows = [{"symbol": s.removesuffix(".US"), "timeframe": "1d",
                 "event_time": runtime.to_iso(at(day - 1, 16, 0) - timedelta(days=i)),
                 "event_id": f"daily|{day}|{s}|{i}"} for s in symbols for i in range(60)]
        return [(at(day, 9, 29), WatchLoopTest.heartbeat(at(day, 9, 29))),
                (at(day, 9, 29), {"kind": "daily_context", "rows": rows})]

    def test_holiday_continuous_to_two_full_days_real_loop(self) -> None:
        symbols = runtime.configured_trading_symbols(runtime.load_config())
        events = [(at(7, 9, 35, 2), self.heartbeat(at(7, 9, 35, 2))),
                  (at(7, 9, 35, 2), {"kind": "bars", "rows": bars(at(7, 9, 35), symbols)})]
        events += self.day_events(8) + self.refresh_daily(9) + self.day_events(9)
        result, statuses, gates, dispatched = self.watch(at(7, 8, 0), events)
        self.assertEqual(result, 0)
        self.assertEqual([g["session_date"] for g in gates], ["2026-09-08", "2026-09-09"])
        self.assertTrue(all(g["complete_boundary_count"] == 78 and g["realtime_bar_count"] == 11466 for g in gates))
        self.assertEqual(len(dispatched), 156)
        self.assertTrue(all(not enabled for _, _, enabled, _ in dispatched))
        self.assertTrue(statuses[-1]["extra"]["trading_daily_context_ready"])

    def test_pending_bar_at_deadline_is_processed_after_heartbeat(self) -> None:
        symbols = runtime.configured_trading_symbols(runtime.load_config())
        events = self.day_events(8, stop=78)
        close = at(8, 16, 0)
        received = close + timedelta(seconds=5)
        rows = bars(close, symbols)
        for row in rows:
            row["received_at"] = runtime.to_iso(received)
        events.extend([(received, self.heartbeat(received)), (received, {"kind": "bars", "rows": rows}),
                       (received, {"kind": "bars", "rows": rows})])
        result, _, gates, dispatched = self.watch(at(8, 9, 29), events)
        self.assertEqual(result, 0)
        self.assertEqual(len(dispatched), 78)
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0]["complete_boundary_count"], 78)

    def test_partial_77_then_78_real_loop(self) -> None:
        result, _, gates, dispatched = self.watch(at(8, 9, 35), self.day_events(8, start=2) + self.refresh_daily(9) + self.day_events(9))
        self.assertEqual(result, 0)
        self.assertEqual(len(dispatched), 155)
        self.assertEqual([g["session_date"] for g in gates], ["2026-09-09"])

    def test_full_day_with_stale_daily_context_cannot_certify(self) -> None:
        result, statuses, gates, dispatched = self.watch(at(9, 9, 29), self.day_events(9))
        self.assertEqual(result, 0)
        self.assertEqual(len(dispatched), 78)
        self.assertEqual(statuses[-1]["extra"]["complete_boundary_count"], 78)
        self.assertFalse(statuses[-1]["extra"]["trading_daily_context_ready"])
        self.assertEqual(gates, [])

    def test_idle_and_heartbeat_missing_boundaries_halt_real_loop(self) -> None:
        for missing, idle in [(1, True), (40, False), (78, True)]:
            close = at(8, 9, 30) + timedelta(minutes=5 * missing)
            check = close + timedelta(seconds=6)
            events = self.day_events(8, stop=missing)
            events.append((check, None if idle else self.heartbeat(check)))
            result, statuses, gates, _ = self.watch(at(8, 9, 29), events)
            self.assertEqual(result, 4)
            self.assertEqual(statuses[-1]["reason"], "realtime_bar_boundary_deadline_exceeded")
            self.assertEqual(statuses[-1]["extra"]["fault_details"]["boundary"], runtime.to_iso(close))
            self.assertEqual(gates, [])

    def test_repeated_callback_after_holiday_open_halts_real_loop(self) -> None:
        events = [(at(8, 9, 30, 31), self.heartbeat(at(8, 9, 30, 31), at(7, 9, 30)))]
        result, statuses, gates, _ = self.watch(at(7, 8, 0), events)
        self.assertEqual(result, 4)
        self.assertEqual(statuses[-1]["reason"], "reference_market_data_stalled")
        self.assertEqual(gates, [])

    def test_stale_daily_context_disables_entry_but_keeps_exit_client(self) -> None:
        result, statuses, _, dispatched = self.watch(at(9, 9, 29), self.day_events(9, stop=2), dispatch=True, gate_passed=True)
        self.assertEqual(result, 0)
        self.assertEqual(len(dispatched), 1)
        self.assertFalse(dispatched[0][2])
        self.assertIsNotNone(dispatched[0][3])
        self.assertFalse(statuses[-1]["extra"]["dispatch_enabled"])

    def test_validation_waits_for_first_complete_boundary_without_full_session_proof(self) -> None:
        before = [(at(8, 9, 34, 59), self.heartbeat(at(8, 9, 34, 59)))]
        for completed in (False, True):
            with self.subTest(completed=completed):
                events = before + (self.day_events(8, stop=2) if completed else [])
                result, statuses, gates, dispatched = self.watch(
                    at(8, 9, 29), events, dispatch=True, gate_passed=False,
                    validation_approved=True, flatten_blocks_new_entries=False)
                self.assertEqual(result, 0)
                self.assertEqual(gates, [])
                self.assertEqual(len(dispatched), int(completed))
                self.assertTrue(statuses[-1]["extra"]["paper_validation_authorized"])
                self.assertFalse(statuses[-1]["extra"]["complete_session_gate_passed"])
                self.assertEqual(statuses[-1]["extra"]["complete_boundary_count"], int(completed))
                if completed:
                    self.assertEqual(dispatched[0][0], at(8, 9, 35, 2))
                    self.assertTrue(dispatched[0][2])
                    self.assertIsNotNone(dispatched[0][3])
                    self.assertTrue(statuses[-1]["extra"]["dispatch_enabled"])

    def test_validation_partial_first_boundary_never_dispatches(self) -> None:
        result, statuses, gates, dispatched = self.watch(
            at(8, 9, 31), self.day_events(8, stop=3), dispatch=True,
            gate_passed=False, validation_approved=True, flatten_blocks_new_entries=False)
        self.assertEqual(result, 0)
        self.assertEqual(gates, [])
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0][0], at(8, 9, 40, 2))
        self.assertTrue(dispatched[0][2])
        self.assertIsNotNone(dispatched[0][3])
        self.assertEqual(statuses[-1]["extra"]["complete_boundary_count"], 1)
        self.assertFalse(statuses[-1]["extra"]["complete_session_gate_passed"])

    def test_validation_expiry_closes_entries_but_retains_exit_client(self) -> None:
        midnight = at(9, 0, 0)
        before_midnight = midnight - timedelta(seconds=1)
        events = self.day_events(8, start=77)
        events += [(before_midnight, self.heartbeat(before_midnight)), (midnight, self.heartbeat(midnight))]
        events += self.refresh_daily(9) + self.day_events(9, stop=2)
        result, statuses, gates, dispatched = self.watch(
            at(8, 15, 49), events, dispatch=True, gate_passed=False,
            validation_approved=True, flatten_blocks_new_entries=False)
        self.assertEqual(result, 0)
        self.assertEqual(gates, [])
        self.assertEqual(len(dispatched), 3)
        self.assertTrue(all(enabled for _, _, enabled, _ in dispatched[:-1]))
        original_client = dispatched[0][3]
        self.assertIsNotNone(original_client)
        self.assertEqual(dispatched[-1][0], at(9, 9, 35, 2))
        self.assertFalse(dispatched[-1][2])
        self.assertTrue(all(client is original_client for _, _, _, client in dispatched))
        before_midnight_states = [row["extra"] for row in statuses
                                  if row.get("extra", {}).get("evidence_session_date") == "2026-09-08"]
        self.assertTrue(before_midnight_states[-1]["paper_validation_authorized"])
        midnight_states = [row["extra"] for row in statuses
                           if row.get("extra", {}).get("evidence_session_date") == "2026-09-09"]
        self.assertTrue(midnight_states)
        self.assertTrue(all(not row["paper_validation_authorized"] for row in midnight_states))
        self.assertTrue(all(not row["dispatch_enabled"] for row in midnight_states))
        self.assertTrue(statuses[-1]["extra"]["trading_daily_context_ready"])
        self.assertFalse(statuses[-1]["extra"]["complete_session_gate_passed"])

    def test_validation_worker_fault_halts_without_new_context_or_later_dispatch(self) -> None:
        failed_at = at(8, 9, 35, 3)
        events = self.day_events(8, stop=2)
        events += [(failed_at, {"kind": "error", "reason": "official_sdk_callback_failed"})]
        events += self.day_events(8, start=2, stop=3)
        result, statuses, gates, dispatched = self.watch(
            at(8, 9, 29), events, dispatch=True, gate_passed=False,
            validation_approved=True, flatten_blocks_new_entries=False)
        self.assertEqual(result, 4)
        self.assertEqual(gates, [])
        self.assertEqual(len(dispatched), 1)
        self.assertTrue(dispatched[0][2])
        self.assertIsNotNone(dispatched[0][3])
        self.assertEqual(statuses[-1]["status"], "fault_halted")
        self.assertEqual(statuses[-1]["reason"], "official_sdk_callback_failed")
        self.assertFalse(statuses[-1]["extra"]["dispatch_enabled"])

    def test_validation_duplicate_boundary_does_not_replay_dispatch(self) -> None:
        first = self.day_events(8, stop=2)
        events = first + first + self.day_events(8, start=2, stop=3)
        result, statuses, gates, dispatched = self.watch(
            at(8, 9, 29), events, dispatch=True, gate_passed=False,
            validation_approved=True, flatten_blocks_new_entries=False)
        self.assertEqual(result, 0)
        self.assertEqual(gates, [])
        self.assertEqual([when for when, _, _, _ in dispatched], [at(8, 9, 35, 2), at(8, 9, 40, 2)])
        self.assertTrue(all(enabled and client is not None for _, _, enabled, client in dispatched))
        self.assertEqual(statuses[-1]["extra"]["complete_boundary_count"], 2)
        self.assertEqual(statuses[-1]["extra"]["audited_boundary_count"], 2)
        self.assertFalse(statuses[-1]["extra"]["complete_session_gate_passed"])

    def test_real_dispatch_audit_failure_or_staleness_halts_parent(self) -> None:
        symbols = runtime.configured_trading_symbols(runtime.load_config())
        for case, reason in [("stale", "realtime_bar_freshness_rejected"),
                             ("write_failure", "realtime_bar_audit_failed")]:
            close = at(8, 9, 35)
            rows = bars(close, symbols)
            for row in rows:
                row["received_at"] = runtime.to_iso(close + timedelta(seconds=2))
            now = close + timedelta(seconds=4.5)
            events = [(now, self.heartbeat(now)), (now, {"kind": "bars", "rows": rows})]
            result, statuses, gates, _ = self.watch(at(8, 9, 29), events, dispatch=True, gate_passed=True, audit_case=case)
            self.assertEqual(result, 4)
            self.assertEqual(statuses[-1]["reason"], reason)
            self.assertEqual(statuses[-1]["extra"]["audited_boundary_count"], 0)
            self.assertEqual(statuses[-1]["extra"]["session_audit_failure"], reason)
            self.assertEqual(statuses[-1]["extra"]["fault_details"]["pipeline_audit"]["execution"]["submitted_count"], 0)
            self.assertEqual(gates, [])


class AuditDispatchTest(unittest.TestCase):
    def test_full_day_without_audit_acknowledgements_never_passes(self) -> None:
        config = runtime.load_config()
        symbols = runtime.configured_trading_symbols(config)
        evidence = runtime.MarketSessionEvidence(config, at(8, 9, 29))
        for i in range(1, 79):
            close = at(8, 9, 30) + timedelta(minutes=5 * i)
            evidence.accept(bars(close, symbols), close + timedelta(seconds=2))
        self.assertEqual(evidence.complete_boundary_count, 78)
        self.assertFalse(evidence.complete(at(8, 16, 1), [0] * 78, 1))

    def test_two_second_seal_late_consume_is_audited_but_never_executed(self) -> None:
        with TemporaryDirectory() as directory:
            config = replace(runtime.load_config(), market_events_path=Path(directory) / "events.jsonl")
            symbols = runtime.configured_trading_symbols(config)
            close = at(8, 9, 35)
            rows = bars(close, symbols)
            for row in rows:
                row["received_at"] = runtime.to_iso(close + timedelta(seconds=2))
            now = close + timedelta(seconds=4.5)
            evidence = runtime.MarketSessionEvidence(config, at(8, 9, 29))
            self.assertEqual(evidence.accept(rows, now), "accepted")
            freshness_filter = runtime.fresh_market_events
            with patch.object(runtime, "datetime") as clock, patch.object(
                runtime, "fresh_market_events",
                side_effect=lambda values, age, **kw: freshness_filter(values, age, now=now),
            ):
                clock.now.return_value = now
                clock.fromisoformat.side_effect = datetime.fromisoformat
                account, client = MagicMock(), MagicMock()
                result = runtime.dispatch_completed_rows(config, rows, runtime.MarketEventContext(), account, client)
            audited = [json.loads(line) for line in config.market_events_path.read_text().splitlines()]
            self.assertEqual(len(audited), 147)
            self.assertEqual({row["event_id"] for row in audited}, {row["event_id"] for row in rows})
            self.assertEqual(result["audit_event_count"], 147)
            self.assertEqual(result["fresh_event_count"], 0)
            self.assertEqual(result["stale_event_count"], 147)
            self.assertEqual(result["stale_tradable_event_count"], 147)
            self.assertEqual(evidence.record_audit(rows, result), "realtime_bar_freshness_rejected")
            self.assertFalse(evidence.complete(at(8, 16, 1), [0] * 78, 1))
            self.assertEqual(account.mock_calls, [])
            self.assertEqual(client.mock_calls, [])

    def test_stale_volume_only_rows_are_audited_without_entry_eligibility(self) -> None:
        with TemporaryDirectory() as directory:
            config = replace(runtime.load_config(), market_events_path=Path(directory) / "events.jsonl")
            rows = bars(at(8, 9, 35), runtime.configured_trading_symbols(config), carry=True)
            for row in rows:
                row["market_data_blocked_reason"] = "no_price_forming_trade,no_trade_carry_forward"
                row["source_delivery_age_ms"] = 300000
            account, client = MagicMock(), MagicMock()
            result = runtime.dispatch_completed_rows(config, rows, runtime.MarketEventContext(), account, client)
            self.assertEqual(len(config.market_events_path.read_text().splitlines()), 147)
            self.assertEqual(result["audit_event_count"], 147)
            self.assertEqual(result["stale_event_count"], 147)
            self.assertEqual(result["stale_tradable_event_count"], 0)
            self.assertEqual(account.mock_calls, [])
            self.assertEqual(client.mock_calls, [])

    def test_audit_write_failure_prevents_strategy_and_gate(self) -> None:
        config = runtime.load_config()
        rows = bars(at(8, 9, 35), runtime.configured_trading_symbols(config))
        evidence = runtime.MarketSessionEvidence(config, at(8, 9, 29))
        evidence.accept(rows, at(8, 9, 35, 2))
        account, client = MagicMock(), MagicMock()
        with patch.object(runtime, "append_market_events", side_effect=OSError("disk full")):
            result = runtime.dispatch_completed_rows(config, rows, runtime.MarketEventContext(), account, client)
        self.assertEqual(result["audit_status"], "failed")
        self.assertTrue(result["audit_partial_write_possible"])
        self.assertEqual(evidence.record_audit(rows, result), "realtime_bar_audit_failed")
        self.assertFalse(evidence.complete(at(8, 16, 1), [0] * 78, 1))
        self.assertEqual(account.mock_calls, [])
        self.assertEqual(client.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
