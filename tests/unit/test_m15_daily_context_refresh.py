from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from scripts.m15_longbridge_sdk_quote_transport_lib import DailyContextRefresh
from tests.unit.test_m15_longbridge_sdk_quote_transport import fake_sdk_module


class DailyRefreshTest(unittest.TestCase):
    def make(self, stage=None):
        config = SimpleNamespace(market_holidays=("2026-09-07",), daily_context_bars=2,
                                 daily_context_deadline_seconds=600)
        return DailyContextRefresh(config, ["SPY.US", "QQQ.US"], "2026-09-04", on_stage=stage)

    def rows(self, symbol, _candles, _now):
        return [{"symbol": symbol, "event_time": f"2026-09-{day:02d}T13:30:00Z"} for day in (4, 8)]

    def test_no_refresh_holiday_or_current_session_then_same_context_updates_all(self):
        phases = []
        refresh, quote, sdk = self.make(phases.append), Mock(), fake_sdk_module()
        for at in [datetime(2026, 9, 7, 20, 20, tzinfo=UTC), datetime(2026, 9, 8, 15, tzinfo=UTC)]:
            self.assertIsNone(refresh.step(quote, sdk, at))
        quote.candlesticks.assert_not_called()
        with patch("scripts.m15_longbridge_sdk_quote_transport_lib.daily_candlestick_event_rows", side_effect=self.rows):
            result = refresh.step(quote, sdk, datetime(2026, 9, 8, 20, 10, tzinfo=UTC))
        self.assertEqual(len(result), 4)
        self.assertEqual([call.args[0] for call in quote.candlesticks.call_args_list], ["SPY.US", "QQQ.US"])
        self.assertEqual(refresh.completed_date, "2026-09-08")
        self.assertEqual(phases, ["daily_refresh"])
        self.assertIsNone(refresh.step(quote, sdk, datetime(2026, 9, 9, 15, tzinfo=UTC)))

    def test_old_daily_response_fails_without_retry_or_partial_publication(self):
        refresh, quote = self.make(), Mock()
        with patch("scripts.m15_longbridge_sdk_quote_transport_lib.daily_candlestick_event_rows", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "daily_refresh_incomplete:SPY.US"):
                refresh.step(quote, fake_sdk_module(), datetime(2026, 9, 8, 20, 10, tzinfo=UTC))
        self.assertEqual(refresh.completed_date, "2026-09-04")
        with self.assertRaisesRegex(RuntimeError, "failed_no_retry"):
            refresh.step(quote, fake_sdk_module(), datetime(2026, 9, 8, 20, 11, tzinfo=UTC))
        self.assertEqual(quote.candlesticks.call_count, 1)

    def test_stale_context_at_next_open_cannot_fetch_in_hot_path(self):
        refresh, quote = self.make(), Mock()
        with self.assertRaisesRegex(RuntimeError, "daily_context_stale_at_market_open"):
            refresh.step(quote, fake_sdk_module(), datetime(2026, 9, 9, 13, 30, tzinfo=UTC))
        quote.candlesticks.assert_not_called()

    def test_deadline_is_not_reset_between_symbols(self):
        refresh, quote = self.make(), Mock()
        with patch("scripts.m15_longbridge_sdk_quote_transport_lib.time.monotonic", side_effect=[10, 11, 12, 611]), \
             patch("scripts.m15_longbridge_sdk_quote_transport_lib.daily_candlestick_event_rows", side_effect=self.rows):
            with self.assertRaisesRegex(RuntimeError, "daily_refresh_deadline_exceeded"):
                refresh.step(quote, fake_sdk_module(), datetime(2026, 9, 8, 20, 10, tzinfo=UTC))
        self.assertEqual(quote.candlesticks.call_count, 1)
        self.assertEqual(refresh.completed_date, "2026-09-04")

    def test_slow_sync_request_checked_on_return_without_fake_nonblocking_claim(self):
        phases = []
        refresh, quote = self.make(phases.append), Mock()
        with patch("scripts.m15_longbridge_sdk_quote_transport_lib.time.monotonic", side_effect=[10, 11, 611]):
            with self.assertRaisesRegex(RuntimeError, "daily_refresh_deadline_exceeded"):
                refresh.step(quote, fake_sdk_module(), datetime(2026, 9, 8, 20, 10, tzinfo=UTC))
        self.assertEqual(phases, ["daily_refresh"])
        self.assertEqual(quote.candlesticks.call_count, 1)
        self.assertEqual(refresh.completed_date, "2026-09-04")

    def test_sync_sdk_exception_propagates_and_cannot_restart_refresh(self):
        refresh, quote = self.make(), Mock()
        quote.candlesticks.side_effect = TimeoutError("sdk timeout")
        with self.assertRaises(TimeoutError):
            refresh.step(quote, fake_sdk_module(), datetime(2026, 9, 8, 20, 10, tzinfo=UTC))
        with self.assertRaisesRegex(RuntimeError, "failed_no_retry"):
            refresh.step(quote, fake_sdk_module(), datetime(2026, 9, 8, 20, 11, tzinfo=UTC))
        self.assertEqual(quote.candlesticks.call_count, 1)
