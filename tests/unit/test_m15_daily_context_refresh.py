from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
import threading
import time

from scripts.m15_longbridge_sdk_quote_transport_lib import DailyContextRefresh
from tests.unit.test_m15_longbridge_sdk_quote_transport import fake_sdk_module


class DailyRefreshTest(unittest.TestCase):
    def make(self):
        config = SimpleNamespace(market_holidays=("2026-09-07",), daily_context_bars=2,
                                 daily_context_deadline_seconds=600)
        return DailyContextRefresh(config, ["SPY.US", "QQQ.US"], "2026-09-04")

    def inline_thread(self, *, target, args, **_kwargs):
        return SimpleNamespace(start=lambda: target(*args))

    def rows(self, symbol, _candles, _now):
        return [{"symbol": symbol, "event_time": f"2026-09-{day:02d}T13:30:00Z"} for day in (4, 8)]

    def test_no_refresh_holiday_or_during_session_then_same_context_updates_all(self):
        refresh, quote, sdk = self.make(), Mock(), fake_sdk_module()
        for at in [datetime(2026, 9, 7, 20, 20, tzinfo=UTC), datetime(2026, 9, 8, 15, tzinfo=UTC)]:
            self.assertIsNone(refresh.step(quote, sdk, at))
        quote.candlesticks.assert_not_called()
        with (patch("scripts.m15_longbridge_sdk_quote_transport_lib.daily_candlestick_event_rows", side_effect=self.rows),
              patch("scripts.m15_longbridge_sdk_quote_transport_lib.threading.Thread", side_effect=self.inline_thread)):
            at = datetime(2026, 9, 8, 20, 10, tzinfo=UTC)
            result = refresh.step(quote, sdk, at)
        self.assertEqual(len(result), 4)
        self.assertEqual(quote.candlesticks.call_count, 2)
        self.assertEqual(refresh.completed_date, "2026-09-08")
        self.assertIsNone(refresh.step(quote, sdk, datetime(2026, 9, 9, 15, tzinfo=UTC)))

    def test_old_daily_response_fails_without_retry_or_partial_publication(self):
        refresh = self.make()
        with (patch("scripts.m15_longbridge_sdk_quote_transport_lib.daily_candlestick_event_rows", return_value=[]),
              patch("scripts.m15_longbridge_sdk_quote_transport_lib.threading.Thread", side_effect=self.inline_thread)):
            with self.assertRaisesRegex(RuntimeError, "daily_refresh_incomplete:SPY.US"):
                refresh.step(Mock(), fake_sdk_module(), datetime(2026, 9, 8, 20, 10, tzinfo=UTC))
        self.assertEqual(refresh.rows, [])

    def test_unfinished_context_at_next_open_cannot_fetch_in_hot_path(self):
        refresh, quote = self.make(), Mock()
        with self.assertRaisesRegex(RuntimeError, "daily_context_stale_at_market_open"):
            refresh.step(quote, fake_sdk_module(), datetime(2026, 9, 9, 13, 30, tzinfo=UTC))
        quote.candlesticks.assert_not_called()

    def test_deadline_is_not_reset_between_symbols(self):
        refresh = self.make()
        refresh.target_date, refresh.deadline = "2026-09-08", 610
        refresh.result.put_nowait(self.rows("SPY.US", None, None))
        with patch("scripts.m15_longbridge_sdk_quote_transport_lib.time.monotonic", return_value=611):
            with self.assertRaisesRegex(RuntimeError, "daily_refresh_deadline_exceeded"):
                refresh.step(Mock(), fake_sdk_module(), datetime(2026, 9, 8, 20, 11, tzinfo=UTC))
        self.assertEqual(refresh.completed_date, "2026-09-04")

    def test_slow_sdk_request_does_not_block_processing_loop(self):
        refresh, quote, release, entered = self.make(), Mock(), threading.Event(), threading.Event()
        def slow(*_args):
            entered.set()
            release.wait(2)
            return []
        quote.candlesticks.side_effect = slow
        at = datetime(2026, 9, 8, 20, 10, tzinfo=UTC)
        try:
            started = time.monotonic()
            self.assertIsNone(refresh.step(quote, fake_sdk_module(), at))
            self.assertTrue(entered.wait(1))
            for _ in range(30):
                self.assertIsNone(refresh.step(quote, fake_sdk_module(), at))
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(quote.candlesticks.call_count, 1)
        finally:
            release.set()
        self.assertIsInstance(refresh.result.get(timeout=2), RuntimeError)
