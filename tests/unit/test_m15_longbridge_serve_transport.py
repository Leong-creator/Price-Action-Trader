from __future__ import annotations

import queue
import os
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.m15_longbridge_serve_transport_lib import (
    LongbridgeServeSession,
    emit_worker,
    longbridge_serve_quote_worker,
    merge_quote_payload,
    normalize_symbol,
    probe_longbridge_serve_transport,
    process_resource_snapshot,
    subscription_symbols_from_result,
    symbol_batches,
)
from scripts.m15_longbridge_sdk_runtime_lib import FiveMinuteBarBuilder


class _FakeProcess:
    pid = 4321
    returncode = None

    def poll(self):
        return None


class _FakeSession:
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.process = _FakeProcess()
        self.messages = queue.Queue()
        self.stderr_tail = []
        self.sent = []
        self.concurrent_request_counts = []
        self.closed = False
        self.__class__.instances.append(self)

    def send(self, request):
        self.sent.append(request)

    def _response(self, request_id, on_notification):
        if request_id == 1:
            return {"id": 1, "result": {"protocolVersion": "1"}}
        request = next(row for row in self.sent if row.get("id") == request_id)
        method = request["method"]
        if method == "quote.subscriptions":
            symbols = [
                symbol
                for row in self.sent
                if row.get("method") == "quote.subscribe"
                for symbol in row["params"]["symbols"]
            ]
            return {
                "id": request_id,
                "result": {
                    "sub_list": [
                        {"symbol": symbol, "sub_type": [1, 4]}
                        for symbol in symbols
                    ]
                },
            }
        symbols = request.get("params", {}).get("symbols", [])
        if method == "quote.quote":
            return {
                "id": request_id,
                "result": [
                    {
                        "symbol": symbol,
                        "last_done": "100",
                        "timestamp": "2026-08-25T13:30:00Z",
                    }
                    for symbol in symbols
                ],
            }
        if request_id == 2:
            on_notification(
                {
                    "method": "quote.updated",
                    "params": {
                        "symbol": "SPY.US",
                        "last_done": "500",
                        "timestamp": "2026-08-25T13:30:01Z",
                    },
                }
            )
            on_notification(
                {
                    "method": "quote.trades",
                    "params": {
                        "symbol": "SPY.US",
                        "trades": [
                            {
                                "price": "500",
                                "volume": 2,
                                "timestamp": "2026-08-25T13:30:01Z",
                            }
                        ],
                    },
                }
            )
        return {
            "id": request_id,
            "result": {
                "subscribed": [
                    {"symbol": symbol, "fields": ["quote", "trades"]}
                    for symbol in symbols
                ],
                "quotes": [
                    {
                        "symbol": symbol,
                        "last_done": "100",
                        "timestamp": "2026-08-25T13:30:00Z",
                    }
                    for symbol in symbols
                ],
            },
        }

    def wait_for_response(self, request_id, on_notification):
        return self._response(request_id, on_notification)

    def wait_for_responses(
        self, request_ids, on_notification, *, timeout_seconds=None
    ):
        del timeout_seconds
        self.concurrent_request_counts.append(len(request_ids))
        return {
            request_id: self._response(request_id, on_notification)
            for request_id in request_ids
        }

    def close(self, _request_id):
        self.closed = True


class _ReaderErrorSession(_FakeSession):
    def __init__(self, *_args, **_kwargs):
        super().__init__(*_args, **_kwargs)
        self.reader_errors = ["invalid_json_stdout"]


class _MonitoringTimeoutSession(_FakeSession):
    def _response(self, request_id, on_notification):
        request = next(row for row in self.sent if row.get("id") == request_id)
        if request.get("method") == "quote.subscribe" and "EXTRA.US" in request[
            "params"
        ]["symbols"]:
            return None
        if request.get("method") == "quote.subscriptions":
            return {
                "id": request_id,
                "result": {
                    "sub_list": [
                        {"symbol": "SPY.US", "sub_type": [1, 4]},
                    ]
                },
            }
        return super()._response(request_id, on_notification)

    def wait_for_responses(
        self, request_ids, on_notification, *, timeout_seconds=None
    ):
        del timeout_seconds
        return {
            request_id: response
            for request_id in request_ids
            if (response := self._response(request_id, on_notification)) is not None
        }


