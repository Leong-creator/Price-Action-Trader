"""Local CSV/JSON loaders for early-stage offline validation."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


class DataValidationError(ValueError):
    """Raised when static test data does not satisfy the contract."""


@dataclass(frozen=True, slots=True)
class PriceBar:
    symbol: str
    market: str
    timeframe: str
    timestamp: datetime
    timezone: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True, slots=True)
class NewsEvent:
    symbol: str
    market: str
    timestamp: datetime
    source: str
    event_type: str
    headline: str
    severity: str
    notes: str


OHLCV_FIELDS = (
    "symbol",
    "market",
    "timeframe",
    "timestamp",
    "timezone",
    "open",
    "high",
    "low",
    "close",
    "volume",
)

NEWS_FIELDS = (
    "symbol",
    "market",
    "timestamp",
    "source",
    "event_type",
    "headline",
    "severity",
    "notes",
)


def load_ohlcv_csv(path: str | Path) -> list[PriceBar]:
    """Load local OHLCV bars from CSV and validate deterministic replay inputs."""

    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_csv_header(reader.fieldnames, csv_path)
        bars = [_build_price_bar(row, row_number) for row_number, row in enumerate(reader, start=2)]

    _validate_duplicate_bars(bars, csv_path)
    return sorted(bars, key=lambda bar: (bar.timestamp, bar.symbol, bar.timeframe))


def load_news_events(path: str | Path) -> list[NewsEvent]:
    """Load local JSON news fixtures used for event filtering and replay context."""

    json_path = Path(path)
    with json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, list):
        raise DataValidationError(f"{json_path}: top-level JSON payload must be a list.")

    events = [_build_news_event(item, index, json_path) for index, item in enumerate(payload, start=1)]
    return sorted(events, key=lambda event: (event.timestamp, event.symbol, event.source))


def _validate_csv_header(fieldnames: Iterable[str] | None, path: Path) -> None:
    actual = tuple(fieldnames or ())
    if actual != OHLCV_FIELDS:
        raise DataValidationError(
            f"{path}: expected CSV header {OHLCV_FIELDS}, got {actual}."
        )


def _build_price_bar(row: dict[str, str], row_number: int) -> PriceBar:
    _ensure_required_fields(row, OHLCV_FIELDS, f"OHLCV row {row_number}")

    symbol = row["symbol"].strip()
    market = row["market"].strip()
    timeframe = row["timeframe"].strip()
    timezone_name = row["timezone"].strip()
    timestamp = _parse_timestamp(row["timestamp"], timezone_name, f"OHLCV row {row_number}")

    open_price = _parse_positive_number(row["open"], f"OHLCV row {row_number} field 'open'")
    high_price = _parse_positive_number(row["high"], f"OHLCV row {row_number} field 'high'")
    low_price = _parse_positive_number(row["low"], f"OHLCV row {row_number} field 'low'")
    close_price = _parse_positive_number(row["close"], f"OHLCV row {row_number} field 'close'")
    volume = _parse_volume(row["volume"], f"OHLCV row {row_number} field 'volume'")

    if high_price < max(open_price, close_price, low_price):
        raise DataValidationError(
            f"OHLCV row {row_number}: high must be >= open/close/low."
        )
    if low_price > min(open_price, close_price, high_price):
        raise DataValidationError(
            f"OHLCV row {row_number}: low must be <= open/close/high."
        )

    return PriceBar(
        symbol=symbol,
        market=market,
        timeframe=timeframe,
        timestamp=timestamp,
        timezone=timezone_name,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
    )


def _build_news_event(item: Any, index: int, path: Path) -> NewsEvent:
    if not isinstance(item, dict):
        raise DataValidationError(f"{path}: event #{index} must be a JSON object.")

    _ensure_required_fields(item, NEWS_FIELDS, f"{path} event #{index}")
    timestamp = _parse_timestamp(item["timestamp"], item.get("timezone"), f"{path} event #{index}")

    return NewsEvent(
        symbol=str(item["symbol"]).strip(),
        market=str(item["market"]).strip(),
        timestamp=timestamp,
        source=str(item["source"]).strip(),
        event_type=str(item["event_type"]).strip(),
        headline=str(item["headline"]).strip(),
        severity=str(item["severity"]).strip(),
        notes=str(item["notes"]).strip(),
    )


def _ensure_required_fields(payload: dict[str, Any], fields: Iterable[str], label: str) -> None:
    missing = [field for field in fields if str(payload.get(field, "")).strip() == ""]
    if missing:
        raise DataValidationError(f"{label}: missing required fields {missing}.")


def _parse_timestamp(value: Any, timezone_name: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DataValidationError(f"{label}: timestamp must be a non-empty string.")

    raw_value = value.strip()
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError as exc:
        raise DataValidationError(f"{label}: invalid timestamp '{raw_value}'.") from exc

    if parsed.tzinfo is not None:
        return parsed

    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise DataValidationError(
            f"{label}: naive timestamp requires a timezone field."
        )

    try:
        zone = ZoneInfo(timezone_name.strip())
    except Exception as exc:  # pragma: no cover - ZoneInfo emits a platform-specific error type.
        raise DataValidationError(
            f"{label}: invalid timezone '{timezone_name}'."
        ) from exc

    return parsed.replace(tzinfo=zone)


def _parse_positive_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DataValidationError(f"{label}: must be numeric.") from exc

    if not math.isfinite(number) or number <= 0:
        raise DataValidationError(f"{label}: must be finite and > 0.")
    return number


def _parse_volume(value: Any, label: str) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise DataValidationError(f"{label}: must be numeric.") from exc

    if not math.isfinite(numeric) or numeric < 0:
        raise DataValidationError(f"{label}: must be finite and >= 0.")
    if not numeric.is_integer():
        raise DataValidationError(f"{label}: must be an integer-like value.")
    return int(numeric)


def _validate_duplicate_bars(bars: list[PriceBar], path: Path) -> None:
    seen: set[tuple[str, str, datetime]] = set()
    for bar in bars:
        key = (bar.symbol, bar.timeframe, bar.timestamp)
        if key in seen:
            raise DataValidationError(
                f"{path}: duplicate OHLCV row for {bar.symbol}/{bar.timeframe}/{bar.timestamp.isoformat()}."
            )
        seen.add(key)

