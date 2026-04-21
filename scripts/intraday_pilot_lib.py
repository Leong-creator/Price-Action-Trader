#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest import BacktestReport, TradeRecord, run_backtest
from src.data import OhlcvRow, build_replay, load_ohlcv_csv
from src.execution import ExecutionRequest, PaperBrokerAdapter, PaperPosition
from src.risk import PositionSnapshot, RiskConfig, SessionRiskState, evaluate_order_request, maybe_reset_session
from src.strategy import Signal, generate_signals, summarize_knowledge_trace

from scripts.public_backtest_demo_lib import (
    BlockedSignalRecord,
    DataValidationError,
    DatasetCacheRecord,
    DemoRiskSettings,
    ExecutedTradeRecord,
    InstrumentConfig,
    NoTradeWaitRecord,
    PaperDemoOutcome,
    SymbolBacktestResult,
    build_knowledge_trace_coverage,
    build_no_trade_wait_records,
    compute_demo_quantity,
    compute_max_drawdown,
    humanize_block_reason,
    humanize_exit_reason,
    summarize_no_trade_wait,
    serialize_repo_logical_path,
    sanitize_vendor_rows,
    trade_to_summary_row,
    write_equity_curve_png,
    write_knowledge_trace_json,
    write_no_trade_wait_jsonl,
    write_summary_json,
    write_trades_csv,
)
from scripts.longbridge_history_lib import fetch_longbridge_intraday_history_rows

try:  # pragma: no cover - optional runtime dependency
    import yfinance as yf
except ImportError:  # pragma: no cover - optional runtime dependency
    yf = None


ZERO = Decimal("0")
HUNDRED = Decimal("100")
QUANT = Decimal("0.0001")
REGULAR_SESSION_START = time(9, 30)
REGULAR_SESSION_LAST_BAR = time(15, 45)
REGULAR_SESSION_CLOSE = time(16, 0)
CURATED_TRACE_TYPES = frozenset({"concept", "setup", "rule"})
SUPPORTED_INTRADAY_INTERVALS = frozenset({"1m", "5m", "15m", "30m", "1h"})
INTRADAY_INTERVAL_TO_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}


@dataclass(frozen=True, slots=True)
class IntradayCostModel:
    slippage_bps: Decimal
    fee_per_order: Decimal


@dataclass(frozen=True, slots=True)
class IntradaySessionModel:
    timezone: str
    regular_open: str
    regular_close: str
    expected_bars_per_session: int
    allow_extended_hours: bool = False


@dataclass(frozen=True, slots=True)
class IntradayPilotConfig:
    title: str
    description: str
    start: date
    end: date
    interval: str
    cache_dir: Path
    report_dir: Path
    source_order: tuple[str, ...]
    instrument: InstrumentConfig
    risk: DemoRiskSettings
    session: IntradaySessionModel
    costs: IntradayCostModel


@dataclass(frozen=True, slots=True)
class SessionAudit:
    session_key: str
    timezone: str
    first_bar_timestamp: datetime | None
    last_bar_timestamp: datetime | None
    raw_bar_count: int
    regular_bar_count: int
    expected_bar_count: int
    missing_bar_count: int
    duplicate_bar_count: int
    out_of_hours_bar_count: int
    complete: bool
    used_for_pilot: bool
    skipped_reason: str | None
    regular_bars: tuple[OhlcvRow, ...] = ()


@dataclass(frozen=True, slots=True)
class SessionExecutionSummary:
    session_key: str
    timezone: str
    session_open: str
    session_close: str
    expected_bars: int
    actual_bars: int
    signal_count: int
    executed_trades: int
    blocked_signals: int
    no_trade_wait: int
    session_reset_applied: bool
    missing_bar_count: int
    out_of_hours_bar_count: int
    complete: bool
    used_for_pilot: bool
    skipped_reason: str | None
    first_bar_timestamp: str | None
    last_bar_timestamp: str | None
    trace_curated_signal_pct: str
    trace_statement_signal_pct: str


def load_intraday_pilot_config(path: str | Path) -> IntradayPilotConfig:
    config_path = _resolve_repo_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    instrument_payload = payload["instrument"]
    risk_payload = payload["risk"]
    session_payload = payload["session"]
    costs_payload = payload["costs"]
    interval = payload["interval"]
    if interval not in SUPPORTED_INTRADAY_INTERVALS:
        raise ValueError(f"Unsupported intraday interval: {interval}")
    return IntradayPilotConfig(
        title=payload["title"],
        description=payload.get("description", ""),
        start=date.fromisoformat(payload["start"]),
        end=date.fromisoformat(payload["end"]),
        interval=interval,
        cache_dir=_resolve_repo_path(payload["cache_dir"]),
        report_dir=_resolve_repo_path(payload["report_dir"]),
        source_order=tuple(payload.get("source_order") or ("longbridge",)),
        instrument=InstrumentConfig(
            ticker=instrument_payload["ticker"],
            symbol=instrument_payload["symbol"],
            label=instrument_payload["label"],
            market=instrument_payload["market"],
            timezone=instrument_payload["timezone"],
            demo_role=instrument_payload.get("demo_role", "intraday_pilot"),
        ),
        risk=DemoRiskSettings(
            starting_capital=_decimal(risk_payload["starting_capital"]),
            risk_per_trade=_decimal(risk_payload["risk_per_trade"]),
            max_total_exposure=_decimal(risk_payload["max_total_exposure"]),
            max_symbol_exposure_ratio=_decimal(risk_payload["max_symbol_exposure_ratio"]),
            max_daily_loss=_decimal(risk_payload["max_daily_loss"]),
            max_consecutive_losses=int(risk_payload["max_consecutive_losses"]),
        ),
        session=IntradaySessionModel(
            timezone=session_payload["timezone"],
            regular_open=session_payload["regular_open"],
            regular_close=session_payload["regular_close"],
            expected_bars_per_session=int(session_payload["expected_bars_per_session"]),
            allow_extended_hours=bool(session_payload.get("allow_extended_hours", False)),
        ),
        costs=IntradayCostModel(
            slippage_bps=_decimal(costs_payload["slippage_bps"]),
            fee_per_order=_decimal(costs_payload["fee_per_order"]),
        ),
    )


