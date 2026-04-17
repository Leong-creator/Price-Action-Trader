from __future__ import annotations

import unittest
from decimal import Decimal

from src.backtest import run_backtest
from src.data import build_replay
from src.execution import PaperBrokerAdapter
from src.risk import evaluate_order_request
from src.strategy import generate_signals

from tests.reliability._support import (
    build_execution_request,
    default_risk_config,
    default_session_state,
    extended_bullish_trade_bars,
)


class ForbiddenPathTests(unittest.TestCase):
    def test_risk_block_never_enters_simulated_fill(self) -> None:
        bars = extended_bullish_trade_bars()
        signals = generate_signals(build_replay(bars))
        report = run_backtest(bars, signals)
        signal = signals[0]
        trade = report.trades[0]

        session_state = default_session_state()
        config = default_risk_config()
        risk_decision = evaluate_order_request(
            signal,
            entry_price=trade.entry_price,
            stop_price=trade.stop_price,
            proposed_quantity=Decimal("151"),
            positions=(),
            session_state=session_state,
            config=config,
            market_is_open=True,
        )
        adapter = PaperBrokerAdapter()
        execution_result = adapter.submit(
            build_execution_request(signal=signal, trade=trade, quantity="151"),
            risk_decision=risk_decision,
            session_state=session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )

        self.assertEqual(risk_decision.outcome, "block")
        self.assertEqual(execution_result.status, "blocked")
        self.assertIsNone(execution_result.fill_event)
        self.assertFalse(any(log.action == "simulated_fill" for log in execution_result.logs))

    def test_mismatched_allow_decision_never_enters_simulated_fill(self) -> None:
        bars = extended_bullish_trade_bars()
        signals = generate_signals(build_replay(bars))
        report = run_backtest(bars, signals)
        signal = signals[0]
        trade = report.trades[0]

        session_state = default_session_state()
        config = default_risk_config()
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
        mismatched_request = build_execution_request(
            signal=signal,
            trade=trade,
            quantity="2",
        )
        execution_result = adapter.submit(
            mismatched_request,
            risk_decision=risk_decision,
            session_state=session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )

        self.assertEqual(risk_decision.outcome, "allow")
        self.assertEqual(execution_result.status, "blocked")
        self.assertIsNone(execution_result.fill_event)
        self.assertFalse(any(log.action == "simulated_fill" for log in execution_result.logs))
        self.assertIn("risk_decision_mismatch", execution_result.logs[-1].reason_codes)


if __name__ == "__main__":
    unittest.main()
