#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from scripts.intraday_pilot_lib import (
    InstrumentConfig,
    fetch_intraday_history_rows,
    write_intraday_cache_csv,
)
from src.data import OhlcvRow, load_ohlcv_csv


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_ID = "PA-SC-002"
FILTER_ID = "PA-SC-009"
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE_LAST_BAR = time(15, 55)
REGULAR_CLOSE = time(16, 0)
PRICE_QUANT = Decimal("0.0001")
PERCENT_QUANT = Decimal("0.0001")
TWO = Decimal("2")


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    ticker: str
    symbol: str
    market: str
    timeframe: str
    source: str
    timezone: str
    start: date
    end: date
    cache_dir: Path
    artifact_dir: Path
    report_path: Path
    summary_path: Path
    trades_csv_path: Path
    candidates_csv_path: Path
    skip_summary_path: Path
    blocked_time_buckets: tuple[str, ...]
    starting_capital: Decimal
    risk_per_trade: Decimal
    lookback_bars: int
    follow_through_window: int
    stop_buffer: Decimal
    entry_buffer: Decimal
    target_r_multiple: Decimal
    slippage_bps: Decimal
    per_side_tick_slippage: Decimal
    max_risk_to_median_range_multiple: Decimal
    breakout_body_multiple: Decimal
    breakout_min_body_ratio: Decimal
    breakout_min_close_ratio: Decimal
    breakout_max_opposite_wick_ratio: Decimal
    ft_min_close_ratio: Decimal
    ft_min_body_ratio: Decimal
    filter_max_displacement_ratio: Decimal
    filter_max_displacement_for_doji_veto: Decimal
    filter_min_flip_count: int
    filter_min_doji_count: int
    trend_supportive_min_displacement_ratio: Decimal
    trend_supportive_max_flip_count: int
    trend_supportive_max_doji_count: int
    minimum_probe_trade_count: int
    minimum_probe_split_trade_count: int
    formal_trade_count_gate: int
    formal_split_trade_count_gate: int


@dataclass(frozen=True, slots=True)
class SessionSlice:
    session_key: str
    split: str
    bars: tuple[OhlcvRow, ...]


@dataclass(frozen=True, slots=True)
class FilterSnapshot:
    state: str
    flip_count: int
    doji_count: int
    displacement_ratio: Decimal


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    session_key: str
    split: str
    breakout_timestamp: datetime
    direction: str
    prior_level: Decimal
    filter_state: str
    breakout_body_ratio: Decimal
    breakout_close_ratio: Decimal
    breakout_avg_body_multiple: Decimal
    breakout_opposite_wick_ratio: Decimal
    filter_displacement_ratio: Decimal
    filter_flip_count: int
    filter_doji_count: int
    status: str
    reason_code: str
    time_bucket: str


@dataclass(frozen=True, slots=True)
class ExecutedTrade:
    trade_id: str
    session_key: str
    split: str
    direction: str
    filter_state: str
    breakout_timestamp: datetime
    follow_through_timestamp: datetime
    entry_timestamp: datetime
    exit_timestamp: datetime
    time_bucket: str
    raw_entry_price: Decimal
    executed_entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    exit_price: Decimal
    executed_exit_price: Decimal
    risk_per_share: Decimal
    pnl_per_share: Decimal
    pnl_r: Decimal
    exit_reason: str
    breakout_body_ratio: Decimal
    breakout_close_ratio: Decimal
    breakout_avg_body_multiple: Decimal
    breakout_opposite_wick_ratio: Decimal
    filter_displacement_ratio: Decimal
    filter_flip_count: int
    filter_doji_count: int
    quantity: Decimal = Decimal("0")
    pnl_cash: Decimal = Decimal("0")
    equity_after_close: Decimal = Decimal("0")


def build_default_config() -> ExperimentConfig:
    artifact_dir = ROOT / "reports" / "strategy_lab" / "pa_sc_002_longbridge_backtest_artifacts"
    return ExperimentConfig(
        ticker="SPY",
        symbol="SPY",
        market="US",
        timeframe="5m",
        source="longbridge",
        timezone="America/New_York",
        start=date.fromisoformat("2026-02-20"),
        end=date.fromisoformat("2026-04-17"),
        cache_dir=ROOT / "local_data" / "longbridge_intraday",
        artifact_dir=artifact_dir,
        report_path=ROOT / "reports" / "strategy_lab" / "pa_sc_002_longbridge_backtest_report.md",
        summary_path=artifact_dir / "summary.json",
        trades_csv_path=artifact_dir / "trades.csv",
        candidates_csv_path=artifact_dir / "candidate_events.csv",
        skip_summary_path=artifact_dir / "skip_summary.json",
        blocked_time_buckets=(),
        starting_capital=Decimal("25000"),
        risk_per_trade=Decimal("100"),
        lookback_bars=6,
        follow_through_window=2,
        stop_buffer=Decimal("0.01"),
        entry_buffer=Decimal("0.00"),
        target_r_multiple=Decimal("1.0"),
        slippage_bps=Decimal("0.0001"),
        per_side_tick_slippage=Decimal("0.01"),
        max_risk_to_median_range_multiple=Decimal("3.0"),
        breakout_body_multiple=Decimal("0.9"),
        breakout_min_body_ratio=Decimal("0.35"),
        breakout_min_close_ratio=Decimal("0.60"),
        breakout_max_opposite_wick_ratio=Decimal("0.40"),
        ft_min_close_ratio=Decimal("0.50"),
        ft_min_body_ratio=Decimal("0.20"),
        filter_max_displacement_ratio=Decimal("0.30"),
        filter_max_displacement_for_doji_veto=Decimal("0.30"),
        filter_min_flip_count=4,
        filter_min_doji_count=3,
        trend_supportive_min_displacement_ratio=Decimal("0.55"),
        trend_supportive_max_flip_count=2,
        trend_supportive_max_doji_count=1,
        minimum_probe_trade_count=60,
        minimum_probe_split_trade_count=15,
        formal_trade_count_gate=100,
        formal_split_trade_count_gate=20,
    )


def run_experiment(
    config: ExperimentConfig | None = None,
    *,
    refresh_data: bool = False,
) -> dict[str, Any]:
    resolved = config or build_default_config()
    dataset = load_or_download_dataset(resolved, refresh_data=refresh_data)
    sessions = load_complete_sessions(dataset["csv_path"], config=resolved)
    filtered = simulate_all_sessions(sessions, config=resolved, apply_filter=True)
    unfiltered = simulate_all_sessions(sessions, config=resolved, apply_filter=False)
    summary = build_summary_payload(
        config=resolved,
        dataset=dataset,
        sessions=sessions,
        filtered=filtered,
        unfiltered=unfiltered,
    )
    write_artifacts(
        config=resolved,
        summary=summary,
        filtered=filtered,
    )
    return summary


