from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.execution import ExecutionRequest, PaperBrokerAdapter
from src.risk import (
    PositionSnapshot,
    RiskConfig,
    SessionRiskState,
    evaluate_order_request,
    maybe_resume_trading,
)
from src.strategy.contracts import Signal


class PaperExecutionPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = PaperBrokerAdapter()
        self.config = RiskConfig(
            max_risk_per_order=Decimal("150"),
            max_total_exposure=Decimal("500"),
            max_symbol_exposure_ratio=Decimal("1"),
            max_daily_loss=Decimal("120"),
            max_consecutive_losses=2,
            allow_manual_resume_from_loss_streak=True,
        )
        self.session_state = SessionRiskState(session_key="2026-01-05")

    def test_allow_path_creates_fill_position_and_logs(self) -> None:
        request = self._request(signal_id="sig-allow", requested_at=self._timestamp(0))
        decision = evaluate_order_request(
            request.signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=(),
            session_state=self.session_state,
            config=self.config,
            market_is_open=True,
        )

        result = self.adapter.submit(
            request,
            risk_decision=decision,
            session_state=self.session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )

        self.assertEqual(decision.outcome, "allow")
        self.assertEqual(result.status, "filled")
        self.assertIsNotNone(result.suggested_order)
        self.assertIsNotNone(result.fill_event)
        self.assertEqual(len(result.resulting_positions), 1)
        self.assertEqual(result.resulting_positions[0].signal_id, request.signal.signal_id)
        self.assertEqual(result.resulting_seen_signal_ids, frozenset({request.signal.signal_id}))
        self.assertEqual([entry.action for entry in result.logs], ["risk_check", "suggested_order_created", "simulated_fill"])

    def test_market_closed_is_blocked_before_fill(self) -> None:
        request = self._request(signal_id="sig-closed", requested_at=self._timestamp(1))
        decision = evaluate_order_request(
            request.signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=(),
            session_state=self.session_state,
            config=self.config,
            market_is_open=False,
        )

        result = self.adapter.submit(
            request,
            risk_decision=decision,
            session_state=self.session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )

        self.assertEqual(decision.outcome, "block")
        self.assertEqual(result.status, "blocked")
        self.assertIsNone(result.fill_event)
        self.assertEqual(result.logs[-1].reason_codes, ("market_closed",))

    def test_duplicate_signal_is_blocked_by_execution_guard(self) -> None:
        request = self._request(signal_id="sig-duplicate", requested_at=self._timestamp(2))
        decision = evaluate_order_request(
            request.signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=(),
            session_state=self.session_state,
            config=self.config,
            market_is_open=True,
        )
        first = self.adapter.submit(
            request,
            risk_decision=decision,
            session_state=self.session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )
        second = self.adapter.submit(
            request,
            risk_decision=decision,
            session_state=self.session_state,
            positions=first.resulting_positions,
            seen_signal_ids=first.resulting_seen_signal_ids,
        )

        self.assertEqual(first.status, "filled")
        self.assertEqual(second.status, "blocked")
        self.assertEqual(second.logs[-1].reason_codes, ("duplicate_signal",))
        self.assertEqual(len(second.resulting_positions), 1)

    def test_risk_block_path_prevents_suggested_order(self) -> None:
        request = self._request(
            signal_id="sig-risk-block",
            requested_at=self._timestamp(3),
            proposed_quantity=Decimal("151"),
        )
        decision = evaluate_order_request(
            request.signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=(),
            session_state=self.session_state,
            config=self.config,
            market_is_open=True,
        )

        result = self.adapter.submit(
            request,
            risk_decision=decision,
            session_state=self.session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )

        self.assertEqual(decision.outcome, "block")
        self.assertEqual(result.status, "blocked")
        self.assertIsNone(result.suggested_order)
        self.assertIsNone(result.fill_event)
        self.assertIn("max_risk_per_order_exceeded", result.logs[-1].reason_codes)

    def test_consecutive_losses_trigger_halt_and_recovery_on_next_session(self) -> None:
        first_request = self._request(signal_id="sig-loss-1", requested_at=self._timestamp(4))
        first_fill = self._submit_allowed(first_request)
        first_close = self.adapter.close_position(
            position_id=first_fill.fill_event.position_id,
            exit_price=Decimal("98"),
            closed_at=self._timestamp(5),
            positions=first_fill.resulting_positions,
            session_state=first_fill.session_state,
            config=self.config,
            exit_reason="stop_hit",
        )
        second_request = self._request(signal_id="sig-loss-2", requested_at=self._timestamp(6))
        second_fill = self._submit_allowed(second_request)
        second_close = self.adapter.close_position(
            position_id=second_fill.fill_event.position_id,
            exit_price=Decimal("98"),
            closed_at=self._timestamp(7),
            positions=second_fill.resulting_positions,
            session_state=first_close.session_state,
            config=self.config,
            exit_reason="stop_hit",
        )

        halted_decision = evaluate_order_request(
            self._signal("sig-after-halt"),
            entry_price=Decimal("100"),
            stop_price=Decimal("99"),
            proposed_quantity=Decimal("1"),
            positions=(),
            session_state=second_close.session_state,
            config=self.config,
            market_is_open=True,
        )
        resumed_state = maybe_resume_trading(
            second_close.session_state,
            config=self.config,
            next_session_key="2026-01-06",
            manual_resume=False,
        )
        resumed_decision = evaluate_order_request(
            self._signal("sig-after-reset"),
            entry_price=Decimal("100"),
            stop_price=Decimal("99"),
            proposed_quantity=Decimal("1"),
            positions=(),
            session_state=resumed_state,
            config=self.config,
            market_is_open=True,
        )

        self.assertTrue(second_close.session_state.pause.paused)
        self.assertEqual(second_close.session_state.pause.reason, "consecutive_losses_limit")
        self.assertEqual(second_close.logs[0].signal_id, second_fill.fill_event.signal_id)
        self.assertEqual(second_close.logs[0].source_refs, second_close.closed_position.source_refs)
        self.assertEqual(second_close.logs[0].quantity, second_close.closed_position.quantity)
        self.assertEqual(second_close.logs[0].entry_price, second_close.closed_position.entry_price)
        self.assertEqual(second_close.logs[0].exit_price, Decimal("98"))
        self.assertEqual(second_close.logs[0].realized_pnl, Decimal("-2"))
        self.assertEqual(second_close.logs[1].signal_id, second_fill.fill_event.signal_id)
        self.assertEqual(second_close.logs[1].source_refs, second_close.closed_position.source_refs)
        self.assertEqual(second_close.logs[1].quantity, second_close.closed_position.quantity)
        self.assertEqual(halted_decision.outcome, "halted")
        self.assertFalse(resumed_state.pause.paused)
        self.assertEqual(resumed_decision.outcome, "allow")

    def test_manual_resume_is_allowed_for_loss_streak_when_configured(self) -> None:
        paused_state = SessionRiskState(
            session_key="2026-01-05",
            realized_pnl=Decimal("-50"),
            consecutive_losses=2,
            pause=self.session_state.pause.__class__(
                paused=True,
                reason="consecutive_losses_limit",
                message="Trading paused after exceeding the consecutive loss limit.",
            ),
        )

        resumed_state = maybe_resume_trading(
            paused_state,
            config=self.config,
            manual_resume=True,
        )

        self.assertFalse(resumed_state.pause.paused)
        self.assertEqual(resumed_state.consecutive_losses, 0)

    def test_total_exposure_and_symbol_concentration_are_blocked(self) -> None:
        positions = (
            PositionSnapshot(symbol="SAMPLE", quantity=Decimal("2"), market_value=Decimal("250")),
        )
        request = self._request(signal_id="sig-concentration", requested_at=self._timestamp(8), proposed_quantity=Decimal("3"))

        decision = evaluate_order_request(
            request.signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=positions,
            session_state=self.session_state,
            config=self.config,
            market_is_open=True,
        )

        self.assertEqual(decision.outcome, "block")
        self.assertIn(
            decision.reason_codes[0],
            {"max_total_exposure_exceeded", "symbol_concentration_exceeded"},
        )

    def test_config_error_is_exposed_through_execution_result(self) -> None:
        request = self._request(signal_id="sig-config-error", requested_at=self._timestamp(9))
        bad_config = RiskConfig(
            max_risk_per_order=Decimal("150"),
            max_total_exposure=Decimal("0"),
            max_symbol_exposure_ratio=Decimal("1"),
            max_daily_loss=Decimal("120"),
            max_consecutive_losses=2,
            allow_manual_resume_from_loss_streak=True,
        )
        decision = evaluate_order_request(
            request.signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=(),
            session_state=self.session_state,
            config=bad_config,
            market_is_open=True,
        )

        result = self.adapter.submit(
            request,
            risk_decision=decision,
            session_state=self.session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )

        self.assertEqual(decision.outcome, "config_error")
        self.assertEqual(result.status, "blocked")
        self.assertIn("invalid_max_total_exposure", result.logs[-1].reason_codes)

    def test_invalid_request_is_exposed_through_execution_result(self) -> None:
        request = self._request(
            signal_id="sig-invalid-request",
            requested_at=self._timestamp(10),
            proposed_quantity=Decimal("0"),
        )
        decision = evaluate_order_request(
            request.signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=(),
            session_state=self.session_state,
            config=self.config,
            market_is_open=True,
        )

        result = self.adapter.submit(
            request,
            risk_decision=decision,
            session_state=self.session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )

        self.assertEqual(decision.outcome, "block")
        self.assertEqual(result.status, "blocked")
        self.assertIn("invalid_request", result.logs[-1].reason_codes)

    def _submit_allowed(self, request: ExecutionRequest):
        decision = evaluate_order_request(
            request.signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=(),
            session_state=self.session_state,
            config=self.config,
            market_is_open=True,
        )
        return self.adapter.submit(
            request,
            risk_decision=decision,
            session_state=self.session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )

    def test_mismatched_allow_decision_is_blocked_before_fill(self) -> None:
        approved_request = self._request(signal_id="sig-approved", requested_at=self._timestamp(11))
        approved_decision = evaluate_order_request(
            approved_request.signal,
            entry_price=approved_request.entry_price,
            stop_price=approved_request.stop_price,
            proposed_quantity=approved_request.proposed_quantity,
            positions=(),
            session_state=self.session_state,
            config=self.config,
            market_is_open=True,
        )
        mismatched_request = self._request(signal_id="sig-other", requested_at=self._timestamp(12))

        result = self.adapter.submit(
            mismatched_request,
            risk_decision=approved_decision,
            session_state=self.session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.logs[-1].reason_codes, ("risk_decision_mismatch",))
        self.assertIsNone(result.fill_event)

    def test_stale_allow_decision_is_blocked_after_session_state_changes(self) -> None:
        request = self._request(signal_id="sig-stale", requested_at=self._timestamp(13))
        approved_decision = evaluate_order_request(
            request.signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=(),
            session_state=self.session_state,
            config=self.config,
            market_is_open=True,
        )
        changed_state = SessionRiskState(
            session_key=self.session_state.session_key,
            realized_pnl=Decimal("-10"),
            consecutive_losses=1,
        )

        result = self.adapter.submit(
            request,
            risk_decision=approved_decision,
            session_state=changed_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.logs[-1].reason_codes, ("risk_decision_mismatch",))
        self.assertIsNone(result.fill_event)

    def test_direction_mismatch_is_blocked_even_when_signal_id_matches(self) -> None:
        approved_request = self._request(signal_id="sig-same", requested_at=self._timestamp(14))
        approved_decision = evaluate_order_request(
            approved_request.signal,
            entry_price=approved_request.entry_price,
            stop_price=approved_request.stop_price,
            proposed_quantity=approved_request.proposed_quantity,
            positions=(),
            session_state=self.session_state,
            config=self.config,
            market_is_open=True,
        )
        reversed_request = ExecutionRequest(
            signal=Signal(
                signal_id="sig-same",
                symbol="SAMPLE",
                market="US",
                timeframe="5m",
                direction="short",
                setup_type="signal_bar_entry_placeholder",
                pa_context="trend",
                entry_trigger="placeholder entry",
                stop_rule="signal-bar low",
                target_rule="2R target",
                invalidation="close back below prior high",
                confidence="low",
                source_refs=("knowledge/wiki/setups/signal-bar-entry-placeholder.md",),
                explanation="research-only paper signal",
                risk_notes=("research-only placeholder",),
            ),
            requested_at=self._timestamp(15),
            session_key=self.session_state.session_key,
            entry_price=Decimal("100"),
            stop_price=Decimal("99"),
            target_price=Decimal("102"),
            proposed_quantity=Decimal("1"),
        )

        result = self.adapter.submit(
            reversed_request,
            risk_decision=approved_decision,
            session_state=self.session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.logs[-1].reason_codes, ("risk_decision_mismatch",))
        self.assertIsNone(result.fill_event)

    def _request(
        self,
        *,
        signal_id: str,
        requested_at: datetime,
        proposed_quantity: Decimal = Decimal("1"),
    ) -> ExecutionRequest:
        return ExecutionRequest(
            signal=self._signal(signal_id),
            requested_at=requested_at,
            session_key=requested_at.date().isoformat(),
            entry_price=Decimal("100"),
            stop_price=Decimal("99"),
            target_price=Decimal("102"),
            proposed_quantity=proposed_quantity,
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
            source_refs=("knowledge/wiki/setups/signal-bar-entry-placeholder.md",),
            explanation="research-only paper signal",
            risk_notes=("research-only placeholder",),
        )

    def _timestamp(self, index: int) -> datetime:
        base = datetime(2026, 1, 5, 9, 30, tzinfo=ZoneInfo("America/New_York"))
        return base + timedelta(minutes=index * 5)


if __name__ == "__main__":
    unittest.main()
