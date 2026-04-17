from __future__ import annotations

import unittest
from decimal import Decimal

from src.backtest import run_backtest
from src.data import build_replay
from src.execution import PaperBrokerAdapter
from src.news import evaluate_news_context
from src.review import build_review_report
from src.risk import evaluate_order_request
from src.strategy import generate_signals

from tests.reliability._support import (
    build_execution_request,
    default_risk_config,
    default_session_state,
    extended_bullish_trade_bars,
    past_caution_news,
)


class AuditTraceabilityTests(unittest.TestCase):
    def test_closed_trade_audit_fields_are_complete(self) -> None:
        bars = extended_bullish_trade_bars()
        news_events = past_caution_news()
        signals = generate_signals(build_replay(bars, news_events))
        report = run_backtest(bars, signals)
        signal = signals[0]
        trade = report.trades[0]

        config = default_risk_config()
        session_state = default_session_state()
        risk_decision = evaluate_order_request(
            signal,
            entry_price=trade.entry_price,
            stop_price=trade.stop_price,
            proposed_quantity=Decimal("1"),
            positions=(),
            session_state=session_state,
            config=config,
            market_is_open=True,
        )
        adapter = PaperBrokerAdapter()
        execution_result = adapter.submit(
            build_execution_request(signal=signal, trade=trade),
            risk_decision=risk_decision,
            session_state=session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )
        close_result = adapter.close_position(
            position_id=execution_result.fill_event.position_id,
            exit_price=trade.exit_price,
            closed_at=trade.exit_timestamp,
            positions=execution_result.resulting_positions,
            session_state=execution_result.session_state,
            config=config,
            exit_reason=trade.exit_reason,
        )

        audit_log = close_result.logs[0]
        self.assertEqual(audit_log.signal_id, signal.signal_id)
        self.assertEqual(audit_log.symbol, signal.symbol)
        self.assertTrue(audit_log.source_refs)
        self.assertIsNotNone(audit_log.quantity)
        self.assertIsNotNone(audit_log.entry_price)
        self.assertIsNotNone(audit_log.exit_price)
        self.assertIsNotNone(audit_log.realized_pnl)

    def test_review_report_keeps_kb_risk_news_and_trade_traceability(self) -> None:
        bars = extended_bullish_trade_bars()
        news_events = past_caution_news()
        signals = generate_signals(build_replay(bars, news_events))
        report = run_backtest(bars, signals)
        signal = signals[0]
        trade = report.trades[0]

        config = default_risk_config()
        session_state = default_session_state()
        risk_decision = evaluate_order_request(
            signal,
            entry_price=trade.entry_price,
            stop_price=trade.stop_price,
            proposed_quantity=Decimal("1"),
            positions=(),
            session_state=session_state,
            config=config,
            market_is_open=True,
        )
        adapter = PaperBrokerAdapter()
        execution_result = adapter.submit(
            build_execution_request(signal=signal, trade=trade),
            risk_decision=risk_decision,
            session_state=session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )
        close_result = adapter.close_position(
            position_id=execution_result.fill_event.position_id,
            exit_price=trade.exit_price,
            closed_at=trade.exit_timestamp,
            positions=execution_result.resulting_positions,
            session_state=execution_result.session_state,
            config=config,
            exit_reason=trade.exit_reason,
        )
        news_decision = evaluate_news_context(
            signal,
            news_events,
            reference_timestamp=trade.signal_bar_timestamp,
        )

        review = build_review_report(
            signals,
            [news_decision],
            report,
            execution_logs=execution_result.logs + close_result.logs,
        )

        item = review.items[0]
        self.assertTrue(item.kb_source_refs)
        self.assertTrue(item.pa_explanation)
        self.assertTrue(item.risk_notes)
        self.assertEqual(item.risk_notes, signal.risk_notes)
        self.assertTrue(item.news_source_refs)
        self.assertTrue(item.news_review_notes)
        self.assertEqual(item.trade_outcome.status, "closed_trade")
        self.assertTrue(item.trade_outcome.evidence_refs)
        self.assertIn(signal.source_refs[0], review.source_refs)
        self.assertIn(item.news_source_refs[0], review.source_refs)


if __name__ == "__main__":
    unittest.main()
