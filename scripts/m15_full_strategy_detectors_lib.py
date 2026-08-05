#!/usr/bin/env python3
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo


ZERO = Decimal("0")
ONE = Decimal("1")
NEW_YORK = ZoneInfo("America/New_York")


def d(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return ZERO


def bar_time(row: dict[str, Any]) -> datetime | None:
    raw = str(row.get("event_time") or row.get("bar_time") or row.get("timestamp") or "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def close_position(row: dict[str, Any]) -> Decimal:
    high, low, close = d(row.get("high")), d(row.get("low")), d(row.get("close"))
    return (close - low) / (high - low) if high > low and close > ZERO else ZERO


def body_fraction(row: dict[str, Any]) -> Decimal:
    high, low = d(row.get("high")), d(row.get("low"))
    return abs(d(row.get("close")) - d(row.get("open"))) / (high - low) if high > low else ZERO


def next_bar_entry(row: dict[str, Any]) -> tuple[Decimal, str, str]:
    price = d(row.get("next_bar_first_quote_price"))
    at = str(row.get("next_bar_first_quote_at") or "")
    source = str(row.get("next_bar_entry_source") or "")
    if price <= ZERO or not at:
        return ZERO, "", ""
    return price, at, source or "longbridge_sdk_first_quote_after_bar_close"


def base_result(
    *,
    detector_id: str,
    symbol: str,
    latest: dict[str, Any],
    entry: Decimal,
    stop: Decimal,
    target: Decimal,
    entry_at: str,
    entry_source: str,
    structure: dict[str, Any],
) -> dict[str, Any] | None:
    if min(entry, stop, target) <= ZERO or not (stop < entry < target):
        return None
    return {
        "detector_id": detector_id,
        "symbol": symbol,
        "direction": "long",
        "side": "buy",
        "order_type": "limit",
        "limit_price": format(entry, "f"),
        "stop_price": format(stop, "f"),
        "target_price": format(target, "f"),
        "current_price": format(entry, "f"),
        "source_market_event_id": str(latest.get("event_id") or latest.get("market_event_id") or ""),
        "market_event_time": str(latest.get("event_time") or latest.get("bar_time") or latest.get("timestamp") or ""),
        "created_at": entry_at,
        "entry_timing": "next_bar_first_quote",
        "entry_price_source": entry_source,
        "confirmation_state": "confirmed_then_next_bar_entry",
        "contract_evidence": structure,
    }


def pa001_daily_long(
    symbol: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """20-bar trend, two-leg pullback and H2-style resumption, long only."""
    if len(rows) < 22:
        return None
    latest = rows[-1]
    entry, entry_at, entry_source = next_bar_entry(latest)
    if entry <= ZERO:
        return None
    context = rows[-21:-1]
    closes = [d(row.get("close")) for row in context]
    if min(closes) <= ZERO:
        return None
    sma20 = sum(closes, ZERO) / Decimal(len(closes))
    trend_start = closes[0]
    trend_close = closes[-1]
    recent = rows[-9:-1]
    if not (trend_close > sma20 and trend_close > trend_start):
        return None
    countertrend_bars = sum(
        1 for index in range(1, len(recent))
        if d(recent[index].get("close")) < d(recent[index - 1].get("close"))
    )
    local_lows = [
        index for index in range(1, len(recent) - 1)
        if d(recent[index].get("low")) < d(recent[index - 1].get("low"))
        and d(recent[index].get("low")) <= d(recent[index + 1].get("low"))
    ]
    if countertrend_bars < 2 or len(local_lows) < 2:
        return None
    previous = rows[-2]
    if d(latest.get("close")) <= d(previous.get("high")) or d(latest.get("close")) <= d(latest.get("open")):
        return None
    recent_high = max(d(row.get("high")) for row in recent)
    recent_low = min(d(row.get("low")) for row in recent)
    average_range = sum((d(row.get("high")) - d(row.get("low")) for row in context), ZERO) / Decimal(len(context))
    overlap_count = sum(
        1 for index in range(1, 5)
        if min(d(rows[-index].get("high")), d(rows[-index - 1].get("high")))
        > max(d(rows[-index].get("low")), d(rows[-index - 1].get("low")))
    )
    if average_range > ZERO and recent_high - recent_low <= average_range * Decimal("1.50") and overlap_count >= 3:
        return None
    stop = recent_low
    risk = entry - stop
    if risk <= ZERO:
        return None
    return base_result(
        detector_id="pa001_daily_long_contract_v1",
        symbol=symbol,
        latest=latest,
        entry=entry,
        stop=stop,
        target=entry + risk * Decimal("2"),
        entry_at=entry_at,
        entry_source=entry_source,
        structure={
            "trend_lookback_bars": 20,
            "sma20": format(sma20, "f"),
            "countertrend_bar_count": countertrend_bars,
            "confirmed_pullback_low_count": len(local_lows),
            "h2_resumption_confirmed": True,
            "tight_range_blocked": False,
            "pullback_stop": format(stop, "f"),
            "target_model": "2R",
        },
    )


def _qualified_upside_breakout(row: dict[str, Any], range_high: Decimal) -> bool:
    return (
        d(row.get("close")) > range_high
        and body_fraction(row) >= Decimal("0.50")
        and close_position(row) >= Decimal("0.666666")
    )


def pa002_five_minute_long(
    symbol: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Strict prior-20-bar breakout plus the first valid 1-2 bar follow-through."""
    if len(rows) < 22:
        return None
    latest = rows[-1]
    entry, entry_at, entry_source = next_bar_entry(latest)
    if entry <= ZERO:
        return None
    matched: tuple[dict[str, Any], Decimal, Decimal, int] | None = None
    for confirmation_lag in (1, 2):
        breakout_index = len(rows) - 1 - confirmation_lag
        if breakout_index < 20:
            continue
        breakout = rows[breakout_index]
        prior = rows[breakout_index - 20:breakout_index]
        range_high = max(d(row.get("high")) for row in prior)
        range_low = min(d(row.get("low")) for row in prior)
        if range_high <= range_low or not _qualified_upside_breakout(breakout, range_high):
            continue
        follow = rows[breakout_index + 1:]
        if any(d(row.get("close")) <= range_high for row in follow):
            continue
        # Only the first qualifying follow-through bar may confirm the setup.
        if confirmation_lag == 2 and d(follow[0].get("close")) > range_high:
            continue
        if d(latest.get("close")) <= range_high:
            continue
        matched = breakout, range_high, range_low, confirmation_lag
        break
    if matched is None:
        return None
    breakout, range_high, range_low, confirmation_lag = matched
    stop = d(breakout.get("low"))
    measured_target = entry + (range_high - range_low)
    if stop <= ZERO or stop >= entry or measured_target <= entry:
        return None
    return base_result(
        detector_id="pa002_5m_long_contract_v1",
        symbol=symbol,
        latest=latest,
        entry=entry,
        stop=stop,
        target=measured_target,
        entry_at=entry_at,
        entry_source=entry_source,
        structure={
            "range_lookback_bars": 20,
            "range_high": format(range_high, "f"),
            "range_low": format(range_low, "f"),
            "breakout_bar_event_id": str(breakout.get("event_id") or ""),
            "breakout_body_fraction": format(body_fraction(breakout), "f"),
            "breakout_close_position": format(close_position(breakout), "f"),
            "follow_through_bar_count": confirmation_lag,
            "immediate_range_reentry": False,
            "target_model": "prior_20_bar_range_measured_move",
        },
    )


def ny_session_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timed = [(bar_time(row), row) for row in rows]
    timed = [(value, row) for value, row in timed if value is not None]
    if not timed:
        return []
    latest_date = timed[-1][0].astimezone(NEW_YORK).date()
    return [row for value, row in timed if value.astimezone(NEW_YORK).date() == latest_date]


def pa012_five_minute_long(
    symbol: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """First-30-minute ORB with a qualified bar and first 1-2 bar confirmation."""
    session = ny_session_rows(rows)
    if len(session) < 8:
        return None
    latest = session[-1]
    entry, entry_at, entry_source = next_bar_entry(latest)
    if entry <= ZERO:
        return None
    opening = session[:6]
    opening_high = max(d(row.get("high")) for row in opening)
    opening_low = min(d(row.get("low")) for row in opening)
    if opening_high <= opening_low:
        return None
    matched: tuple[dict[str, Any], int] | None = None
    for breakout_index in range(6, len(session) - 1):
        breakout = session[breakout_index]
        if not _qualified_upside_breakout(breakout, opening_high):
            continue
        offset = len(session) - 1 - breakout_index
        if offset not in (1, 2):
            continue
        follow = session[breakout_index + 1:]
        if any(d(row.get("close")) <= opening_high for row in follow):
            continue
        if offset == 2 and d(follow[0].get("close")) > opening_high:
            continue
        matched = breakout, offset
        break
    if matched is None:
        return None
    breakout, confirmation_lag = matched
    stop = min(opening_low, d(breakout.get("low")))
    target = entry + (opening_high - opening_low)
    if stop <= ZERO or stop >= entry or target <= entry:
        return None
    return base_result(
        detector_id="pa012_5m_long_contract_v1",
        symbol=symbol,
        latest=latest,
        entry=entry,
        stop=stop,
        target=target,
        entry_at=entry_at,
        entry_source=entry_source,
        structure={
            "regular_session_only": True,
            "opening_range_bar_count": 6,
            "opening_range_high": format(opening_high, "f"),
            "opening_range_low": format(opening_low, "f"),
            "breakout_bar_event_id": str(breakout.get("event_id") or ""),
            "breakout_body_fraction": format(body_fraction(breakout), "f"),
            "breakout_close_position": format(close_position(breakout), "f"),
            "follow_through_bar_count": confirmation_lag,
            "target_model": "opening_range_height_measured_move",
            "forced_exit_time_ny": "15:55",
        },
    )
