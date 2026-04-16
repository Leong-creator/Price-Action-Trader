from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.strategy.contracts import Signal

from .contracts import ExecutionLogEntry


def build_execution_log_entry(
    *,
    occurred_at: datetime,
    action: str,
    status: str,
    signal: Signal | None,
    reason_codes: tuple[str, ...],
    message: str,
    signal_id: str | None = None,
    symbol: str | None = None,
    source_refs: tuple[str, ...] | None = None,
    quantity: Decimal | None = None,
    entry_price: Decimal | None = None,
    exit_price: Decimal | None = None,
    realized_pnl: Decimal | None = None,
    related_position_id: str | None = None,
    related_fill_id: str | None = None,
) -> ExecutionLogEntry:
    return ExecutionLogEntry(
        occurred_at=occurred_at,
        action=action,
        status=status,
        signal_id=signal.signal_id if signal is not None else signal_id,
        symbol=signal.symbol if signal is not None else symbol,
        reason_codes=reason_codes,
        message=message,
        source_refs=signal.source_refs if signal is not None else (source_refs or ()),
        quantity=quantity,
        entry_price=entry_price,
        exit_price=exit_price,
        realized_pnl=realized_pnl,
        related_position_id=related_position_id,
        related_fill_id=related_fill_id,
    )
