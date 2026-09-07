"""Offline SDK callback replay; never connects to a broker or writes live artifacts."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
import sys
import types
import unittest
from unittest.mock import patch

from scripts import m15_longbridge_sdk_quote_transport_lib as transport
from scripts.m15_longbridge_sdk_runtime_lib import configured_symbols, load_config
from scripts.run_m15_longbridge_sdk_runtime import realtime_boundary_is_complete
from tests.unit.test_m15_longbridge_sdk_quote_transport import FakeQuoteContext, fake_sdk_module


class OfflineMarketSessionTest(unittest.TestCase):
    def test_production_worker_holiday_then_147_symbols_78_boundaries(self):
        config = load_config()
        symbols = configured_symbols(config)
        self.assertEqual(len(symbols), 147)
        opening = datetime(2026, 9, 8, 13, 30, tzinfo=UTC)
        schedule = [(datetime(2026, 9, 7, h, m, tzinfo=UTC), None) for h, m in [(13, 35), (19, 55), (20, 0)]]
        for i in range(78):
            start = opening + timedelta(minutes=i * 5)
            schedule.extend((start + timedelta(seconds=s), price) for s, price in [(0, "100"), (60, "102"), (120, "99"), (240, "101")])
            schedule.append((start + timedelta(minutes=5, milliseconds=2100), None))

        class Clock(datetime):
            current = datetime(2026, 9, 7, 13, 29, tzinfo=UTC)

            @classmethod
            def now(cls, tz=None):
                return cls.current.astimezone(tz or UTC)

        class Stop:
            done = False
            index = 0

            def is_set(self):
                return self.done

            def wait(self, _timeout):
                if self.index == len(schedule):
                    self.done = True
                    return True
                Clock.current, price = schedule[self.index]
                self.index += 1
                if price:
                    ctx = FakeQuoteContext.instances[0]
                    for symbol in symbols:
                        ctx.quote_callback(symbol, SimpleNamespace(last_done=price, timestamp=Clock.current))
                        ctx.trade_callback(symbol, SimpleNamespace(trades=[SimpleNamespace(
                            price=price, volume=10, timestamp=Clock.current, trade_session="Intraday")]))
                return False

        class Output:
            rows = []

            def put(self, payload, timeout=None):
                self.rows.append(payload)

            def put_nowait(self, payload):
                self.rows.append(payload)

        sdk = fake_sdk_module()
        module = types.ModuleType("longbridge")
        module.openapi = sdk
        FakeQuoteContext.instances = []
        FakeQuoteContext.fail_subscribe = False
        FakeQuoteContext.omit_subscription = False
        FakeQuoteContext.omit_trade_subscription = False
        FakeQuoteContext.emit_callbacks_during_subscribe = False
        output = Output()
        cached = [{"symbol": s.removesuffix(".US"), "timeframe": "1d"} for s in symbols for _ in range(60)]
        started = perf_counter()
        with (patch.dict(sys.modules, {"longbridge": module, "longbridge.openapi": sdk}),
              patch.object(transport, "load_config", return_value=config),
              patch.object(transport, "read_client_id", return_value="offline"),
              patch.object(transport, "sdk_config_from_oauth", return_value=object()),
              patch.object(transport, "load_valid_daily_context_cache", return_value=cached),
              patch.object(transport, "datetime", Clock)):
            transport.official_sdk_quote_worker("offline-only", output, Stop())
        self.assertFalse([m for m in output.rows if m["kind"] == "error"])
        batches = [m["rows"] for m in output.rows if m["kind"] == "bars"]
        self.assertEqual(len(FakeQuoteContext.instances), 1)
        self.assertEqual(len(batches), 78)
        self.assertEqual(sum(map(len, batches)), 11466)
        for i, batch in enumerate(batches):
            self.assertTrue(realtime_boundary_is_complete(batch, symbols))
            expected = opening + timedelta(minutes=(i + 1) * 5)
            for row in batch:
                self.assertEqual(datetime.fromisoformat(row["event_time"].replace("Z", "+00:00")), expected)
                self.assertEqual([row[k] for k in ("open", "high", "low", "close", "volume")], ["100", "102", "99", "101", "40"])
                self.assertEqual(row["market_data_blocked_reason"], "")
        print(f"Offline SDK replay: 147 symbols, 78 boundaries, 11466 verified bars; wall_seconds={perf_counter()-started:.3f}")
