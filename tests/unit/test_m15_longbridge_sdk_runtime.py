from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.m15_longbridge_realtime_execution_lib import response_order_id
from scripts.m15_longbridge_sdk_runtime_lib import (
    FiveMinuteBarBuilder, MarketEventContext, SdkRealtimePaperClient, append_market_events, compact_market_events,
    fresh_market_events, sdk_config_from_oauth, sdk_endpoint_overrides, subscribe_private_trade_updates,
    subscribe_quote_and_trades,
)


class M15LongbridgeSdkRuntimeTest(unittest.TestCase):
    def test_sdk_quote_push_builds_final_five_minute_bar(self) -> None:
        builder = FiveMinuteBarBuilder()
        first = datetime(2026, 7, 14, 13, 31, tzinfo=UTC)
        self.assertEqual(builder.on_quote("AAPL.US", {"timestamp": int(first.timestamp()), "last_done": "200", "current_volume": 10}, received_at=first), [])
        last = datetime(2026, 7, 14, 13, 34, 59, tzinfo=UTC)
        self.assertEqual(builder.on_quote("AAPL.US", {"timestamp": int(last.timestamp()), "last_done": "202", "current_volume": 20}, received_at=last), [])
        rows = builder.flush(datetime(2026, 7, 14, 13, 35, 1, tzinfo=UTC))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_mode"], "longbridge_sdk_push")
        self.assertTrue(rows[0]["bar_final"])
        self.assertEqual(rows[0]["open"], "200")
        self.assertEqual(rows[0]["close"], "202")
        self.assertEqual(rows[0]["volume"], "30")
        self.assertEqual(rows[0]["received_at"], "2026-07-14T13:35:01Z")
        self.assertEqual(rows[0]["source_delivery_age_ms"], 2000)

    def test_cli_table_order_id_is_recognised(self) -> None:
        self.assertEqual(response_order_id([{"field": "Order ID", "value": "701234"}]), "701234")

    def test_sdk_event_append_does_not_rewrite_and_heartbeat_compacts(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = [{"event_id": f"event-{index}", "value": index} for index in range(5)]
            append_market_events(path, rows, keep_lines=3)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 5)
            compact_market_events(path, 3)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn('"event-4"', lines[-1])

    def test_delayed_sdk_push_does_not_enter_realtime_event_stream(self) -> None:
        rows = [{"event_id": "fresh", "source_delivery_age_ms": 1999}, {"event_id": "late", "source_delivery_age_ms": 2001}]
        self.assertEqual([row["event_id"] for row in fresh_market_events(rows, 2000)], ["fresh"])

    def test_subscribe_uses_the_installed_sdk_two_argument_contract(self) -> None:
        class QuoteContext:
            def __init__(self) -> None:
                self.calls = []

            def subscribe(self, symbols, subscription_types) -> None:
                self.calls.append((symbols, subscription_types))

        quote = QuoteContext()
        subscribe_quote_and_trades(quote, ["AAPL.US"], ["Quote", "Trade"])
        self.assertEqual(quote.calls, [(["AAPL.US"], ["Quote", "Trade"])])

    def test_subscription_batches_large_universe_without_a_single_large_request(self) -> None:
        class QuoteContext:
            def __init__(self) -> None:
                self.calls = []

            def subscribe(self, symbols, subscription_types) -> None:
                self.calls.append((symbols, subscription_types))

        quote = QuoteContext()
        subscribe_quote_and_trades(quote, ["AAPL.US", "MSFT.US", "NVDA.US"], ["Quote"], batch_size=2)
        self.assertEqual(quote.calls, [(["AAPL.US", "MSFT.US"], ["Quote"]), (["NVDA.US"], ["Quote"])])

    def test_failed_batch_falls_back_to_single_symbols_without_stopping_healthy_symbols(self) -> None:
        class QuoteContext:
            def __init__(self) -> None:
                self.calls = []

            def subscribe(self, symbols, _subscription_types) -> None:
                self.calls.append(symbols)
                if symbols == ["AAPL.US", "BAD.US"] or symbols == ["BAD.US"]:
                    raise RuntimeError("symbol unavailable")

        quote = QuoteContext()
        failures = subscribe_quote_and_trades(
            quote,
            ["AAPL.US", "BAD.US"],
            ["Quote"],
            batch_size=2,
            retry_count=0,
        )
        self.assertEqual(failures, ["BAD.US"])
        self.assertIn(["AAPL.US"], quote.calls)

    def test_sdk_region_endpoints_are_explicit(self) -> None:
        self.assertEqual(
            sdk_endpoint_overrides("cn"),
            {
                "http_url": "https://openapi.longbridge.cn",
                "quote_ws_url": "wss://openapi-quote.longbridge.cn/v2",
                "trade_ws_url": "wss://openapi-trade.longbridge.cn/v2",
            },
        )
        self.assertEqual(sdk_endpoint_overrides("global")["http_url"], "https://openapi.longbridge.com")
        with self.assertRaisesRegex(ValueError, "unsupported_longbridge_sdk_region"):
            sdk_endpoint_overrides("invalid")

    def test_sdk_config_and_private_push_keep_trade_websocket_optional(self) -> None:
        class Config:
            @staticmethod
            def from_oauth(oauth, **kwargs):
                return {"oauth": oauth, **kwargs}

        class Sdk:
            class TopicType:
                Private = "Private"

        Sdk.Config = Config

        self.assertEqual(
            sdk_config_from_oauth(Sdk, "token", "cn")["quote_ws_url"],
            "wss://openapi-quote.longbridge.cn/v2",
        )

        class Trade:
            def __init__(self) -> None:
                self.calls = []

            def subscribe(self, topics) -> None:
                self.calls.append(topics)

        trade = Trade()
        self.assertFalse(subscribe_private_trade_updates(trade, Sdk, enabled=False))
        self.assertEqual(trade.calls, [])
        self.assertTrue(subscribe_private_trade_updates(trade, Sdk, enabled=True))
        self.assertEqual(trade.calls, [["Private"]])

    def test_market_event_context_is_bounded_and_deduplicated(self) -> None:
        context = MarketEventContext(maximum_rows=2)
        self.assertEqual(
            [row["event_id"] for row in context.append([{"event_id": "one"}, {"event_id": "two"}])],
            ["one", "two"],
        )
        self.assertEqual(context.append([{"event_id": "two"}]), [])
        context.append([{"event_id": "three"}])
        self.assertEqual([row["event_id"] for row in context.rows()], ["two", "three"])

    def test_sdk_client_submits_limit_if_touched_with_idempotent_signal_remark(self) -> None:
        class Enum:
            Buy = "Buy"
            Sell = "Sell"
            LO = "LO"
            LIT = "LIT"
            Day = "Day"
            RTHOnly = "RTHOnly"

        class Sdk:
            OrderSide = Enum
            OrderType = Enum
            TimeInForceType = Enum
            OutsideRTH = Enum

        class Response:
            order_id = "SDK-1"

        class Trade:
            def __init__(self) -> None:
                self.kwargs = {}

            def submit_order(self, **kwargs):
                self.kwargs = kwargs
                return Response()

        trade = Trade()
        result = SdkRealtimePaperClient(trade, Sdk()).submit_order({
            "side": "buy", "symbol": "AAPL.US", "order_type": "trigger_limit", "limit_price": "200.1",
            "trigger_price": "200", "quantity": "2", "signal_id": "signal-1",
        })
        self.assertTrue(result["submitted"])
        self.assertEqual(result["order_id"], "SDK-1")
        self.assertEqual(trade.kwargs["order_type"], "LIT")
        self.assertEqual(trade.kwargs["trigger_price"], Decimal("200"))
        self.assertEqual(trade.kwargs["outside_rth"], "RTHOnly")
