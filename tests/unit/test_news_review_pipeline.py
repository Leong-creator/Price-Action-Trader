from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.backtest.contracts import BacktestReport, BacktestStats, SlippageResult, TradeRecord
from src.data.schema import NewsEvent
from src.execution.contracts import ExecutionLogEntry
from src.news import evaluate_news_context
from src.review import build_review_report
from src.strategy.contracts import Signal


class NewsReviewPipelineTests(unittest.TestCase):
    def test_no_news_returns_allow_decision(self) -> None:
        signal = self._signal("sig-no-news")

        decision = evaluate_news_context(signal, (), reference_timestamp=self._timestamp(3))

        self.assertEqual(decision.outcome, "allow")
        self.assertEqual(decision.reason_codes, ("no_relevant_news",))
        self.assertEqual(decision.matched_events, ())

    def test_medium_news_generates_caution_without_mutating_signal(self) -> None:
        signal = self._signal("sig-caution")
        original = signal
        decision = evaluate_news_context(
            signal,
            (
                self._news(
                    severity="medium",
                    headline="Product launch later today",
                    event_type="product",
                ),
            ),
            reference_timestamp=self._timestamp(3),
        )

        self.assertEqual(decision.outcome, "caution")
        self.assertEqual(signal, original)
        self.assertEqual(signal.entry_trigger, "placeholder entry")
        self.assertTrue(any("Product launch later today" in note for note in decision.risk_notes))
        self.assertEqual(decision.review_notes[0].kind, "risk_hint")

    def test_news_context_does_not_change_signal_primary_fields(self) -> None:
        signal = self._signal("sig-immutable")
        before = (
            signal.direction,
            signal.setup_type,
            signal.pa_context,
            signal.entry_trigger,
            signal.stop_rule,
            signal.target_rule,
        )

        _ = evaluate_news_context(
            signal,
            (
                self._news(
                    severity="high",
                    headline="Macro event later today",
                    event_type="macro_commentary",
                ),
            ),
            reference_timestamp=self._timestamp(3),
        )

        after = (
            signal.direction,
            signal.setup_type,
            signal.pa_context,
            signal.entry_trigger,
            signal.stop_rule,
            signal.target_rule,
        )
        self.assertEqual(before, after)

    def test_high_risk_event_blocks(self) -> None:
        signal = self._signal("sig-block")

        decision = evaluate_news_context(
            signal,
            (
                self._news(
                    severity="high",
                    headline="Earnings in 10 minutes",
                    event_type="earnings",
                ),
            ),
            reference_timestamp=self._timestamp(3),
        )

        self.assertEqual(decision.outcome, "block")
        self.assertEqual(decision.reason_codes, ("high_risk_news_event",))

    def test_review_combines_kb_news_and_trade_result(self) -> None:
        signal = self._signal("sig-review")
        decision = evaluate_news_context(
            signal,
            (
                self._news(
                    severity="medium",
                    headline="Analyst day adds volatility risk",
                    event_type="analyst_day",
                ),
            ),
            reference_timestamp=self._timestamp(3),
        )
        report = build_review_report(
            [signal],
            [decision],
            self._backtest_report(
                trades=(
                    self._trade(
                        signal_id=signal.signal_id,
                        exit_reason="target_hit",
                        pnl_r=Decimal("2.0000"),
                    ),
                )
            ),
            generated_at=self._timestamp(9),
        )

        item = report.items[0]
        self.assertEqual(item.trade_outcome.status, "closed_trade")
        self.assertEqual(item.trade_outcome.pnl_r, Decimal("2.0000"))
        self.assertEqual(item.kb_source_refs, signal.source_refs)
        self.assertEqual(item.news_outcome, "caution")
        self.assertTrue(item.news_source_refs)
        self.assertEqual(item.news_review_notes[0].kind, "risk_hint")
        self.assertIn(signal.source_refs[0], report.source_refs)
        self.assertIn(item.news_source_refs[0], report.source_refs)

    def test_review_without_trade_still_builds_item(self) -> None:
        signal = self._signal("sig-no-trade")
        decision = evaluate_news_context(signal, (), reference_timestamp=self._timestamp(3))

        report = build_review_report([signal], [decision], self._backtest_report(trades=()))

        self.assertEqual(len(report.items), 1)
        self.assertEqual(report.items[0].trade_outcome.status, "no_trade")
        self.assertEqual(report.items[0].news_review_notes[0].kind, "explanation")
        self.assertTrue(any("No trade was recorded" in note for note in report.items[0].improvement_notes))

    def test_execution_blocked_path_carries_error_reason(self) -> None:
        signal = self._signal("sig-blocked")
        decision = evaluate_news_context(signal, (), reference_timestamp=self._timestamp(3))
        log = ExecutionLogEntry(
            occurred_at=self._timestamp(10),
            action="risk_check",
            status="blocked",
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            reason_codes=("market_closed", "high_risk_news_event"),
            message="Execution blocked before fill.",
            source_refs=("paper:execution:blocked",),
        )

        report = build_review_report(
            [signal],
            [decision],
            self._backtest_report(trades=()),
            execution_logs=[log],
        )

        self.assertEqual(report.items[0].trade_outcome.status, "execution_blocked")
        self.assertEqual(report.items[0].news_review_notes[0].kind, "explanation")
        self.assertIn("market_closed", report.items[0].trade_outcome.error_reason)

    def test_blocked_news_role_is_visible_in_review_output(self) -> None:
        signal = self._signal("sig-block-role")
        decision = evaluate_news_context(
            signal,
            (
                self._news(
                    severity="critical",
                    headline="Trading halt pending news",
                    event_type="trading_halt",
                ),
            ),
            reference_timestamp=self._timestamp(3),
        )

        report = build_review_report([signal], [decision], self._backtest_report(trades=()))

        self.assertEqual(report.items[0].news_outcome, "block")
        self.assertEqual(report.items[0].news_review_notes[0].kind, "filter")

    def test_multiple_news_events_are_summarized_stably(self) -> None:
        signal = self._signal("sig-multi-news")
        events = (
            self._news(
                severity="low",
                headline="Late filing resolved",
                event_type="filing",
                minute_offset=2,
            ),
            self._news(
                severity="medium",
                headline="Conference appearance scheduled",
                event_type="conference",
                minute_offset=1,
            ),
            self._news(
                severity="medium",
                headline="Conference appearance scheduled",
                event_type="conference",
                minute_offset=1,
            ),
        )

        first = evaluate_news_context(signal, events, reference_timestamp=self._timestamp(4))
        second = evaluate_news_context(signal, tuple(reversed(events)), reference_timestamp=self._timestamp(4))

        self.assertEqual(first.headline_summary, second.headline_summary)
        self.assertEqual(first.source_refs, second.source_refs)
        self.assertEqual(len(first.matched_events), 3)

    def test_future_event_does_not_affect_current_signal(self) -> None:
        signal = self._signal("sig-future")

        decision = evaluate_news_context(
            signal,
            (
                self._news(
                    severity="critical",
                    headline="Trading halt tomorrow morning",
                    event_type="trading_halt",
                    minute_offset=60,
                ),
            ),
            reference_timestamp=self._timestamp(3),
        )

        self.assertEqual(decision.outcome, "allow")
        self.assertEqual(decision.reason_codes, ("no_relevant_news",))
        self.assertEqual(decision.matched_events, ())

    def test_missing_reference_timestamp_raises_clear_error(self) -> None:
        signal = self._signal("sig-missing-reference")

        with self.assertRaisesRegex(ValueError, "reference_timestamp is required"):
            evaluate_news_context(
                signal,
                (
                    self._news(
                        severity="medium",
                        headline="Conference appearance scheduled",
                        event_type="conference",
                    ),
                ),
            )

    def _signal(self, signal_id: str) -> Signal:
        return Signal(
            signal_id=signal_id,
            symbol="SAMPLE",
            market="US",
            timeframe="5m",
            direction="long",
            setup_type="signal_bar_entry_placeholder",
            pa_context="trend",
            entry_trigger="placeholder entry",
            stop_rule="signal-bar low",
            target_rule="2R target",
            invalidation="close back below prior high",
            confidence="low",
            source_refs=(
                "wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md",
                "wiki:knowledge/wiki/rules/m3-research-reference-pack.md",
            ),
            explanation="research-only paper signal",
            risk_notes=("research-only placeholder",),
        )

    def _news(
        self,
        *,
        severity: str,
        headline: str,
        event_type: str,
        minute_offset: int = 0,
    ) -> NewsEvent:
        return NewsEvent(
            symbol="SAMPLE",
            market="US",
            timestamp=self._timestamp(3) + timedelta(minutes=minute_offset),
            source="synthetic-news",
            event_type=event_type,
            headline=headline,
            severity=severity,
            notes="headline risk only",
            timezone="America/New_York",
        )

    def _trade(self, *, signal_id: str, exit_reason: str, pnl_r: Decimal) -> TradeRecord:
        timestamp = self._timestamp(4)
        return TradeRecord(
            signal_id=signal_id,
            symbol="SAMPLE",
            market="US",
            timeframe="5m",
            direction="long",
            setup_type="signal_bar_entry_placeholder",
            signal_bar_index=2,
            signal_bar_timestamp=self._timestamp(2),
            entry_bar_index=3,
            entry_timestamp=timestamp,
            entry_price=Decimal("100"),
            stop_price=Decimal("99"),
            target_price=Decimal("102"),
            exit_bar_index=4,
            exit_timestamp=timestamp + timedelta(minutes=5),
            exit_price=Decimal("102") if pnl_r > 0 else Decimal("99"),
            exit_reason=exit_reason,
            risk_per_share=Decimal("1"),
            pnl_per_share=Decimal("2") if pnl_r > 0 else Decimal("-1"),
            pnl_r=pnl_r,
            bars_held=1,
            source_refs=("wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md",),
            explanation="deterministic backtest assumed next-bar-open entry",
            risk_notes=("research-only placeholder",),
        )

    def _backtest_report(self, *, trades: tuple[TradeRecord, ...]) -> BacktestReport:
        return BacktestReport(
            trades=trades,
            stats=BacktestStats(
                total_signals=1,
                trade_count=len(trades),
                closed_trade_count=len(trades),
                win_count=sum(1 for trade in trades if trade.pnl_r > 0),
                loss_count=sum(1 for trade in trades if trade.pnl_r < 0),
                win_rate=Decimal("1.0000") if trades else Decimal("0.0000"),
                average_win_r=Decimal("2.0000") if trades else Decimal("0.0000"),
                average_loss_r=Decimal("0.0000"),
                expectancy_r=Decimal("2.0000") if trades else Decimal("0.0000"),
                total_pnl_r=sum((trade.pnl_r for trade in trades), start=Decimal("0.0000")),
                profit_factor=None,
                max_drawdown_r=Decimal("0.0000"),
                trades_per_100_bars=Decimal("10.0000") if trades else Decimal("0.0000"),
                slippage_sensitivity=(
                    SlippageResult(
                        label="baseline_0r",
                        total_pnl_r=sum((trade.pnl_r for trade in trades), start=Decimal("0.0000")),
                        delta_from_baseline_r=Decimal("0.0000"),
                    ),
                ),
            ),
            summary="backtest summary",
            warnings=(),
            assumptions=("paper-only baseline",),
        )

    def _timestamp(self, index: int) -> datetime:
        base = datetime(2026, 1, 5, 9, 30, tzinfo=ZoneInfo("America/New_York"))
        return base + timedelta(minutes=index * 5)


if __name__ == "__main__":
    unittest.main()
