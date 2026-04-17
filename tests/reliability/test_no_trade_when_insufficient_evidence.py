from __future__ import annotations

import unittest

from src.strategy import assess_kb_alignment

from tests.reliability._support import (
    build_bundle_from_refs,
    load_case,
    sideways_bars,
    bullish_trend_bars,
)


class NoTradeWhenInsufficientEvidenceTests(unittest.TestCase):
    def test_context_only_case_allows_wait(self) -> None:
        case = load_case("gc_us_5m_context_only_wait")
        bundle = build_bundle_from_refs(*case.required_source_refs)

        assessment = assess_kb_alignment(sideways_bars(), knowledge=bundle)

        self.assertIn(assessment.action, case.allowed_actions)
        self.assertIsNone(assessment.setup_type)
        self.assertEqual(assessment.context, case.expected_context["market_cycle"])
        self._assert_case_language(case, assessment.explanation)

    def test_not_applicable_case_blocks_trade(self) -> None:
        case = load_case("gc_us_5m_not_applicable_blocks_trade")
        bundle = build_bundle_from_refs(*case.required_source_refs)

        assessment = assess_kb_alignment(
            bullish_trend_bars(market=case.market, timeframe=case.timeframe),
            knowledge=bundle,
        )

        self.assertIn(assessment.action, case.allowed_actions)
        self.assertIn("not_applicable", assessment.issues)
        self.assertIn("signal_bar_entry_placeholder", assessment.explanation)
        self._assert_case_language(case, assessment.explanation)

    def _assert_case_language(self, case, explanation: str) -> None:
        lowered = explanation.lower()
        for phrase in case.must_explain:
            self.assertIn(phrase.lower(), lowered)
        for phrase in case.must_not_claim:
            self.assertNotIn(phrase.lower(), lowered)


if __name__ == "__main__":
    unittest.main()