class _BurstSession(_FakeSession):
    def _response(self, request_id, on_notification):
        request = next(row for row in self.sent if row.get("id") == request_id)
        if request.get("method") == "quote.subscribe" and request_id == 2:
            for index in range(500):
                on_notification(
                    {
                        "method": "quote.updated",
                        "params": {
                            "symbol": "SPY.US",
                            "last_done": str(500 + index / 1000),
                            "timestamp": "2026-08-25T13:30:01Z",
                        },
                    }
                )
            symbols = request["params"]["symbols"]
            return {
                "id": request_id,
                "result": {
                    "subscribed": [
                        {"symbol": symbol, "fields": ["quote", "trades"]}
                        for symbol in symbols
                    ],
                    "quotes": [
                        {
                            "symbol": symbol,
                            "last_done": "100",
                            "timestamp": "2026-08-25T13:30:00Z",
                        }
                        for symbol in symbols
                    ],
                },
            }
        return super()._response(request_id, on_notification)


class _FailOnceByKindQueue(queue.Queue):
    def __init__(self, *kinds: str):
        super().__init__()
        self.fail_once = set(kinds)

    def put_nowait(self, item):
        kind = str(item.get("kind") or "") if isinstance(item, dict) else ""
        if kind in self.fail_once:
            self.fail_once.remove(kind)
            raise queue.Full
        return super().put_nowait(item)


class _FakeStopEvent:
    def __init__(self):
        self.check_count = 0

    def is_set(self):
        self.check_count += 1
        return self.check_count > 1

    def wait(self, _seconds):
        return None


class _FakeBuilder:
    def __init__(self, *_args, **_kwargs):
        self.seeded = []

    def seed_quote(self, symbol, payload, *, received_at):
        self.seeded.append((symbol, payload, received_at))

    def on_trade(self, symbol, payload, *, received_at):
        return [
            {
                "symbol": symbol,
                "payload": payload,
                "received_at": received_at.isoformat(),
            }
        ]

    def complete_boundary(self, _symbols, _now):
        return []


class LongbridgeServeTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeSession.instances.clear()

    def test_symbol_helpers_are_deterministic(self) -> None:
        self.assertEqual(normalize_symbol("spy"), "SPY.US")
        self.assertEqual(
            symbol_batches(["A.US", "B.US", "C.US"], 2),
            [["A.US", "B.US"], ["C.US"]],
        )

    def test_subscription_result_parser_covers_serve_response_shapes(self) -> None:
        self.assertEqual(
            subscription_symbols_from_result(
                {
                    "subscribed": [
                        {"symbol": "SPY.US", "fields": ["quote", "trades"]}
                    ]
                }
            ),
            {"SPY.US"},
        )
        self.assertEqual(
            subscription_symbols_from_result(
                {"sub_list": [{"symbol": "QQQ.US", "sub_type": [1, 4]}]}
            ),
            {"QQQ.US"},
        )

    def test_process_resource_snapshot_reports_current_process(self) -> None:
        resources = process_resource_snapshot(os.getpid())
        self.assertGreater(resources["rss_kb"], 0)
        self.assertGreater(resources["thread_count"], 0)
        self.assertGreater(resources["file_descriptor_count"], 0)

    def test_emit_worker_never_waits_when_cross_process_queue_is_full(self) -> None:
        output = queue.Queue(maxsize=1)
        output.put_nowait({"kind": "occupied"})
        started = time.monotonic()

        self.assertFalse(emit_worker(output, {"kind": "heartbeat"}))
        self.assertLess(time.monotonic() - started, 0.05)

    def test_quote_tick_and_snapshot_merge_without_timestamp_regression(self) -> None:
        received_at = datetime(2026, 8, 25, 13, 31, tzinfo=UTC)
        merged, kept_newer = merge_quote_payload(
            {
                "symbol": "SPY.US",
                "last_done": "501",
                "timestamp": "2026-08-25T13:31:00Z",
            },
            {
                "symbol": "SPY.US",
                "last_done": "499",
                "open": "498",
                "high": "502",
                "low": "497",
                "volume": 1000,
                "timestamp": "2026-08-25T13:30:59Z",
            },
            received_at=received_at,
        )

        self.assertTrue(kept_newer)
        self.assertEqual(merged["last_done"], "501")
        self.assertEqual(merged["timestamp"], "2026-08-25T13:31:00Z")
        self.assertEqual(merged["open"], "498")
        self.assertEqual(merged["volume"], 1000)

    def test_market_data_session_rejects_trade_write_methods_locally(self) -> None:
        session = object.__new__(LongbridgeServeSession)
        with self.assertRaisesRegex(ValueError, "method_not_allowed"):
            session.send(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "trade.submit_order",
                    "params": {},
                }
            )

    def test_market_data_session_preserves_out_of_order_responses(self) -> None:
        session = object.__new__(LongbridgeServeSession)
        session.response_timeout_seconds = 1
        session.messages = queue.Queue()
        session.pending_responses = {}
        session.process = _FakeProcess()
        session.messages.put({"id": 2, "result": "second"})
        session.messages.put({"id": 1, "result": "first"})

        first = session.wait_for_response(1, lambda _message: None)
        second = session.wait_for_response(2, lambda _message: None)

        self.assertEqual(first["result"], "first")
        self.assertEqual(second["result"], "second")
        self.assertEqual(session.pending_responses, {})

    def test_market_data_session_fails_wait_when_reader_breaks_before_ready(self) -> None:
        session = object.__new__(LongbridgeServeSession)
        session.response_timeout_seconds = 30
        session.messages = queue.Queue()
        session.pending_responses = {}
        session.process = _FakeProcess()
        session.reader_errors = ["invalid_json_stdout"]

        with self.assertRaisesRegex(RuntimeError, "longbridge_serve_reader_failed"):
            session.wait_for_responses(
                {1},
                lambda _message: None,
                timeout_seconds=30,
            )

    def test_preflight_initializes_and_checks_subscription_and_quotes(self) -> None:
        config = SimpleNamespace(
            longbridge_serve_binary=Path("/tmp/longbridge"),
            longbridge_serve_response_timeout_seconds=30,
            quote_region="cn",
        )
        with patch(
            "scripts.m15_longbridge_serve_transport_lib.LongbridgeServeSession",
            _FakeSession,
        ):
            result = probe_longbridge_serve_transport(
                config, ("SPY.US", "QQQ.US")
            )

        self.assertEqual(result["subscription_coverage"], "2/2")
        self.assertEqual(result["initial_quote_coverage"], "2/2")
        methods = [row["method"] for row in _FakeSession.instances[0].sent]
        self.assertEqual(methods, ["initialize", "quote.subscribe"])
        self.assertTrue(_FakeSession.instances[0].closed)

    def test_worker_stops_when_transport_reader_reports_corrupt_data(self) -> None:
        config = SimpleNamespace(
            bar_minutes=5,
            longbridge_serve_binary=Path("/tmp/longbridge"),
            longbridge_serve_response_timeout_seconds=30,
            longbridge_serve_batch_size=2,
            quote_region="cn",
        )
        output = queue.Queue()
        with (
            patch(
                "scripts.m15_longbridge_serve_transport_lib.load_config",
                return_value=config,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_symbols",
                return_value=("SPY.US",),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_trading_symbols",
                return_value=("SPY.US",),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.LongbridgeServeSession",
                _ReaderErrorSession,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.FiveMinuteBarBuilder",
                _FakeBuilder,
            ),
        ):
            longbridge_serve_quote_worker(
                "unused.json",
                output,
                _FakeStopEvent(),
            )

        errors = []
        while not output.empty():
            row = output.get_nowait()
            if row["kind"] == "error":
                errors.append(row["reason"])
        self.assertEqual(len(errors), 1)
        self.assertIn("longbridge_serve_reader_failed", errors[0])

    def test_builder_preserves_serve_source_and_iso_timestamps(self) -> None:
        bar_open = datetime(2026, 8, 25, 13, 30, tzinfo=UTC)
        builder = FiveMinuteBarBuilder(
            5,
            complete_bar_open_not_before=bar_open,
            boundary_batch_mode=True,
            push_source_mode="longbridge_serve_push",
            no_trade_source_mode="longbridge_serve_no_trade_carry_forward",
            event_id_prefix="longbridge-serve-5m",
        )
        builder.seed_quote(
            "SPY.US",
            {"last_done": "500", "timestamp": "2026-08-25T13:30:00Z"},
            received_at=bar_open,
        )
        builder.on_trade(
            "SPY.US",
            {
                "trades": [
                    {
                        "price": "501",
                        "volume": 3,
                        "timestamp": "2026-08-25T13:31:00Z",
                    }
                ]
            },
            received_at=datetime(2026, 8, 25, 13, 31, 1, tzinfo=UTC),
        )
        rows = builder.complete_boundary(
            ["SPY.US"],
            datetime(2026, 8, 25, 13, 35, 1, tzinfo=UTC),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_mode"], "longbridge_serve_push")
        self.assertTrue(rows[0]["event_id"].startswith("longbridge-serve-5m|"))

    def test_older_initial_snapshot_cannot_replace_newer_push_price(self) -> None:
        bar_open = datetime(2026, 8, 25, 13, 30, tzinfo=UTC)
        builder = FiveMinuteBarBuilder(
            5,
            complete_bar_open_not_before=bar_open,
            boundary_batch_mode=True,
            push_source_mode="longbridge_serve_push",
            no_trade_source_mode="longbridge_serve_no_trade_carry_forward",
            event_id_prefix="longbridge-serve-5m",
        )
        builder.seed_quote(
            "SPY.US",
            {"last_done": "501", "timestamp": "2026-08-25T13:31:00Z"},
            received_at=bar_open,
        )
        builder.seed_quote(
            "SPY.US",
            {"last_done": "499", "timestamp": "2026-08-25T13:30:59Z"},
            received_at=bar_open,
        )

        rows = builder.complete_boundary(
            ["SPY.US"],
            datetime(2026, 8, 25, 13, 35, 1, tzinfo=UTC),
        )

        self.assertEqual(rows[0]["close"], "501")

    def test_worker_emits_existing_parent_message_contract(self) -> None:
        config = SimpleNamespace(
            bar_minutes=5,
            longbridge_serve_binary=Path("/tmp/longbridge"),
            longbridge_serve_response_timeout_seconds=30,
            longbridge_serve_batch_size=2,
            quote_region="cn",
        )
        output = queue.Queue()
        with (
            patch(
                "scripts.m15_longbridge_serve_transport_lib.load_config",
                return_value=config,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_symbols",
                return_value=("SPY.US", "QQQ.US", "AAPL.US"),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_trading_symbols",
                return_value=("SPY.US", "QQQ.US", "AAPL.US"),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.LongbridgeServeSession",
                _FakeSession,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.FiveMinuteBarBuilder",
                _FakeBuilder,
            ),
        ):
            longbridge_serve_quote_worker(
                "unused.json",
                output,
                _FakeStopEvent(),
            )

        rows = []
        while not output.empty():
            rows.append(output.get_nowait())
        kinds = {row["kind"] for row in rows}
        self.assertTrue(
            {
                "subscription_progress",
                "quote_state_batch",
                "market_activity",
                "bars",
                "ready",
                "heartbeat",
            }
            <= kinds
        )
        ready = next(row for row in rows if row["kind"] == "ready")
        self.assertEqual(ready["market_data_mode"], "longbridge_serve_subscription")
        self.assertEqual(ready["subscription_failed_symbols"], [])
        spy_quotes = [
            quote
            for row in rows
            if row["kind"] == "quote_state_batch"
            for quote in row["rows"]
            if quote["symbol"] == "SPY.US"
        ]
        self.assertEqual(spy_quotes[-1]["payload"]["last_done"], "500")
        self.assertEqual(spy_quotes[-1]["source_mode"], "longbridge_serve_push")
        session = _FakeSession.instances[0]
        subscribe_requests = [
            request for request in session.sent if request.get("method") == "quote.subscribe"
        ]
        self.assertEqual(len(subscribe_requests), 2)
        self.assertEqual(subscribe_requests[0]["params"]["fields"], ["quote", "trades"])
        self.assertTrue(session.concurrent_request_counts)
        self.assertLessEqual(max(session.concurrent_request_counts), 1)
        self.assertTrue(session.closed)

    def test_worker_coalesces_quote_burst_before_cross_process_delivery(self) -> None:
        config = SimpleNamespace(
            bar_minutes=5,
            longbridge_serve_binary=Path("/tmp/longbridge"),
            longbridge_serve_response_timeout_seconds=30,
            longbridge_serve_batch_size=2,
            quote_region="cn",
        )
        output = queue.Queue()
        with (
            patch(
                "scripts.m15_longbridge_serve_transport_lib.load_config",
                return_value=config,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_symbols",
                return_value=("SPY.US", "QQQ.US", "AAPL.US"),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_trading_symbols",
                return_value=("SPY.US", "QQQ.US", "AAPL.US"),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.LongbridgeServeSession",
                _BurstSession,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.FiveMinuteBarBuilder",
                _FakeBuilder,
            ),
        ):
            longbridge_serve_quote_worker(
                "unused.json",
                output,
                _FakeStopEvent(),
            )

        rows = []
        while not output.empty():
            rows.append(output.get_nowait())
        quote_batches = [row for row in rows if row["kind"] == "quote_state_batch"]
        self.assertEqual(len(quote_batches), 1)
        spy_rows = [
            row
            for row in quote_batches[0]["rows"]
            if row["symbol"] == "SPY.US"
        ]
        self.assertEqual(len(spy_rows), 1)
        self.assertEqual(spy_rows[0]["payload"]["last_done"], "500.499")

    def test_worker_retries_critical_bar_after_temporary_queue_pressure(self) -> None:
        config = SimpleNamespace(
            bar_minutes=5,
            longbridge_serve_binary=Path("/tmp/longbridge"),
            longbridge_serve_response_timeout_seconds=30,
            longbridge_serve_batch_size=2,
            quote_region="cn",
        )
        output = _FailOnceByKindQueue("bars")
        with (
            patch(
                "scripts.m15_longbridge_serve_transport_lib.load_config",
                return_value=config,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_symbols",
                return_value=("SPY.US", "QQQ.US", "AAPL.US"),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_trading_symbols",
                return_value=("SPY.US", "QQQ.US", "AAPL.US"),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.LongbridgeServeSession",
                _FakeSession,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.FiveMinuteBarBuilder",
                _FakeBuilder,
            ),
        ):
            longbridge_serve_quote_worker("unused.json", output, _FakeStopEvent())

        rows = []
        while not output.empty():
            rows.append(output.get_nowait())
        self.assertTrue(any(row["kind"] == "bars" for row in rows))
        self.assertTrue(any(row["kind"] == "ready" for row in rows))

    def test_worker_retries_reference_activity_after_queue_pressure(self) -> None:
        config = SimpleNamespace(
            bar_minutes=5,
            longbridge_serve_binary=Path("/tmp/longbridge"),
            longbridge_serve_response_timeout_seconds=30,
            longbridge_serve_batch_size=2,
            quote_region="cn",
        )
        output = _FailOnceByKindQueue("market_activity")
        with (
            patch(
                "scripts.m15_longbridge_serve_transport_lib.load_config",
                return_value=config,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_symbols",
                return_value=("SPY.US", "QQQ.US", "AAPL.US"),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_trading_symbols",
                return_value=("SPY.US", "QQQ.US", "AAPL.US"),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.LongbridgeServeSession",
                _FakeSession,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.FiveMinuteBarBuilder",
                _FakeBuilder,
            ),
        ):
            longbridge_serve_quote_worker("unused.json", output, _FakeStopEvent())

        rows = []
        while not output.empty():
            rows.append(output.get_nowait())
        activities = [row for row in rows if row["kind"] == "market_activity"]
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities[0]["symbol"], "SPY.US")

    def test_worker_serially_subscribes_full_pool_and_monitoring_symbols(self) -> None:
        base_symbols = tuple(
            ["SPY.US"] + [f"S{index:03}.US" for index in range(146)]
        )
        monitoring_symbols = tuple(f"M{index:03}.US" for index in range(9))
        config = SimpleNamespace(
            bar_minutes=5,
            longbridge_serve_binary=Path("/tmp/longbridge"),
            longbridge_serve_response_timeout_seconds=30,
            longbridge_serve_batch_size=10,
            quote_region="cn",
        )
        output = queue.Queue()
        with (
            patch(
                "scripts.m15_longbridge_serve_transport_lib.load_config",
                return_value=config,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_symbols",
                return_value=base_symbols,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_trading_symbols",
                return_value=base_symbols,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.LongbridgeServeSession",
                _FakeSession,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.FiveMinuteBarBuilder",
                _FakeBuilder,
            ),
        ):
            longbridge_serve_quote_worker(
                "unused.json",
                output,
                _FakeStopEvent(),
                monitoring_symbols,
            )

        rows = []
        while not output.empty():
            rows.append(output.get_nowait())
        ready = next(row for row in rows if row["kind"] == "ready")
        self.assertEqual(len(ready["subscribed_symbols"]), 147)
        self.assertEqual(len(ready["position_monitoring_subscribed_symbols"]), 9)
        self.assertEqual(ready["subscription_failed_symbols"], [])
        self.assertEqual(ready["position_monitoring_failed_symbols"], [])
        session = _FakeSession.instances[0]
        subscribe_requests = [
            request
            for request in session.sent
            if request.get("method") == "quote.subscribe"
        ]
        self.assertEqual(len(subscribe_requests), 16)
        self.assertTrue(
            all(len(request["params"]["symbols"]) <= 10 for request in subscribe_requests)
        )
        self.assertLessEqual(max(session.concurrent_request_counts), 1)

    def test_monitoring_subscription_timeout_keeps_base_worker_ready(self) -> None:
        config = SimpleNamespace(
            bar_minutes=5,
            longbridge_serve_binary=Path("/tmp/longbridge"),
            longbridge_serve_response_timeout_seconds=1,
            longbridge_serve_batch_size=2,
            subscription_progress_deadline_seconds=1,
            subscription_request_interval_seconds=0,
            subscription_retry_count=0,
            subscription_retry_backoff_seconds=0,
            quote_region="cn",
        )
        output = queue.Queue()
        with (
            patch(
                "scripts.m15_longbridge_serve_transport_lib.load_config",
                return_value=config,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_symbols",
                return_value=("SPY.US",),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.configured_trading_symbols",
                return_value=("SPY.US",),
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.LongbridgeServeSession",
                _MonitoringTimeoutSession,
            ),
            patch(
                "scripts.m15_longbridge_serve_transport_lib.FiveMinuteBarBuilder",
                _FakeBuilder,
            ),
        ):
            longbridge_serve_quote_worker(
                "unused.json",
                output,
                _FakeStopEvent(),
                ("EXTRA.US",),
            )

        rows = []
        while not output.empty():
            rows.append(output.get_nowait())
        ready = next(row for row in rows if row["kind"] == "ready")
        self.assertEqual(ready["subscription_failed_symbols"], [])
        self.assertEqual(
            ready["position_monitoring_failed_symbols"], ["EXTRA.US"]
        )
        self.assertFalse(any(row["kind"] == "error" for row in rows))


if __name__ == "__main__":
    unittest.main()