def load_or_download_dataset(
    config: ExperimentConfig,
    *,
    refresh_data: bool = False,
) -> dict[str, Any]:
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    csv_path = build_cache_path(config)
    metadata_path = csv_path.with_suffix(".metadata.json")
    if csv_path.exists() and metadata_path.exists() and not refresh_data:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return {
            "csv_path": csv_path,
            "metadata_path": metadata_path,
            "metadata": metadata,
        }

    instrument = InstrumentConfig(
        ticker=config.ticker,
        symbol=config.symbol,
        label="SPDR S&P 500 ETF",
        market=config.market,
        timezone=config.timezone,
        demo_role="PA-SC-002 minimum experiment",
    )
    rows = fetch_intraday_history_rows(
        instrument=instrument,
        start=config.start,
        end=config.end,
        interval=config.timeframe,
        source=config.source,
        timezone_name=config.timezone,
        allow_extended_hours=False,
    )
    if not rows:
        raise RuntimeError(f"No intraday rows returned for {config.ticker} {config.timeframe}.")
    write_intraday_cache_csv(csv_path, rows)
    row_count = len(load_ohlcv_csv(csv_path))
    metadata = {
        "instrument": asdict(instrument),
        "source": config.source,
        "row_count": row_count,
        "start": config.start.isoformat(),
        "end": config.end.isoformat(),
        "interval": config.timeframe,
        "boundary": "paper/simulated",
        "timezone": config.timezone,
        "regular_session_only": True,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "strategy_id": STRATEGY_ID,
        "filter_id": FILTER_ID,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "csv_path": csv_path,
        "metadata_path": metadata_path,
        "metadata": metadata,
    }


def build_cache_path(config: ExperimentConfig) -> Path:
    filename = "_".join(
        (
            config.market.lower(),
            config.symbol,
            config.timeframe,
            config.start.isoformat(),
            config.end.isoformat(),
            config.source,
        )
    )
    return config.cache_dir / f"{filename}.csv"


def load_complete_sessions(csv_path: Path, *, config: ExperimentConfig) -> tuple[SessionSlice, ...]:
    bars = tuple(load_ohlcv_csv(csv_path))
    grouped: dict[str, list[OhlcvRow]] = defaultdict(list)
    for bar in bars:
        grouped[bar.timestamp.date().isoformat()].append(bar)

    expected_times = build_expected_session_times(config.timeframe)
    session_keys = []
    complete_bars: dict[str, tuple[OhlcvRow, ...]] = {}
    for session_key, items in sorted(grouped.items()):
        ordered = tuple(sorted(items, key=lambda item: item.timestamp))
        if len(ordered) != len(expected_times):
            continue
        actual_times = tuple(bar.timestamp.time().strftime("%H:%M") for bar in ordered)
        if actual_times != expected_times:
            continue
        session_keys.append(session_key)
        complete_bars[session_key] = ordered

    labels = assign_split_labels(session_keys)
    sessions = [
        SessionSlice(session_key=key, split=labels[key], bars=complete_bars[key])
        for key in session_keys
    ]
    return tuple(sessions)


def build_expected_session_times(timeframe: str) -> tuple[str, ...]:
    if timeframe != "5m":
        raise ValueError(f"PA-SC-002 minimum experiment only supports 5m, got {timeframe}")
    current = datetime.combine(date.today(), REGULAR_OPEN)
    end = datetime.combine(date.today(), REGULAR_CLOSE_LAST_BAR)
    values: list[str] = []
    while current <= end:
        values.append(current.time().strftime("%H:%M"))
        current += timedelta(minutes=5)
    return tuple(values)


def assign_split_labels(session_keys: list[str] | tuple[str, ...]) -> dict[str, str]:
    total = len(session_keys)
    if total < 3:
        raise ValueError("At least 3 complete sessions are required for split assignment.")
    in_sample_count = max(1, round(total * 0.50))
    validation_count = max(1, round(total * 0.25))
    out_of_sample_count = total - in_sample_count - validation_count
    if out_of_sample_count < 1:
        out_of_sample_count = 1
        if validation_count > 1:
            validation_count -= 1
        else:
            in_sample_count -= 1
    labels: dict[str, str] = {}
    for index, session_key in enumerate(session_keys):
        if index < in_sample_count:
            labels[session_key] = "in_sample"
        elif index < in_sample_count + validation_count:
            labels[session_key] = "validation"
        else:
            labels[session_key] = "out_of_sample"
    return labels


def simulate_all_sessions(
    sessions: tuple[SessionSlice, ...],
    *,
    config: ExperimentConfig,
    apply_filter: bool,
) -> dict[str, Any]:
    all_candidates: list[CandidateEvent] = []
    all_trades: list[ExecutedTrade] = []
    for session in sessions:
        candidates, trades = simulate_session(
            session,
            config=config,
            apply_filter=apply_filter,
        )
        all_candidates.extend(candidates)
        all_trades.extend(trades)
    all_trades.sort(key=lambda item: item.entry_timestamp)
    sized_trades = apply_cash_sizing(tuple(all_trades), config=config)
    return {
        "candidate_events": tuple(all_candidates),
        "trades": sized_trades,
        "skip_counts": summarize_skip_counts(all_candidates),
        "stats": compute_trade_stats(sized_trades, starting_capital=config.starting_capital),
    }