def create_intraday_pilot_run(
    config: IntradayPilotConfig,
    *,
    refresh_data: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    dataset = download_and_cache_intraday_dataset(config, refresh=refresh_data)
    bars = tuple(load_ohlcv_csv(dataset.csv_path))
    session_audits = audit_intraday_sessions(
        bars,
        timeframe=config.interval,
        timezone_name=config.session.timezone,
        expected_bars_per_session=config.session.expected_bars_per_session,
        allow_extended_hours=config.session.allow_extended_hours,
    )
    session_results = tuple(
        run_intraday_session_backtest(dataset, audit)
        for audit in session_audits
        if audit.used_for_pilot
    )
    paper_outcome, session_reset_map = run_intraday_paper_demo(
        session_results,
        risk_settings=config.risk,
        costs=config.costs,
    )
    no_trade_wait_records = build_intraday_no_trade_wait_records(
        session_results,
        paper_outcome,
        session_audits,
        instrument=config.instrument,
        timeframe=config.interval,
        timezone_name=config.session.timezone,
    )
    session_summary = build_session_summary(
        session_audits=session_audits,
        session_results=session_results,
        paper_outcome=paper_outcome,
        no_trade_wait_records=no_trade_wait_records,
        session_reset_map=session_reset_map,
        timezone_name=config.session.timezone,
        session_open=config.session.regular_open,
        session_close=config.session.regular_close,
        expected_bars_per_session=config.session.expected_bars_per_session,
    )
    session_quality = build_session_quality_payload(session_audits)
    knowledge_trace_coverage = build_knowledge_trace_coverage(session_results, paper_outcome)

    resolved_run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_intraday_pilot")
    report_dir = config.report_dir / resolved_run_id
    report_dir.mkdir(parents=True, exist_ok=True)

    summary = build_intraday_summary_payload(
        config=config,
        dataset=dataset,
        session_audits=session_audits,
        session_results=session_results,
        paper_outcome=paper_outcome,
        no_trade_wait_records=no_trade_wait_records,
        session_summary=session_summary,
        session_quality=session_quality,
        knowledge_trace_coverage=knowledge_trace_coverage,
        run_id=resolved_run_id,
        report_dir=report_dir,
    )
    write_summary_json(report_dir / "summary.json", summary)
    write_summary_json(report_dir / "session_summary.json", session_summary)
    write_summary_json(report_dir / "session_quality.json", session_quality)
    write_summary_json(report_dir / "knowledge_trace_coverage.json", knowledge_trace_coverage)
    write_no_trade_wait_jsonl(report_dir / "no_trade_wait.jsonl", no_trade_wait_records)
    write_trades_csv(report_dir / "trades.csv", paper_outcome.executed_trades)
    write_knowledge_trace_json(
        report_dir / "knowledge_trace.json",
        run_id=resolved_run_id,
        paper_outcome=paper_outcome,
    )
    if paper_outcome.equity_points:
        try:
            write_equity_curve_png(report_dir / "equity_curve.png", paper_outcome.equity_points)
        except RuntimeError:
            pass
    write_intraday_markdown_report(
        report_dir / "report.md",
        summary=summary,
        session_summary=session_summary,
        paper_outcome=paper_outcome,
    )
    return {
        "run_id": resolved_run_id,
        "report_dir": report_dir,
        "summary": summary,
    }


def download_and_cache_intraday_dataset(
    config: IntradayPilotConfig,
    *,
    refresh: bool = False,
) -> DatasetCacheRecord:
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for source in config.source_order:
        if source not in {"longbridge", "yfinance"}:
            last_error = RuntimeError(f"Unsupported intraday source: {source}")
            continue
        csv_path = build_intraday_cache_path(config, source=source)
        metadata_path = csv_path.with_suffix(".metadata.json")
        if csv_path.exists() and metadata_path.exists() and not refresh:
            row_count = len(load_ohlcv_csv(csv_path))
            return DatasetCacheRecord(
                instrument=config.instrument,
                source=source,
                csv_path=csv_path,
                metadata_path=metadata_path,
                row_count=row_count,
            )

        try:
            rows = fetch_intraday_history_rows(
                instrument=config.instrument,
                start=config.start,
                end=config.end,
                interval=config.interval,
                source=source,
                timezone_name=config.session.timezone,
                allow_extended_hours=config.session.allow_extended_hours,
            )
            rows, vendor_anomalies = sanitize_vendor_rows(rows)
            if not rows:
                raise RuntimeError(f"{config.instrument.ticker} returned no rows from {source}")
            write_intraday_cache_csv(csv_path, rows)
            row_count = len(load_ohlcv_csv(csv_path))
            anomaly_path = csv_path.with_suffix(".vendor_anomalies.json")
            if vendor_anomalies:
                anomaly_path.write_text(
                    json.dumps(vendor_anomalies, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            elif anomaly_path.exists():
                anomaly_path.unlink()
            metadata = {
                "instrument": asdict(config.instrument),
                "source": source,
                "row_count": row_count,
                "start": config.start.isoformat(),
                "end": config.end.isoformat(),
                "interval": config.interval,
                "boundary": "paper/simulated",
                "timezone": config.session.timezone,
                "regular_session_only": not config.session.allow_extended_hours,
                "downloaded_at": datetime.now(UTC).isoformat(),
                "dropped_invalid_vendor_rows": len(vendor_anomalies),
                "vendor_anomalies_path": str(anomaly_path) if vendor_anomalies else None,
            }
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            return DatasetCacheRecord(
                instrument=config.instrument,
                source=source,
                csv_path=csv_path,
                metadata_path=metadata_path,
                row_count=row_count,
            )
        except Exception as exc:  # pragma: no cover - runtime path
            last_error = exc

    if last_error is None:
        raise RuntimeError("No supported intraday source is configured.")
    raise RuntimeError(str(last_error))


def fetch_intraday_history_rows(
    *,
    instrument: InstrumentConfig,
    start: date,
    end: date,
    interval: str,
    source: str,
    timezone_name: str,
    allow_extended_hours: bool,
) -> list[dict[str, str]]:
    if source == "longbridge":
        return fetch_longbridge_intraday_history_rows(
            ticker=instrument.ticker,
            symbol=instrument.symbol,
            market=instrument.market,
            timezone_name=timezone_name,
            start=start,
            end=end,
            interval=interval,
            allow_extended_hours=allow_extended_hours,
        )
    if source != "yfinance":
        raise RuntimeError(f"Unsupported intraday source: {source}")
    if yf is None:  # pragma: no cover - runtime dependency
        raise RuntimeError("yfinance is required for intraday public history retrieval.")
    frame = yf.download(
        instrument.ticker,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
        prepost=allow_extended_hours,
    )
    if getattr(frame, "empty", True):
        raise RuntimeError(f"yfinance returned no intraday rows for {instrument.ticker}")
    frame = _flatten_yfinance_frame(frame, instrument.ticker)
    zone = ZoneInfo(timezone_name)
    rows: list[dict[str, str]] = []
    for timestamp, row in frame.iterrows():
        localized = timestamp.tz_convert(zone)
        rows.append(
            {
                "symbol": instrument.symbol,
                "market": instrument.market,
                "timeframe": interval,
                "timestamp": localized.replace(tzinfo=None).isoformat(timespec="seconds"),
                "timezone": timezone_name,
                "open": _string_decimal(_decimal(row["Open"])),
                "high": _string_decimal(_decimal(row["High"])),
                "low": _string_decimal(_decimal(row["Low"])),
                "close": _string_decimal(_decimal(row["Close"])),
                "volume": _string_decimal(_decimal(row["Volume"])),
            }
        )
    return rows


def build_intraday_cache_path(config: IntradayPilotConfig, *, source: str) -> Path:
    filename = "_".join(
        [
            config.instrument.market.lower(),
            config.instrument.symbol.replace(".", "-"),
            config.interval,
            config.start.isoformat(),
            config.end.isoformat(),
            source,
        ]
    )
    return config.cache_dir / f"{filename}.csv"


def write_intraday_cache_csv(path: Path, rows: list[dict[str, str]]) -> None:
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


def audit_intraday_sessions(
    bars: tuple[OhlcvRow, ...] | list[OhlcvRow],
    *,
    timeframe: str,
    timezone_name: str,
    expected_bars_per_session: int,
    allow_extended_hours: bool,
) -> tuple[SessionAudit, ...]:
    zone = ZoneInfo(timezone_name)
    grouped: dict[str, list[OhlcvRow]] = defaultdict(list)
    for bar in bars:
        session_key = bar.timestamp.astimezone(zone).date().isoformat()
        grouped[session_key].append(bar)

    audits: list[SessionAudit] = []
    expected_times = _expected_session_times(timeframe)
    for session_key, session_bars in sorted(grouped.items()):
        seen = Counter(bar.timestamp.astimezone(zone).time().strftime("%H:%M") for bar in session_bars)
        duplicate_count = sum(count - 1 for count in seen.values() if count > 1)
        regular_bars = tuple(
            bar
            for bar in sorted(session_bars, key=lambda item: item.timestamp)
            if _is_regular_session_bar(bar.timestamp.astimezone(zone).time(), timeframe=timeframe)
        )
        out_of_hours_count = len(session_bars) - len(regular_bars)
        actual_times = {
            bar.timestamp.astimezone(zone).time().strftime("%H:%M")
            for bar in regular_bars
        }
        missing = sorted(expected_times - actual_times)
        complete = (
            len(regular_bars) == expected_bars_per_session
            and not missing
            and duplicate_count == 0
            and (allow_extended_hours or out_of_hours_count == 0)
        )
        skipped_reason = None
        if not complete:
            if missing:
                skipped_reason = "data_gap_or_incomplete_session"
            elif out_of_hours_count:
                skipped_reason = "session_closed_or_out_of_hours"
            elif duplicate_count:
                skipped_reason = "duplicate_bars_in_session"
            else:
                skipped_reason = "session_quality_gate"
        audits.append(
            SessionAudit(
                session_key=session_key,
                timezone=timezone_name,
                first_bar_timestamp=regular_bars[0].timestamp if regular_bars else None,
                last_bar_timestamp=regular_bars[-1].timestamp if regular_bars else None,
                raw_bar_count=len(session_bars),
                regular_bar_count=len(regular_bars),
                expected_bar_count=expected_bars_per_session,
                missing_bar_count=len(missing),
                duplicate_bar_count=duplicate_count,
                out_of_hours_bar_count=out_of_hours_count,
                complete=complete,
                used_for_pilot=complete,
                skipped_reason=skipped_reason,
                regular_bars=regular_bars,
            )
        )
    return tuple(audits)


def run_intraday_session_backtest(
    dataset: DatasetCacheRecord,
    audit: SessionAudit,
) -> SymbolBacktestResult:
    replay = build_replay(audit.regular_bars, ())
    signals = generate_signals(replay)
    backtest_report = run_backtest(audit.regular_bars, signals)
    return SymbolBacktestResult(
        instrument=dataset.instrument,
        source=dataset.source,
        csv_path=dataset.csv_path,
        metadata_path=dataset.metadata_path,
        bars=audit.regular_bars,
        bars_count=len(audit.regular_bars),
        signals=signals,
        backtest_report=backtest_report,
    )


def run_intraday_paper_demo(
    session_results: tuple[SymbolBacktestResult, ...],
    *,
    risk_settings: DemoRiskSettings,
    costs: IntradayCostModel,
) -> tuple[PaperDemoOutcome, dict[str, bool]]:
    adapter = PaperBrokerAdapter()
    risk_config = RiskConfig(
        max_risk_per_order=risk_settings.risk_per_trade,
        max_total_exposure=risk_settings.max_total_exposure,
        max_symbol_exposure_ratio=risk_settings.max_symbol_exposure_ratio,
        max_daily_loss=risk_settings.max_daily_loss,
        max_consecutive_losses=risk_settings.max_consecutive_losses,
    )
    positions: tuple[PaperPosition, ...] = ()
    seen_signal_ids = frozenset()
    session_state: SessionRiskState | None = None
    session_reset_map: dict[str, bool] = {}
    equity = risk_settings.starting_capital
    equity_points: list[tuple[str, float]] = []
    executed: list[ExecutedTradeRecord] = []
    blocked: list[BlockedSignalRecord] = []
    open_plans: dict[str, tuple[SymbolBacktestResult, Signal, TradeRecord, Decimal, IntradayCostModel]] = {}
    candidates = sorted(
        _iter_trade_candidates(session_results),
        key=lambda item: (item[2].entry_timestamp, item[0].instrument.symbol, item[1].signal_id),
    )

    for result, signal, trade in candidates:
        session_key = trade.entry_timestamp.date().isoformat()
        if session_state is None:
            session_state = SessionRiskState(session_key=session_key)
            seen_signal_ids = frozenset()
            session_reset_map[session_key] = False
            equity_points.append((trade.entry_timestamp.isoformat(), float(equity)))
        elif session_state.session_key != session_key:
            positions, session_state, equity = _close_due_intraday_positions(
                adapter=adapter,
                current_positions=positions,
                session_state=session_state,
                config=risk_config,
                current_equity=equity,
                due_before=trade.entry_timestamp,
                open_plans=open_plans,
                executed=executed,
                equity_points=equity_points,
            )
            session_state = maybe_reset_session(session_state, next_session_key=session_key)
            seen_signal_ids = frozenset()
            session_reset_map[session_key] = True
            equity_points.append((trade.entry_timestamp.isoformat(), float(equity)))

        positions, session_state, equity = _close_due_intraday_positions(
            adapter=adapter,
            current_positions=positions,
            session_state=session_state,
            config=risk_config,
            current_equity=equity,
            due_before=trade.entry_timestamp,
            open_plans=open_plans,
            executed=executed,
            equity_points=equity_points,
        )
        quantity = compute_demo_quantity(
            trade=trade,
            current_equity=equity,
            risk_per_trade=risk_settings.risk_per_trade,
        )
        if quantity <= ZERO:
            blocked.append(
                BlockedSignalRecord(
                    instrument=result.instrument,
                    signal=signal,
                    entry_timestamp=trade.entry_timestamp,
                    reason_codes=("risk_budget_too_small_for_one_share",),
                    message="Current intraday pilot risk budget cannot support even one share.",
                )
            )
            continue

        entry_price = apply_slippage(
            trade.entry_price,
            direction=trade.direction,
            side="entry",
            slippage_bps=costs.slippage_bps,
        )
        decision = evaluate_order_request(
            signal,
            entry_price=entry_price,
            stop_price=trade.stop_price,
            proposed_quantity=quantity,
            positions=_positions_to_snapshots(positions),
            session_state=session_state,
            config=risk_config,
            market_is_open=_is_regular_session_bar(trade.entry_timestamp.time(), timeframe=trade.timeframe),
        )
        request = ExecutionRequest(
            signal=signal,
            requested_at=trade.entry_timestamp,
            session_key=session_state.session_key,
            entry_price=entry_price,
            stop_price=trade.stop_price,
            target_price=trade.target_price,
            proposed_quantity=quantity,
        )
        execution_result = adapter.submit(
            request,
            risk_decision=decision,
            session_state=session_state,
            positions=positions,
            seen_signal_ids=seen_signal_ids,
        )
        session_state = execution_result.session_state
        positions = execution_result.resulting_positions
        seen_signal_ids = execution_result.resulting_seen_signal_ids

        if execution_result.status != "filled" or execution_result.fill_event is None:
            blocked_reason_codes = (
                execution_result.logs[-1].reason_codes
                if execution_result.logs
                else execution_result.risk_decision.reason_codes
            )
            blocked.append(
                BlockedSignalRecord(
                    instrument=result.instrument,
                    signal=signal,
                    entry_timestamp=trade.entry_timestamp,
                    reason_codes=blocked_reason_codes,
                    message=execution_result.logs[-1].message if execution_result.logs else "Risk blocked the trade.",
                )
            )
            continue

        open_plans[execution_result.fill_event.position_id] = (
            result,
            signal,
            trade,
            execution_result.suggested_order.quantity,
            costs,
        )

    if session_state is not None:
        positions, session_state, equity = _close_due_intraday_positions(
            adapter=adapter,
            current_positions=positions,
            session_state=session_state,
            config=risk_config,
            current_equity=equity,
            due_before=None,
            open_plans=open_plans,
            executed=executed,
            equity_points=equity_points,
        )
    return (
        PaperDemoOutcome(
            executed_trades=tuple(executed),
            blocked_signals=tuple(blocked),
            equity_points=tuple(equity_points),
            ending_equity=equity,
        ),
        session_reset_map,
    )


def build_intraday_no_trade_wait_records(
    session_results: tuple[SymbolBacktestResult, ...],
    paper_outcome: PaperDemoOutcome,
    session_audits: tuple[SessionAudit, ...],
    *,
    instrument: InstrumentConfig,
    timeframe: str,
    timezone_name: str,
) -> tuple[NoTradeWaitRecord, ...]:
    records = list(build_no_trade_wait_records(session_results, paper_outcome))
    zone = ZoneInfo(timezone_name)
    for audit in session_audits:
        if audit.complete:
            continue
        session_end = datetime.combine(date.fromisoformat(audit.session_key), REGULAR_SESSION_CLOSE, tzinfo=zone)
        reason_code = audit.skipped_reason or "data_gap_or_incomplete_session"
        detail_parts = []
        if audit.missing_bar_count:
            detail_parts.append(f"missing_bars={audit.missing_bar_count}")
        if audit.out_of_hours_bar_count:
            detail_parts.append(f"out_of_hours_bars={audit.out_of_hours_bar_count}")
        if audit.duplicate_bar_count:
            detail_parts.append(f"duplicate_bars={audit.duplicate_bar_count}")
        detail = ", ".join(detail_parts) or "session did not satisfy the intraday quality gate"
        records.append(
            NoTradeWaitRecord(
                symbol=instrument.symbol,
                market=instrument.market,
                timeframe=timeframe,
                timestamp=session_end,
                action="wait",
                reason_code=reason_code,
                reason_detail=detail,
                decision_site="intraday_session_quality_gate",
                pa_context="session_quality_gate",
                regime_summary="intraday session skipped before signal generation",
                source_refs=(),
            )
        )
    return tuple(sorted(records, key=lambda item: (item.timestamp, item.reason_code, item.signal_id or "")))


def build_session_summary(
    *,
    session_audits: tuple[SessionAudit, ...],
    session_results: tuple[SymbolBacktestResult, ...],
    paper_outcome: PaperDemoOutcome,
    no_trade_wait_records: tuple[NoTradeWaitRecord, ...],
    session_reset_map: dict[str, bool],
    timezone_name: str,
    session_open: str,
    session_close: str,
    expected_bars_per_session: int,
) -> dict[str, Any]:
    by_session_result = {
        result.bars[0].timestamp.date().isoformat(): result
        for result in session_results
        if result.bars
    }
    no_trade_by_session = defaultdict(list)
    for item in no_trade_wait_records:
        no_trade_by_session[item.timestamp.astimezone(ZoneInfo(timezone_name)).date().isoformat()].append(item)
    executed_by_session = defaultdict(list)
    for item in paper_outcome.executed_trades:
        executed_by_session[item.trade.entry_timestamp.date().isoformat()].append(item)
    blocked_by_session = defaultdict(list)
    for item in paper_outcome.blocked_signals:
        blocked_by_session[item.entry_timestamp.date().isoformat()].append(item)

    sessions: list[dict[str, Any]] = []
    for audit in session_audits:
        result = by_session_result.get(audit.session_key)
        trace_summary = build_knowledge_trace_coverage((result,), PaperDemoOutcome((), (), (), ZERO))["overall"] if result else {
            "curated_signal_pct": "0.0000",
            "statement_signal_pct": "0.0000",
        }
        sessions.append(
            asdict(
                SessionExecutionSummary(
                    session_key=audit.session_key,
                    timezone=timezone_name,
                    session_open=session_open,
                    session_close=session_close,
                    expected_bars=expected_bars_per_session,
                    actual_bars=audit.regular_bar_count,
                    signal_count=len(result.signals) if result else 0,
                    executed_trades=len(executed_by_session[audit.session_key]),
                    blocked_signals=len(blocked_by_session[audit.session_key]),
                    no_trade_wait=len(no_trade_by_session[audit.session_key]),
                    session_reset_applied=session_reset_map.get(audit.session_key, False),
                    missing_bar_count=audit.missing_bar_count,
                    out_of_hours_bar_count=audit.out_of_hours_bar_count,
                    complete=audit.complete,
                    used_for_pilot=audit.used_for_pilot,
                    skipped_reason=audit.skipped_reason,
                    first_bar_timestamp=audit.first_bar_timestamp.isoformat() if audit.first_bar_timestamp else None,
                    last_bar_timestamp=audit.last_bar_timestamp.isoformat() if audit.last_bar_timestamp else None,
                    trace_curated_signal_pct=str(trace_summary["curated_signal_pct"]),
                    trace_statement_signal_pct=str(trace_summary["statement_signal_pct"]),
                )
            )
        )
    return {
        "boundary": "paper/simulated",
        "sessions": sessions,
    }


def build_session_quality_payload(session_audits: tuple[SessionAudit, ...]) -> dict[str, Any]:
    return {
        "boundary": "paper/simulated",
        "overall": {
            "total_sessions": len(session_audits),
            "complete_sessions": sum(1 for audit in session_audits if audit.complete),
            "skipped_sessions": sum(1 for audit in session_audits if not audit.used_for_pilot),
            "missing_bars_total": sum(audit.missing_bar_count for audit in session_audits),
            "out_of_hours_bars_total": sum(audit.out_of_hours_bar_count for audit in session_audits),
            "duplicate_bars_total": sum(audit.duplicate_bar_count for audit in session_audits),
        },
        "sessions": [
            {
                "session_key": audit.session_key,
                "raw_bar_count": audit.raw_bar_count,
                "regular_bar_count": audit.regular_bar_count,
                "expected_bar_count": audit.expected_bar_count,
                "missing_bar_count": audit.missing_bar_count,
                "duplicate_bar_count": audit.duplicate_bar_count,
                "out_of_hours_bar_count": audit.out_of_hours_bar_count,
                "complete": audit.complete,
                "used_for_pilot": audit.used_for_pilot,
                "skipped_reason": audit.skipped_reason,
                "first_bar_timestamp": audit.first_bar_timestamp.isoformat() if audit.first_bar_timestamp else None,
                "last_bar_timestamp": audit.last_bar_timestamp.isoformat() if audit.last_bar_timestamp else None,
            }
            for audit in session_audits
        ],
    }


def build_intraday_summary_payload(
    *,
    config: IntradayPilotConfig,
    dataset: DatasetCacheRecord,
    session_audits: tuple[SessionAudit, ...],
    session_results: tuple[SymbolBacktestResult, ...],
    paper_outcome: PaperDemoOutcome,
    no_trade_wait_records: tuple[NoTradeWaitRecord, ...],
    session_summary: dict[str, Any],
    session_quality: dict[str, Any],
    knowledge_trace_coverage: dict[str, Any],
    run_id: str,
    report_dir: Path,
) -> dict[str, Any]:
    closed_trades = paper_outcome.executed_trades
    total_pnl = sum((item.pnl_cash for item in closed_trades), ZERO)
    ending_equity = paper_outcome.ending_equity
    total_return = _percent((ending_equity - config.risk.starting_capital) / config.risk.starting_capital)
    max_drawdown_cash, max_drawdown_pct = compute_max_drawdown(paper_outcome.equity_points)
    wins = [item for item in closed_trades if item.pnl_cash > ZERO]
    losses = [item for item in closed_trades if item.pnl_cash < ZERO]
    gross_profit = sum((item.pnl_cash for item in wins), ZERO)
    gross_loss = abs(sum((item.pnl_cash for item in losses), ZERO))
    profit_factor = _quantize(gross_profit / gross_loss) if gross_loss > ZERO else None
    win_rate = _percent(Decimal(len(wins)) / Decimal(len(closed_trades))) if closed_trades else ZERO
    best_trades = sorted(closed_trades, key=lambda item: item.pnl_cash, reverse=True)[:5]
    worst_trades = sorted(closed_trades, key=lambda item: item.pnl_cash)[:5]
    blocked_examples = [
        {
            "symbol": item.instrument.symbol,
            "timestamp": item.entry_timestamp.isoformat(),
            "reason_codes": list(item.reason_codes),
            "message": item.message,
        }
        for item in paper_outcome.blocked_signals[:5]
    ]
    no_trade_wait_summary = summarize_no_trade_wait(no_trade_wait_records)
    return {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "title": config.title,
        "description": config.description,
        "boundary": "paper/simulated",
        "symbol": config.instrument.symbol,
        "label": config.instrument.label,
        "market": config.instrument.market,
        "interval": config.interval,
        "time_range": {
            "start": config.start.isoformat(),
            "end": config.end.isoformat(),
        },
        "data_source": dataset.source,
        "cache_csv": serialize_repo_logical_path(dataset.csv_path),
        "cache_metadata": serialize_repo_logical_path(dataset.metadata_path),
        "report_dir": serialize_repo_logical_path(report_dir),
        "session_model": {
            "timezone": config.session.timezone,
            "regular_open": config.session.regular_open,
            "regular_close": config.session.regular_close,
            "expected_bars_per_session": config.session.expected_bars_per_session,
            "allow_extended_hours": config.session.allow_extended_hours,
            "risk_reset_model": "session_key reset per trading day",
            "intraday_position_model": "per-session replay; unfinished positions close at session end_of_data",
        },
        "cost_model": {
            "slippage_bps": _string_decimal(config.costs.slippage_bps),
            "fee_per_order": _string_decimal(config.costs.fee_per_order),
        },
        "core_results": {
            "total_pnl": _string_decimal(total_pnl),
            "ending_equity": _string_decimal(ending_equity),
            "total_return_pct": _string_decimal(total_return),
            "max_drawdown": _string_decimal(max_drawdown_cash),
            "max_drawdown_pct": _string_decimal(max_drawdown_pct),
            "trade_count": len(closed_trades),
            "blocked_signals": len(paper_outcome.blocked_signals),
            "no_trade_wait": len(no_trade_wait_records),
            "win_rate_pct": _string_decimal(win_rate),
            "profit_factor": _string_decimal(profit_factor) if profit_factor is not None else None,
        },
        "session_quality_summary": session_quality["overall"],
        "knowledge_trace_coverage": knowledge_trace_coverage["overall"],
        "no_trade_wait_summary": no_trade_wait_summary,
        "session_count": len(session_audits),
        "sessions_used_for_pilot": sum(1 for audit in session_audits if audit.used_for_pilot),
        "best_trades": [trade_to_summary_row(item) for item in best_trades],
        "worst_trades": [trade_to_summary_row(item) for item in worst_trades],
        "blocked_examples": blocked_examples,
        "session_summary_overview": session_summary["sessions"],
        "limitations": [
            "当前仍处于 paper / simulated 边界，不代表 broker/live/real-money 能力。",
            (
                f"当前 intraday pilot 只覆盖 {config.instrument.symbol} {config.interval} regular session，不包含期权、不包含多标的并发。"
                if not config.session.allow_extended_hours
                else f"当前 intraday pilot 只覆盖 {config.instrument.symbol} {config.interval} 单标的时段回放，不包含期权、不包含多标的并发。"
            ),
            "statement / source_note 仍只进入 knowledge_trace，不参与 trigger。",
            "当前滑点/手续费模型是最小可配置研究模型，不是实盘成交真实性证明。",
        ],
    }


def write_intraday_markdown_report(
    path: Path,
    *,
    summary: dict[str, Any],
    session_summary: dict[str, Any],
    paper_outcome: PaperDemoOutcome,
) -> None:
    trace_coverage = summary["knowledge_trace_coverage"]
    no_trade_wait_summary = summary["no_trade_wait_summary"]
    lines = [
        f"# {summary['title']}",
        "",
        "本报告仅用于单标的 intraday paper validation，仍处于 `paper / simulated` 边界，不代表 broker/live/real-money 能力。",
        "",
        "## 1. 测试范围",
        "",
        f"- 标的：{summary['symbol']} ({summary['label']})",
        f"- 市场：{summary['market']}",
        f"- 周期：{summary['interval']}",
        f"- 时间范围：{summary['time_range']['start']} ~ {summary['time_range']['end']}",
        f"- 数据来源：{summary['data_source']}",
        f"- 本地缓存：`{summary['cache_csv']}`",
        f"- 交易时区：{summary['session_model']['timezone']}",
        f"- 市场时段：{summary['session_model']['regular_open']} ~ {summary['session_model']['regular_close']}",
        "- 交易边界：paper / simulated",
        "- 当前仍未进入期权、broker、live、real-money。",
        "",
        "## 2. 核心结果",
        "",
        f"- 总盈亏：{summary['core_results']['total_pnl']}",
        f"- 总收益率：{summary['core_results']['total_return_pct']}%",
        f"- 最大回撤：{summary['core_results']['max_drawdown']} ({summary['core_results']['max_drawdown_pct']}%)",
        f"- 交易笔数：{summary['core_results']['trade_count']}",
        f"- 胜率：{summary['core_results']['win_rate_pct']}%",
        f"- 盈亏比（profit factor）：{summary['core_results']['profit_factor'] or 'N/A'}",
        f"- 风控拦截信号数：{summary['core_results']['blocked_signals']}",
        f"- no-trade / wait 结构化记录：{summary['core_results']['no_trade_wait']}",
        "",
        "## 3. Session 质量与重置摘要",
        "",
        f"- Session 总数：{summary['session_count']}；用于 pilot：{summary['sessions_used_for_pilot']}",
        f"- 缺失 bar 总数：{summary['session_quality_summary']['missing_bars_total']}",
        f"- 非交易时段 bar 总数：{summary['session_quality_summary']['out_of_hours_bars_total']}",
        f"- 重复 bar 总数：{summary['session_quality_summary']['duplicate_bars_total']}",
        "",
        "| Session | Bars | Signals | 实际执行 | 风控拦截 | no-trade/wait | reset | 完整 | curated trace | statement trace |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: |",
    ]
    for item in session_summary["sessions"]:
        lines.append(
            "| {session_key} | {actual_bars}/{expected_bars} | {signal_count} | {executed_trades} | {blocked_signals} | {no_trade_wait} | {session_reset_applied} | {complete} | {trace_curated_signal_pct}% | {trace_statement_signal_pct}% |".format(
                **item
            )
        )

    lines.extend(
        [
            "",
            "## 4. Knowledge Trace 摘要",
            "",
            f"- trace 非空占比：{trace_coverage['trace_nonempty_pct']}%",
            f"- curated trace 覆盖率：{trace_coverage['curated_signal_pct']}%",
            f"- statement 补充覆盖率：{trace_coverage['statement_signal_pct']}%",
            f"- actual hit family 分布：{_format_counter(trace_coverage['actual_hit_source_family_presence'])}",
            f"- actual evidence family 分布：{_format_counter(trace_coverage['actual_evidence_source_family_presence'])}",
            f"- bundle support family 分布：{_format_counter(trace_coverage['bundle_support_family_presence'])}",
            f"- curated vs statement（按受控 trace item 计）：curated={trace_coverage['curated_vs_statement']['curated_item_pct']}%， statement={trace_coverage['curated_vs_statement']['statement_item_pct']}%",
            "",
            "## 5. no-trade / wait 摘要",
            "",
            f"- 结构化记录总数：{no_trade_wait_summary['total_records']}",
            f"- action 分布：{_format_counter(no_trade_wait_summary['actions'])}",
            f"- reason 分布：{_format_counter(no_trade_wait_summary['reason_counts'])}",
        ]
    )
    if no_trade_wait_summary["examples"]:
        lines.append("- 代表性样本：")
        for item in no_trade_wait_summary["examples"]:
            lines.append(
                f"  - `{item['symbol']}` @ {item['timestamp']}: {item['action']} / {item['reason_code']} ({item['reason_detail']})"
            )

    lines.extend(["", "## 6. 代表性交易", ""])
    representative = list(summary["best_trades"][:2]) + list(summary["worst_trades"][:2])
    if representative:
        for item in representative:
            lines.extend(
                [
                    f"- `{item['symbol']}` {item['direction']} | {item['entry_timestamp']} -> {item['exit_timestamp']}",
                    f"  进场原因：{item['explanation']}",
                    f"  出场原因：{humanize_exit_reason(item['exit_reason'])}",
                    f"  setup/context：`{item['setup_type']}` / `{item['pa_context']}`",
                    f"  actual refs：{' | '.join(item['source_refs']) if item['source_refs'] else '当前没有 actual hit refs'}",
                    f"  bundle support：{' | '.join(item['bundle_support_refs']) if item['bundle_support_refs'] else '当前没有 bundle support refs'}",
                    f"  trace 摘要：{_format_trace_summary(item['knowledge_trace_summary'])}",
                    f"  risk_notes：{' | '.join(item['risk_notes']) if item['risk_notes'] else '当前版本无额外风控注释'}",
                ]
            )
    else:
        lines.append("- 当前没有已完成的 intraday 交易可展示。")

    lines.extend(["", "## 7. 风控拦截样本", ""])
    if summary["blocked_examples"]:
        for item in summary["blocked_examples"]:
            lines.append(
                f"- `{item['symbol']}` @ {item['timestamp']}: {humanize_block_reason(item['reason_codes'])}。{item['message']}"
            )
    else:
        lines.append("- 本轮 intraday pilot 中，没有出现被风控拦截后仍继续成交的情况。")

    lines.extend(["", "## 8. 结论与局限", ""])
    lines.append(
        f"- 结论：在 `{summary['symbol']} {summary['interval']}`、`{summary['time_range']['start']} ~ {summary['time_range']['end']}` 的 regular session pilot 中，"
        f"系统以 paper/simulated 方式完成了 intraday session、risk reset、duplicate protection、slippage/fee、knowledge trace 的最小验证。"
    )
    for item in summary["limitations"]:
        lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_slippage(
    price: Decimal,
    *,
    direction: str,
    side: str,
    slippage_bps: Decimal,
) -> Decimal:
    if slippage_bps <= ZERO:
        return price
    factor = slippage_bps / Decimal("10000")
    if direction == "long":
        multiplier = Decimal("1") + factor if side == "entry" else Decimal("1") - factor
    else:
        multiplier = Decimal("1") - factor if side == "entry" else Decimal("1") + factor
    return _quantize(price * multiplier)


def _close_due_intraday_positions(
    *,
    adapter: PaperBrokerAdapter,
    current_positions: tuple[PaperPosition, ...],
    session_state: SessionRiskState,
    config: RiskConfig,
    current_equity: Decimal,
    due_before: datetime | None,
    open_plans: dict[str, tuple[SymbolBacktestResult, Signal, TradeRecord, Decimal, IntradayCostModel]],
    executed: list[ExecutedTradeRecord],
    equity_points: list[tuple[str, float]],
) -> tuple[tuple[PaperPosition, ...], SessionRiskState, Decimal]:
    if not open_plans:
        return current_positions, session_state, current_equity
    due_ids = [
        position_id
        for position_id, (_, _, trade, _, _) in sorted(
            open_plans.items(),
            key=lambda item: (item[1][2].exit_timestamp, item[1][2].signal_id),
        )
        if due_before is None or trade.exit_timestamp <= due_before
    ]
    positions = current_positions
    next_state = session_state
    equity = current_equity
    for position_id in due_ids:
        result, signal, trade, quantity, costs = open_plans.pop(position_id)
        exit_price = apply_slippage(
            trade.exit_price,
            direction=trade.direction,
            side="exit",
            slippage_bps=costs.slippage_bps,
        )
        close_result = adapter.close_position(
            position_id=position_id,
            exit_price=exit_price,
            closed_at=trade.exit_timestamp,
            positions=positions,
            session_state=next_state,
            config=config,
            exit_reason=trade.exit_reason,
        )
        positions = close_result.resulting_positions
        next_state = close_result.session_state
        fees_total = costs.fee_per_order * Decimal("2")
        net_realized_pnl = close_result.realized_pnl - fees_total
        equity += net_realized_pnl
        executed.append(
            ExecutedTradeRecord(
                instrument=result.instrument,
                signal=signal,
                trade=trade,
                quantity=quantity,
                pnl_cash=net_realized_pnl,
                equity_after_close=equity,
            )
        )
        equity_points.append((trade.exit_timestamp.isoformat(), float(equity)))
    return positions, next_state, equity


def _expected_session_times(timeframe: str) -> set[str]:
    step_minutes = INTRADAY_INTERVAL_TO_MINUTES.get(timeframe)
    if step_minutes is None:
        raise ValueError(f"Unsupported intraday timeframe: {timeframe}")
    current = datetime.combine(date.today(), REGULAR_SESSION_START)
    values = set()
    close = datetime.combine(date.today(), REGULAR_SESSION_CLOSE)
    while current < close:
        values.add(current.time().strftime("%H:%M"))
        current += timedelta(minutes=step_minutes)
    return values


def _is_regular_session_bar(value: time, *, timeframe: str) -> bool:
    return value.strftime("%H:%M") in _expected_session_times(timeframe)


def _iter_trade_candidates(
    results: tuple[SymbolBacktestResult, ...],
) -> list[tuple[SymbolBacktestResult, Signal, TradeRecord]]:
    candidates: list[tuple[SymbolBacktestResult, Signal, TradeRecord]] = []
    for result in results:
        signal_lookup = {signal.signal_id: signal for signal in result.signals}
        for trade in result.backtest_report.trades:
            signal = signal_lookup.get(trade.signal_id)
            if signal is None:
                continue
            candidates.append((result, signal, trade))
    return candidates


def _positions_to_snapshots(positions: tuple[PaperPosition, ...]) -> tuple[PositionSnapshot, ...]:
    return tuple(
        PositionSnapshot(
            symbol=position.symbol,
            quantity=position.quantity,
            market_value=position.market_value,
        )
        for position in positions
    )


def _format_trace_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return "当前版本未提供"
    rendered: list[str] = []
    for item in items[:3]:
        base = f"{item['atom_type']} {item['atom_id']} @ {item['raw_locator']}"
        evidence_summary = item.get("evidence_locator_summary", "")
        if evidence_summary:
            evidence_preview = " / ".join(evidence_summary.split(" | ")[:2])
            base += f" <= {evidence_preview}"
        rendered.append(base)
    return " | ".join(rendered)


def _format_counter(counter_payload: dict[str, Any]) -> str:
    if not counter_payload:
        return "当前没有记录"
    return " | ".join(f"{key}={value}" for key, value in counter_payload.items())


def _flatten_yfinance_frame(frame: Any, ticker: str) -> Any:
    columns = getattr(frame, "columns", ())
    if getattr(columns, "nlevels", 1) == 1:
        return frame
    if ticker in columns.get_level_values(-1):
        return frame.xs(ticker, axis=1, level=-1)
    return frame.droplevel(-1, axis=1)


def _resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT / path


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(QUANT, rounding=ROUND_HALF_UP)


def _percent(value: Decimal) -> Decimal:
    return _quantize(value * HUNDRED)


def _string_decimal(value: Decimal) -> str:
    return format(_quantize(value), "f")
