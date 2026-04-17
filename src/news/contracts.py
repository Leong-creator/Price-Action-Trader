from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

NewsOutcome = Literal["allow", "caution", "block"]
NewsNoteKind = Literal["filter", "explanation", "risk_hint"]


@dataclass(frozen=True, slots=True)
class NewsMatch:
    symbol: str
    market: str
    timestamp: datetime
    source: str
    event_type: str
    severity: str
    headline: str
    notes: str
    source_ref: str


@dataclass(frozen=True, slots=True)
class NewsReviewNote:
    kind: NewsNoteKind
    message: str
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NewsFilterDecision:
    signal_id: str
    symbol: str
    market: str
    outcome: NewsOutcome
    reason_codes: tuple[str, ...]
    matched_events: tuple[NewsMatch, ...]
    headline_summary: tuple[str, ...]
    source_refs: tuple[str, ...]
    risk_notes: tuple[str, ...]
    review_notes: tuple[NewsReviewNote, ...]
