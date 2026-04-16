"""Local CSV/JSON loaders for early-stage offline validation."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .schema import (
    NEWS_REQUIRED_FIELDS,
    OHLCV_REQUIRED_FIELDS,
    NewsEvent,
    OhlcvRow,
    ValidationError,
    clean_news_event,
    clean_ohlcv_row,
)


class DataValidationError(ValueError):
    """Raised when static test data does not satisfy the contract."""

    def __init__(self, source: Path, issues: Iterable[ValidationError]) -> None:
        issue_tuple = tuple(issues)
        self.source = source
        self.issues = issue_tuple
        message = "; ".join(
            f"{issue.code}:{issue.field or '-'}:{issue.message}" for issue in issue_tuple
        )
        super().__init__(f"{source}: {message}")


def load_ohlcv_csv(path: str | Path) -> list[OhlcvRow]:
    """Load local OHLCV bars from CSV and validate deterministic replay inputs."""

    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_csv_header(reader.fieldnames, csv_path)
        bars = []
        for row_number, row in enumerate(reader, start=2):
            cleaned, issues = clean_ohlcv_row(
                row,
                row_number=row_number,
                source_name=str(csv_path),
            )
            if issues:
                raise DataValidationError(csv_path, issues)
            bars.append(cleaned.payload)

    _validate_duplicate_bars(bars, csv_path)
    return sorted(bars, key=lambda bar: (bar.timestamp, bar.symbol, bar.timeframe))


def load_news_events(path: str | Path) -> list[NewsEvent]:
    """Load local JSON news fixtures used for event filtering and replay context."""

    json_path = Path(path)
    with json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, list):
        raise DataValidationError(
            json_path,
            (
                ValidationError(
                    record_type="news",
                    code="invalid_payload",
                    message="top-level JSON payload must be a list",
                ),
            ),
        )

    events = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise DataValidationError(
                json_path,
                (
                    ValidationError(
                        record_type="news",
                        code="invalid_event",
                        message=f"event #{index} must be a JSON object",
                        row_number=index,
                        raw_value=item,
                    ),
                ),
            )
        cleaned, issues = clean_news_event(
            item,
            row_number=index,
            source_name=str(json_path),
        )
        if issues:
            raise DataValidationError(json_path, issues)
        events.append(cleaned.payload)
    return sorted(events, key=lambda event: (event.timestamp, event.symbol, event.source))


def _validate_csv_header(fieldnames: Iterable[str] | None, path: Path) -> None:
    actual = tuple(fieldnames or ())
    if actual != OHLCV_REQUIRED_FIELDS:
        raise DataValidationError(
            path,
            (
                ValidationError(
                    record_type="ohlcv",
                    code="invalid_header",
                    message=f"expected CSV header {OHLCV_REQUIRED_FIELDS}, got {actual}",
                ),
            ),
        )

def _validate_duplicate_bars(bars: list[OhlcvRow], path: Path) -> None:
    seen: set[tuple[str, ...]] = set()
    for bar in bars:
        key = bar.identity_key
        if key in seen:
            raise DataValidationError(
                path,
                (
                    ValidationError(
                        record_type="ohlcv",
                        code="duplicate_bar",
                        message=(
                            "duplicate OHLCV row for "
                            f"{bar.symbol}/{bar.timeframe}/{bar.timestamp.isoformat()}"
                        ),
                    ),
                ),
            )
        seen.add(key)
