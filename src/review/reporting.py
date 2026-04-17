from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from src.backtest.contracts import BacktestReport, TradeRecord
from src.execution.contracts import ExecutionLogEntry
from src.news.contracts import NewsFilterDecision
from src.strategy.contracts import Signal

from .contracts import ReviewItem, ReviewReport, ReviewTradeOutcome


def build_review_report(
    signals: tuple[Signal, ...] | list[Signal],
    news_decisions: tuple[NewsFilterDecision, ...] | list[NewsFilterDecision],
    backtest_report: BacktestReport,
    execution_logs: tuple[ExecutionLogEntry, ...] | list[ExecutionLogEntry] = (),
    *,
    generated_at: datetime | None = None,
) -> ReviewReport:
    decision_by_signal = {decision.signal_id: decision for decision in news_decisions}
    trade_by_signal = {trade.signal_id: trade for trade in backtest_report.trades}
    logs_by_signal: dict[str, list[ExecutionLogEntry]] = defaultdict(list)
    for entry in execution_logs:
        if entry.signal_id:
            logs_by_signal[entry.signal_id].append(entry)

    items = tuple(
        _build_review_item(
            signal=signal,
            decision=decision_by_signal.get(signal.signal_id),
            trade=trade_by_signal.get(signal.signal_id),
            execution_logs=tuple(logs_by_signal.get(signal.signal_id, ())),
        )
        for signal in signals
    )
    warnings = tuple(backtest_report.warnings) + tuple(
        item.trade_outcome.error_reason
        for item in items
        if item.trade_outcome.error_reason
    )
    assumptions = tuple(backtest_report.assumptions) + (
        "News is treated only as filter, explanation, or risk hint.",
    )
    source_refs = tuple(
        dict.fromkeys(
            ref
            for item in items
            for ref in (*item.kb_source_refs, *item.news_source_refs, *item.trade_outcome.evidence_refs)
        )
    )
    generated_at = generated_at or datetime.now(UTC)
    summary = (
        f"Review report for {len(items)} signals; "
        f"{sum(1 for item in items if item.trade_outcome.status == 'closed_trade')} closed trades, "
        f"{sum(1 for item in items if item.trade_outcome.status == 'execution_blocked')} blocked paths, "
        f"{sum(1 for item in items if item.news_outcome == 'block')} high-risk news filters."
    )

    return ReviewReport(
        generated_at=generated_at,
        items=items,
        summary=summary,
        warnings=warnings,
        assumptions=assumptions,
        source_refs=source_refs,
    )


def _build_review_item(
    *,
    signal: Signal,
    decision: NewsFilterDecision | None,
    trade: TradeRecord | None,
    execution_logs: tuple[ExecutionLogEntry, ...],
) -> ReviewItem:
    if decision is None:
        decision = NewsFilterDecision(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            market=signal.market,
            outcome="allow",
            reason_codes=("news_decision_missing",),
            matched_events=(),
            headline_summary=(),
            source_refs=(),
            risk_notes=("No explicit news review decision was provided.",),
            review_notes=(),
        )

    if trade is not None:
        trade_outcome = ReviewTradeOutcome(
            signal_id=signal.signal_id,
            status="closed_trade",
            exit_reason=trade.exit_reason,
            pnl_r=trade.pnl_r,
            error_reason=None,
            evidence_refs=trade.source_refs,
        )
    else:
        blocking_log = next(
            (entry for entry in reversed(execution_logs) if entry.status in {"blocked", "error"}),
            None,
        )
        if blocking_log is not None:
            error_reason = ", ".join(blocking_log.reason_codes) or blocking_log.message
            trade_outcome = ReviewTradeOutcome(
                signal_id=signal.signal_id,
                status="execution_blocked",
                exit_reason=None,
                pnl_r=None,
                error_reason=error_reason,
                evidence_refs=blocking_log.source_refs,
            )
        else:
            trade_outcome = ReviewTradeOutcome(
                signal_id=signal.signal_id,
                status="no_trade",
                exit_reason=None,
                pnl_r=None,
                error_reason=None,
                evidence_refs=(),
            )

    improvement_notes = _build_improvement_notes(decision, trade_outcome)

    return ReviewItem(
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        market=signal.market,
        timeframe=signal.timeframe,
        direction=signal.direction,
        setup_type=signal.setup_type,
        kb_source_refs=signal.source_refs,
        pa_explanation=signal.explanation,
        risk_notes=signal.risk_notes,
        news_outcome=decision.outcome,
        news_headlines=decision.headline_summary,
        news_source_refs=decision.source_refs,
        news_notes=decision.risk_notes,
        news_review_notes=decision.review_notes,
        entry_trigger=signal.entry_trigger,
        stop_rule=signal.stop_rule,
        target_rule=signal.target_rule,
        trade_outcome=trade_outcome,
        improvement_notes=improvement_notes,
        kb_trace=signal.knowledge_trace,
    )


def _build_improvement_notes(
    decision: NewsFilterDecision,
    trade_outcome: ReviewTradeOutcome,
) -> tuple[str, ...]:
    notes: list[str] = []
    if decision.outcome == "block":
        notes.append("Review whether high-risk news should defer the setup entirely.")
    elif decision.outcome == "caution":
        notes.append("Carry forward the news caution into trade review and risk discussion.")

    if trade_outcome.status == "execution_blocked" and trade_outcome.error_reason:
        notes.append(f"Execution was blocked because: {trade_outcome.error_reason}.")
    if trade_outcome.status == "no_trade":
        notes.append("No trade was recorded; confirm whether the setup remained actionable.")
    return tuple(notes)
