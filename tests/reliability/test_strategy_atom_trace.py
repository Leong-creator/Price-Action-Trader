from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.data.replay import build_replay
from src.data.schema import OhlcvRow
from src.strategy import KnowledgeQuery, generate_signals, load_default_knowledge_access


class StrategyAtomTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.knowledge_access = load_default_knowledge_access()

    def test_signal_contains_structured_knowledge_trace(self) -> None:
        signal = generate_signals(build_replay(self._trend_bars()))[0]

        self.assertTrue(signal.knowledge_trace)
        curated_hits = [hit for hit in signal.knowledge_trace if hit.atom_type in {"concept", "setup", "rule"}]
        self.assertEqual([hit.atom_type for hit in curated_hits], ["concept", "setup", "rule"])
        for hit in signal.knowledge_trace:
            self.assertTrue(hit.atom_id)
            self.assertTrue(hit.source_ref)
            self.assertTrue(hit.raw_locator)
            self.assertTrue(hit.match_reason)
            self.assertTrue(hit.applicability_state)
            self.assertEqual(hit.reference_tier, "actual_hit")
            self.assertNotEqual(hit.applicability_state, "not_applicable")
        for hit in curated_hits:
            self.assertTrue(hit.claim_id)
            self.assertTrue(hit.promotion_theme)
            self.assertTrue(hit.evidence_refs)
            self.assertTrue(hit.evidence_locator_summary)
            self.assertTrue(hit.field_mappings)
        self.assertTrue(signal.knowledge_debug_trace)
        self.assertTrue(any(hit.reference_tier == "bundle_support" for hit in signal.knowledge_debug_trace))

    def test_statement_atoms_are_trace_only_and_do_not_change_trigger_fields(self) -> None:
        full_signal = generate_signals(
            build_replay(self._trend_bars()),
            knowledge_access=self.knowledge_access,
        )[0]
        curated_only_access = self.knowledge_access.filtered(
            exclude_atom_types=("statement", "source_note", "contradiction", "open_question")
        )
        curated_only_signal = generate_signals(
            build_replay(self._trend_bars()),
            knowledge_access=curated_only_access,
        )[0]

        self.assertEqual(full_signal.signal_id, curated_only_signal.signal_id)
        self.assertEqual(full_signal.direction, curated_only_signal.direction)
        self.assertEqual(full_signal.setup_type, curated_only_signal.setup_type)
        self.assertEqual(full_signal.entry_trigger, curated_only_signal.entry_trigger)
        self.assertEqual(full_signal.stop_rule, curated_only_signal.stop_rule)
        self.assertEqual(full_signal.target_rule, curated_only_signal.target_rule)
        self.assertEqual(full_signal.invalidation, curated_only_signal.invalidation)
        self.assertEqual(full_signal.confidence, curated_only_signal.confidence)
        self.assertTrue(any(hit.atom_type == "statement" for hit in full_signal.knowledge_trace))
        self.assertTrue(
            all(hit.atom_type in {"concept", "setup", "rule"} for hit in curated_only_signal.knowledge_trace)
        )

    def test_brooks_heavy_statement_population_does_not_change_confidence_or_trigger(self) -> None:
        brooks_statements = self.knowledge_access.query_atoms(
            KnowledgeQuery(atom_type="statement", source_families=("al_brooks_ppt",))
        )
        full_signal = generate_signals(
            build_replay(self._trend_bars()),
            knowledge_access=self.knowledge_access,
        )[0]
        no_statement_access = self.knowledge_access.filtered(
            exclude_atom_types=("statement", "source_note", "contradiction", "open_question")
        )
        curated_signal = generate_signals(
            build_replay(self._trend_bars()),
            knowledge_access=no_statement_access,
        )[0]

        self.assertEqual(full_signal.confidence, curated_signal.confidence)
        self.assertEqual(full_signal.entry_trigger, curated_signal.entry_trigger)
        self.assertEqual(full_signal.stop_rule, curated_signal.stop_rule)
        self.assertEqual(full_signal.target_rule, curated_signal.target_rule)
        self.assertEqual(full_signal.invalidation, curated_signal.invalidation)
        self.assertGreater(len(brooks_statements), 1000)
        self.assertFalse(any(hit.atom_type == "statement" for hit in curated_signal.knowledge_trace))

    def test_actual_hit_and_bundle_support_refs_are_split_but_legacy_source_refs_remain_compatible(self) -> None:
        signal = generate_signals(build_replay(self._trend_bars()))[0]

        self.assertTrue(signal.actual_source_refs)
        self.assertTrue(signal.bundle_support_refs)
        self.assertIn("wiki:knowledge/wiki/concepts/market-cycle-overview.md", signal.source_refs)
        self.assertIn("wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md", signal.source_refs)
        self.assertIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", signal.source_refs)
        self.assertIn("wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md", signal.source_refs)
        self.assertNotIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", signal.actual_source_refs)
        self.assertIn("wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md", signal.actual_source_refs)
        self.assertIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", signal.bundle_support_refs)
        for hit in signal.knowledge_trace:
            self.assertIn(hit.source_ref, signal.actual_source_refs)
            self.assertIn(hit.source_ref, signal.source_refs)
            for ref in hit.conflict_refs:
                self.assertIn(ref, signal.source_refs)
        self.assertTrue(any("al-brooks" in ref for ref in signal.bundle_support_refs))
        self.assertTrue(
            any(
                "fangfangtu-price-action-transcript.md" in ref or "al-brooks-price-action-ppt-1-36-units.md" in ref
                for hit in signal.knowledge_trace
                for ref in hit.evidence_refs
            )
        )

    def test_visible_trace_excludes_purely_governance_derived_not_applicable(self) -> None:
        signal = generate_signals(build_replay(self._trend_bars()))[0]

        self.assertTrue(any(hit.governance_notes for hit in signal.knowledge_trace if hit.atom_type in {"concept", "setup"}))
        self.assertTrue(all(hit.applicability_state != "not_applicable" for hit in signal.knowledge_trace))

    def test_visible_trace_does_not_surface_broad_rule_chunk_set(self) -> None:
        signal = generate_signals(build_replay(self._trend_bars()))[0]

        rule_hits = [hit for hit in signal.knowledge_trace if hit.atom_type == "rule"]
        self.assertEqual(len(rule_hits), 1)
        self.assertLess(rule_hits[0].raw_locator.get("member_count", 0), 64)
        self.assertTrue(rule_hits[0].evidence_locator_summary)
        self.assertTrue(rule_hits[0].field_mappings)
        self.assertFalse(
            any(
                hit.atom_type == "rule"
                and hit.raw_locator.get("locator_kind") == "chunk_set"
                and hit.raw_locator.get("member_count", 0) >= 100
                for hit in signal.knowledge_trace
            )
        )
        self.assertTrue(
            any(
                hit.atom_type == "rule"
                and hit.reference_tier == "bundle_support"
                and hit.raw_locator.get("locator_kind") == "bundle_support_summary"
                for hit in signal.knowledge_debug_trace
            )
        )

    def test_source_family_imbalance_is_capped(self) -> None:
        signal = generate_signals(build_replay(self._trend_bars()))[0]

        statement_hits = [hit for hit in signal.knowledge_trace if hit.atom_type == "statement"]
        self.assertLessEqual(len(signal.knowledge_trace), 6)
        self.assertLessEqual(len(statement_hits), 2)
        self.assertLessEqual(
            sum(1 for hit in statement_hits if "al-brooks" in hit.source_ref),
            1,
        )
        self.assertEqual(
            len({self._family_from_source_ref(hit.source_ref) for hit in statement_hits}),
            len(statement_hits),
        )

    def _family_from_source_ref(self, source_ref: str) -> str:
        if "al-brooks" in source_ref:
            return "al_brooks_ppt"
        if "fangfangtu" in source_ref and "transcript" in source_ref:
            return "fangfangtu_transcript"
        if "fangfangtu" in source_ref:
            return "fangfangtu_notes"
        return "curated"

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

    def _timestamp(self, index: int) -> datetime:
        base = datetime(2026, 1, 5, 9, 30, tzinfo=ZoneInfo("America/New_York"))
        return base.replace(minute=base.minute + (index * 5))


if __name__ == "__main__":
    unittest.main()