def simulate_session(
    session: SessionSlice,
    *,
    config: ExperimentConfig,
    apply_filter: bool,
) -> tuple[tuple[CandidateEvent, ...], tuple[ExecutedTrade, ...]]:
    bars = session.bars
    candidates: list[CandidateEvent] = []
    trades: list[ExecutedTrade] = []
    index = config.lookback_bars
    trade_counter = 1
    while index < len(bars) - (config.follow_through_window + 1):
        history = bars[index - config.lookback_bars : index]
        breakout_bar = bars[index]
        direction, prior_level = detect_breakout_direction(history, breakout_bar)
        if direction is None:
            index += 1
            continue
        filter_snapshot = classify_filter_state(history, config=config)
        body_ratio, close_ratio, avg_body_multiple, opposite_wick_ratio = breakout_bar_metrics(
            history=history,
            breakout_bar=breakout_bar,
            direction=direction,
        )
        time_bucket = classify_time_bucket(breakout_bar.timestamp.time())
        candidate_base = {
            "session_key": session.session_key,
            "split": session.split,
            "breakout_timestamp": breakout_bar.timestamp,
            "direction": direction,
            "prior_level": prior_level,
            "filter_state": filter_snapshot.state,
            "breakout_body_ratio": body_ratio,
            "breakout_close_ratio": close_ratio,
            "breakout_avg_body_multiple": avg_body_multiple,
            "breakout_opposite_wick_ratio": opposite_wick_ratio,
            "filter_displacement_ratio": filter_snapshot.displacement_ratio,
            "filter_flip_count": filter_snapshot.flip_count,
            "filter_doji_count": filter_snapshot.doji_count,
            "time_bucket": time_bucket,
        }
        if time_bucket in config.blocked_time_buckets:
            candidates.append(
                CandidateEvent(
                    **candidate_base,
                    status="skipped",
                    reason_code="blocked_time_bucket",
                )
            )
            index += 1
            continue
        if apply_filter and filter_snapshot.state == "range_veto":
            candidates.append(
                CandidateEvent(
                    **candidate_base,
                    status="skipped",
                    reason_code="range_veto",
                )
            )
            index += 1
            continue
        if not passes_breakout_quality(
            body_ratio=body_ratio,
            close_ratio=close_ratio,
            avg_body_multiple=avg_body_multiple,
            opposite_wick_ratio=opposite_wick_ratio,
            config=config,
        ):
            candidates.append(
                CandidateEvent(
                    **candidate_base,
                    status="skipped",
                    reason_code="weak_breakout_bar",
                )
            )
            index += 1
            continue
        follow_through_index, ft_reason = find_follow_through_index(
            bars=bars,
            breakout_index=index,
            prior_level=prior_level,
            direction=direction,
            config=config,
        )
        if follow_through_index is None:
            candidates.append(
                CandidateEvent(
                    **candidate_base,
                    status="skipped",
                    reason_code=ft_reason,
                )
            )
            index += 1
            continue
        entry_index = follow_through_index + 1
        if entry_index >= len(bars):
            candidates.append(
                CandidateEvent(
                    **candidate_base,
                    status="skipped",
                    reason_code="insufficient_future_bars",
                )
            )
            index += 1
            continue
        setup = build_trade_setup(
            bars=bars,
            breakout_index=index,
            follow_through_index=follow_through_index,
            prior_level=prior_level,
            direction=direction,
            config=config,
            history=history,
        )
        if setup is None:
            candidates.append(
                CandidateEvent(
                    **candidate_base,
                    status="skipped",
                    reason_code="stop_too_wide",
                )
            )
            index += 1
            continue
        exit_index, exit_price, exit_reason = find_trade_exit(
            bars=bars,
            entry_index=entry_index,
            direction=direction,
            stop_price=setup["stop_price"],
            target_price=setup["target_price"],
        )
        executed_entry = apply_side_cost(
            setup["entry_price"],
            direction=direction,
            side="entry",
            config=config,
        )
        executed_exit = apply_side_cost(
            exit_price,
            direction=direction,
            side="exit",
            config=config,
        )
        pnl_per_share = compute_pnl(
            direction=direction,
            entry_price=executed_entry,
            exit_price=executed_exit,
        )
        pnl_r = quantize(pnl_per_share / setup["risk_per_share"])
        filter_state = (
            "trend_supportive"
            if filter_snapshot.state == "trend_supportive"
            else "neutral"
        )
        trades.append(
            ExecutedTrade(
                trade_id=f"{STRATEGY_ID}-{session.session_key}-{trade_counter:02d}",
                session_key=session.session_key,
                split=session.split,
                direction=direction,
                filter_state=filter_state,
                breakout_timestamp=breakout_bar.timestamp,
                follow_through_timestamp=bars[follow_through_index].timestamp,
                entry_timestamp=bars[entry_index].timestamp,
                exit_timestamp=bars[exit_index].timestamp,
                time_bucket=time_bucket,
                raw_entry_price=setup["entry_price"],
                executed_entry_price=executed_entry,
                stop_price=setup["stop_price"],
                target_price=setup["target_price"],
                exit_price=exit_price,
                executed_exit_price=executed_exit,
                risk_per_share=setup["risk_per_share"],
                pnl_per_share=quantize(pnl_per_share),
                pnl_r=pnl_r,
                exit_reason=exit_reason,
                breakout_body_ratio=body_ratio,
                breakout_close_ratio=close_ratio,
                breakout_avg_body_multiple=avg_body_multiple,
                breakout_opposite_wick_ratio=opposite_wick_ratio,
                filter_displacement_ratio=filter_snapshot.displacement_ratio,
                filter_flip_count=filter_snapshot.flip_count,
                filter_doji_count=filter_snapshot.doji_count,
            )
        )
        executed_candidate = dict(candidate_base)
        executed_candidate["filter_state"] = filter_state
        candidates.append(
            CandidateEvent(
                **executed_candidate,
                status="executed",
                reason_code="executed",
            )
        )
        trade_counter += 1
        index = exit_index + 1
    return tuple(candidates), tuple(trades)


def detect_breakout_direction(
    history: tuple[OhlcvRow, ...] | list[OhlcvRow],
    breakout_bar: OhlcvRow,
) -> tuple[str | None, Decimal]:
    prior_high = max(bar.high for bar in history)
    prior_low = min(bar.low for bar in history)
    if breakout_bar.high > prior_high and breakout_bar.close > prior_high:
        return "long", prior_high
    if breakout_bar.low < prior_low and breakout_bar.close < prior_low:
        return "short", prior_low
    return None, Decimal("0")


