from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PAContextSnapshot:
    symbol: str
    market: str
    timeframe: str
    market_cycle: str
    higher_timeframe_context: str
    regime_summary: str
    bar_by_bar_bias: str
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SetupCandidate:
    setup_type: str
    direction: str
    pa_context: str
    trigger_bar_index: int
    entry_trigger: str
    stop_rule: str
    target_rule: str
    invalidation: str
    confidence: str
    source_refs: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class Signal:
    signal_id: str
    symbol: str
    market: str
    timeframe: str
    direction: str
    setup_type: str
    pa_context: str
    entry_trigger: str
    stop_rule: str
    target_rule: str
    invalidation: str
    confidence: str
    source_refs: tuple[str, ...]
    explanation: str
    risk_notes: tuple[str, ...]
