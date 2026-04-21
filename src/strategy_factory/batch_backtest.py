from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from pathlib import Path
from typing import Any

from src.backtest import BacktestReport, run_backtest
from src.data import OhlcvRow, load_ohlcv_csv
from src.strategy.contracts import Signal


ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = ROOT / "reports" / "strategy_lab"
STRATEGY_FACTORY_ROOT = REPORT_ROOT / "strategy_factory"
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
QUANT = Decimal("0.0001")
PRIMARY_DATASET_SYMBOL = "SPY"
SUPPORTED_TIMEFRAME = "5m"
SPLIT_NAMES = ("in_sample", "validation", "out_of_sample")


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    strategy_id: str
    title: str
    setup_family: str
    test_priority: str
    chart_dependency: str
    source_refs: tuple[str, ...]
    applicable_market: tuple[str, ...]
    timeframe: tuple[str, ...]
    direction: str
    entry_idea: str
    stop_idea: str
    target_idea: str
    invalidation: tuple[str, ...]
    no_trade_conditions: tuple[str, ...]
    parameter_candidates: tuple[str, ...]
    expected_failure_modes: tuple[str, ...]
    data_requirements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EligibilityRecord:
    strategy_id: str
    title: str
    eligibility_status: str
    eligibility_reason: str
    source_family_support_breadth: int
    family_bias_risk: str
    chart_dependency: str
    readiness_gate: str
    wave_assignment: str
    queue_kind: str


@dataclass(frozen=True, slots=True)
class StrategyVariant:
    strategy_id: str
    variant_id: str
    label: str
    rule_overrides: dict[str, str]


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    strategy_id: str
    variant_id: str
    symbol: str
    market: str
    timeframe: str
    timestamp: datetime
    direction: str
    status: str
    reason_code: str
    context_note: str
    setup_note: str
    split_name: str


@dataclass(frozen=True, slots=True)
class VariantResult:
    strategy_id: str
    variant_id: str
    label: str
    bar_count: int
    signal_count: int
    trade_count: int
    closed_trade_count: int
    sample_status: str
    expectancy_r: Decimal
    total_pnl_r: Decimal
    win_rate: Decimal
    max_drawdown_r: Decimal
    split_trade_counts: dict[str, int]
    split_executed_trade_counts: dict[str, int]
    result_status: str
    queue_status: str
    summary_path: Path
    trades_path: Path
    candidate_events_path: Path
    skip_summary_path: Path


