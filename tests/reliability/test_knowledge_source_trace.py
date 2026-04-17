from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from src.data.replay import build_replay
from src.data.schema import OhlcvRow
from src.strategy import (
    DEFAULT_CONCEPT_PATH,
    DEFAULT_SETUP_PATH,
    generate_signals,
    load_default_knowledge,
    load_strategy_knowledge,
)


TRANSCRIPT_SOURCE_PAGE = "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md"
BROOKS_SOURCE_PAGE = "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt.md"
RULE_PACK_PAGE = "wiki:knowledge/wiki/rules/m3-research-reference-pack.md"


class KnowledgeSourceTraceTests(unittest.TestCase):
    def test_default_bundle_pulls_active_rule_pack_sources(self) -> None:
        bundle = load_default_knowledge()

        self.assertIn(RULE_PACK_PAGE, bundle.source_refs)
        self.assertIn(TRANSCRIPT_SOURCE_PAGE, bundle.source_refs)
        self.assertIn(BROOKS_SOURCE_PAGE, bundle.source_refs)

    def test_wired_transcript_and_brooks_source_pages_reach_signal_explanation(self) -> None:
        signal = generate_signals(build_replay(self._trend_bars()))[0]

        self.assertIn(TRANSCRIPT_SOURCE_PAGE, signal.source_refs)
        self.assertIn(BROOKS_SOURCE_PAGE, signal.source_refs)
        self.assertIn(TRANSCRIPT_SOURCE_PAGE, signal.bundle_support_refs)
        self.assertIn(BROOKS_SOURCE_PAGE, signal.bundle_support_refs)
        self.assertNotIn(TRANSCRIPT_SOURCE_PAGE, signal.actual_source_refs)
        self.assertNotIn(BROOKS_SOURCE_PAGE, signal.actual_source_refs)
        self.assertNotIn(TRANSCRIPT_SOURCE_PAGE, signal.explanation)
        self.assertNotIn(BROOKS_SOURCE_PAGE, signal.explanation)

    def test_unwired_bundle_does_not_fabricate_transcript_or_brooks_refs(self) -> None:
        temp_rule_pack = self._write_temp_rule_pack()
        bundle = load_strategy_knowledge(
            DEFAULT_CONCEPT_PATH,
            DEFAULT_SETUP_PATH,
            supporting_paths=(temp_rule_pack,),
        )

        signal = generate_signals(build_replay(self._trend_bars()), knowledge=bundle)[0]

        self.assertNotIn(TRANSCRIPT_SOURCE_PAGE, signal.source_refs)
        self.assertNotIn(BROOKS_SOURCE_PAGE, signal.source_refs)
        self.assertNotIn(TRANSCRIPT_SOURCE_PAGE, signal.explanation)
        self.assertNotIn(BROOKS_SOURCE_PAGE, signal.explanation)

    def _write_temp_rule_pack(self) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="pat-knowledge-trace-"))
        path = temp_dir / "temp-rule-pack.md"
        path.write_text(
            """---
title: Temporary Rule Pack
type: rule
status: draft
confidence: low
market: ["US"]
timeframes: ["5m"]
direction: neutral
source_refs: ["wiki:knowledge/wiki/concepts/market-cycle-overview.md", "wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md"]
tags: ["temp", "rule-pack"]
applicability: ["test-only"]
not_applicable: ["not-for-production"]
contradictions: []
missing_visuals: []
open_questions: []
pa_context: ["trend"]
market_cycle: []
higher_timeframe_context: []
bar_by_bar_notes: []
signal_bar: []
entry_trigger: []
entry_bar: []
stop_rule: []
target_rule: []
trade_management: []
measured_move: false
invalidation: []
risk_reward_min:
last_reviewed: 2026-04-17
---
""",
            encoding="utf-8",
        )
        return path

    def _trend_bars(self) -> tuple[OhlcvRow, ...]:
        return (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
        )

    def _bar(self, index: int, *, open_: str, high: str, low: str, close: str) -> OhlcvRow:
        return OhlcvRow(
            symbol="TRACE",
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
        return base.replace(minute=base.minute + (index * 5))


if __name__ == "__main__":
    unittest.main()
