from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from src.data.schema import OhlcvRow

from .contracts import PAContextSnapshot
from .knowledge import StrategyKnowledgeBundle


def build_context_snapshot(
    bars: Sequence[OhlcvRow], knowledge: StrategyKnowledgeBundle
) -> PAContextSnapshot:
    current_bar = bars[-1]
    recent_bars = tuple(bars[-3:])
    market_cycle, bias, regime_summary = _classify_recent_bars(recent_bars)
    higher_timeframe_context = _resolve_higher_timeframe_context(knowledge)
    return PAContextSnapshot(
        symbol=current_bar.symbol,
        market=current_bar.market,
        timeframe=current_bar.timeframe,
        market_cycle=market_cycle,
        higher_timeframe_context=higher_timeframe_context,
        regime_summary=regime_summary,
        bar_by_bar_bias=bias,
        source_refs=knowledge.concept_page.source_refs,
    )


def _classify_recent_bars(bars: Sequence[OhlcvRow]) -> tuple[str, str, str]:
    if len(bars) < 3:
        return (
            "transition",
            "neutral",
            "insufficient history for context classification",
        )

    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]

    if closes[0] < closes[1] < closes[2] and highs[0] <= highs[1] <= highs[2] and lows[0] <= lows[1] <= lows[2]:
        return (
            "trend",
            "bullish",
            "three-bar upward progression with rising highs/lows",
        )
    if closes[0] > closes[1] > closes[2] and highs[0] >= highs[1] >= highs[2] and lows[0] >= lows[1] >= lows[2]:
        return (
            "trend",
            "bearish",
            "three-bar downward progression with falling highs/lows",
        )

    closing_range = max(closes) - min(closes)
    reference_price = closes[-1]
    if reference_price > Decimal("0") and closing_range <= reference_price * Decimal("0.003"):
        return (
            "trading-range",
            "neutral",
            "recent closes are compressed into a narrow range",
        )
    return (
        "transition",
        "neutral",
        "recent bars do not show a stable trend or tight trading range",
    )


def _resolve_higher_timeframe_context(knowledge: StrategyKnowledgeBundle) -> str:
    notes = knowledge.concept_page.higher_timeframe_context or knowledge.setup_page.higher_timeframe_context
    if not notes:
        return "higher timeframe context unavailable"
    return notes[0]
