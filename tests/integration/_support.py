from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from src.backtest import BacktestReport, run_backtest
from src.data import NewsEvent, OhlcvRow, build_replay, load_news_events, load_ohlcv_csv
from src.execution import ExecutionRequest, ExecutionResult, PaperBrokerAdapter, PositionCloseResult
from src.news import NewsFilterDecision, evaluate_news_context
from src.review import ReviewReport, build_review_report
from src.risk import RiskConfig, RiskDecision, SessionRiskState, evaluate_order_request
from src.strategy import Signal, generate_signals


@dataclass(frozen=True, slots=True)
class OfflinePipelineResult:
    bars: tuple[OhlcvRow, ...]
    news_events: tuple[NewsEvent, ...]
    signals: tuple[Signal, ...]
    backtest_report: BacktestReport
    news_decisions: tuple[NewsFilterDecision, ...]
    risk_decision: RiskDecision | None
    execution_result: ExecutionResult | None
    close_result: PositionCloseResult | None
    review_report: ReviewReport


def trend_csv_payload(*, include_follow_through_bar: bool = True, reverse_rows: bool = False) -> str:
    rows = [
        "symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume",
        "SAMPLE,US,5m,2026-01-05T09:30:00,America/New_York,100.00,100.60,99.80,100.30,100000",
        "SAMPLE,US,5m,2026-01-05T09:35:00,America/New_York,100.30,100.90,100.10,100.70,100000",
        "SAMPLE,US,5m,2026-01-05T09:40:00,America/New_York,100.70,101.40,100.60,101.20,100000",
    ]
    if include_follow_through_bar:
        rows.append(
            "SAMPLE,US,5m,2026-01-05T09:45:00,America/New_York,101.20,102.50,101.00,102.30,100000"
        )
    header, *body = rows
    if reverse_rows:
        body = list(reversed(body))
    return "\n".join([header, *body]) + "\n"


def news_payload(*, current_medium: bool = False, future_critical: bool = False) -> str:
    events: list[dict[str, str]] = []
    if current_medium:
        events.append(
            {
                "symbol": "SAMPLE",
                "market": "US",
                "timestamp": "2026-01-05T09:40:00-05:00",
                "source": "synthetic-news",
                "event_type": "conference",
                "headline": "Conference appearance scheduled",
                "severity": "medium",
                "notes": "Synthetic event for offline M8C integration tests.",
                "timezone": "America/New_York",
            }
        )
    if future_critical:
        events.append(
            {
                "symbol": "SAMPLE",
                "market": "US",
                "timestamp": "2026-01-05T09:50:00-05:00",
                "source": "synthetic-news",
                "event_type": "trading_halt",
                "headline": "Trading halt planned later",
                "severity": "critical",
                "notes": "Future event should not leak into current signal evaluation.",
                "timezone": "America/New_York",
            }
        )
    return json.dumps(events, ensure_ascii=False, indent=2)


def run_offline_pipeline(
    *,
    csv_payload: str,
    news_json: str | None = None,
    proposed_quantity: Decimal = Decimal("1"),
    market_is_open: bool = True,
    close_filled_position: bool = False,
    close_exit_price: Decimal | None = None,
) -> OfflinePipelineResult:
    bars = load_ohlcv_csv(_write_temp_file("bars.csv", csv_payload))
    news_events = load_news_events(_write_temp_file("news.json", news_json)) if news_json is not None else ()

    replay = build_replay(bars, news_events)
    signals = generate_signals(replay)
    backtest_report = run_backtest(bars, signals)

    news_decisions = tuple(
        evaluate_news_context(
            signal,
            news_events,
            reference_timestamp=_signal_reference_timestamp(signal, bars),
        )
        for signal in signals
    )

    risk_decision: RiskDecision | None = None
    execution_result: ExecutionResult | None = None
    close_result: PositionCloseResult | None = None
    execution_logs = ()

    if signals:
        signal = signals[0]
        request = build_execution_request(signal, bars, proposed_quantity=proposed_quantity)
        session_state = SessionRiskState(session_key=request.session_key)
        risk_decision = evaluate_order_request(
            request.signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=(),
            session_state=session_state,
            config=default_risk_config(),
            market_is_open=market_is_open,
        )
        adapter = PaperBrokerAdapter()
        execution_result = adapter.submit(
            request,
            risk_decision=risk_decision,
            session_state=session_state,
            positions=(),
            seen_signal_ids=frozenset(),
        )
        execution_logs = execution_result.logs

        if close_filled_position and execution_result.fill_event is not None:
            close_result = adapter.close_position(
                position_id=execution_result.fill_event.position_id,
                exit_price=close_exit_price or bars[-1].close,
                closed_at=bars[-1].timestamp,
                positions=execution_result.resulting_positions,
                session_state=execution_result.session_state,
                config=default_risk_config(),
                session_key=request.session_key,
                exit_reason="paper_exit",
            )
            execution_logs = execution_logs + close_result.logs

    review_report = build_review_report(
        signals,
        news_decisions,
        backtest_report,
        execution_logs=execution_logs,
    )

    return OfflinePipelineResult(
        bars=bars,
        news_events=tuple(news_events),
        signals=signals,
        backtest_report=backtest_report,
        news_decisions=news_decisions,
        risk_decision=risk_decision,
        execution_result=execution_result,
        close_result=close_result,
        review_report=review_report,
    )


