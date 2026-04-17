from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from src.data.schema import NewsEvent, OhlcvRow
from src.strategy import (
    DEFAULT_CONCEPT_PATH,
    DEFAULT_SETUP_PATH,
    GoldenCase,
    load_golden_case,
    load_strategy_knowledge,
    resolve_reference_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_CASES_DIR = PROJECT_ROOT / "tests" / "golden_cases" / "cases"


def load_case(case_id: str) -> GoldenCase:
    return load_golden_case(GOLDEN_CASES_DIR / f"{case_id}.json")


def build_bundle_from_refs(*refs: str):
    supporting_paths = []
    seen: set[Path] = set()
    for reference in refs:
        if not reference.startswith("wiki:"):
            continue
        path = resolve_reference_path(reference)
        if path is None or path in {DEFAULT_CONCEPT_PATH, DEFAULT_SETUP_PATH} or path in seen:
            continue
        seen.add(path)
        supporting_paths.append(path)
    return load_strategy_knowledge(
        DEFAULT_CONCEPT_PATH,
        DEFAULT_SETUP_PATH,
        supporting_paths=tuple(supporting_paths),
    )


def bullish_trend_bars(*, market: str = "US", timeframe: str = "5m") -> tuple[OhlcvRow, ...]:
    return (
        _bar(0, market=market, timeframe=timeframe, open_="100.0", high="100.6", low="99.8", close="100.3"),
        _bar(1, market=market, timeframe=timeframe, open_="100.3", high="100.9", low="100.1", close="100.7"),
        _bar(2, market=market, timeframe=timeframe, open_="100.7", high="101.4", low="100.6", close="101.2"),
    )


def sideways_bars(*, market: str = "US", timeframe: str = "5m") -> tuple[OhlcvRow, ...]:
    return (
        _bar(0, market=market, timeframe=timeframe, open_="100.0", high="100.2", low="99.9", close="100.1"),
        _bar(1, market=market, timeframe=timeframe, open_="100.1", high="100.2", low="99.95", close="100.0"),
    )


def synthetic_news_event(*, market: str = "US", index: int = 2) -> NewsEvent:
    return NewsEvent(
        symbol="SAMPLE",
        market=market,
        timestamp=_timestamp(index),
        source="synthetic-news",
        event_type="earnings",
        headline="synthetic event for knowledge-role conflict only",
        severity="high",
        notes="synthetic reliability fixture",
        timezone="America/New_York",
    )


def _bar(
    index: int,
    *,
    market: str,
    timeframe: str,
    open_: str,
    high: str,
    low: str,
    close: str,
) -> OhlcvRow:
    return OhlcvRow(
        symbol="SAMPLE",
        market=market,
        timeframe=timeframe,
        timestamp=_timestamp(index),
        timezone="America/New_York",
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("100000"),
    )


def _timestamp(index: int) -> datetime:
    base = datetime(2026, 1, 5, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    return base + timedelta(minutes=index * 5)