def run_strategy_factory_batch_backtest(repo_root: Path | None = None) -> dict[str, Any]:
    resolved_root = repo_root or ROOT
    provider = _load_primary_provider(resolved_root)
    audit = _load_json(resolved_root / "reports/strategy_lab/full_extraction_audit.json")
    corroboration = _load_json(
        resolved_root / "reports/strategy_lab/cross_source_corroboration_final.json"
    )
    catalog = _load_json(resolved_root / "reports/strategy_lab/strategy_catalog.json")
    gaps = _load_json(
        resolved_root / "reports/strategy_lab/unresolved_strategy_extraction_gaps.json"
    )

    strategies = _load_strategies(catalog)
    eligibility = _build_eligibility_matrix(strategies, corroboration)
    eligible_ids = [
        item.strategy_id for item in eligibility if item.eligibility_status == "eligible_for_batch_backtest"
    ]

    dataset_path = _select_primary_intraday_dataset(resolved_root, provider=provider)
    bars = tuple(load_ohlcv_csv(dataset_path))
    split_labels = _build_split_labels(bars)

    run_id = datetime.now(UTC).strftime("m9_strategy_factory_batch_backtest_%Y%m%d_%H%M%S")
    batch_root = resolved_root / "reports/strategy_lab/strategy_factory" / "batch_runs" / run_id
    batch_root.mkdir(parents=True, exist_ok=True)

    executable_spec_queue = _build_executable_spec_queue(eligibility, run_id, dataset_path, provider)
    backtest_queue = _build_backtest_queue(eligibility, run_id, dataset_path, provider)
    _write_json(resolved_root / "reports/strategy_lab/executable_spec_queue.json", executable_spec_queue)
    _write_json(resolved_root / "reports/strategy_lab/backtest_queue.json", backtest_queue)
    _write_json(batch_root / "executable_spec_queue.json", executable_spec_queue)
    _write_json(batch_root / "backtest_queue.json", backtest_queue)
    _write_json(resolved_root / "reports/strategy_lab/backtest_eligibility_matrix.json", {
        "schema_version": "m9-batch-backtest-v10",
        "generated_at": _utc_now(),
        "eligible_count": len(eligible_ids),
        "records": [asdict(item) for item in eligibility],
    })

    results: list[dict[str, Any]] = []
    triage_records: list[dict[str, Any]] = []
    heartbeat_rows: list[dict[str, Any]] = []

    for strategy in strategies:
        strategy_dir = resolved_root / "reports/strategy_lab" / strategy.strategy_id
        strategy_dir.mkdir(parents=True, exist_ok=True)
        variants_dir = strategy_dir / "variants"
        variants_dir.mkdir(parents=True, exist_ok=True)
        _write_executable_spec(strategy_dir / "executable_spec.md", strategy, provider, dataset_path, run_id)
        _write_test_plan(strategy_dir / "test_plan.md", strategy, provider, dataset_path)

        eligibility_record = next(item for item in eligibility if item.strategy_id == strategy.strategy_id)
        if eligibility_record.eligibility_status != "eligible_for_batch_backtest":
            triage_status = (
                "deferred_single_source_risk"
                if eligibility_record.eligibility_status == "deferred_single_source_risk"
                else "parked_needs_visual_review"
            )
            result_payload = _build_deferred_strategy_result(
                strategy=strategy,
                eligibility=eligibility_record,
                strategy_dir=strategy_dir,
                triage_status=triage_status,
                gaps=gaps,
            )
            _write_deferred_artifacts(strategy_dir, result_payload)
            results.append(result_payload)
            triage_records.append(result_payload["triage_record"])
            heartbeat_rows.append(result_payload["heartbeat"])
            continue

        variants = _build_strategy_variants(strategy.strategy_id)
        variant_results: list[VariantResult] = []
        baseline_result: VariantResult | None = None
        best_result: VariantResult | None = None
        for variant in variants:
            candidate_events, signals = _generate_signals_for_variant(
                bars=bars,
                split_labels=split_labels,
                strategy=strategy,
                variant=variant,
                provider=provider,
            )
            report = run_backtest(bars, signals)
            skip_counts = Counter(
                item.reason_code for item in candidate_events if item.status == "skipped"
            )
            variant_dir = variants_dir / variant.variant_id
            variant_dir.mkdir(parents=True, exist_ok=True)
            candidate_path = variant_dir / "candidate_events.csv"
            trades_path = variant_dir / "trades.csv"
            skip_path = variant_dir / "skip_summary.json"
            summary_path = variant_dir / "summary.json"
            _write_candidate_events(candidate_path, candidate_events)
            _write_trade_rows(trades_path, strategy, variant, report)
            _write_json(skip_path, {
                "strategy_id": strategy.strategy_id,
                "variant_id": variant.variant_id,
                "skipped": dict(sorted(skip_counts.items())),
                "total_candidates": len(candidate_events),
                "emitted_signals": len(signals),
            })
            split_trade_counts = _count_split_trades(report, split_labels, closed_only=True)
            split_executed = _count_split_trades(report, split_labels, closed_only=False)
            sample_status = _classify_sample_status(
                trade_count=report.stats.closed_trade_count,
                split_trade_counts=split_trade_counts,
                symbol_count=1,
                regime_count=1,
            )
            variant_result = VariantResult(
                strategy_id=strategy.strategy_id,
                variant_id=variant.variant_id,
                label=variant.label,
                bar_count=len(bars),
                signal_count=len(signals),
                trade_count=report.stats.trade_count,
                closed_trade_count=report.stats.closed_trade_count,
                sample_status=sample_status,
                expectancy_r=report.stats.expectancy_r,
                total_pnl_r=report.stats.total_pnl_r,
                win_rate=report.stats.win_rate,
                max_drawdown_r=report.stats.max_drawdown_r,
                split_trade_counts=split_trade_counts,
                split_executed_trade_counts=split_executed,
                result_status="completed",
                queue_status="completed",
                summary_path=summary_path,
                trades_path=trades_path,
                candidate_events_path=candidate_path,
                skip_summary_path=skip_path,
            )
            _write_json(summary_path, _variant_result_payload(strategy, variant, variant_result, report, dataset_path, provider))
            variant_results.append(variant_result)
            if variant.variant_id == "baseline":
                baseline_result = variant_result
            if best_result is None or _is_better_variant(variant_result, best_result):
                best_result = variant_result

        assert baseline_result is not None
        assert best_result is not None
        triage_status, triage_reason, variant_status_counts = _triage_strategy(
            strategy=strategy,
            baseline=baseline_result,
            best=best_result,
            variant_results=variant_results,
        )
        _promote_baseline_artifacts(strategy_dir, variants_dir / "baseline")
        diagnostics_path = strategy_dir / "diagnostics.md"
        _write_diagnostics(
            diagnostics_path,
            strategy=strategy,
            baseline=baseline_result,
            best=best_result,
            triage_status=triage_status,
            triage_reason=triage_reason,
            variant_results=variant_results,
        )
        strategy_result = {
            "strategy_id": strategy.strategy_id,
            "title": strategy.title,
            "eligibility_status": eligibility_record.eligibility_status,
            "queue_status": "completed",
            "backtest_status": "completed",
            "sample_status": baseline_result.sample_status,
            "triage_status": triage_status,
            "triage_reason": triage_reason,
            "best_variant_id": best_result.variant_id,
            "baseline_variant_id": baseline_result.variant_id,
            "variant_status_counts": variant_status_counts,
            "variants": [
                _variant_public_payload(item) for item in variant_results
            ],
            "artifact_paths": {
                "strategy_dir": _repo_relative(strategy_dir),
                "summary_json": _repo_relative(strategy_dir / "summary.json"),
                "trades_csv": _repo_relative(strategy_dir / "trades.csv"),
                "candidate_events_csv": _repo_relative(strategy_dir / "candidate_events.csv"),
                "skip_summary_json": _repo_relative(strategy_dir / "skip_summary.json"),
                "diagnostics_md": _repo_relative(diagnostics_path),
                "executable_spec_md": _repo_relative(strategy_dir / "executable_spec.md"),
                "test_plan_md": _repo_relative(strategy_dir / "test_plan.md"),
            },
            "dataset_path": _repo_relative(dataset_path),
        }
        _write_json(strategy_dir / "summary.json", {
            "strategy_id": strategy.strategy_id,
            "title": strategy.title,
            "eligibility_status": eligibility_record.eligibility_status,
            "queue_status": "completed",
            "backtest_status": "completed",
            "sample_status": baseline_result.sample_status,
            "triage_status": triage_status,
            "triage_reason": triage_reason,
            "best_variant_id": best_result.variant_id,
            "baseline_variant_id": baseline_result.variant_id,
            "provider": provider,
            "baseline_variant": _variant_public_payload(baseline_result),
            "best_variant": _variant_public_payload(best_result),
            "variants": [_variant_public_payload(item) for item in variant_results],
            "dataset_path": _repo_relative(dataset_path),
            "boundary": "paper/simulated",
        })
        results.append(strategy_result)
        triage_records.append({
            "strategy_id": strategy.strategy_id,
            "title": strategy.title,
            "triage_status": triage_status,
            "triage_reason": triage_reason,
            "sample_status": baseline_result.sample_status,
            "best_variant_id": best_result.variant_id,
            "variant_status_counts": variant_status_counts,
        })
        heartbeat_rows.append({
            "timestamp": _utc_now(),
            "phase": "strategy_backtest_completed",
            "strategy_id": strategy.strategy_id,
            "spec_status": "completed",
            "backtest_status": "completed",
            "sample_status": baseline_result.sample_status,
            "result_status": triage_status,
            "next_action": "batch_triage_consolidation",
        })

    batch_summary = _build_batch_summary(
        run_id=run_id,
        provider=provider,
        dataset_path=dataset_path,
        eligibility=eligibility,
        results=results,
        audit=audit,
    )
    triage_matrix = {
        "schema_version": "m9-batch-backtest-v10",
        "generated_at": _utc_now(),
        "records": triage_records,
    }
    report_path = resolved_root / "reports/strategy_lab/final_strategy_factory_report.md"
    _write_json(resolved_root / "reports/strategy_lab/backtest_batch_summary.json", batch_summary)
    _write_json(batch_root / "backtest_batch_summary.json", batch_summary)
    _write_json(resolved_root / "reports/strategy_lab/strategy_triage_matrix.json", triage_matrix)
    _write_json(batch_root / "strategy_triage_matrix.json", triage_matrix)
    _write_final_report(report_path, batch_summary, triage_matrix, eligibility)
    _append_heartbeat_rows(resolved_root / "reports/strategy_lab/heartbeat.jsonl", heartbeat_rows)
    _write_automation_state(
        resolved_root / "reports/strategy_lab/automation_state.json",
        run_id=run_id,
        provider=provider,
        dataset_path=dataset_path,
        eligibility=eligibility,
        triage_matrix=triage_matrix,
    )
    _update_strategy_factory_ledgers(
        resolved_root=resolved_root,
        run_id=run_id,
        provider=provider,
        eligibility=eligibility,
        results=results,
        triage_matrix=triage_matrix,
        batch_summary=batch_summary,
    )
    return {
        "run_id": run_id,
        "provider": provider,
        "dataset_path": dataset_path,
        "batch_summary": batch_summary,
        "triage_matrix": triage_matrix,
        "report_path": report_path,
    }


