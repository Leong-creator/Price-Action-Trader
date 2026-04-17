from __future__ import annotations

import unittest

from src.data import build_replay
from src.news import evaluate_news_context
from src.strategy import generate_signals

from tests.reliability._support import (
    between_bar_news,
    bullish_trend_bars,
    future_blocking_news,
    future_tail_bars,
    past_caution_news,
)


class NoFutureLeakageTests(unittest.TestCase):
    def test_future_news_is_ignored_for_current_reference_timestamp(self) -> None:
        bars = future_tail_bars()
        signals = generate_signals(build_replay(bars))
        signal = signals[0]
        reference_timestamp = bars[2].timestamp
        events = past_caution_news(index=1) + future_blocking_news(index=4)

        decision = evaluate_news_context(
            signal,
            events,
            reference_timestamp=reference_timestamp,
        )

        self.assertEqual(decision.outcome, "caution")
        self.assertEqual(decision.reason_codes, ("news_risk_warning",))
        self.assertEqual(len(decision.matched_events), 1)
        self.assertLessEqual(decision.matched_events[0].timestamp, reference_timestamp)
        self.assertNotIn("high_risk_news_event", decision.reason_codes)

    def test_future_bars_do_not_change_current_signal_decision(self) -> None:
        prefix_bars = bullish_trend_bars()
        full_bars = future_tail_bars()

        prefix_signals = generate_signals(build_replay(prefix_bars))
        full_signals = generate_signals(build_replay(full_bars))

        self.assertEqual(len(prefix_signals), 1)
        self.assertGreaterEqual(len(full_signals), 1)
        self.assertEqual(prefix_signals[0].signal_id, full_signals[0].signal_id)
        self.assertEqual(prefix_signals[0].direction, full_signals[0].direction)
        self.assertEqual(prefix_signals[0].explanation, full_signals[0].explanation)
        self.assertEqual(prefix_signals[0].source_refs, full_signals[0].source_refs)

    def test_missing_reference_timestamp_fails_fast(self) -> None:
        bars = future_tail_bars()
        signal = generate_signals(build_replay(bars))[0]

        with self.assertRaisesRegex(ValueError, "reference_timestamp is required"):
            evaluate_news_context(signal, between_bar_news())


if __name__ == "__main__":
    unittest.main()
