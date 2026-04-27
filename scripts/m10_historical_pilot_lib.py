#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data import OhlcvRow, load_ohlcv_csv


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m10_wave_a_historical_pilot.json"
WAVE_A_IDS = ("M10-PA-001", "M10-PA-002", "M10-PA-005", "M10-PA-012")
VISUAL_FIRST_IDS = ("M10-PA-003", "M10-PA-004", "M10-PA-007", "M10-PA-008", "M10-PA-009", "M10-PA-010", "M10-PA-011")
EXCLUDED_IDS = VISUAL_FIRST_IDS + ("M10-PA-013", "M10-PA-014", "M10-PA-015", "M10-PA-006", "M10-PA-016")
ALLOWED_OUTCOMES = ("needs_definition_fix", "needs_visual_review", "continue_testing", "reject_for_now")
NOT_ALLOWED = ("retain", "promote", "live_execution", "broker_connection", "real_orders")
CSV_HEADER = ("symbol", "market", "timeframe", "timestamp", "timezone", "open", "high", "low", "close", "volume")
DATASET_RE = re.compile(
    r"^us_(?P<symbol>[A-Z]+)_(?P<timeframe>1d|5m|15m|1h)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})_(?P<source>[A-Za-z0-9_]+)\.csv$"
)
TIMEFRAME_TO_MINUTES = {"5m": 5, "15m": 15, "1h": 60}
QUANT = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class DataWindow:
    start: date
    end: date
    derive_from: str | None = None


@dataclass(frozen=True, slots=True)
class PilotConfig:
    title: str
    run_id: str
    symbols: tuple[str, ...]
    market: str
    timezone: str
    data_windows: dict[str, DataWindow]
    cache_roots: tuple[Path, ...]
    spec_index_path: Path
    cost_sample_policy_path: Path
    output_dir: Path
    allow_download: bool
    paper_simulated_only: bool


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    symbol: str
    timeframe: str
    status: str
    csv_path: Path | None
    source: str
    lineage: str
    requested_start: date
    requested_end: date
    actual_start: str | None
    actual_end: str | None
    row_count: int
    checksum_sha256: str | None
    deferred_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    strategy_id: str
    symbol: str
    timeframe: str
    direction: str
    signal_index: int
    entry_index: int
    signal_timestamp: datetime
    entry_timestamp: datetime
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    risk_per_share: Decimal
    setup_notes: str


@dataclass(frozen=True, slots=True)
class SimulatedTrade:
    event: CandidateEvent
    exit_timestamp: datetime
    exit_price: Decimal
    exit_reason: str
    gross_r: Decimal
    net_r_by_tier: dict[str, Decimal]
    regime: str


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def load_pilot_config(path: str | Path = DEFAULT_CONFIG_PATH) -> PilotConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    data_windows = {
        timeframe: DataWindow(
            start=date.fromisoformat(window["start"]),
            end=date.fromisoformat(window["end"]),
            derive_from=window.get("derive_from"),
        )
        for timeframe, window in payload["data_windows"].items()
    }
    return PilotConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m10_4_wave_a_pilot"),
        symbols=tuple(payload["symbols"]),
        market=payload.get("market", "US"),
        timezone=payload.get("timezone", "America/New_York"),
        data_windows=data_windows,
        cache_roots=tuple(resolve_repo_path(path) for path in payload["cache_roots"]),
        spec_index_path=resolve_repo_path(payload["spec_index_path"]),
        cost_sample_policy_path=resolve_repo_path(payload["cost_sample_policy_path"]),
        output_dir=resolve_repo_path(payload["output_dir"]),
        allow_download=bool(payload.get("allow_download", False)),
        paper_simulated_only=bool(payload.get("paper_simulated_only", True)),
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_wave_a_specs(spec_index_path: Path) -> list[dict[str, Any]]:
    spec_index = load_json(spec_index_path)
    specs: list[dict[str, Any]] = []
    for item in spec_index.get("specs", []):
        strategy_id = item.get("strategy_id", "")
        if strategy_id not in WAVE_A_IDS:
            continue
        spec_path = M10_DIR / item["spec_json"]
        specs.append(load_json(spec_path))
    return specs


def validate_wave_a_specs(specs: list[dict[str, Any]]) -> None:
    spec_ids = {spec["strategy_id"] for spec in specs}
    if spec_ids != set(WAVE_A_IDS):
        raise ValueError(f"M10.4 requires exact Wave A specs: {sorted(spec_ids)}")
    for spec in specs:
        if spec["strategy_id"] == "M10-PA-012" and spec.get("timeframes") != ["15m", "5m"]:
            raise ValueError("M10-PA-012 must only run on 15m/5m")
        if set(spec.get("not_allowed", [])) != set(NOT_ALLOWED):
            raise ValueError(f"{spec['strategy_id']} not_allowed policy drift")
        if spec.get("allowed_outcomes") != list(ALLOWED_OUTCOMES):
            raise ValueError(f"{spec['strategy_id']} allowed_outcomes policy drift")


