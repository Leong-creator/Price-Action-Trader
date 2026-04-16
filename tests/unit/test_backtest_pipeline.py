from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.backtest import run_backtest
from src.data.replay import build_replay
from src.data.schema import NewsEvent, OhlcvRow
from src.strategy import generate_signals


class BacktestPipelineTests(unittest.TestCase):
    def test_zero_trade_report_when_no_signals_exist(self) -> None:
        bars = (
            self._bar(0, open_="100.0", high="100.3", low="99.9", close="100.1"),
            self._bar(1, open_="100.1", high="100.2", low="99.95", close="100.0"),
            self._bar(2, open_="100.0", high="100.15", low="99.92", close="100.02"),
        )
        signals = generate_signals(build_replay(bars))

        report = run_backtest(bars, signals)

        self.assertEqual(report.trades, ())
        self.assertEqual(report.stats.trade_count, 0)
        self.assertIn("No trades were recorded", report.summary)

    def test_single_trade_target_hit_is_recorded(self) -> None:
        bars = (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
            self._bar(3, open_="101.2", high="102.5", low="101.0", close="102.3"),
        )
        signals = generate_signals(build_replay(bars))

        report = run_backtest(bars, signals)

        self.assertEqual(report.stats.trade_count, 1)
        self.assertEqual(report.stats.closed_trade_count, 1)
        trade = report.trades[0]
        self.assertEqual(trade.exit_reason, "target_hit")
        self.assertEqual(trade.pnl_r, Decimal("2.0000"))
        self.assertEqual(report.stats.win_rate, Decimal("1.0000"))
        self.assertEqual(report.stats.slippage_sensitivity[0].label, "baseline_0r")
        self.assertIn("deterministic backtest assumed next-bar-open entry", trade.explanation)

    def test_single_trade_stop_hit_is_recorded(self) -> None:
        bars = (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
            self._bar(3, open_="101.2", high="101.3", low="100.4", close="100.5"),
        )
        signals = generate_signals(build_replay(bars))

        report = run_backtest(bars, signals)

        self.assertEqual(report.stats.trade_count, 1)
        trade = report.trades[0]
        self.assertEqual(trade.exit_reason, "stop_hit")
        self.assertEqual(trade.pnl_r, Decimal("-1.0000"))
        self.assertEqual(report.stats.loss_count, 1)

    def test_multi_trade_stats_are_deterministic(self) -> None:
        bars = (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
            self._bar(3, open_="101.1", high="101.2", low="100.6", close="100.8"),
            self._bar(4, open_="100.8", high="100.9", low="100.0", close="100.2"),
            self._bar(5, open_="100.2", high="100.3", low="99.4", close="99.5"),
            self._bar(6, open_="99.5", high="101.0", low="99.4", close="100.8"),
        )
        signals = generate_signals(build_replay(bars))

        first_report = run_backtest(bars, signals)
        second_report = run_backtest(bars, signals)

        self.assertEqual([trade.direction for trade in first_report.trades], ["long", "short"])
        self.assertEqual(
            [trade.signal_id for trade in first_report.trades],
            [trade.signal_id for trade in second_report.trades],
        )
        self.assertEqual(first_report.stats.trade_count, 2)
        self.assertEqual(first_report.stats.win_count, 0)
        self.assertEqual(first_report.stats.loss_count, 2)
        self.assertEqual(first_report.stats.total_pnl_r, Decimal("-2.0000"))

    def test_data_insufficiency_is_reported_when_signal_has_no_entry_bar(self) -> None:
        bars = (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
        )
        signals = generate_signals(build_replay(bars))

        report = run_backtest(bars, signals)

        self.assertEqual(report.stats.trade_count, 0)
        self.assertTrue(any("data is insufficient" in warning for warning in report.warnings))
        self.assertIn("Warnings:", report.summary)

    def test_same_bar_stop_and_target_uses_stop_first_priority(self) -> None:
        bars = (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
            self._bar(3, open_="101.2", high="102.5", low="99.7", close="101.1"),
        )
        signals = generate_signals(build_replay(bars))

        report = run_backtest(build_replay(bars), signals)

        self.assertEqual(report.trades[0].exit_reason, "stop_before_target_same_bar")
        self.assertEqual(report.trades[0].pnl_r, Decimal("-1.0000"))

    def test_end_of_data_trade_is_forced_closed_with_warning(self) -> None:
        bars = (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
            self._bar(3, open_="101.2", high="101.5", low="101.0", close="101.3"),
        )
        signals = generate_signals(build_replay(bars))

        report = run_backtest(bars, signals)

        self.assertEqual(report.trades[0].exit_reason, "end_of_data")
        self.assertEqual(report.stats.trade_count, 1)
        self.assertEqual(report.stats.closed_trade_count, 0)
        self.assertEqual(report.stats.expectancy_r, Decimal("0.0000"))
        self.assertIsNone(report.stats.profit_factor)
        self.assertTrue(any("reached the end of available bars" in warning for warning in report.warnings))

    def test_news_context_does_not_change_pnl_metrics(self) -> None:
        bars = (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
            self._bar(3, open_="101.2", high="102.5", low="101.0", close="102.3"),
        )
        plain_signals = generate_signals(build_replay(bars))
        news_signals = generate_signals(
            build_replay(
                bars,
                (
                    NewsEvent(
                        symbol="SAMPLE",
                        market="US",
                        timestamp=self._timestamp(2),
                        source="synthetic-news",
                        event_type="earnings",
                        headline="earnings later today",
                        severity="high",
                        notes="headline risk only",
                        timezone="America/New_York",
                    ),
                ),
            )
        )

        plain_report = run_backtest(bars, plain_signals)
        news_report = run_backtest(bars, news_signals)

        self.assertEqual(plain_report.stats.total_pnl_r, news_report.stats.total_pnl_r)
        self.assertEqual(plain_report.trades[0].entry_price, news_report.trades[0].entry_price)
        self.assertTrue(any("news context only:" in note for note in news_report.trades[0].risk_notes))

    def test_profit_factor_is_none_when_no_losing_trade_exists(self) -> None:
        bars = (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
            self._bar(3, open_="101.2", high="102.5", low="101.0", close="102.3"),
        )
        signals = generate_signals(build_replay(bars))

        report = run_backtest(build_replay(bars), signals)

        self.assertEqual(report.stats.win_count, 1)
        self.assertEqual(report.stats.loss_count, 0)
        self.assertIsNone(report.stats.profit_factor)

    def _bar(self, index: int, *, open_: str, high: str, low: str, close: str) -> OhlcvRow:
        return OhlcvRow(
            symbol="SAMPLE",
            market="US",
            timeframe="5m",
            timestamp=self._timestamp(index),
            timezone="America/New_York",
            open=Decimal(open_),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=Decimal("100000"),
        )

    def _timestamp(self, index: int) -> datetime:
        base = datetime(2026, 1, 5, 9, 30, tzinfo=ZoneInfo("America/New_York"))
        return base + timedelta(minutes=index * 5)


if __name__ == "__main__":
    unittest.main()
