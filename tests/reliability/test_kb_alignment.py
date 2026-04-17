from __future__ import annotations

import unittest

from src.strategy import assess_kb_alignment

from tests.reliability._support import (
    build_bundle_from_refs,
    bullish_trend_bars,
    load_case,
    synthetic_news_event,
)


class KBAlignmentTests(unittest.TestCase):
    def test_placeholder_setup_case_keeps_traceability(self) -> None:
        case = load_case("gc_hk_15m_placeholder_setup_research_only")
        bundle = build_bundle_from_refs(*case.required_source_refs)

        assessment = assess_kb_alignment(
            bullish_trend_bars(market=case.market, timeframe=case.timeframe),
            knowledge=bundle,
        )

        self.assertIn(assessment.action, case.allowed_actions)
        self.assertEqual(assessment.confidence, case.confidence_floor)
        self.assertEqual(assessment.setup_type, "signal_bar_entry_placeholder")
        self.assertTrue(set(case.required_source_refs).issubset(set(assessment.source_refs)))
        self._assert_case_language(case, assessment.explanation)

    def test_news_role_conflict_is_explicit(self) -> None:
        case = load_case("gc_us_15m_news_role_conflict_must_be_explicit")
        bundle = build_bundle_from_refs(*case.required_source_refs)

        assessment = assess_kb_alignment(
            bullish_trend_bars(market=case.market, timeframe=case.timeframe),
            knowledge=bundle,
            news_events=(synthetic_news_event(market=case.market),),
        )

        self.assertIn(assessment.action, case.allowed_actions)
        self.assertIn("knowledge_conflict", assessment.issues)
        self.assertIn("news_role_guard", assessment.issues)
        self.assertEqual(assessment.setup_type, "signal_bar_entry_placeholder")
        self._assert_case_language(case, assessment.explanation)

    def _assert_case_language(self, case, explanation: str) -> None:
        lowered = explanation.lower()
        for phrase in case.must_explain:
            self.assertIn(phrase.lower(), lowered)
        for phrase in case.must_not_claim:
            self.assertNotIn(phrase.lower(), lowered)


if __name__ == "__main__":
    unittest.main()