def _load_strategies(catalog: dict[str, Any]) -> list[StrategyDefinition]:
    strategies: list[StrategyDefinition] = []
    for item in catalog["strategies"]:
        strategies.append(
            StrategyDefinition(
                strategy_id=item["strategy_id"],
                title=item["title"],
                setup_family=item["setup_family"],
                test_priority=item["test_priority"],
                chart_dependency=item["chart_dependency"],
                source_refs=tuple(item["source_refs"]),
                applicable_market=tuple(item["applicable_market"]),
                timeframe=tuple(item["timeframe"]),
                direction=item["direction"],
                entry_idea=item["entry_idea"],
                stop_idea=item["stop_idea"],
                target_idea=item["target_idea"],
                invalidation=tuple(item["invalidation"]),
                no_trade_conditions=tuple(item["no_trade_conditions"]),
                parameter_candidates=tuple(item["parameter_candidates"]),
                expected_failure_modes=tuple(item["expected_failure_modes"]),
                data_requirements=tuple(item["data_requirements"]),
            )
        )
    return strategies


def _build_eligibility_matrix(
    strategies: list[StrategyDefinition],
    corroboration: dict[str, Any],
) -> list[EligibilityRecord]:
    support_by_id = {
        item["strategy_id"]: item for item in corroboration["families"]
    }
    records: list[EligibilityRecord] = []
    for strategy in strategies:
        support = support_by_id[strategy.strategy_id]
        support_breadth = int(support["source_family_support_breadth"])
        family_bias_risk = support["family_bias_risk"]
        if support_breadth >= 2 and family_bias_risk != "single_source_risk":
            records.append(
                EligibilityRecord(
                    strategy_id=strategy.strategy_id,
                    title=strategy.title,
                    eligibility_status="eligible_for_batch_backtest",
                    eligibility_reason="frozen text-extractable family with multi-source corroboration",
                    source_family_support_breadth=support_breadth,
                    family_bias_risk=family_bias_risk,
                    chart_dependency=strategy.chart_dependency,
                    readiness_gate="ready",
                    wave_assignment="wave_1_baseline_and_wave_2_diagnostics",
                    queue_kind="batch_backtest",
                )
            )
            continue
        if family_bias_risk == "single_source_risk":
            records.append(
                EligibilityRecord(
                    strategy_id=strategy.strategy_id,
                    title=strategy.title,
                    eligibility_status="deferred_single_source_risk",
                    eligibility_reason="single-source corroboration and coarse family boundary",
                    source_family_support_breadth=support_breadth,
                    family_bias_risk=family_bias_risk,
                    chart_dependency=strategy.chart_dependency,
                    readiness_gate="deferred",
                    wave_assignment="deferred_wave",
                    queue_kind="deferred",
                )
            )
            continue
        records.append(
            EligibilityRecord(
                strategy_id=strategy.strategy_id,
                title=strategy.title,
                eligibility_status="parked_needs_visual_review",
                eligibility_reason="not in current frozen executable wave",
                source_family_support_breadth=support_breadth,
                family_bias_risk=family_bias_risk,
                chart_dependency=strategy.chart_dependency,
                readiness_gate="parked",
                wave_assignment="deferred_wave",
                queue_kind="parked",
            )
        )
    return records


def _build_executable_spec_queue(
    eligibility: list[EligibilityRecord],
    run_id: str,
    dataset_path: Path,
    provider: str,
) -> dict[str, Any]:
    return {
        "schema_version": "m9-batch-backtest-v10",
        "generated_at": _utc_now(),
        "run_id": run_id,
        "provider": provider,
        "dataset_path": _repo_relative(dataset_path),
        "items": [
            {
                "strategy_id": item.strategy_id,
                "title": item.title,
                "queue_status": "ready" if item.eligibility_status == "eligible_for_batch_backtest" else "deferred",
                "eligibility_status": item.eligibility_status,
                "eligibility_reason": item.eligibility_reason,
            }
            for item in eligibility
        ],
    }


def _build_backtest_queue(
    eligibility: list[EligibilityRecord],
    run_id: str,
    dataset_path: Path,
    provider: str,
) -> dict[str, Any]:
    queue_items = []
    for item in eligibility:
        if item.eligibility_status == "eligible_for_batch_backtest":
            queue_items.append(
                {
                    "strategy_id": item.strategy_id,
                    "dataset_path": _repo_relative(dataset_path),
                    "provider": provider,
                    "timeframe": SUPPORTED_TIMEFRAME,
                    "variants": ["baseline", "quality_filter"],
                    "queue_status": "pending",
                }
            )
        else:
            queue_items.append(
                {
                    "strategy_id": item.strategy_id,
                    "dataset_path": _repo_relative(dataset_path),
                    "provider": provider,
                    "timeframe": SUPPORTED_TIMEFRAME,
                    "variants": [],
                    "queue_status": "deferred",
                    "deferred_reason": item.eligibility_reason,
                }
            )
    return {
        "schema_version": "m9-batch-backtest-v10",
        "generated_at": _utc_now(),
        "run_id": run_id,
        "items": queue_items,
    }


def _build_strategy_variants(strategy_id: str) -> tuple[StrategyVariant, ...]:
    return (
        StrategyVariant(
            strategy_id=strategy_id,
            variant_id="baseline",
            label="baseline_v0_1",
            rule_overrides={},
        ),
        StrategyVariant(
            strategy_id=strategy_id,
            variant_id="quality_filter",
            label="quality_filter_v0_1",
            rule_overrides={"mode": "quality_filter"},
        ),
    )


def _generate_signals_for_variant(
    *,
    bars: tuple[OhlcvRow, ...],
    split_labels: dict[str, str],
    strategy: StrategyDefinition,
    variant: StrategyVariant,
    provider: str,
) -> tuple[tuple[CandidateEvent, ...], tuple[Signal, ...]]:
    events: list[CandidateEvent] = []
    signals: list[Signal] = []
    last_signal_index_by_direction: dict[str, int] = {}
    for index in range(25, len(bars) - 1):
        bar = bars[index]
        split_name = split_labels[bar.timestamp.date().isoformat()]
        event = _evaluate_strategy_bar(
            bars=bars,
            index=index,
            strategy=strategy,
            variant=variant,
            split_name=split_name,
        )
        events.append(event)
        if event.status != "emitted":
            continue
        cooldown = 6 if strategy.strategy_id in {"SF-002", "SF-003"} else 4
        last_index = last_signal_index_by_direction.get(event.direction)
        if last_index is not None and index - last_index < cooldown:
            events[-1] = CandidateEvent(
                strategy_id=event.strategy_id,
                variant_id=event.variant_id,
                symbol=event.symbol,
                market=event.market,
                timeframe=event.timeframe,
                timestamp=event.timestamp,
                direction=event.direction,
                status="skipped",
                reason_code="cooldown_active",
                context_note=event.context_note,
                setup_note=event.setup_note,
                split_name=event.split_name,
            )
            continue
        last_signal_index_by_direction[event.direction] = index
        signals.append(_build_signal(strategy, bar, event.direction, variant, provider))
    return tuple(events), tuple(signals)


