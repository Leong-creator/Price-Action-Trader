from __future__ import annotations

import json
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from src.data.replay import build_replay
from src.data.schema import OhlcvRow
from src.strategy import (
    DEFAULT_CONCEPT_PATH,
    DEFAULT_RULE_PACK_PATH,
    DEFAULT_SETUP_PATH,
    generate_signals,
    load_strategy_knowledge,
)
from tests.reliability._atomization_support import load_fixture


ROOT = Path(__file__).resolve().parents[2]
PROMOTION_MAP_PATH = ROOT / "knowledge" / "indices" / "curated_promotion_map.json"
TRANSCRIPT_SOURCE_PAGE = "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md"
BROOKS_SOURCE_PAGE = "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md"
PROMOTED_RULE_PAGE = "wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md"


class CuratedPromotionMinimalSetTests(unittest.TestCase):
    def test_curated_promotion_map_resolves_to_promoted_atoms(self) -> None:
        fixture = load_fixture()
        promotion_map = json.loads(PROMOTION_MAP_PATH.read_text(encoding="utf-8"))
        promoted_atoms = {
            atom["claim_id"]: atom
            for atom in fixture["atoms"]
            if "promoted_curated" in atom.get("callable_tags", [])
            and atom["atom_type"] in {"concept", "setup", "rule"}
        }

        self.assertEqual(len(promotion_map["promotions"]), 3)
        for promotion in promotion_map["promotions"]:
            atom = promoted_atoms[promotion["claim_id"]]
            self.assertEqual(atom["source_ref"], promotion["page_ref"])
            self.assertEqual(atom["status"], "draft")
            self.assertEqual(atom["confidence"], "low")
            self.assertTrue(atom["evidence_chunk_ids"])
            self.assertTrue(atom["evidence_refs"])
            self.assertTrue(atom["evidence_locator_summary"])
            self.assertTrue(atom["field_mappings"])
            self.assertEqual(atom["promotion_theme"], promotion["theme_id"])
            self.assertNotIn("strategy_candidate", atom["callable_tags"])

    def test_open_questions_are_preserved_for_promoted_themes(self) -> None:
        fixture = load_fixture()
        promotion_map = json.loads(PROMOTION_MAP_PATH.read_text(encoding="utf-8"))
        open_questions = [
            atom
            for atom in fixture["atoms"]
            if atom["atom_type"] == "open_question"
            and atom.get("claim_id")
            and atom["source_ref"].startswith("wiki:knowledge/wiki/")
        ]
        by_claim = {(atom["source_ref"], atom["claim_id"]): atom for atom in open_questions}

        for promotion in promotion_map["promotions"]:
            if not promotion.get("open_questions"):
                continue
            self.assertIn((promotion["page_ref"], promotion["claim_id"]), by_claim)
            atom = by_claim[(promotion["page_ref"], promotion["claim_id"])]
            self.assertTrue(atom["evidence_chunk_ids"])
            self.assertEqual(atom["field_mappings"], ["open_question"])

    def test_no_contradiction_is_fabricated_for_promoted_themes(self) -> None:
        fixture = load_fixture()
        promotion_map = json.loads(PROMOTION_MAP_PATH.read_text(encoding="utf-8"))
        contradictions = [
            atom
            for atom in fixture["atoms"]
            if atom["atom_type"] == "contradiction"
            and atom.get("claim_id")
            and atom["source_ref"].startswith("wiki:knowledge/wiki/")
        ]
        contradiction_keys = {(atom["source_ref"], atom["claim_id"]) for atom in contradictions}

        for promotion in promotion_map["promotions"]:
            if promotion.get("contradictions"):
                self.assertIn((promotion["page_ref"], promotion["claim_id"]), contradiction_keys)
            else:
                self.assertNotIn((promotion["page_ref"], promotion["claim_id"]), contradiction_keys)

    def test_promoted_transcript_and_brooks_evidence_enter_actual_visible_trace(self) -> None:
        signal = generate_signals(build_replay(self._trend_bars()))[0]

        curated_hits = [hit for hit in signal.knowledge_trace if hit.atom_type in {"concept", "setup", "rule"}]
        self.assertEqual([hit.atom_type for hit in curated_hits], ["concept", "setup", "rule"])
        evidence_refs = {ref for hit in curated_hits for ref in hit.evidence_refs}
        self.assertIn(TRANSCRIPT_SOURCE_PAGE, evidence_refs)
        self.assertIn(BROOKS_SOURCE_PAGE, evidence_refs)
        rule_hit = next(hit for hit in curated_hits if hit.atom_type == "rule")
        self.assertEqual(rule_hit.source_ref, PROMOTED_RULE_PAGE)
        self.assertEqual(rule_hit.claim_id, "trend_vs_range.filter.minimal.v1")
        self.assertEqual(rule_hit.promotion_theme, "trend_vs_range_filter")
        self.assertTrue(rule_hit.evidence_locator_summary)

    def test_promotion_does_not_change_trigger_fields(self) -> None:
        replay = build_replay(self._trend_bars())
        promoted_signal = generate_signals(replay)[0]
        replay.reset()
        legacy_bundle = load_strategy_knowledge(
            DEFAULT_CONCEPT_PATH,
            DEFAULT_SETUP_PATH,
            supporting_paths=(DEFAULT_RULE_PACK_PATH,),
        )
        legacy_signal = generate_signals(replay, knowledge=legacy_bundle)[0]

        self.assertEqual(promoted_signal.signal_id, legacy_signal.signal_id)
        self.assertEqual(promoted_signal.direction, legacy_signal.direction)
        self.assertEqual(promoted_signal.setup_type, legacy_signal.setup_type)
        self.assertEqual(promoted_signal.entry_trigger, legacy_signal.entry_trigger)
        self.assertEqual(promoted_signal.stop_rule, legacy_signal.stop_rule)
        self.assertEqual(promoted_signal.target_rule, legacy_signal.target_rule)
        self.assertEqual(promoted_signal.invalidation, legacy_signal.invalidation)
        self.assertEqual(promoted_signal.confidence, legacy_signal.confidence)
        self.assertIn(PROMOTED_RULE_PAGE, promoted_signal.actual_source_refs)
        self.assertNotIn(PROMOTED_RULE_PAGE, legacy_signal.actual_source_refs)

    def _trend_bars(self) -> tuple[OhlcvRow, ...]:
        return (
            self._bar(0, open_="100.0", high="100.6", low="99.8", close="100.3"),
            self._bar(1, open_="100.3", high="100.9", low="100.1", close="100.7"),
            self._bar(2, open_="100.7", high="101.4", low="100.6", close="101.2"),
        )

    def _bar(self, index: int, *, open_: str, high: str, low: str, close: str) -> OhlcvRow:
        base = datetime(2026, 1, 5, 9, 30, tzinfo=ZoneInfo("America/New_York"))
        return OhlcvRow(
            symbol="PROMO",
            market="US",
            timeframe="5m",
            timestamp=base.replace(minute=base.minute + (index * 5)),
            timezone="America/New_York",
            open=Decimal(open_),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=Decimal("100000"),
        )


if __name__ == "__main__":
    unittest.main()
