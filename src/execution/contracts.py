from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from src.risk import RiskDecision, SessionRiskState
from src.strategy.contracts import Signal

ExecutionStatus = Literal["filled", "blocked", "closed", "error"]


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    signal: Signal
    requested_at: datetime
    session_key: str
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    proposed_quantity: Decimal


@dataclass(frozen=True, slots=True)
class SuggestedOrder:
    signal_id: str
    symbol: str
    market: str
    timeframe: str
    direction: str
    order_type: str
    quantity: Decimal
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    risk_amount: Decimal


@dataclass(frozen=True, slots=True)
class FillEvent:
    fill_id: str
    signal_id: str
    position_id: str
    symbol: str
    direction: str
    quantity: Decimal
    fill_price: Decimal
    filled_at: datetime
    simulated: bool


@dataclass(frozen=True, slots=True)
class PaperPosition:
    position_id: str
    signal_id: str
    symbol: str
    market: str
    timeframe: str
    direction: str
    quantity: Decimal
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    opened_at: datetime
    source_refs: tuple[str, ...]

    @property
    def market_value(self) -> Decimal:
        return self.entry_price * self.quantity


@dataclass(frozen=True, slots=True)
class ExecutionLogEntry:
    occurred_at: datetime
    action: str
    status: ExecutionStatus
    signal_id: str | None
    symbol: str | None
    reason_codes: tuple[str, ...]
    message: str
    source_refs: tuple[str, ...]
    quantity: Decimal | None = None
    entry_price: Decimal | None = None
    exit_price: Decimal | None = None
    realized_pnl: Decimal | None = None
    related_position_id: str | None = None
    related_fill_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: ExecutionStatus
    request: ExecutionRequest
    risk_decision: RiskDecision
    suggested_order: SuggestedOrder | None
    fill_event: FillEvent | None
    resulting_positions: tuple[PaperPosition, ...]
    resulting_seen_signal_ids: frozenset[str]
    session_state: SessionRiskState
    logs: tuple[ExecutionLogEntry, ...]


@dataclass(frozen=True, slots=True)
class PositionCloseResult:
    status: ExecutionStatus
    closed_position: PaperPosition | None
    realized_pnl: Decimal
    resulting_positions: tuple[PaperPosition, ...]
    session_state: SessionRiskState
    logs: tuple[ExecutionLogEntry, ...]
