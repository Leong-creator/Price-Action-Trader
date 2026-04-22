from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from scripts.longbridge_history_lib import fetch_longbridge_intraday_history_rows
from src.backtest import TradeRecord, run_backtest
from src.backtest.engine import _compute_stats
from src.data import OhlcvRow, load_ohlcv_csv

from .batch_backtest import (
    CASH_RISK_PER_TRADE,
    CASH_STARTING_CAPITAL,
    DATASET_MARKET,
    DATASET_TIMEZONE,
    ROOT,
    SUPPORTED_TIMEFRAME,
    StrategyDefinition,
    StrategyVariant,
    _find_covering_intraday_dataset,
    _generate_signals_for_variant,
    _load_json,
    _load_primary_provider,
    _parse_intraday_cache_name,
    _quantize,
    _repo_relative,
    _sanitize_vendor_rows,
    _string_decimal,
    _utc_now,
    _write_intraday_cache_csv,
    _write_json,
    _write_text,
)


REPORT_ROOT = ROOT / "reports" / "strategy_lab"
STRATEGY_FACTORY_ROOT = REPORT_ROOT / "strategy_factory"
TARGET_START = date(2024, 4, 1)
FREEZE_BOUNDARY = date(2026, 4, 21)
WAVE3_SCHEMA_VERSION = "m9-wave3-robustness-v1"
WAVE3_STRATEGIES = ("SF-001", "SF-002", "SF-003", "SF-004")
WAVE3_SYMBOLS = ("SPY", "QQQ", "NVDA", "TSLA")
WAVE3_TIME_BUCKETS = {
    "open_hour": (9, 30, 10, 30),
    "midday": (10, 30, 13, 30),
    "late_day": (13, 30, 16, 0),
}
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
QUANT = Decimal("0.0001")
EPSILON = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class Wave3Dataset:
    symbol: str
    provider: str
    csv_path: Path
    metadata_path: Path
    fetch_mode: str
    requested_start: date
    requested_end: date
    actual_start: date
    actual_end: date
    row_count: int
    bars: tuple[OhlcvRow, ...]
    session_dates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    window_index: int
    is_sessions: tuple[str, ...]
    oos_sessions: tuple[str, ...]


def run_strategy_factory_wave3_validation(repo_root: Path | None = None) -> dict[str, Any]:
    resolved_root = repo_root or ROOT
    provider = _load_primary_provider(resolved_root)
    spec_paths = _spec_paths(resolved_root)
    specs = [_load_v02_spec(path) for path in spec_paths]
    spec_hashes = {spec["strategy_id"]: _sha256_file(path) for spec, path in zip(specs, spec_paths, strict=True)}
    dataset_target_end = datetime.now(UTC).date()
    datasets = _prepare_wave3_datasets(
        resolved_root,
        provider=provider,
        target_start=TARGET_START,
        target_end=dataset_target_end,
    )
    split_plan = _build_split_plan(datasets)
    run_id = datetime.now(UTC).strftime("m9_wave3_robustness_validation_%Y%m%d_%H%M%S")

    inventory_payload = _build_dataset_inventory_payload(
        run_id=run_id,
        provider=provider,
        datasets=datasets,
        split_plan=split_plan,
    )
    _write_json(REPORT_ROOT / "backtest_dataset_inventory.json", inventory_payload)

    strategy_results: list[dict[str, Any]] = []
    summary_md_rows: list[str] = []
    for spec in specs:
        result = _run_wave3_for_strategy(
            resolved_root=resolved_root,
            provider=provider,
            spec=spec,
            datasets=datasets,
            split_plan=split_plan,
        )
        strategy_results.append(result)
        summary_md_rows.append(
            f"| {result['strategy_id']} | {result['triage_status']} | {result['walk_forward_summary']['window_count']} | "
            f"{result['proxy_holdout_summary']['closed_trades']} | {result['strict_holdout_summary']['closed_trades']} | "
            f"{result['robustness_score']} | {result['triage_reason']} |"
        )

    triage_counts = Counter(item["triage_status"] for item in strategy_results)
    retain_count = sum(1 for item in strategy_results if item["triage_status"] == "retain_candidate")
    strict_holdout_available = bool(split_plan["strict_holdout_sessions"])
    summary_payload = {
        "schema_version": WAVE3_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "run_id": run_id,
        "spec_set": [_repo_relative(path) for path in spec_paths],
        "input_spec_hashes": spec_hashes,
        "provider_contract_ref": "config/strategy_factory/active_provider_config.json#source_order[0]",
        "provider": provider,
        "data_window": {
            "target_start": TARGET_START.isoformat(),
            "target_end": dataset_target_end.isoformat(),
            "actual_common_start": split_plan["common_sessions"][0] if split_plan["common_sessions"] else None,
            "actual_common_end": split_plan["common_sessions"][-1] if split_plan["common_sessions"] else None,
            "common_session_count": len(split_plan["common_sessions"]),
        },
        "strict_holdout_available": strict_holdout_available,
        "split_definition": {
            "freeze_boundary": FREEZE_BOUNDARY.isoformat(),
            "core_history_session_count": len(split_plan["core_history_sessions"]),
            "proxy_holdout_session_count": len(split_plan["proxy_holdout_sessions"]),
            "strict_holdout_session_count": len(split_plan["strict_holdout_sessions"]),
            "walk_forward_window_count": len(split_plan["walk_forward_windows"]),
            "walk_forward_is_sessions": 120,
            "walk_forward_oos_sessions": 40,
            "walk_forward_step_sessions": 20,
        },
        "split_sessions": {
            "core_history_sessions": list(split_plan["core_history_sessions"]),
            "proxy_holdout_sessions": list(split_plan["proxy_holdout_sessions"]),
            "strict_holdout_sessions": list(split_plan["strict_holdout_sessions"]),
            "walk_forward_windows": [
                {
                    "window_index": item.window_index,
                    "is_sessions": list(item.is_sessions),
                    "oos_sessions": list(item.oos_sessions),
                }
                for item in split_plan["walk_forward_windows"]
            ],
        },
        "tested_strategies": [item["strategy_id"] for item in strategy_results],
        "triage_counts": dict(sorted(triage_counts.items())),
        "retain_candidate_count": retain_count,
        "strategies": strategy_results,
    }
    _write_json(REPORT_ROOT / "wave3_robustness_summary.json", summary_payload)
    _write_text(REPORT_ROOT / "wave3_robustness_summary.md", _build_wave3_summary_markdown(summary_payload, summary_md_rows))
    _update_strategy_triage_matrix(REPORT_ROOT / "strategy_triage_matrix.json", strategy_results)
    _update_run_state(provider=provider, split_plan=split_plan, run_id=run_id)
    return {
        "run_id": run_id,
        "provider": provider,
        "summary_path": REPORT_ROOT / "wave3_robustness_summary.json",
        "report_path": REPORT_ROOT / "wave3_robustness_summary.md",
        "triage_counts": dict(sorted(triage_counts.items())),
        "strategies": strategy_results,
        "strict_holdout_available": strict_holdout_available,
        "data_window": summary_payload["data_window"],
    }


