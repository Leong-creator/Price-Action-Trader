from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

RiskOutcome = Literal["allow", "block", "halted", "config_error"]
PauseReason = Literal[
    "none",
    "daily_loss_limit",
    "consecutive_losses_limit",
    "manual_pause",
]
EventSeverity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class RiskConfig:
    max_risk_per_order: Decimal = Decimal("100")
    max_total_exposure: Decimal = Decimal("1000")
    max_symbol_exposure_ratio: Decimal = Decimal("0.50")
    max_daily_loss: Decimal = Decimal("200")
    max_consecutive_losses: int = 2
    allow_manual_resume_from_loss_streak: bool = True


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    symbol: str
    quantity: Decimal
    market_value: Decimal


@dataclass(frozen=True, slots=True)
class TradingPauseState:
    paused: bool = False
    reason: PauseReason = "none"
    message: str = ""


@dataclass(frozen=True, slots=True)
class SessionRiskState:
    session_key: str
    realized_pnl: Decimal = Decimal("0")
    consecutive_losses: int = 0
    pause: TradingPauseState = field(default_factory=TradingPauseState)


@dataclass(frozen=True, slots=True)
class RiskEvent:
    code: str
    severity: EventSeverity
    message: str


@dataclass(frozen=True, slots=True)
class RiskDecision:
    outcome: RiskOutcome
    approved_quantity: Decimal
    risk_amount: Decimal
    projected_total_exposure: Decimal
    projected_symbol_exposure_ratio: Decimal
    approved_signal_id: str | None
    approved_symbol: str | None
    approved_market: str | None
    approved_timeframe: str | None
    approved_direction: str | None
    approved_session_key: str | None
    approved_entry_price: Decimal | None
    approved_stop_price: Decimal | None
    reason_codes: tuple[str, ...]
    events: tuple[RiskEvent, ...]
    resulting_state: SessionRiskState