def parse_dataset_filename(path: Path) -> dict[str, Any] | None:
    match = DATASET_RE.match(path.name)
    if not match:
        return None
    return {
        "symbol": match.group("symbol"),
        "timeframe": match.group("timeframe"),
        "start": date.fromisoformat(match.group("start")),
        "end": date.fromisoformat(match.group("end")),
        "source": match.group("source"),
    }


def find_dataset_file(
    *,
    symbol: str,
    timeframe: str,
    window: DataWindow,
    cache_roots: Iterable[Path],
) -> Path | None:
    candidates: list[tuple[int, int, Path]] = []
    source_rank = {"longbridge": 0, "yfinance": 1}
    for root in cache_roots:
        if not root.exists():
            continue
        for path in root.rglob(f"us_{symbol}_{timeframe}_*.csv"):
            meta = parse_dataset_filename(path)
            if not meta:
                continue
            if meta["symbol"] != symbol or meta["timeframe"] != timeframe:
                continue
            if meta["start"] <= window.start and meta["end"] >= window.end:
                span_days = (meta["end"] - meta["start"]).days
                candidates.append((source_rank.get(meta["source"], 9), span_days, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2].as_posix()))
    return candidates[0][2]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_record_from_bars(
    *,
    symbol: str,
    timeframe: str,
    window: DataWindow,
    csv_path: Path | None,
    source: str,
    lineage: str,
    bars: list[OhlcvRow],
    deferred_reason: str | None = None,
) -> DatasetRecord:
    return DatasetRecord(
        symbol=symbol,
        timeframe=timeframe,
        status="available" if bars else "data_unavailable_deferred",
        csv_path=csv_path,
        source=source,
        lineage=lineage,
        requested_start=window.start,
        requested_end=window.end,
        actual_start=bars[0].timestamp.isoformat() if bars else None,
        actual_end=bars[-1].timestamp.isoformat() if bars else None,
        row_count=len(bars),
        checksum_sha256=file_sha256(csv_path) if csv_path and csv_path.exists() else None,
        deferred_reason=deferred_reason,
    )


def load_dataset_for_timeframe(
    *,
    symbol: str,
    timeframe: str,
    config: PilotConfig,
) -> tuple[list[OhlcvRow], DatasetRecord]:
    window = config.data_windows[timeframe]
    direct_path = find_dataset_file(symbol=symbol, timeframe=timeframe, window=window, cache_roots=config.cache_roots)
    if direct_path:
        bars = filter_bars_to_window(load_ohlcv_csv(direct_path), window)
        meta = parse_dataset_filename(direct_path) or {}
        return bars, dataset_record_from_bars(
            symbol=symbol,
            timeframe=timeframe,
            window=window,
            csv_path=direct_path,
            source=str(meta.get("source", "local_cache")),
            lineage="native_cache",
            bars=bars,
        )

    if window.derive_from:
        source_window = config.data_windows[window.derive_from]
        source_path = find_dataset_file(
            symbol=symbol,
            timeframe=window.derive_from,
            window=source_window,
            cache_roots=config.cache_roots,
        )
        if source_path:
            source_bars = filter_bars_to_window(load_ohlcv_csv(source_path), source_window)
            derived = aggregate_bars(source_bars, timeframe)
            derived = filter_bars_to_window(derived, window)
            return derived, dataset_record_from_bars(
                symbol=symbol,
                timeframe=timeframe,
                window=window,
                csv_path=source_path,
                source="longbridge",
                lineage=f"derived_from_{window.derive_from}",
                bars=derived,
            )

    return [], dataset_record_from_bars(
        symbol=symbol,
        timeframe=timeframe,
        window=window,
        csv_path=None,
        source="unavailable",
        lineage="data_unavailable_deferred",
        bars=[],
        deferred_reason="no_local_cache_and_download_disabled",
    )


def filter_bars_to_window(bars: list[OhlcvRow], window: DataWindow) -> list[OhlcvRow]:
    return [bar for bar in bars if window.start <= bar.timestamp.date() <= window.end]


def aggregate_bars(bars: list[OhlcvRow], target_timeframe: str) -> list[OhlcvRow]:
    if target_timeframe not in {"15m", "1h"}:
        raise ValueError(f"Unsupported derived timeframe: {target_timeframe}")
    source_minutes = TIMEFRAME_TO_MINUTES.get(bars[0].timeframe if bars else "5m")
    target_minutes = TIMEFRAME_TO_MINUTES[target_timeframe]
    if source_minutes != 5 or target_minutes % source_minutes != 0:
        raise ValueError("M10.4 only derives 15m/1h from 5m source bars")
    chunk_size = target_minutes // source_minutes
    grouped: dict[tuple[str, date], list[OhlcvRow]] = defaultdict(list)
    for bar in bars:
        grouped[(bar.symbol, bar.timestamp.date())].append(bar)
    derived: list[OhlcvRow] = []
    for (_, _), session_bars in sorted(grouped.items(), key=lambda item: item[0]):
        ordered = sorted(session_bars, key=lambda bar: bar.timestamp)
        for index in range(0, len(ordered), chunk_size):
            chunk = ordered[index : index + chunk_size]
            if len(chunk) < chunk_size:
                continue
            derived.append(
                OhlcvRow(
                    symbol=chunk[0].symbol,
                    market=chunk[0].market,
                    timeframe=target_timeframe,
                    timestamp=chunk[0].timestamp,
                    timezone=chunk[0].timezone,
                    open=chunk[0].open,
                    high=max(bar.high for bar in chunk),
                    low=min(bar.low for bar in chunk),
                    close=chunk[-1].close,
                    volume=sum((bar.volume for bar in chunk), Decimal("0")),
                )
            )
    return derived


