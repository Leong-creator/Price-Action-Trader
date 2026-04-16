from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Sequence

from src.strategy.contracts import Signal

from .contracts import (
    PositionSnapshot,
    RiskConfig,
    RiskDecision,
    RiskEvent,
    SessionRiskState,
    TradingPauseState,
)

ZERO = Decimal("0")
ONE = Decimal("1")


def evaluate_order_request(
    signal: Signal,
    *,
    entry_price: Decimal | int | float | str,
    stop_price: Decimal | int | float | str,
    proposed_quantity: Decimal | int | float | str,
    positions: Sequence[PositionSnapshot],
    session_state: SessionRiskState,
    config: RiskConfig,
    market_is_open: bool,
) -> RiskDecision:
    config_errors = _validate_config(config)
    if config_errors:
        return _decision(
            "config_error",
            session_state,
            approved_signal_id=signal.signal_id,
            approved_symbol=signal.symbol,
            approved_market=signal.market,
            approved_timeframe=signal.timeframe,
            approved_direction=signal.direction,
            approved_session_key=session_state.session_key,
            reason_codes=tuple(config_errors),
            events=tuple(
                RiskEvent(code=code, severity="error", message=_message_for_code(code))
                for code in config_errors
            ),
        )

    resumed_state = maybe_resume_trading(
        session_state,
        config=config,
        next_session_key=session_state.session_key,
        manual_resume=False,
    )

    if resumed_state.pause.paused:
        return _decision(
            "halted",
            resumed_state,
            approved_signal_id=signal.signal_id,
            approved_symbol=signal.symbol,
            approved_market=signal.market,
            approved_timeframe=signal.timeframe,
            approved_direction=signal.direction,
            approved_session_key=session_state.session_key,
            reason_codes=(resumed_state.pause.reason,),
            events=(
                RiskEvent(
                    code=resumed_state.pause.reason,
                    severity="warning",
                    message=resumed_state.pause.message or "Trading remains paused.",
                ),
            ),
        )

    if not market_is_open:
        return _decision(
            "block",
            resumed_state,
            approved_signal_id=signal.signal_id,
            approved_symbol=signal.symbol,
            approved_market=signal.market,
            approved_timeframe=signal.timeframe,
            approved_direction=signal.direction,
            approved_session_key=session_state.session_key,
            reason_codes=("market_closed",),
            events=(
                RiskEvent(
                    code="market_closed",
                    severity="warning",
                    message="Paper order blocked because the market is closed.",
                ),
            ),
        )

    parsed_values = _parse_request_values(entry_price, stop_price, proposed_quantity)
    if parsed_values is None:
        return _decision(
            "block",
            resumed_state,
            approved_signal_id=signal.signal_id,
            approved_symbol=signal.symbol,
            approved_market=signal.market,
            approved_timeframe=signal.timeframe,
            approved_direction=signal.direction,
            approved_session_key=session_state.session_key,
            reason_codes=("invalid_request",),
            events=(
                RiskEvent(
                    code="invalid_request",
                    severity="error",
                    message="Request values must be positive decimals.",
                ),
            ),
        )

    entry_decimal, stop_decimal, quantity_decimal = parsed_values
    direction_error = _validate_stop_direction(
        signal.direction,
        entry_price=entry_decimal,
        stop_price=stop_decimal,
    )
    if direction_error is not None:
        return _decision(
            "block",
            resumed_state,
            approved_signal_id=signal.signal_id,
            approved_symbol=signal.symbol,
            approved_market=signal.market,
            approved_timeframe=signal.timeframe,
            approved_direction=signal.direction,
            approved_session_key=session_state.session_key,
            approved_entry_price=entry_decimal,
            approved_stop_price=stop_decimal,
            reason_codes=(direction_error.code,),
            events=(direction_error,),
        )

    risk_amount = abs(entry_decimal - stop_decimal) * quantity_decimal
    if risk_amount > config.max_risk_per_order:
        return _decision(
            "block",
            resumed_state,
            risk_amount=risk_amount,
            approved_signal_id=signal.signal_id,
            approved_symbol=signal.symbol,
            approved_market=signal.market,
            approved_timeframe=signal.timeframe,
            approved_direction=signal.direction,
            approved_session_key=session_state.session_key,
            approved_entry_price=entry_decimal,
            approved_stop_price=stop_decimal,
            reason_codes=("max_risk_per_order_exceeded",),
            events=(
                RiskEvent(
                    code="max_risk_per_order_exceeded",
                    severity="warning",
                    message="Projected per-order risk exceeds the configured limit.",
                ),
            ),
        )

    current_total_exposure = sum(abs(position.market_value) for position in positions)
    requested_exposure = abs(entry_decimal * quantity_decimal)
    projected_total_exposure = current_total_exposure + requested_exposure
    if projected_total_exposure > config.max_total_exposure:
        return _decision(
            "block",
            resumed_state,
            risk_amount=risk_amount,
            projected_total_exposure=projected_total_exposure,
            approved_signal_id=signal.signal_id,
            approved_symbol=signal.symbol,
            approved_market=signal.market,
            approved_timeframe=signal.timeframe,
            approved_direction=signal.direction,
            approved_session_key=session_state.session_key,
            approved_entry_price=entry_decimal,
            approved_stop_price=stop_decimal,
            reason_codes=("max_total_exposure_exceeded",),
            events=(
                RiskEvent(
                    code="max_total_exposure_exceeded",
                    severity="warning",
                    message="Projected total exposure exceeds the configured limit.",
                ),
            ),
        )

    current_symbol_exposure = sum(
        abs(position.market_value)
        for position in positions
        if position.symbol == signal.symbol
    )
    projected_symbol_exposure = current_symbol_exposure + requested_exposure
    projected_symbol_exposure_ratio = (
        projected_symbol_exposure / projected_total_exposure
        if projected_total_exposure > ZERO
        else ZERO
    )
    if projected_symbol_exposure_ratio > config.max_symbol_exposure_ratio:
        return _decision(
            "block",
            resumed_state,
            risk_amount=risk_amount,
            projected_total_exposure=projected_total_exposure,
            projected_symbol_exposure_ratio=projected_symbol_exposure_ratio,
            approved_signal_id=signal.signal_id,
            approved_symbol=signal.symbol,
            approved_market=signal.market,
            approved_timeframe=signal.timeframe,
            approved_direction=signal.direction,
            approved_session_key=session_state.session_key,
            approved_entry_price=entry_decimal,
            approved_stop_price=stop_decimal,
            reason_codes=("symbol_concentration_exceeded",),
            events=(
                RiskEvent(
                    code="symbol_concentration_exceeded",
                    severity="warning",
                    message="Projected symbol concentration exceeds the configured limit.",
                ),
            ),
        )

    if resumed_state.realized_pnl <= -config.max_daily_loss:
        halted_state = _pause_state(
            resumed_state,
            reason="daily_loss_limit",
            message="Trading paused after reaching the daily loss limit.",
        )
        return _decision(
            "halted",
            halted_state,
            risk_amount=risk_amount,
            projected_total_exposure=projected_total_exposure,
            projected_symbol_exposure_ratio=projected_symbol_exposure_ratio,
            approved_signal_id=signal.signal_id,
            approved_symbol=signal.symbol,
            approved_market=signal.market,
            approved_timeframe=signal.timeframe,
            approved_direction=signal.direction,
            approved_session_key=session_state.session_key,
            approved_entry_price=entry_decimal,
            approved_stop_price=stop_decimal,
            reason_codes=("daily_loss_limit",),
            events=(
                RiskEvent(
                    code="daily_loss_limit",
                    severity="warning",
                    message="Trading paused after reaching the daily loss limit.",
                ),
            ),
        )

    if resumed_state.consecutive_losses >= config.max_consecutive_losses:
        halted_state = _pause_state(
            resumed_state,
            reason="consecutive_losses_limit",
            message="Trading paused after exceeding the consecutive loss limit.",
        )
        return _decision(
            "halted",
            halted_state,
            risk_amount=risk_amount,
            projected_total_exposure=projected_total_exposure,
            projected_symbol_exposure_ratio=projected_symbol_exposure_ratio,
            approved_signal_id=signal.signal_id,
            approved_symbol=signal.symbol,
            approved_session_key=session_state.session_key,
            approved_entry_price=entry_decimal,
            approved_stop_price=stop_decimal,
            reason_codes=("consecutive_losses_limit",),
            events=(
                RiskEvent(
                    code="consecutive_losses_limit",
                    severity="warning",
                    message="Trading paused after exceeding the consecutive loss limit.",
                ),
            ),
        )

    return _decision(
        "allow",
        resumed_state,
        approved_quantity=quantity_decimal,
        risk_amount=risk_amount,
        projected_total_exposure=projected_total_exposure,
        projected_symbol_exposure_ratio=projected_symbol_exposure_ratio,
        approved_signal_id=signal.signal_id,
        approved_symbol=signal.symbol,
        approved_market=signal.market,
        approved_timeframe=signal.timeframe,
        approved_direction=signal.direction,
        approved_session_key=session_state.session_key,
        approved_entry_price=entry_decimal,
        approved_stop_price=stop_decimal,
        reason_codes=("allow",),
        events=(
            RiskEvent(
                code="allow",
                severity="info",
                message="Paper order passed the configured risk checks.",
            ),
        ),
    )


