from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from src.data.replay import build_replay
from src.data.schema import NewsEvent, OhlcvRow
from src.strategy import (
    DEFAULT_CONCEPT_PATH,
    KnowledgeReferenceError,
    SETUP_TYPE,
    generate_signals,
    load_strategy_knowledge,
)


class StrategySignalPipelineTests(unittest.TestCase):
    def test_no_signal_when_context_is_not_trend(self) -> None:
        replay = build_replay(
            (
                self._bar(0, open_="100.0", high="100.3", low="99.9", close="100.1"),
                self._bar(1, open_="100.1", high="100.2", low="99.95", close="100.0"),
                self._bar(2, open_="100.0", high="100.15", low="99.92", close="100.02"),
            )
        )

        self.assertEqual(generate_signals(replay), ())

    def test_single_signal_contains_required_fields(self) -> None:
        replay = build_replay(self._trend_bars())

        signals = generate_signals(replay)

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.setup_type, SETUP_TYPE)
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.pa_context, "trend")
        self.assertTrue(signal.entry_trigger)
        self.assertTrue(signal.stop_rule)
        self.assertTrue(signal.target_rule)
        self.assertTrue(signal.invalidation)
        self.assertTrue(signal.explanation)
        self.assertTrue(signal.risk_notes)
        self.assertTrue(signal.knowledge_trace)
        self.assertIn(signal.knowledge_trace[0].atom_type, {"concept", "setup", "rule"})

    def test_signal_id_and_source_refs_are_stable(self) -> None:
        replay = build_replay(self._trend_bars())

        first_run = generate_signals(replay)
        replay.reset()
        second_run = generate_signals(replay)

        self.assertEqual(first_run[0].signal_id, second_run[0].signal_id)
        self.assertEqual(first_run[0].source_refs, second_run[0].source_refs)
        self.assertEqual(first_run[0].knowledge_trace, second_run[0].knowledge_trace)
        self.assertIn("wiki:knowledge/wiki/concepts/market-cycle-overview.md", first_run[0].source_refs)
        self.assertIn("wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md", first_run[0].source_refs)
        self.assertIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", first_run[0].source_refs)
        self.assertIn("raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf", first_run[0].source_refs)
        self.assertIn("wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md", first_run[0].source_refs)
        self.assertTrue(all(hit.source_ref in first_run[0].source_refs for hit in first_run[0].knowledge_trace))

    def test_placeholder_knowledge_forces_low_confidence_and_risk_notes(self) -> None:
        signal = generate_signals(build_replay(self._trend_bars()))[0]

        self.assertEqual(signal.confidence, "low")
        self.assertTrue(any("placeholder" in note for note in signal.risk_notes))
        self.assertTrue(any("research-only" in note for note in signal.risk_notes))

    def test_news_is_attached_only_as_risk_context(self) -> None:
        replay = build_replay(
            self._trend_bars(),
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

        signal = generate_signals(replay)[0]

        self.assertEqual(signal.setup_type, SETUP_TYPE)
        self.assertEqual(signal.direction, "long")
        self.assertTrue(any("news context only:" in note for note in signal.risk_notes))
        self.assertFalse("earnings" in signal.entry_trigger.lower())

    def test_missing_source_refs_blocks_signal_generation(self) -> None:
        setup_path = self._write_temp_setup_without_source_refs()

        with self.assertRaises(KnowledgeReferenceError):
            load_strategy_knowledge(DEFAULT_CONCEPT_PATH, setup_path)

    def test_invalidation_prevents_placeholder_signal(self) -> None:
        replay = build_replay(
            (
                self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
                self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
                self._bar(2, open_="100.7", high="101.1", low="100.6", close="100.88"),
            )
        )

        self.assertEqual(generate_signals(replay), ())

    def test_multi_signal_order_is_stable_and_unique(self) -> None:
        replay = build_replay(self._reversal_bars())

        first_run = generate_signals(replay)
        replay.reset()
        second_run = generate_signals(replay)

        self.assertEqual([signal.direction for signal in first_run], ["long", "short"])
        self.assertEqual([signal.signal_id for signal in first_run], [signal.signal_id for signal in second_run])
        self.assertEqual(len({signal.signal_id for signal in first_run}), 2)

    def _trend_bars(self) -> tuple[OhlcvRow, ...]:
        return (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
        )

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

    def _reversal_bars(self) -> tuple[OhlcvRow, ...]:
        return (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
            self._bar(3, open_="101.1", high="101.2", low="100.6", close="100.8"),
            self._bar(4, open_="100.8", high="100.9", low="100.0", close="100.2"),
            self._bar(5, open_="100.2", high="100.3", low="99.4", close="99.5"),
        )

    def _timestamp(self, index: int) -> datetime:
        base = datetime(2026, 1, 5, 9, 30, tzinfo=ZoneInfo("America/New_York"))
        return base.replace(minute=base.minute + (index * 5))

    def _write_temp_setup_without_source_refs(self) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="pat-strategy-"))
        path = temp_dir / "setup.md"
        path.write_text(
            """---
title: Missing Source Refs
type: setup
status: draft
confidence: low
market: ["US"]
timeframes: ["5m"]
direction: both
source_refs: []
pa_context: ["trend"]
higher_timeframe_context: ["pending"]
bar_by_bar_notes: ["pending"]
entry_trigger: ["pending"]
stop_rule: ["pending"]
target_rule: ["pending"]
invalidation: ["pending"]
---
""",
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
