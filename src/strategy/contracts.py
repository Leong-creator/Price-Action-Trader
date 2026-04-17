from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
class KnowledgeAtomHit:
    atom_id: str
    atom_type: str
    source_ref: str
    raw_locator: dict[str, Any]
    match_reason: str
    applicability_state: str
    conflict_refs: tuple[str, ...] = ()
    reference_tier: str = "actual_hit"
    governance_notes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    evidence_locator_summary: tuple[str, ...] = ()
    field_mappings: tuple[str, ...] = ()
    claim_id: str | None = None
    promotion_theme: str | None = None


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
    actual_source_refs: tuple[str, ...] = field(default_factory=tuple)
    bundle_support_refs: tuple[str, ...] = field(default_factory=tuple)
    knowledge_trace: tuple[KnowledgeAtomHit, ...] = field(default_factory=tuple)
    knowledge_debug_trace: tuple[KnowledgeAtomHit, ...] = field(default_factory=tuple)