def summarize_pipeline(result: OfflinePipelineResult) -> tuple[object, ...]:
    return (
        tuple(bar.identity_key for bar in result.bars),
        tuple(event.identity_key for event in result.news_events),
        tuple(signal.signal_id for signal in result.signals),
        tuple(signal.source_refs for signal in result.signals),
        tuple(signal.risk_notes for signal in result.signals),
        tuple(decision.outcome for decision in result.news_decisions),
        tuple(decision.reason_codes for decision in result.news_decisions),
        result.backtest_report.stats.trade_count,
        result.backtest_report.stats.closed_trade_count,
        tuple((trade.signal_id, trade.exit_reason, trade.pnl_r) for trade in result.backtest_report.trades),
        None if result.risk_decision is None else result.risk_decision.outcome,
        None if result.execution_result is None else result.execution_result.status,
        ()
        if result.execution_result is None
        else tuple((entry.action, entry.status, entry.reason_codes) for entry in result.execution_result.logs),
        tuple(item.trade_outcome.status for item in result.review_report.items),
        result.review_report.summary,
        result.review_report.source_refs,
    )


def build_execution_request(
    signal: Signal,
    bars: tuple[OhlcvRow, ...],
    *,
    proposed_quantity: Decimal,
) -> ExecutionRequest:
    signal_bar = bars[min(2, len(bars) - 1)]
    entry_bar = bars[min(3, len(bars) - 1)]
    if signal.direction == "long":
        stop_price = signal_bar.low
        target_price = entry_bar.open + ((entry_bar.open - stop_price) * Decimal("2"))
    else:
        stop_price = signal_bar.high
        target_price = entry_bar.open - ((stop_price - entry_bar.open) * Decimal("2"))
    return ExecutionRequest(
        signal=signal,
        requested_at=entry_bar.timestamp,
        session_key=entry_bar.timestamp.date().isoformat(),
        entry_price=entry_bar.open,
        stop_price=stop_price,
        target_price=target_price,
        proposed_quantity=proposed_quantity,
    )


def default_risk_config() -> RiskConfig:
    return RiskConfig(
        max_risk_per_order=Decimal("150"),
        max_total_exposure=Decimal("1000"),
        max_symbol_exposure_ratio=Decimal("1"),
        max_daily_loss=Decimal("200"),
        max_consecutive_losses=2,
        allow_manual_resume_from_loss_streak=True,
    )


def signal_reference_timestamp(bars: tuple[OhlcvRow, ...]) -> datetime:
    return bars[min(2, len(bars) - 1)].timestamp


def _signal_reference_timestamp(signal: Signal, bars: tuple[OhlcvRow, ...]) -> datetime:
    del signal
    return signal_reference_timestamp(bars)


def _write_temp_file(filename: str, content: str) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="pat-m8c-integration-"))
    path = temp_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def synthetic_timestamp(index: int) -> datetime:
    base = datetime(2026, 1, 5, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    return base + timedelta(minutes=index * 5)
