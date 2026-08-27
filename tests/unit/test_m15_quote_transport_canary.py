from __future__ import annotations

import queue
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.m15_quote_transport_canary_lib import (
    EventRecorder,
    cli_serve_subscription_fields,
    load_symbols,
    run_cli_serve_canary,
    run_sdk_canary,
    symbol_batches,
)


class FakeQuoteContext:
    def __init__(self, _config):
        self.rows = []
        self.quote_callback = None
        self.trade_callback = None

    def set_on_quote(self, callback):
        self.quote_callback = callback

    def set_on_trades(self, callback):
        self.trade_callback = callback

    def subscribe(self, symbols, _fields):
        self.rows.extend(SimpleNamespace(symbol=symbol) for symbol in symbols)
        for symbol in symbols:
            if self.quote_callback:
                self.quote_callback(symbol, object())
            if self.trade_callback:
                self.trade_callback(symbol, object())

    def subscriptions(self):
        return self.rows


class FailingBatchQuoteContext(FakeQuoteContext):
    def subscribe(self, symbols, fields):
        if len(symbols) > 1:
            raise RuntimeError("request timeout")
        super().subscribe(symbols, fields)


class FakeServeProcess:
    returncode = None

    def poll(self):
        return None


class FakeServeSession:
    instance = None

    def __init__(self, *_args, **_kwargs):
        self.process = FakeServeProcess()
        self.messages = queue.Queue()
        self.reader_errors = []
        self.stderr_tail = []
        self.sent = []
        self.kwargs = dict(_kwargs)
        self.__class__.instance = self

    def send(self, request):
        self.sent.append(request)

    def wait_for_response(self, request_id, _callback):
        request = next(row for row in self.sent if row["id"] == request_id)
        if request["method"] == "initialize":
            return {"id": request_id, "result": {"protocolVersion": "1"}}
        symbols = request.get("params", {}).get("symbols", [])
        if request["method"] == "quote.subscribe":
            return {
                "id": request_id,
                "result": {
                    "subscribed": [
                        {"symbol": symbol, "fields": ["quote", "trades"]}
                        for symbol in symbols
                    ]
                },
            }
        subscribed = [
            symbol
            for row in self.sent
            if row["method"] == "quote.subscribe"
            for symbol in row["params"]["symbols"]
        ]
        return {
            "id": request_id,
            "result": {
                "sub_list": [
                    {"symbol": symbol, "sub_type": [1, 4]}
                    for symbol in subscribed
                ]
            },
        }

    def drain_coalesced_quote_notifications(self):
        return []

    def transport_diagnostics(self):
        return {"coalesced_quote_pending_count": 0}

    def close(self, _request_id):
        self.process.returncode = 0


class M15QuoteTransportCanaryTest(unittest.TestCase):
    def test_load_symbols_normalizes_us_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "universe.json"
            path.write_text('{"symbols":["SPY","QQQ","AAPL"]}', encoding="utf-8")
            self.assertEqual(load_symbols(path, 3), ["SPY.US", "QQQ.US", "AAPL.US"])

    def test_callbacks_are_registered_before_subscription(self) -> None:
        sdk = SimpleNamespace(
            QuoteContext=FakeQuoteContext,
            SubType=SimpleNamespace(Quote="quote", Trade="trade"),
        )
        payload = run_sdk_canary(
            sdk=sdk,
            sdk_config=object(),
            symbols=["SPY.US", "QQQ.US", "AAPL.US"],
            fields=("quote", "trade"),
            duration_seconds=0,
        )
        self.assertEqual(payload["actual_subscription_count"], 3)
        self.assertEqual(payload["events"]["quote_event_count"], 3)
        self.assertEqual(payload["events"]["trade_event_count"], 3)

    def test_event_recorder_ignores_unknown_symbols(self) -> None:
        recorder = EventRecorder(["SPY.US"])
        recorder.record("QQQ.US", "quote")
        self.assertEqual(recorder.snapshot()["quote_event_count"], 0)

    def test_cli_serve_uses_plural_trades_wire_field(self) -> None:
        self.assertEqual(
            cli_serve_subscription_fields(("quote", "trade")),
            ["quote", "trades"],
        )

    def test_cli_serve_rejects_unknown_wire_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_cli_serve_field:depth"):
            cli_serve_subscription_fields(("depth",))

    def test_cli_serve_batches_large_universe(self) -> None:
        symbols = [f"SYM{index}.US" for index in range(147)]
        batches = symbol_batches(symbols, 50)
        self.assertEqual([len(batch) for batch in batches], [50, 50, 47])
        self.assertEqual([symbol for batch in batches for symbol in batch], symbols)

    def test_cli_serve_rejects_invalid_batch_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_batch_size:0"):
            symbol_batches(["SPY.US"], 0)

    def test_cli_serve_rejects_unknown_region_before_starting_process(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported_longbridge_region:invalid"):
            run_cli_serve_canary(
                binary="unused",
                symbols=["SPY.US"],
                fields=("quote",),
                duration_seconds=0,
                region="invalid",
            )

    def test_cli_serve_canary_reuses_bounded_production_transport(self) -> None:
        with patch(
            "scripts.m15_quote_transport_canary_lib.LongbridgeServeSession",
            FakeServeSession,
        ):
            payload = run_cli_serve_canary(
                binary="unused",
                symbols=["SPY.US", "QQQ.US", "AAPL.US"],
                fields=("quote", "trade"),
                duration_seconds=0,
                batch_size=2,
            )

        self.assertEqual(payload["actual_subscription_count"], 3)
        self.assertEqual(payload["missing_subscriptions"], [])
        self.assertEqual(payload["process_returncode"], 0)
        self.assertEqual(
            FakeServeSession.instance.kwargs["owner_value"],
            "price-action-trader-m15-canary",
        )
        self.assertEqual(
            [row["method"] for row in FakeServeSession.instance.sent],
            [
                "initialize",
                "quote.subscribe",
                "quote.subscribe",
                "quote.subscribe",
                "quote.subscribe",
                "quote.subscriptions",
            ],
        )
        self.assertEqual(payload["subscription_request_count"], 4)

    def test_subscription_failure_is_reported_instead_of_crashing(self) -> None:
        sdk = SimpleNamespace(
            QuoteContext=FailingBatchQuoteContext,
            SubType=SimpleNamespace(Quote="quote", Trade="trade"),
        )
        payload = run_sdk_canary(
            sdk=sdk,
            sdk_config=object(),
            symbols=["SPY.US", "QQQ.US"],
            fields=("quote",),
            duration_seconds=0,
            batch_size=2,
        )
        self.assertEqual(payload["actual_subscription_count"], 0)
        self.assertEqual(payload["subscribe_receipts"][0]["status"], "failed")