def _evaluate_strategy_bar(
    *,
    bars: tuple[OhlcvRow, ...],
    index: int,
    strategy: StrategyDefinition,
    variant: StrategyVariant,
    split_name: str,
) -> CandidateEvent:
    if strategy.strategy_id == "SF-001":
        status, direction, reason, context_note, setup_note = _evaluate_sf001(bars, index, variant)
    elif strategy.strategy_id == "SF-002":
        status, direction, reason, context_note, setup_note = _evaluate_sf002(bars, index, variant)
    elif strategy.strategy_id == "SF-003":
        status, direction, reason, context_note, setup_note = _evaluate_sf003(bars, index, variant)
    elif strategy.strategy_id == "SF-004":
        status, direction, reason, context_note, setup_note = _evaluate_sf004(bars, index, variant)
    else:
        status, direction, reason, context_note, setup_note = (
            "skipped",
            "both",
            "adapter_missing",
            "strategy not implemented in this wave",
            "deferred by runner",
        )
    bar = bars[index]
    return CandidateEvent(
        strategy_id=strategy.strategy_id,
        variant_id=variant.variant_id,
        symbol=bar.symbol,
        market=bar.market,
        timeframe=bar.timeframe,
        timestamp=bar.timestamp,
        direction=direction,
        status=status,
        reason_code=reason,
        context_note=context_note,
        setup_note=setup_note,
        split_name=split_name,
    )


def _evaluate_sf001(
    bars: tuple[OhlcvRow, ...],
    index: int,
    variant: StrategyVariant,
) -> tuple[str, str, str, str, str]:
    window = bars[index - 10 : index + 1]
    bar = bars[index]
    closes = [item.close for item in window]
    sma_fast = _average(closes[-5:])
    sma_slow = _average(closes[:5])
    pullback = bars[index - 3 : index]
    bullish_pullback_count = sum(1 for item in pullback if item.close < item.open)
    bearish_pullback_count = sum(1 for item in pullback if item.close > item.open)
    body_ratio = _body_ratio(bar)
    close_ratio = _close_ratio(bar)
    threshold = Decimal("0.50") if variant.variant_id == "quality_filter" else Decimal("0.42")
    max_pullback = 2 if variant.variant_id == "quality_filter" else 3
    if sma_fast > sma_slow and bullish_pullback_count and bullish_pullback_count <= max_pullback:
        if bar.close > bars[index - 1].high and body_ratio >= threshold and close_ratio >= Decimal("0.60"):
            return (
                "emitted",
                "long",
                "signal_confirmed",
                "trend context with limited bullish pullback count",
                "second-entry style resumption bar closed above prior high",
            )
        return (
            "skipped",
            "long",
            "weak_signal_bar",
            "trend context with bullish pullback, but signal bar quality is insufficient",
            "signal bar did not close strong enough above prior high",
        )
    if sma_fast < sma_slow and bearish_pullback_count and bearish_pullback_count <= max_pullback:
        if bar.close < bars[index - 1].low and body_ratio >= threshold and close_ratio <= Decimal("0.40"):
            return (
                "emitted",
                "short",
                "signal_confirmed",
                "downtrend context with limited bearish pullback count",
                "second-entry style resumption bar closed below prior low",
            )
        return (
            "skipped",
            "short",
            "weak_signal_bar",
            "downtrend context with bearish pullback, but signal bar quality is insufficient",
            "signal bar did not close strong enough below prior low",
        )
    return (
        "skipped",
        "both",
        "context_not_ready",
        "trend-pullback context was not present",
        "no usable second-entry pullback structure found",
    )


def _evaluate_sf002(
    bars: tuple[OhlcvRow, ...],
    index: int,
    variant: StrategyVariant,
) -> tuple[str, str, str, str, str]:
    prior = bars[index - 1]
    bar = bars[index]
    breakout_window = bars[index - 12 : index - 1]
    long_breakout_level = max(item.high for item in breakout_window)
    short_breakout_level = min(item.low for item in breakout_window)
    prior_body = _body_ratio(prior)
    current_body = _body_ratio(bar)
    threshold = Decimal("0.60") if variant.variant_id == "quality_filter" else Decimal("0.48")
    if prior.close > long_breakout_level and prior_body >= threshold:
        if bar.close > prior.high and current_body >= threshold:
            return (
                "emitted",
                "long",
                "signal_confirmed",
                "prior bar broke above the recent range with follow-through",
                "current bar confirms breakout continuation within the follow-through window",
            )
        return (
            "skipped",
            "long",
            "missing_follow_through",
            "breakout occurred but current bar did not confirm continuation",
            "follow-through cluster quality below threshold",
        )
    if prior.close < short_breakout_level and prior_body >= threshold:
        if bar.close < prior.low and current_body >= threshold:
            return (
                "emitted",
                "short",
                "signal_confirmed",
                "prior bar broke below the recent range with follow-through",
                "current bar confirms breakout continuation within the follow-through window",
            )
        return (
            "skipped",
            "short",
            "missing_follow_through",
            "breakout occurred but current bar did not confirm downside continuation",
            "follow-through cluster quality below threshold",
        )
    return (
        "skipped",
        "both",
        "no_breakout_context",
        "no valid breakout was detected in the prior bar",
        "waiting for a breakout + follow-through cluster",
    )


def _evaluate_sf003(
    bars: tuple[OhlcvRow, ...],
    index: int,
    variant: StrategyVariant,
) -> tuple[str, str, str, str, str]:
    window = bars[index - 20 : index - 1]
    prior = bars[index - 1]
    bar = bars[index]
    if not window:
        return (
            "skipped",
            "both",
            "range_context_missing",
            "insufficient lookback bars for failed-breakout reversal logic",
            "failed breakout reversal requires a completed range lookback before the breakout bar",
        )
    range_high = max(item.high for item in window)
    range_low = min(item.low for item in window)
    avg_range = _average([item.high - item.low for item in window])
    range_height = range_high - range_low
    max_range_multiple = Decimal("6.0") if variant.variant_id == "quality_filter" else Decimal("8.0")
    if avg_range <= ZERO or range_height > avg_range * max_range_multiple:
        return (
            "skipped",
            "both",
            "range_context_missing",
            "prior 20-bar window is too directional for range-edge reversal logic",
            "failed breakout reversal requires a stable trading-range context",
        )
    body_threshold = Decimal("0.55") if variant.variant_id == "quality_filter" else Decimal("0.42")
    if prior.high > range_high and prior.close < range_high and bar.close < prior.low and _body_ratio(bar) >= body_threshold:
        return (
            "emitted",
            "short",
            "signal_confirmed",
            "upside breakout failed back into the range",
            "current bar confirms failed breakout reversal from the range edge",
        )
    if prior.low < range_low and prior.close > range_low and bar.close > prior.high and _body_ratio(bar) >= body_threshold:
        return (
            "emitted",
            "long",
            "signal_confirmed",
            "downside breakout failed back into the range",
            "current bar confirms failed breakout reversal from the range edge",
        )
    return (
        "skipped",
        "both",
        "failed_breakout_not_confirmed",
        "range context exists, but no confirmed failed-breakout reversal is present",
        "waiting for trap + reversal confirmation",
    )