def record_closed_trade(
    session_state: SessionRiskState,
    *,
    pnl_amount: Decimal | int | float | str,
    config: RiskConfig,
    session_key: str | None = None,
) -> SessionRiskState:
    next_state = session_state
    if session_key is not None:
        next_state = maybe_reset_session(next_state, next_session_key=session_key)

    pnl_decimal = _parse_decimal(pnl_amount)
    if pnl_decimal is None:
        return _pause_state(
            next_state,
            reason="manual_pause",
            message="Trading paused because closed-trade PnL was invalid.",
        )

    realized_pnl = next_state.realized_pnl + pnl_decimal
    consecutive_losses = next_state.consecutive_losses + 1 if pnl_decimal < ZERO else 0
    updated_state = SessionRiskState(
        session_key=next_state.session_key,
        realized_pnl=realized_pnl,
        consecutive_losses=consecutive_losses,
        pause=next_state.pause,
    )

    if realized_pnl <= -config.max_daily_loss:
        return _pause_state(
            updated_state,
            reason="daily_loss_limit",
            message="Trading paused after reaching the daily loss limit.",
        )

    if consecutive_losses >= config.max_consecutive_losses:
        return _pause_state(
            updated_state,
            reason="consecutive_losses_limit",
            message="Trading paused after exceeding the consecutive loss limit.",
        )

    return updated_state


