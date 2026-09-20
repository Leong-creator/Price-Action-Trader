from __future__ import annotations

import queue
from datetime import UTC, datetime, timedelta
import os
import sys
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

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
    omit_trade_subscription = False
    emit_callbacks_during_subscribe = False

    def __init__(self, _config) -> None:
        self.received_config = _config
        self.events: list[str] = []
        self.quote_callback = None
        self.trade_callback = None
        self.subscribed: list[str] = []
        self.subscribe_calls: list[list[str]] = []
        self.subscribe_types: list[list[str]] = []
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
        self.subscribe_types.append(list(_sub_types))
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
        self.events.append("subscriptions")
        rows = self.subscribed[:-1] if self.omit_subscription else self.subscribed
        types = ["quote"] if self.omit_trade_subscription else ["quote", "trade"]
        return [SimpleNamespace(symbol=symbol, sub_types=types) for symbol in rows]

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
    module.Config = SimpleNamespace(from_oauth=lambda oauth: {"official_defaults": True, "oauth": oauth})
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
        FakeQuoteContext.omit_trade_subscription = False
        FakeQuoteContext.emit_callbacks_during_subscribe = False
        self.config = SimpleNamespace(
            quote_region="cn",
            daily_context_path=Path("unused-daily-context.jsonl"),
            daily_context_deadline_seconds=10,
            daily_context_bars=2,
            bar_minutes=5,
            market_holidays=("2026-09-07",),
            maximum_source_delivery_age_ms=2000,
            subscription_deadline_seconds=45,
        )

    def run_worker(
        self,
        *,
        stop_kind: str = "ready",
        cached_daily_rows: list[dict] | None = None,
        stage_ack=None,
        symbols: tuple[str, ...] | None = None,
    ) -> list[dict]:
        stop_event = threading.Event()
        output = CapturingQueue(stop_event, stop_kind=stop_kind)
        sdk = fake_sdk_module()
        longbridge = types.ModuleType("longbridge")
        longbridge.openapi = sdk
        with (
            patch.dict(sys.modules, {"longbridge": longbridge, "longbridge.openapi": sdk}),
            patch.object(transport, "load_config", return_value=self.config),
            patch.object(transport, "read_client_id", return_value="client-id"),
            patch.object(
                transport,
                "load_valid_daily_context_cache",
                return_value=list(cached_daily_rows or []),
            ),
            patch.object(
                transport,
                "configured_symbols",
                return_value=symbols or ("SPY.US", "QQQ.US", "AAPL.US"),
            ),
            patch.object(
                transport,
                "configured_trading_symbols",
                return_value=symbols or ("SPY.US", "QQQ.US", "AAPL.US"),
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
            transport.official_sdk_quote_worker("config.json", output, stop_event, stage_ack=stage_ack)
        return output.rows

    def test_one_context_registers_callbacks_before_single_subscription(self) -> None:
        rows = self.run_worker()
        self.assertEqual(len(FakeQuoteContext.instances), 1)
        context = FakeQuoteContext.instances[0]
        self.assertLess(context.events.index("set_quote_callback"), context.events.index("subscribe"))
        self.assertLess(context.events.index("set_trade_callback"), context.events.index("subscribe"))
        self.assertEqual(context.subscribe_calls, [["SPY.US", "QQQ.US", "AAPL.US"]])
        self.assertEqual(context.subscribe_types, [["quote", "trade"]])
        self.assertEqual(context.events.count("subscriptions"), 1)
        self.assertLess(context.events.index("subscribe"), context.events.index("subscriptions"))
        self.assertLess(context.events.index("subscriptions"), context.events.index("snapshot"))
        ready = next(row for row in rows if row["kind"] == "ready")
        self.assertEqual(ready["market_data_mode"], "official_sdk_subscription")
        self.assertEqual(ready["initial_snapshot_coverage"], "3/3")

    def test_official_config_defaults_and_single_stage_transition_evidence(self) -> None:
        rows = self.run_worker()
        self.assertTrue(FakeQuoteContext.instances[0].received_config["official_defaults"])
        stages = [row for row in rows if row["kind"] == "sdk_stage"]
        self.assertEqual([row["phase"] for row in stages], [
            "initializing", "daily_context", "subscribing", "initial_snapshot", "streaming"])
        clocks = [row["started_monotonic"] for row in stages]
        self.assertEqual(clocks, sorted(clocks))
        self.assertTrue(all(value > 0 for value in clocks))
        ready = next(row for row in rows if row["kind"] == "ready")
        self.assertEqual(ready["sdk_quote_context_api"], "QuoteContext")
        self.assertEqual(ready["sdk_config_source"], "Config.from_oauth_defaults")

    def test_endpoint_overrides_are_rejected_before_context_without_values(self) -> None:
        for name in ("LONGBRIDGE_REGION", "LONGBRIDGE_QUOTE_WS_URL", "LONGPORT_HTTP_URL", "LONGPORT_REGION"):
            with self.subTest(name=name), patch.dict(os.environ, {name: "secret-endpoint-value"}):
                rows = self.run_worker(stop_kind="error")
                error = next(row for row in rows if row["kind"] == "error")
                self.assertIn(name, error["reason"])
                self.assertNotIn("secret-endpoint-value", str(rows))
                self.assertEqual(FakeQuoteContext.instances, [])
                self.assertFalse(any(row["kind"] == "ready" for row in rows))

    def test_whitespace_endpoint_override_is_not_treated_as_official_default(self) -> None:
        with patch.dict(os.environ, {"LONGBRIDGE_HTTP_URL": " "}):
            with self.assertRaisesRegex(RuntimeError, "LONGBRIDGE_HTTP_URL"):
                transport.reject_quote_endpoint_overrides()

    def test_proxy_environment_is_not_mutated(self) -> None:
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://localhost:1234"}):
            self.run_worker()
            self.assertEqual(os.environ["HTTPS_PROXY"], "http://localhost:1234")

    def test_unacknowledged_stage_stops_before_any_native_context(self) -> None:
        ack = Mock()
        ack.wait.return_value = False
        rows = self.run_worker(stop_kind="error", stage_ack=ack)
        self.assertEqual(FakeQuoteContext.instances, [])
        ack.clear.assert_called_once()
        ack.wait.assert_called_once_with(timeout=5)
        error = next(row for row in rows if row["kind"] == "error")
        self.assertIn("stage_ack_timeout:initializing", error["reason"])

    def test_daily_sdk_error_stops_immediately_without_more_requests(self) -> None:
        with patch.object(FakeQuoteContext, "candlesticks", side_effect=TimeoutError("sdk timeout")) as fetch:
            rows = self.run_worker(stop_kind="error")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(FakeQuoteContext.instances[0].subscribe_calls, [])
        error = next(row for row in rows if row["kind"] == "error")
        self.assertIn("daily_context_request_failed:SPY.US", error["reason"])
        self.assertEqual(error["safe_error"]["error_category"], "request_timeout")

    def test_147_symbols_use_one_request_and_verify_complete_coverage(self) -> None:
        symbols = tuple(f"S{index}.US" for index in range(147))
        rows = self.run_worker(symbols=symbols)
        context = FakeQuoteContext.instances[0]
        self.assertEqual(context.subscribe_calls, [list(symbols)])
        self.assertEqual(context.subscribe_types, [["quote", "trade"]])
        self.assertEqual(context.events.count("subscriptions"), 1)
        self.assertLess(context.events.index("subscribe"), context.events.index("subscriptions"))
        self.assertLess(context.events.index("subscriptions"), context.events.index("snapshot"))
        ready = next(row for row in rows if row["kind"] == "ready")
        self.assertEqual(len(ready["subscribed_symbols"]), 147)
        self.assertEqual(ready["initial_snapshot_coverage"], "147/147")
        self.assertEqual([row["completed"] for row in rows if row["kind"] == "subscription_progress"], [147])

    def test_501_symbols_are_rejected_before_context_without_partial_subscriptions(self) -> None:
        rows = self.run_worker(symbols=tuple(f"S{index}.US" for index in range(501)), stop_kind="error")
        self.assertEqual(FakeQuoteContext.instances, [])
        error = next(row for row in rows if row["kind"] == "error")
        self.assertIn("target_count_out_of_range:501", error["reason"])

    def test_config_loaded_dotenv_override_rejected_before_quote_context(self) -> None:
        sdk = fake_sdk_module()
        def from_oauth(_oauth):
            os.environ["LONGPORT_QUOTE_WS_URL"] = "secret-dotenv-endpoint"
            return object()
        sdk.Config.from_oauth = from_oauth
        with patch.dict(os.environ, {}), patch(__name__ + ".fake_sdk_module", return_value=sdk):
            rows = self.run_worker(stop_kind="error")
        self.assertEqual(FakeQuoteContext.instances, [])
        error = next(row for row in rows if row["kind"] == "error")
        self.assertIn("LONGPORT_QUOTE_WS_URL", error["reason"])
        self.assertNotIn("secret-dotenv-endpoint", str(rows))

    def test_callback_failure_preserves_raw_entry_evidence(self) -> None:
        FakeQuoteContext.emit_callbacks_during_subscribe = True
        with patch.object(transport, "sdk_object_to_dict", side_effect=ValueError("bad_event")):
            rows = self.run_worker(stop_kind="error")
        error = next(row for row in rows if row["kind"] == "error")
        stages = error["pipeline_diagnostics"]["stages"]
        self.assertEqual(stages["raw_callback:SPY.US:quote"]["count"], 1)
        self.assertEqual(stages["normalization_error:SPY.US:quote"]["count"], 1)
        self.assertNotIn("enqueued:SPY.US:quote", stages)

    def test_subscription_failure_stops_without_retry(self) -> None:
        FakeQuoteContext.fail_subscribe = True
        rows = self.run_worker(stop_kind="error")
        context = FakeQuoteContext.instances[0]
        self.assertEqual(len(context.subscribe_calls), 1)
        error = next(row for row in rows if row["kind"] == "error")
        self.assertIn("official_sdk_quote_worker_failed:RuntimeError:request timeout", error["reason"])
        self.assertIn("request timeout", error["reason"])

    def test_quote_only_subscription_cannot_claim_trade_coverage(self) -> None:
        FakeQuoteContext.omit_trade_subscription = True
        rows = self.run_worker(stop_kind="error")
        self.assertNotIn("snapshot", FakeQuoteContext.instances[0].events)
        self.assertIn("official_sdk_subscription_incomplete", rows[-1]["reason"])

    def test_complete_daily_cache_skips_redundant_pull_requests(self) -> None:
        cached = [
            {"symbol": symbol, "timeframe": "1d"}
            for symbol in ("SPY", "QQQ", "AAPL")
            for _index in range(2)
        ]

        rows = self.run_worker(cached_daily_rows=cached)

        context = FakeQuoteContext.instances[0]
        self.assertFalse(any(event.startswith("daily:") for event in context.events))
        daily = next(row for row in rows if row["kind"] == "daily_context")
        self.assertEqual(daily["source_mode"], "official_sdk_daily_context_cache")
        self.assertEqual(len(daily["rows"]), 6)

    def test_heartbeat_carries_raw_reference_callback_activity(self) -> None:
        FakeQuoteContext.emit_callbacks_during_subscribe = True

        rows = self.run_worker(
            stop_kind="heartbeat",
            cached_daily_rows=[
                {"symbol": symbol, "timeframe": "1d"}
                for symbol in ("SPY", "QQQ", "AAPL")
                for _index in range(2)
            ],
        )

        heartbeat = next(row for row in rows if row["kind"] == "heartbeat")
        activity = {
            row["symbol"]: row for row in heartbeat["raw_reference_activity"]
        }
        self.assertEqual(set(activity), {"SPY.US", "QQQ.US"})
        self.assertTrue(activity["SPY.US"]["received_at"].endswith("Z"))
        self.assertIn(
            activity["QQQ.US"]["source_mode"],
            {"official_sdk_raw_quote_callback", "official_sdk_raw_trade_callback"},
        )

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
            patch.object(transport, "load_valid_daily_context_cache", return_value=[]),
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

    def test_daily_context_deadline_names_unprocessed_symbols(self) -> None:
        self.config.daily_context_deadline_seconds = 0

        rows = self.run_worker(stop_kind="error")

        error = next(row for row in rows if row["kind"] == "error")
        self.assertIn(
            "official_sdk_daily_context_deadline_exceeded:SPY.US,QQQ.US,AAPL.US",
            error["reason"],
        )
        self.assertEqual(FakeQuoteContext.instances[0].subscribe_calls, [])

    def test_transport_has_no_cli_or_account_dependency(self) -> None:
        source = Path(transport.__file__).read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)
        self.assertNotIn("longbridge serve", source)
        self.assertNotIn("TradeContext", source)
        self.assertNotIn("local_ledger", source)

    def test_critical_messages_cannot_silently_disappear(self) -> None:
        real_emit = transport._emit
        for kind in ("daily_context", "quote_state_batch", "ready"):
            with self.subTest(kind=kind):
                def emit(output, payload, *, critical=False):
                    if payload["kind"] == kind:
                        return False
                    return real_emit(output, payload, critical=critical)
                with patch.object(transport, "_emit", side_effect=emit):
                    rows = self.run_worker(stop_kind="error")
                self.assertEqual(rows[-1]["kind"], "error")
                self.assertIn("delivery_failed", rows[-1]["reason"])

    @staticmethod
    def trade_payload(source_at, **overrides):
        return {"trades": [{"timestamp": source_at, "price": "100", "volume": 5,
                            "trade_session": "Intraday", "trade_type": "", **overrides}]}

    def test_trade_delivery_2000_ms_is_accepted(self) -> None:
        source = datetime(2026, 9, 21, 14, 1, tzinfo=UTC)
        builder = transport.FiveMinuteBarBuilder(boundary_batch_mode=True)
        builder.on_trade("SPY.US", self.trade_payload(source), received_at=source+timedelta(milliseconds=2000),
                         maximum_source_delivery_age_ms=2000)
        self.assertEqual(builder.open_bar_count, 1)

    def test_trade_delivery_2001_ms_and_same_bucket_239_seconds_rejected(self) -> None:
        source = datetime(2026, 9, 21, 14, 1, tzinfo=UTC)
        for age in (2001, 239000):
            with self.subTest(age_ms=age):
                builder = transport.FiveMinuteBarBuilder(boundary_batch_mode=True)
                with self.assertRaisesRegex(ValueError, "trade_source_delivery_age_exceeded"):
                    builder.on_trade("SPY.US", self.trade_payload(source), received_at=source+timedelta(milliseconds=age),
                                     maximum_source_delivery_age_ms=2000)
                self.assertEqual(builder.open_bar_count, 0)

    def test_timely_early_trade_still_finalizes_normally(self) -> None:
        from scripts.m15_longbridge_sdk_runtime_lib import fresh_market_events
        source = datetime(2026, 9, 21, 14, 1, tzinfo=UTC)
        finalized = datetime(2026, 9, 21, 14, 5, 2, tzinfo=UTC)
        builder = transport.FiveMinuteBarBuilder(boundary_batch_mode=True)
        builder.on_trade("SPY.US", self.trade_payload(source), received_at=source,
                         maximum_source_delivery_age_ms=2000, processed_at=source+timedelta(seconds=1))
        bars = builder.complete_boundary(["SPY.US"], finalized)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["close"], "100")
        self.assertEqual(bars[0]["market_data_blocked_reason"], "")
        self.assertEqual(fresh_market_events(bars, 2000, now=finalized+timedelta(milliseconds=100)), bars)

    def test_delivery_check_ignores_non_actionable_trades(self) -> None:
        received = datetime(2026, 9, 21, 14, 4, tzinfo=UTC)
        cases = [
            (datetime(2026, 9, 21, 14, 1, tzinfo=UTC), {"trade_session": "Pre"}, None, ()),
            (datetime(2026, 9, 21, 14, 1, tzinfo=UTC), {"trade_type": "M"}, None, ()),
            (datetime(2026, 9, 21, 13, 0, tzinfo=UTC), {}, None, ()),
            (datetime(2026, 9, 20, 14, 1, tzinfo=UTC), {}, None, ()),
            (datetime(2026, 9, 21, 14, 1, tzinfo=UTC), {}, None, ("2026-09-21",)),
            (datetime(2026, 9, 21, 14, 1, tzinfo=UTC), {}, datetime(2026, 9, 21, 14, 5, tzinfo=UTC), ()),
        ]
        for source, changes, not_before, holidays in cases:
            with self.subTest(source=source, changes=changes, not_before=not_before, holidays=holidays):
                builder = transport.FiveMinuteBarBuilder(boundary_batch_mode=True,
                    complete_bar_open_not_before=not_before, market_holidays=holidays)
                self.assertEqual(builder.on_trade("SPY.US", self.trade_payload(source, **changes),
                    received_at=received, maximum_source_delivery_age_ms=2000,
                    processed_at=received+timedelta(seconds=300)), [])
                self.assertEqual(builder.open_bar_count, 0)

    def test_stale_volume_only_trade_is_rejected(self) -> None:
        source = datetime(2026, 9, 21, 14, 1, tzinfo=UTC)
        builder = transport.FiveMinuteBarBuilder(boundary_batch_mode=True)
        with self.assertRaisesRegex(ValueError, "trade_source_delivery_age_exceeded"):
            builder.on_trade("SPY.US", self.trade_payload(source, trade_type="I"),
                received_at=source+timedelta(seconds=3), maximum_source_delivery_age_ms=2000)
        self.assertEqual(builder.open_bar_count, 0)

    def test_trade_delivery_and_queue_each_allow_2000_ms(self) -> None:
        source = datetime(2026, 9, 21, 14, 1, tzinfo=UTC)
        received = source+timedelta(milliseconds=2000)
        builder = transport.FiveMinuteBarBuilder(boundary_batch_mode=True)
        builder.on_trade("SPY.US", self.trade_payload(source), received_at=received,
            maximum_source_delivery_age_ms=2000, processed_at=received+timedelta(milliseconds=2000))
        self.assertEqual(builder.open_bar_count, 1)

    def test_trade_processing_2001_ms_rejected_before_bar_update(self) -> None:
        source = datetime(2026, 9, 21, 14, 1, tzinfo=UTC)
        builder = transport.FiveMinuteBarBuilder(boundary_batch_mode=True)
        with self.assertRaisesRegex(ValueError, "trade_processing_backlog"):
            builder.on_trade("SPY.US", self.trade_payload(source), received_at=source,
                maximum_source_delivery_age_ms=2000, processed_at=source+timedelta(milliseconds=2001))
        self.assertEqual(builder.open_bar_count, 0)

    def test_worker_propagates_242_second_queue_backlog_without_bars(self) -> None:
        class Clock(datetime):
            current = datetime(2026, 9, 21, 14, 5, 2, tzinfo=UTC)
            @classmethod
            def now(cls, tz=None):
                return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)
        real_emit = transport._emit
        def emit(output, payload, **kwargs):
            result = real_emit(output, payload, **kwargs)
            if payload.get("kind") == "ready":
                Clock.current = datetime(2026, 9, 21, 14, 11, tzinfo=UTC)
                FakeQuoteContext.instances[0].trade_callback("SPY.US", self.trade_payload(Clock.current))
                Clock.current = datetime(2026, 9, 21, 14, 15, 2, tzinfo=UTC)
            return result
        with patch.object(transport, "datetime", Clock), patch.object(transport, "_emit", side_effect=emit):
            rows = self.run_worker(stop_kind="error")
        self.assertEqual(len(FakeQuoteContext.instances), 1)
        self.assertEqual(rows[-1]["kind"], "error")
        self.assertIn("trade_processing_backlog", rows[-1]["reason"])
        self.assertNotIn("trade_source_delivery_age_exceeded", rows[-1]["reason"])
        self.assertFalse(any(row["kind"] == "bars" for row in rows))
        self.assertIn("pipeline_diagnostics", rows[-1])

    def test_worker_propagates_late_trade_error_without_bars_or_retry(self) -> None:
        class Clock(datetime):
            current = datetime(2026, 9, 21, 14, 5, 2, tzinfo=UTC)
            @classmethod
            def now(cls, tz=None):
                return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)
        real_emit = transport._emit
        def emit(output, payload, **kwargs):
            result = real_emit(output, payload, **kwargs)
            if payload.get("kind") == "ready":
                Clock.current = datetime(2026, 9, 21, 14, 14, 59, tzinfo=UTC)
                FakeQuoteContext.instances[0].trade_callback("SPY.US",
                    self.trade_payload(datetime(2026, 9, 21, 14, 11, tzinfo=UTC)))
            return result
        with patch.object(transport, "datetime", Clock), patch.object(transport, "_emit", side_effect=emit):
            rows = self.run_worker(stop_kind="error")
        self.assertEqual(len(FakeQuoteContext.instances), 1)
        self.assertEqual(FakeQuoteContext.instances[0].subscribe_calls, [["SPY.US", "QQQ.US", "AAPL.US"]])
        self.assertEqual(rows[-1]["kind"], "error")
        self.assertIn("trade_source_delivery_age_exceeded", rows[-1]["reason"])
        self.assertFalse(any(row["kind"] == "bars" for row in rows))
        self.assertIn("pipeline_diagnostics", rows[-1])

    def test_callback_overflow_stops_without_another_context(self) -> None:
        FakeQuoteContext.emit_callbacks_during_subscribe = True
        with patch.object(transport, "CALLBACK_QUEUE_MAXSIZE", 1):
            rows = self.run_worker(stop_kind="error")
        self.assertEqual(len(FakeQuoteContext.instances), 1)
        self.assertIn("callback_queue_overflow", rows[-1]["reason"])


if __name__ == "__main__":
    unittest.main()