def run_m10_historical_pilot(config: PilotConfig) -> dict[str, Any]:
    specs = load_wave_a_specs(config.spec_index_path)
    validate_wave_a_specs(specs)
    policy = load_json(config.cost_sample_policy_path)
    tiers = policy["cost_model_policy"]["sensitivity_tiers"]
    sample_gate = policy["sample_gate_policy"]

    config.output_dir.mkdir(parents=True, exist_ok=True)
    data_by_key: dict[tuple[str, str], list[OhlcvRow]] = {}
    inventory: list[DatasetRecord] = []
    required_timeframes = sorted({timeframe for spec in specs for timeframe in spec["timeframes"]})
    for symbol in config.symbols:
        for timeframe in required_timeframes:
            bars, record = load_dataset_for_timeframe(symbol=symbol, timeframe=timeframe, config=config)
            data_by_key[(symbol, timeframe)] = bars
            inventory.append(record)

    strategy_summaries: list[dict[str, Any]] = []
    for spec in specs:
        strategy_dir = config.output_dir / spec["strategy_id"]
        strategy_dir.mkdir(parents=True, exist_ok=True)
        for timeframe in spec["timeframes"]:
            run_result = run_strategy_timeframe(
                spec=spec,
                timeframe=timeframe,
                symbols=config.symbols,
                data_by_key=data_by_key,
                tiers=tiers,
                sample_gate=sample_gate,
                output_dir=strategy_dir / timeframe,
            )
            strategy_summaries.append(run_result)

    data_availability = build_data_availability(config, inventory)
    dataset_inventory = build_dataset_inventory(config, inventory)
    summary = build_pilot_summary(config, data_availability, strategy_summaries)
    write_json(config.output_dir / "m10_4_data_availability.json", data_availability)
    write_json(config.output_dir / "m10_4_dataset_inventory.json", dataset_inventory)
    write_json(config.output_dir / "m10_4_wave_a_pilot_summary.json", summary)
    (config.output_dir / "m10_4_wave_a_pilot_report.md").write_text(build_pilot_report(summary), encoding="utf-8")
    return summary