def maybe_reset_session(
    session_state: SessionRiskState,
    *,
    next_session_key: str,
) -> SessionRiskState:
    if not next_session_key or next_session_key == session_state.session_key:
        return session_state
    return SessionRiskState(session_key=next_session_key)


def maybe_resume_trading(
    session_state: SessionRiskState,
    *,
    config: RiskConfig,
    next_session_key: str | None = None,
    manual_resume: bool = False,
) -> SessionRiskState:
    if next_session_key and next_session_key != session_state.session_key:
        return maybe_reset_session(session_state, next_session_key=next_session_key)

    if not session_state.pause.paused:
        return session_state

    if (
        manual_resume
        and session_state.pause.reason == "consecutive_losses_limit"
        and config.allow_manual_resume_from_loss_streak
    ):
        return SessionRiskState(
            session_key=session_state.session_key,
            realized_pnl=session_state.realized_pnl,
            consecutive_losses=0,
        )

    return session_state


def _validate_config(config: RiskConfig) -> list[str]:
    errors: list[str] = []
    if config.max_risk_per_order <= ZERO:
        errors.append("invalid_max_risk_per_order")
    if config.max_total_exposure <= ZERO:
        errors.append("invalid_max_total_exposure")
    if config.max_symbol_exposure_ratio <= ZERO or config.max_symbol_exposure_ratio > ONE:
        errors.append("invalid_max_symbol_exposure_ratio")
    if config.max_daily_loss <= ZERO:
        errors.append("invalid_max_daily_loss")
    if config.max_consecutive_losses <= 0:
        errors.append("invalid_max_consecutive_losses")
    return errors


