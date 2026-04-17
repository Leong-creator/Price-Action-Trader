from __future__ import annotations

import unittest
from decimal import Decimal

from tests.integration._support import (
    news_payload,
    run_offline_pipeline,
    summarize_pipeline,
    trend_csv_payload,
)


class OfflineE2EPipelineTests(unittest.TestCase):
    def test_pipeline_baseline_is_deterministic_across_repeated_runs(self) -> None:
        csv_payload = trend_csv_payload(include_follow_through_bar=True, reverse_rows=True)
        current_news = news_payload(current_medium=True)

        first = run_offline_pipeline(
            csv_payload=csv_payload,
            news_json=current_news,
            close_filled_position=True,
        )
        second = run_offline_pipeline(
            csv_payload=csv_payload,
            news_json=current_news,
            close_filled_position=True,
        )

        self.assertEqual(summarize_pipeline(first), summarize_pipeline(second))
        self.assertEqual(first.execution_result.status, "filled")
        self.assertEqual(first.backtest_report.stats.trade_count, 1)
        self.assertEqual(first.review_report.items[0].trade_outcome.status, "closed_trade")

    def test_risk_blocked_request_never_enters_fill_path(self) -> None:
        result = run_offline_pipeline(
            csv_payload=trend_csv_payload(include_follow_through_bar=False),
            proposed_quantity=Decimal("151"),
        )

        self.assertEqual(len(result.signals), 1)
        self.assertEqual(result.risk_decision.outcome, "block")
        self.assertEqual(result.execution_result.status, "blocked")
        self.assertIsNone(result.execution_result.suggested_order)
        self.assertIsNone(result.execution_result.fill_event)
        self.assertFalse(any(entry.action == "simulated_fill" for entry in result.execution_result.logs))
        self.assertEqual(result.review_report.items[0].trade_outcome.status, "execution_blocked")
        self.assertTrue(result.review_report.items[0].trade_outcome.error_reason)

    def test_review_and_audit_fields_remain_traceable(self) -> None:
        result = run_offline_pipeline(
            csv_payload=trend_csv_payload(include_follow_through_bar=True),
            news_json=news_payload(current_medium=True),
            close_filled_position=True,
            close_exit_price=Decimal("102.30"),
        )

        signal = result.signals[0]
        item = result.review_report.items[0]
        close_log = result.close_result.logs[0]

        self.assertTrue(signal.source_refs)
        self.assertEqual(item.kb_source_refs, signal.source_refs)
        self.assertTrue(item.pa_explanation)
        self.assertTrue(item.risk_notes)
        self.assertEqual(item.risk_notes, signal.risk_notes)
        self.assertTrue(item.news_source_refs)
        self.assertTrue(item.news_review_notes)
        self.assertTrue(item.trade_outcome.evidence_refs)
        self.assertEqual(close_log.source_refs, signal.source_refs)
        self.assertIsNotNone(close_log.quantity)
        self.assertIsNotNone(close_log.entry_price)
        self.assertIsNotNone(close_log.exit_price)
        self.assertIsNotNone(close_log.realized_pnl)
        self.assertIn(signal.source_refs[0], result.review_report.source_refs)
        self.assertIn(item.news_source_refs[0], result.review_report.source_refs)

    def test_end_of_data_path_is_robust_and_future_news_does_not_leak(self) -> None:
        result = run_offline_pipeline(
            csv_payload=trend_csv_payload(include_follow_through_bar=False),
            news_json=news_payload(future_critical=True),
        )

        self.assertEqual(len(result.signals), 1)
        self.assertEqual(result.backtest_report.stats.trade_count, 0)
        self.assertTrue(any("data is insufficient" in warning for warning in result.backtest_report.warnings))
        self.assertEqual(result.news_decisions[0].outcome, "allow")
        self.assertEqual(result.news_decisions[0].reason_codes, ("no_relevant_news",))
        self.assertEqual(result.review_report.items[0].trade_outcome.status, "no_trade")
        self.assertFalse(result.review_report.items[0].news_source_refs)


if __name__ == "__main__":
    unittest.main()