def run_strategy_timeframe(
    *,
    spec: dict[str, Any],
    timeframe: str,
    symbols: tuple[str, ...],
    data_by_key: dict[tuple[str, str], list[OhlcvRow]],
    tiers: list[dict[str, Any]],
    sample_gate: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    events: list[CandidateEvent] = []
    skip_rows: list[dict[str, Any]] = []
    trades: list[SimulatedTrade] = []
    for symbol in symbols:
        bars = data_by_key.get((symbol, timeframe), [])
        if not bars:
            skip_rows.append(skip_row(spec["strategy_id"], symbol, timeframe, None, "data_unavailable_deferred", "No local dataset resolved."))
            continue
        symbol_events, symbol_skips = detect_events(spec, bars)
        events.extend(symbol_events)
        skip_rows.extend(symbol_skips)
        trades.extend(simulate_trades(symbol_events, bars, tiers))

    write_candidate_events_csv(output_dir / "candidate_events.csv", events, trades)
    write_jsonl(output_dir / "skip_no_trade_ledger.jsonl", skip_rows)
    write_json(output_dir / "source_ledger.json", build_source_ledger(spec))
    write_json(output_dir / "cost_slippage_sensitivity.json", build_cost_sensitivity(events, trades, tiers))
    write_json(output_dir / "per_symbol_breakdown.json", build_group_breakdown(events, trades, key_name="symbol"))
    write_json(output_dir / "per_regime_breakdown.json", build_group_breakdown(events, trades, key_name="regime"))
    (output_dir / "failure_mode_notes.md").write_text(
        build_failure_mode_notes(spec, timeframe, events, skip_rows, trades, sample_gate),
        encoding="utf-8",
    )
    return build_strategy_timeframe_summary(spec, timeframe, events, skip_rows, trades, sample_gate, output_dir)


def detect_events(spec: dict[str, Any], bars: list[OhlcvRow]) -> tuple[list[CandidateEvent], list[dict[str, Any]]]:
    strategy_id = spec["strategy_id"]
    if strategy_id == "M10-PA-001":
        return detect_m10_pa_001(bars, strategy_id)
    if strategy_id == "M10-PA-002":
        return detect_m10_pa_002(bars, strategy_id)
    if strategy_id == "M10-PA-005":
        return detect_m10_pa_005(bars, strategy_id)
    if strategy_id == "M10-PA-012":
        return detect_m10_pa_012(bars, strategy_id)
    raise ValueError(f"Unsupported M10.4 strategy: {strategy_id}")


def detect_m10_pa_001(bars: list[OhlcvRow], strategy_id: str) -> tuple[list[CandidateEvent], list[dict[str, Any]]]:
    events: list[CandidateEvent] = []
    skips: list[dict[str, Any]] = []
    closes = [bar.close for bar in bars]
    for i in range(25, len(bars) - 1):
        sma20 = sum(closes[i - 20 : i], Decimal("0")) / Decimal("20")
        recent = bars[i - 10 : i]
        long_trend = bars[i - 1].close > sma20 and bars[i - 1].close > bars[i - 10].close
        short_trend = bars[i - 1].close < sma20 and bars[i - 1].close < bars[i - 10].close
        if not long_trend and not short_trend:
            if i % 50 == 0:
                skips.append(skip_row(strategy_id, bars[i].symbol, bars[i].timeframe, bars[i].timestamp, "m10_001_no_clear_trend", "No 20-bar directional trend context."))
            continue
        if long_trend:
            counter_bars = sum(1 for j in range(i - 5, i) if bars[j].close < bars[j - 1].close)
            local_lows = sum(1 for j in range(i - 8, i - 1) if bars[j].low < bars[j - 1].low and bars[j].low <= bars[j + 1].low)
            if counter_bars < 2 or local_lows < 2:
                continue
            if bars[i].close <= bars[i - 1].high:
                continue
            stop = min(bar.low for bar in recent)
            event = build_event(strategy_id, bars, i, "long", stop, "trend_pullback_second_entry")
            if event:
                events.append(event)
        if short_trend:
            counter_bars = sum(1 for j in range(i - 5, i) if bars[j].close > bars[j - 1].close)
            local_highs = sum(1 for j in range(i - 8, i - 1) if bars[j].high > bars[j - 1].high and bars[j].high >= bars[j + 1].high)
            if counter_bars < 2 or local_highs < 2:
                continue
            if bars[i].close >= bars[i - 1].low:
                continue
            stop = max(bar.high for bar in recent)
            event = build_event(strategy_id, bars, i, "short", stop, "trend_pullback_second_entry")
            if event:
                events.append(event)
    return events, skips


def detect_m10_pa_002(bars: list[OhlcvRow], strategy_id: str) -> tuple[list[CandidateEvent], list[dict[str, Any]]]:
    events: list[CandidateEvent] = []
    skips: list[dict[str, Any]] = []
    for i in range(20, len(bars) - 3):
        prior = bars[i - 20 : i]
        range_high = max(bar.high for bar in prior)
        range_low = min(bar.low for bar in prior)
        bar = bars[i]
        true_range = bar.high - bar.low
        body = abs(bar.close - bar.open)
        if true_range <= 0:
            continue
        body_ok = body / true_range >= Decimal("0.5")
        close_top = bar.close >= bar.low + true_range * Decimal("0.6667")
        close_bottom = bar.close <= bar.low + true_range * Decimal("0.3333")
        if bar.close > range_high:
            if not body_ok or not close_top:
                skips.append(skip_row(strategy_id, bar.symbol, bar.timeframe, bar.timestamp, "m10_002_weak_breakout_bar", "Upside breakout bar failed body/close-location tests."))
                continue
            confirmation = next((j for j in (i + 1, i + 2) if bars[j].close > range_high), None)
            if confirmation is None:
                skips.append(skip_row(strategy_id, bar.symbol, bar.timeframe, bar.timestamp, "m10_002_no_follow_through", "No upside follow-through close within two bars."))
                continue
            event = build_event(strategy_id, bars, confirmation, "long", bar.low, "breakout_follow_through")
            if event:
                events.append(event)
        elif bar.close < range_low:
            if not body_ok or not close_bottom:
                skips.append(skip_row(strategy_id, bar.symbol, bar.timeframe, bar.timestamp, "m10_002_weak_breakout_bar", "Downside breakout bar failed body/close-location tests."))
                continue
            confirmation = next((j for j in (i + 1, i + 2) if bars[j].close < range_low), None)
            if confirmation is None:
                skips.append(skip_row(strategy_id, bar.symbol, bar.timeframe, bar.timestamp, "m10_002_no_follow_through", "No downside follow-through close within two bars."))
                continue
            event = build_event(strategy_id, bars, confirmation, "short", bar.high, "breakout_follow_through")
            if event:
                events.append(event)
    return events, skips


def detect_m10_pa_005(bars: list[OhlcvRow], strategy_id: str) -> tuple[list[CandidateEvent], list[dict[str, Any]]]:
    events: list[CandidateEvent] = []
    skips: list[dict[str, Any]] = []
    for i in range(20, len(bars) - 4):
        prior = bars[i - 20 : i]
        range_high = max(bar.high for bar in prior)
        range_low = min(bar.low for bar in prior)
        range_height = range_high - range_low
        avg_price = sum((bar.close for bar in prior), Decimal("0")) / Decimal("20")
        if avg_price <= 0 or range_height / avg_price > Decimal("0.12"):
            continue
        breakout = bars[i]
        if breakout.high > range_high:
            confirm = next((j for j in (i + 1, i + 2, i + 3) if bars[j].close < range_high), None)
            if confirm is None:
                skips.append(skip_row(strategy_id, breakout.symbol, breakout.timeframe, breakout.timestamp, "m10_005_breakout_not_failed", "Upside breakout did not close back inside within three bars."))
                continue
            event = build_event(strategy_id, bars, confirm, "short", max(bar.high for bar in bars[i : confirm + 1]), "failed_upside_range_breakout")
            if event:
                events.append(event)
        elif breakout.low < range_low:
            confirm = next((j for j in (i + 1, i + 2, i + 3) if bars[j].close > range_low), None)
            if confirm is None:
                skips.append(skip_row(strategy_id, breakout.symbol, breakout.timeframe, breakout.timestamp, "m10_005_breakout_not_failed", "Downside breakout did not close back inside within three bars."))
                continue
            event = build_event(strategy_id, bars, confirm, "long", min(bar.low for bar in bars[i : confirm + 1]), "failed_downside_range_breakout")
            if event:
                events.append(event)
    return events, skips


def detect_m10_pa_012(bars: list[OhlcvRow], strategy_id: str) -> tuple[list[CandidateEvent], list[dict[str, Any]]]:
    events: list[CandidateEvent] = []
    skips: list[dict[str, Any]] = []
    if bars and bars[0].timeframe not in {"5m", "15m"}:
        return events, [skip_row(strategy_id, bars[0].symbol, bars[0].timeframe, None, "m10_012_invalid_timeframe", "Opening range breakout only supports 5m/15m.")]
    opening_bars_required = 6 if bars and bars[0].timeframe == "5m" else 2
    sessions: dict[date, list[OhlcvRow]] = defaultdict(list)
    for bar in bars:
        sessions[bar.timestamp.date()].append(bar)
    for session_date, session_bars in sessions.items():
        ordered = sorted(session_bars, key=lambda bar: bar.timestamp)
        if len(ordered) <= opening_bars_required + 2:
            skips.append(skip_row(strategy_id, ordered[0].symbol, ordered[0].timeframe, ordered[0].timestamp, "m10_012_incomplete_session", "Not enough bars to define opening range and follow-through."))
            continue
        opening = ordered[:opening_bars_required]
        or_high = max(bar.high for bar in opening)
        or_low = min(bar.low for bar in opening)
        or_height = or_high - or_low
        if or_height <= 0:
            skips.append(skip_row(strategy_id, ordered[0].symbol, ordered[0].timeframe, ordered[0].timestamp, "m10_012_range_too_narrow_for_costs", "Opening range height is zero."))
            continue
        for idx in range(opening_bars_required, len(ordered) - 3):
            bar = ordered[idx]
            true_range = bar.high - bar.low
            body = abs(bar.close - bar.open)
            if true_range <= 0 or body / true_range < Decimal("0.5"):
                continue
            if bar.close > or_high:
                confirm = next((j for j in (idx + 1, idx + 2) if j < len(ordered) and ordered[j].close > or_high), None)
                if confirm is None:
                    continue
                global_index = bars.index(ordered[confirm])
                event = build_event(strategy_id, bars, global_index, "long", min(or_low, bar.low), f"opening_range_breakout_{session_date.isoformat()}")
                if event:
                    events.append(event)
                break
            if bar.close < or_low:
                confirm = next((j for j in (idx + 1, idx + 2) if j < len(ordered) and ordered[j].close < or_low), None)
                if confirm is None:
                    continue
                global_index = bars.index(ordered[confirm])
                event = build_event(strategy_id, bars, global_index, "short", max(or_high, bar.high), f"opening_range_breakout_{session_date.isoformat()}")
                if event:
                    events.append(event)
                break
    return events, skips


def build_event(
    strategy_id: str,
    bars: list[OhlcvRow],
    signal_index: int,
    direction: str,
    stop_price: Decimal,
    setup_notes: str,
) -> CandidateEvent | None:
    entry_index = signal_index + 1
    if entry_index >= len(bars):
        return None
    entry = bars[entry_index]
    risk = entry.open - stop_price if direction == "long" else stop_price - entry.open
    if risk <= 0:
        return None
    target = entry.open + risk * Decimal("2") if direction == "long" else entry.open - risk * Decimal("2")
    return CandidateEvent(
        strategy_id=strategy_id,
        symbol=entry.symbol,
        timeframe=entry.timeframe,
        direction=direction,
        signal_index=signal_index,
        entry_index=entry_index,
        signal_timestamp=bars[signal_index].timestamp,
        entry_timestamp=entry.timestamp,
        entry_price=entry.open,
        stop_price=stop_price,
        target_price=target,
        risk_per_share=risk,
        setup_notes=setup_notes,
    )


def simulate_trades(events: list[CandidateEvent], bars: list[OhlcvRow], tiers: list[dict[str, Any]]) -> list[SimulatedTrade]:
    trades: list[SimulatedTrade] = []
    for event in events:
        exit_price = bars[-1].close
        exit_timestamp = bars[-1].timestamp
        exit_reason = "end_of_data"
        for bar in bars[event.entry_index :]:
            if event.direction == "long":
                stop_hit = bar.low <= event.stop_price
                target_hit = bar.high >= event.target_price
                if stop_hit:
                    exit_price = event.stop_price
                    exit_timestamp = bar.timestamp
                    exit_reason = "stop_hit" if not target_hit else "stop_before_target_same_bar"
                    break
                if target_hit:
                    exit_price = event.target_price
                    exit_timestamp = bar.timestamp
                    exit_reason = "target_hit"
                    break
            else:
                stop_hit = bar.high >= event.stop_price
                target_hit = bar.low <= event.target_price
                if stop_hit:
                    exit_price = event.stop_price
                    exit_timestamp = bar.timestamp
                    exit_reason = "stop_hit" if not target_hit else "stop_before_target_same_bar"
                    break
                if target_hit:
                    exit_price = event.target_price
                    exit_timestamp = bar.timestamp
                    exit_reason = "target_hit"
                    break
        gross_per_share = exit_price - event.entry_price if event.direction == "long" else event.entry_price - exit_price
        gross_r = gross_per_share / event.risk_per_share
        net_r_by_tier = {
            tier["tier"]: quantize_r(gross_r - cost_r(event, exit_price, Decimal(str(tier["slippage_bps"])), Decimal(str(tier["fee_per_order"]))))
            for tier in tiers
        }
        trades.append(
            SimulatedTrade(
                event=event,
                exit_timestamp=exit_timestamp,
                exit_price=exit_price,
                exit_reason=exit_reason,
                gross_r=quantize_r(gross_r),
                net_r_by_tier=net_r_by_tier,
                regime=classify_regime(bars, event.signal_index),
            )
        )
    return trades


def cost_r(event: CandidateEvent, exit_price: Decimal, slippage_bps: Decimal, fee_per_order: Decimal) -> Decimal:
    bps = Decimal("10000")
    price_cost = (event.entry_price + exit_price) * slippage_bps / bps
    fee_cost = fee_per_order * Decimal("2")
    return (price_cost + fee_cost) / event.risk_per_share


def classify_regime(bars: list[OhlcvRow], index: int) -> str:
    if index < 60:
        return "insufficient_context"
    sma20 = sum((bar.close for bar in bars[index - 20 : index]), Decimal("0")) / Decimal("20")
    sma50 = sum((bar.close for bar in bars[index - 50 : index]), Decimal("0")) / Decimal("50")
    close = bars[index].close
    if close > sma20 > sma50:
        return "trend_up"
    if close < sma20 < sma50:
        return "trend_down"
    return "range_or_mixed"


def quantize_r(value: Decimal) -> Decimal:
    return value.quantize(QUANT, rounding=ROUND_HALF_UP)


def skip_row(strategy_id: str, symbol: str, timeframe: str, timestamp: datetime | None, skip_code: str, reason: str) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": timestamp.isoformat() if timestamp else None,
        "skip_code": skip_code,
        "reason": reason,
    }