def _evaluate_sf004(
    bars: tuple[OhlcvRow, ...],
    index: int,
    variant: StrategyVariant,
) -> tuple[str, str, str, str, str]:
    window = bars[index - 8 : index + 1]
    bar = bars[index]
    bullish_count = sum(1 for item in window[:-1] if item.close >= item.open)
    bearish_count = sum(1 for item in window[:-1] if item.close <= item.open)
    overlap_ratio = _overlap_ratio(window[:-1])
    max_overlap = Decimal("0.35") if variant.variant_id == "quality_filter" else Decimal("0.48")
    pullback_bars = bars[index - 2 : index]
    if bullish_count >= 6 and overlap_ratio <= max_overlap and any(item.close < item.open for item in pullback_bars):
        if bar.close > bars[index - 1].high and _body_ratio(bar) >= Decimal("0.40"):
            return (
                "emitted",
                "long",
                "signal_confirmed",
                "tight bullish channel with shallow micro pullback",
                "current bar resumes the channel direction after the pullback",
            )
        return (
            "skipped",
            "long",
            "weak_channel_resumption",
            "tight bullish channel detected, but resumption bar is weak",
            "waiting for stronger continuation bar after micro pullback",
        )
    if bearish_count >= 6 and overlap_ratio <= max_overlap and any(item.close > item.open for item in pullback_bars):
        if bar.close < bars[index - 1].low and _body_ratio(bar) >= Decimal("0.40"):
            return (
                "emitted",
                "short",
                "signal_confirmed",
                "tight bearish channel with shallow micro pullback",
                "current bar resumes the channel direction after the pullback",
            )
        return (
            "skipped",
            "short",
            "weak_channel_resumption",
            "tight bearish channel detected, but resumption bar is weak",
            "waiting for stronger continuation bar after micro pullback",
        )
    return (
        "skipped",
        "both",
        "tight_channel_context_missing",
        "tight-channel / Always-In context was not strong enough",
        "waiting for low-overlap channel plus micro-pullback structure",
    )


def _build_signal(
    strategy: StrategyDefinition,
    bar: OhlcvRow,
    direction: str,
    variant: StrategyVariant,
    provider: str,
) -> Signal:
    setup_type = f"{strategy.setup_family}__{variant.variant_id}"
    payload = "|".join(
        [
            setup_type,
            direction,
            bar.symbol,
            bar.market,
            bar.timeframe,
            bar.timestamp.isoformat(),
        ]
    )
    signal_id = sha256(payload.encode("utf-8")).hexdigest()[:16]
    risk_notes = [
        "research-only strategy factory batch backtest",
        "paper/simulated only",
        "trigger logic unchanged; this is an exploratory executable spec proxy",
    ]
    if strategy.strategy_id == "SF-004":
        risk_notes.append("trend day/session filter remains a deferred toggle outside the baseline trigger")
    return Signal(
        signal_id=signal_id,
        symbol=bar.symbol,
        market=bar.market,
        timeframe=bar.timeframe,
        direction=direction,
        setup_type=setup_type,
        pa_context=strategy.setup_family,
        entry_trigger=strategy.entry_idea,
        stop_rule=strategy.stop_idea,
        target_rule=strategy.target_idea,
        invalidation="; ".join(strategy.invalidation),
        confidence="medium",
        source_refs=strategy.source_refs,
        actual_source_refs=strategy.source_refs,
        bundle_support_refs=(),
        explanation=(
            f"{strategy.title} {variant.label} baseline on {SUPPORTED_TIMEFRAME} {provider} intraday cache; "
            f"family={strategy.setup_family}"
        ),
        risk_notes=tuple(risk_notes),
    )


def _count_split_trades(
    report: BacktestReport,
    split_labels: dict[str, str],
    *,
    closed_only: bool,
) -> dict[str, int]:
    counts = {name: 0 for name in SPLIT_NAMES}
    for trade in report.trades:
        if closed_only and trade.exit_reason == "end_of_data":
            continue
        split = split_labels[trade.entry_timestamp.date().isoformat()]
        counts[split] += 1
    return counts


def _classify_sample_status(
    *,
    trade_count: int,
    split_trade_counts: dict[str, int],
    symbol_count: int,
    regime_count: int,
) -> str:
    if trade_count < 60 or any(split_trade_counts[name] < 15 for name in SPLIT_NAMES):
        return "insufficient_sample"
    if trade_count < 100 or any(split_trade_counts[name] < 20 for name in SPLIT_NAMES):
        return "exploratory_probe"
    if symbol_count < 2 and regime_count < 2:
        return "exploratory_probe"
    if trade_count >= 200 and symbol_count >= 2 and regime_count >= 2:
        return "robust_candidate"
    if trade_count >= 100:
        return "formal_candidate"
    return "exploratory_probe"


def _triage_strategy(
    *,
    strategy: StrategyDefinition,
    baseline: VariantResult,
    best: VariantResult,
    variant_results: list[VariantResult],
) -> tuple[str, str, dict[str, int]]:
    variant_status_counts = Counter()
    for item in variant_results:
        if item.variant_id == best.variant_id:
            variant_status_counts["selected_variant"] += 1
        elif _is_better_variant(best, item):
            variant_status_counts["rejected_variant"] += 1
        else:
            variant_status_counts["retain_variant"] += 1

    if baseline.sample_status == "insufficient_sample":
        return (
            "insufficient_sample",
            "baseline trade count or split coverage did not clear the minimum probe gate",
            dict(sorted(variant_status_counts.items())),
        )
    if best.variant_id != baseline.variant_id and (
        best.expectancy_r > baseline.expectancy_r + Decimal("0.05")
        or best.total_pnl_r > baseline.total_pnl_r + Decimal("1.00")
    ):
        return (
            "modify_and_retest",
            "a stricter diagnostic variant materially outperformed the baseline and should guide the next exploratory spec freeze before any broader wave",
            dict(sorted(variant_status_counts.items())),
        )
    if baseline.expectancy_r > ZERO and baseline.total_pnl_r > ZERO:
        return (
            "retain_candidate",
            "baseline remained positive after controlled diagnostics without needing a narrower variant",
            dict(sorted(variant_status_counts.items())),
        )
    return (
        "modify_and_retest",
        "baseline remains exploratory and needs a tighter rule freeze before a larger wave",
        dict(sorted(variant_status_counts.items())),
    )


