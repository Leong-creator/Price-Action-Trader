from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Generic, Literal, Mapping, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RecordType = Literal["ohlcv", "news"]

OHLCV_REQUIRED_FIELDS = (
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

NEWS_REQUIRED_FIELDS = (
    "symbol",
    "market",
    "timestamp",
    "source",
    "event_type",
    "headline",
    "severity",
    "notes",
)

ALLOWED_MARKETS = frozenset({"US", "HK"})
ALLOWED_NEWS_SEVERITIES = frozenset({"low", "medium", "high", "critical"})

T = TypeVar("T", bound="DataRecord")


@dataclass(frozen=True, slots=True)
class ValidationError:
    record_type: RecordType
    code: str
    message: str
    field: str | None = None
    row_number: int | None = None
    raw_value: Any = None
    fatal: bool = True


class DataRecord:
    @property
    def identity_key(self) -> tuple[str, ...]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class OhlcvRow(DataRecord):
    symbol: str
    market: str
    timeframe: str
    timestamp: datetime
    timezone: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @property
    def identity_key(self) -> tuple[str, ...]:
        return (
            self.symbol,
            self.timeframe,
            self.timestamp.isoformat(),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp.isoformat(),
            "timezone": self.timezone,
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
        }


@dataclass(frozen=True, slots=True)
class NewsEvent(DataRecord):
    symbol: str
    market: str
    timestamp: datetime
    source: str
    event_type: str
    headline: str
    severity: str
    notes: str
    timezone: str

    @property
    def identity_key(self) -> tuple[str, ...]:
        return (
            self.symbol,
            self.market,
            self.timestamp.isoformat(),
            self.source,
            self.event_type,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "event_type": self.event_type,
            "headline": self.headline,
            "severity": self.severity,
            "notes": self.notes,
            "timezone": self.timezone,
        }


@dataclass(frozen=True, slots=True)
class CleanedRecord(Generic[T]):
    record_type: RecordType
    payload: T
    row_number: int | None = None
    source_name: str | None = None
    warnings: tuple[ValidationError, ...] = field(default_factory=tuple)

    @property
    def identity_key(self) -> tuple[str, ...]:
        return self.payload.identity_key

    def to_mapping(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "row_number": self.row_number,
            "source_name": self.source_name,
            "identity_key": list(self.identity_key),
            "payload": self.payload.to_mapping(),
            "warnings": [
                {
                    "record_type": warning.record_type,
                    "code": warning.code,
                    "message": warning.message,
                    "field": warning.field,
                    "row_number": warning.row_number,
                    "raw_value": warning.raw_value,
                    "fatal": warning.fatal,
                }
                for warning in self.warnings
            ],
        }


def clean_ohlcv_row(
    raw: Mapping[str, Any],
    *,
    row_number: int | None = None,
    source_name: str | None = None,
) -> tuple[CleanedRecord[OhlcvRow] | None, tuple[ValidationError, ...]]:
    errors: list[ValidationError] = []
    symbol = _clean_text(raw, "symbol", "ohlcv", errors, row_number, uppercase=True)
    market = _clean_text(raw, "market", "ohlcv", errors, row_number, uppercase=True)
    timeframe = _clean_text(raw, "timeframe", "ohlcv", errors, row_number, lowercase=True)
    timezone_name = _clean_text(raw, "timezone", "ohlcv", errors, row_number)
    open_price = _clean_decimal(raw, "open", "ohlcv", errors, row_number)
    high_price = _clean_decimal(raw, "high", "ohlcv", errors, row_number)
    low_price = _clean_decimal(raw, "low", "ohlcv", errors, row_number)
    close_price = _clean_decimal(raw, "close", "ohlcv", errors, row_number)
    volume = _clean_decimal(raw, "volume", "ohlcv", errors, row_number, allow_zero=True)

    if market and market not in ALLOWED_MARKETS:
        errors.append(
            ValidationError(
                record_type="ohlcv",
                code="invalid_market",
                message=f"market must be one of {sorted(ALLOWED_MARKETS)}",
                field="market",
                row_number=row_number,
                raw_value=market,
            )
        )

    timestamp_value = _clean_timestamp(
        raw.get("timestamp"),
        timezone_name=timezone_name,
        record_type="ohlcv",
        field_name="timestamp",
        errors=errors,
        row_number=row_number,
    )

    if all(value is not None for value in (open_price, high_price, low_price, close_price)):
        if high_price < max(open_price, close_price, low_price):
            errors.append(
                ValidationError(
                    record_type="ohlcv",
                    code="invalid_high",
                    message="high must be >= open/close/low",
                    field="high",
                    row_number=row_number,
                    raw_value=str(high_price),
                )
            )
        if low_price > min(open_price, close_price, high_price):
            errors.append(
                ValidationError(
                    record_type="ohlcv",
                    code="invalid_low",
                    message="low must be <= open/close/high",
                    field="low",
                    row_number=row_number,
                    raw_value=str(low_price),
                )
            )

    for field_name, value in (
        ("open", open_price),
        ("high", high_price),
        ("low", low_price),
        ("close", close_price),
    ):
        if value is not None and value <= Decimal("0"):
            errors.append(
                ValidationError(
                    record_type="ohlcv",
                    code="non_positive_price",
                    message=f"{field_name} must be > 0",
                    field=field_name,
                    row_number=row_number,
                    raw_value=str(value),
                )
            )

    if volume is not None and volume < Decimal("0"):
        errors.append(
            ValidationError(
                record_type="ohlcv",
                code="negative_volume",
                message="volume must be >= 0",
                field="volume",
                row_number=row_number,
                raw_value=str(volume),
            )
        )

    if errors:
        return None, tuple(errors)

    record = OhlcvRow(
        symbol=symbol,
        market=market,
        timeframe=timeframe,
        timestamp=timestamp_value,
        timezone=timezone_name,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
    )
    return (
        CleanedRecord(
            record_type="ohlcv",
            payload=record,
            row_number=row_number,
            source_name=source_name,
        ),
        (),
    )


def clean_news_event(
    raw: Mapping[str, Any],
    *,
    row_number: int | None = None,
    source_name: str | None = None,
) -> tuple[CleanedRecord[NewsEvent] | None, tuple[ValidationError, ...]]:
    errors: list[ValidationError] = []
    symbol = _clean_text(raw, "symbol", "news", errors, row_number, uppercase=True)
    market = _clean_text(raw, "market", "news", errors, row_number, uppercase=True)
    source = _clean_text(raw, "source", "news", errors, row_number)
    event_type = _clean_text(raw, "event_type", "news", errors, row_number, lowercase=True)
    headline = _clean_text(raw, "headline", "news", errors, row_number)
    severity = _clean_text(raw, "severity", "news", errors, row_number, lowercase=True)
    notes = _clean_text(raw, "notes", "news", errors, row_number)
    timezone_name = _clean_optional_text(raw.get("timezone"))

    if market and market not in ALLOWED_MARKETS:
        errors.append(
            ValidationError(
                record_type="news",
                code="invalid_market",
                message=f"market must be one of {sorted(ALLOWED_MARKETS)}",
                field="market",
                row_number=row_number,
                raw_value=market,
            )
        )

    if severity and severity not in ALLOWED_NEWS_SEVERITIES:
        errors.append(
            ValidationError(
                record_type="news",
                code="invalid_severity",
                message=f"severity must be one of {sorted(ALLOWED_NEWS_SEVERITIES)}",
                field="severity",
                row_number=row_number,
                raw_value=severity,
            )
        )

    timestamp_value = _clean_timestamp(
        raw.get("timestamp"),
        timezone_name=timezone_name,
        record_type="news",
        field_name="timestamp",
        errors=errors,
        row_number=row_number,
    )

    if errors:
        return None, tuple(errors)

    record = NewsEvent(
        symbol=symbol,
        market=market,
        timestamp=timestamp_value,
        source=source,
        event_type=event_type,
        headline=headline,
        severity=severity,
        notes=notes,
        timezone=timezone_name or _tz_label(timestamp_value),
    )
    return (
        CleanedRecord(
            record_type="news",
            payload=record,
            row_number=row_number,
            source_name=source_name,
        ),
        (),
    )


def _clean_text(
    raw: Mapping[str, Any],
    field_name: str,
    record_type: RecordType,
    errors: list[ValidationError],
    row_number: int | None,
    *,
    uppercase: bool = False,
    lowercase: bool = False,
) -> str | None:
    value = _clean_optional_text(raw.get(field_name))
    if value is None:
        errors.append(
            ValidationError(
                record_type=record_type,
                code="missing_required_field",
                message=f"{field_name} is required",
                field=field_name,
                row_number=row_number,
                raw_value=raw.get(field_name),
            )
        )
        return None

    if uppercase:
        return value.upper()
    if lowercase:
        return value.lower()
    return value


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_decimal(
    raw: Mapping[str, Any],
    field_name: str,
    record_type: RecordType,
    errors: list[ValidationError],
    row_number: int | None,
    *,
    allow_zero: bool = False,
) -> Decimal | None:
    value = raw.get(field_name)
    if value is None or str(value).strip() == "":
        errors.append(
            ValidationError(
                record_type=record_type,
                code="missing_required_field",
                message=f"{field_name} is required",
                field=field_name,
                row_number=row_number,
                raw_value=value,
            )
        )
        return None

    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        errors.append(
            ValidationError(
                record_type=record_type,
                code="invalid_decimal",
                message=f"{field_name} must be a valid decimal",
                field=field_name,
                row_number=row_number,
                raw_value=value,
            )
        )
        return None

    if not allow_zero and number == Decimal("0"):
        errors.append(
            ValidationError(
                record_type=record_type,
                code="zero_not_allowed",
                message=f"{field_name} must be non-zero",
                field=field_name,
                row_number=row_number,
                raw_value=str(number),
            )
        )
        return None

    return number


def _clean_timestamp(
    value: Any,
    *,
    timezone_name: str | None,
    record_type: RecordType,
    field_name: str,
    errors: list[ValidationError],
    row_number: int | None,
) -> datetime | None:
    if value is None or str(value).strip() == "":
        errors.append(
            ValidationError(
                record_type=record_type,
                code="missing_required_field",
                message=f"{field_name} is required",
                field=field_name,
                row_number=row_number,
                raw_value=value,
            )
        )
        return None

    text = str(value).strip()
    try:
        timestamp = datetime.fromisoformat(text)
    except ValueError:
        errors.append(
            ValidationError(
                record_type=record_type,
                code="invalid_timestamp",
                message=f"{field_name} must be ISO-8601 compatible",
                field=field_name,
                row_number=row_number,
                raw_value=text,
            )
        )
        return None

    zone = _resolve_zoneinfo(timezone_name, record_type, errors, row_number)
    if zone is None and timestamp.tzinfo is None:
        errors.append(
            ValidationError(
                record_type=record_type,
                code="missing_timezone_context",
                message=f"{field_name} requires timezone context",
                field=field_name,
                row_number=row_number,
                raw_value=text,
            )
        )
        return None

    if timestamp.tzinfo is None and zone is not None:
        return timestamp.replace(tzinfo=zone)
    if zone is not None:
        return timestamp.astimezone(zone)
    return timestamp


def _resolve_zoneinfo(
    timezone_name: str | None,
    record_type: RecordType,
    errors: list[ValidationError],
    row_number: int | None,
) -> ZoneInfo | None:
    if not timezone_name:
        return None

    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        errors.append(
            ValidationError(
                record_type=record_type,
                code="invalid_timezone",
                message="timezone must be a valid IANA timezone name",
                field="timezone",
                row_number=row_number,
                raw_value=timezone_name,
            )
        )
        return None


def _tz_label(value: datetime) -> str:
    zone_key = getattr(value.tzinfo, "key", None)
    if zone_key:
        return zone_key
    offset = value.utcoffset()
    if offset is None:
        return "UTC"
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


__all__ = [
    "ALLOWED_MARKETS",
    "ALLOWED_NEWS_SEVERITIES",
    "CleanedRecord",
    "NEWS_REQUIRED_FIELDS",
    "NewsEvent",
    "OHLCV_REQUIRED_FIELDS",
    "OhlcvRow",
    "ValidationError",
    "clean_news_event",
    "clean_ohlcv_row",
]