def build_source_ledger(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "m10.4.source-ledger.v1",
        "strategy_id": spec["strategy_id"],
        "source_ledger_ref": spec["source_ledger_ref"],
        "source_refs": spec["source_refs"],
        "supporting_rules": spec.get("supporting_rules", []),
        "legacy_policy": "PA-SC and SF artifacts are forbidden as M10.4 signal sources",
    }


def build_cost_sensitivity(events: list[CandidateEvent], trades: list[SimulatedTrade], tiers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "m10.4.cost-slippage-sensitivity.v1",
        "candidate_event_count": len(events),
        "executed_trade_count": len(trades),
        "tiers": [
            {
                "tier": tier["tier"],
                "slippage_bps": tier["slippage_bps"],
                "fee_per_order": tier["fee_per_order"],
                "total_r": decimal_to_str(sum((trade.net_r_by_tier[tier["tier"]] for trade in trades), Decimal("0"))),
                "mean_r": decimal_to_str(mean_decimal([trade.net_r_by_tier[tier["tier"]] for trade in trades])),
                "win_rate": win_rate([trade.net_r_by_tier[tier["tier"]] for trade in trades]),
            }
            for tier in tiers
        ],
    }


def build_group_breakdown(events: list[CandidateEvent], trades: list[SimulatedTrade], *, key_name: str) -> dict[str, Any]:
    grouped_events: Counter[str] = Counter()
    grouped_trades: dict[str, list[SimulatedTrade]] = defaultdict(list)
    if key_name == "regime":
        for trade in trades:
            grouped_events[trade.regime] += 1
    else:
        for event in events:
            grouped_events[getattr(event, key_name)] += 1
    for trade in trades:
        key = trade.regime if key_name == "regime" else getattr(trade.event, key_name)
        grouped_trades[key].append(trade)
    rows = []
    for key in sorted(set(grouped_events) | set(grouped_trades)):
        tier_values = [trade.net_r_by_tier.get("baseline", Decimal("0")) for trade in grouped_trades[key]]
        rows.append(
            {
                key_name: key,
                "candidate_event_count": grouped_events.get(key, 0),
                "executed_trade_count": len(grouped_trades[key]),
                "baseline_total_r": decimal_to_str(sum(tier_values, Decimal("0"))),
                "baseline_mean_r": decimal_to_str(mean_decimal(tier_values)),
                "baseline_win_rate": win_rate(tier_values),
            }
        )
    return {"schema_version": f"m10.4.per-{key_name}-breakdown.v1", "rows": rows}