def _is_better_variant(left: VariantResult, right: VariantResult) -> bool:
    left_score = (left.expectancy_r, left.total_pnl_r, Decimal(left.trade_count))
    right_score = (right.expectancy_r, right.total_pnl_r, Decimal(right.trade_count))
    return left_score > right_score


def _variant_result_payload(
    strategy: StrategyDefinition,
    variant: StrategyVariant,
    result: VariantResult,
    report: BacktestReport,
    dataset_path: Path,
    provider: str,
) -> dict[str, Any]:
    return {
        "strategy_id": strategy.strategy_id,
        "title": strategy.title,
        "variant_id": variant.variant_id,
        "label": variant.label,
        "provider": provider,
        "dataset_path": _repo_relative(dataset_path),
        "timeframe": SUPPORTED_TIMEFRAME,
        "bar_count": result.bar_count,
        "signal_count": result.signal_count,
        "trade_count": result.trade_count,
        "closed_trade_count": result.closed_trade_count,
        "sample_status": result.sample_status,
        "expectancy_r": _string_decimal(result.expectancy_r),
        "total_pnl_r": _string_decimal(result.total_pnl_r),
        "win_rate": _string_decimal(result.win_rate),
        "max_drawdown_r": _string_decimal(result.max_drawdown_r),
        "split_trade_counts": result.split_trade_counts,
        "split_executed_trade_counts": result.split_executed_trade_counts,
        "warnings": list(report.warnings),
        "summary": report.summary,
        "artifact_paths": {
            "summary_json": _repo_relative(result.summary_path),
            "trades_csv": _repo_relative(result.trades_path),
            "candidate_events_csv": _repo_relative(result.candidate_events_path),
            "skip_summary_json": _repo_relative(result.skip_summary_path),
        },
        "boundary": "paper/simulated",
    }


def _variant_public_payload(result: VariantResult) -> dict[str, Any]:
    return {
        "variant_id": result.variant_id,
        "label": result.label,
        "trade_count": result.trade_count,
        "closed_trade_count": result.closed_trade_count,
        "sample_status": result.sample_status,
        "expectancy_r": _string_decimal(result.expectancy_r),
        "total_pnl_r": _string_decimal(result.total_pnl_r),
        "win_rate": _string_decimal(result.win_rate),
        "max_drawdown_r": _string_decimal(result.max_drawdown_r),
        "split_trade_counts": result.split_trade_counts,
        "split_executed_trade_counts": result.split_executed_trade_counts,
        "artifact_paths": {
            "summary_json": _repo_relative(result.summary_path),
            "trades_csv": _repo_relative(result.trades_path),
            "candidate_events_csv": _repo_relative(result.candidate_events_path),
            "skip_summary_json": _repo_relative(result.skip_summary_path),
        },
    }


def _build_deferred_strategy_result(
    *,
    strategy: StrategyDefinition,
    eligibility: EligibilityRecord,
    strategy_dir: Path,
    triage_status: str,
    gaps: dict[str, Any],
) -> dict[str, Any]:
    gap_rows = [
        item
        for item in gaps["gaps"]
        if item["source_family"] in {"al_brooks_ppt", "fangfangtu_notes", "fangfangtu_transcript"}
    ]
    reason = eligibility.eligibility_reason
    return {
        "strategy_id": strategy.strategy_id,
        "title": strategy.title,
        "eligibility_status": eligibility.eligibility_status,
        "queue_status": "deferred",
        "backtest_status": "not_run",
        "sample_status": "not_run",
        "triage_status": triage_status,
        "triage_reason": reason,
        "best_variant_id": None,
        "baseline_variant_id": None,
        "variant_status_counts": {"deferred": 1},
        "variants": [],
        "artifact_paths": {
            "strategy_dir": _repo_relative(strategy_dir),
            "summary_json": _repo_relative(strategy_dir / "summary.json"),
            "trades_csv": _repo_relative(strategy_dir / "trades.csv"),
            "candidate_events_csv": _repo_relative(strategy_dir / "candidate_events.csv"),
            "skip_summary_json": _repo_relative(strategy_dir / "skip_summary.json"),
            "diagnostics_md": _repo_relative(strategy_dir / "diagnostics.md"),
            "executable_spec_md": _repo_relative(strategy_dir / "executable_spec.md"),
            "test_plan_md": _repo_relative(strategy_dir / "test_plan.md"),
        },
        "dataset_path": None,
        "triage_record": {
            "strategy_id": strategy.strategy_id,
            "title": strategy.title,
            "triage_status": triage_status,
            "triage_reason": reason,
            "sample_status": "not_run",
            "best_variant_id": None,
            "variant_status_counts": {"deferred": 1},
        },
        "heartbeat": {
            "timestamp": _utc_now(),
            "phase": "strategy_deferred",
            "strategy_id": strategy.strategy_id,
            "spec_status": "completed",
            "backtest_status": "deferred",
            "sample_status": "not_run",
            "result_status": triage_status,
            "next_action": "deferred_visual_or_corroboration_lane",
        },
        "gap_reference_count": len(gap_rows),
    }


def _write_deferred_artifacts(strategy_dir: Path, payload: dict[str, Any]) -> None:
    _write_json(strategy_dir / "summary.json", payload)
    _write_json(strategy_dir / "skip_summary.json", {
        "strategy_id": payload["strategy_id"],
        "status": payload["triage_status"],
        "reason": payload["triage_reason"],
        "deferred": True,
    })
    _write_candidate_events(strategy_dir / "candidate_events.csv", ())
    _write_text(
        strategy_dir / "diagnostics.md",
        "\n".join(
            [
                f"# {payload['strategy_id']} Deferred Diagnostics",
                "",
                f"- `triage_status`: `{payload['triage_status']}`",
                f"- `reason`: {payload['triage_reason']}",
                f"- `gap_reference_count`: {payload['gap_reference_count']}",
                "",
                "本策略在当前 wave 中不进入 batch backtest。",
                "",
            ]
        ),
    )
    _write_text(
        strategy_dir / "trades.csv",
        "symbol,label,market,direction,entry_timestamp,exit_timestamp,entry_price,exit_price,quantity,pnl_cash,pnl_r,exit_reason,setup_type,entry_trigger,stop_rule,target_rule,actual_source_refs,bundle_support_refs,legacy_source_refs,explanation\n",
    )


def _promote_baseline_artifacts(strategy_dir: Path, baseline_dir: Path) -> None:
    for src_name, dst_name in (
        ("summary.json", "summary.json"),
        ("trades.csv", "trades.csv"),
        ("candidate_events.csv", "candidate_events.csv"),
        ("skip_summary.json", "skip_summary.json"),
    ):
        (strategy_dir / dst_name).write_text((baseline_dir / src_name).read_text(encoding="utf-8"), encoding="utf-8")


