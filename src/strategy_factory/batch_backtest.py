from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from hashlib import sha256
from pathlib import Path
from typing import Any

from scripts.longbridge_history_lib import fetch_longbridge_intraday_history_rows
from src.backtest import BacktestReport, TradeRecord, run_backtest
from src.backtest.engine import _compute_stats
from src.backtest.reporting import build_summary, default_assumptions
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
SCHEMA_VERSION = "m9-batch-backtest-v11"
WAVE2_START = date(2025, 4, 1)
WAVE2_END = date(2026, 4, 21)
WAVE2_SYMBOLS = ("SPY", "QQQ", "NVDA", "TSLA")
DATASET_TIMEZONE = "America/New_York"
DATASET_MARKET = "US"
CASH_STARTING_CAPITAL = Decimal("25000")
CASH_RISK_PER_TRADE = Decimal("100")


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    symbol: str
    market: str
    timeframe: str
    provider: str
    start: date
    end: date
    csv_path: Path
    metadata_path: Path
    row_count: int
    fetch_mode: str


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
    dataset_count: int
    symbol_count: int
    regime_count: int
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

    datasets = _prepare_wave2_datasets(resolved_root, provider=provider)
    dataset_inventory = [_dataset_public_payload(item) for item in datasets]

    run_id = datetime.now(UTC).strftime("m9_strategy_factory_batch_backtest_%Y%m%d_%H%M%S")
    batch_root = resolved_root / "reports/strategy_lab/strategy_factory" / "batch_runs" / run_id
    batch_root.mkdir(parents=True, exist_ok=True)

    executable_spec_queue = _build_executable_spec_queue(
        eligibility,
        run_id,
        datasets=datasets,
        provider=provider,
    )
    backtest_queue = _build_backtest_queue(
        eligibility,
        run_id,
        datasets=datasets,
        provider=provider,
    )
    _write_json(resolved_root / "reports/strategy_lab/executable_spec_queue.json", executable_spec_queue)
    _write_json(resolved_root / "reports/strategy_lab/backtest_queue.json", backtest_queue)
    _write_json(
        resolved_root / "reports/strategy_lab/backtest_dataset_inventory.json",
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "provider": provider,
            "datasets": dataset_inventory,
        },
    )
    _write_json(batch_root / "executable_spec_queue.json", executable_spec_queue)
    _write_json(batch_root / "backtest_queue.json", backtest_queue)
    _write_json(
        batch_root / "backtest_dataset_inventory.json",
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "provider": provider,
            "datasets": dataset_inventory,
        },
    )
    _write_json(resolved_root / "reports/strategy_lab/backtest_eligibility_matrix.json", {
        "schema_version": SCHEMA_VERSION,
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
        _write_executable_spec(strategy_dir / "executable_spec.md", strategy, provider, datasets, run_id)
        _write_test_plan(strategy_dir / "test_plan.md", strategy, provider, datasets)

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
            variant_dir = variants_dir / variant.variant_id
            variant_dir.mkdir(parents=True, exist_ok=True)
            variant_result, aggregated_report = _run_variant_across_datasets(
                resolved_root=resolved_root,
                strategy=strategy,
                variant=variant,
                datasets=datasets,
                provider=provider,
                variant_dir=variant_dir,
            )
            variant_results.append(variant_result)
            if variant.variant_id == "baseline":
                baseline_result = variant_result
            if best_result is None or _is_better_variant(variant_result, best_result):
                best_result = variant_result
            _write_json(
                variant_result.summary_path,
                _variant_result_payload(
                    strategy,
                    variant,
                    variant_result,
                    aggregated_report,
                    datasets,
                    provider,
                ),
            )

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
            "dataset_count": baseline_result.dataset_count,
            "symbol_count": baseline_result.symbol_count,
            "regime_count": baseline_result.regime_count,
            "dataset_paths": [_repo_relative(item.csv_path) for item in datasets],
            "dataset_path": _repo_relative(datasets[0].csv_path),
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
            "dataset_count": baseline_result.dataset_count,
            "symbol_count": baseline_result.symbol_count,
            "regime_count": baseline_result.regime_count,
            "dataset_paths": [_repo_relative(item.csv_path) for item in datasets],
            "dataset_path": _repo_relative(datasets[0].csv_path),
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
        datasets=datasets,
        eligibility=eligibility,
        results=results,
        audit=audit,
    )
    triage_matrix = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "records": triage_records,
    }
    report_path = resolved_root / "reports/strategy_lab/final_strategy_factory_report.md"
    trade_report_path = resolved_root / "reports/strategy_lab/final_strategy_factory_trade_report.md"
    cash_report_path = resolved_root / "reports/strategy_lab/final_strategy_factory_cash_report.md"
    _write_json(resolved_root / "reports/strategy_lab/backtest_batch_summary.json", batch_summary)
    _write_json(batch_root / "backtest_batch_summary.json", batch_summary)
    _write_json(resolved_root / "reports/strategy_lab/strategy_triage_matrix.json", triage_matrix)
    _write_json(batch_root / "strategy_triage_matrix.json", triage_matrix)
    _write_final_report(report_path, batch_summary, triage_matrix, eligibility)
    _write_trading_style_report(trade_report_path, batch_summary)
    _write_trading_style_report(batch_root / "final_strategy_factory_trade_report.md", batch_summary)
    _write_cash_style_report(cash_report_path, batch_summary)
    _write_cash_style_report(batch_root / "final_strategy_factory_cash_report.md", batch_summary)
    _append_heartbeat_rows(resolved_root / "reports/strategy_lab/heartbeat.jsonl", heartbeat_rows)
    _write_automation_state(
        resolved_root / "reports/strategy_lab/automation_state.json",
        run_id=run_id,
        provider=provider,
        datasets=datasets,
        eligibility=eligibility,
        triage_matrix=triage_matrix,
    )
    _update_strategy_factory_ledgers(
        resolved_root=resolved_root,
        run_id=run_id,
        provider=provider,
        datasets=datasets,
        eligibility=eligibility,
        results=results,
        triage_matrix=triage_matrix,
        batch_summary=batch_summary,
    )
    return {
        "run_id": run_id,
        "provider": provider,
        "dataset_path": datasets[0].csv_path,
        "datasets": [item.csv_path for item in datasets],
        "batch_summary": batch_summary,
        "triage_matrix": triage_matrix,
        "report_path": report_path,
        "trade_report_path": trade_report_path,
        "cash_report_path": cash_report_path,
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
    *,
    datasets: list[DatasetRecord],
    provider: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "run_id": run_id,
        "provider": provider,
        "dataset_paths": [_repo_relative(item.csv_path) for item in datasets],
        "symbols": [item.symbol for item in datasets],
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
    *,
    datasets: list[DatasetRecord],
    provider: str,
) -> dict[str, Any]:
    queue_items = []
    for item in eligibility:
        if item.eligibility_status == "eligible_for_batch_backtest":
            queue_items.append(
                {
                    "strategy_id": item.strategy_id,
                    "dataset_paths": [_repo_relative(dataset.csv_path) for dataset in datasets],
                    "symbols": [dataset.symbol for dataset in datasets],
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
                    "dataset_paths": [_repo_relative(dataset.csv_path) for dataset in datasets],
                    "symbols": [dataset.symbol for dataset in datasets],
                    "provider": provider,
                    "timeframe": SUPPORTED_TIMEFRAME,
                    "variants": [],
                    "queue_status": "deferred",
                    "deferred_reason": item.eligibility_reason,
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
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


def _prepare_wave2_datasets(repo_root: Path, *, provider: str) -> list[DatasetRecord]:
    datasets = [
        _ensure_wave2_intraday_dataset(repo_root, provider=provider, symbol=symbol)
        for symbol in WAVE2_SYMBOLS
    ]
    if len(datasets) < 2:
        raise RuntimeError("Wave2 batch backtest requires at least two intraday datasets.")
    return datasets


def _ensure_wave2_intraday_dataset(
    repo_root: Path,
    *,
    provider: str,
    symbol: str,
) -> DatasetRecord:
    cache_dir = repo_root / "local_data" / f"{provider}_intraday"
    cache_dir.mkdir(parents=True, exist_ok=True)
    covering_csv = _find_covering_intraday_dataset(
        cache_dir=cache_dir,
        symbol=symbol,
        provider=provider,
        start=WAVE2_START,
        end=WAVE2_END,
    )
    if covering_csv is not None:
        metadata_path = covering_csv.with_suffix(".metadata.json")
        row_count = len(load_ohlcv_csv(covering_csv))
        return DatasetRecord(
            symbol=symbol,
            market=DATASET_MARKET,
            timeframe=SUPPORTED_TIMEFRAME,
            provider=provider,
            start=WAVE2_START,
            end=WAVE2_END,
            csv_path=covering_csv,
            metadata_path=metadata_path,
            row_count=row_count,
            fetch_mode="local_cache",
        )

    if provider != "longbridge":
        raise FileNotFoundError(
            f"No cached {provider} intraday dataset covers {symbol} {WAVE2_START.isoformat()}~{WAVE2_END.isoformat()}"
        )

    rows = fetch_longbridge_intraday_history_rows(
        ticker=symbol,
        symbol=symbol,
        market=DATASET_MARKET,
        timezone_name=DATASET_TIMEZONE,
        start=WAVE2_START,
        end=WAVE2_END,
        interval=SUPPORTED_TIMEFRAME,
        allow_extended_hours=False,
    )
    rows, anomalies = _sanitize_vendor_rows(rows)
    if not rows:
        raise RuntimeError(
            f"Longbridge returned no usable intraday rows for {symbol} {SUPPORTED_TIMEFRAME} {WAVE2_START}~{WAVE2_END}"
        )

    csv_path = cache_dir / (
        f"{DATASET_MARKET.lower()}_{symbol}_{SUPPORTED_TIMEFRAME}_{WAVE2_START.isoformat()}_{WAVE2_END.isoformat()}_{provider}.csv"
    )
    metadata_path = csv_path.with_suffix(".metadata.json")
    anomaly_path = csv_path.with_suffix(".vendor_anomalies.json")
    _write_intraday_cache_csv(csv_path, rows)
    row_count = len(load_ohlcv_csv(csv_path))
    if anomalies:
        anomaly_path.write_text(json.dumps(anomalies, ensure_ascii=False, indent=2), encoding="utf-8")
    elif anomaly_path.exists():
        anomaly_path.unlink()
    metadata = {
        "instrument": {
            "ticker": symbol,
            "symbol": symbol,
            "market": DATASET_MARKET,
            "timezone": DATASET_TIMEZONE,
        },
        "source": provider,
        "row_count": row_count,
        "start": WAVE2_START.isoformat(),
        "end": WAVE2_END.isoformat(),
        "interval": SUPPORTED_TIMEFRAME,
        "boundary": "paper/simulated",
        "timezone": DATASET_TIMEZONE,
        "regular_session_only": True,
        "downloaded_at": _utc_now(),
        "dropped_invalid_vendor_rows": len(anomalies),
        "vendor_anomalies_path": str(anomaly_path) if anomalies else None,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return DatasetRecord(
        symbol=symbol,
        market=DATASET_MARKET,
        timeframe=SUPPORTED_TIMEFRAME,
        provider=provider,
        start=WAVE2_START,
        end=WAVE2_END,
        csv_path=csv_path,
        metadata_path=metadata_path,
        row_count=row_count,
        fetch_mode="fetched_from_provider",
    )


def _find_covering_intraday_dataset(
    *,
    cache_dir: Path,
    symbol: str,
    provider: str,
    start: date,
    end: date,
) -> Path | None:
    dataset_glob = f"{DATASET_MARKET.lower()}_{symbol}_{SUPPORTED_TIMEFRAME}_*_{provider}.csv"
    covering: list[tuple[date, date, Path]] = []
    for csv_path in cache_dir.glob(dataset_glob):
        parsed = _parse_intraday_cache_name(csv_path)
        if parsed is None:
            continue
        file_start, file_end = parsed
        if file_start <= start and file_end >= end:
            covering.append((file_start, file_end, csv_path))
    if not covering:
        return None
    covering.sort(key=lambda item: ((item[1] - item[0]).days, item[2].name))
    return covering[0][2]


def _parse_intraday_cache_name(path: Path) -> tuple[date, date] | None:
    parts = path.stem.split("_")
    if len(parts) < 6:
        return None
    try:
        return (
            date.fromisoformat(parts[3]),
            date.fromisoformat(parts[4]),
        )
    except ValueError:
        return None


def _write_intraday_cache_csv(path: Path, rows: list[dict[str, str]]) -> None:
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
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _sanitize_vendor_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    sanitized: list[dict[str, str]] = []
    anomalies: list[dict[str, Any]] = []
    for row in rows:
        open_value = Decimal(row["open"])
        high_value = Decimal(row["high"])
        low_value = Decimal(row["low"])
        close_value = Decimal(row["close"])
        if high_value < max(open_value, low_value, close_value) or low_value > min(
            open_value,
            high_value,
            close_value,
        ):
            anomalies.append(
                {
                    "reason": "ohlc_range_inconsistent",
                    "symbol": row["symbol"],
                    "market": row["market"],
                    "timeframe": row["timeframe"],
                    "timestamp": row["timestamp"],
                    "row": row,
                }
            )
            continue
        sanitized.append(row)
    return sanitized, anomalies


def _dataset_public_payload(dataset: DatasetRecord) -> dict[str, Any]:
    return {
        "symbol": dataset.symbol,
        "market": dataset.market,
        "timeframe": dataset.timeframe,
        "provider": dataset.provider,
        "start": dataset.start.isoformat(),
        "end": dataset.end.isoformat(),
        "csv_path": _repo_relative(dataset.csv_path),
        "metadata_path": _repo_relative(dataset.metadata_path),
        "row_count": dataset.row_count,
        "fetch_mode": dataset.fetch_mode,
    }


def _run_variant_across_datasets(
    *,
    resolved_root: Path,
    strategy: StrategyDefinition,
    variant: StrategyVariant,
    datasets: list[DatasetRecord],
    provider: str,
    variant_dir: Path,
) -> tuple[VariantResult, BacktestReport]:
    datasets_dir = variant_dir / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    aggregated_events: list[CandidateEvent] = []
    aggregated_trades: list[TradeRecord] = []
    aggregated_warnings: list[str] = []
    total_bar_count = 0
    total_signal_count = 0
    split_trade_counts = {name: 0 for name in SPLIT_NAMES}
    split_executed_trade_counts = {name: 0 for name in SPLIT_NAMES}
    emitted_symbols: set[str] = set()
    regime_buckets: set[str] = set()
    skipped_reason_counts: Counter[str] = Counter()
    per_dataset_summary: list[dict[str, Any]] = []

    for dataset in datasets:
        bars = tuple(load_ohlcv_csv(dataset.csv_path))
        split_labels = _build_split_labels(bars)
        candidate_events, signals = _generate_signals_for_variant(
            bars=bars,
            split_labels=split_labels,
            strategy=strategy,
            variant=variant,
            provider=provider,
        )
        report = run_backtest(bars, signals)
        dataset_dir = datasets_dir / dataset.symbol
        dataset_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = dataset_dir / "candidate_events.csv"
        trades_path = dataset_dir / "trades.csv"
        skip_path = dataset_dir / "skip_summary.json"
        summary_path = dataset_dir / "summary.json"
        _write_candidate_events(candidate_path, candidate_events)
        _write_trade_rows(trades_path, strategy, variant, report)

        skip_counts = Counter(item.reason_code for item in candidate_events if item.status == "skipped")
        skipped_reason_counts.update(skip_counts)
        closed_split_counts = _count_split_trades(report, split_labels, closed_only=True)
        executed_split_counts = _count_split_trades(report, split_labels, closed_only=False)
        for split_name in SPLIT_NAMES:
            split_trade_counts[split_name] += closed_split_counts[split_name]
            split_executed_trade_counts[split_name] += executed_split_counts[split_name]

        emitted_symbols.update(item.symbol for item in candidate_events if item.status == "emitted")
        for trade in report.trades:
            if trade.exit_reason == "end_of_data":
                continue
            regime_buckets.add(_regime_bucket(trade.entry_timestamp))

        total_bar_count += len(bars)
        total_signal_count += len(signals)
        aggregated_events.extend(candidate_events)
        aggregated_trades.extend(report.trades)
        aggregated_warnings.extend(report.warnings)
        _write_json(
            skip_path,
            {
                "strategy_id": strategy.strategy_id,
                "variant_id": variant.variant_id,
                "symbol": dataset.symbol,
                "dataset_path": _repo_relative(dataset.csv_path),
                "skipped": dict(sorted(skip_counts.items())),
                "total_candidates": len(candidate_events),
                "emitted_signals": len(signals),
            },
        )
        dataset_summary = {
            "strategy_id": strategy.strategy_id,
            "variant_id": variant.variant_id,
            "symbol": dataset.symbol,
            "dataset_path": _repo_relative(dataset.csv_path),
            "provider": provider,
            "timeframe": SUPPORTED_TIMEFRAME,
            "bar_count": len(bars),
            "signal_count": len(signals),
            "trade_count": report.stats.trade_count,
            "closed_trade_count": report.stats.closed_trade_count,
            "expectancy_r": _string_decimal(report.stats.expectancy_r),
            "total_pnl_r": _string_decimal(report.stats.total_pnl_r),
            "win_rate": _string_decimal(report.stats.win_rate),
            "max_drawdown_r": _string_decimal(report.stats.max_drawdown_r),
            "split_trade_counts": closed_split_counts,
            "split_executed_trade_counts": executed_split_counts,
            "warnings": list(report.warnings),
            "summary": report.summary,
            "boundary": "paper/simulated",
        }
        _write_json(summary_path, dataset_summary)
        per_dataset_summary.append(dataset_summary)

    aggregated_events_tuple = tuple(
        sorted(
            aggregated_events,
            key=lambda item: (item.timestamp, item.symbol, item.variant_id, item.reason_code),
        )
    )
    aggregated_trades_tuple = tuple(
        sorted(
            aggregated_trades,
            key=lambda item: (item.exit_timestamp, item.entry_timestamp, item.symbol, item.signal_id),
        )
    )
    aggregated_warnings_tuple = tuple(sorted(set(aggregated_warnings)))
    stats = _compute_stats(
        aggregated_trades_tuple,
        bar_count=total_bar_count,
        signal_count=total_signal_count,
    )
    aggregated_report = BacktestReport(
        trades=aggregated_trades_tuple,
        stats=stats,
        summary=build_summary(stats, aggregated_warnings_tuple),
        warnings=aggregated_warnings_tuple,
        assumptions=default_assumptions(),
    )
    candidate_path = variant_dir / "candidate_events.csv"
    trades_path = variant_dir / "trades.csv"
    skip_path = variant_dir / "skip_summary.json"
    summary_path = variant_dir / "summary.json"
    _write_candidate_events(candidate_path, aggregated_events_tuple)
    _write_trade_rows(trades_path, strategy, variant, aggregated_report)
    _write_json(
        skip_path,
        {
            "strategy_id": strategy.strategy_id,
            "variant_id": variant.variant_id,
            "dataset_count": len(datasets),
            "symbols": [item.symbol for item in datasets],
            "skipped": dict(sorted(skipped_reason_counts.items())),
            "total_candidates": len(aggregated_events_tuple),
            "emitted_signals": total_signal_count,
            "per_dataset": per_dataset_summary,
        },
    )
    sample_status = _classify_sample_status(
        trade_count=aggregated_report.stats.closed_trade_count,
        split_trade_counts=split_trade_counts,
        symbol_count=len(emitted_symbols),
        regime_count=len(regime_buckets),
    )
    variant_result = VariantResult(
        strategy_id=strategy.strategy_id,
        variant_id=variant.variant_id,
        label=variant.label,
        dataset_count=len(datasets),
        symbol_count=len(emitted_symbols),
        regime_count=len(regime_buckets),
        bar_count=total_bar_count,
        signal_count=total_signal_count,
        trade_count=aggregated_report.stats.trade_count,
        closed_trade_count=aggregated_report.stats.closed_trade_count,
        sample_status=sample_status,
        expectancy_r=aggregated_report.stats.expectancy_r,
        total_pnl_r=aggregated_report.stats.total_pnl_r,
        win_rate=aggregated_report.stats.win_rate,
        max_drawdown_r=aggregated_report.stats.max_drawdown_r,
        split_trade_counts=split_trade_counts,
        split_executed_trade_counts=split_executed_trade_counts,
        result_status="completed",
        queue_status="completed",
        summary_path=summary_path,
        trades_path=trades_path,
        candidate_events_path=candidate_path,
        skip_summary_path=skip_path,
    )
    return variant_result, aggregated_report


def _regime_bucket(timestamp: datetime) -> str:
    quarter = ((timestamp.month - 1) // 3) + 1
    return f"{timestamp.year}-Q{quarter}"


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


def _compute_cash_metrics(
    report: BacktestReport,
    *,
    starting_capital: Decimal = CASH_STARTING_CAPITAL,
    risk_per_trade: Decimal = CASH_RISK_PER_TRADE,
) -> dict[str, Any]:
    closed_trades = [
        trade
        for trade in sorted(report.trades, key=lambda item: (item.entry_timestamp, item.exit_timestamp, item.signal_id))
        if trade.exit_reason != "end_of_data"
    ]
    if not closed_trades:
        return {
            "starting_capital": _string_decimal(starting_capital),
            "risk_per_trade": _string_decimal(risk_per_trade),
            "ending_equity": _string_decimal(starting_capital),
            "net_pnl_cash": _string_decimal(ZERO),
            "average_trade_pnl_cash": _string_decimal(ZERO),
            "max_drawdown_cash": _string_decimal(ZERO),
            "profit_factor_cash": None,
            "total_return_pct": _string_decimal(ZERO),
        }

    equity = starting_capital
    peak = starting_capital
    max_drawdown_cash = ZERO
    pnl_cash_values: list[Decimal] = []
    for trade in closed_trades:
        quantity_by_risk = (risk_per_trade / trade.risk_per_share).to_integral_value(rounding=ROUND_DOWN)
        quantity_by_capital = (equity / trade.entry_price).to_integral_value(rounding=ROUND_DOWN)
        quantity = min(quantity_by_risk, quantity_by_capital)
        if quantity <= 0:
            quantity = Decimal("1")
        pnl_cash = _quantize(trade.pnl_per_share * quantity)
        pnl_cash_values.append(pnl_cash)
        equity = _quantize(equity + pnl_cash)
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_drawdown_cash:
            max_drawdown_cash = drawdown

    gross_profit_cash = sum((value for value in pnl_cash_values if value > ZERO), ZERO)
    gross_loss_cash = abs(sum((value for value in pnl_cash_values if value < ZERO), ZERO))
    net_pnl_cash = sum(pnl_cash_values, ZERO)
    average_trade_pnl_cash = _quantize(net_pnl_cash / Decimal(len(pnl_cash_values)))
    total_return_pct = _quantize(((equity - starting_capital) / starting_capital) * HUNDRED)
    return {
        "starting_capital": _string_decimal(starting_capital),
        "risk_per_trade": _string_decimal(risk_per_trade),
        "ending_equity": _string_decimal(equity),
        "net_pnl_cash": _string_decimal(net_pnl_cash),
        "average_trade_pnl_cash": _string_decimal(average_trade_pnl_cash),
        "max_drawdown_cash": _string_decimal(max_drawdown_cash),
        "profit_factor_cash": _string_decimal(gross_profit_cash / gross_loss_cash)
        if gross_loss_cash > ZERO
        else None,
        "total_return_pct": _string_decimal(total_return_pct),
    }


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
    datasets: list[DatasetRecord],
    provider: str,
) -> dict[str, Any]:
    cash_metrics = _compute_cash_metrics(report)
    return {
        "strategy_id": strategy.strategy_id,
        "title": strategy.title,
        "variant_id": variant.variant_id,
        "label": variant.label,
        "provider": provider,
        "dataset_count": result.dataset_count,
        "symbol_count": result.symbol_count,
        "regime_count": result.regime_count,
        "dataset_path": _repo_relative(datasets[0].csv_path),
        "dataset_paths": [_repo_relative(item.csv_path) for item in datasets],
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
        "cash_model": {
            "starting_capital": _string_decimal(CASH_STARTING_CAPITAL),
            "risk_per_trade": _string_decimal(CASH_RISK_PER_TRADE),
        },
        "cash_metrics": cash_metrics,
        "artifact_paths": {
            "summary_json": _repo_relative(result.summary_path),
            "trades_csv": _repo_relative(result.trades_path),
            "candidate_events_csv": _repo_relative(result.candidate_events_path),
            "skip_summary_json": _repo_relative(result.skip_summary_path),
        },
        "boundary": "paper/simulated",
    }


def _variant_public_payload(result: VariantResult) -> dict[str, Any]:
    summary_payload = _load_json(result.summary_path)
    return {
        "variant_id": result.variant_id,
        "label": result.label,
        "dataset_count": result.dataset_count,
        "symbol_count": result.symbol_count,
        "regime_count": result.regime_count,
        "trade_count": result.trade_count,
        "closed_trade_count": result.closed_trade_count,
        "sample_status": result.sample_status,
        "expectancy_r": _string_decimal(result.expectancy_r),
        "total_pnl_r": _string_decimal(result.total_pnl_r),
        "win_rate": _string_decimal(result.win_rate),
        "max_drawdown_r": _string_decimal(result.max_drawdown_r),
        "cash_metrics": summary_payload.get("cash_metrics"),
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
    datasets: list[DatasetRecord],
    eligibility: list[EligibilityRecord],
    results: list[dict[str, Any]],
    audit: dict[str, Any],
) -> dict[str, Any]:
    completed = [item for item in results if item["backtest_status"] == "completed"]
    triage_counts = Counter(item["triage_status"] for item in results)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "run_id": run_id,
        "provider": provider,
        "dataset_path": _repo_relative(datasets[0].csv_path),
        "dataset_paths": [_repo_relative(item.csv_path) for item in datasets],
        "dataset_count": len(datasets),
        "symbols": [item.symbol for item in datasets],
        "coverage_start": min(item.start for item in datasets).isoformat(),
        "coverage_end": max(item.end for item in datasets).isoformat(),
        "frozen_strategy_count": audit["final_strategy_card_count"],
        "eligible_strategy_count": sum(
            1 for item in eligibility if item.eligibility_status == "eligible_for_batch_backtest"
        ),
        "tested_strategy_count": len(completed),
        "completed_backtests": len(completed),
        "cash_model": {
            "starting_capital": _string_decimal(CASH_STARTING_CAPITAL),
            "risk_per_trade": _string_decimal(CASH_RISK_PER_TRADE),
        },
        "triage_counts": dict(sorted(triage_counts.items())),
        "results": results,
        "boundary": "paper/simulated",
        "notes": [
            "This wave is a controlled intraday 5m multi-symbol exploratory batch built on the primary-provider cache.",
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
        f"- `dataset_count`: {batch_summary['dataset_count']}",
        f"- `symbols`: {', '.join(batch_summary['symbols'])}",
        f"- `coverage_window`: `{batch_summary['coverage_start']} ~ {batch_summary['coverage_end']}`",
        f"- `frozen_strategy_count`: {batch_summary['frozen_strategy_count']}",
        f"- `eligible_strategy_count`: {batch_summary['eligible_strategy_count']}",
        f"- `tested_strategy_count`: {batch_summary['tested_strategy_count']}",
        "- `boundary`: `paper/simulated`",
        "- `scope`: `exploratory multi-symbol intraday batch; not live / not real-money`",
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


def _write_trading_style_report(path: Path, batch_summary: dict[str, Any]) -> None:
    lines = [
        "# M9 Trading-Style Batch Report",
        "",
        f"- `run_id`: `{batch_summary['run_id']}`",
        f"- `provider`: `{batch_summary['provider']}`",
        f"- `symbols`: {', '.join(batch_summary['symbols'])}",
        f"- `coverage_window`: `{batch_summary['coverage_start']} ~ {batch_summary['coverage_end']}`",
        f"- `timeframe`: `{SUPPORTED_TIMEFRAME}`",
        "- `capital_model`: `notional capital not modeled in this runner; all PnL is reported in R`",
        "- `boundary`: `paper/simulated`",
        "",
        "| Strategy | Baseline Trades | Baseline Win Rate | Baseline PnL | Baseline Max DD | Best Variant | Best Trades | Best Win Rate | Best PnL | Best Max DD | Sample Status | Triage |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for result in batch_summary["results"]:
        if result["backtest_status"] != "completed":
            lines.append(
                f"| {result['strategy_id']} | 0 | - | - | - | - | 0 | - | - | - | {result['sample_status']} | {result['triage_status']} |"
            )
            continue
        baseline = next(
            item for item in result["variants"] if item["variant_id"] == result["baseline_variant_id"]
        )
        best = next(
            item for item in result["variants"] if item["variant_id"] == result["best_variant_id"]
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    result["strategy_id"],
                    str(baseline["trade_count"]),
                    baseline["win_rate"],
                    f"{baseline['total_pnl_r']}R",
                    f"{baseline['max_drawdown_r']}R",
                    best["variant_id"],
                    str(best["trade_count"]),
                    best["win_rate"],
                    f"{best['total_pnl_r']}R",
                    f"{best['max_drawdown_r']}R",
                    result["sample_status"],
                    result["triage_status"],
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "- 本报告按交易报告口径展示交易笔数、胜率、总盈亏与最大回撤，但当前 runner 仍使用 R 倍数口径，不输出美元本金权益曲线。",
            "- `robust_candidate` 仅表示样本覆盖更充分，不代表稳定盈利、实盘 readiness 或自动交易能力。",
            "",
        ]
    )
    _write_text(path, "\n".join(lines))


def _write_cash_style_report(path: Path, batch_summary: dict[str, Any]) -> None:
    cash_model = batch_summary["cash_model"]
    lines = [
        "# M9 Cash-Equity Batch Report",
        "",
        f"- `run_id`: `{batch_summary['run_id']}`",
        f"- `provider`: `{batch_summary['provider']}`",
        f"- `symbols`: {', '.join(batch_summary['symbols'])}",
        f"- `coverage_window`: `{batch_summary['coverage_start']} ~ {batch_summary['coverage_end']}`",
        f"- `timeframe`: `{SUPPORTED_TIMEFRAME}`",
        f"- `starting_capital`: `${cash_model['starting_capital']}`",
        f"- `risk_per_trade`: `${cash_model['risk_per_trade']}`",
        "- `sizing_rule`: `position_size = min(floor(risk_per_trade / risk_per_share), floor(current_equity / entry_price))`",
        "- `boundary`: `paper/simulated`",
        "",
        "| Strategy | Variant | Trades | Win Rate | Net PnL | Ending Equity | Return | Max DD | Avg Trade | Triage |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in batch_summary["results"]:
        if result["backtest_status"] != "completed":
            lines.append(
                f"| {result['strategy_id']} | - | 0 | - | - | - | - | - | - | {result['triage_status']} |"
            )
            continue
        best = next(
            item for item in result["variants"] if item["variant_id"] == result["best_variant_id"]
        )
        cash = best.get("cash_metrics") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    result["strategy_id"],
                    result["best_variant_id"],
                    str(best["trade_count"]),
                    best["win_rate"],
                    f"${cash.get('net_pnl_cash', '-')}",
                    f"${cash.get('ending_equity', '-')}",
                    f"{cash.get('total_return_pct', '-')}%",
                    f"${cash.get('max_drawdown_cash', '-')}",
                    f"${cash.get('average_trade_pnl_cash', '-')}",
                    result["triage_status"],
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "- 现金口径为研究用途的固定 sizing layer，不改变现有 trigger、risk、execution 或 broker 语义。",
            "- 本报告按每个策略独立账户计算，默认从 `$25,000` 起始、单笔风险预算 `$100`，不模拟策略间资金共享。",
            "- 该层仅用于把 R 倍数结果映射为更直观的美元盈亏/回撤/权益变化，不代表实盘能力。",
            "",
        ]
    )
    _write_text(path, "\n".join(lines))


def _append_heartbeat_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_automation_state(
    path: Path,
    *,
    run_id: str,
    provider: str,
    datasets: list[DatasetRecord],
    eligibility: list[EligibilityRecord],
    triage_matrix: dict[str, Any],
) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _utc_now(),
        "current_phase": "M9H.wave2_batch_backtest_triage_completed",
        "run_id": run_id,
        "primary_provider": provider,
        "dataset_path": _repo_relative(datasets[0].csv_path),
        "dataset_paths": [_repo_relative(item.csv_path) for item in datasets],
        "dataset_count": len(datasets),
        "coverage_start": min(item.start for item in datasets).isoformat(),
        "coverage_end": max(item.end for item in datasets).isoformat(),
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
    datasets: list[DatasetRecord],
    eligibility: list[EligibilityRecord],
    results: list[dict[str, Any]],
    triage_matrix: dict[str, Any],
    batch_summary: dict[str, Any],
) -> None:
    strategy_backtest_queue = {
        "schema_version": SCHEMA_VERSION,
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
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "run_id": run_id,
            "ledger_kind": "strategy_factory_triage",
            "records": triage_matrix["records"],
        },
    )
    run_state = _load_json(STRATEGY_FACTORY_ROOT / "run_state.json")
    run_state.update(
        {
            "current_phase": "M9H.wave2_batch_backtest_triage_completed",
            "active_batch_id": run_id,
            "primary_provider": provider,
            "dataset_count": len(datasets),
            "coverage_start": min(item.start for item in datasets).isoformat(),
            "coverage_end": max(item.end for item in datasets).isoformat(),
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
                f"- `dataset_count`: {len(datasets)}",
                f"- `coverage_window`: `{min(item.start for item in datasets).isoformat()} ~ {max(item.end for item in datasets).isoformat()}`",
                f"- `eligible_strategy_count`: {batch_summary['eligible_strategy_count']}",
                f"- `tested_strategy_count`: {batch_summary['tested_strategy_count']}",
            ]
        )
        + "\n",
    )


def _write_executable_spec(
    path: Path,
    strategy: StrategyDefinition,
    provider: str,
    datasets: list[DatasetRecord],
    run_id: str,
) -> None:
    lines = [
        f"# {strategy.strategy_id} Executable Spec",
        "",
        f"- `run_id`: `{run_id}`",
        f"- `setup_family`: `{strategy.setup_family}`",
        f"- `provider`: `{provider}`",
        f"- `dataset_count`: {len(datasets)}",
        f"- `dataset_paths`: `{', '.join(_repo_relative(item.csv_path) for item in datasets)}`",
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
    datasets: list[DatasetRecord],
) -> None:
    lines = [
        f"# {strategy.strategy_id} Test Plan",
        "",
        f"- `provider`: `{provider}`",
        f"- `dataset_count`: `{len(datasets)}`",
        f"- `symbols`: `{', '.join(item.symbol for item in datasets)}`",
        f"- `coverage_window`: `{min(item.start for item in datasets).isoformat()} ~ {max(item.end for item in datasets).isoformat()}`",
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


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(QUANT, rounding=ROUND_HALF_UP)


def _string_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(_quantize(value))