def _spec_paths(repo_root: Path) -> tuple[Path, ...]:
    paths = tuple(repo_root / "reports" / "strategy_lab" / "specs" / f"{strategy_id}-v0.2-candidate.yaml" for strategy_id in WAVE3_STRATEGIES)
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Missing frozen wave3 spec: {path}")
    sf005 = repo_root / "reports" / "strategy_lab" / "specs" / "SF-005-v0.2-candidate.yaml"
    if sf005.exists():
        raise RuntimeError("SF-005-v0.2-candidate.yaml must not exist before Wave3 validation.")
    return paths


def _load_v02_spec(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload["strategy_id"] not in WAVE3_STRATEGIES:
        raise RuntimeError(f"Unexpected wave3 strategy id in {path}: {payload['strategy_id']}")
    if payload["spec_version"] != "v0.2-candidate":
        raise RuntimeError(f"{path} is not a v0.2-candidate spec")
    if payload["selected_variant_id"] != "quality_filter":
        raise RuntimeError(f"{path} must be derived from wave2 quality_filter")
    return payload


def _prepare_wave3_datasets(
    repo_root: Path,
    *,
    provider: str,
    target_start: date,
    target_end: date,
) -> list[Wave3Dataset]:
    datasets = [
        _ensure_wave3_intraday_dataset(
            repo_root,
            provider=provider,
            symbol=symbol,
            target_start=target_start,
            target_end=target_end,
        )
        for symbol in WAVE3_SYMBOLS
    ]
    if len(datasets) != len(WAVE3_SYMBOLS):
        raise RuntimeError("Wave3 requires four symbol datasets.")
    return datasets


def _ensure_wave3_intraday_dataset(
    repo_root: Path,
    *,
    provider: str,
    symbol: str,
    target_start: date,
    target_end: date,
) -> Wave3Dataset:
    cache_dir = repo_root / "local_data" / f"{provider}_intraday"
    cache_dir.mkdir(parents=True, exist_ok=True)
    covering_csv = _find_covering_intraday_dataset(
        cache_dir=cache_dir,
        symbol=symbol,
        provider=provider,
        start=target_start,
        end=target_end,
    )
    fetch_mode = "local_cache"
    if covering_csv is None:
        fallback_csv = _best_available_intraday_dataset(
            cache_dir=cache_dir,
            symbol=symbol,
            provider=provider,
        )
        if fallback_csv is not None:
            parsed = _parse_intraday_cache_name(fallback_csv)
            if parsed is not None:
                fallback_start, fallback_end = parsed
                if fallback_end >= FREEZE_BOUNDARY and (fallback_end - fallback_start).days >= 300:
                    covering_csv = fallback_csv
                    metadata_path = covering_csv.with_suffix(".metadata.json")
                    fetch_mode = "local_cache_fallback"
        if covering_csv is not None:
            bars = tuple(load_ohlcv_csv(covering_csv))
            actual_start = min(bar.timestamp.date() for bar in bars)
            actual_end = max(bar.timestamp.date() for bar in bars)
            session_dates = tuple(sorted({bar.timestamp.date().isoformat() for bar in bars}))
            return Wave3Dataset(
                symbol=symbol,
                provider=provider,
                csv_path=covering_csv,
                metadata_path=metadata_path,
                fetch_mode=fetch_mode,
                requested_start=target_start,
                requested_end=target_end,
                actual_start=actual_start,
                actual_end=actual_end,
                row_count=len(bars),
                bars=bars,
                session_dates=session_dates,
            )
        if provider != "longbridge":
            raise FileNotFoundError(
                f"No cached {provider} intraday dataset covers {symbol} {target_start.isoformat()}~{target_end.isoformat()}"
            )
        try:
            rows = fetch_longbridge_intraday_history_rows(
                ticker=symbol,
                symbol=symbol,
                market=DATASET_MARKET,
                timezone_name=DATASET_TIMEZONE,
                start=target_start,
                end=target_end,
                interval=SUPPORTED_TIMEFRAME,
                allow_extended_hours=False,
            )
            rows, anomalies = _sanitize_vendor_rows(rows)
            if not rows:
                raise RuntimeError(
                    f"{provider} returned no usable intraday rows for {symbol} {SUPPORTED_TIMEFRAME} {target_start}~{target_end}"
                )
            covering_csv = cache_dir / (
                f"{DATASET_MARKET.lower()}_{symbol}_{SUPPORTED_TIMEFRAME}_{target_start.isoformat()}_{target_end.isoformat()}_{provider}.csv"
            )
            metadata_path = covering_csv.with_suffix(".metadata.json")
            anomaly_path = covering_csv.with_suffix(".vendor_anomalies.json")
            _write_intraday_cache_csv(covering_csv, rows)
            if anomalies:
                anomaly_path.write_text(json.dumps(anomalies, ensure_ascii=False, indent=2), encoding="utf-8")
            elif anomaly_path.exists():
                anomaly_path.unlink()
            metadata_payload = {
                "instrument": {
                    "ticker": symbol,
                    "symbol": symbol,
                    "market": DATASET_MARKET,
                    "timezone": DATASET_TIMEZONE,
                },
                "source": provider,
                "start": target_start.isoformat(),
                "end": target_end.isoformat(),
                "interval": SUPPORTED_TIMEFRAME,
                "timezone": DATASET_TIMEZONE,
                "regular_session_only": True,
                "downloaded_at": _utc_now(),
                "dropped_invalid_vendor_rows": len(anomalies),
                "vendor_anomalies_path": str(anomaly_path) if anomalies else None,
                "boundary": "paper/simulated",
            }
            metadata_path.write_text(json.dumps(metadata_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            fetch_mode = "fetched_from_provider"
        except RuntimeError:
            covering_csv = _best_available_intraday_dataset(
                cache_dir=cache_dir,
                symbol=symbol,
                provider=provider,
            )
            if covering_csv is None:
                raise
            metadata_path = covering_csv.with_suffix(".metadata.json")
            fetch_mode = "local_cache_fallback"
    else:
        metadata_path = covering_csv.with_suffix(".metadata.json")

    bars = tuple(load_ohlcv_csv(covering_csv))
    if not bars:
        raise RuntimeError(f"Cached dataset is empty: {covering_csv}")
    actual_start = min(bar.timestamp.date() for bar in bars)
    actual_end = max(bar.timestamp.date() for bar in bars)
    session_dates = tuple(sorted({bar.timestamp.date().isoformat() for bar in bars}))
    return Wave3Dataset(
        symbol=symbol,
        provider=provider,
        csv_path=covering_csv,
        metadata_path=metadata_path,
        fetch_mode=fetch_mode,
        requested_start=target_start,
        requested_end=target_end,
        actual_start=actual_start,
        actual_end=actual_end,
        row_count=len(bars),
        bars=bars,
        session_dates=session_dates,
    )


def _best_available_intraday_dataset(
    *,
    cache_dir: Path,
    symbol: str,
    provider: str,
) -> Path | None:
    dataset_glob = f"{DATASET_MARKET.lower()}_{symbol}_{SUPPORTED_TIMEFRAME}_*_{provider}.csv"
    candidates: list[tuple[date, date, Path]] = []
    for csv_path in cache_dir.glob(dataset_glob):
        parsed = _parse_intraday_cache_name(csv_path)
        if parsed is None:
            continue
        start, end = parsed
        candidates.append((start, end, csv_path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: ((item[1] - item[0]).days, item[1].toordinal(), item[2].name))
    return candidates[-1][2]


def _build_split_plan(datasets: list[Wave3Dataset]) -> dict[str, Any]:
    common_sessions = sorted(set(datasets[0].session_dates).intersection(*(set(item.session_dates) for item in datasets[1:])))
    strict_holdout_sessions = tuple(key for key in common_sessions if date.fromisoformat(key) > FREEZE_BOUNDARY)
    pre_freeze_history = tuple(key for key in common_sessions if date.fromisoformat(key) <= FREEZE_BOUNDARY)
    proxy_holdout_sessions = pre_freeze_history[-40:] if len(pre_freeze_history) >= 40 else pre_freeze_history
    core_history_sessions = pre_freeze_history[: max(0, len(pre_freeze_history) - len(proxy_holdout_sessions))]
    walk_forward_windows = _build_walk_forward_windows(core_history_sessions)
    return {
        "common_sessions": tuple(common_sessions),
        "pre_freeze_history": pre_freeze_history,
        "proxy_holdout_sessions": proxy_holdout_sessions,
        "core_history_sessions": core_history_sessions,
        "strict_holdout_sessions": strict_holdout_sessions,
        "walk_forward_windows": walk_forward_windows,
    }


def _build_walk_forward_windows(core_history_sessions: tuple[str, ...]) -> tuple[WalkForwardWindow, ...]:
    is_size = 120
    oos_size = 40
    step = 20
    windows: list[WalkForwardWindow] = []
    if len(core_history_sessions) < is_size + oos_size:
        return ()
    start_index = 0
    window_index = 1
    while start_index + is_size + oos_size <= len(core_history_sessions):
        is_sessions = core_history_sessions[start_index : start_index + is_size]
        oos_sessions = core_history_sessions[start_index + is_size : start_index + is_size + oos_size]
        windows.append(
            WalkForwardWindow(
                window_index=window_index,
                is_sessions=is_sessions,
                oos_sessions=oos_sessions,
            )
        )
        start_index += step
        window_index += 1
    return tuple(windows)


def _run_wave3_for_strategy(
    *,
    resolved_root: Path,
    provider: str,
    spec: dict[str, Any],
    datasets: list[Wave3Dataset],
    split_plan: dict[str, Any],
) -> dict[str, Any]:
    strategy = _strategy_from_spec(spec)
    variant = StrategyVariant(
        strategy_id=strategy.strategy_id,
        variant_id="v0.2-candidate",
        label="v0.2_candidate",
        rule_overrides=dict(spec["rule_overrides"]),
    )
    strategy_wave3_dir = resolved_root / "reports" / "strategy_lab" / strategy.strategy_id / "wave3"
    strategy_wave3_dir.mkdir(parents=True, exist_ok=True)

    common_sessions = set(split_plan["common_sessions"])
    regime_maps: dict[str, dict[str, str]] = {}
    full_events: list[dict[str, Any]] = []
    full_trades: list[TradeRecord] = []
    full_signal_count = 0
    full_bar_count = 0
    symbol_rows: list[dict[str, Any]] = []
    time_bucket_candidates: Counter[str] = Counter()
    time_bucket_executed: Counter[str] = Counter()
    skip_reason_counts: Counter[str] = Counter()

    proxy_trade_subsets: list[TradeRecord] = []
    strict_trade_subsets: list[TradeRecord] = []
    aggregate_oos_trade_subsets: list[TradeRecord] = []
    proxy_candidate_count = 0
    strict_candidate_count = 0
    aggregate_oos_candidate_count = 0

    for dataset in datasets:
        bars = tuple(bar for bar in dataset.bars if bar.timestamp.date().isoformat() in common_sessions)
        split_labels = _build_partition_labels(split_plan)
        regime_maps[dataset.symbol] = _build_session_regimes(bars)
        candidate_events, signals = _generate_signals_for_variant(
            bars=bars,
            split_labels=split_labels,
            strategy=strategy,
            variant=variant,
            provider=provider,
        )
        report = run_backtest(bars, signals)
        full_signal_count += len(signals)
        full_bar_count += len(bars)
        full_events.extend(_event_rows(candidate_events))
        full_trades.extend(report.trades)

        proxy_candidates = [item for item in candidate_events if item.split_name == "proxy_holdout"]
        strict_candidates = [item for item in candidate_events if item.split_name == "strict_post_freeze_holdout"]
        aggregate_candidates = [
            item for item in candidate_events if item.split_name in {"proxy_holdout", "strict_post_freeze_holdout"}
        ]
        proxy_candidate_count += len(proxy_candidates)
        strict_candidate_count += len(strict_candidates)
        aggregate_oos_candidate_count += len(aggregate_candidates)

        proxy_trades = _filter_trades_by_sessions(report.trades, split_plan["proxy_holdout_sessions"], dataset.symbol)
        strict_trades = _filter_trades_by_sessions(report.trades, split_plan["strict_holdout_sessions"], dataset.symbol)
        aggregate_trades = _filter_trades_by_sessions(
            report.trades,
            tuple(sorted(set(split_plan["proxy_holdout_sessions"]) | set(split_plan["strict_holdout_sessions"]))),
            dataset.symbol,
        )
        proxy_trade_subsets.extend(proxy_trades)
        strict_trade_subsets.extend(strict_trades)
        aggregate_oos_trade_subsets.extend(aggregate_trades)

        skip_reason_counts.update(item.reason_code for item in candidate_events if item.status == "skipped")
        executed_trade_count = sum(1 for trade in report.trades if trade.exit_reason != "end_of_data")
        conversion_rate = _ratio_decimal(executed_trade_count, len(candidate_events))
        symbol_metrics = _metrics_payload(
            trades=tuple(aggregate_trades),
            signal_count=len([item for item in aggregate_candidates if item.status == "emitted"]),
            bar_count=len([bar for bar in bars if bar.timestamp.date().isoformat() in set(split_plan["proxy_holdout_sessions"]) | set(split_plan["strict_holdout_sessions"])]),
        )
        symbol_rows.append(
            {
                "symbol": dataset.symbol,
                "closed_trades": symbol_metrics["closed_trades"],
                "total_pnl_r": symbol_metrics["total_pnl_r"],
                "cash_net_pnl": symbol_metrics["cash_net_pnl"],
                "max_drawdown_r": symbol_metrics["max_drawdown_r"],
                "profit_factor": symbol_metrics["profit_factor"],
                "candidate_event_count": len(aggregate_candidates),
                "executed_trade_count": executed_trade_count,
                "conversion_rate": _string_decimal(conversion_rate),
            }
        )

        for event in candidate_events:
            bucket = _time_of_day_bucket(event.timestamp)
            time_bucket_candidates[bucket] += 1
        for trade in report.trades:
            if trade.exit_reason == "end_of_data":
                continue
            bucket = _time_of_day_bucket(trade.entry_timestamp)
            time_bucket_executed[bucket] += 1

    walk_forward_rows = _run_walk_forward_windows(
        strategy=strategy,
        variant=variant,
        datasets=datasets,
        split_plan=split_plan,
        provider=provider,
    )
    walk_forward_summary = _summarize_walk_forward_rows(walk_forward_rows)
    proxy_holdout_summary = _holdout_summary(
        trades=tuple(proxy_trade_subsets),
        candidate_count=proxy_candidate_count,
        session_keys=split_plan["proxy_holdout_sessions"],
        label="proxy_holdout",
    )
    strict_holdout_summary = _holdout_summary(
        trades=tuple(strict_trade_subsets),
        candidate_count=strict_candidate_count,
        session_keys=split_plan["strict_holdout_sessions"],
        label="strict_post_freeze_holdout",
    )
    aggregate_oos_summary = _holdout_summary(
        trades=tuple(aggregate_oos_trade_subsets),
        candidate_count=aggregate_oos_candidate_count,
        session_keys=tuple(sorted(set(split_plan["proxy_holdout_sessions"]) | set(split_plan["strict_holdout_sessions"]))),
        label="aggregate_oos",
    )
    regime_rows = _build_regime_breakdown(tuple(aggregate_oos_trade_subsets), regime_maps)
    time_of_day_rows = _build_time_of_day_breakdown(tuple(aggregate_oos_trade_subsets), tuple(full_events))
    conversion_summary = _build_conversion_summary(
        symbol_rows=symbol_rows,
        time_bucket_candidates=time_bucket_candidates,
        time_bucket_executed=time_bucket_executed,
        skip_reason_counts=skip_reason_counts,
        total_candidates=len(full_events),
        total_executed=sum(1 for trade in full_trades if trade.exit_reason != "end_of_data"),
    )
    cost_stress_summary = _build_cost_stress_summary(
        proxy_trades=tuple(proxy_trade_subsets),
        strict_trades=tuple(strict_trade_subsets),
        aggregate_oos_trades=tuple(aggregate_oos_trade_subsets),
    )
    symbol_breadth_summary = _summarize_symbol_breadth(symbol_rows)
    regime_breadth_summary = _summarize_regime_breadth(regime_rows)
    time_of_day_summary = _summarize_time_breadth(time_of_day_rows)
    robustness_score = _compute_robustness_score(
        strict_holdout_summary=strict_holdout_summary,
        proxy_holdout_summary=proxy_holdout_summary,
        walk_forward_summary=walk_forward_summary,
        symbol_breadth_summary=symbol_breadth_summary,
        regime_breadth_summary=regime_breadth_summary,
        time_of_day_summary=time_of_day_summary,
        cost_stress_summary=cost_stress_summary,
        conversion_summary=conversion_summary,
    )
    triage_status, triage_reason = _triage_wave3_strategy(
        strict_holdout_summary=strict_holdout_summary,
        aggregate_oos_summary=aggregate_oos_summary,
        walk_forward_summary=walk_forward_summary,
        symbol_breadth_summary=symbol_breadth_summary,
        regime_breadth_summary=regime_breadth_summary,
        cost_stress_summary=cost_stress_summary,
        robustness_score=robustness_score,
        strict_holdout_available=bool(split_plan["strict_holdout_sessions"]),
    )

    summary_payload = {
        "strategy_id": strategy.strategy_id,
        "title": strategy.title,
        "spec_ref": _repo_relative(Path(spec["base_spec_ref"]).with_name(f"{strategy.strategy_id}-v0.2-candidate.yaml")),
        "spec_version": "v0.2-candidate",
        "provider": provider,
        "triage_status": triage_status,
        "triage_reason": triage_reason,
        "strict_holdout_available": bool(split_plan["strict_holdout_sessions"]),
        "strict_holdout_summary": strict_holdout_summary,
        "proxy_holdout_summary": proxy_holdout_summary,
        "aggregate_oos_summary": aggregate_oos_summary,
        "walk_forward_summary": walk_forward_summary,
        "symbol_breadth_summary": symbol_breadth_summary,
        "regime_breadth_summary": regime_breadth_summary,
        "time_of_day_summary": time_of_day_summary,
        "cost_stress_summary": cost_stress_summary,
        "conversion_summary": conversion_summary,
        "robustness_score": robustness_score,
        "r_cash_explanation": _r_cash_explanation(aggregate_oos_summary),
    }

    _write_json(strategy_wave3_dir / "summary.json", summary_payload)
    _write_json(
        strategy_wave3_dir / "holdout_summary.json",
        {
            "strict_holdout_summary": strict_holdout_summary,
            "proxy_holdout_summary": proxy_holdout_summary,
            "aggregate_oos_summary": aggregate_oos_summary,
        },
    )
    _write_csv(strategy_wave3_dir / "walk_forward_windows.csv", walk_forward_rows)
    _write_csv(strategy_wave3_dir / "symbol_breakdown.csv", symbol_rows)
    _write_csv(strategy_wave3_dir / "regime_breakdown.csv", regime_rows)
    _write_csv(strategy_wave3_dir / "time_of_day_breakdown.csv", time_of_day_rows)
    _write_json(strategy_wave3_dir / "cost_stress.json", cost_stress_summary)
    _write_json(strategy_wave3_dir / "conversion_analysis.json", conversion_summary)
    return summary_payload


def _strategy_from_spec(spec: dict[str, Any]) -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id=spec["strategy_id"],
        title=spec["title"],
        setup_family=spec["setup_family"],
        test_priority=spec["test_priority"],
        chart_dependency=spec["chart_dependency"],
        source_refs=tuple(spec["source_refs"]),
        applicable_market=tuple(spec["applicable_market"]),
        timeframe=tuple(spec["timeframe"]),
        direction=spec["direction"],
        entry_idea=spec["entry_idea"],
        stop_idea=spec["stop_idea"],
        target_idea=spec["target_idea"],
        invalidation=tuple(spec["invalidation"]),
        no_trade_conditions=tuple(spec["no_trade_conditions"]),
        parameter_candidates=tuple(spec["parameter_candidates"]),
        expected_failure_modes=tuple(spec["expected_failure_modes"]),
        data_requirements=tuple(spec["data_requirements"]),
    )


def _build_partition_labels(split_plan: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for session in split_plan["core_history_sessions"]:
        labels[session] = "core_history"
    for session in split_plan["proxy_holdout_sessions"]:
        labels[session] = "proxy_holdout"
    for session in split_plan["strict_holdout_sessions"]:
        labels[session] = "strict_post_freeze_holdout"
    return labels


def _event_rows(events: tuple[Any, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in events:
        rows.append(
            {
                "strategy_id": item.strategy_id,
                "variant_id": item.variant_id,
                "symbol": item.symbol,
                "timestamp": item.timestamp.isoformat(),
                "direction": item.direction,
                "status": item.status,
                "reason_code": item.reason_code,
                "split_name": item.split_name,
            }
        )
    return rows


def _filter_trades_by_sessions(
    trades: tuple[TradeRecord, ...],
    session_keys: tuple[str, ...],
    symbol: str,
) -> list[TradeRecord]:
    key_set = set(session_keys)
    return [
        trade
        for trade in trades
        if trade.symbol == symbol and trade.entry_timestamp.date().isoformat() in key_set
    ]


def _build_session_regimes(bars: tuple[OhlcvRow, ...]) -> dict[str, str]:
    by_session: dict[str, list[OhlcvRow]] = defaultdict(list)
    for bar in bars:
        by_session[bar.timestamp.date().isoformat()].append(bar)
    ordered_sessions = sorted(by_session.keys())
    session_ranges: dict[str, Decimal] = {}
    session_returns: dict[str, Decimal] = {}
    for key in ordered_sessions:
        session_bars = by_session[key]
        session_high = max(item.high for item in session_bars)
        session_low = min(item.low for item in session_bars)
        session_open = session_bars[0].open
        session_close = session_bars[-1].close
        session_ranges[key] = session_high - session_low
        session_returns[key] = session_close - session_open
    regimes: dict[str, str] = {}
    rolling_ranges: list[Decimal] = []
    for key in ordered_sessions:
        rolling_ranges.append(session_ranges[key])
        lookback = rolling_ranges[-20:]
        atr20 = sum(lookback, ZERO) / Decimal(len(lookback))
        session_range = session_ranges[key]
        session_return = session_returns[key]
        efficiency_ratio = abs(session_return) / max(session_range, EPSILON)
        if efficiency_ratio >= Decimal("0.45") and abs(session_return) >= atr20 * Decimal("0.75"):
            regimes[key] = "trend_up" if session_return > ZERO else "trend_down"
        elif session_range >= atr20 * Decimal("1.25"):
            regimes[key] = "range_high_vol"
        else:
            regimes[key] = "range_low_vol"
    return regimes


def _run_walk_forward_windows(
    *,
    strategy: StrategyDefinition,
    variant: StrategyVariant,
    datasets: list[Wave3Dataset],
    split_plan: dict[str, Any],
    provider: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in split_plan["walk_forward_windows"]:
        all_oos_trades: list[TradeRecord] = []
        total_signals = 0
        total_bars = 0
        for dataset in datasets:
            session_set = set(window.is_sessions) | set(window.oos_sessions)
            bars = tuple(bar for bar in dataset.bars if bar.timestamp.date().isoformat() in session_set)
            split_labels = {session: "in_sample" for session in window.is_sessions}
            split_labels.update({session: "out_of_sample" for session in window.oos_sessions})
            candidate_events, signals = _generate_signals_for_variant(
                bars=bars,
                split_labels=split_labels,
                strategy=strategy,
                variant=variant,
                provider=provider,
            )
            report = run_backtest(bars, signals)
            all_oos_trades.extend(_filter_trades_by_sessions(report.trades, window.oos_sessions, dataset.symbol))
            total_signals += len([item for item in candidate_events if item.split_name == "out_of_sample" and item.status == "emitted"])
            total_bars += len([bar for bar in bars if bar.timestamp.date().isoformat() in set(window.oos_sessions)])
        metrics = _metrics_payload(trades=tuple(all_oos_trades), signal_count=total_signals, bar_count=total_bars)
        rows.append(
            {
                "window_index": window.window_index,
                "is_start": window.is_sessions[0],
                "is_end": window.is_sessions[-1],
                "oos_start": window.oos_sessions[0],
                "oos_end": window.oos_sessions[-1],
                "closed_trades": metrics["closed_trades"],
                "total_pnl_r": metrics["total_pnl_r"],
                "win_rate": metrics["win_rate"],
                "profit_factor": metrics["profit_factor"],
                "max_drawdown_r": metrics["max_drawdown_r"],
                "cash_net_pnl": metrics["cash_net_pnl"],
                "cash_max_drawdown": metrics["cash_max_drawdown"],
                "r_cash_sign_consistency": metrics["r_cash_sign_consistency"],
            }
        )
    return rows


def _holdout_summary(
    *,
    trades: tuple[TradeRecord, ...],
    candidate_count: int,
    session_keys: tuple[str, ...],
    label: str,
) -> dict[str, Any]:
    metrics = _metrics_payload(trades=trades, signal_count=candidate_count, bar_count=0)
    return {
        "label": label,
        "available": bool(session_keys),
        "session_count": len(session_keys),
        "start": session_keys[0] if session_keys else None,
        "end": session_keys[-1] if session_keys else None,
        **metrics,
    }


def _metrics_payload(
    *,
    trades: tuple[TradeRecord, ...],
    signal_count: int,
    bar_count: int,
) -> dict[str, Any]:
    stats = _compute_stats(trades, bar_count=bar_count, signal_count=signal_count)
    cash_metrics = _compute_cash_metrics_for_trades(trades)
    return {
        "trade_count": stats.trade_count,
        "closed_trades": stats.closed_trade_count,
        "win_rate": _string_decimal(stats.win_rate),
        "total_pnl_r": _string_decimal(stats.total_pnl_r),
        "profit_factor": _string_decimal(stats.profit_factor) if stats.profit_factor is not None else None,
        "max_drawdown_r": _string_decimal(stats.max_drawdown_r),
        "avg_trade_r": _string_decimal(stats.expectancy_r),
        "cash_net_pnl": cash_metrics["net_pnl_cash"],
        "cash_max_drawdown": cash_metrics["max_drawdown_cash"],
        "r_cash_sign_consistency": _sign_consistency(stats.total_pnl_r, Decimal(cash_metrics["net_pnl_cash"])),
    }


def _compute_cash_metrics_for_trades(
    trades: tuple[TradeRecord, ...],
    *,
    stress_r_per_trade: Decimal = ZERO,
) -> dict[str, str | None]:
    closed_trades = [
        trade
        for trade in sorted(trades, key=lambda item: (item.entry_timestamp, item.exit_timestamp, item.signal_id))
        if trade.exit_reason != "end_of_data"
    ]
    if not closed_trades:
        return {
            "starting_capital": _string_decimal(CASH_STARTING_CAPITAL),
            "risk_per_trade": _string_decimal(CASH_RISK_PER_TRADE),
            "ending_equity": _string_decimal(CASH_STARTING_CAPITAL),
            "net_pnl_cash": _string_decimal(ZERO),
            "average_trade_pnl_cash": _string_decimal(ZERO),
            "max_drawdown_cash": _string_decimal(ZERO),
            "profit_factor_cash": None,
            "total_return_pct": _string_decimal(ZERO),
        }

    equity = CASH_STARTING_CAPITAL
    peak = CASH_STARTING_CAPITAL
    max_drawdown_cash = ZERO
    pnl_cash_values: list[Decimal] = []
    for trade in closed_trades:
        quantity_by_risk = (CASH_RISK_PER_TRADE / trade.risk_per_share).to_integral_value(rounding=ROUND_DOWN)
        quantity_by_capital = (equity / trade.entry_price).to_integral_value(rounding=ROUND_DOWN)
        quantity = min(quantity_by_risk, quantity_by_capital)
        if quantity <= 0:
            quantity = Decimal("1")
        pnl_cash = _quantize(trade.pnl_per_share * quantity)
        if stress_r_per_trade > ZERO:
            pnl_cash = _quantize(pnl_cash - (stress_r_per_trade * trade.risk_per_share * quantity))
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
    total_return_pct = _quantize(((equity - CASH_STARTING_CAPITAL) / CASH_STARTING_CAPITAL) * HUNDRED)
    return {
        "starting_capital": _string_decimal(CASH_STARTING_CAPITAL),
        "risk_per_trade": _string_decimal(CASH_RISK_PER_TRADE),
        "ending_equity": _string_decimal(equity),
        "net_pnl_cash": _string_decimal(net_pnl_cash),
        "average_trade_pnl_cash": _string_decimal(average_trade_pnl_cash),
        "max_drawdown_cash": _string_decimal(max_drawdown_cash),
        "profit_factor_cash": _string_decimal(gross_profit_cash / gross_loss_cash) if gross_loss_cash > ZERO else None,
        "total_return_pct": _string_decimal(total_return_pct),
    }


def _build_regime_breakdown(
    trades: tuple[TradeRecord, ...],
    regime_maps: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    grouped: dict[str, list[TradeRecord]] = defaultdict(list)
    for trade in trades:
        session_key = trade.entry_timestamp.date().isoformat()
        regime = regime_maps.get(trade.symbol, {}).get(session_key, "unknown")
        grouped[regime].append(trade)
    for regime in sorted(grouped):
        metrics = _metrics_payload(trades=tuple(grouped[regime]), signal_count=0, bar_count=0)
        rows.append(
            {
                "regime": regime,
                "closed_trades": metrics["closed_trades"],
                "total_pnl_r": metrics["total_pnl_r"],
                "cash_net_pnl": metrics["cash_net_pnl"],
                "profit_factor": metrics["profit_factor"],
                "max_drawdown_r": metrics["max_drawdown_r"],
            }
        )
    return rows


def _build_time_of_day_breakdown(
    trades: tuple[TradeRecord, ...],
    full_events: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    trade_groups: dict[str, list[TradeRecord]] = defaultdict(list)
    candidate_counts: Counter[str] = Counter()
    for event in full_events:
        bucket = _time_of_day_bucket(datetime.fromisoformat(event["timestamp"]))
        candidate_counts[bucket] += 1
    for trade in trades:
        trade_groups[_time_of_day_bucket(trade.entry_timestamp)].append(trade)
    rows: list[dict[str, Any]] = []
    for bucket in WAVE3_TIME_BUCKETS:
        metrics = _metrics_payload(trades=tuple(trade_groups[bucket]), signal_count=0, bar_count=0)
        rows.append(
            {
                "time_bucket": bucket,
                "closed_trades": metrics["closed_trades"],
                "total_pnl_r": metrics["total_pnl_r"],
                "cash_net_pnl": metrics["cash_net_pnl"],
                "profit_factor": metrics["profit_factor"],
                "conversion_rate": _string_decimal(_ratio_decimal(int(metrics["closed_trades"]), candidate_counts[bucket])),
            }
        )
    return rows


def _build_conversion_summary(
    *,
    symbol_rows: list[dict[str, Any]],
    time_bucket_candidates: Counter[str],
    time_bucket_executed: Counter[str],
    skip_reason_counts: Counter[str],
    total_candidates: int,
    total_executed: int,
) -> dict[str, Any]:
    top_skip_reasons = [
        {"reason_code": reason, "count": count}
        for reason, count in skip_reason_counts.most_common(5)
    ]
    return {
        "aggregate_conversion_rate": _string_decimal(_ratio_decimal(total_executed, total_candidates)),
        "total_candidates": total_candidates,
        "total_executed_trades": total_executed,
        "conversion_rate_by_symbol": [
            {
                "symbol": row["symbol"],
                "candidate_event_count": row["candidate_event_count"],
                "executed_trade_count": row["executed_trade_count"],
                "conversion_rate": row["conversion_rate"],
            }
            for row in symbol_rows
        ],
        "conversion_rate_by_time_bucket": [
            {
                "time_bucket": bucket,
                "candidate_event_count": time_bucket_candidates[bucket],
                "executed_trade_count": time_bucket_executed[bucket],
                "conversion_rate": _string_decimal(_ratio_decimal(time_bucket_executed[bucket], time_bucket_candidates[bucket])),
            }
            for bucket in WAVE3_TIME_BUCKETS
        ],
        "top_skip_reasons": top_skip_reasons,
    }


def _build_cost_stress_summary(
    *,
    proxy_trades: tuple[TradeRecord, ...],
    strict_trades: tuple[TradeRecord, ...],
    aggregate_oos_trades: tuple[TradeRecord, ...],
) -> dict[str, Any]:
    layers = {
        "proxy_holdout": proxy_trades,
        "strict_holdout": strict_trades,
        "aggregate_oos": aggregate_oos_trades,
    }
    stress_levels = {
        "baseline": ZERO,
        "stress_0.05r_per_trade": Decimal("0.05"),
        "stress_0.10r_per_trade": Decimal("0.10"),
        "stress_0.15r_per_trade": Decimal("0.15"),
    }
    payload: dict[str, Any] = {}
    for layer_name, trades in layers.items():
        payload[layer_name] = {}
        for label, penalty in stress_levels.items():
            payload[layer_name][label] = _stress_metrics_payload(trades, penalty)
    return payload


def _stress_metrics_payload(trades: tuple[TradeRecord, ...], penalty_r: Decimal) -> dict[str, Any]:
    closed_trades = [trade for trade in trades if trade.exit_reason != "end_of_data"]
    if not closed_trades:
        cash_metrics = _compute_cash_metrics_for_trades((), stress_r_per_trade=penalty_r)
        return {
            "closed_trades": 0,
            "total_pnl_r": _string_decimal(ZERO),
            "profit_factor": None,
            "max_drawdown_r": _string_decimal(ZERO),
            "cash_net_pnl": cash_metrics["net_pnl_cash"],
        }
    stressed_pnls = [trade.pnl_r - penalty_r for trade in closed_trades]
    total_pnl = sum(stressed_pnls, ZERO)
    gross_profit = sum((value for value in stressed_pnls if value > ZERO), ZERO)
    gross_loss = abs(sum((value for value in stressed_pnls if value < ZERO), ZERO))
    equity = ZERO
    peak = ZERO
    max_drawdown = ZERO
    for value in stressed_pnls:
        equity += value
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    cash_metrics = _compute_cash_metrics_for_trades(tuple(closed_trades), stress_r_per_trade=penalty_r)
    return {
        "closed_trades": len(closed_trades),
        "total_pnl_r": _string_decimal(total_pnl),
        "profit_factor": _string_decimal(gross_profit / gross_loss) if gross_loss > ZERO else None,
        "max_drawdown_r": _string_decimal(max_drawdown),
        "cash_net_pnl": cash_metrics["net_pnl_cash"],
    }


def _summarize_symbol_breadth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positive_rows = [
        Decimal(row["total_pnl_r"])
        for row in rows
        if Decimal(row["total_pnl_r"]) > ZERO
    ]
    total_positive = sum(positive_rows, ZERO)
    concentration = ZERO
    if total_positive > ZERO:
        concentration = max(
            (Decimal(row["total_pnl_r"]) for row in rows if Decimal(row["total_pnl_r"]) > ZERO),
            default=ZERO,
        ) / total_positive
    positive_symbol_count = sum(1 for row in rows if Decimal(row["total_pnl_r"]) >= ZERO and int(row["closed_trades"]) > 0)
    return {
        "records": rows,
        "positive_symbol_count": positive_symbol_count,
        "positive_contribution_share_max": _string_decimal(concentration),
    }


def _summarize_regime_breadth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positive_rows = [
        Decimal(row["total_pnl_r"])
        for row in rows
        if Decimal(row["total_pnl_r"]) > ZERO
    ]
    total_positive = sum(positive_rows, ZERO)
    concentration = ZERO
    if total_positive > ZERO:
        concentration = max(
            (Decimal(row["total_pnl_r"]) for row in rows if Decimal(row["total_pnl_r"]) > ZERO),
            default=ZERO,
        ) / total_positive
    positive_regime_count = sum(1 for row in rows if Decimal(row["total_pnl_r"]) >= ZERO and int(row["closed_trades"]) > 0)
    return {
        "records": rows,
        "positive_regime_count": positive_regime_count,
        "positive_contribution_share_max": _string_decimal(concentration),
    }


def _summarize_time_breadth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    non_negative_bucket_count = sum(1 for row in rows if Decimal(row["total_pnl_r"]) >= ZERO)
    return {
        "records": rows,
        "non_negative_bucket_count": non_negative_bucket_count,
    }


def _summarize_walk_forward_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "window_count": 0,
            "non_negative_oos_window_ratio": _string_decimal(ZERO),
            "median_oos_pnl_r": _string_decimal(ZERO),
            "worst_oos_window_pnl_r": _string_decimal(ZERO),
            "best_oos_window_pnl_r": _string_decimal(ZERO),
            "oos_trade_count_total": 0,
        }
    pnl_values = [Decimal(row["total_pnl_r"]) for row in rows]
    non_negative_ratio = _ratio_decimal(sum(1 for value in pnl_values if value >= ZERO), len(rows))
    return {
        "window_count": len(rows),
        "non_negative_oos_window_ratio": _string_decimal(non_negative_ratio),
        "median_oos_pnl_r": _string_decimal(Decimal(str(median(pnl_values)))),
        "worst_oos_window_pnl_r": _string_decimal(min(pnl_values)),
        "best_oos_window_pnl_r": _string_decimal(max(pnl_values)),
        "oos_trade_count_total": sum(int(row["closed_trades"]) for row in rows),
    }


def _compute_robustness_score(
    *,
    strict_holdout_summary: dict[str, Any],
    proxy_holdout_summary: dict[str, Any],
    walk_forward_summary: dict[str, Any],
    symbol_breadth_summary: dict[str, Any],
    regime_breadth_summary: dict[str, Any],
    time_of_day_summary: dict[str, Any],
    cost_stress_summary: dict[str, Any],
    conversion_summary: dict[str, Any],
) -> int:
    score = 0
    strict_pnl = Decimal(strict_holdout_summary["total_pnl_r"])
    proxy_pnl = Decimal(proxy_holdout_summary["total_pnl_r"])
    if strict_holdout_summary["available"]:
        score += 10 if strict_pnl >= ZERO else 0
        score += 10 if int(strict_holdout_summary["closed_trades"]) >= 60 else 0
        score += 5 if strict_holdout_summary["r_cash_sign_consistency"] in {"consistent_sign", "zero_alignment"} else 0
    else:
        score += 12 if proxy_pnl >= ZERO else 4

    score += min(20, int((Decimal(walk_forward_summary["non_negative_oos_window_ratio"]) * Decimal("20")).to_integral_value(rounding=ROUND_HALF_UP)))
    score += min(15, int((Decimal(symbol_breadth_summary["positive_symbol_count"]) / Decimal(len(WAVE3_SYMBOLS)) * Decimal("15")).to_integral_value(rounding=ROUND_HALF_UP)))
    score += min(15, int((Decimal(max(1, regime_breadth_summary["positive_regime_count"])) / Decimal("4") * Decimal("15")).to_integral_value(rounding=ROUND_HALF_UP)))
    score += min(10, int((Decimal(time_of_day_summary["non_negative_bucket_count"]) / Decimal("3") * Decimal("10")).to_integral_value(rounding=ROUND_HALF_UP)))
    stress_oos = cost_stress_summary["aggregate_oos"]["stress_0.10r_per_trade"]
    stress_oos_pnl = Decimal(stress_oos["total_pnl_r"])
    score += 10 if stress_oos_pnl >= ZERO else 3
    aggregate_conversion = Decimal(conversion_summary["aggregate_conversion_rate"])
    score += min(5, int((aggregate_conversion * Decimal("5")).to_integral_value(rounding=ROUND_HALF_UP)))
    return max(0, min(100, score))


def _triage_wave3_strategy(
    *,
    strict_holdout_summary: dict[str, Any],
    aggregate_oos_summary: dict[str, Any],
    walk_forward_summary: dict[str, Any],
    symbol_breadth_summary: dict[str, Any],
    regime_breadth_summary: dict[str, Any],
    cost_stress_summary: dict[str, Any],
    robustness_score: int,
    strict_holdout_available: bool,
) -> tuple[str, str]:
    if int(aggregate_oos_summary["closed_trades"]) < 100:
        return "insufficient_sample", "aggregate OOS closed trades stayed below 100, so Wave3 cannot support a stronger conclusion."
    if walk_forward_summary["window_count"] < 3:
        return "insufficient_sample", "walk-forward produced fewer than 3 non-overlapping OOS windows."
    if not strict_holdout_available:
        return "modify_and_retest", "strict post-freeze holdout is unavailable, so this frozen candidate cannot be promoted beyond modify_and_retest."
    strict_holdout_pnl = Decimal(strict_holdout_summary["total_pnl_r"])
    aggregate_oos_pnl = Decimal(aggregate_oos_summary["total_pnl_r"])
    walk_forward_ratio = Decimal(walk_forward_summary["non_negative_oos_window_ratio"])
    stress_pnl = Decimal(cost_stress_summary["aggregate_oos"]["stress_0.10r_per_trade"]["total_pnl_r"])
    symbol_concentration = Decimal(symbol_breadth_summary["positive_contribution_share_max"])
    regime_concentration = Decimal(regime_breadth_summary["positive_contribution_share_max"])
    if (
        int(strict_holdout_summary["closed_trades"]) >= 60
        and strict_holdout_pnl >= ZERO
        and walk_forward_ratio >= Decimal("0.60")
        and Decimal(walk_forward_summary["median_oos_pnl_r"]) >= ZERO
        and symbol_concentration <= Decimal("0.70")
        and regime_concentration <= Decimal("0.70")
        and stress_pnl >= ZERO
        and strict_holdout_summary["r_cash_sign_consistency"] in {"consistent_sign", "zero_alignment"}
        and robustness_score >= 70
    ):
        return "retain_candidate", "strict holdout, walk-forward breadth and cost stress all cleared the retain gate."
    if (
        aggregate_oos_pnl < ZERO
        and walk_forward_ratio < Decimal("0.40")
        and Decimal(cost_stress_summary["aggregate_oos"]["stress_0.05r_per_trade"]["total_pnl_r"]) < aggregate_oos_pnl
    ):
        return "rejected_variant", "aggregate OOS stayed negative, walk-forward consistency stayed weak, and even light slippage stress worsened the result."
    return "modify_and_retest", "Wave3 found repeatable weak spots across holdout/walk-forward breadth or cost stress, so the frozen candidate still needs another narrower spec revision."


def _r_cash_explanation(summary: dict[str, Any]) -> str:
    if summary["r_cash_sign_consistency"] == "consistent_sign":
        return "R 和 cash 同号，无需额外解释。"
    if summary["r_cash_sign_consistency"] == "zero_alignment":
        return "R 和 cash 都接近零，方向上未出现冲突。"
    return (
        "R 和 cash 出现异号。这里的 cash 只是独立的仓位 sizing 解释层，"
        "会因为每笔交易实际可买股数不同而重新加权，不能把它当成 R 的美元等价物。"
    )


def _build_dataset_inventory_payload(
    *,
    run_id: str,
    provider: str,
    datasets: list[Wave3Dataset],
    split_plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": WAVE3_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "phase": "M9I.2",
        "run_id": run_id,
        "provider": provider,
        "target_start": TARGET_START.isoformat(),
        "target_end": datetime.now(UTC).date().isoformat(),
        "common_session_count": len(split_plan["common_sessions"]),
        "common_start": split_plan["common_sessions"][0] if split_plan["common_sessions"] else None,
        "common_end": split_plan["common_sessions"][-1] if split_plan["common_sessions"] else None,
        "datasets": [
            {
                "symbol": item.symbol,
                "provider": item.provider,
                "timeframe": SUPPORTED_TIMEFRAME,
                "requested_start": item.requested_start.isoformat(),
                "requested_end": item.requested_end.isoformat(),
                "actual_start": item.actual_start.isoformat(),
                "actual_end": item.actual_end.isoformat(),
                "csv_path": _repo_relative(item.csv_path),
                "metadata_path": _repo_relative(item.metadata_path),
                "row_count": item.row_count,
                "fetch_mode": item.fetch_mode,
            }
            for item in datasets
        ],
    }


def _build_wave3_summary_markdown(summary_payload: dict[str, Any], strategy_rows: list[str]) -> str:
    lines = [
        "# M9I.2 Wave3 Holdout / Walk-forward Robustness Validation",
        "",
        f"- `run_id`: `{summary_payload['run_id']}`",
        f"- `provider`: `{summary_payload['provider']}`",
        f"- `data_window`: `{summary_payload['data_window']['actual_common_start']} ~ {summary_payload['data_window']['actual_common_end']}`",
        f"- `common_session_count`: {summary_payload['data_window']['common_session_count']}",
        f"- `strict_holdout_available`: {str(summary_payload['strict_holdout_available']).lower()}",
        f"- `tested_strategies`: {', '.join(summary_payload['tested_strategies'])}",
        "",
        "## Triage Counts",
    ]
    for key, value in sorted(summary_payload["triage_counts"].items()):
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Strategy Snapshot",
            "",
            "| Strategy | Triage | WF Windows | Proxy Trades | Strict Trades | Robustness Score | Reason |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    lines.extend(strategy_rows)
    lines.extend(
        [
            "",
            "## Notes",
            "- 本轮只验证冻结后的 `v0.2-candidate`，未修改 specs，也未新增过滤器。",
            "- 没有严格 post-freeze holdout 时，不允许输出 `retain_candidate`。",
            "- `cash` 只是仓位 sizing 解释层，不能单独覆盖 `R` 口径的硬门槛结论。",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _update_strategy_triage_matrix(path: Path, strategy_results: list[dict[str, Any]]) -> None:
    triage = _load_json(path)
    current_records = {item["strategy_id"]: item for item in triage["records"]}
    results_by_id = {item["strategy_id"]: item for item in strategy_results}
    updated_records: list[dict[str, Any]] = []
    for strategy_id, current in current_records.items():
        history = list(current.get("history", []))
        if not history:
            history.append(
                {
                    "wave": "wave2",
                    "spec_version": "v0.1",
                    "triage_status": current["triage_status"],
                    "triage_reason": current["triage_reason"],
                    "sample_status": current["sample_status"],
                    "best_variant_id": current.get("best_variant_id"),
                    "robustness_score": None,
                    "strict_holdout_available": False,
                }
            )
        if strategy_id in results_by_id:
            result = results_by_id[strategy_id]
            history = [item for item in history if item.get("wave") != "wave3"]
            history.append(
                {
                    "wave": "wave3",
                    "spec_version": "v0.2-candidate",
                    "triage_status": result["triage_status"],
                    "triage_reason": result["triage_reason"],
                    "sample_status": _wave3_sample_status(result),
                    "best_variant_id": "v0.2-candidate",
                    "robustness_score": result["robustness_score"],
                    "strict_holdout_available": result["strict_holdout_available"],
                }
            )
            updated = dict(current)
            updated.update(
                {
                    "triage_status": result["triage_status"],
                    "triage_reason": result["triage_reason"],
                    "sample_status": _wave3_sample_status(result),
                    "best_variant_id": "v0.2-candidate",
                    "best_variant_role": "frozen_candidate_spec",
                    "variant_status_counts": {"frozen_candidate": 1},
                    "robustness_score": result["robustness_score"],
                    "strict_holdout_available": result["strict_holdout_available"],
                    "current_wave": "wave3",
                }
            )
            updated["history"] = history
            updated_records.append(updated)
            continue
        current["history"] = history
        updated_records.append(current)
    triage["generated_at"] = _utc_now()
    triage["records"] = updated_records
    _write_json(path, triage)


def _wave3_sample_status(result: dict[str, Any]) -> str:
    if result["triage_status"] == "insufficient_sample":
        return "insufficient_sample"
    if result["triage_status"] == "parked":
        return "parked"
    if result["walk_forward_summary"]["window_count"] >= 3 and int(result["aggregate_oos_summary"]["closed_trades"]) >= 100:
        return "robust_candidate"
    return "formal_candidate"


def _update_run_state(*, provider: str, split_plan: dict[str, Any], run_id: str) -> None:
    path = STRATEGY_FACTORY_ROOT / "run_state.json"
    run_state = _load_json(path)
    run_state.update(
        {
            "current_phase": "M9I.2.wave3_robustness_validation_completed",
            "active_batch_id": run_id,
            "primary_provider": provider,
            "dataset_count": len(WAVE3_SYMBOLS),
            "coverage_start": split_plan["common_sessions"][0] if split_plan["common_sessions"] else None,
            "coverage_end": split_plan["common_sessions"][-1] if split_plan["common_sessions"] else None,
            "last_summary_at": _utc_now(),
            "strict_holdout_available": bool(split_plan["strict_holdout_sessions"]),
        }
    )
    _write_json(path, run_state)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ratio_decimal(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return ZERO
    return _quantize(Decimal(numerator) / Decimal(denominator))


def _sign_consistency(r_total_pnl: Decimal, cash_total_pnl: Decimal) -> str:
    r_sign = _numeric_sign(r_total_pnl)
    cash_sign = _numeric_sign(cash_total_pnl)
    if r_sign == 0 and cash_sign == 0:
        return "zero_alignment"
    if r_sign == cash_sign:
        return "consistent_sign"
    return "inconsistent_sign"


def _numeric_sign(value: Decimal) -> int:
    if value > ZERO:
        return 1
    if value < ZERO:
        return -1
    return 0


def _time_of_day_bucket(timestamp: datetime) -> str:
    localized = timestamp.astimezone(ZoneInfo(DATASET_TIMEZONE))
    minutes = localized.hour * 60 + localized.minute
    for bucket, (start_hour, start_minute, end_hour, end_minute) in WAVE3_TIME_BUCKETS.items():
        start_value = start_hour * 60 + start_minute
        end_value = end_hour * 60 + end_minute
        if start_value <= minutes < end_value:
            return bucket
    return "late_day"
