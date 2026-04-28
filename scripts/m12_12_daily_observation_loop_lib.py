#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.longbridge_history_lib import fetch_longbridge_daily_history_rows, fetch_longbridge_intraday_history_rows
from scripts.m12_liquid_universe_scanner_lib import (
    US_LIQUID_SEED_V1,
    aggregate_bars,
    evaluate_strategy_candidate,
    load_bars,
)
from scripts.public_backtest_demo_lib import CSV_HEADER, sanitize_vendor_rows, write_cache_csv


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_12_daily_observation_loop.json"
OUTPUT_DIR = M10_DIR / "daily_observation" / "m12_12_loop"
SPEC_DIR = M10_DIR / "backtest_specs"
VISUAL_LEDGER_PATH = M10_DIR / "visual_review" / "m12_9_closure" / "m12_9_case_review_ledger.json"
VISUAL_INDEX_PATH = M10_DIR / "visual_review" / "m12_9_closure" / "m12_9_visual_closure_index.json"
DEFINITION_LEDGER_PATH = M10_DIR / "definition_fix" / "m12_10_definition_fix_and_retest" / "m12_10_definition_field_ledger.json"
FORMAL_DAILY_ID = "M12-FTD-001"
CORE_STRATEGIES = ("M10-PA-001", "M10-PA-002", "M10-PA-012")
DAILY_LOOP_STRATEGIES = (*CORE_STRATEGIES, FORMAL_DAILY_ID)
FORBIDDEN_TEXT = (
    "PA-SC-",
    "SF-",
    "live-ready",
    "real_orders=true",
    "broker_connection=true",
    "paper approval",
)
MONEY = Decimal("0.01")
PERCENT = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
DEFAULT_SIMULATED_EQUITY = Decimal("100000")
DEFAULT_RISK_BUDGET = Decimal("500")
QUANTITY = Decimal("0.0001")
CSV_NAME_RE = re.compile(
    r"^(?P<market>[a-z]+)_(?P<symbol>.+)_(?P<interval>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})_(?P<source>[^.]+)\.csv$"
)


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    allow_readonly_fetch: bool
    fetch_timeframes: tuple[str, ...]
    max_native_fetches: int
    missing_data_behavior: str


@dataclass(frozen=True, slots=True)
class FormalDailyStrategyConfig:
    strategy_id: str
    title: str
    starting_capital: Decimal
    risk_per_trade_percent: Decimal
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BoundaryConfig:
    paper_simulated_only: bool
    trading_connection: bool
    real_money_actions: bool
    live_execution: bool
    paper_trading_approval: bool


@dataclass(frozen=True, slots=True)
class M1212Config:
    title: str
    run_id: str
    stage: str
    market: str
    output_dir: Path
    local_data_roots: tuple[Path, ...]
    universe_definition_path: Path
    first_batch_size: int
    daily_start: date
    daily_end: date
    intraday_full_start: date
    intraday_current_start: date
    intraday_end: date
    fetch_policy: FetchPolicy
    daily_observation_strategies: tuple[str, ...]
    formal_daily_strategy: FormalDailyStrategyConfig
    boundary: BoundaryConfig


@dataclass(frozen=True, slots=True)
class FetchTarget:
    symbol: str
    timeframe: str
    target_start: date
    target_end: date
    fetch_mode: str
    destination: Path


@dataclass(frozen=True, slots=True)
class FormalTrade:
    symbol: str
    direction: str
    signal_timestamp: str
    entry_timestamp: str
    exit_timestamp: str
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    exit_price: Decimal
    outcome: str
    simulated_profit: Decimal
    holding_bars: int


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path | None) -> str:
    if path is None:
        return ""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M1212Config:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    policy = payload["fetch_policy"]
    formal = payload["formal_daily_strategy"]
    boundary = payload["boundary"]
    config = M1212Config(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_12_daily_observation_loop"),
        stage=payload["stage"],
        market=payload.get("market", "US"),
        output_dir=resolve_repo_path(payload["output_dir"]),
        local_data_roots=tuple(resolve_repo_path(item) for item in payload.get("local_data_roots", ["local_data"])),
        universe_definition_path=resolve_repo_path(payload["universe_definition_path"]),
        first_batch_size=int(payload.get("first_batch_size", 50)),
        daily_start=date.fromisoformat(payload["daily_start"]),
        daily_end=date.fromisoformat(payload["daily_end"]),
        intraday_full_start=date.fromisoformat(payload["intraday_full_start"]),
        intraday_current_start=date.fromisoformat(payload["intraday_current_start"]),
        intraday_end=date.fromisoformat(payload["intraday_end"]),
        fetch_policy=FetchPolicy(
            allow_readonly_fetch=bool(policy["allow_readonly_fetch"]),
            fetch_timeframes=tuple(policy["fetch_timeframes"]),
            max_native_fetches=int(policy["max_native_fetches"]),
            missing_data_behavior=policy["missing_data_behavior"],
        ),
        daily_observation_strategies=tuple(payload["daily_observation_strategies"]),
        formal_daily_strategy=FormalDailyStrategyConfig(
            strategy_id=formal["strategy_id"],
            title=formal["title"],
            starting_capital=decimal(formal["starting_capital"]),
            risk_per_trade_percent=decimal(formal["risk_per_trade_percent"]),
            source_refs=tuple(formal["source_refs"]),
        ),
        boundary=BoundaryConfig(
            paper_simulated_only=bool(boundary["paper_simulated_only"]),
            trading_connection=bool(boundary["trading_connection"]),
            real_money_actions=bool(boundary["real_money_actions"]),
            live_execution=bool(boundary["live_execution"]),
            paper_trading_approval=bool(boundary["paper_trading_approval"]),
        ),
    )
    validate_config(config)
    return config


def validate_config(config: M1212Config) -> None:
    if config.stage != "M12.12.daily_observation_loop":
        raise ValueError("M12.12 stage drift")
    if config.first_batch_size != 50:
        raise ValueError("M12.12 first batch must stay 50 symbols")
    if config.formal_daily_strategy.strategy_id != FORMAL_DAILY_ID:
        raise ValueError(f"Formal daily strategy must be {FORMAL_DAILY_ID}")
    if set(config.daily_observation_strategies) != set(DAILY_LOOP_STRATEGIES):
        raise ValueError("M12.12 daily strategies must be M10-PA-001/002/012 plus M12-FTD-001")
    if not config.boundary.paper_simulated_only:
        raise ValueError("M12.12 must stay paper/simulated only")
    if (
        config.boundary.trading_connection
        or config.boundary.real_money_actions
        or config.boundary.live_execution
        or config.boundary.paper_trading_approval
    ):
        raise ValueError("M12.12 cannot enable trading, live execution, or paper approval")
    if config.fetch_policy.missing_data_behavior != "deferred_no_fake_data":
        raise ValueError("M12.12 missing data behavior must be deferred_no_fake_data")


