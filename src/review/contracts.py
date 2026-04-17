from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from src.news.contracts import NewsReviewNote

ReviewOutcomeStatus = Literal["closed_trade", "execution_blocked", "no_trade"]


@dataclass(frozen=True, slots=True)
class ReviewTradeOutcome:
    signal_id: str
    status: ReviewOutcomeStatus
    exit_reason: str | None
    pnl_r: Decimal | None
    error_reason: str | None
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewItem:
    signal_id: str
    symbol: str
    market: str
    timeframe: str
    direction: str
    setup_type: str
    kb_source_refs: tuple[str, ...]
    pa_explanation: str
    risk_notes: tuple[str, ...]
    news_outcome: str
    news_headlines: tuple[str, ...]
    news_source_refs: tuple[str, ...]
    news_notes: tuple[str, ...]
    news_review_notes: tuple[NewsReviewNote, ...]
    entry_trigger: str
    stop_rule: str
    target_rule: str
    trade_outcome: ReviewTradeOutcome
    improvement_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewReport:
    generated_at: datetime
    items: tuple[ReviewItem, ...]
    summary: str
    warnings: tuple[str, ...]
    assumptions: tuple[str, ...]
    source_refs: tuple[str, ...]
