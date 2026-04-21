from __future__ import annotations

import csv
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo


def build_session_rows(
    session_date: date,
    *,
    symbol: str = "SPY",
    market: str = "US",
    timeframe: str = "15m",
    timezone: str = "America/New_York",
    start_price: Decimal | str = Decimal("100"),
    include_out_of_hours: bool = False,
    drop_bar_at: str | None = None,
) -> list[dict[str, str]]:
    zone = ZoneInfo(timezone)
    rows: list[dict[str, str]] = []
    current = datetime.combine(session_date, time(9, 30), tzinfo=zone)
    price = Decimal(str(start_price))
    step_minutes = _interval_to_minutes(timeframe)
    total_bars = _regular_session_bar_count(step_minutes)
    for index in range(total_bars):
        if drop_bar_at and current.strftime("%H:%M") == drop_bar_at:
            current += timedelta(minutes=step_minutes)
            continue
        open_price = price
        close_price = price + Decimal("0.25") if index % 4 != 3 else price - Decimal("0.10")
        high_price = max(open_price, close_price) + Decimal("0.15")
        low_price = min(open_price, close_price) - Decimal("0.15")
        rows.append(
            {
                "symbol": symbol,
                "market": market,
                "timeframe": timeframe,
                "timestamp": current.replace(tzinfo=None).isoformat(timespec="seconds"),
                "timezone": timezone,
                "open": f"{open_price:.4f}",
                "high": f"{high_price:.4f}",
                "low": f"{low_price:.4f}",
                "close": f"{close_price:.4f}",
                "volume": "100000",
            }
        )
        price = close_price
        current += timedelta(minutes=step_minutes)

    if include_out_of_hours:
        rows.append(
            {
                "symbol": symbol,
                "market": market,
                "timeframe": timeframe,
                "timestamp": datetime.combine(session_date, time(8, 0), tzinfo=zone)
                .replace(tzinfo=None)
                .isoformat(timespec="seconds"),
                "timezone": timezone,
                "open": "100.0000",
                "high": "100.1000",
                "low": "99.9000",
                "close": "100.0500",
                "volume": "5000",
            }
        )
    return rows


def write_intraday_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
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
            ),
        )
        writer.writeheader()
        writer.writerows(rows)


def write_metadata(path: Path, *, source: str, row_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source,
        "row_count": row_count,
        "boundary": "paper/simulated",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _interval_to_minutes(timeframe: str) -> int:
    mapping = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
    }
    try:
        return mapping[timeframe]
    except KeyError as exc:
        raise ValueError(f"Unsupported test timeframe: {timeframe}") from exc


def _regular_session_bar_count(step_minutes: int) -> int:
    total_minutes = 390
    count, remainder = divmod(total_minutes, step_minutes)
    return count + (1 if remainder else 0)
