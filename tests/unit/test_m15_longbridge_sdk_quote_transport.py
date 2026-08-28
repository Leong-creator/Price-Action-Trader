from __future__ import annotations

import queue
import sys
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import m15_longbridge_sdk_quote_transport_lib as transport


class CapturingQueue:
    def __init__(self, stop_event: threading.Event, stop_kind: str = "ready") -> None:
        self.rows: list[dict] = []
        self.stop_event = stop_event
        self.stop_kind = stop_kind

    def put(self, payload, timeout=None):
        self.put_nowait(payload)

    def put_nowait(self, payload):
        self.rows.append(payload)
        if payload.get("kind") == self.stop_kind:
            self.stop_event.set()


class FakeQuoteContext:
    instances: list["FakeQuoteContext"] = []
    fail_subscribe = False
    omit_subscription = False
    emit_callbacks_during_subscribe = False

    def __init__(self, _config) -> None:
        self.events: list[str] = []
        self.quote_callback = None
        self.trade_callback = None
        self.subscribed: list[str] = []
        self.subscribe_calls: list[list[str]] = []
        self.__class__.instances.append(self)

    def set_on_quote(self, callback) -> None:
        self.events.append("set_quote_callback")
        self.quote_callback = callback

    def set_on_trades(self, callback) -> None:
        self.events.append("set_trade_callback")
        self.trade_callback = callback

    def candlesticks(self, symbol, *_args):
        self.events.append(f"daily:{symbol}")
        return [object(), object()]

    def subscribe(self, symbols, _sub_types) -> None:
        self.events.append("subscribe")
        self.subscribe_calls.append(list(symbols))
        if self.quote_callback is None or self.trade_callback is None:
            raise AssertionError("callbacks_must_be_registered_before_subscription")
        if self.fail_subscribe:
            raise RuntimeError("request timeout")
        self.subscribed.extend(symbols)
        if self.emit_callbacks_during_subscribe:
            for symbol in symbols:
                self.quote_callback(symbol, {"symbol": symbol, "last_done": "1"})
                self.trade_callback(symbol, {"symbol": symbol, "price": "1", "volume": 1})

    def subscriptions(self):
        rows = self.subscribed[:-1] if self.omit_subscription else self.subscribed
        return [SimpleNamespace(symbol=symbol) for symbol in rows]

    def quote(self, symbols):
        self.events.append("snapshot")
        return [
            {
                "symbol": symbol,
                "timestamp": "2026-08-28T13:30:00Z",
                "last_done": "100",
                "open": "100",
                "high": "100",
                "low": "100",
                "volume": 1,
            }
            for symbol in symbols
        ]


def fake_sdk_module() -> types.ModuleType:
    module = types.ModuleType("longbridge.openapi")
    module.QuoteContext = FakeQuoteContext
    module.OAuthBuilder = lambda _client_id: SimpleNamespace(
        build=lambda _callback: object()
    )
    module.SubType = SimpleNamespace(Quote="quote", Trade="trade")
    module.Period = SimpleNamespace(Day="day")
    module.AdjustType = SimpleNamespace(NoAdjust="none")
    module.TradeSessions = SimpleNamespace(Intraday="intraday")
    return module


class OfficialSdkQuoteTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeQuoteContext.instances = []
        FakeQuoteContext.fail_subscribe = False
        FakeQuoteContext.omit_subscription = False
        FakeQuoteContext.emit_callbacks_during_subscribe = False
        self.config = SimpleNamespace(
            quote_region="cn",
            daily_context_deadline_seconds=10,
            daily_context_bars=2,
            sdk_subscribe_batch_size=2,
            bar_minutes=5,
        )

    def run_worker(self, *, stop_kind: str = "ready") -> list[dict]:
        stop_event = threading.Event()
        output = CapturingQueue(stop_event, stop_kind=stop_kind)
        sdk = fake_sdk_module()
        longbridge = types.ModuleType("longbridge")
        longbridge.openapi = sdk
        with (
            patch.dict(sys.modules, {"longbridge": longbridge, "longbridge.openapi": sdk}),
            patch.object(transport, "load_config", return_value=self.config),
            patch.object(transport, "read_client_id", return_value="client-id"),
            patch.object(transport, "sdk_config_from_oauth", return_value=object()),
            patch.object(
                transport,
                "configured_symbols",
                return_value=("SPY.US", "QQQ.US", "AAPL.US"),
            ),
            patch.object(
                transport,
                "configured_trading_symbols",
                return_value=("SPY.US", "QQQ.US", "AAPL.US"),
            ),
            patch.object(
                transport,
                "daily_candlestick_event_rows",
                side_effect=lambda symbol, _candles, _now: [
                    {"symbol": symbol, "timeframe": "1d"},
                    {"symbol": symbol, "timeframe": "1d"},
                ],
            ),
        ):
            transport.official_sdk_quote_worker("config.json", output, stop_event)
        return output.rows

    def test_one_context_registers_callbacks_before_batched_subscription(self) -> None:
        rows = self.run_worker()
        self.assertEqual(len(FakeQuoteContext.instances), 1)
        context = FakeQuoteContext.instances[0]
        self.assertLess(context.events.index("set_quote_callback"), context.events.index("subscribe"))
        self.assertLess(context.events.index("set_trade_callback"), context.events.index("subscribe"))
        self.assertEqual(context.subscribe_calls, [["SPY.US", "QQQ.US"], ["AAPL.US"]])
        self.assertLess(context.events.index("subscribe"), context.events.index("snapshot"))
        ready = next(row for row in rows if row["kind"] == "ready")
        self.assertEqual(ready["market_data_mode"], "official_sdk_subscription")
        self.assertEqual(ready["initial_snapshot_coverage"], "3/3")

    def test_subscription_failure_stops_without_retry(self) -> None:
        FakeQuoteContext.fail_subscribe = True
        rows = self.run_worker(stop_kind="error")
        context = FakeQuoteContext.instances[0]
        self.assertEqual(len(context.subscribe_calls), 1)
        error = next(row for row in rows if row["kind"] == "error")
        self.assertIn("official_sdk_quote_worker_failed:RuntimeError:request timeout", error["reason"])

    def test_incomplete_subscription_stops_before_snapshot(self) -> None:
        FakeQuoteContext.omit_subscription = True
        rows = self.run_worker(stop_kind="error")
        context = FakeQuoteContext.instances[0]
        self.assertNotIn("snapshot", context.events)
        error = next(row for row in rows if row["kind"] == "error")
        self.assertIn("official_sdk_subscription_incomplete:AAPL.US", error["reason"])

    def test_daily_context_failure_stops_before_subscription(self) -> None:
        stop_event = threading.Event()
        output = CapturingQueue(stop_event, stop_kind="error")
        sdk = fake_sdk_module()
        longbridge = types.ModuleType("longbridge")
        longbridge.openapi = sdk
        with (
            patch.dict(sys.modules, {"longbridge": longbridge, "longbridge.openapi": sdk}),
            patch.object(transport, "load_config", return_value=self.config),
            patch.object(transport, "read_client_id", return_value="client-id"),
            patch.object(transport, "sdk_config_from_oauth", return_value=object()),
            patch.object(transport, "configured_symbols", return_value=("SPY.US",)),
            patch.object(transport, "configured_trading_symbols", return_value=("SPY.US",)),
            patch.object(transport, "daily_candlestick_event_rows", return_value=[]),
        ):
            transport.official_sdk_quote_worker("config.json", output, stop_event)
        self.assertEqual(FakeQuoteContext.instances[0].subscribe_calls, [])
        self.assertIn(
            "official_sdk_daily_context_incomplete:SPY.US",
            next(row for row in output.rows if row["kind"] == "error")["reason"],
        )

    def test_transport_has_no_cli_or_account_dependency(self) -> None:
        source = Path(transport.__file__).read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)
        self.assertNotIn("longbridge serve", source)
        self.assertNotIn("TradeContext", source)
        self.assertNotIn("local_ledger", source)


if __name__ == "__main__":
    unittest.main()
