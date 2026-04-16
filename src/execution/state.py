from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from typing import Sequence

from .contracts import FillEvent, PaperPosition


def detect_duplicate_signal(signal_id: str, seen_signal_ids: Sequence[str] | frozenset[str]) -> bool:
    return signal_id in seen_signal_ids


def apply_fill(
    positions: Sequence[PaperPosition],
    *,
    fill_event: FillEvent,
    market: str,
    timeframe: str,
    stop_price: Decimal,
    target_price: Decimal,
    source_refs: tuple[str, ...],
) -> tuple[PaperPosition, ...]:
    next_positions = list(positions)
    next_positions.append(
        PaperPosition(
            position_id=fill_event.position_id,
            signal_id=fill_event.signal_id,
            symbol=fill_event.symbol,
            market=market,
            timeframe=timeframe,
            direction=fill_event.direction,
            quantity=fill_event.quantity,
            entry_price=fill_event.fill_price,
            stop_price=stop_price,
            target_price=target_price,
            opened_at=fill_event.filled_at,
            source_refs=source_refs,
        )
    )
    return tuple(next_positions)


def close_position(
    positions: Sequence[PaperPosition],
    *,
    position_id: str,
    exit_price: Decimal,
) -> tuple[tuple[PaperPosition, ...], PaperPosition | None, Decimal]:
    remaining: list[PaperPosition] = []
    closed_position: PaperPosition | None = None

    for position in positions:
        if position.position_id == position_id and closed_position is None:
            closed_position = position
            continue
        remaining.append(position)

    if closed_position is None:
        return tuple(positions), None, Decimal("0")

    if closed_position.direction == "long":
        realized_pnl = (exit_price - closed_position.entry_price) * closed_position.quantity
    else:
        realized_pnl = (closed_position.entry_price - exit_price) * closed_position.quantity
    return tuple(remaining), closed_position, realized_pnl


def build_fill_id(signal_id: str, quantity: Decimal, entry_price: Decimal) -> str:
    payload = f"{signal_id}|{quantity}|{entry_price}"
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_position_id(fill_id: str) -> str:
    return sha256(f"position|{fill_id}".encode("utf-8")).hexdigest()[:16]