def build_failure_mode_notes(
    spec: dict[str, Any],
    timeframe: str,
    events: list[CandidateEvent],
    skip_rows: list[dict[str, Any]],
    trades: list[SimulatedTrade],
    sample_gate: dict[str, Any],
) -> str:
    skip_counts = Counter(row["skip_code"] for row in skip_rows)
    outcome = outcome_for(events, trades, sample_gate)
    lines = [
        f"# {spec['strategy_id']} {timeframe} Failure Mode Notes",
        "",
        f"- candidate_event_count: `{len(events)}`",
        f"- executed_trade_count: `{len(trades)}`",
        f"- outcome: `{outcome}`",
        "- This is a paper/simulated pilot artifact, not a profitability claim.",
        "",
        "## Skip Counts",
        "",
    ]
    if skip_counts:
        lines.extend(f"- `{code}`: {count}" for code, count in sorted(skip_counts.items()))
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- If event counts are low, prefer `needs_definition_fix` or `continue_testing` rather than interpreting performance.",
            "- If OHLCV approximation misses source context, route to `needs_visual_review`.",
            "- `retain/promote/live` conclusions are forbidden in M10.4.",
            "",
        ]
    )
    return "\n".join(lines)


def build_strategy_timeframe_summary(
    spec: dict[str, Any],
    timeframe: str,
    events: list[CandidateEvent],
    skip_rows: list[dict[str, Any]],
    trades: list[SimulatedTrade],
    sample_gate: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    return {
        "strategy_id": spec["strategy_id"],
        "title": spec["title"],
        "timeframe": timeframe,
        "candidate_event_count": len(events),
        "executed_trade_count": len(trades),
        "skip_no_trade_count": len(skip_rows),
        "sample_gate": {
            "candidate_events_required": sample_gate["minimum_candidate_events_per_strategy_timeframe"],
            "executed_trades_required": sample_gate["minimum_executed_trades_after_skips_per_strategy_timeframe"],
            "passed": sample_gate_passed(events, trades, sample_gate),
        },
        "outcome": outcome_for(events, trades, sample_gate),
        "allowed_outcomes": list(ALLOWED_OUTCOMES),
        "not_allowed": list(NOT_ALLOWED),
        "artifacts": {
            "candidate_events": project_path(output_dir / "candidate_events.csv"),
            "skip_no_trade_ledger": project_path(output_dir / "skip_no_trade_ledger.jsonl"),
            "source_ledger": project_path(output_dir / "source_ledger.json"),
            "cost_slippage_sensitivity": project_path(output_dir / "cost_slippage_sensitivity.json"),
            "per_symbol_breakdown": project_path(output_dir / "per_symbol_breakdown.json"),
            "per_regime_breakdown": project_path(output_dir / "per_regime_breakdown.json"),
            "failure_mode_notes": project_path(output_dir / "failure_mode_notes.md"),
        },
    }


def sample_gate_passed(events: list[CandidateEvent], trades: list[SimulatedTrade], sample_gate: dict[str, Any]) -> bool:
    return (
        len(events) >= int(sample_gate["minimum_candidate_events_per_strategy_timeframe"])
        and len(trades) >= int(sample_gate["minimum_executed_trades_after_skips_per_strategy_timeframe"])
    )


def outcome_for(events: list[CandidateEvent], trades: list[SimulatedTrade], sample_gate: dict[str, Any]) -> str:
    if not events:
        return "needs_definition_fix"
    if not sample_gate_passed(events, trades, sample_gate):
        return "continue_testing"
    return "continue_testing"


def build_data_availability(config: PilotConfig, inventory: list[DatasetRecord]) -> dict[str, Any]:
    return {
        "schema_version": "m10.4.data-availability.v1",
        "run_id": config.run_id,
        "cache_roots": [path.as_posix() for path in config.cache_roots],
        "allow_download": config.allow_download,
        "records": [dataset_record_to_json(record) for record in inventory],
        "available_count": sum(1 for record in inventory if record.status == "available"),
        "deferred_count": sum(1 for record in inventory if record.status != "available"),
    }


def build_dataset_inventory(config: PilotConfig, inventory: list[DatasetRecord]) -> dict[str, Any]:
    return {
        "schema_version": "m10.4.dataset-inventory.v1",
        "run_id": config.run_id,
        "daily_default_window": {
            "start": config.data_windows["1d"].start.isoformat(),
            "end": config.data_windows["1d"].end.isoformat(),
        },
        "records": [dataset_record_to_json(record) for record in inventory],
    }


def build_pilot_summary(config: PilotConfig, data_availability: dict[str, Any], strategy_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "m10.4.wave-a-historical-pilot-summary.v1",
        "run_id": config.run_id,
        "title": config.title,
        "paper_simulated_only": True,
        "broker_connection": False,
        "live_execution": False,
        "real_orders": False,
        "retain_or_promote_allowed": False,
        "wave_a_strategy_ids": list(WAVE_A_IDS),
        "excluded_strategy_ids": list(EXCLUDED_IDS),
        "data_availability": {
            "available_count": data_availability["available_count"],
            "deferred_count": data_availability["deferred_count"],
        },
        "strategy_timeframe_results": strategy_summaries,
        "allowed_outcomes": list(ALLOWED_OUTCOMES),
        "not_allowed": list(NOT_ALLOWED),
        "m10_5_handoff": "Only after reviewing M10.4 pilot quality, design read-only observation; no broker or orders.",
    }


def build_pilot_report(summary: dict[str, Any]) -> str:
    rows = [
        "| strategy | timeframe | candidates | trades | sample gate | outcome |",
        "|---|---|---:|---:|---|---|",
    ]
    for item in summary["strategy_timeframe_results"]:
        rows.append(
            "| {strategy} | {timeframe} | {candidates} | {trades} | {gate} | `{outcome}` |".format(
                strategy=item["strategy_id"],
                timeframe=item["timeframe"],
                candidates=item["candidate_event_count"],
                trades=item["executed_trade_count"],
                gate="pass" if item["sample_gate"]["passed"] else "not_met",
                outcome=item["outcome"],
            )
        )
    return "\n".join(
        [
            "# M10.4 Wave A Historical Backtest Pilot",
            "",
            "## Summary",
            "",
            "- This pilot validates M10.3 executable specs and output plumbing.",
            "- It remains paper / simulated only.",
            "- It does not prove profitability and does not allow retain/promote/live conclusions.",
            "",
            "## Results",
            "",
            *rows,
            "",
            "## Boundary",
            "",
            "- No broker connection.",
            "- No real account.",
            "- No live execution.",
            "- No real orders.",
            "",
        ]
    )


def dataset_record_to_json(record: DatasetRecord) -> dict[str, Any]:
    return {
        "symbol": record.symbol,
        "timeframe": record.timeframe,
        "status": record.status,
        "csv_path": record.csv_path.as_posix() if record.csv_path else None,
        "source": record.source,
        "lineage": record.lineage,
        "requested_start": record.requested_start.isoformat(),
        "requested_end": record.requested_end.isoformat(),
        "actual_start": record.actual_start,
        "actual_end": record.actual_end,
        "row_count": record.row_count,
        "checksum_sha256": record.checksum_sha256,
        "deferred_reason": record.deferred_reason,
    }


def write_candidate_events_csv(path: Path, events: list[CandidateEvent], trades: list[SimulatedTrade]) -> None:
    trade_by_key = {(trade.event.strategy_id, trade.event.symbol, trade.event.timeframe, trade.event.signal_timestamp): trade for trade in trades}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "strategy_id",
            "symbol",
            "timeframe",
            "direction",
            "signal_timestamp",
            "entry_timestamp",
            "entry_price",
            "stop_price",
            "target_price",
            "risk_per_share",
            "exit_timestamp",
            "exit_price",
            "exit_reason",
            "gross_r",
            "baseline_net_r",
            "setup_notes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for event in events:
            trade = trade_by_key.get((event.strategy_id, event.symbol, event.timeframe, event.signal_timestamp))
            writer.writerow(
                {
                    "strategy_id": event.strategy_id,
                    "symbol": event.symbol,
                    "timeframe": event.timeframe,
                    "direction": event.direction,
                    "signal_timestamp": event.signal_timestamp.isoformat(),
                    "entry_timestamp": event.entry_timestamp.isoformat(),
                    "entry_price": str(event.entry_price),
                    "stop_price": str(event.stop_price),
                    "target_price": str(event.target_price),
                    "risk_per_share": str(event.risk_per_share),
                    "exit_timestamp": trade.exit_timestamp.isoformat() if trade else "",
                    "exit_price": str(trade.exit_price) if trade else "",
                    "exit_reason": trade.exit_reason if trade else "",
                    "gross_r": str(trade.gross_r) if trade else "",
                    "baseline_net_r": str(trade.net_r_by_tier.get("baseline", "")) if trade else "",
                    "setup_notes": event.setup_notes,
                }
            )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def mean_decimal(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


def win_rate(values: list[Decimal]) -> str:
    if not values:
        return "0"
    wins = sum(1 for value in values if value > 0)
    return str(quantize_r(Decimal(wins) / Decimal(len(values))))


def decimal_to_str(value: Decimal) -> str:
    return str(quantize_r(value))


def project_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()
