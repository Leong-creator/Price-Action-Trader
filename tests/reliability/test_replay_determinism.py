from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from src.backtest import run_backtest
from src.data import DataValidationError, build_replay, load_news_events, load_ohlcv_csv
from src.strategy import generate_signals

from tests.reliability._support import (
    _bar,
    equal_timestamp_news,
    extended_bullish_trade_bars,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DATA_DIR = PROJECT_ROOT / "tests" / "test_data"


class ReplayDeterminismTests(unittest.TestCase):
    def test_replay_snapshot_is_stable_across_input_order(self) -> None:
        bars = load_ohlcv_csv(TEST_DATA_DIR / "ohlcv_sample_5m.csv")
        news = load_news_events(TEST_DATA_DIR / "news_sample.json") + list(equal_timestamp_news())

        shuffled_bars = list(bars)
        random.Random(7).shuffle(shuffled_bars)
        shuffled_news = list(news)
        random.Random(11).shuffle(shuffled_news)

        baseline = build_replay(bars, news)
        reversed_replay = build_replay(reversed(bars), reversed(news))
        shuffled_replay = build_replay(shuffled_bars, shuffled_news)

        self.assertEqual(self._snapshot_signature(baseline.snapshot()), self._snapshot_signature(baseline.snapshot()))
        self.assertEqual(self._snapshot_signature(baseline.snapshot()), self._snapshot_signature(reversed_replay.snapshot()))
        self.assertEqual(self._snapshot_signature(baseline.snapshot()), self._snapshot_signature(shuffled_replay.snapshot()))

        baseline.reset()
        self.assertEqual(self._snapshot_signature(tuple(baseline)), self._snapshot_signature(baseline.snapshot()))

    def test_signal_and_backtest_outputs_are_deterministic_for_same_fixture(self) -> None:
        bars = extended_bullish_trade_bars()

        forward_replay = build_replay(bars)
        reverse_replay = build_replay(reversed(bars))

        forward_signals = generate_signals(forward_replay)
        reverse_signals = generate_signals(reverse_replay)

        self.assertEqual(self._signal_signature(forward_signals), self._signal_signature(reverse_signals))

        forward_report = run_backtest(bars, forward_signals)
        reverse_report = run_backtest(tuple(reversed(bars)), reverse_signals)

        self.assertEqual(self._trade_signature(forward_report), self._trade_signature(reverse_report))
        self.assertEqual(forward_report.stats.total_pnl_r, reverse_report.stats.total_pnl_r)
        self.assertEqual(forward_report.summary, reverse_report.summary)

    def test_duplicate_bar_loader_fails_fast(self) -> None:
        duplicate_csv = """symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume
SAMPLE,US,5m,2026-01-05T09:30:00,America/New_York,100.00,100.60,99.80,100.30,100000
SAMPLE,US,5m,2026-01-05T09:30:00,America/New_York,100.30,100.90,100.10,100.70,100000
"""

        path = self._write_temp_file("duplicate-bars.csv", duplicate_csv)
        with self.assertRaisesRegex(DataValidationError, "duplicate OHLCV row"):
            load_ohlcv_csv(path)

    def test_gap_bars_do_not_fabricate_missing_slots(self) -> None:
        bars = (
            _bar(0, market="US", timeframe="5m", open_="100.0", high="100.6", low="99.8", close="100.3"),
            _bar(1, market="US", timeframe="5m", open_="100.3", high="100.9", low="100.1", close="100.7"),
            _bar(3, market="US", timeframe="5m", open_="100.7", high="101.2", low="100.6", close="101.0"),
            _bar(4, market="US", timeframe="5m", open_="101.0", high="101.4", low="100.8", close="101.2"),
        )

        replay = build_replay(bars)
        snapshot = replay.snapshot()
        report = run_backtest(bars, generate_signals(replay))

        self.assertEqual(
            [step.bar.timestamp.isoformat() for step in snapshot],
            [
                "2026-01-05T09:30:00-05:00",
                "2026-01-05T09:35:00-05:00",
                "2026-01-05T09:45:00-05:00",
                "2026-01-05T09:50:00-05:00",
            ],
        )
        self.assertEqual(len(snapshot), 4)
        self.assertGreaterEqual(report.stats.trade_count, 0)

    def _snapshot_signature(self, steps) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (
                step.index,
                step.bar.identity_key,
                tuple(event.identity_key for event in step.news_events),
            )
            for step in steps
        )

    def _signal_signature(self, signals) -> tuple[tuple[str, ...], ...]:
        return tuple(
            (
                signal.signal_id,
                signal.direction,
                signal.pa_context,
                signal.entry_trigger,
                signal.stop_rule,
                signal.target_rule,
                signal.invalidation,
                signal.confidence,
                "|".join(signal.source_refs),
                "|".join(signal.risk_notes),
            )
            for signal in signals
        )

    def _trade_signature(self, report) -> tuple[tuple[str, ...], ...]:
        return tuple(
            (
                trade.signal_id,
                str(trade.entry_price),
                str(trade.stop_price),
                str(trade.target_price),
                str(trade.exit_price),
                trade.exit_reason,
                str(trade.pnl_r),
            )
            for trade in report.trades
        )

    def _write_temp_file(self, filename: str, content: str) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="pat-m8c-determinism-"))
        path = temp_dir / filename
        path.write_text(content, encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