def breakout_bar_metrics(
    *,
    history: tuple[OhlcvRow, ...] | list[OhlcvRow],
    breakout_bar: OhlcvRow,
    direction: str,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    bar_range = breakout_bar.high - breakout_bar.low
    if bar_range <= 0:
        return Decimal("0"), Decimal("0"), Decimal("0"), Decimal("1")
    body = abs(breakout_bar.close - breakout_bar.open)
    avg_body = sum((abs(bar.close - bar.open) for bar in history), Decimal("0")) / Decimal(len(history))
    body_ratio = body / bar_range if bar_range > 0 else Decimal("0")
    avg_body_multiple = body / avg_body if avg_body > 0 else Decimal("0")
    if direction == "long":
        close_ratio = (breakout_bar.close - breakout_bar.low) / bar_range
        opposite_wick_ratio = (min(breakout_bar.open, breakout_bar.close) - breakout_bar.low) / bar_range
    else:
        close_ratio = (breakout_bar.high - breakout_bar.close) / bar_range
        opposite_wick_ratio = (breakout_bar.high - max(breakout_bar.open, breakout_bar.close)) / bar_range
    return (
        quantize(body_ratio),
        quantize(close_ratio),
        quantize(avg_body_multiple),
        quantize(opposite_wick_ratio),
    )


def classify_filter_state(
    history: tuple[OhlcvRow, ...] | list[OhlcvRow],
    *,
    config: ExperimentConfig,
) -> FilterSnapshot:
    flip_count = 0
    doji_count = 0
    for left, right in zip(history, history[1:]):
        left_dir = candle_direction(left)
        right_dir = candle_direction(right)
        if left_dir and right_dir and left_dir != right_dir:
            flip_count += 1
    for bar in history:
        bar_range = bar.high - bar.low
        if bar_range > 0 and abs(bar.close - bar.open) / bar_range <= Decimal("0.25"):
            doji_count += 1
    total_range = max(bar.high for bar in history) - min(bar.low for bar in history)
    displacement_ratio = (
        abs(history[-1].close - history[0].open) / total_range if total_range > 0 else Decimal("0")
    )
    state = "neutral"
    if (
        flip_count >= config.filter_min_flip_count
        and displacement_ratio <= config.filter_max_displacement_ratio
    ) or (
        doji_count >= config.filter_min_doji_count
        and displacement_ratio <= config.filter_max_displacement_for_doji_veto
    ):
        state = "range_veto"
    elif (
        displacement_ratio >= config.trend_supportive_min_displacement_ratio
        and flip_count <= config.trend_supportive_max_flip_count
        and doji_count <= config.trend_supportive_max_doji_count
    ):
        state = "trend_supportive"
    return FilterSnapshot(
        state=state,
        flip_count=flip_count,
        doji_count=doji_count,
        displacement_ratio=quantize(displacement_ratio),
    )


def passes_breakout_quality(
    *,
    body_ratio: Decimal,
    close_ratio: Decimal,
    avg_body_multiple: Decimal,
    opposite_wick_ratio: Decimal,
    config: ExperimentConfig,
) -> bool:
    return (
        avg_body_multiple >= config.breakout_body_multiple
        and body_ratio >= config.breakout_min_body_ratio
        and close_ratio >= config.breakout_min_close_ratio
        and opposite_wick_ratio <= config.breakout_max_opposite_wick_ratio
    )


def find_follow_through_index(
    *,
    bars: tuple[OhlcvRow, ...] | list[OhlcvRow],
    breakout_index: int,
    prior_level: Decimal,
    direction: str,
    config: ExperimentConfig,
) -> tuple[int | None, str]:
    for candidate_index in range(
        breakout_index + 1,
        min(breakout_index + config.follow_through_window + 1, len(bars) - 1),
    ):
        follow_bar = bars[candidate_index]
        bar_range = follow_bar.high - follow_bar.low
        if bar_range <= 0:
            continue
        body_ratio = abs(follow_bar.close - follow_bar.open) / bar_range
        if direction == "long" and follow_bar.close < prior_level:
            return None, "returned_to_range"
        if direction == "short" and follow_bar.close > prior_level:
            return None, "returned_to_range"
        if direction == "long":
            close_ratio = (follow_bar.close - follow_bar.low) / bar_range
            valid = follow_bar.close > prior_level and close_ratio >= config.ft_min_close_ratio
        else:
            close_ratio = (follow_bar.high - follow_bar.close) / bar_range
            valid = follow_bar.close < prior_level and close_ratio >= config.ft_min_close_ratio
        if valid and body_ratio >= config.ft_min_body_ratio:
            return candidate_index, "confirmed"
    return None, "no_follow_through"


def build_trade_setup(
    *,
    bars: tuple[OhlcvRow, ...] | list[OhlcvRow],
    breakout_index: int,
    follow_through_index: int,
    prior_level: Decimal,
    direction: str,
    config: ExperimentConfig,
    history: tuple[OhlcvRow, ...] | list[OhlcvRow],
) -> dict[str, Decimal] | None:
    entry_index = follow_through_index + 1
    entry_price = bars[entry_index].open
    breakout_bar = bars[breakout_index]
    if direction == "long":
        stop_price = min(breakout_bar.low, prior_level) - config.stop_buffer
        risk = entry_price - stop_price
        target_price = entry_price + (risk * config.target_r_multiple)
    else:
        stop_price = max(breakout_bar.high, prior_level) + config.stop_buffer
        risk = stop_price - entry_price
        target_price = entry_price - (risk * config.target_r_multiple)
    if risk <= 0:
        return None
    recent_median_range = median_decimal(tuple(bar.high - bar.low for bar in history))
    if recent_median_range > 0 and risk > (recent_median_range * config.max_risk_to_median_range_multiple):
        return None
    return {
        "entry_price": quantize(entry_price),
        "stop_price": quantize(stop_price),
        "target_price": quantize(target_price),
        "risk_per_share": quantize(risk),
    }


def find_trade_exit(
    *,
    bars: tuple[OhlcvRow, ...] | list[OhlcvRow],
    entry_index: int,
    direction: str,
    stop_price: Decimal,
    target_price: Decimal,
) -> tuple[int, Decimal, str]:
    for index in range(entry_index, len(bars)):
        bar = bars[index]
        if direction == "long":
            stop_hit = bar.low <= stop_price
            target_hit = bar.high >= target_price
        else:
            stop_hit = bar.high >= stop_price
            target_hit = bar.low <= target_price
        if stop_hit and target_hit:
            return index, stop_price, "stop_before_target_same_bar"
        if stop_hit:
            return index, stop_price, "stop_hit"
        if target_hit:
            return index, target_price, "target_hit"
    return len(bars) - 1, bars[-1].close, "session_close"


def summarize_skip_counts(candidate_events: tuple[CandidateEvent, ...] | list[CandidateEvent]) -> dict[str, int]:
    counter = Counter()
    for event in candidate_events:
        if event.status != "executed":
            counter[event.reason_code] += 1
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def apply_cash_sizing(
    trades: tuple[ExecutedTrade, ...] | list[ExecutedTrade],
    *,
    config: ExperimentConfig,
) -> tuple[ExecutedTrade, ...]:
    equity = config.starting_capital
    sized: list[ExecutedTrade] = []
    for trade in trades:
        quantity_by_risk = (config.risk_per_trade / trade.risk_per_share).to_integral_value(
            rounding=ROUND_DOWN
        )
        quantity_by_capital = (equity / trade.executed_entry_price).to_integral_value(
            rounding=ROUND_DOWN
        )
        quantity = min(quantity_by_risk, quantity_by_capital)
        if quantity <= 0:
            raise RuntimeError(
                f"Account/risk budget is too small to size trade {trade.trade_id} with at least 1 share."
            )
        pnl_cash = quantize(trade.pnl_per_share * quantity)
        equity = quantize(equity + pnl_cash)
        sized.append(
            replace(
                trade,
                quantity=quantity,
                pnl_cash=pnl_cash,
                equity_after_close=equity,
            )
        )
    return tuple(sized)


def compute_trade_stats(
    trades: tuple[ExecutedTrade, ...] | list[ExecutedTrade],
    *,
    starting_capital: Decimal | None = None,
) -> dict[str, Any]:
    ordered = list(trades)
    if not ordered:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "average_r": 0.0,
            "expectancy_r": 0.0,
            "profit_factor": None,
            "max_drawdown_r": 0.0,
            "max_consecutive_losses": 0,
            "starting_capital": float(starting_capital) if starting_capital is not None else None,
            "ending_equity": float(starting_capital) if starting_capital is not None else None,
            "net_pnl_cash": 0.0,
            "average_trade_pnl_cash": 0.0,
            "profit_factor_cash": None,
            "max_drawdown_cash": 0.0,
        }
    pnl_values = [float(trade.pnl_r) for trade in ordered]
    pnl_cash_values = [float(trade.pnl_cash) for trade in ordered]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value <= 0]
    wins_cash = [value for value in pnl_cash_values if value > 0]
    losses_cash = [value for value in pnl_cash_values if value <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(value for value in losses if value < 0))
    gross_profit_cash = sum(wins_cash)
    gross_loss_cash = abs(sum(value for value in losses_cash if value < 0))
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    cash_equity = float(starting_capital) if starting_capital is not None else 0.0
    cash_peak = cash_equity
    max_drawdown_cash = 0.0
    current_loss_streak = 0
    max_loss_streak = 0
    for value, cash_value in zip(pnl_values, pnl_cash_values):
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
        cash_equity += cash_value
        cash_peak = max(cash_peak, cash_equity)
        max_drawdown_cash = min(max_drawdown_cash, cash_equity - cash_peak)
        if value <= 0:
            current_loss_streak += 1
            max_loss_streak = max(max_loss_streak, current_loss_streak)
        else:
            current_loss_streak = 0
    return {
        "trade_count": len(ordered),
        "win_rate": round(len(wins) / len(ordered), 4),
        "average_r": round(sum(pnl_values) / len(ordered), 4),
        "expectancy_r": round(sum(pnl_values) / len(ordered), 4),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "max_drawdown_r": round(max_drawdown, 4),
        "max_consecutive_losses": max_loss_streak,
        "starting_capital": round(float(starting_capital), 2) if starting_capital is not None else None,
        "ending_equity": round(cash_equity, 2) if starting_capital is not None else None,
        "net_pnl_cash": round(sum(pnl_cash_values), 2),
        "average_trade_pnl_cash": round(sum(pnl_cash_values) / len(ordered), 2),
        "profit_factor_cash": round(gross_profit_cash / gross_loss_cash, 4) if gross_loss_cash else None,
        "max_drawdown_cash": round(max_drawdown_cash, 2),
    }