def run_m12_12_daily_observation_loop(
    config: M1212Config | None = None,
    *,
    generated_at: str | None = None,
    execute_fetch: bool = True,
    max_native_fetches: int | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    validate_config(config)
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    config.output_dir.mkdir(parents=True, exist_ok=True)

    symbols = select_first_batch_symbols(config)
    fetch_results = run_fetch_plan(
        config,
        symbols,
        generated_at=generated_at,
        execute_fetch=execute_fetch,
        max_native_fetches=max_native_fetches,
    )
    cache_inventory, cache_summary = build_cache_inventory(config, symbols, generated_at, fetch_results)
    specs = load_specs()
    scanner_candidates, observation_rows, scanner_deferred = scan_daily_loop(config, symbols, specs, generated_at)
    formal_summary, formal_trades = run_formal_daily_strategy(config, symbols, generated_at)
    dashboard_trade_rows = build_dashboard_trade_rows(scanner_candidates)
    visual_packet = build_visual_confirmation_packet(config, generated_at)
    all_strategy_status = build_all_strategy_status(config, generated_at, cache_summary, formal_summary, scanner_candidates)
    gate_recheck = build_m11_6_recheck(config, generated_at, cache_summary, formal_summary, all_strategy_status)
    dashboard = build_dashboard(
        config,
        generated_at,
        cache_summary,
        formal_summary,
        formal_trades,
        scanner_candidates,
        dashboard_trade_rows,
        observation_rows,
        all_strategy_status,
        gate_recheck,
    )
    summary = build_summary(
        config,
        generated_at,
        cache_summary,
        formal_summary,
        scanner_candidates,
        dashboard_trade_rows,
        observation_rows,
        visual_packet,
        all_strategy_status,
        gate_recheck,
    )

    write_json(config.output_dir / "m12_12_first50_universe.json", {
        "schema_version": "m12.12.first50-universe.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "selection_rule": "M12.5 static seed order first 50; not a live liquidity ranking.",
        "symbol_count": len(symbols),
        "symbols": symbols,
    })
    write_json(config.output_dir / "m12_12_first50_cache_inventory.json", {
        "schema_version": "m12.12.first50-cache-inventory.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "items": cache_inventory,
    })
    write_json(config.output_dir / "m12_12_first50_cache_summary.json", cache_summary)
    write_json(config.output_dir / "m12_12_cache_fetch_results.json", {
        "schema_version": "m12.12.cache-fetch-results.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "execute_fetch": execute_fetch,
        "items": fetch_results,
    })
    write_json(config.output_dir / "m12_12_formal_daily_strategy_spec.json", formal_strategy_spec(config))
    write_json(config.output_dir / "m12_12_formal_daily_strategy_summary.json", formal_summary)
    write_csv(config.output_dir / "m12_12_formal_daily_strategy_trades.csv", [formal_trade_row(row) for row in formal_trades])
    (config.output_dir / "m12_12_formal_daily_strategy_source_reextract.md").write_text(
        build_formal_source_reextract_md(config, formal_summary),
        encoding="utf-8",
    )
    write_csv(config.output_dir / "m12_12_daily_candidates.csv", scanner_candidates)
    write_jsonl(config.output_dir / "m12_12_daily_candidates.jsonl", scanner_candidates)
    write_csv(config.output_dir / "m12_12_daily_observation_events.csv", observation_rows)
    write_csv(config.output_dir / "m12_12_dashboard_trade_view.csv", dashboard_trade_rows)
    write_json(config.output_dir / "m12_12_daily_observation_summary.json", {
        "schema_version": "m12.12.daily-observation-summary.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "candidate_count": len(scanner_candidates),
        "observation_event_count": len(observation_rows),
        "deferred_count": len(scanner_deferred),
        "deferred": scanner_deferred,
        "strategy_scope": list(DAILY_LOOP_STRATEGIES),
    })
    write_json(config.output_dir / "m12_12_visual_confirmation_packet.json", visual_packet)
    (config.output_dir / "m12_12_visual_confirmation_packet.md").write_text(build_visual_packet_md(visual_packet), encoding="utf-8")
    write_json(config.output_dir / "m12_13_all_strategy_status_matrix.json", all_strategy_status)
    write_csv(config.output_dir / "m12_13_all_strategy_status_matrix.csv", all_strategy_status["items"])
    (config.output_dir / "m12_13_all_strategy_status_summary.md").write_text(build_status_summary_md(all_strategy_status), encoding="utf-8")
    write_json(config.output_dir / "m11_6_paper_gate_recheck.json", gate_recheck)
    (config.output_dir / "m11_6_paper_gate_recheck_report.md").write_text(build_gate_report_md(gate_recheck), encoding="utf-8")
    write_json(config.output_dir / "m12_12_dashboard_data.json", dashboard)
    (config.output_dir / "m12_12_readonly_daily_dashboard.html").write_text(build_dashboard_html(dashboard), encoding="utf-8")
    (config.output_dir / "m12_12_daily_report.md").write_text(build_daily_report_md(summary, dashboard), encoding="utf-8")
    (config.output_dir / "m12_12_handoff.md").write_text(build_handoff(config, summary), encoding="utf-8")
    write_json(config.output_dir / "m12_12_loop_summary.json", summary)

    assert_no_forbidden_output(config.output_dir)
    return summary


def select_first_batch_symbols(config: M1212Config) -> list[str]:
    payload = json.loads(config.universe_definition_path.read_text(encoding="utf-8"))
    symbols = payload.get("symbols", [])
    expected = list(US_LIQUID_SEED_V1[: config.first_batch_size])
    if symbols[: config.first_batch_size] != expected:
        raise ValueError("M12.12 first-50 universe must match M12.5 seed order")
    return expected


def run_fetch_plan(
    config: M1212Config,
    symbols: list[str],
    *,
    generated_at: str,
    execute_fetch: bool,
    max_native_fetches: int | None,
) -> list[dict[str, Any]]:
    budget = config.fetch_policy.max_native_fetches if max_native_fetches is None else max_native_fetches
    fetch_enabled = execute_fetch and config.fetch_policy.allow_readonly_fetch
    results: list[dict[str, Any]] = []
    targets = build_fetch_targets(config, symbols)
    executed = 0
    for target in targets:
        existing = best_cache_file(config.local_data_roots, target.symbol, target.timeframe, target.target_start, target.target_end)
        if existing and is_target_ready(existing, target.target_start, target.target_end):
            results.append(fetch_result(target, "already_ready", existing, generated_at, skipped_reason="cache_already_covers_target"))
            continue
        if not fetch_enabled:
            results.append(fetch_result(target, "deferred", existing, generated_at, skipped_reason="fetch_disabled"))
            continue
        if executed >= budget:
            results.append(fetch_result(target, "deferred", existing, generated_at, skipped_reason="fetch_budget_exhausted"))
            continue
        try:
            rows = fetch_target_rows(config, target)
            rows, anomalies = sanitize_vendor_rows(rows)
            if not rows:
                raise RuntimeError("provider returned no usable rows")
            write_cache_csv(target.destination, rows)
            write_cache_metadata(target.destination, target, rows, anomalies, generated_at)
            executed += 1
            results.append(fetch_result(target, "fetched", target.destination, generated_at, row_count=len(rows), anomaly_count=len(anomalies)))
        except Exception as exc:  # pragma: no cover - runtime provider path
            results.append(fetch_result(target, "deferred", existing, generated_at, skipped_reason=str(exc)))
    return results


def build_fetch_targets(config: M1212Config, symbols: list[str]) -> list[FetchTarget]:
    targets: list[FetchTarget] = []
    for symbol in symbols:
        if "1d" in config.fetch_policy.fetch_timeframes:
            targets.append(
                FetchTarget(
                    symbol=symbol,
                    timeframe="1d",
                    target_start=config.daily_start,
                    target_end=config.daily_end,
                    fetch_mode="full_daily",
                    destination=ROOT
                    / "local_data"
                    / "longbridge_history"
                    / f"{config.market.lower()}_{symbol}_1d_{config.daily_start.isoformat()}_{config.daily_end.isoformat()}_longbridge.csv",
                )
            )
        if "5m_current" in config.fetch_policy.fetch_timeframes:
            targets.append(
                FetchTarget(
                    symbol=symbol,
                    timeframe="5m",
                    target_start=config.intraday_current_start,
                    target_end=config.intraday_end,
                    fetch_mode="current_regular_session_5m",
                    destination=ROOT
                    / "local_data"
                    / "longbridge_intraday"
                    / f"{config.market.lower()}_{symbol}_5m_{config.intraday_current_start.isoformat()}_{config.intraday_end.isoformat()}_longbridge.csv",
                )
            )
    return targets


def fetch_target_rows(config: M1212Config, target: FetchTarget) -> list[dict[str, str]]:
    if target.timeframe == "1d":
        return fetch_longbridge_daily_history_rows(
            ticker=target.symbol,
            symbol=target.symbol,
            market=config.market,
            timezone_name="America/New_York",
            start=target.target_start,
            end=target.target_end,
            interval="1d",
        )
    if target.timeframe == "5m":
        return fetch_longbridge_intraday_history_rows(
            ticker=target.symbol,
            symbol=target.symbol,
            market=config.market,
            timezone_name="America/New_York",
            start=target.target_start,
            end=target.target_end,
            interval="5m",
            allow_extended_hours=False,
        )
    raise ValueError(f"Unsupported fetch target: {target.timeframe}")


def fetch_result(
    target: FetchTarget,
    status: str,
    path: Path | None,
    generated_at: str,
    *,
    row_count: int | None = None,
    anomaly_count: int = 0,
    skipped_reason: str = "",
) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "symbol": target.symbol,
        "timeframe": target.timeframe,
        "fetch_mode": target.fetch_mode,
        "target_start": target.target_start.isoformat(),
        "target_end": target.target_end.isoformat(),
        "status": status,
        "cache_path": project_path(path),
        "checksum": sha256_file(path),
        "row_count": row_count if row_count is not None else csv_stats(path)["row_count"],
        "anomaly_count": anomaly_count,
        "skipped_reason": skipped_reason,
        "fake_data_created": False,
    }


