#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, time as wall_time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.m15_visual_strategy_shadow_lib import bar_id
from scripts.m15_visual_strategy_shadow_lib import load_config as load_shadow_config
from scripts.m15_visual_strategy_shadow_lib import load_state as load_shadow_state
from scripts.m15_visual_strategy_shadow_lib import normalize_bar
from scripts.m15_visual_strategy_shadow_lib import run_visual_strategy_shadow
from scripts.m15_visual_strategy_shadow_lib import stream_key


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_visual_strategy_shadow_session.json"
SCHEMA_VERSION = "m15.visual-strategy-shadow-session.v1"


@dataclass(frozen=True, slots=True)
class VisualShadowSessionConfig:
    stage: str
    market_events_path: Path
    universe_path: Path
    shadow_config_path: Path
    acceptance_config_path: Path | None
    session_ledger_path: Path
    session_summary_path: Path
    aggregated_daily_bars_path: Path
    market_timezone: str
    regular_open_time: str
    regular_close_time: str
    timeframe_minutes: int
    expected_bars_per_symbol: int
    required_symbol_count: int
    allowed_source_modes: tuple[str, ...]


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> VisualShadowSessionConfig:
    payload = json.loads(resolve_path(path).read_text(encoding="utf-8"))
    boundaries = payload.get("hard_boundaries", {})
    forbidden = [
        key
        for key in ("order_generation", "broker_connection", "real_orders", "live_execution")
        if boundaries.get(key) is not False
    ]
    if forbidden:
        raise ValueError(f"visual shadow session hard boundaries must be explicitly false: {forbidden}")
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    session = payload["session"]
    config = VisualShadowSessionConfig(
        stage=str(payload["stage"]),
        market_events_path=resolve_path(inputs["market_events"]),
        universe_path=resolve_path(inputs["universe"]),
        shadow_config_path=resolve_path(inputs["shadow_config"]),
        acceptance_config_path=(
            resolve_path(inputs["acceptance_config"])
            if inputs.get("acceptance_config")
            else None
        ),
        session_ledger_path=resolve_path(outputs["session_ledger_jsonl"]),
        session_summary_path=resolve_path(outputs["session_summary_json"]),
        aggregated_daily_bars_path=resolve_path(outputs["aggregated_daily_bars_jsonl"]),
        market_timezone=str(session["market_timezone"]),
        regular_open_time=str(session["regular_open_time"]),
        regular_close_time=str(session["regular_close_time"]),
        timeframe_minutes=int(session["timeframe_minutes"]),
        expected_bars_per_symbol=int(session["expected_bars_per_symbol"]),
        required_symbol_count=int(session["required_symbol_count"]),
        allowed_source_modes=tuple(str(item) for item in session["allowed_source_modes"]),
    )
    validate_config(config)
    return config


def validate_config(config: VisualShadowSessionConfig) -> None:
    if config.stage != "M15.visual_strategy_shadow_session":
        raise ValueError("visual shadow session stage drift")
    if config.timeframe_minutes <= 0 or config.expected_bars_per_symbol <= 0:
        raise ValueError("visual shadow session intervals must be positive")
    if config.required_symbol_count <= 0:
        raise ValueError("visual shadow session required_symbol_count must be positive")
    if not config.allowed_source_modes:
        raise ValueError("visual shadow session requires at least one SDK source mode")
    if any("sdk" not in mode.lower() for mode in config.allowed_source_modes):
        raise ValueError("visual shadow session source modes must be SDK-only")
    open_time = parse_clock(config.regular_open_time)
    close_time = parse_clock(config.regular_close_time)
    open_minutes = open_time.hour * 60 + open_time.minute
    close_minutes = close_time.hour * 60 + close_time.minute
    expected = (close_minutes - open_minutes) // config.timeframe_minutes
    if expected != config.expected_bars_per_symbol:
        raise ValueError("visual shadow session expected bar count does not match RTH window")
    for path in (
        config.market_events_path,
        config.universe_path,
        config.shadow_config_path,
        config.acceptance_config_path,
    ):
        if path is None:
            continue
        if not path.exists():
            raise ValueError(f"visual shadow session input missing: {path}")


def parse_clock(value: str) -> wall_time:
    hour, minute = value.split(":")
    return wall_time(hour=int(hour), minute=int(minute))