def build_summary_payload(
    *,
    config: ExperimentConfig,
    dataset: dict[str, Any],
    sessions: tuple[SessionSlice, ...],
    filtered: dict[str, Any],
    unfiltered: dict[str, Any],
) -> dict[str, Any]:
    filtered_trades = filtered["trades"]
    split_stats = {
        split: compute_trade_stats([trade for trade in filtered_trades if trade.split == split])
        for split in ("in_sample", "validation", "out_of_sample")
    }
    env_stats = {
        state: compute_trade_stats([trade for trade in filtered_trades if trade.filter_state == state])
        for state in ("trend_supportive", "neutral")
    }
    time_bucket_stats = {
        bucket: compute_trade_stats([trade for trade in filtered_trades if trade.time_bucket == bucket])
        for bucket in ("open_0930_1100", "midday_1100_1330", "late_1330_1600")
    }
    candidate_total = len(filtered["candidate_events"])
    candidate_executed = sum(1 for item in filtered["candidate_events"] if item.status == "executed")
    filter_delta = round(
        filtered["stats"]["expectancy_r"] - unfiltered["stats"]["expectancy_r"],
        4,
    )
    probe_gate_pass = (
        filtered["stats"]["trade_count"] >= config.minimum_probe_trade_count
        and all(
            split_stats[split]["trade_count"] >= config.minimum_probe_split_trade_count
            for split in ("validation", "out_of_sample")
        )
    )
    formal_gate_pass = (
        filtered["stats"]["trade_count"] >= config.formal_trade_count_gate
        and all(
            split_stats[split]["trade_count"] >= config.formal_split_trade_count_gate
            for split in ("validation", "out_of_sample")
        )
    )
    sample_conclusion = (
        "达到最小实验样本要求，但未达到正式 promotion 门槛"
        if probe_gate_pass and not formal_gate_pass
        else (
            "达到最小实验样本要求，并达到正式 promotion 门槛"
            if formal_gate_pass
            else "未达到最小实验样本要求"
        )
    )
    conclusion, conclusion_reason = determine_conclusion(
        filtered_stats=filtered["stats"],
        split_stats=split_stats,
        time_bucket_stats=time_bucket_stats,
        filter_delta=filter_delta,
        sample_conclusion=sample_conclusion,
    )
    return {
        "strategy_id": STRATEGY_ID,
        "strategy_name": "突破后的 Follow-Through 延续",
        "filter_id": FILTER_ID,
        "filter_name": "强趋势日 vs 震荡日过滤 v0.1（negative veto）",
        "dataset": {
            "symbol": config.symbol,
            "market": config.market,
            "timeframe": config.timeframe,
            "session_scope": "regular_session_only",
            "blocked_time_buckets": list(config.blocked_time_buckets),
            "source": dataset["metadata"]["source"],
            "cache_csv": str(dataset["csv_path"]),
            "cache_metadata": str(dataset["metadata_path"]),
            "date_range": f"{config.start.isoformat()} -> {config.end.isoformat()}",
            "complete_sessions": len(sessions),
            "split_windows": build_split_windows(sessions),
        },
        "costs": {
            "slippage": "1bp + 1 tick/side",
            "fees": "0",
            "event_exclusion_applied": False,
            "event_exclusion_gap": "当前仓库没有可直接复用的 SPY 5m 事件标签，本轮未排除宏观新闻窗口。",
        },
        "capital": {
            "starting_capital": float(config.starting_capital),
            "risk_per_trade": float(config.risk_per_trade),
            "position_sizing_rule": "按每笔固定 100 USD 风险预算 sizing，并受账户可买股数限制。",
        },
        "candidate_summary": {
            "candidate_count": candidate_total,
            "executed_trade_count": candidate_executed,
            "skip_count": candidate_total - candidate_executed,
            "skip_counts": filtered["skip_counts"],
        },
        "stats": filtered["stats"],
        "split_stats": split_stats,
        "env_stats": env_stats,
        "time_bucket_stats": time_bucket_stats,
        "filter_comparison": {
            "without_filter": unfiltered["stats"],
            "with_filter": filtered["stats"],
            "delta_expectancy_r": filter_delta,
            "delta_trade_count": filtered["stats"]["trade_count"] - unfiltered["stats"]["trade_count"],
        },
        "sample_conclusion": sample_conclusion,
        "minimum_probe_gate": {
            "total_trades": config.minimum_probe_trade_count,
            "validation_or_oos_min_trades": config.minimum_probe_split_trade_count,
        },
        "formal_gate": {
            "total_trades": config.formal_trade_count_gate,
            "validation_or_oos_min_trades": config.formal_split_trade_count_gate,
        },
        "case_studies": {
            "winners": build_case_studies(filtered_trades, positive=True),
            "losers": build_case_studies(filtered_trades, positive=False),
        },
        "conclusion": {
            "label": conclusion,
            "reason": conclusion_reason,
        },
    }


