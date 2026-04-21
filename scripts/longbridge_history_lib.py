#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo


LONGBRIDGE_INSTALL_HINT = (
    "longbridge CLI is not installed. Install it first with the official installer, "
    "then run `longbridge auth login` before requesting historical data."
)
LONGRIDGE_AUTH_HINT = (
    "longbridge CLI is not authenticated or does not have quote permission. "
    "Run `longbridge auth login`, finish the browser authorization for the simulated account, "
    "and confirm quote permission is enabled in OpenAPI."
)
SUPPORTED_LONGBRIDGE_INTERVALS = frozenset({"1m", "5m", "15m", "30m", "1h", "1d", "1w", "1mo", "1y"})
INTRADAY_INTERVALS = frozenset({"1m", "5m", "15m", "30m", "1h"})
_INTERVAL_TO_PERIOD = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "1d": "day",
    "1w": "week",
    "1mo": "month",
    "1y": "year",
}
_INTERVAL_CHUNK_DAYS = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "1d": 900,
    "1w": 3650,
    "1mo": 3650,
    "1y": 3650,
}


@dataclass(frozen=True, slots=True)
class LongbridgeHistoryBar:
    time_text: str
    open_value: str
    high_value: str
    low_value: str
    close_value: str
    volume_value: str
    turnover_value: str
    session: str | None = None


def build_longbridge_symbol(*, ticker: str, market: str) -> str:
    if "." in ticker:
        return ticker
    return f"{ticker}.{market.upper()}"


def fetch_longbridge_daily_history_rows(
    *,
    ticker: str,
    symbol: str,
    market: str,
    timezone_name: str,
    start: date,
    end: date,
    interval: str,
) -> list[dict[str, str]]:
    if interval not in {"1d", "1w", "1mo", "1y"}:
        raise RuntimeError(f"Unsupported Longbridge daily interval: {interval}")

    bars = _fetch_longbridge_history_bars(
        ticker=ticker,
        market=market,
        start=start,
        end=end,
        interval=interval,
        session=None,
    )
    zone = ZoneInfo(timezone_name)
    rows: list[dict[str, str]] = []
    for bar in bars:
        trading_date = _parse_cli_timestamp(bar.time_text).date()
        local_timestamp = datetime.combine(trading_date, time(16, 0), tzinfo=zone)
        rows.append(
            {
                "symbol": symbol,
                "market": market,
                "timeframe": interval,
                "timestamp": local_timestamp.isoformat(),
                "timezone": timezone_name,
                "open": bar.open_value,
                "high": bar.high_value,
                "low": bar.low_value,
                "close": bar.close_value,
                "volume": bar.volume_value,
            }
        )
    return rows


def fetch_longbridge_intraday_history_rows(
    *,
    ticker: str,
    symbol: str,
    market: str,
    timezone_name: str,
    start: date,
    end: date,
    interval: str,
    allow_extended_hours: bool,
) -> list[dict[str, str]]:
    if interval not in INTRADAY_INTERVALS:
        raise RuntimeError(f"Unsupported Longbridge intraday interval: {interval}")

    bars = _fetch_longbridge_history_bars(
        ticker=ticker,
        market=market,
        start=start,
        end=end,
        interval=interval,
        session="all" if allow_extended_hours else "intraday",
    )
    zone = ZoneInfo(timezone_name)
    rows: list[dict[str, str]] = []
    for bar in bars:
        localized = _parse_cli_timestamp(bar.time_text).astimezone(zone)
        rows.append(
            {
                "symbol": symbol,
                "market": market,
                "timeframe": interval,
                "timestamp": localized.replace(tzinfo=None).isoformat(timespec="seconds"),
                "timezone": timezone_name,
                "open": bar.open_value,
                "high": bar.high_value,
                "low": bar.low_value,
                "close": bar.close_value,
                "volume": bar.volume_value,
            }
        )
    return rows


def _fetch_longbridge_history_bars(
    *,
    ticker: str,
    market: str,
    start: date,
    end: date,
    interval: str,
    session: str | None,
) -> list[LongbridgeHistoryBar]:
    if interval not in SUPPORTED_LONGBRIDGE_INTERVALS:
        raise RuntimeError(f"Unsupported Longbridge interval: {interval}")
    if start > end:
        raise RuntimeError(f"Longbridge history requires start <= end, got {start} > {end}")

    binary = shutil.which("longbridge")
    if binary is None:
        raise RuntimeError(LONGBRIDGE_INSTALL_HINT)

    symbol = build_longbridge_symbol(ticker=ticker, market=market)
    period = _INTERVAL_TO_PERIOD[interval]
    deduped: dict[tuple[str, str | None], LongbridgeHistoryBar] = {}

    for chunk_start, chunk_end in _iter_date_chunks(
        start=start,
        end=end,
        max_days=_INTERVAL_CHUNK_DAYS[interval],
    ):
        command = [
            binary,
            "kline",
            "history",
            symbol,
            "--start",
            chunk_start.isoformat(),
            "--end",
            chunk_end.isoformat(),
            "--period",
            period,
            "--adjust",
            "none",
            "--format",
            "json",
        ]
        if session is not None:
            command.extend(["--session", session])
        payload = _run_longbridge_command(command, symbol=symbol, start=chunk_start, end=chunk_end)
        for bar in _parse_history_payload(payload):
            deduped[(bar.time_text, bar.session)] = bar
    return sorted(deduped.values(), key=lambda item: (item.time_text, item.session or ""))


def _run_longbridge_command(
    command: list[str],
    *,
    symbol: str,
    start: date,
    end: date,
) -> Any:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stderr or completed.stdout or "").strip()
    if completed.returncode != 0:
        lowered = output.lower()
        if any(token in lowered for token in ("auth", "login", "unauthorized", "forbidden", "permission")):
            raise RuntimeError(LONGRIDGE_AUTH_HINT)
        detail = output or f"exit code {completed.returncode}"
        raise RuntimeError(
            f"longbridge kline history failed for {symbol} {start.isoformat()}~{end.isoformat()}: {detail}"
        )
    stdout = completed.stdout.strip()
    if not stdout:
        return []
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"longbridge returned non-JSON output for {symbol}: {stdout}") from exc


def _parse_history_payload(payload: Any) -> list[LongbridgeHistoryBar]:
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected longbridge history payload: {payload!r}")

    rows: list[LongbridgeHistoryBar] = []
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimeError(f"Unexpected longbridge history row: {item!r}")
        rows.append(
            LongbridgeHistoryBar(
                time_text=_require_text(item, "time"),
                open_value=_require_text(item, "open"),
                high_value=_require_text(item, "high"),
                low_value=_require_text(item, "low"),
                close_value=_require_text(item, "close"),
                volume_value=_normalize_number_text(_require_text(item, "volume")),
                turnover_value=_normalize_number_text(_require_text(item, "turnover")),
                session=_optional_text(item.get("session")),
            )
        )
    return rows


def _iter_date_chunks(*, start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    if max_days <= 0:
        raise RuntimeError(f"Longbridge chunk size must be positive, got {max_days}")
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end)
        windows.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return windows


def _parse_cli_timestamp(value: str) -> datetime:
    text = value.strip()
    normalized = text.replace(" ", "T")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _require_text(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    text = _optional_text(value)
    if text is None:
        raise RuntimeError(f"longbridge history row missing `{key}`: {item!r}")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_number_text(value: str) -> str:
    return value.replace(",", "")
