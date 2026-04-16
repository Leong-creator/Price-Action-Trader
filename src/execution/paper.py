from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from src.risk import RiskConfig, RiskDecision, SessionRiskState, record_closed_trade

from .contracts import (
    ExecutionRequest,
    ExecutionResult,
    FillEvent,
    PaperPosition,
    PositionCloseResult,
    SuggestedOrder,
)
from .logging import build_execution_log_entry
from .state import apply_fill, build_fill_id, build_position_id, close_position, detect_duplicate_signal


class PaperBrokerAdapter:
    def submit(
        self,
        request: ExecutionRequest,
        *,
        risk_decision: RiskDecision,
        session_state: SessionRiskState,
        positions: Sequence[PaperPosition],
        seen_signal_ids: frozenset[str],
    ) -> ExecutionResult:
        logs = [
            build_execution_log_entry(
                occurred_at=request.requested_at,
                action="risk_check",
                status="blocked" if risk_decision.outcome != "allow" else "filled",
                signal=request.signal,
                reason_codes=risk_decision.reason_codes,
                message="Paper request evaluated by risk engine.",
                quantity=request.proposed_quantity,
                entry_price=request.entry_price,
            )
        ]
        resulting_state = risk_decision.resulting_state

        if risk_decision.outcome == "allow" and not _risk_decision_matches_request(
            risk_decision,
            request=request,
            session_state=session_state,
        ):
            logs.append(
                build_execution_log_entry(
                    occurred_at=request.requested_at,
                    action="risk_decision_mismatch",
                    status="blocked",
                    signal=request.signal,
                    reason_codes=("risk_decision_mismatch",),
                    message="Paper order blocked because the risk decision does not match the current request or session state.",
                    quantity=request.proposed_quantity,
                    entry_price=request.entry_price,
                )
            )
            return ExecutionResult(
                status="blocked",
                request=request,
                risk_decision=risk_decision,
                suggested_order=None,
                fill_event=None,
                resulting_positions=tuple(positions),
                resulting_seen_signal_ids=seen_signal_ids,
                session_state=session_state,
                logs=tuple(logs),
            )

        if risk_decision.outcome != "allow":
            logs.append(
                build_execution_log_entry(
                    occurred_at=request.requested_at,
                    action="paper_order_blocked",
                    status="blocked",
                    signal=request.signal,
                    reason_codes=risk_decision.reason_codes,
                    message="Paper order blocked before simulated fill.",
                    quantity=request.proposed_quantity,
                    entry_price=request.entry_price,
                )
            )
            return ExecutionResult(
                status="blocked",
                request=request,
                risk_decision=risk_decision,
                suggested_order=None,
                fill_event=None,
                resulting_positions=tuple(positions),
                resulting_seen_signal_ids=seen_signal_ids,
                session_state=resulting_state,
                logs=tuple(logs),
            )

        if detect_duplicate_signal(request.signal.signal_id, seen_signal_ids):
            logs.append(
                build_execution_log_entry(
                    occurred_at=request.requested_at,
                    action="duplicate_signal_blocked",
                    status="blocked",
                    signal=request.signal,
                    reason_codes=("duplicate_signal",),
                    message="Duplicate paper signal was blocked.",
                    quantity=request.proposed_quantity,
                    entry_price=request.entry_price,
                )
            )
            return ExecutionResult(
                status="blocked",
                request=request,
                risk_decision=risk_decision,
                suggested_order=None,
                fill_event=None,
                resulting_positions=tuple(positions),
                resulting_seen_signal_ids=seen_signal_ids,
                session_state=resulting_state,
                logs=tuple(logs),
            )

        suggested_order = SuggestedOrder(
            signal_id=request.signal.signal_id,
            symbol=request.signal.symbol,
            market=request.signal.market,
            timeframe=request.signal.timeframe,
            direction=request.signal.direction,
            order_type="paper_market",
            quantity=risk_decision.approved_quantity,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            target_price=request.target_price,
            risk_amount=risk_decision.risk_amount,
        )
        fill_id = build_fill_id(
            request.signal.signal_id,
            suggested_order.quantity,
            suggested_order.entry_price,
        )
        position_id = build_position_id(fill_id)
        fill_event = FillEvent(
            fill_id=fill_id,
            signal_id=request.signal.signal_id,
            position_id=position_id,
            symbol=request.signal.symbol,
            direction=request.signal.direction,
            quantity=suggested_order.quantity,
            fill_price=suggested_order.entry_price,
            filled_at=request.requested_at,
            simulated=True,
        )
        resulting_positions = apply_fill(
            positions,
            fill_event=fill_event,
            market=request.signal.market,
            timeframe=request.signal.timeframe,
            stop_price=request.stop_price,
            target_price=request.target_price,
            source_refs=request.signal.source_refs,
        )
        resulting_seen_signal_ids = frozenset(set(seen_signal_ids) | {request.signal.signal_id})
        logs.extend(
            [
                build_execution_log_entry(
                    occurred_at=request.requested_at,
                    action="suggested_order_created",
                    status="filled",
                    signal=request.signal,
                    reason_codes=("paper_order_ready",),
                    message="Paper suggested order created after risk approval.",
                    quantity=suggested_order.quantity,
                    entry_price=suggested_order.entry_price,
                    related_position_id=position_id,
                ),
                build_execution_log_entry(
                    occurred_at=request.requested_at,
                    action="simulated_fill",
                    status="filled",
                    signal=request.signal,
                    reason_codes=("simulated_fill",),
                    message="Paper broker simulated an immediate market fill.",
                    quantity=fill_event.quantity,
                    entry_price=fill_event.fill_price,
                    related_position_id=position_id,
                    related_fill_id=fill_id,
                ),
            ]
        )
        return ExecutionResult(
            status="filled",
            request=request,
            risk_decision=risk_decision,
            suggested_order=suggested_order,
            fill_event=fill_event,
            resulting_positions=resulting_positions,
            resulting_seen_signal_ids=resulting_seen_signal_ids,
            session_state=resulting_state,
            logs=tuple(logs),
        )

    def close_position(
        self,
        *,
        position_id: str,
        exit_price: Decimal,
        closed_at: datetime,
        positions: Sequence[PaperPosition],
        session_state: SessionRiskState,
        config: RiskConfig,
        session_key: str | None = None,
        exit_reason: str = "paper_exit",
    ) -> PositionCloseResult:
        remaining_positions, closed_position, realized_pnl = close_position(
            positions,
            position_id=position_id,
            exit_price=exit_price,
        )
        if closed_position is None:
            return PositionCloseResult(
                status="error",
                closed_position=None,
                realized_pnl=Decimal("0"),
                resulting_positions=tuple(positions),
                session_state=session_state,
                logs=(
                    build_execution_log_entry(
                        occurred_at=closed_at,
                        action="position_close_failed",
                        status="error",
                        signal=None,
                        reason_codes=("unknown_position",),
                        message="Paper close failed because the position_id was not found.",
                    ),
                ),
            )

        next_state = record_closed_trade(
            session_state,
            pnl_amount=realized_pnl,
            config=config,
            session_key=session_key,
        )
        logs = [
            build_execution_log_entry(
                occurred_at=closed_at,
                action="position_closed",
                status="closed",
                signal=None,
                reason_codes=(exit_reason,),
                message=(
                    f"Paper position {closed_position.position_id} closed with realized PnL "
                    f"{realized_pnl}."
                ),
                signal_id=closed_position.signal_id,
                symbol=closed_position.symbol,
                source_refs=closed_position.source_refs,
                quantity=closed_position.quantity,
                entry_price=closed_position.entry_price,
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                related_position_id=closed_position.position_id,
            )
        ]
        if next_state.pause.paused:
            logs.append(
                build_execution_log_entry(
                    occurred_at=closed_at,
                    action="trading_paused",
                    status="blocked",
                    signal=None,
                    reason_codes=(next_state.pause.reason,),
                    message=next_state.pause.message or "Trading paused after paper close.",
                    signal_id=closed_position.signal_id,
                    symbol=closed_position.symbol,
                    source_refs=closed_position.source_refs,
                    quantity=closed_position.quantity,
                    entry_price=closed_position.entry_price,
                    exit_price=exit_price,
                    realized_pnl=realized_pnl,
                    related_position_id=closed_position.position_id,
                )
            )

        return PositionCloseResult(
            status="closed",
            closed_position=closed_position,
            realized_pnl=realized_pnl,
            resulting_positions=remaining_positions,
            session_state=next_state,
            logs=tuple(logs),
        )


def _risk_decision_matches_request(
    risk_decision: RiskDecision,
    *,
    request: ExecutionRequest,
    session_state: SessionRiskState,
) -> bool:
    return (
        risk_decision.approved_signal_id == request.signal.signal_id
        and risk_decision.approved_symbol == request.signal.symbol
        and risk_decision.approved_market == request.signal.market
        and risk_decision.approved_timeframe == request.signal.timeframe
        and risk_decision.approved_direction == request.signal.direction
        and risk_decision.approved_session_key == request.session_key
        and request.session_key == session_state.session_key
        and risk_decision.approved_entry_price == request.entry_price
        and risk_decision.approved_stop_price == request.stop_price
        and risk_decision.approved_quantity == request.proposed_quantity
        and risk_decision.resulting_state == session_state
    )