def now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_universe_symbols(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("symbols", [])
    if not isinstance(raw, list):
        raise ValueError("visual shadow universe symbols must be a list")
    symbols = [str(item).strip().upper() for item in raw if str(item).strip()]
    if len(symbols) != len(set(symbols)):
        raise ValueError("visual shadow universe contains duplicate symbols")
    return symbols


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row must be an object at {path}:{line_number}")
            rows.append(row)
    return rows


def read_completed_dates(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        str(row.get("business_date"))
        for row in read_jsonl(path)
        if row.get("status") == "completed" and row.get("session_complete") is True
    }


def expected_close_times(config: VisualShadowSessionConfig, business_date: str) -> list[datetime]:
    timezone = ZoneInfo(config.market_timezone)
    date_value = datetime.fromisoformat(f"{business_date}T00:00:00").date()
    cursor = datetime.combine(date_value, parse_clock(config.regular_open_time), tzinfo=timezone)
    close = datetime.combine(date_value, parse_clock(config.regular_close_time), tzinfo=timezone)
    values: list[datetime] = []
    while cursor < close:
        cursor += timedelta(minutes=config.timeframe_minutes)
        values.append(cursor)
    return values


def collect_session_rows(
    config: VisualShadowSessionConfig,
    *,
    business_date: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    symbols = read_universe_symbols(config.universe_path)
    if len(symbols) != config.required_symbol_count:
        raise ValueError(
            f"visual shadow universe count drift: expected={config.required_symbol_count} actual={len(symbols)}"
        )
    required = set(symbols)
    timezone = ZoneInfo(config.market_timezone)
    expected_times = expected_close_times(config, business_date)
    expected_time_keys = {item.isoformat() for item in expected_times}
    grouped: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    duplicates: list[str] = []
    invalid_sources: list[str] = []
    blocked_rows: list[str] = []
    seen: set[tuple[str, str]] = set()

    for row in read_jsonl(config.market_events_path):
        if str(row.get("timeframe")) != f"{config.timeframe_minutes}m" or row.get("bar_final") is not True:
            continue
        # Context-only rows restore strategy state after a process restart. They
        # are not evidence that the realtime SDK stream delivered that bar.
        if row.get("context_only") is True:
            continue
        symbol = str(row.get("symbol") or "").upper()
        if symbol not in required:
            continue
        raw_time = str(row.get("event_time") or row.get("bar_close_at") or "")
        if not raw_time:
            continue
        event_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if event_time.tzinfo is None:
            raise ValueError("visual shadow market event time must include timezone")
        market_time = event_time.astimezone(timezone)
        if market_time.date().isoformat() != business_date:
            continue
        market_time_key = market_time.isoformat()
        if market_time_key not in expected_time_keys:
            continue
        identity = (symbol, market_time_key)
        if identity in seen:
            duplicates.append(f"{symbol}@{market_time_key}")
            continue
        seen.add(identity)
        source_mode = str(row.get("source_mode") or "")
        if source_mode not in config.allowed_source_modes:
            invalid_sources.append(f"{symbol}@{market_time_key}:{source_mode or 'missing'}")
            continue
        blocked_reason = str(row.get("market_data_blocked_reason") or "")
        if blocked_reason:
            blocked_rows.append(f"{symbol}@{market_time_key}:{blocked_reason}")
            continue
        grouped[symbol].append(row)

    missing_by_symbol: dict[str, list[str]] = {}
    for symbol, rows in grouped.items():
        actual = {
            datetime.fromisoformat(str(row["event_time"]).replace("Z", "+00:00"))
            .astimezone(timezone)
            .isoformat()
            for row in rows
        }
        missing = sorted(expected_time_keys - actual)
        if missing:
            missing_by_symbol[symbol] = missing
        rows.sort(key=lambda row: str(row["event_time"]))

    complete_symbols = [
        symbol
        for symbol, rows in grouped.items()
        if len(rows) == config.expected_bars_per_symbol and symbol not in missing_by_symbol
    ]
    diagnostics = {
        "required_symbol_count": len(symbols),
        "complete_symbol_count": len(complete_symbols),
        "expected_bars_per_symbol": config.expected_bars_per_symbol,
        "accepted_five_minute_bar_count": sum(len(rows) for rows in grouped.values()),
        "duplicate_count": len(duplicates),
        "duplicate_examples": duplicates[:20],
        "invalid_source_count": len(invalid_sources),
        "invalid_source_examples": invalid_sources[:20],
        "blocked_row_count": len(blocked_rows),
        "blocked_row_examples": blocked_rows[:20],
        "incomplete_symbol_count": len(missing_by_symbol),
        "incomplete_symbol_examples": {
            symbol: values[:10] for symbol, values in list(sorted(missing_by_symbol.items()))[:20]
        },
    }
    return grouped, diagnostics


def aggregate_daily_bars(
    grouped: dict[str, list[dict[str, Any]]],
    *,
    business_date: str,
    config: VisualShadowSessionConfig,
) -> list[dict[str, Any]]:
    close_dt = datetime.combine(
        datetime.fromisoformat(f"{business_date}T00:00:00").date(),
        parse_clock(config.regular_close_time),
        tzinfo=ZoneInfo(config.market_timezone),
    ).astimezone(UTC)
    bars: list[dict[str, Any]] = []
    for symbol, rows in grouped.items():
        if len(rows) != config.expected_bars_per_symbol:
            continue
        opens = [Decimal(str(row["open"])) for row in rows]
        highs = [Decimal(str(row["high"])) for row in rows]
        lows = [Decimal(str(row["low"])) for row in rows]
        closes = [Decimal(str(row["close"])) for row in rows]
        volumes = [Decimal(str(row.get("volume") or "0")) for row in rows]
        bars.append(
            {
                "symbol": symbol,
                "market": "US",
                "timeframe": "1d",
                "event_time": close_dt.isoformat().replace("+00:00", "Z"),
                "open": str(opens[0]),
                "high": str(max(highs)),
                "low": str(min(lows)),
                "close": str(closes[-1]),
                "volume": str(sum(volumes, Decimal("0"))),
                "source_mode": "longbridge_sdk_rth_5m_aggregate",
                "source_business_date": business_date,
                "source_bar_count": len(rows),
            }
        )
    return sorted(bars, key=lambda row: row["symbol"])


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def append_session_daily_bars(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    business_date: str,
) -> None:
    existing = read_jsonl(path) if path.exists() else []
    existing_for_date = [
        row for row in existing if str(row.get("source_business_date") or "") == business_date
    ]
    if existing_for_date:
        existing_ids = {bar_id(normalize_bar(row)) for row in existing_for_date}
        incoming_ids = {bar_id(normalize_bar(row)) for row in rows}
        if existing_ids != incoming_ids:
            raise ValueError("visual shadow session daily bar ledger conflicts for business date")
        return
    append_jsonl_rows(path, rows)


def shadow_state_day_match(
    config: VisualShadowSessionConfig,
    rows: list[dict[str, Any]],
    *,
    business_date: str,
) -> tuple[int, int]:
    shadow_config = load_shadow_config(config.shadow_config_path)
    state = load_shadow_state(shadow_config.state_path)
    expected = {stream_key(normalize_bar(row)): bar_id(normalize_bar(row)) for row in rows}
    exact = conflicts = 0
    timezone = ZoneInfo(config.market_timezone)
    for key, expected_id in expected.items():
        stream = state.get("streams", {}).get(key, {})
        matches = []
        for historical in stream.get("history", []):
            event_time = datetime.fromisoformat(str(historical["event_time"]).replace("Z", "+00:00"))
            if event_time.astimezone(timezone).date().isoformat() == business_date:
                matches.append(historical)
        if not matches:
            continue
        if any(bar_id(normalize_bar(row)) == expected_id for row in matches):
            exact += 1
        else:
            conflicts += 1
    return exact, conflicts


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def run_visual_shadow_session(
    config: VisualShadowSessionConfig,
    *,
    business_date: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or now_utc_iso()
    observed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("generated_at must include timezone")
    business_date = business_date or observed.astimezone(ZoneInfo(config.market_timezone)).date().isoformat()
    if datetime.fromisoformat(f"{business_date}T00:00:00").weekday() >= 5:
        raise ValueError("visual shadow session business_date must be a weekday")

    base = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "business_date": business_date,
        "mode": "read_only_sdk_session_shadow",
        "source_mode": "longbridge_sdk_rth_5m_aggregate",
        "hard_boundaries": {
            "order_generation": False,
            "broker_connection": False,
            "real_orders": False,
            "live_execution": False,
        },
    }
    if business_date in read_completed_dates(config.session_ledger_path):
        result = {**base, "status": "already_completed", "session_complete": True}
        result["acceptance_refresh"] = refresh_acceptance_evidence(config, generated_at)
        atomic_write_json(config.session_summary_path, result)
        return result

    grouped, diagnostics = collect_session_rows(config, business_date=business_date)
    session_complete = (
        diagnostics["complete_symbol_count"] == diagnostics["required_symbol_count"]
        and diagnostics["duplicate_count"] == 0
        and diagnostics["invalid_source_count"] == 0
        and diagnostics["blocked_row_count"] == 0
        and diagnostics["incomplete_symbol_count"] == 0
    )
    if not session_complete:
        result = {
            **base,
            "status": "blocked_incomplete_session",
            "session_complete": False,
            "diagnostics": diagnostics,
            "plain_language_result": "当天300只标的的SDK常规时段五分钟数据不完整，本次不计入实时影子验收。",
        }
        atomic_write_json(config.session_summary_path, result)
        append_jsonl(config.session_ledger_path, result)
        result["acceptance_refresh"] = refresh_acceptance_evidence(config, generated_at)
        atomic_write_json(config.session_summary_path, result)
        return result

    daily_bars = aggregate_daily_bars(grouped, business_date=business_date, config=config)
    exact_state_rows, conflicting_state_rows = shadow_state_day_match(
        config,
        daily_bars,
        business_date=business_date,
    )
    if conflicting_state_rows or exact_state_rows not in (0, config.required_symbol_count):
        result = {
            **base,
            "status": "blocked_same_business_date_state_conflict",
            "session_complete": False,
            "exact_state_row_count": exact_state_rows,
            "conflicting_state_row_count": conflicting_state_rows,
            "plain_language_result": "影子状态已存在同交易日但内容不一致，本次不重复写入也不计入验收。",
        }
        atomic_write_json(config.session_summary_path, result)
        append_jsonl(config.session_ledger_path, result)
        return result

    if exact_state_rows == config.required_symbol_count:
        shadow_accepted = 0
        shadow_duplicates = config.required_symbol_count
        completed = True
        existing_equivalent = True
    else:
        shadow_summary = run_visual_strategy_shadow(
            load_shadow_config(config.shadow_config_path),
            bars=daily_bars,
            generated_at=generated_at,
        )
        shadow_accepted = int(shadow_summary.get("accepted_bar_count", 0))
        shadow_duplicates = int(shadow_summary.get("duplicate_bar_or_event_count", 0))
        completed = shadow_accepted == config.required_symbol_count and shadow_duplicates == 0
        existing_equivalent = False
    if completed:
        append_session_daily_bars(
            config.aggregated_daily_bars_path,
            daily_bars,
            business_date=business_date,
        )
    result = {
        **base,
        "status": "completed" if completed else "blocked_shadow_state_not_advanced",
        "session_complete": completed,
        "required_symbol_count": config.required_symbol_count,
        "complete_symbol_count": diagnostics["complete_symbol_count"],
        "expected_bars_per_symbol": config.expected_bars_per_symbol,
        "accepted_five_minute_bar_count": diagnostics["accepted_five_minute_bar_count"],
        "aggregated_daily_bar_count": len(daily_bars),
        "shadow_accepted_daily_bar_count": shadow_accepted,
        "shadow_duplicate_bar_or_event_count": shadow_duplicates,
        "shadow_state_already_equivalent": existing_equivalent,
        "shadow_summary_path": str(load_shadow_config(config.shadow_config_path).summary_path),
        "plain_language_result": (
            "当天300只标的完整SDK行情已形成一晚实时影子证据。"
            if completed
            else "当天行情完整，但影子状态未推进300只标的；本次不计入验收。"
        ),
    }
    atomic_write_json(config.session_summary_path, result)
    append_jsonl(config.session_ledger_path, result)
    result["acceptance_refresh"] = refresh_acceptance_evidence(config, generated_at)
    atomic_write_json(config.session_summary_path, result)
    return result


def refresh_acceptance_evidence(
    config: VisualShadowSessionConfig,
    generated_at: str,
) -> dict[str, Any]:
    if config.acceptance_config_path is None:
        return {"status": "not_configured"}
    from scripts.m15_visual_strategy_acceptance_lib import generate_acceptance_evidence
    from scripts.m15_visual_strategy_acceptance_lib import load_acceptance_config

    acceptance_config = load_acceptance_config(config.acceptance_config_path)
    generate_acceptance_evidence(acceptance_config, generated_at=generated_at)
    return {
        "status": "refreshed",
        "output_path": str(acceptance_config.output_path),
        "machine_candidates_do_not_count_as_reviewed": True,
    }
