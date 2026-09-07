from datetime import UTC, datetime, timedelta
import unittest

from types import SimpleNamespace
from scripts.m15_longbridge_sdk_runtime_lib import FiveMinuteBarBuilder, sdk_object_to_dict


class PreopenBarIntegrityTest(unittest.TestCase):
    def builder(self):
        return FiveMinuteBarBuilder(boundary_batch_mode=True, market_holidays=("2026-09-07",))

    def trade(self, builder, stamp, price, *, received=None):
        at = datetime.fromisoformat(stamp)
        return builder.on_trade("SPY.US", {"trades": [{"timestamp": at, "price": price, "volume": 10}]}, received_at=received or at)

    def test_holiday_cannot_emit_placeholder_bars(self):
        builder = self.builder()
        at = datetime(2026, 9, 7, 13, 35, tzinfo=UTC)
        builder.seed_quote("SPY.US", {"last_done": "100"}, received_at=at)
        self.assertEqual(builder.complete_boundary(["SPY.US"], at), [])

    def test_out_of_order_ticks_use_event_time_for_open_and_close(self):
        builder = self.builder()
        for stamp, price in [("2026-09-08T13:32:00+00:00", "102"),
                             ("2026-09-08T13:30:00+00:00", "100"),
                             ("2026-09-08T13:31:00+00:00", "101")]:
            self.trade(builder, stamp, price)
        row = builder.complete_boundary(["SPY.US"], datetime(2026, 9, 8, 13, 35, tzinfo=UTC))[0]
        self.assertEqual((row["open"], row["high"], row["low"], row["close"], row["volume"]), ("100", "102", "100", "102", "30"))

    def test_tick_for_closed_bar_cannot_create_hidden_unclosed_bar(self):
        builder = self.builder()
        self.trade(builder, "2026-09-08T13:32:00+00:00", "102")
        at = datetime(2026, 9, 8, 13, 35, tzinfo=UTC)
        builder.complete_boundary(["SPY.US"], at)
        with self.assertRaisesRegex(ValueError, "trade_after_bar_finalized"):
            self.trade(builder, "2026-09-08T13:34:00+00:00", "101", received=at + timedelta(seconds=3))
        self.assertEqual(builder.open_bar_count, 0)

    def test_future_bar_is_not_accepted(self):
        builder = self.builder()
        with self.assertRaisesRegex(ValueError, "trade_timestamp_in_future"):
            self.trade(builder, "2026-09-08T13:40:00+00:00", "101", received=datetime(2026, 9, 8, 13, 31, tzinfo=UTC))

    def test_official_trade_conditions_preserve_volume_without_price_spikes(self):
        builder = self.builder()
        at = datetime(2026, 9, 8, 13, 31, tzinfo=UTC)
        trades = [SimpleNamespace(price=p, volume=v, timestamp=at, trade_type=t, trade_session="Intraday")
                  for p, v, t in [("100", 10, ""), ("200", 7, "I"), ("1", 5, "P")]]
        payload = sdk_object_to_dict(SimpleNamespace(trades=trades))
        self.assertEqual([r["trade_type"] for r in payload["trades"]], ["", "I", "P"])
        builder.on_trade("SPY.US", payload, received_at=at)
        row = builder.complete_boundary(["SPY.US"], at.replace(minute=35))[0]
        self.assertEqual([row[k] for k in ("open", "high", "low", "close", "volume")], ["100", "100", "100", "100", "17"])

    def test_volume_only_before_regular_trade_and_identical_legal_trades(self):
        builder = self.builder()
        at = datetime(2026, 9, 8, 13, 31, tzinfo=UTC)
        builder.on_trade("SPY.US", {"trades": [{"price":"200", "volume":7, "trade_type":"I", "timestamp":at}]}, received_at=at)
        for _ in range(2):
            self.trade(builder, at.isoformat(), "100")
        row = builder.complete_boundary(["SPY.US"], at.replace(minute=35))[0]
        self.assertEqual((row["open"], row["close"], row["volume"]), ("100", "100", "27"))

    def test_settle_window_collects_boundary_arrivals(self):
        builder = FiveMinuteBarBuilder(boundary_batch_mode=True, boundary_settle_seconds=2)
        close = datetime(2026, 9, 8, 13, 35, tzinfo=UTC)
        self.assertEqual(builder.complete_boundary(["SPY.US"], close), [])
        self.trade(builder, (close-timedelta(seconds=1)).isoformat(), "100", received=close+timedelta(seconds=1))
        row = builder.complete_boundary(["SPY.US"], close+timedelta(seconds=2))[0]
        self.assertEqual(row["volume"], "10")

    def test_every_official_us_condition_has_correct_price_and_volume_role(self):
        at = datetime(2026, 9, 8, 13, 31, tzinfo=UTC)
        for condition in ["", "A", "B", "D", "E", "F", "K", "S", "X", "1", "C", "G", "H", "I", "V", "W", "P", "M", "Z"]:
            with self.subTest(condition=condition):
                builder = self.builder()
                self.trade(builder, at.isoformat(), "100")
                builder.on_trade("SPY.US", {"trades": [{"price": "200", "volume": 7,
                                 "trade_type": condition, "timestamp": at + timedelta(seconds=1)}]},
                                 received_at=at + timedelta(seconds=1))
                row = builder.complete_boundary(["SPY.US"], at.replace(minute=35))[0]
                price_forming = condition in {"", "A", "B", "D", "E", "F", "K", "S", "X", "1"}
                volume_forming = price_forming or condition in {"C", "G", "H", "I", "V", "W"}
                self.assertEqual(row["high"], "200" if price_forming else "100")
                self.assertEqual(row["volume"], "17" if volume_forming else "10")

    def test_volume_only_bar_is_not_eligible_for_strategy_entry(self):
        builder, at = self.builder(), datetime(2026, 9, 8, 13, 31, tzinfo=UTC)
        builder.seed_quote("SPY.US", {"last_done": "100"}, received_at=at)
        builder.on_trade("SPY.US", {"trades": [{"price": "200", "volume": 7, "trade_type": "I", "timestamp": at}]}, received_at=at)
        row = builder.complete_boundary(["SPY.US"], at.replace(minute=35))[0]
        self.assertEqual(row["close"], "100")
        self.assertEqual(row["volume"], "7")
        self.assertIn("no_price_forming_trade", row["market_data_blocked_reason"])

    def test_after_boundary_quote_cannot_reprice_previous_placeholder(self):
        for volume_only in (True, False):
            with self.subTest(volume_only=volume_only):
                builder = self.builder()
                at = datetime(2026, 9, 8, 13, 34, tzinfo=UTC)
                builder.seed_quote("SPY.US", {"last_done": "100", "timestamp": at}, received_at=at)
                if volume_only:
                    builder.on_trade("SPY.US", {"trades": [{"price": "200", "volume": 7, "trade_type": "I", "timestamp": at}]}, received_at=at)
                later = at.replace(minute=35, second=1)
                builder.seed_quote("SPY.US", {"last_done": "999", "timestamp": later}, received_at=later)
                row = builder.complete_boundary(["SPY.US"], later + timedelta(seconds=1))[0]
                self.assertEqual(row["close"], "100")
                self.assertEqual(row["source_event_at"], "2026-09-08T13:34:00Z")