def write_cache_metadata(path: Path, target: FetchTarget, rows: list[dict[str, str]], anomalies: list[dict[str, Any]], generated_at: str) -> None:
    anomaly_path = path.with_suffix(".vendor_anomalies.json")
    if anomalies:
        anomaly_path.write_text(json.dumps(anomalies, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif anomaly_path.exists():
        anomaly_path.unlink()
    metadata = {
        "schema_version": "m12.12.local-cache-metadata.v1",
        "generated_at": generated_at,
        "source": "longbridge_readonly_kline",
        "symbol": target.symbol,
        "timeframe": target.timeframe,
        "fetch_mode": target.fetch_mode,
        "target_start": target.target_start.isoformat(),
        "target_end": target.target_end.isoformat(),
        "row_count": len(rows),
        "local_data_tracked": False,
        "fake_data_created": False,
        "dropped_invalid_vendor_rows": len(anomalies),
        "vendor_anomalies_path": project_path(anomaly_path) if anomalies else "",
    }
    path.with_suffix(".metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_cache_inventory(
    config: M1212Config,
    symbols: list[str],
    generated_at: str,
    fetch_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fetch_by_symbol_tf = {(item["symbol"], item["timeframe"], item["fetch_mode"]): item for item in fetch_results}
    for symbol in symbols:
        daily_path = best_cache_file(config.local_data_roots, symbol, "1d", config.daily_start, config.daily_end)
        five_current_path = best_cache_file(config.local_data_roots, symbol, "5m", config.intraday_current_start, config.intraday_end)
        five_full_path = best_cache_file(config.local_data_roots, symbol, "5m", config.intraday_full_start, config.intraday_end)
        rows.append(inventory_row(config, symbol, "1d", "native_daily_cache", daily_path, config.daily_start, config.daily_end))
        rows.append(inventory_row(config, symbol, "5m_current", "native_current_session_5m_cache", five_current_path, config.intraday_current_start, config.intraday_end))
        rows.append(inventory_row(config, symbol, "5m_full_target", "native_full_5m_cache", five_full_path, config.intraday_full_start, config.intraday_end))
        rows.append(inventory_row(config, symbol, "15m_current", "derived_from_5m_current", five_current_path, config.intraday_current_start, config.intraday_end))
        rows.append(inventory_row(config, symbol, "1h_current", "derived_from_5m_current", five_current_path, config.intraday_current_start, config.intraday_end))
        for timeframe in ("1d", "5m"):
            for mode in ("full_daily", "current_regular_session_5m"):
                result = fetch_by_symbol_tf.get((symbol, timeframe, mode))
                if result:
                    rows[-1].setdefault("fetch_refs", [])
    counts = Counter(row["coverage_status"] for row in rows)
    daily_ready = sorted(row["symbol"] for row in rows if row["timeframe"] == "1d" and row["ready_for_daily_test"])
    current_5m_ready = sorted(row["symbol"] for row in rows if row["timeframe"] == "5m_current" and row["ready_for_daily_test"])
    full_5m_ready = sorted(row["symbol"] for row in rows if row["timeframe"] == "5m_full_target" and row["ready_for_daily_test"])
    summary = {
        "schema_version": "m12.12.first50-cache-summary.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "symbol_count": len(symbols),
        "daily_ready_symbols": len(daily_ready),
        "current_5m_ready_symbols": len(current_5m_ready),
        "full_5m_target_ready_symbols": len(full_5m_ready),
        "daily_ready_symbol_list": daily_ready,
        "current_5m_ready_symbol_list": current_5m_ready,
        "full_5m_target_ready_symbol_list": full_5m_ready,
        "coverage_status_counts": dict(sorted(counts.items())),
        "full_intraday_target_note": "5m_full_target is the long historical intraday window; current_5m is enough for today's readonly bar-close dashboard but not enough for long historical intraday claims.",
        "fake_data_created": False,
        "local_data_git_policy": "local_data_not_tracked; checked-in reports record only path, checksum, coverage, and gaps",
    }
    return rows, summary


def inventory_row(
    config: M1212Config,
    symbol: str,
    timeframe: str,
    lineage: str,
    path: Path | None,
    target_start: date,
    target_end: date,
) -> dict[str, Any]:
    stats = csv_stats(path)
    status, reason = coverage_status(stats, target_start, target_end)
    return {
        "symbol": symbol,
        "market": config.market,
        "timeframe": timeframe,
        "lineage": lineage,
        "target_start": target_start.isoformat(),
        "target_end": target_end.isoformat(),
        "cache_exists": path is not None,
        "cache_path": project_path(path),
        "checksum": sha256_file(path),
        "row_count": stats["row_count"],
        "cache_start": stats["start_date"],
        "cache_end": stats["end_date"],
        "timezone": stats["timezone"],
        "coverage_status": status,
        "coverage_reason": reason,
        "ready_for_daily_test": status in {"complete_for_target_window", "complete_from_first_available_bar"},
        "fake_data_created": False,
    }


def load_specs() -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for strategy_id in CORE_STRATEGIES:
        path = SPEC_DIR / f"{strategy_id}.json"
        specs[strategy_id] = json.loads(path.read_text(encoding="utf-8"))
    return specs


def scan_daily_loop(
    config: M1212Config,
    symbols: list[str],
    specs: dict[str, dict[str, Any]],
    generated_at: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]]:
    candidates: list[dict[str, str]] = []
    events: list[dict[str, str]] = []
    deferred: list[dict[str, Any]] = []
    for symbol in symbols:
        paths = {
            "1d": best_cache_file(config.local_data_roots, symbol, "1d", config.daily_start, config.daily_end),
            "5m": best_cache_file(config.local_data_roots, symbol, "5m", config.intraday_current_start, config.intraday_end),
        }
        bars_by_tf: dict[str, tuple[list[Any], str, Path | None]] = {}
        if paths["1d"]:
            bars_by_tf["1d"] = (load_bars(paths["1d"]), "native_daily_cache", paths["1d"])
        if paths["5m"]:
            five = load_bars(paths["5m"])
            bars_by_tf["5m"] = (five, "native_current_session_5m_cache", paths["5m"])
            bars_by_tf["15m"] = (aggregate_bars(five, "15m"), "derived_from_5m_current", paths["5m"])
            bars_by_tf["1h"] = (aggregate_bars(five, "1h"), "derived_from_5m_current", paths["5m"])
        for strategy_id in CORE_STRATEGIES:
            timeframes = ("15m", "5m") if strategy_id == "M10-PA-012" else ("1d", "1h", "15m", "5m")
            for timeframe in timeframes:
                bars, lineage, path = bars_by_tf.get(timeframe, ([], "", None))
                if not bars:
                    deferred.append({"symbol": symbol, "strategy_id": strategy_id, "timeframe": timeframe, "reason": "cache_missing"})
                    events.append(skip_event(generated_at, symbol, strategy_id, timeframe, "数据未补齐"))
                    continue
                candidate = evaluate_strategy_candidate(
                    generated_at=generated_at,
                    strategy_id=strategy_id,
                    strategy_title=strategy_id_title(strategy_id),
                    timeframe=timeframe,
                    bars=bars,
                    lineage=lineage,
                    data_path=path,
                    spec=specs[strategy_id],
                )
                if candidate:
                    row = normalize_candidate_row(candidate)
                    candidates.append(row)
                    events.append(candidate_event(row))
                else:
                    events.append(skip_event(generated_at, symbol, strategy_id, timeframe, "当前K线未触发"))
        daily_bars, _, daily_path = bars_by_tf.get("1d", ([], "", None))
        formal_candidate = evaluate_formal_daily_candidate(config, symbol, daily_bars, generated_at, daily_path)
        if formal_candidate:
            candidates.append(formal_candidate)
            events.append(candidate_event(formal_candidate))
        else:
            events.append(skip_event(generated_at, symbol, FORMAL_DAILY_ID, "1d", "当前日线未触发"))
    return candidates, events, deferred


def normalize_candidate_row(row: dict[str, str]) -> dict[str, str]:
    mapping = {
        "entry_price": "hypothetical_entry_price",
        "stop_price": "hypothetical_stop_price",
        "target_price": "hypothetical_target_price",
        "risk_per_share": "hypothetical_risk_per_share",
    }
    out = dict(row)
    out["stage"] = "M12.12.daily_observation_loop"
    for old, new in mapping.items():
        out[new] = out.pop(old)
    out["simulated_context"] = "readonly_observation_candidate"
    return out


def evaluate_formal_daily_candidate(
    config: M1212Config,
    symbol: str,
    bars: list[Any],
    generated_at: str,
    data_path: Path | None,
) -> dict[str, str] | None:
    if len(bars) < 4:
        return None
    last = bars[-1]
    previous = bars[-2]
    context = classify_daily_context(bars[-4:])
    signal = daily_signal_quality(last, previous)
    direction = ""
    if context == "上涨趋势" and signal == "看涨信号K" and last.high > previous.high:
        direction = "long"
        entry = last.high
        stop = last.low
    elif context == "下跌趋势" and signal == "看跌信号K" and last.low < previous.low:
        direction = "short"
        entry = last.low
        stop = last.high
    else:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target = entry + risk * Decimal("2") if direction == "long" else entry - risk * Decimal("2")
    return {
        "schema_version": "m12.daily-candidate.v1",
        "stage": "M12.12.daily_observation_loop",
        "generated_at": generated_at,
        "symbol": symbol,
        "market": config.market,
        "strategy_id": FORMAL_DAILY_ID,
        "strategy_title": config.formal_daily_strategy.title,
        "timeframe": "1d",
        "candidate_status": "trigger_candidate",
        "signal_direction": direction,
        "bar_timestamp": last.timestamp,
        "hypothetical_entry_price": money(entry),
        "hypothetical_stop_price": money(stop),
        "hypothetical_target_price": money(target),
        "hypothetical_risk_per_share": money(risk),
        "risk_level": "medium",
        "queue_action": "eligible_for_read_only_observation",
        "source_refs": ";".join(config.formal_daily_strategy.source_refs),
        "spec_ref": "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_12_loop/m12_12_formal_daily_strategy_spec.json",
        "data_lineage": "native_daily_cache",
        "data_path": project_path(data_path) if data_path else "",
        "data_checksum": sha256_file(data_path) if data_path else "",
        "review_status": "needs_read_only_bar_close_review",
        "notes": "日线市场周期和信号K确认同时出现；只做模拟观察。",
        "simulated_context": "readonly_observation_candidate",
    }


def candidate_event(row: dict[str, str]) -> dict[str, str]:
    return {
        "schema_version": "m12.12.observation-event.v1",
        "stage": "M12.12.daily_observation_loop",
        "generated_at": row["generated_at"],
        "event_type": "今日候选",
        "symbol": row["symbol"],
        "strategy_id": row["strategy_id"],
        "strategy_title": row["strategy_title"],
        "timeframe": row["timeframe"],
        "bar_timestamp": row["bar_timestamp"],
        "direction": row["signal_direction"],
        "hypothetical_entry_price": row["hypothetical_entry_price"],
        "hypothetical_stop_price": row["hypothetical_stop_price"],
        "hypothetical_target_price": row["hypothetical_target_price"],
        "review_status": row["review_status"],
        "real_money_actions": "false",
    }


def skip_event(generated_at: str, symbol: str, strategy_id: str, timeframe: str, reason: str) -> dict[str, str]:
    return {
        "schema_version": "m12.12.observation-event.v1",
        "stage": "M12.12.daily_observation_loop",
        "generated_at": generated_at,
        "event_type": "未触发",
        "symbol": symbol,
        "strategy_id": strategy_id,
        "strategy_title": strategy_id_title(strategy_id),
        "timeframe": timeframe,
        "bar_timestamp": "",
        "direction": "",
        "hypothetical_entry_price": "",
        "hypothetical_stop_price": "",
        "hypothetical_target_price": "",
        "review_status": reason,
        "real_money_actions": "false",
    }


def run_formal_daily_strategy(
    config: M1212Config,
    symbols: list[str],
    generated_at: str,
) -> tuple[dict[str, Any], list[FormalTrade]]:
    all_trades: list[FormalTrade] = []
    per_symbol: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for symbol in symbols:
        path = best_cache_file(config.local_data_roots, symbol, "1d", config.daily_start, config.daily_end)
        if not path:
            deferred.append({"symbol": symbol, "reason": "daily_cache_missing"})
            continue
        bars = load_bars(path)
        trades = generate_formal_daily_trades(symbol, bars, config)
        all_trades.extend(trades)
        per_symbol.append(metric_row_for_trades(symbol, trades, config.formal_daily_strategy.starting_capital))
    overall = metric_row_for_trades("ALL", all_trades, config.formal_daily_strategy.starting_capital)
    return {
        "schema_version": "m12.12.formal-daily-strategy-summary.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "strategy_id": FORMAL_DAILY_ID,
        "title": config.formal_daily_strategy.title,
        "source_refs": list(config.formal_daily_strategy.source_refs),
        "formalization_note": "从方方土市场周期与信号K来源重提炼为日线策略；不再把旧截图逻辑当正式来源。",
        "legacy_reference_metrics": {
            "simulated_starting_capital": "100000.00",
            "simulated_final_equity": "149786.19",
            "simulated_net_profit": "49786.19",
            "return_percent": "49.79",
            "win_rate": "36.22",
            "max_drawdown_percent": "12.19",
        },
        "overall_metrics": overall,
        "per_symbol_metrics": per_symbol,
        "deferred": deferred,
        "decision": decide_formal_daily_strategy(overall),
        "paper_gate_route": "excluded_factor_only_until_revalidated",
        "paper_gate_evidence_now": False,
    }, all_trades


def generate_formal_daily_trades(symbol: str, bars: list[Any], config: M1212Config) -> list[FormalTrade]:
    trades: list[FormalTrade] = []
    for idx in range(3, len(bars) - 1):
        history = bars[idx - 3 : idx + 1]
        signal_bar = bars[idx]
        previous = bars[idx - 1]
        context = classify_daily_context(history)
        signal = daily_signal_quality(signal_bar, previous)
        if context == "上涨趋势" and signal == "看涨信号K" and signal_bar.high > previous.high:
            direction = "long"
            stop = signal_bar.low
            entry_bar = bars[idx + 1]
            entry = entry_bar.open
            target = entry + (entry - stop) * Decimal("2")
        elif context == "下跌趋势" and signal == "看跌信号K" and signal_bar.low < previous.low:
            direction = "short"
            stop = signal_bar.high
            entry_bar = bars[idx + 1]
            entry = entry_bar.open
            target = entry - (stop - entry) * Decimal("2")
        else:
            continue
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        exit_price, exit_timestamp, outcome, holding = resolve_trade_exit(bars[idx + 1 : idx + 21], direction, stop, target)
        risk_budget = config.formal_daily_strategy.starting_capital * config.formal_daily_strategy.risk_per_trade_percent / HUNDRED
        qty = risk_budget / risk
        profit = (exit_price - entry) * qty if direction == "long" else (entry - exit_price) * qty
        trades.append(
            FormalTrade(
                symbol=symbol,
                direction=direction,
                signal_timestamp=signal_bar.timestamp,
                entry_timestamp=entry_bar.timestamp,
                exit_timestamp=exit_timestamp,
                entry_price=entry,
                stop_price=stop,
                target_price=target,
                exit_price=exit_price,
                outcome=outcome,
                simulated_profit=profit,
                holding_bars=holding,
            )
        )
    return trades


def classify_daily_context(bars: list[Any]) -> str:
    if len(bars) < 4:
        return "不清楚"
    closes = [bar.close for bar in bars]
    if closes[-1] > closes[-2] > closes[-3] and bars[-1].high > bars[-2].high:
        return "上涨趋势"
    if closes[-1] < closes[-2] < closes[-3] and bars[-1].low < bars[-2].low:
        return "下跌趋势"
    return "震荡或过渡"


def daily_signal_quality(bar: Any, previous: Any) -> str:
    true_range = bar.high - bar.low
    if true_range <= 0:
        return "无效"
    body = abs(bar.close - bar.open)
    if body / true_range < Decimal("0.35"):
        return "不够强"
    upper_tail = bar.high - bar.close
    lower_tail = bar.close - bar.low
    if bar.close > bar.open and upper_tail / true_range <= Decimal("0.35") and bar.close > previous.close:
        return "看涨信号K"
    if bar.close < bar.open and lower_tail / true_range <= Decimal("0.35") and bar.close < previous.close:
        return "看跌信号K"
    return "不够强"


def resolve_trade_exit(future_bars: list[Any], direction: str, stop: Decimal, target: Decimal) -> tuple[Decimal, str, str, int]:
    for offset, bar in enumerate(future_bars, start=1):
        if direction == "long":
            if bar.low <= stop:
                return stop, bar.timestamp, "止损", offset
            if bar.high >= target:
                return target, bar.timestamp, "止盈", offset
        else:
            if bar.high >= stop:
                return stop, bar.timestamp, "止损", offset
            if bar.low <= target:
                return target, bar.timestamp, "止盈", offset
    last = future_bars[-1]
    return last.close, last.timestamp, "到期退出", len(future_bars)


def metric_row_for_trades(symbol: str, trades: list[FormalTrade], starting_capital: Decimal) -> dict[str, Any]:
    equity = starting_capital
    peak = starting_capital
    max_dd = ZERO
    wins = 0
    gross_profit = ZERO
    gross_loss = ZERO
    total_holding = 0
    for trade in sorted(trades, key=lambda item: item.entry_timestamp):
        equity += trade.simulated_profit
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * HUNDRED)
        if trade.simulated_profit > 0:
            wins += 1
            gross_profit += trade.simulated_profit
        else:
            gross_loss += abs(trade.simulated_profit)
        total_holding += trade.holding_bars
    count = len(trades)
    return {
        "symbol": symbol,
        "initial_capital": money(starting_capital),
        "final_equity": money(equity),
        "net_profit": money(equity - starting_capital),
        "return_percent": pct((equity - starting_capital) / starting_capital * HUNDRED if starting_capital else ZERO),
        "trade_count": count,
        "win_rate": pct(Decimal(wins) / Decimal(count) * HUNDRED if count else ZERO),
        "profit_factor": pct(gross_profit / gross_loss if gross_loss else ZERO),
        "max_drawdown_percent": pct(max_dd),
        "average_holding_bars": pct(Decimal(total_holding) / Decimal(count) if count else ZERO),
    }


def decide_formal_daily_strategy(overall: dict[str, Any]) -> str:
    if int(overall["trade_count"]) < 30:
        return "继续观察，样本不足"
    if decimal(overall["net_profit"]) > 0 and decimal(overall["max_drawdown_percent"]) <= Decimal("25"):
        return "可进入每日只读测试"
    return "只保留为对照或选股因子"


def formal_strategy_spec(config: M1212Config) -> dict[str, Any]:
    return {
        "schema_version": "m12.12.formal-daily-strategy-spec.v1",
        "stage": config.stage,
        "strategy_id": FORMAL_DAILY_ID,
        "title": config.formal_daily_strategy.title,
        "plain_language_rule": "先判断日线处在明显上涨或下跌节奏，再要求当天K线本身也顺着这个方向收得足够强；只在下一根日线确认时模拟观察。",
        "entry": "上涨时观察突破信号K高点；下跌时观察跌破信号K低点。",
        "stop": "使用信号K另一端作为模拟止损。",
        "target": "默认观察 2R 目标。",
        "skip": [
            "日线背景不清楚",
            "信号K实体太弱",
            "信号K方向与市场周期相反",
            "风险距离为零或数据不足"
        ],
        "source_refs": list(config.formal_daily_strategy.source_refs),
        "not_source_of_truth": [
            "M12-BENCH-001",
            "early screenshot placeholder",
            "wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md"
        ],
        "paper_simulated_only": True,
        "paper_gate_evidence_now": False,
    }


def build_formal_source_reextract_md(config: M1212Config, formal_summary: dict[str, Any]) -> str:
    overall = formal_summary["overall_metrics"]
    lines = [
        "# M12.12 早期日线策略重新提炼说明",
        "",
        "## 用人话结论",
        "",
        "- 早期截图里的策略盈利能力值得继续挖，但不能直接照搬成正式交易策略。",
        "- 本轮已经把它从旧的 `signal_bar_entry_placeholder` 改成 `M12-FTD-001 方方土日线趋势顺势信号K`。",
        "- 当前来源是方方土“市场周期”和“信号K线与入场”两类资料；旧截图和 `M12-BENCH-001` 只作为历史参考，不再当来源。",
        f"- 重测结果：模拟盈利 `{overall['net_profit']}`，收益率 `{overall['return_percent']}%`，胜率 `{overall['win_rate']}%`，最大回撤 `{overall['max_drawdown_percent']}%`，交易 `{overall['trade_count']}` 笔。",
        "- 结论：收益强，但最大回撤太大，先进入每日只读观察和选股参考；下一步应该做来源驱动的定义收紧，而不是用收益曲线扫参数。",
        "",
        "## 当前重新提炼出的规则",
        "",
        f"- 策略：`{config.formal_daily_strategy.strategy_id}` {config.formal_daily_strategy.title}",
        "- 先判断日线是否处在明显上涨或下跌节奏。",
        "- 再看当天 K 线是否是顺着趋势方向的强信号 K。",
        "- 看涨时观察突破信号 K 高点；看跌时观察跌破信号 K 低点。",
        "- 模拟止损放在信号 K 另一端。",
        "- 默认观察 2R 目标；这只是当前测试口径，不是最终交易管理规则。",
        "",
        "## 来源",
        "",
    ]
    lines.extend(f"- `{ref}`" for ref in config.formal_daily_strategy.source_refs)
    lines.extend([
        "",
        "## 可以继续优化的方向",
        "",
        "- 把“市场周期”从现在的简化三四根日线判断，改成更细的趋势、震荡、过渡期字段。",
        "- 把“信号 K 强度”补成来源字段，例如实体大小、收盘位置、上下影线、是否顺着背景。",
        "- 补跳过条件：背景不清、风险距离太大、连续震荡、信号 K 与大背景冲突。",
        "- 补交易管理：是否只看 2R、是否移动止损、是否分批出场、何时放弃。",
        "",
        "## 不能做的事",
        "",
        "- 不能因为某个参数收益好，就直接把它定为规则。",
        "- 不能把最大回撤从 49% 降下来这件事，靠盲目调阈值完成。",
        "- 不能把旧截图或 placeholder 重新当正式来源。",
    ])
    return "\n".join(lines) + "\n"


def build_visual_confirmation_packet(config: M1212Config, generated_at: str) -> dict[str, Any]:
    ledger = json.loads(VISUAL_LEDGER_PATH.read_text(encoding="utf-8"))
    priority = [row for row in ledger["case_rows"] if row["strategy_id"] in {"M10-PA-008", "M10-PA-009"}]
    key_cases = []
    prompts = {
        "M10-PA-008-boundary-001": "这张到底是主要趋势反转，还是只够做小反弹/震荡？",
        "M10-PA-009-boundary-001": "你希望楔形最小标准多严格：必须三推、必须收敛、还是允许不完美楔形？",
        "M10-PA-009-counterexample-001": "这张是否应排除为普通突破回调，而不是楔形反转？",
        "M10-PA-008-positive-001": "强下跌后的 HH MTR 是否可接受，不必机械等 LH MTR？",
    }
    for row in priority:
        key_cases.append(
            {
                "strategy_id": row["strategy_id"],
                "case_id": row["case_id"],
                "case_type": row["case_type"],
                "agent_decision": row["case_level_decision"],
                "user_decision": "pending",
                "review_priority": "关键模糊图" if row["case_id"] in prompts else "锚点图",
                "question_for_user": prompts.get(row["case_id"], "请确认这张图是否支持该策略的关键图形语义。"),
                "brooks_unit_ref": row["brooks_unit_ref"],
                "image_logical_path": row["evidence_image_logical_path"],
                "checksum": row["evidence_image_checksum"],
                "paper_gate_evidence_now": False,
            }
        )
    return {
        "schema_version": "m12.12.visual-confirmation-packet.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "packet_title": "M10-PA-008/009 图形确认包",
        "plain_language_summary": "我已经先把图读了一遍；你只需要优先看两张最模糊的边界图，再看两张二级争议图。",
        "needs_user_review_count": len(key_cases),
        "priority_cases": key_cases,
        "definition_blocker_notes": [
            "M10-PA-004 缺宽通道边界、触边、反转确认、通道失效标签。",
            "M10-PA-007 缺第一腿、第二腿、对侧失败点、陷阱确认标签。"
        ],
        "paper_gate_evidence_now": False,
    }


def build_all_strategy_status(
    config: M1212Config,
    generated_at: str,
    cache_summary: dict[str, Any],
    formal_summary: dict[str, Any],
    candidates: list[dict[str, str]],
) -> dict[str, Any]:
    candidate_counts = Counter(row["strategy_id"] for row in candidates)
    rows = [
        status_row("M10-PA-001", "趋势回调二次入场", "已进入每日测试", "50只日线可测；日内用当前5m观察", candidate_counts),
        status_row("M10-PA-002", "突破后续跟进", "已进入每日测试", "50只日线可测；日内用当前5m观察", candidate_counts),
        status_row("M10-PA-003", "紧密通道顺势", "观察名单", "不阻塞主线，后续按图形策略排队", candidate_counts),
        status_row("M10-PA-004", "宽通道边界反转", "待人工标签/定义闭环", "缺宽通道边界、触边、反转确认、失效条件", candidate_counts),
        status_row("M10-PA-005", "交易区间失败突破反转", "暂不进入每日测试", "已补几何字段，但复测结果弱，先暂停", candidate_counts),
        status_row("M10-PA-006", "BLSHS 限价框架", "研究项", "不是独立入场策略", candidate_counts),
        status_row("M10-PA-007", "第二腿陷阱反转", "待人工标签/定义闭环", "缺腿部计数、对侧失败点、陷阱确认", candidate_counts),
        status_row("M10-PA-008", "主要趋势反转 MTR", "等待你确认关键图", "agent 已预审，确认后可进入候选队列", candidate_counts),
        status_row("M10-PA-009", "楔形反转 / 楔形旗形", "等待你确认关键图", "agent 已预审，确认后可进入候选队列", candidate_counts),
        status_row("M10-PA-010", "Final Flag / Climax / TBTL", "暂非本阶段重点", "图形依赖高，后续排队", candidate_counts),
        status_row("M10-PA-011", "开盘反转", "观察名单", "不阻塞主线，后续排队", candidate_counts),
        status_row("M10-PA-012", "开盘区间突破", "已进入每日测试", "当前5m可做日内只读观察", candidate_counts),
        status_row("M10-PA-013", "支撑阻力失败测试", "观察名单", "Wave B 候选，不进入本轮自动主线", candidate_counts),
        status_row("M10-PA-014", "Measured Move 目标模块", "辅助规则", "只用于目标，不单独交易", candidate_counts),
        status_row("M10-PA-015", "止损与仓位模块", "辅助规则", "只用于风险控制，不单独交易", candidate_counts),
        status_row("M10-PA-016", "交易区间加仓研究", "研究项", "不进入每日自动测试", candidate_counts),
        {
            "strategy_id": FORMAL_DAILY_ID,
            "title": config.formal_daily_strategy.title,
            "status": formal_summary["decision"],
            "plain_reason": "从方方土来源重新正式化，不再叫 placeholder；本轮已重测。",
            "candidate_count_today": str(candidate_counts.get(FORMAL_DAILY_ID, 0)),
            "paper_gate_evidence_now": "false",
        },
    ]
    return {
        "schema_version": "m12.13.all-strategy-status-matrix.v1",
        "stage": "M12.13.all_strategy_status",
        "generated_at": generated_at,
        "cache_context": {
            "first_batch_symbols": cache_summary["symbol_count"],
            "daily_ready_symbols": cache_summary["daily_ready_symbols"],
            "current_5m_ready_symbols": cache_summary["current_5m_ready_symbols"],
        },
        "items": rows,
    }


def status_row(strategy_id: str, title: str, status: str, reason: str, counts: Counter[str]) -> dict[str, str]:
    return {
        "strategy_id": strategy_id,
        "title": title,
        "status": status,
        "plain_reason": reason,
        "candidate_count_today": str(counts.get(strategy_id, 0)),
        "paper_gate_evidence_now": "false",
    }


def build_m11_6_recheck(
    config: M1212Config,
    generated_at: str,
    cache_summary: dict[str, Any],
    formal_summary: dict[str, Any],
    all_strategy_status: dict[str, Any],
) -> dict[str, Any]:
    blockers = []
    if cache_summary["daily_ready_symbols"] < 50:
        blockers.append("第一批50只日线数据还没有全部补齐。")
    if cache_summary["current_5m_ready_symbols"] < 50:
        blockers.append("第一批50只当前5分钟数据还没有全部补齐。")
    blockers.append("还没有连续10个交易日的每日看板记录。")
    blockers.append("M10-PA-008/009 关键图形还需要你确认。")
    blockers.append("你尚未明确批准进入模拟交易试运行。")
    paper_ready = len(blockers) == 0
    return {
        "schema_version": "m11.6.paper-gate-recheck.v1",
        "stage": "M11.6.paper_gate_recheck",
        "generated_at": generated_at,
        "plain_language": {
            "paper_gate": "是否允许进入模拟买卖试运行的检查。",
            "paper_trading": "每天按策略模拟买卖、模拟持仓和模拟盈亏，但不碰真钱。",
        },
        "approval_for_paper_trading_trial": paper_ready,
        "first_batch_candidate_strategies": [
            "M10-PA-001",
            "M10-PA-002",
            "M10-PA-012",
        ],
        "non_gate_daily_factor_strategies": [
            FORMAL_DAILY_ID,
        ],
        "blockers": blockers,
        "approval_rule": "50只数据可用、每日看板连续10个交易日稳定输出、候选记录足够、关键图形完成确认后，才批准模拟交易试运行。",
    }


def build_dashboard_trade_rows(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    close_cache: dict[str, Decimal] = {}
    rows: list[dict[str, str]] = []
    for row in candidates:
        entry = decimal(row["hypothetical_entry_price"])
        stop = decimal(row["hypothetical_stop_price"])
        target = decimal(row["hypothetical_target_price"])
        risk = decimal(row["hypothetical_risk_per_share"])
        current = current_reference_price(row, close_cache)
        qty = DEFAULT_RISK_BUDGET / risk if risk > 0 else ZERO
        if row["signal_direction"] == "long":
            pnl = (current - entry) * qty
            stop_distance = current - stop
            target_distance = target - current
        elif row["signal_direction"] == "short":
            pnl = (entry - current) * qty
            stop_distance = stop - current
            target_distance = current - target
        else:
            pnl = ZERO
            stop_distance = ZERO
            target_distance = ZERO
        rows.append({
            "strategy_id": row["strategy_id"],
            "strategy_title": row["strategy_title"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "direction": "看涨" if row["signal_direction"] == "long" else "看跌" if row["signal_direction"] == "short" else row["signal_direction"],
            "bar_timestamp": row["bar_timestamp"],
            "opportunity_status": chinese_candidate_status(row.get("candidate_status", "")),
            "hypothetical_entry_price": row["hypothetical_entry_price"],
            "hypothetical_stop_price": row["hypothetical_stop_price"],
            "hypothetical_target_price": row["hypothetical_target_price"],
            "current_reference_price": money(current),
            "risk_budget_usd": money(DEFAULT_RISK_BUDGET),
            "hypothetical_quantity": str(qty.quantize(QUANTITY, rounding=ROUND_HALF_UP)),
            "simulated_unrealized_pnl": money(pnl),
            "simulated_unrealized_return_percent": pct(pnl / DEFAULT_SIMULATED_EQUITY * HUNDRED),
            "distance_to_stop": money(stop_distance),
            "distance_to_target": money(target_distance),
            "risk_level": chinese_risk_level(row.get("risk_level", "")),
            "review_status": chinese_review_status(row.get("review_status", "")),
            "data_lineage": row.get("data_lineage", ""),
            "source_refs": row.get("source_refs", ""),
        })
    return rows


def current_reference_price(row: dict[str, str], close_cache: dict[str, Decimal]) -> Decimal:
    data_path = row.get("data_path", "")
    if data_path:
        path = resolve_repo_path(data_path)
        key = project_path(path)
        if key not in close_cache:
            close_cache[key] = latest_close_from_cache(path)
        if close_cache[key] > 0:
            return close_cache[key]
    return decimal(row["hypothetical_entry_price"])


def latest_close_from_cache(path: Path) -> Decimal:
    if not path.exists():
        return ZERO
    last_close = ZERO
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                last_close = decimal(row.get("close", "0"))
            except (InvalidOperation, ValueError):
                continue
    return last_close


def summarize_dashboard_trades(rows: list[dict[str, str]]) -> dict[str, Any]:
    total = sum((decimal(row["simulated_unrealized_pnl"]) for row in rows), ZERO)
    positive = sum(1 for row in rows if decimal(row["simulated_unrealized_pnl"]) > 0)
    negative = sum(1 for row in rows if decimal(row["simulated_unrealized_pnl"]) < 0)
    by_strategy: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = by_strategy.setdefault(row["strategy_id"], {
            "strategy_id": row["strategy_id"],
            "strategy_title": row["strategy_title"],
            "opportunity_count": 0,
            "simulated_unrealized_pnl": ZERO,
            "positive_count": 0,
        })
        pnl = decimal(row["simulated_unrealized_pnl"])
        bucket["opportunity_count"] += 1
        bucket["simulated_unrealized_pnl"] += pnl
        if pnl > 0:
            bucket["positive_count"] += 1
    strategy_rows = []
    for bucket in by_strategy.values():
        count = Decimal(bucket["opportunity_count"])
        strategy_rows.append({
            "strategy_id": bucket["strategy_id"],
            "strategy_title": bucket["strategy_title"],
            "opportunity_count": bucket["opportunity_count"],
            "simulated_unrealized_pnl": money(bucket["simulated_unrealized_pnl"]),
            "floating_positive_percent": pct(Decimal(bucket["positive_count"]) / count * HUNDRED if count else ZERO),
        })
    strategy_rows.sort(key=lambda item: (decimal(item["simulated_unrealized_pnl"]), item["opportunity_count"]), reverse=True)
    count = Decimal(len(rows))
    return {
        "opportunity_count": len(rows),
        "simulated_unrealized_pnl": money(total),
        "simulated_unrealized_return_percent": pct(total / DEFAULT_SIMULATED_EQUITY * HUNDRED),
        "floating_positive_count": positive,
        "floating_negative_count": negative,
        "floating_positive_percent": pct(Decimal(positive) / count * HUNDRED if count else ZERO),
        "strategy_rows": strategy_rows,
    }


def build_equity_curve_points(trades: list[FormalTrade], starting_capital: Decimal, max_points: int = 80) -> list[dict[str, str]]:
    points: list[dict[str, str]] = [{"timestamp": "", "equity": money(starting_capital)}]
    equity = starting_capital
    for trade in sorted(trades, key=lambda item: item.exit_timestamp):
        equity += trade.simulated_profit
        points.append({"timestamp": trade.exit_timestamp, "equity": money(equity)})
    if len(points) <= max_points:
        return points
    step = max(1, len(points) // max_points)
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


def chinese_candidate_status(status: str) -> str:
    return {
        "trigger_candidate": "已触发观察",
        "watch_candidate": "观察名单",
    }.get(status, status or "待观察")


def chinese_review_status(status: str) -> str:
    return {
        "needs_read_only_bar_close_review": "等待收盘复核",
    }.get(status, status or "待复核")


def chinese_risk_level(level: str) -> str:
    return {
        "low": "低",
        "medium": "中",
        "high": "高",
        "unknown": "未知",
    }.get(level, level or "未知")


def build_dashboard(
    config: M1212Config,
    generated_at: str,
    cache_summary: dict[str, Any],
    formal_summary: dict[str, Any],
    formal_trades: list[FormalTrade],
    candidates: list[dict[str, str]],
    dashboard_trade_rows: list[dict[str, str]],
    events: list[dict[str, str]],
    all_strategy_status: dict[str, Any],
    gate_recheck: dict[str, Any],
) -> dict[str, Any]:
    overall = formal_summary["overall_metrics"]
    trade_summary = summarize_dashboard_trades(dashboard_trade_rows)
    return {
        "schema_version": "m12.12.readonly-dashboard.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "approval_for_paper_trading_trial": gate_recheck["approval_for_paper_trading_trial"],
        "candidate_definition": "候选是一条“策略 x 标的 x 周期”的可观察机会，不等于已经成交的交易；同一只股票可同时出现多条候选。",
        "top_metrics": {
            "今日机会数": len(candidates),
            "今日机会估算盈亏（未成交）": trade_summary["simulated_unrealized_pnl"],
            "今日机会估算收益率（未成交）": trade_summary["simulated_unrealized_return_percent"],
            "今日浮盈机会占比": trade_summary["floating_positive_percent"],
            "早期日线历史模拟盈利": overall["net_profit"],
            "早期日线历史收益率": overall["return_percent"],
            "早期日线历史胜率": overall["win_rate"],
            "早期日线最大回撤": overall["max_drawdown_percent"],
            "第一批可测股票": cache_summary["daily_ready_symbols"],
            "当前5分钟可观察股票": cache_summary["current_5m_ready_symbols"],
            "长历史5分钟完整度": f"{cache_summary['full_5m_target_ready_symbols']}/50",
            "日线策略定位": formal_summary["decision"],
        },
        "trade_view_summary": trade_summary,
        "today_trade_view": dashboard_trade_rows,
        "today_candidates": candidates,
        "strategy_status": all_strategy_status["items"],
        "observation_events": events,
        "formal_daily_metrics": formal_summary,
        "formal_daily_equity_curve": build_equity_curve_points(formal_trades, config.formal_daily_strategy.starting_capital),
        "gate_recheck": gate_recheck,
    }


def build_summary(
    config: M1212Config,
    generated_at: str,
    cache_summary: dict[str, Any],
    formal_summary: dict[str, Any],
    candidates: list[dict[str, str]],
    dashboard_trade_rows: list[dict[str, str]],
    events: list[dict[str, str]],
    visual_packet: dict[str, Any],
    all_strategy_status: dict[str, Any],
    gate_recheck: dict[str, Any],
) -> dict[str, Any]:
    trade_summary = summarize_dashboard_trades(dashboard_trade_rows)
    return {
        "schema_version": "m12.12.loop-summary.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "first50_cache": cache_summary,
        "formal_daily_strategy": formal_summary,
        "daily_loop": {
            "strategy_scope": list(DAILY_LOOP_STRATEGIES),
            "candidate_count": len(candidates),
            "candidate_plain_language": "候选是一条策略、标的、周期组合上的可观察机会，不是已经成交的交易。",
            "dashboard_trade_view_count": len(dashboard_trade_rows),
            "simulated_unrealized_pnl": trade_summary["simulated_unrealized_pnl"],
            "floating_positive_percent": trade_summary["floating_positive_percent"],
            "observation_event_count": len(events),
        },
        "visual_packet": {
            "needs_user_review_count": visual_packet["needs_user_review_count"],
            "paper_gate_evidence_now": visual_packet["paper_gate_evidence_now"],
        },
        "all_strategy_status_count": len(all_strategy_status["items"]),
        "paper_gate_recheck": gate_recheck,
    }


def best_cache_file(roots: Iterable[Path], symbol: str, interval: str, target_start: date, target_end: date) -> Path | None:
    candidates: list[Path] = []
    pattern = f"us_{symbol.replace('.', '-')}_{interval}_*_longbridge.csv"
    subdir = "longbridge_history" if interval == "1d" else "longbridge_intraday"
    for root in roots:
        directory = root / subdir
        if directory.exists():
            candidates.extend(directory.glob(pattern))
    if not candidates:
        return None
    covering = [path for path in candidates if is_target_ready(path, target_start, target_end)]
    pool = covering or candidates
    return max(pool, key=lambda path: (cache_file_date_window(path)[1] or date.min, csv_stats(path)["row_count"], path.name))


def is_target_ready(path: Path, target_start: date, target_end: date) -> bool:
    status, _ = coverage_status(csv_stats(path), target_start, target_end)
    return status in {"complete_for_target_window", "complete_from_first_available_bar"}


def csv_stats(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"row_count": 0, "start_date": "", "end_date": "", "timezone": "", "request_start_date": "", "request_end_date": ""}
    request_start, request_end = cache_file_date_window(path)
    row_count = 0
    first = ""
    last = ""
    timezone = ""
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            if row_count == 1:
                first = row.get("timestamp", "")
                timezone = row.get("timezone", "")
            last = row.get("timestamp", "")
    return {
        "row_count": row_count,
        "start_date": timestamp_date(first).isoformat() if first else "",
        "end_date": timestamp_date(last).isoformat() if last else "",
        "timezone": timezone,
        "request_start_date": request_start.isoformat() if request_start else "",
        "request_end_date": request_end.isoformat() if request_end else "",
    }


def coverage_status(stats: dict[str, Any], target_start: date, target_end: date) -> tuple[str, str]:
    if not stats["row_count"]:
        return "missing_cache", "没有本地K线缓存。"
    cache_start = date.fromisoformat(stats["start_date"])
    cache_end = date.fromisoformat(stats["end_date"])
    if cache_end < target_end:
        return "stale_cache", f"缓存只到 {cache_end.isoformat()}，目标到 {target_end.isoformat()}。"
    if cache_start > target_start:
        request_start = stats.get("request_start_date", "")
        if request_start and date.fromisoformat(request_start) <= target_start:
            return "complete_from_first_available_bar", "已从目标起点请求，首根K线晚于目标起点，视作上市/数据起点较晚。"
        return "start_after_target_or_availability_gap", "缓存起点晚于目标起点，尚未确认是上市较晚还是缺口。"
    return "complete_for_target_window", "覆盖目标窗口。"


def cache_file_date_window(path: Path) -> tuple[date | None, date | None]:
    match = CSV_NAME_RE.match(path.name)
    if not match:
        return None, None
    return date.fromisoformat(match.group("start")), date.fromisoformat(match.group("end"))


def timestamp_date(value: str) -> date:
    return datetime.fromisoformat(value).date()


def sha256_file(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strategy_id_title(strategy_id: str) -> str:
    return {
        "M10-PA-001": "趋势回调二次入场",
        "M10-PA-002": "突破后续跟进",
        "M10-PA-012": "开盘区间突破",
        FORMAL_DAILY_ID: "方方土日线趋势顺势信号K",
    }.get(strategy_id, strategy_id)


def money(value: Decimal) -> str:
    return str(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def pct(value: Decimal) -> str:
    return str(value.quantize(PERCENT, rounding=ROUND_HALF_UP))


def formal_trade_row(trade: FormalTrade) -> dict[str, str]:
    return {
        "strategy_id": FORMAL_DAILY_ID,
        "symbol": trade.symbol,
        "direction": "看涨" if trade.direction == "long" else "看跌",
        "signal_timestamp": trade.signal_timestamp,
        "entry_timestamp": trade.entry_timestamp,
        "exit_timestamp": trade.exit_timestamp,
        "hypothetical_entry_price": money(trade.entry_price),
        "hypothetical_stop_price": money(trade.stop_price),
        "hypothetical_target_price": money(trade.target_price),
        "hypothetical_exit_price": money(trade.exit_price),
        "outcome": trade.outcome,
        "simulated_profit": money(trade.simulated_profit),
        "holding_bars": str(trade.holding_bars),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_visual_packet_md(packet: dict[str, Any]) -> str:
    lines = [
        "# M12.12 图形确认包",
        "",
        "我已经先做预审。你只需要优先看标为“关键模糊图”的样例；确认前这些图形策略不计入模拟交易准入。",
        "",
        "| 策略 | 图例 | 类型 | 我方预判 | 你要回答的问题 | 图片路径 |",
        "|---|---|---|---|---|---|",
    ]
    for row in packet["priority_cases"]:
        lines.append(
            f"| {row['strategy_id']} | {row['case_id']} | {row['case_type']} | {row['agent_decision']} | "
            f"{row['question_for_user']} | `{row['image_logical_path']}` |"
        )
    lines.extend([
        "",
        "## 结论口径",
        "",
        "- `pass`：你认可这张图支持该策略关键语义。",
        "- `fail`：这张图不应支持该策略，后续降级或换图。",
        "- `ambiguous`：需要更多上下文，不能作为准入证据。",
    ])
    return "\n".join(lines) + "\n"


def build_status_summary_md(status: dict[str, Any]) -> str:
    lines = ["# M12.13 全策略状态总表", "", "这张表直接说明每条策略现在能不能进入每日测试。", ""]
    for row in status["items"]:
        lines.append(f"- `{row['strategy_id']}` {row['title']}：{row['status']}。{row['plain_reason']}")
    return "\n".join(lines) + "\n"


def build_gate_report_md(gate: dict[str, Any]) -> str:
    lines = [
        "# M11.6 模拟交易准入复查",
        "",
        f"- Paper Gate：{gate['plain_language']['paper_gate']}",
        f"- Paper Trading：{gate['plain_language']['paper_trading']}",
        f"- 当前是否批准进入模拟交易试运行：`{gate['approval_for_paper_trading_trial']}`",
        "",
        "## 还差什么",
        "",
    ]
    lines.extend(f"- {item}" for item in gate["blockers"])
    return "\n".join(lines) + "\n"


def build_dashboard_html(dashboard: dict[str, Any]) -> str:
    metrics = dashboard["top_metrics"]
    cards = "\n".join(
        f"<section><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></section>"
        for label, value in metrics.items()
    )
    trade_rows = sorted(
        dashboard["today_trade_view"],
        key=lambda row: decimal(row["simulated_unrealized_pnl"]),
        reverse=True,
    )
    trade_table_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row['symbol'])}</td>"
        f"<td>{html.escape(row['strategy_id'])}</td>"
        f"<td>{html.escape(row['timeframe'])}</td>"
        f"<td>{html.escape(row['direction'])}</td>"
        f"<td>{html.escape(row['hypothetical_entry_price'])}</td>"
        f"<td>{html.escape(row['current_reference_price'])}</td>"
        f"<td>{html.escape(row['hypothetical_stop_price'])}</td>"
        f"<td>{html.escape(row['hypothetical_target_price'])}</td>"
        f"<td>{html.escape(row['hypothetical_quantity'])}</td>"
        f"<td class=\"money\">{html.escape(row['simulated_unrealized_pnl'])}</td>"
        f"<td>{html.escape(row['risk_level'])}</td>"
        f"<td>{html.escape(row['review_status'])}</td>"
        "</tr>"
        for row in trade_rows[:60]
    )
    strategy_chart = build_strategy_chart_html(dashboard["trade_view_summary"]["strategy_rows"])
    equity_chart = build_equity_svg(dashboard["formal_daily_equity_curve"])
    candidate_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row['symbol'])}</td>"
        f"<td>{html.escape(row['strategy_id'])}</td>"
        f"<td>{html.escape(row['timeframe'])}</td>"
        f"<td>{html.escape('看涨' if row['signal_direction'] == 'long' else '看跌' if row['signal_direction'] == 'short' else row['signal_direction'])}</td>"
        f"<td>{html.escape(row['hypothetical_entry_price'])}</td>"
        f"<td>{html.escape(row['hypothetical_stop_price'])}</td>"
        f"<td>{html.escape(row['hypothetical_target_price'])}</td>"
        f"<td>{html.escape(chinese_review_status(row['review_status']))}</td>"
        "</tr>"
        for row in dashboard["today_candidates"]
    )
    status_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row['strategy_id'])}</td>"
        f"<td>{html.escape(row['title'])}</td>"
        f"<td>{html.escape(row['status'])}</td>"
        f"<td>{html.escape(row['candidate_count_today'])}</td>"
        f"<td>{html.escape(row['plain_reason'])}</td>"
        "</tr>"
        for row in dashboard["strategy_status"]
    )
    data = html.escape(json.dumps(dashboard_html_data(dashboard), ensure_ascii=False, sort_keys=True))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>M12.12 每日只读测试看板</title>
  <style>
    :root {{ --line: #d8dde5; --muted: #5c6675; --good: #16794c; --bad: #b42318; --accent: #1f6feb; --gold: #b7791f; }}
    body {{ margin: 0; font-family: Arial, "Noto Sans SC", sans-serif; background: #f7f8fa; color: #1d2430; }}
    header {{ padding: 20px 24px; background: #fff; border-bottom: 1px solid var(--line); }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    main {{ padding: 18px 24px 28px; display: grid; gap: 18px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
    section, .panel {{ background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 12px; }}
    section span {{ display: block; color: var(--muted); font-size: 13px; }}
    section strong {{ display: block; margin-top: 6px; font-size: 22px; }}
    .grid2 {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 14px; }}
    .note {{ color: var(--muted); font-size: 13px; line-height: 1.6; margin: 4px 0 0; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; min-width: 960px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px; text-align: left; font-size: 13px; white-space: nowrap; }}
    th {{ color: var(--muted); }}
    .money {{ font-weight: 700; }}
    .bars {{ display: grid; gap: 9px; }}
    .bar-row {{ display: grid; grid-template-columns: 98px 1fr 88px; gap: 8px; align-items: center; font-size: 13px; }}
    .bar-track {{ height: 16px; background: #eef2f7; border-radius: 4px; overflow: hidden; }}
    .bar-fill {{ height: 100%; background: var(--accent); }}
    .bar-fill.negative {{ background: var(--bad); }}
    svg {{ width: 100%; height: 220px; display: block; }}
    @media (max-width: 900px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>M12.12 每日只读测试看板</h1>
    <div>开头优先看今日机会、未成交估算盈亏、胜率、最大回撤和策略状态。这里没有真实成交，也没有批准模拟买卖试运行。</div>
  </header>
  <main>
    <div class="metrics">{cards}</div>
    <div class="panel">
      <h2>今日机会估算视图（未成交）</h2>
      <p class="note">这里把“候选机会”按每笔最多亏 500 美元估算假设数量、当前参考价和估算盈亏。它不是实际成交，不是模拟买卖试运行，也没有真实账户。</p>
      <div class="table-wrap"><table><thead><tr><th>标的</th><th>策略</th><th>周期</th><th>方向</th><th>假设入场</th><th>当前参考价</th><th>假设止损</th><th>假设目标</th><th>假设数量</th><th>机会估算盈亏（未成交）</th><th>风险</th><th>状态</th></tr></thead><tbody>{trade_table_rows}</tbody></table></div>
    </div>
    <div class="grid2">
      <div class="panel">
        <h2>策略今日贡献</h2>
        <p class="note">按今日所有可观察机会估算，不代表已完成交易。</p>
        {strategy_chart}
      </div>
      <div class="panel">
        <h2>早期日线资金曲线</h2>
        <p class="note">这是历史模拟曲线，用来判断这条强收益策略是否值得继续降回撤。</p>
        {equity_chart}
      </div>
    </div>
    <div class="panel">
      <h2>今日机会明细</h2>
      <p class="note">{html.escape(dashboard['candidate_definition'])}</p>
      <div class="table-wrap"><table><thead><tr><th>标的</th><th>策略</th><th>周期</th><th>方向</th><th>假设入场</th><th>假设止损</th><th>假设目标</th><th>状态</th></tr></thead><tbody>{candidate_rows}</tbody></table></div>
    </div>
    <div class="panel">
      <h2>策略状态</h2>
      <div class="table-wrap"><table><thead><tr><th>策略</th><th>名称</th><th>当前状态</th><th>今日机会</th><th>说明</th></tr></thead><tbody>{status_rows}</tbody></table></div>
    </div>
  </main>
  <script type="application/json" id="dashboard-data">{data}</script>
</body>
</html>
"""


def dashboard_html_data(dashboard: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": dashboard["schema_version"],
        "generated_at": dashboard["generated_at"],
        "candidate_definition": dashboard["candidate_definition"],
        "top_metrics": dashboard["top_metrics"],
        "trade_view_summary": dashboard["trade_view_summary"],
        "today_trade_view": dashboard["today_trade_view"],
        "strategy_status": dashboard["strategy_status"],
        "formal_daily_equity_curve": dashboard["formal_daily_equity_curve"],
        "paper_simulated_only": dashboard["paper_simulated_only"],
        "trading_connection": dashboard["trading_connection"],
        "real_money_actions": dashboard["real_money_actions"],
        "live_execution": dashboard["live_execution"],
        "approval_for_paper_trading_trial": dashboard["approval_for_paper_trading_trial"],
    }


def build_strategy_chart_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<div class=\"note\">暂无策略机会。</div>"
    max_abs = max(abs(decimal(row["simulated_unrealized_pnl"])) for row in rows) or ONE
    lines = ["<div class=\"bars\">"]
    for row in rows:
        pnl = decimal(row["simulated_unrealized_pnl"])
        width = max(4, int(abs(pnl) / max_abs * Decimal("100")))
        cls = "bar-fill negative" if pnl < 0 else "bar-fill"
        lines.append(
            "<div class=\"bar-row\">"
            f"<div>{html.escape(row['strategy_id'])}</div>"
            f"<div class=\"bar-track\"><div class=\"{cls}\" style=\"width:{width}%\"></div></div>"
            f"<div>{html.escape(row['simulated_unrealized_pnl'])}</div>"
            "</div>"
        )
    lines.append("</div>")
    return "\n".join(lines)


def build_equity_svg(points: list[dict[str, str]]) -> str:
    if len(points) < 2:
        return "<div class=\"note\">暂无资金曲线。</div>"
    values = [decimal(point["equity"]) for point in points]
    min_v = min(values)
    max_v = max(values)
    span = max(max_v - min_v, ONE)
    width = Decimal("700")
    height = Decimal("190")
    coords = []
    for index, value in enumerate(values):
        x = Decimal(index) / Decimal(max(len(values) - 1, 1)) * width
        y = height - ((value - min_v) / span * height)
        coords.append(f"{pct(x)},{pct(y)}")
    return (
        "<svg viewBox=\"0 0 700 220\" role=\"img\" aria-label=\"早期日线策略历史模拟资金曲线\">"
        "<rect x=\"0\" y=\"0\" width=\"700\" height=\"220\" fill=\"#ffffff\"/>"
        "<line x1=\"0\" y1=\"190\" x2=\"700\" y2=\"190\" stroke=\"#d8dde5\"/>"
        f"<polyline fill=\"none\" stroke=\"#16794c\" stroke-width=\"3\" points=\"{' '.join(coords)}\"/>"
        f"<text x=\"0\" y=\"212\" font-size=\"13\" fill=\"#5c6675\">起点 {html.escape(points[0]['equity'])}</text>"
        f"<text x=\"560\" y=\"212\" font-size=\"13\" fill=\"#5c6675\">当前 {html.escape(points[-1]['equity'])}</text>"
        "</svg>"
    )


def build_daily_report_md(summary: dict[str, Any], dashboard: dict[str, Any]) -> str:
    metrics = dashboard["top_metrics"]
    trade_summary = dashboard["trade_view_summary"]
    lines = [
        "# M12.12 每日只读测试报告",
        "",
        "## 先看结果",
        "",
        f"- 今日机会数：`{metrics['今日机会数']}`",
        f"- 今日机会估算盈亏（未成交）：`{metrics['今日机会估算盈亏（未成交）']}`",
        f"- 今日机会估算收益率（未成交）：`{metrics['今日机会估算收益率（未成交）']}%`",
        f"- 今日浮盈机会占比：`{metrics['今日浮盈机会占比']}%`",
        f"- 早期日线历史模拟盈利：`{metrics['早期日线历史模拟盈利']}`",
        f"- 早期日线历史收益率：`{metrics['早期日线历史收益率']}%`",
        f"- 早期日线历史胜率：`{metrics['早期日线历史胜率']}%`",
        f"- 早期日线最大回撤：`{metrics['早期日线最大回撤']}%`",
        f"- 第一批可测股票：`{metrics['第一批可测股票']}/50`",
        f"- 当前5分钟可观察股票：`{metrics['当前5分钟可观察股票']}/50`",
        "",
        "## 候选是什么意思",
        "",
        f"候选不是已经成交的交易。候选是一条“策略 x 标的 x 周期”的可观察机会；同一只股票可以同时有日线机会、15分钟机会、5分钟机会，所以 `{metrics['今日机会数']}` 条不是 `{metrics['今日机会数']}` 只股票，也不是已经下了 `{metrics['今日机会数']}` 笔单。",
        "",
        "## 今日机会估算视图（未成交）",
        "",
        f"- 按每笔最多亏 `500 USD` 粗算，今日所有机会的未成交估算盈亏合计：`{trade_summary['simulated_unrealized_pnl']}`。",
        f"- 当前浮盈机会：`{trade_summary['floating_positive_count']}` 条；当前浮亏机会：`{trade_summary['floating_negative_count']}` 条。",
        "- 这些只是只读观察数据，没有真实成交、真实持仓或真实账户。",
        "",
        "## 说明",
        "",
        "本报告只做只读/模拟观察，没有真实交易动作。早期日线策略收益强，但回撤也大，下一步应该按来源补定义、降回撤，而不是按收益曲线硬调参数。图形策略 `M10-PA-008/009` 已整理确认包，等待你看关键模糊图。",
        "",
        "## 必须注意",
        "",
        f"- 长历史 `5m` 全窗口目前是 `{metrics['长历史5分钟完整度']}`，所以现在只能说“当前交易日5分钟每日观察可用”，不能说“两年日内历史已完整”。",
        f"- `M12-FTD-001` 当前定位是：{metrics['日线策略定位']}；它参与每日观察和选股参考，但不作为模拟交易准入候选。",
    ]
    return "\n".join(lines) + "\n"


def build_handoff(config: M1212Config, summary: dict[str, Any]) -> str:
    return f"""task_id: M12.12 Daily Observation Loop
role: main_agent
branch_or_worktree: feature/m12-12-daily-observation-loop
objective: Build the first daily readonly loop for 50 symbols, formalize the early daily strategy as a factor-only candidate, generate dashboard/status/gate artifacts, and keep paper trading closed.
status: success
files_changed:
  - config/examples/m12_12_daily_observation_loop.json
  - scripts/m12_12_daily_observation_loop_lib.py
  - scripts/run_m12_12_daily_observation_loop.py
  - tests/unit/test_m12_12_daily_observation_loop.py
  - reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_12_loop/
  - docs/status.md
  - plans/active-plan.md
  - reports/strategy_lab/README.md
interfaces_changed:
  - Added M12.12 readonly daily loop runner and local dashboard artifacts.
commands_run:
  - python scripts/run_m12_12_daily_observation_loop.py --max-native-fetches 100
  - python scripts/run_m12_12_daily_observation_loop.py --max-native-fetches 2
  - python scripts/run_m12_12_daily_observation_loop.py --no-fetch
tests_run:
  - python scripts/validate_kb.py
  - python scripts/validate_kb_coverage.py
  - python scripts/validate_knowledge_atoms.py
  - python -m unittest tests/unit/test_m12_12_daily_observation_loop.py -v
  - python -m unittest discover -s tests/unit -v
  - python -m unittest discover -s tests/reliability -v
  - git diff --check
assumptions:
  - First-50 means M12.5 static seed order, not a live liquidity ranking.
  - Current 5m cache is enough for daily readonly observation, not for two-year intraday historical claims.
risks:
  - Continuous 10-trading-day observation has not been completed yet.
  - M10-PA-008/009 user visual confirmation is still pending.
qa_focus:
  - Confirm M12-FTD-001 stays factor-only and outside M11.6 gate candidates.
  - Confirm manual user approval remains a blocker.
rollback_notes:
  - Revert the M12.12 commit and remove {project_path(config.output_dir)} artifacts.
next_recommended_action: Run the daily loop for 10 trading days, complete priority visual confirmations, then re-run M11.6 gate.
needs_user_decision: false
user_decision_needed:
summary:
  first50_daily_ready: {summary['first50_cache']['daily_ready_symbols']}
  first50_current_5m_ready: {summary['first50_cache']['current_5m_ready_symbols']}
  first50_full_5m_target_ready: {summary['first50_cache']['full_5m_target_ready_symbols']}
  daily_candidate_count: {summary['daily_loop']['candidate_count']}
  paper_gate_approval: {summary['paper_gate_recheck']['approval_for_paper_trading_trial']}
"""


def assert_no_forbidden_output(output_dir: Path) -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in output_dir.glob("m12_12_*")
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md", ".html", ".csv"}
    )
    lowered = combined.lower()
    for forbidden in FORBIDDEN_TEXT:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden M12.12 output text found: {forbidden}")
