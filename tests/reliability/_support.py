from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from src.execution import ExecutionRequest
from src.risk import RiskConfig, SessionRiskState
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


def extended_bullish_trade_bars(*, market: str = "US", timeframe: str = "5m") -> tuple[OhlcvRow, ...]:
    return bullish_trend_bars(market=market, timeframe=timeframe) + (
        _bar(
            3,
            market=market,
            timeframe=timeframe,
            open_="101.2",
            high="101.6",
            low="100.8",
            close="101.4",
        ),
        _bar(
            4,
            market=market,
            timeframe=timeframe,
            open_="101.4",
            high="103.4",
            low="101.3",
            close="103.0",
        ),
    )


def end_of_data_bars(*, market: str = "US", timeframe: str = "5m") -> tuple[OhlcvRow, ...]:
    return bullish_trend_bars(market=market, timeframe=timeframe) + (
        _bar(
            3,
            market=market,
            timeframe=timeframe,
            open_="101.2",
            high="101.5",
            low="101.0",
            close="101.3",
        ),
    )


def future_tail_bars(*, market: str = "US", timeframe: str = "5m") -> tuple[OhlcvRow, ...]:
    return bullish_trend_bars(market=market, timeframe=timeframe) + (
        _bar(
            3,
            market=market,
            timeframe=timeframe,
            open_="101.2",
            high="101.5",
            low="100.9",
            close="101.1",
        ),
        _bar(
            4,
            market=market,
            timeframe=timeframe,
            open_="101.1",
            high="101.2",
            low="99.2",
            close="99.5",
        ),
    )


def past_caution_news(*, market: str = "US", index: int = 1) -> tuple[NewsEvent, ...]:
    return (
        NewsEvent(
            symbol="SAMPLE",
            market=market,
            timestamp=_timestamp(index),
            source="synthetic-news",
            event_type="conference",
            headline="synthetic caution event for offline reliability",
            severity="medium",
            notes="synthetic reliability fixture",
            timezone="America/New_York",
        ),
    )


def future_blocking_news(*, market: str = "US", index: int = 4) -> tuple[NewsEvent, ...]:
    return (
        NewsEvent(
            symbol="SAMPLE",
            market=market,
            timestamp=_timestamp(index),
            source="synthetic-news",
            event_type="earnings",
            headline="synthetic future blocking event for leakage testing",
            severity="high",
            notes="synthetic reliability fixture",
            timezone="America/New_York",
        ),
    )


def equal_timestamp_news(*, market: str = "US", index: int = 0) -> tuple[NewsEvent, ...]:
    return (
        NewsEvent(
            symbol="SAMPLE",
            market=market,
            timestamp=_timestamp(index),
            source="synthetic-news",
            event_type="filing",
            headline="synthetic equal timestamp event for replay ordering",
            severity="low",
            notes="synthetic reliability fixture",
            timezone="America/New_York",
        ),
    )


def between_bar_news(*, market: str = "US") -> tuple[NewsEvent, ...]:
    return (
        NewsEvent(
            symbol="SAMPLE",
            market=market,
            timestamp=_timestamp(0) + timedelta(minutes=2),
            source="synthetic-news",
            event_type="macro_commentary",
            headline="synthetic between-bar event for leakage boundary",
            severity="medium",
            notes="synthetic reliability fixture",
            timezone="America/New_York",
        ),
    )


def default_risk_config() -> RiskConfig:
    return RiskConfig(
        max_risk_per_order=Decimal("150"),
        max_total_exposure=Decimal("1000"),
        max_symbol_exposure_ratio=Decimal("1"),
        max_daily_loss=Decimal("200"),
        max_consecutive_losses=2,
        allow_manual_resume_from_loss_streak=True,
    )


def default_session_state(session_key: str = "2026-01-05") -> SessionRiskState:
    return SessionRiskState(session_key=session_key)


def build_execution_request(
    *,
    signal,
    trade,
    session_key: str = "2026-01-05",
    quantity: str = "1",
) -> ExecutionRequest:
    quantity_decimal = Decimal(quantity)
    return ExecutionRequest(
        signal=signal,
        requested_at=trade.entry_timestamp,
        session_key=session_key,
        entry_price=trade.entry_price,
        stop_price=trade.stop_price,
        target_price=trade.target_price,
        proposed_quantity=quantity_decimal,
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