def _parse_request_values(
    entry_price: Decimal | int | float | str,
    stop_price: Decimal | int | float | str,
    proposed_quantity: Decimal | int | float | str,
) -> tuple[Decimal, Decimal, Decimal] | None:
    entry_decimal = _parse_decimal(entry_price)
    stop_decimal = _parse_decimal(stop_price)
    quantity_decimal = _parse_decimal(proposed_quantity)
    if (
        entry_decimal is None
        or stop_decimal is None
        or quantity_decimal is None
        or entry_decimal <= ZERO
        or stop_decimal <= ZERO
        or quantity_decimal <= ZERO
    ):
        return None
    return entry_decimal, stop_decimal, quantity_decimal


def _parse_decimal(value: Decimal | int | float | str) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _validate_stop_direction(
    direction: str,
    *,
    entry_price: Decimal,
    stop_price: Decimal,
) -> RiskEvent | None:
    normalized_direction = direction.lower()
    if normalized_direction == "long" and stop_price >= entry_price:
        return RiskEvent(
            code="invalid_stop_for_long",
            severity="error",
            message="Long paper orders require a stop below the entry price.",
        )
    if normalized_direction == "short" and stop_price <= entry_price:
        return RiskEvent(
            code="invalid_stop_for_short",
            severity="error",
            message="Short paper orders require a stop above the entry price.",
        )
    if normalized_direction not in {"long", "short"}:
        return RiskEvent(
            code="invalid_direction",
            severity="error",
            message="Signal direction must be long or short.",
        )
    return None


def _pause_state(
    session_state: SessionRiskState,
    *,
    reason: str,
    message: str,
) -> SessionRiskState:
    return SessionRiskState(
        session_key=session_state.session_key,
        realized_pnl=session_state.realized_pnl,
        consecutive_losses=session_state.consecutive_losses,
        pause=TradingPauseState(paused=True, reason=reason, message=message),
    )


def _decision(
    outcome: str,
    resulting_state: SessionRiskState,
    *,
    approved_quantity: Decimal = ZERO,
    risk_amount: Decimal = ZERO,
    projected_total_exposure: Decimal = ZERO,
    projected_symbol_exposure_ratio: Decimal = ZERO,
    approved_signal_id: str | None = None,
    approved_symbol: str | None = None,
    approved_market: str | None = None,
    approved_timeframe: str | None = None,
    approved_direction: str | None = None,
    approved_session_key: str | None = None,
    approved_entry_price: Decimal | None = None,
    approved_stop_price: Decimal | None = None,
    reason_codes: tuple[str, ...] = (),
    events: tuple[RiskEvent, ...] = (),
) -> RiskDecision:
    return RiskDecision(
        outcome=outcome,
        approved_quantity=approved_quantity,
        risk_amount=risk_amount,
        projected_total_exposure=projected_total_exposure,
        projected_symbol_exposure_ratio=projected_symbol_exposure_ratio,
        approved_signal_id=approved_signal_id,
        approved_symbol=approved_symbol,
        approved_market=approved_market,
        approved_timeframe=approved_timeframe,
        approved_direction=approved_direction,
        approved_session_key=approved_session_key,
        approved_entry_price=approved_entry_price,
        approved_stop_price=approved_stop_price,
        reason_codes=reason_codes,
        events=events,
        resulting_state=resulting_state,
    )


def _message_for_code(code: str) -> str:
    messages = {
        "invalid_max_risk_per_order": "max_risk_per_order must be positive.",
        "invalid_max_total_exposure": "max_total_exposure must be positive.",
        "invalid_max_symbol_exposure_ratio": "max_symbol_exposure_ratio must be within (0, 1].",
        "invalid_max_daily_loss": "max_daily_loss must be positive.",
        "invalid_max_consecutive_losses": "max_consecutive_losses must be positive.",
    }
    return messages.get(code, "Risk configuration is invalid.")
