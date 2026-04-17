from __future__ import annotations

from collections.abc import Iterable, Sequence
from hashlib import sha256

from src.data.replay import DeterministicReplay, ReplayStep
from src.data.schema import NewsEvent, OhlcvRow

from .context import build_context_snapshot
from .contracts import PAContextSnapshot, SetupCandidate, Signal
from .knowledge import StrategyKnowledgeBundle, load_default_knowledge
from .knowledge_access import (
    CallableKnowledgeAccess,
    aggregate_legacy_source_refs,
    load_default_knowledge_access,
    render_trace_summary,
)


SETUP_TYPE = "signal_bar_entry_placeholder"


def generate_signals(
    replay: DeterministicReplay | Iterable[ReplayStep],
    *,
    knowledge: StrategyKnowledgeBundle | None = None,
    knowledge_access: CallableKnowledgeAccess | None = None,
) -> tuple[Signal, ...]:
    active_knowledge = knowledge or load_default_knowledge()
    active_knowledge_access = knowledge_access or load_default_knowledge_access()
    active_knowledge.validate()

    steps = replay.snapshot() if isinstance(replay, DeterministicReplay) else tuple(replay)
    signals: list[Signal] = []
    history: list[OhlcvRow] = []
    active_direction: str | None = None

    for step in steps:
        history.append(step.bar)
        context = build_context_snapshot(history, active_knowledge)
        candidate = identify_setup_candidate(
            history,
            step,
            context=context,
            knowledge=active_knowledge,
            previous_direction=active_direction,
        )
        if candidate is None:
            if _context_resets_direction(context, active_direction):
                active_direction = None
            continue
        signal = _build_signal(
            step,
            context,
            candidate,
            active_knowledge,
            active_knowledge_access,
        )
        signals.append(_attach_news_risk(signal, step.news_events))
        active_direction = candidate.direction

    return tuple(signals)


def identify_setup_candidate(
    bars: Sequence[OhlcvRow],
    step: ReplayStep,
    *,
    context: PAContextSnapshot,
    knowledge: StrategyKnowledgeBundle,
    previous_direction: str | None,
) -> SetupCandidate | None:
    if len(bars) < 3 or context.market_cycle != "trend":
        return None

    setup_page = knowledge.setup_page
    bar = step.bar
    previous_bar = bars[-2]
    body_size = abs(bar.close - bar.open)
    bar_range = bar.high - bar.low
    if bar_range <= 0 or body_size <= 0:
        return None

    direction: str | None = None
    if (
        context.bar_by_bar_bias == "bullish"
        and bar.close > bar.open
        and bar.close > previous_bar.close
        and body_size >= bar_range * bar.close.__class__("0.4")
    ):
        direction = "long"
    elif (
        context.bar_by_bar_bias == "bearish"
        and bar.close < bar.open
        and bar.close < previous_bar.close
        and body_size >= bar_range * bar.close.__class__("0.4")
    ):
        direction = "short"

    if direction is None or previous_direction == direction:
        return None
    if _is_invalidated(direction, bar, previous_bar):
        return None

    return SetupCandidate(
        setup_type=SETUP_TYPE,
        direction=direction,
        pa_context=context.market_cycle,
        trigger_bar_index=step.index,
        entry_trigger=_resolve_entry_trigger(direction, setup_page),
        stop_rule=_resolve_stop_rule(direction, setup_page),
        target_rule=_resolve_target_rule(direction, setup_page),
        invalidation=_resolve_invalidation(direction, setup_page),
        confidence="low",
        source_refs=knowledge.source_refs,
        explanation=(
            f"research-only placeholder setup triggered after {context.regime_summary}; "
            f"bar {step.index} closed {'above' if direction == 'long' else 'below'} the prior close "
            f"with a directional body in a {context.market_cycle} context"
        ),
    )