def _write_diagnostics(
    path: Path,
    *,
    strategy: StrategyDefinition,
    baseline: VariantResult,
    best: VariantResult,
    triage_status: str,
    triage_reason: str,
    variant_results: list[VariantResult],
) -> None:
    lines = [
        f"# {strategy.strategy_id} Diagnostics",
        "",
        f"- `triage_status`: `{triage_status}`",
        f"- `triage_reason`: {triage_reason}",
        f"- `baseline_variant`: `{baseline.variant_id}`",
        f"- `best_variant`: `{best.variant_id}`",
        "",
        "## Variant Snapshot",
    ]
    for item in variant_results:
        lines.append(
            f"- `{item.variant_id}`: trades={item.trade_count}, sample_status={item.sample_status}, "
            f"expectancy={_string_decimal(item.expectancy_r)}R, pnl={_string_decimal(item.total_pnl_r)}R"
        )
    lines.append("")
    _write_text(path, "\n".join(lines) + "\n")


def _build_batch_summary(
    *,
    run_id: str,
    provider: str,
    dataset_path: Path,
    eligibility: list[EligibilityRecord],
    results: list[dict[str, Any]],
    audit: dict[str, Any],
) -> dict[str, Any]:
    completed = [item for item in results if item["backtest_status"] == "completed"]
    triage_counts = Counter(item["triage_status"] for item in results)
    return {
        "schema_version": "m9-batch-backtest-v10",
        "generated_at": _utc_now(),
        "run_id": run_id,
        "provider": provider,
        "dataset_path": _repo_relative(dataset_path),
        "frozen_strategy_count": audit["final_strategy_card_count"],
        "eligible_strategy_count": sum(
            1 for item in eligibility if item.eligibility_status == "eligible_for_batch_backtest"
        ),
        "tested_strategy_count": len(completed),
        "completed_backtests": len(completed),
        "triage_counts": dict(sorted(triage_counts.items())),
        "results": results,
        "boundary": "paper/simulated",
        "notes": [
            "This wave is a controlled intraday 5m exploratory batch built on the primary-provider cache.",
            "SF-005 remains deferred because the final corroboration report marks it as single_source_risk.",
        ],
    }


def _write_final_report(
    path: Path,
    batch_summary: dict[str, Any],
    triage_matrix: dict[str, Any],
    eligibility: list[EligibilityRecord],
) -> None:
    triage_counts = batch_summary["triage_counts"]
    lines = [
        "# M9 Controlled Batch Backtest + Strategy Triage",
        "",
        f"- `run_id`: `{batch_summary['run_id']}`",
        f"- `provider`: `{batch_summary['provider']}`",
        f"- `dataset_path`: `{batch_summary['dataset_path']}`",
        f"- `frozen_strategy_count`: {batch_summary['frozen_strategy_count']}",
        f"- `eligible_strategy_count`: {batch_summary['eligible_strategy_count']}",
        f"- `tested_strategy_count`: {batch_summary['tested_strategy_count']}",
        "- `boundary`: `paper/simulated`",
        "- `scope`: `exploratory single-symbol intraday batch; not live / not real-money`",
        "",
        "## Triage Counts",
    ]
    for key, value in sorted(triage_counts.items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Eligibility",])
    for item in eligibility:
        lines.append(
            f"- `{item.strategy_id}`: {item.eligibility_status} "
            f"({item.eligibility_reason})"
        )
    lines.extend(["", "## Best Next Wave Candidates"])
    sorted_records = sorted(
        triage_matrix["records"],
        key=lambda item: (
            item["triage_status"] != "retain_candidate",
            item["triage_status"] != "modify_and_retest",
            item["strategy_id"],
        ),
    )
    for item in sorted_records[:5]:
        lines.append(
            f"- `{item['strategy_id']}`: {item['triage_status']} "
            f"({item['triage_reason']})"
        )
    lines.append("")
    _write_text(path, "\n".join(lines) + "\n")


def _append_heartbeat_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_automation_state(
    path: Path,
    *,
    run_id: str,
    provider: str,
    dataset_path: Path,
    eligibility: list[EligibilityRecord],
    triage_matrix: dict[str, Any],
) -> None:
    payload = {
        "schema_version": "m9-batch-backtest-v10",
        "updated_at": _utc_now(),
        "current_phase": "M9H.batch_backtest_triage_completed",
        "run_id": run_id,
        "primary_provider": provider,
        "dataset_path": _repo_relative(dataset_path),
        "eligible_strategy_count": sum(
            1 for item in eligibility if item.eligibility_status == "eligible_for_batch_backtest"
        ),
        "triage_counts": Counter(item["triage_status"] for item in triage_matrix["records"]),
        "next_action": "manual_review_before_next_wave",
        "boundary": "paper/simulated",
    }
    payload["triage_counts"] = dict(sorted(payload["triage_counts"].items()))
    _write_json(path, payload)


def _update_strategy_factory_ledgers(
    *,
    resolved_root: Path,
    run_id: str,
    provider: str,
    eligibility: list[EligibilityRecord],
    results: list[dict[str, Any]],
    triage_matrix: dict[str, Any],
    batch_summary: dict[str, Any],
) -> None:
    strategy_backtest_queue = {
        "schema_version": "m9-batch-backtest-v10",
        "generated_at": _utc_now(),
        "run_id": run_id,
        "ledger_kind": "strategy_factory_backtest_queue",
        "provider": provider,
        "items": [
            {
                "strategy_id": item.strategy_id,
                "queue_status": "completed"
                if item.eligibility_status == "eligible_for_batch_backtest"
                else "deferred",
                "eligibility_status": item.eligibility_status,
                "wave_assignment": item.wave_assignment,
            }
            for item in eligibility
        ],
    }
    _write_json(STRATEGY_FACTORY_ROOT / "backtest_queue.json", strategy_backtest_queue)
    _write_json(
        STRATEGY_FACTORY_ROOT / "triage_ledger.json",
        {
            "schema_version": "m9-batch-backtest-v10",
            "generated_at": _utc_now(),
            "run_id": run_id,
            "ledger_kind": "strategy_factory_triage",
            "records": triage_matrix["records"],
        },
    )
    run_state = _load_json(STRATEGY_FACTORY_ROOT / "run_state.json")
    run_state.update(
        {
            "current_phase": "M9H.batch_backtest_triage_completed",
            "active_batch_id": run_id,
            "primary_provider": provider,
            "last_summary_at": _utc_now(),
        }
    )
    _write_json(STRATEGY_FACTORY_ROOT / "run_state.json", run_state)
    _write_text(
        STRATEGY_FACTORY_ROOT / "final_summary.md",
        "\n".join(
            [
                "# Strategy Factory Batch Backtest Summary",
                "",
                f"- `run_id`: `{run_id}`",
                f"- `provider`: `{provider}`",
                f"- `eligible_strategy_count`: {batch_summary['eligible_strategy_count']}",
                f"- `tested_strategy_count`: {batch_summary['tested_strategy_count']}",
                "",
            ]
        )
        + "\n",
    )


def _write_executable_spec(
    path: Path,
    strategy: StrategyDefinition,
    provider: str,
    dataset_path: Path,
    run_id: str,
) -> None:
    lines = [
        f"# {strategy.strategy_id} Executable Spec",
        "",
        f"- `run_id`: `{run_id}`",
        f"- `setup_family`: `{strategy.setup_family}`",
        f"- `provider`: `{provider}`",
        f"- `dataset_path`: `{_repo_relative(dataset_path)}`",
        f"- `timeframe`: `{SUPPORTED_TIMEFRAME}`",
        f"- `boundary`: `paper/simulated`",
        "",
        "## Entry",
        strategy.entry_idea,
        "",
        "## Stop",
        strategy.stop_idea,
        "",
        "## Target",
        strategy.target_idea,
        "",
        "## Invalidation",
    ]
    lines.extend(f"- {item}" for item in strategy.invalidation)
    lines.extend(["", "## No-Trade"])
    lines.extend(f"- {item}" for item in strategy.no_trade_conditions)
    lines.extend(["", "## Parameter Candidates"])
    lines.extend(f"- {item}" for item in strategy.parameter_candidates)
    lines.extend(["", "## Notes", "- Research-only executable proxy for the controlled batch backtest wave."])
    _write_text(path, "\n".join(lines) + "\n")


def _write_test_plan(
    path: Path,
    strategy: StrategyDefinition,
    provider: str,
    dataset_path: Path,
) -> None:
    lines = [
        f"# {strategy.strategy_id} Test Plan",
        "",
        f"- `provider`: `{provider}`",
        f"- `dataset_path`: `{_repo_relative(dataset_path)}`",
        f"- `timeframe`: `{SUPPORTED_TIMEFRAME}`",
        "- `variants`: `baseline`, `quality_filter`",
        "- `sample gates`: probe>=60 trades with validation/OOS>=15; formal>=100 trades with validation/OOS>=20",
        "",
        "## Data Requirements",
    ]
    lines.extend(f"- {item}" for item in strategy.data_requirements)
    lines.extend(["", "## Expected Failure Modes"])
    lines.extend(f"- {item}" for item in strategy.expected_failure_modes)
    _write_text(path, "\n".join(lines) + "\n")


def _write_candidate_events(path: Path, events: tuple[CandidateEvent, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "strategy_id",
                "variant_id",
                "symbol",
                "market",
                "timeframe",
                "timestamp",
                "direction",
                "status",
                "reason_code",
                "context_note",
                "setup_note",
                "split_name",
            ),
            lineterminator="\n",
        )
        writer.writeheader()
        for item in events:
            writer.writerow(
                {
                    "strategy_id": item.strategy_id,
                    "variant_id": item.variant_id,
                    "symbol": item.symbol,
                    "market": item.market,
                    "timeframe": item.timeframe,
                    "timestamp": item.timestamp.isoformat(),
                    "direction": item.direction,
                    "status": item.status,
                    "reason_code": item.reason_code,
                    "context_note": item.context_note,
                    "setup_note": item.setup_note,
                    "split_name": item.split_name,
                }
            )


def _write_trade_rows(
    path: Path,
    strategy: StrategyDefinition,
    variant: StrategyVariant,
    report: BacktestReport,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "strategy_id",
                "variant_id",
                "symbol",
                "market",
                "direction",
                "entry_timestamp",
                "exit_timestamp",
                "entry_price",
                "exit_price",
                "risk_per_share",
                "pnl_r",
                "exit_reason",
                "setup_type",
                "source_refs",
                "explanation",
            ),
            lineterminator="\n",
        )
        writer.writeheader()
        for trade in report.trades:
            writer.writerow(
                {
                    "strategy_id": strategy.strategy_id,
                    "variant_id": variant.variant_id,
                    "symbol": trade.symbol,
                    "market": trade.market,
                    "direction": trade.direction,
                    "entry_timestamp": trade.entry_timestamp.isoformat(),
                    "exit_timestamp": trade.exit_timestamp.isoformat(),
                    "entry_price": _string_decimal(trade.entry_price),
                    "exit_price": _string_decimal(trade.exit_price),
                    "risk_per_share": _string_decimal(trade.risk_per_share),
                    "pnl_r": _string_decimal(trade.pnl_r),
                    "exit_reason": trade.exit_reason,
                    "setup_type": trade.setup_type,
                    "source_refs": " | ".join(trade.source_refs),
                    "explanation": trade.explanation,
                }
            )