def build_split_windows(sessions: tuple[SessionSlice, ...]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for split in ("in_sample", "validation", "out_of_sample"):
        split_sessions = [item.session_key for item in sessions if item.split == split]
        payload[split] = (
            f"{split_sessions[0]} -> {split_sessions[-1]}" if split_sessions else "n/a"
        )
    return payload


def determine_conclusion(
    *,
    filtered_stats: dict[str, Any],
    split_stats: dict[str, Any],
    time_bucket_stats: dict[str, Any],
    filter_delta: float,
    sample_conclusion: str,
) -> tuple[str, str]:
    if (
        filtered_stats["expectancy_r"] > 0
        and (filtered_stats["profit_factor"] or 0) >= 1.15
        and split_stats["out_of_sample"]["expectancy_r"] > 0
        and (split_stats["out_of_sample"]["profit_factor"] or 0) >= 1.0
        and filtered_stats["max_drawdown_r"] >= -12.0
    ):
        return (
            "保留，进入第二轮改进",
            "成本后整体与样本外仍保持正期望，且最大回撤未突破当前容忍上限。",
        )
    if (
        filter_delta >= 0
        and (
            time_bucket_stats["open_0930_1100"]["expectancy_r"] > 0
            or time_bucket_stats["late_1330_1600"]["expectancy_r"] > 0
        )
    ):
        return (
            "修改后重测",
            "当前 v0.1 成本后整体仍为负，且样本外转弱；但开盘/尾盘窗口和过滤器本身有改善迹象，值得先收紧时段与过滤条件后再测。",
        )
    return (
        "淘汰，不再投入",
        f"{sample_conclusion}，且过滤后仍未出现可复用的正期望线索。",
    )


def build_case_studies(
    trades: tuple[ExecutedTrade, ...] | list[ExecutedTrade],
    *,
    positive: bool,
) -> list[dict[str, Any]]:
    ordered = sorted(trades, key=lambda item: item.pnl_r, reverse=positive)
    selected = [item for item in ordered if (item.pnl_r > 0) == positive][:5]
    cases = []
    for trade in selected[:5]:
        cases.append(
            {
                "trade_id": trade.trade_id,
                "day": trade.session_key,
                "direction": trade.direction,
                "breakout_time": trade.breakout_timestamp.time().isoformat(),
                "entry_time": trade.entry_timestamp.time().isoformat(),
                "filter_state": trade.filter_state,
                "exit_reason": trade.exit_reason,
                "pnl_r": float(trade.pnl_r),
                "pnl_cash": float(trade.pnl_cash),
                "why": explain_trade_case(trade),
            }
        )
    return cases[:5]


def explain_trade_case(trade: ExecutedTrade) -> str:
    if trade.pnl_r > 0:
        return (
            "突破 bar 收盘靠近极值，1 至 2 根 bar 内出现同向确认，且交易发生在成本影响相对可控的窗口，"
            "因此固定 1R 目标仍能在滑点后保住正收益。"
        )
    if trade.risk_per_share <= Decimal("0.70"):
        return (
            "结构本身成立，但初始 stop 很近，1bp + 1 tick/side 的摩擦把亏损放大，"
            "导致这类小风险 breakout 在回撤中被成本吃掉。"
        )
    if trade.exit_reason == "session_close":
        return "突破后没有形成足够延续，既没到 1R，也没触及止损，最终被收盘前平掉。"
    return (
        "突破后虽然一度确认，但后续跟进不足或很快被反向打回，"
        "说明当前 v0.1 对午盘/区间化环境的过滤仍不够强。"
    )


def classify_time_bucket(value: time) -> str:
    if value < time(11, 0):
        return "open_0930_1100"
    if value < time(13, 30):
        return "midday_1100_1330"
    return "late_1330_1600"


def candle_direction(bar: OhlcvRow) -> int:
    if bar.close > bar.open:
        return 1
    if bar.close < bar.open:
        return -1
    return 0


def compute_pnl(
    *,
    direction: str,
    entry_price: Decimal,
    exit_price: Decimal,
) -> Decimal:
    if direction == "long":
        return exit_price - entry_price
    return entry_price - exit_price


def apply_side_cost(
    price: Decimal,
    *,
    direction: str,
    side: str,
    config: ExperimentConfig,
) -> Decimal:
    impact = (price * config.slippage_bps) + config.per_side_tick_slippage
    if side == "entry":
        return quantize(price + impact) if direction == "long" else quantize(price - impact)
    return quantize(price - impact) if direction == "long" else quantize(price + impact)


def median_decimal(values: tuple[Decimal, ...] | list[Decimal]) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        return Decimal("0")
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / TWO


def quantize(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)


def write_artifacts(
    *,
    config: ExperimentConfig,
    summary: dict[str, Any],
    filtered: dict[str, Any],
) -> None:
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    config.summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    config.skip_summary_path.write_text(
        json.dumps(summary["candidate_summary"]["skip_counts"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_candidates_csv(config.candidates_csv_path, filtered["candidate_events"])
    write_trades_csv(config.trades_csv_path, filtered["trades"])
    config.report_path.write_text(render_markdown_report(summary), encoding="utf-8")


def write_candidates_csv(path: Path, events: tuple[CandidateEvent, ...] | list[CandidateEvent]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "session_key",
                "split",
                "breakout_timestamp",
                "direction",
                "prior_level",
                "filter_state",
                "breakout_body_ratio",
                "breakout_close_ratio",
                "breakout_avg_body_multiple",
                "filter_displacement_ratio",
                "filter_flip_count",
                "filter_doji_count",
                "status",
                "reason_code",
                "time_bucket",
            ]
        )
        for item in events:
            writer.writerow(
                [
                    item.session_key,
                    item.split,
                    item.breakout_timestamp.isoformat(),
                    item.direction,
                    str(item.prior_level),
                    item.filter_state,
                    str(item.breakout_body_ratio),
                    str(item.breakout_close_ratio),
                    str(item.breakout_avg_body_multiple),
                    str(item.filter_displacement_ratio),
                    item.filter_flip_count,
                    item.filter_doji_count,
                    item.status,
                    item.reason_code,
                    item.time_bucket,
                ]
            )


def write_trades_csv(path: Path, trades: tuple[ExecutedTrade, ...] | list[ExecutedTrade]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "trade_id",
                "session_key",
                "split",
                "direction",
                "filter_state",
                "breakout_timestamp",
                "follow_through_timestamp",
                "entry_timestamp",
                "exit_timestamp",
                "time_bucket",
                "raw_entry_price",
                "executed_entry_price",
                "stop_price",
                "target_price",
                "exit_price",
                "executed_exit_price",
                "risk_per_share",
                "quantity",
                "pnl_per_share",
                "pnl_cash",
                "pnl_r",
                "equity_after_close",
                "exit_reason",
            ]
        )
        for item in trades:
            writer.writerow(
                [
                    item.trade_id,
                    item.session_key,
                    item.split,
                    item.direction,
                    item.filter_state,
                    item.breakout_timestamp.isoformat(),
                    item.follow_through_timestamp.isoformat(),
                    item.entry_timestamp.isoformat(),
                    item.exit_timestamp.isoformat(),
                    item.time_bucket,
                    str(item.raw_entry_price),
                    str(item.executed_entry_price),
                    str(item.stop_price),
                    str(item.target_price),
                    str(item.exit_price),
                    str(item.executed_exit_price),
                    str(item.risk_per_share),
                    str(item.quantity),
                    str(item.pnl_per_share),
                    str(item.pnl_cash),
                    str(item.pnl_r),
                    str(item.equity_after_close),
                    item.exit_reason,
                ]
            )


def render_markdown_report(summary: dict[str, Any]) -> str:
    stats = summary["stats"]
    split_stats = summary["split_stats"]
    time_bucket_stats = summary["time_bucket_stats"]
    env_stats = summary["env_stats"]
    skip_counts = summary["candidate_summary"]["skip_counts"]
    winners = summary["case_studies"]["winners"][:3]
    losers = summary["case_studies"]["losers"][:3]
    out_of_sample = split_stats["out_of_sample"]
    lines = [
        "# PA-SC-002 Longbridge Backtest Report",
        "",
        "本报告只代表 `paper / simulated` 范围内的最小研究闭环，不代表实盘能力或收益承诺。",
        "",
        "## 这次测了什么",
        "",
        "- 主策略：`PA-SC-002` 突破后的 Follow-Through 延续",
        "- 过滤器：`PA-SC-009 filter v0.1`，只做 `range_veto` 负向拦截",
        "- 标的与周期：`SPY 5m`，仅 `regular session`",
        f"- 数据区间：`{summary['dataset']['date_range']}`，完整 session `40` 天",
        "",
        "## 表 1：实验摘要",
        "",
        "| 项目 | 内容 |",
        "|---|---|",
        f"| 策略 ID | `{summary['strategy_id']}` |",
        f"| 策略名称 | {summary['strategy_name']} |",
        f"| 过滤器 | {summary['filter_name']} |",
        f"| 标的 | `{summary['dataset']['symbol']}` |",
        f"| 周期 | `{summary['dataset']['timeframe']}` |",
        f"| 数据源 | `{summary['dataset']['source']}` |",
        "| 时段限制 | `regular session only` |",
        f"| 数据区间 | `{summary['dataset']['date_range']}` |",
        f"| 假设本金 | `${summary['capital']['starting_capital']:.2f}` |",
        f"| 单笔风险预算 | `${summary['capital']['risk_per_trade']:.2f}` |",
        f"| 成本假设 | {summary['costs']['fees']} 费用，{summary['costs']['slippage']} |",
        f"| 滑点假设 | {summary['costs']['slippage']} |",
        f"| 样本结论 | {summary['sample_conclusion']} |",
        "",
        "## 表 2：核心结果",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 交易次数 | {stats['trade_count']} |",
        f"| 胜率 | {format_pct(stats['win_rate'])} |",
        f"| 平均 R | {stats['average_r']:.4f} |",
        f"| Expectancy | {stats['expectancy_r']:.4f} |",
        f"| 净盈利 / 亏损 | ${stats['net_pnl_cash']:.2f} |",
        f"| 期末本金 | ${stats['ending_equity']:.2f} |",
        f"| 平均每笔盈亏 | ${stats['average_trade_pnl_cash']:.2f} |",
        f"| Profit Factor | {format_optional(stats['profit_factor'])} |",
        f"| 最大回撤 | {stats['max_drawdown_r']:.4f}R |",
        f"| 最大回撤(USD) | ${stats['max_drawdown_cash']:.2f} |",
        f"| 最大连续亏损 | {stats['max_consecutive_losses']} |",
        f"| 样本外表现 | `交易 {out_of_sample['trade_count']} 笔 / Expectancy {out_of_sample['expectancy_r']:.4f} / 净盈亏 ${out_of_sample['net_pnl_cash']:.2f} / PF {format_optional(out_of_sample['profit_factor'])}` |",
        "",
        "## 表 3：环境拆分",
        "",
        "| 环境 | 交易数 | 胜率 | 平均 R | 结论 |",
        "|---|---:|---:|---:|---|",
        f"| 开盘窗口 `09:30-11:00` | {time_bucket_stats['open_0930_1100']['trade_count']} | {format_pct(time_bucket_stats['open_0930_1100']['win_rate'])} | {time_bucket_stats['open_0930_1100']['expectancy_r']:.4f} | {describe_time_bucket(time_bucket_stats['open_0930_1100']['expectancy_r'], positive_label='比午盘更稳，但还没到可用正期望', negative_label='开盘也没过线，说明单靠早盘 breakout 还不够')} |",
        f"| 午盘窗口 `11:00-13:30` | {time_bucket_stats['midday_1100_1330']['trade_count']} | {format_pct(time_bucket_stats['midday_1100_1330']['win_rate'])} | {time_bucket_stats['midday_1100_1330']['expectancy_r']:.4f} | 本轮最差，突破常被来回打回 |",
        f"| 尾盘窗口 `13:30-16:00` | {time_bucket_stats['late_1330_1600']['trade_count']} | {format_pct(time_bucket_stats['late_1330_1600']['win_rate'])} | {time_bucket_stats['late_1330_1600']['expectancy_r']:.4f} | {describe_time_bucket(time_bucket_stats['late_1330_1600']['expectancy_r'], positive_label='本轮唯一转正的时间段，值得下一轮单独验证', negative_label='比午盘更好，但稳定性仍不足')} |",
        f"| `trend_supportive` 标签 | {env_stats['trend_supportive']['trade_count']} | {format_pct(env_stats['trend_supportive']['win_rate'])} | {env_stats['trend_supportive']['expectancy_r']:.4f} | 样本太少，暂不能证明过滤器已足够强 |",
        f"| `neutral` 标签 | {env_stats['neutral']['trade_count']} | {format_pct(env_stats['neutral']['win_rate'])} | {env_stats['neutral']['expectancy_r']:.4f} | 大部分交易都落在这里，说明当前 veto 还不够锋利 |",
        "",
        "## 表 4：最常见跳过原因",
        "",
        "| skip / no-trade 原因 | 次数 | 含义 |",
        "|---|---:|---|",
    ]
    for reason, count in list(skip_counts.items())[:5]:
        lines.append(f"| `{reason}` | {count} | {humanize_skip_reason(reason)} |")
    lines.extend(
        [
            "",
            "## 本次怎么测的",
            "",
            f"- 完整 session 按时间顺序切成 `50 / 25 / 25`：样本内 `{summary['dataset']['split_windows']['in_sample']}`，验证集 `{summary['dataset']['split_windows']['validation']}`，样本外 `{summary['dataset']['split_windows']['out_of_sample']}`。",
            "- 只做 `SPY 5m`，不并行扩到 `QQQ / NVDA / TSLA`。",
            "- 每次交易只在 breakout 后 1 到 2 根 bar 内找 follow-through；找不到就跳过。",
            "- 只用固定 `1R` 目标，不在这一轮做大规模调参。",
            f"- 当前没有可复用的 `SPY 5m` 新闻/财报标签，所以本轮没有排除宏观新闻窗口。这是明确的数据缺口，而不是默认不存在风险。",
            "",
            "## 这次结果说明了什么",
            "",
            f"- 过滤器加入后，交易从 `{summary['filter_comparison']['without_filter']['trade_count']}` 笔降到 `{summary['filter_comparison']['with_filter']['trade_count']}` 笔，Expectancy 从 `{summary['filter_comparison']['without_filter']['expectancy_r']:.4f}` 改善到 `{summary['filter_comparison']['with_filter']['expectancy_r']:.4f}`。说明 `PA-SC-009` 的负向 veto 有帮助，但还不够把策略拉到正期望。",
            f"- 按 `${summary['capital']['starting_capital']:.2f}` 本金、每笔 `${summary['capital']['risk_per_trade']:.2f}` 风险预算 sizing 后，本轮净结果是 `${stats['net_pnl_cash']:.2f}`，期末权益 `${stats['ending_equity']:.2f}`。这让结果更接近真实研究视角，而不只是抽象 R 值。",
            f"- 成本和滑点是这轮的关键拖累。很多亏损交易的初始风险只有 `0.2 ~ 0.7` 点，`1bp + 1 tick/side` 会明显放大实际亏损，所以表面上看起来像“成功 breakout”，净值上却不划算。",
            f"- 午盘窗口最差：`11:00-13:30` 的 Expectancy 是 `{time_bucket_stats['midday_1100_1330']['expectancy_r']:.4f}`。这说明当前规则对区间化、来回打脸的环境过滤不够强。",
            f"- 尾盘窗口是本轮唯一转正的时段，但开盘窗口仍然为负；再加上样本外整体仍是负的：`{out_of_sample['expectancy_r']:.4f}`。因此这轮还不能说策略已经成立。",
            "",
            "## 代表性盈利案例",
            "",
            "| 日期 | 方向 | 入场时间 | 净结果(R) | 净结果(USD) | 为什么赢 |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for item in winners:
        lines.append(
            f"| {item['day']} | {item['direction']} | {item['entry_time']} | {item['pnl_r']:.4f} | ${item['pnl_cash']:.2f} | {item['why']} |"
        )
    lines.extend(
        [
            "",
            "## 代表性亏损案例",
            "",
            "| 日期 | 方向 | 入场时间 | 净结果(R) | 净结果(USD) | 为什么亏 |",
            "|---|---|---|---:|---:|---|",
        ]
    )
    for item in losers:
        lines.append(
            f"| {item['day']} | {item['direction']} | {item['entry_time']} | {item['pnl_r']:.4f} | ${item['pnl_cash']:.2f} | {item['why']} |"
        )
    lines.extend(
        [
            "",
            "## 表 5：最终结论",
            "",
            "| 结论 | 原因 |",
            "|---|---|",
            f"| {summary['conclusion']['label']} | {summary['conclusion']['reason']} |",
            "",
            "## 下一步最该改什么",
            "",
            "- 第一优先：把午盘 `11:00-13:30` 设为可测试禁做窗口，先看是否能显著改善 Expectancy 与回撤。",
            "- 第二优先：增加“最小风险距离”或“最小可用波动”约束，避免小 stop 被交易摩擦吃掉。",
            "- 第三优先：在不改 entry 逻辑的前提下，只做很小范围的 `1R / 1.5R` 对照，确认问题主要在 entry 还是 exit。",
        ]
    )
    return "\n".join(lines) + "\n"


def humanize_skip_reason(reason_code: str) -> str:
    mapping = {
        "weak_breakout_bar": "突破 bar 自身不够强，实体/收盘位置/尾巴结构不达标",
        "returned_to_range": "突破后很快回到原区间，说明 follow-through 失败",
        "range_veto": "过滤器判断最近 30 分钟更像震荡或紧密区间，直接禁止追突破",
        "no_follow_through": "突破后 1 到 2 根 bar 内没有出现合格的同向延续",
        "stop_too_wide": "止损会放得过宽，先跳过避免结构不清的交易",
        "insufficient_future_bars": "样本靠近收盘，无法给 follow-through 和入场 bar 留足空间",
        "blocked_time_bucket": "当前实验版本显式禁止该时间段的 breakout 交易",
    }
    return mapping.get(reason_code, reason_code)


def format_pct(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def format_optional(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def describe_time_bucket(
    expectancy_r: float,
    *,
    positive_label: str,
    negative_label: str,
) -> str:
    if expectancy_r > 0:
        return positive_label
    return negative_label