def _build_signal(
    step: ReplayStep,
    context: PAContextSnapshot,
    candidate: SetupCandidate,
    knowledge: StrategyKnowledgeBundle,
    knowledge_access: CallableKnowledgeAccess,
) -> Signal:
    setup_page = knowledge.setup_page
    risk_notes = [
        "research-only placeholder setup; not validated for live trading",
    ]
    if setup_page.is_placeholder or knowledge.concept_page.is_placeholder:
        risk_notes.append("knowledge page is draft/placeholder, so confidence is intentionally low")
    knowledge_trace = knowledge_access.resolve_trace(
        knowledge=knowledge,
        market=step.bar.market,
        timeframe=step.bar.timeframe,
        pa_context=context.market_cycle,
    )
    legacy_source_refs = aggregate_legacy_source_refs(candidate.source_refs, knowledge_trace)
    trace_summary = render_trace_summary(knowledge_trace)

    return Signal(
        signal_id=_build_signal_id(step.bar, candidate.direction),
        symbol=step.bar.symbol,
        market=step.bar.market,
        timeframe=step.bar.timeframe,
        direction=candidate.direction,
        setup_type=candidate.setup_type,
        pa_context=context.market_cycle,
        entry_trigger=candidate.entry_trigger,
        stop_rule=candidate.stop_rule,
        target_rule=candidate.target_rule,
        invalidation=candidate.invalidation,
        confidence=candidate.confidence,
        source_refs=legacy_source_refs,
        explanation=(
            f"{candidate.explanation}; knowledge refs: {', '.join(legacy_source_refs)}; "
            f"knowledge trace: {trace_summary}"
        ),
        risk_notes=tuple(risk_notes),
        knowledge_trace=knowledge_trace,
    )


def _attach_news_risk(signal: Signal, news_events: Sequence[NewsEvent]) -> Signal:
    if not news_events:
        return signal
    news_summary = "; ".join(
        f"{event.severity}:{event.event_type}:{event.headline}" for event in news_events
    )
    return Signal(
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        market=signal.market,
        timeframe=signal.timeframe,
        direction=signal.direction,
        setup_type=signal.setup_type,
        pa_context=signal.pa_context,
        entry_trigger=signal.entry_trigger,
        stop_rule=signal.stop_rule,
        target_rule=signal.target_rule,
        invalidation=signal.invalidation,
        confidence=signal.confidence,
        source_refs=signal.source_refs,
        explanation=signal.explanation,
        risk_notes=signal.risk_notes + (f"news context only: {news_summary}",),
        knowledge_trace=signal.knowledge_trace,
    )


def _resolve_entry_trigger(direction: str, knowledge_page: object) -> str:
    return (
        f"placeholder confirmation for {direction} entry; "
        f"{_first_text(getattr(knowledge_page, 'entry_trigger', ()), 'entry trigger pending source extraction')}"
    )


def _resolve_stop_rule(direction: str, knowledge_page: object) -> str:
    return (
        f"protective stop for {direction}; "
        f"{_first_text(getattr(knowledge_page, 'stop_rule', ()), 'stop rule pending source extraction')}"
    )


def _resolve_target_rule(direction: str, knowledge_page: object) -> str:
    return (
        f"initial target for {direction}; "
        f"{_first_text(getattr(knowledge_page, 'target_rule', ()), 'target rule pending source extraction')}"
    )


def _resolve_invalidation(direction: str, knowledge_page: object) -> str:
    boundary = "prior high" if direction == "long" else "prior low"
    return (
        f"cancel {direction} placeholder setup unless the signal bar closes beyond the {boundary}; "
        f"{_first_text(getattr(knowledge_page, 'invalidation', ()), 'invalidation pending source extraction')}"
    )


def _is_invalidated(direction: str, bar: OhlcvRow, previous_bar: OhlcvRow) -> bool:
    if direction == "long":
        return bar.close <= previous_bar.high
    return bar.close >= previous_bar.low


def _context_resets_direction(
    context: PAContextSnapshot, active_direction: str | None
) -> bool:
    if active_direction is None:
        return False
    if context.market_cycle != "trend" or context.bar_by_bar_bias == "neutral":
        return True
    if active_direction == "long" and context.bar_by_bar_bias == "bearish":
        return True
    if active_direction == "short" and context.bar_by_bar_bias == "bullish":
        return True
    return False


def _first_text(values: Sequence[str], fallback: str) -> str:
    return values[0] if values else fallback


def _build_signal_id(bar: OhlcvRow, direction: str) -> str:
    payload = "|".join(
        [
            SETUP_TYPE,
            direction,
            bar.symbol,
            bar.market,
            bar.timeframe,
            bar.timestamp.isoformat(),
        ]
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:16]
