from __future__ import annotations

from datetime import datetime, timedelta

from src.data.schema import NewsEvent
from src.strategy.contracts import Signal

from .contracts import NewsFilterDecision, NewsMatch, NewsReviewNote

BLOCKING_EVENT_TYPES = frozenset(
    {
        "earnings",
        "guidance",
        "trading_halt",
        "sec",
        "fomc",
        "fed",
        "cpi",
        "geopolitical",
    }
)
SEVERITY_RANK = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


def evaluate_news_context(
    signal: Signal,
    events: tuple[NewsEvent, ...] | list[NewsEvent],
    *,
    reference_timestamp: datetime | None = None,
    lookback_window: timedelta = timedelta(hours=24),
) -> NewsFilterDecision:
    if reference_timestamp is None:
        raise ValueError("reference_timestamp is required for news evaluation")

    relevant = [
        event
        for event in events
        if (
            event.symbol == signal.symbol
            and event.market == signal.market
            and event.timestamp <= reference_timestamp
            and reference_timestamp - event.timestamp <= lookback_window
        )
    ]

    relevant.sort(
        key=lambda event: (
            event.timestamp,
            -SEVERITY_RANK.get(event.severity, -1),
            event.source,
            event.event_type,
            event.headline,
        )
    )

    matches = tuple(_to_match(event) for event in relevant)
    source_refs = tuple(match.source_ref for match in matches)

    if not matches:
        return NewsFilterDecision(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            market=signal.market,
            outcome="allow",
            reason_codes=("no_relevant_news",),
            matched_events=(),
            headline_summary=(),
            source_refs=(),
            risk_notes=("No matching news events within the configured lookback window.",),
            review_notes=(
                NewsReviewNote(
                    kind="explanation",
                    message="No relevant news context was attached to this signal.",
                    source_refs=(),
                ),
            ),
        )

    has_blocking_event = any(
        match.severity == "critical"
        or (match.severity == "high" and match.event_type in BLOCKING_EVENT_TYPES)
        for match in matches
    )
    has_caution_event = any(match.severity in {"medium", "high"} for match in matches)

    if has_blocking_event:
        outcome = "block"
        reason_codes = ("high_risk_news_event",)
        review_kind = "filter"
        risk_prefix = "High-risk news filter"
    elif has_caution_event:
        outcome = "caution"
        reason_codes = ("news_risk_warning",)
        review_kind = "risk_hint"
        risk_prefix = "News caution"
    else:
        outcome = "allow"
        reason_codes = ("informational_news_only",)
        review_kind = "explanation"
        risk_prefix = "Informational news context"

    headline_summary = tuple(
        f"{match.severity}:{match.event_type}:{match.headline}" for match in matches
    )
    risk_notes = tuple(
        f"{risk_prefix}: {match.headline} ({match.source}, {match.severity})"
        for match in matches
    )
    review_notes = tuple(
        NewsReviewNote(
            kind=review_kind,
            message=f"{match.event_type} from {match.source}: {match.headline}",
            source_refs=(match.source_ref,),
        )
        for match in matches
    )

    return NewsFilterDecision(
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        market=signal.market,
        outcome=outcome,
        reason_codes=reason_codes,
        matched_events=matches,
        headline_summary=headline_summary,
        source_refs=source_refs,
        risk_notes=risk_notes,
        review_notes=review_notes,
    )


def _to_match(event: NewsEvent) -> NewsMatch:
    return NewsMatch(
        symbol=event.symbol,
        market=event.market,
        timestamp=event.timestamp,
        source=event.source,
        event_type=event.event_type,
        severity=event.severity,
        headline=event.headline,
        notes=event.notes,
        source_ref=f"news:{event.source}:{event.event_type}:{event.timestamp.isoformat()}",
    )