def _select_primary_intraday_dataset(repo_root: Path, *, provider: str) -> Path:
    cache_dir = repo_root / "local_data" / f"{provider}_intraday"
    dataset_glob = f"us_{PRIMARY_DATASET_SYMBOL}_{SUPPORTED_TIMEFRAME}_*.csv"
    candidates = sorted(cache_dir.glob(dataset_glob))
    if not candidates:
        raise FileNotFoundError(
            f"No primary-provider intraday dataset matched {dataset_glob!r} in {cache_dir}"
        )
    return max(candidates, key=lambda item: item.name)


def _build_split_labels(bars: tuple[OhlcvRow, ...]) -> dict[str, str]:
    session_keys = sorted({bar.timestamp.date().isoformat() for bar in bars})
    one_third = max(1, len(session_keys) // 3)
    two_third = max(one_third + 1, (len(session_keys) * 2) // 3)
    labels: dict[str, str] = {}
    for index, key in enumerate(session_keys):
        if index < one_third:
            labels[key] = "in_sample"
        elif index < two_third:
            labels[key] = "validation"
        else:
            labels[key] = "out_of_sample"
    return labels


def _average(values: list[Decimal]) -> Decimal:
    if not values:
        return ZERO
    return sum(values, ZERO) / Decimal(len(values))


def _body_ratio(bar: OhlcvRow) -> Decimal:
    total_range = bar.high - bar.low
    if total_range <= ZERO:
        return ZERO
    return abs(bar.close - bar.open) / total_range


def _close_ratio(bar: OhlcvRow) -> Decimal:
    total_range = bar.high - bar.low
    if total_range <= ZERO:
        return Decimal("0.5")
    return (bar.close - bar.low) / total_range


def _overlap_ratio(bars: tuple[OhlcvRow, ...]) -> Decimal:
    if len(bars) < 2:
        return ZERO
    overlaps: list[Decimal] = []
    for left, right in zip(bars, bars[1:]):
        overlap = min(left.high, right.high) - max(left.low, right.low)
        span = max(left.high, right.high) - min(left.low, right.low)
        if span <= ZERO:
            continue
        overlaps.append(max(ZERO, overlap) / span)
    if not overlaps:
        return ZERO
    return _average(overlaps)


def _repo_relative(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_primary_provider(repo_root: Path) -> str:
    payload = _load_json(repo_root / "config/strategy_factory/active_provider_config.json")
    return str(payload["source_order"][0])


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _string_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(QUANT, rounding=ROUND_HALF_UP))
