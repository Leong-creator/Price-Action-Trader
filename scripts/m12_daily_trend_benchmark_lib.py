#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.public_backtest_demo_lib import (
    ARTIFACT_CSV_LINE_TERMINATOR,
    DatasetCacheRecord,
    DemoRiskSettings,
    InstrumentConfig,
    SymbolBacktestResult,
    compute_max_drawdown,
    run_paper_demo,
)
from src.backtest import run_backtest
from src.data import OhlcvRow, load_ohlcv_csv
from src.strategy import Signal


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_7_DIR = M10_DIR / "benchmark" / "m12_7_daily_trend_benchmark"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_daily_trend_benchmark.json"
BENCHMARK_ID = "M12-BENCH-001"
SETUP_TYPE = "signal_bar_entry_placeholder"
ALLOWED_DECISIONS = ("benchmark_only", "scanner_factor_candidate", "reject_as_overfit")
FORBIDDEN_TEXT = (
    "PA-SC-",
    "SF-",
    "live" + "-ready",
    "broker",
    "account",
    "position",
    "order",
    "fill",
)
FROZEN_BENCHMARK_SOURCE_REFS = (
    "wiki:knowledge/wiki/concepts/market-cycle-overview.md",
    "wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md",
    "wiki:knowledge/wiki/rules/m3-research-reference-pack.md",
    "wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md",
    "raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf",
    "wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md",
    "raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf",
)
CSV_LINE_TERMINATOR = "\n"
QUANT = Decimal("0.0001")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
CACHE_NAME_RE = re.compile(
    r"^(?P<market>[a-z]+)_(?P<symbol>.+)_(?P<interval>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})_(?P<source>[^.]+)\.csv$"
)


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    allowed_decisions: tuple[str, ...]
    scanner_factor_min_event_count: int
    scanner_factor_min_profit_factor: Decimal
    scanner_factor_max_symbol_profit_share: Decimal


@dataclass(frozen=True, slots=True)
class DailyTrendBenchmarkConfig:
    title: str
    run_id: str
    description: str
    strategy_id: str
    strategy_name: str
    stage: str
    start: date
    end: date
    interval: str
    cache_dir: Path
    output_dir: Path
    comparison_dashboard_path: Path
    comparison_strategy_ids: tuple[str, ...]
    legacy_reference_run: Path
    runtime_scope: str
    gate_evidence: bool
    instruments: tuple[InstrumentConfig, ...]
    simulation_budget: DemoRiskSettings
    decision_policy: DecisionPolicy


@dataclass(frozen=True, slots=True)
class CacheSelection:
    instrument: InstrumentConfig
    source: str
    csv_path: Path | None
    metadata_path: Path | None
    cache_start: date | None
    cache_end: date | None
    row_count: int
    selected_reason: str
    deferred_reason: str | None = None


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def project_path(path: str | Path) -> str:
    candidate = Path(path)
    try:
        return candidate.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return candidate.as_posix()


def load_benchmark_config(path: str | Path = DEFAULT_CONFIG_PATH) -> DailyTrendBenchmarkConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    instruments = tuple(
        InstrumentConfig(
            ticker=item["ticker"],
            symbol=item["symbol"],
            label=item["label"],
            market=item["market"],
            timezone=item["timezone"],
            demo_role=item.get("demo_role", "benchmark"),
        )
        for item in payload["instruments"]
    )
    budget_payload = payload["simulation_budget"]
    policy_payload = payload["decision_policy"]
    config = DailyTrendBenchmarkConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_7_daily_trend_benchmark"),
        description=payload["description"],
        strategy_id=payload["strategy_id"],
        strategy_name=payload["strategy_name"],
        stage=payload["stage"],
        start=date.fromisoformat(payload["start"]),
        end=date.fromisoformat(payload["end"]),
        interval=payload["interval"],
        cache_dir=resolve_repo_path(payload["cache_dir"]),
        output_dir=resolve_repo_path(payload["output_dir"]),
        comparison_dashboard_path=resolve_repo_path(payload["comparison_dashboard_path"]),
        comparison_strategy_ids=tuple(payload["comparison_strategy_ids"]),
        legacy_reference_run=resolve_repo_path(payload["legacy_reference_run"]),
        runtime_scope=payload["runtime_scope"],
        gate_evidence=bool(payload.get("gate_evidence", False)),
        instruments=instruments,
        simulation_budget=DemoRiskSettings(
            starting_capital=decimal(budget_payload["starting_capital"]),
            risk_per_trade=decimal(budget_payload["unit_budget"]),
            max_total_exposure=decimal(budget_payload["max_gross_exposure"]),
            max_symbol_exposure_ratio=decimal(budget_payload["max_symbol_allocation_ratio"]),
            max_daily_loss=decimal(budget_payload["session_loss_budget"]),
            max_consecutive_losses=int(budget_payload["max_loss_streak"]),
        ),
        decision_policy=DecisionPolicy(
            allowed_decisions=tuple(policy_payload["allowed_decisions"]),
            scanner_factor_min_event_count=int(policy_payload["scanner_factor_min_event_count"]),
            scanner_factor_min_profit_factor=decimal(policy_payload["scanner_factor_min_profit_factor"]),
            scanner_factor_max_symbol_profit_share=decimal(policy_payload["scanner_factor_max_symbol_profit_share"]),
        ),
    )
    validate_config(config)
    return config


def validate_config(config: DailyTrendBenchmarkConfig) -> None:
    if config.strategy_id != BENCHMARK_ID:
        raise ValueError(f"M12.7 benchmark strategy_id must be {BENCHMARK_ID}")
    if config.interval != "1d":
        raise ValueError("M12.7 benchmark only supports daily bars")
    if config.runtime_scope != "historical_simulation_benchmark_only":
        raise ValueError("M12.7 benchmark runtime_scope must stay historical_simulation_benchmark_only")
    if config.gate_evidence:
        raise ValueError("M12.7 benchmark must not count as gate evidence")
    if set(config.decision_policy.allowed_decisions) != set(ALLOWED_DECISIONS):
        raise ValueError(f"M12.7 benchmark decisions must be exactly {ALLOWED_DECISIONS}")


def run_m12_daily_trend_benchmark(
    config: DailyTrendBenchmarkConfig,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    validate_config(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    selections = tuple(select_local_cache(config, instrument) for instrument in config.instruments)
    runnable_records = tuple(selection_to_dataset_record(config, item) for item in selections if item.csv_path is not None)
    symbol_results = tuple(run_symbol_benchmark(config, record) for record in runnable_records)
    paper_outcome = run_paper_demo(symbol_results, risk_settings=config.simulation_budget)
    core = compute_core_metrics(config, paper_outcome)
    decision, decision_reason = decide_benchmark(config, core, symbol_results, paper_outcome)
    comparison_rows = build_comparison_rows(config, paper_outcome, decision)
    summary = build_summary(
        config,
        generated_at,
        selections,
        symbol_results,
        paper_outcome,
        comparison_rows,
        core,
        decision,
        decision_reason,
    )

    write_json(config.output_dir / "m12_7_daily_trend_benchmark_summary.json", summary)
    write_deferred_inputs(config.output_dir / "m12_7_daily_trend_benchmark_deferred_inputs.json", selections)
    legacy_trade_path = config.output_dir / "m12_7_daily_trend_benchmark_trades.csv"
    if legacy_trade_path.exists():
        legacy_trade_path.unlink()
    write_simulated_event_ledger(
        config.output_dir / "m12_7_daily_trend_benchmark_simulated_events.csv",
        paper_outcome.executed_trades,
    )
    write_equity_curve_csv(config.output_dir / "m12_7_daily_trend_benchmark_equity_curve.csv", paper_outcome.equity_points)
    write_comparison_csv(config.output_dir / "m12_7_daily_trend_benchmark_comparison.csv", comparison_rows)
    (config.output_dir / "m12_7_daily_trend_benchmark_report.md").write_text(
        build_report(summary, comparison_rows),
        encoding="utf-8",
    )
    (config.output_dir / "m12_7_handoff.md").write_text(build_handoff(config, summary), encoding="utf-8")
    assert_no_forbidden_output(config.output_dir)
    return summary


def select_local_cache(config: DailyTrendBenchmarkConfig, instrument: InstrumentConfig) -> CacheSelection:
    exact = config.cache_dir / (
        f"{instrument.market.lower()}_{instrument.symbol.replace('.', '-')}_{config.interval}_"
        f"{config.start.isoformat()}_{config.end.isoformat()}_longbridge.csv"
    )
    if exact.exists():
        return cache_selection_from_path(config, instrument, exact, "exact_window_match")

    candidates: list[tuple[date, date, Path]] = []
    pattern = f"{instrument.market.lower()}_{instrument.symbol.replace('.', '-')}_{config.interval}_*_longbridge.csv"
    for path in sorted(config.cache_dir.glob(pattern)):
        parsed = parse_cache_window(path.name)
        if parsed is None:
            continue
        cache_start, cache_end = parsed
        if cache_start <= config.start and cache_end >= config.end:
            candidates.append((cache_start, cache_end, path))

    if candidates:
        candidates.sort(key=lambda item: ((item[1] - item[0]).days, item[0], item[2].name))
        return cache_selection_from_path(config, instrument, candidates[0][2], "covering_window_match")

    return CacheSelection(
        instrument=instrument,
        source="longbridge_local_cache",
        csv_path=None,
        metadata_path=None,
        cache_start=None,
        cache_end=None,
        row_count=0,
        selected_reason="deferred_missing_local_cache",
        deferred_reason=f"missing local daily cache covering {config.start.isoformat()} to {config.end.isoformat()}",
    )


def parse_cache_window(filename: str) -> tuple[date, date] | None:
    match = CACHE_NAME_RE.match(filename)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group("start")), date.fromisoformat(match.group("end"))
    except ValueError:
        return None


def cache_selection_from_path(
    config: DailyTrendBenchmarkConfig,
    instrument: InstrumentConfig,
    csv_path: Path,
    selected_reason: str,
) -> CacheSelection:
    parsed = parse_cache_window(csv_path.name)
    cache_start, cache_end = parsed if parsed is not None else (None, None)
    row_count = len(filter_bars(load_ohlcv_csv(csv_path), config.start, config.end))
    return CacheSelection(
        instrument=instrument,
        source="longbridge_local_cache",
        csv_path=csv_path,
        metadata_path=csv_path.with_suffix(".metadata.json"),
        cache_start=cache_start,
        cache_end=cache_end,
        row_count=row_count,
        selected_reason=selected_reason,
    )


def selection_to_dataset_record(config: DailyTrendBenchmarkConfig, selection: CacheSelection) -> DatasetCacheRecord:
    if selection.csv_path is None or selection.metadata_path is None:
        raise ValueError("Cannot build dataset record from deferred cache selection")
    return DatasetCacheRecord(
        instrument=selection.instrument,
        source=selection.source,
        csv_path=selection.csv_path,
        metadata_path=selection.metadata_path,
        row_count=selection.row_count,
    )


def run_symbol_benchmark(config: DailyTrendBenchmarkConfig, record: DatasetCacheRecord) -> SymbolBacktestResult:
    bars = filter_bars(load_ohlcv_csv(record.csv_path), config.start, config.end)
    signals = generate_frozen_benchmark_signals(bars)
    backtest_report = run_backtest(bars, signals)
    return SymbolBacktestResult(
        instrument=record.instrument,
        source=record.source,
        csv_path=record.csv_path,
        metadata_path=record.metadata_path,
        bars=tuple(bars),
        bars_count=len(bars),
        signals=tuple(signals),
        backtest_report=backtest_report,
    )


def generate_frozen_benchmark_signals(bars: tuple[OhlcvRow, ...]) -> tuple[Signal, ...]:
    signals: list[Signal] = []
    active_direction: str | None = None
    history: list[OhlcvRow] = []
    for index, bar in enumerate(bars):
        history.append(bar)
        market_cycle, bias, regime_summary = classify_frozen_context(tuple(history[-3:]))
        direction = identify_frozen_setup(history, market_cycle, bias, active_direction)
        if direction is None:
            if context_resets_frozen_direction(market_cycle, bias, active_direction):
                active_direction = None
            continue
        signals.append(build_frozen_signal(bar, index, direction, regime_summary))
        active_direction = direction
    return tuple(signals)


def classify_frozen_context(bars: tuple[OhlcvRow, ...]) -> tuple[str, str, str]:
    if len(bars) < 3:
        return "transition", "neutral", "insufficient history for context classification"
    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    if closes[0] < closes[1] < closes[2] and highs[0] <= highs[1] <= highs[2] and lows[0] <= lows[1] <= lows[2]:
        return "trend", "bullish", "three-bar upward progression with rising highs/lows"
    if closes[0] > closes[1] > closes[2] and highs[0] >= highs[1] >= highs[2] and lows[0] >= lows[1] >= lows[2]:
        return "trend", "bearish", "three-bar downward progression with falling highs/lows"
    closing_range = max(closes) - min(closes)
    reference_price = closes[-1]
    if reference_price > ZERO and closing_range <= reference_price * Decimal("0.003"):
        return "trading-range", "neutral", "recent closes are compressed into a narrow range"
    return "transition", "neutral", "recent bars do not show a stable trend or tight trading range"


def identify_frozen_setup(history: list[OhlcvRow], market_cycle: str, bias: str, active_direction: str | None) -> str | None:
    if len(history) < 3 or market_cycle != "trend":
        return None
    bar = history[-1]
    previous_bar = history[-2]
    body_size = abs(bar.close - bar.open)
    bar_range = bar.high - bar.low
    if bar_range <= ZERO or body_size <= ZERO:
        return None
    direction: str | None = None
    if bias == "bullish" and bar.close > bar.open and bar.close > previous_bar.close and body_size >= bar_range * Decimal("0.4"):
        direction = "long"
    elif bias == "bearish" and bar.close < bar.open and bar.close < previous_bar.close and body_size >= bar_range * Decimal("0.4"):
        direction = "short"
    if direction is None:
        return None
    if direction == active_direction:
        return None
    if direction == "long" and bar.close <= previous_bar.high:
        return None
    if direction == "short" and bar.close >= previous_bar.low:
        return None
    return direction


def context_resets_frozen_direction(market_cycle: str, bias: str, active_direction: str | None) -> bool:
    if active_direction is None:
        return False
    if market_cycle != "trend" or bias == "neutral":
        return True
    if active_direction == "long" and bias == "bearish":
        return True
    if active_direction == "short" and bias == "bullish":
        return True
    return False


def build_frozen_signal(bar: OhlcvRow, index: int, direction: str, regime_summary: str) -> Signal:
    return Signal(
        signal_id=build_frozen_signal_id(bar, direction),
        symbol=bar.symbol,
        market=bar.market,
        timeframe=bar.timeframe,
        direction=direction,
        setup_type=SETUP_TYPE,
        pa_context="trend",
        entry_trigger=f"frozen placeholder confirmation for {direction}; enter beyond the signal bar extreme",
        stop_rule=f"frozen protective stop for {direction}; use the signal bar opposite extreme",
        target_rule=f"frozen initial target for {direction}; use fixed 2R placeholder target",
        invalidation=(
            f"cancel {direction} placeholder setup unless the signal bar closes beyond "
            f"the {'prior high' if direction == 'long' else 'prior low'}"
        ),
        confidence="low",
        source_refs=FROZEN_BENCHMARK_SOURCE_REFS,
        actual_source_refs=FROZEN_BENCHMARK_SOURCE_REFS,
        bundle_support_refs=(),
        explanation=(
            f"frozen M12.7 daily trend benchmark triggered after {regime_summary}; "
            f"bar {index} closed {'above' if direction == 'long' else 'below'} the prior close with a directional body"
        ),
        risk_notes=(
            "research-only placeholder setup; not validated as a deployable strategy",
            "frozen for M12.7 benchmark reproducibility",
        ),
        knowledge_trace=(),
        knowledge_debug_trace=(),
    )


def build_frozen_signal_id(bar: OhlcvRow, direction: str) -> str:
    payload = "|".join([SETUP_TYPE, direction, bar.symbol, bar.market, bar.timeframe, bar.timestamp.isoformat()])
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def filter_bars(rows: list[OhlcvRow] | tuple[OhlcvRow, ...], start: date, end: date) -> tuple[OhlcvRow, ...]:
    return tuple(row for row in rows if start <= row.timestamp.date() <= end)


def build_summary(
    config: DailyTrendBenchmarkConfig,
    generated_at: str,
    selections: tuple[CacheSelection, ...],
    symbol_results: tuple[SymbolBacktestResult, ...],
    paper_outcome: Any,
    comparison_rows: list[dict[str, str]],
    core: dict[str, Any],
    decision: str,
    decision_reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": "m12.daily-trend-benchmark-summary.v1",
        "stage": config.stage,
        "run_id": config.run_id,
        "generated_at": generated_at,
        "title": config.title,
        "strategy_id": config.strategy_id,
        "strategy_name": config.strategy_name,
        "legacy_reference_run": project_path(config.legacy_reference_run),
        "legacy_source_logic": "signal_bar_entry_placeholder",
        "benchmark_signal_contract": {
            "contract_version": "m12-bench-001.frozen-signal-bar-placeholder.v1",
            "implementation": "scripts/m12_daily_trend_benchmark_lib.py::generate_frozen_benchmark_signals",
            "source_refs": list(FROZEN_BENCHMARK_SOURCE_REFS),
        },
        "clean_room_catalog_source": False,
        "boundary": {
            "runtime_scope": config.runtime_scope,
            "benchmark_only": True,
            "gate_evidence": False,
            "clean_room_catalog_source": False,
        },
        "time_range": {
            "start": config.start.isoformat(),
            "end": config.end.isoformat(),
            "interval": config.interval,
        },
        "simulation_budget": {
            "starting_capital": money(config.simulation_budget.starting_capital),
            "unit_budget": money(config.simulation_budget.risk_per_trade),
            "max_gross_exposure": money(config.simulation_budget.max_total_exposure),
            "max_symbol_allocation_ratio": decimal_str(config.simulation_budget.max_symbol_exposure_ratio),
            "session_loss_budget": money(config.simulation_budget.max_daily_loss),
            "max_loss_streak": config.simulation_budget.max_consecutive_losses,
        },
        "core_results": core,
        "per_symbol": build_per_symbol_rows(symbol_results, paper_outcome),
        "data_inventory": [selection_payload(item) for item in selections],
        "deferred_symbol_count": sum(1 for item in selections if item.deferred_reason),
        "benchmark_decision": decision,
        "benchmark_decision_reason": decision_reason,
        "scanner_factor_allowed": decision == "scanner_factor_candidate",
        "comparison_strategy_ids": list(config.comparison_strategy_ids),
        "comparison_artifact": project_path(config.output_dir / "m12_7_daily_trend_benchmark_comparison.csv"),
        "not_allowed": [
            "clean_room_catalog_source",
            "gate_evidence",
            "direct_strategy_candidate",
        ],
    }


def compute_core_metrics(config: DailyTrendBenchmarkConfig, paper_outcome: Any) -> dict[str, Any]:
    simulated_events = tuple(paper_outcome.executed_trades)
    total_result = paper_outcome.ending_equity - config.simulation_budget.starting_capital
    wins = [item for item in simulated_events if item.pnl_cash > ZERO]
    losses = [item for item in simulated_events if item.pnl_cash < ZERO]
    gross_profit = sum((item.pnl_cash for item in wins), ZERO)
    gross_loss = sum((-item.pnl_cash for item in losses), ZERO)
    profit_factor = None if gross_loss == ZERO else gross_profit / gross_loss
    simulated_drawdown, simulated_drawdown_pct = compute_max_drawdown(paper_outcome.equity_points)
    return {
        "simulated_starting_capital": money(config.simulation_budget.starting_capital),
        "simulated_final_equity": money(paper_outcome.ending_equity),
        "simulated_net_result": money(total_result),
        "simulated_return_percent": decimal_str(
            percent(total_result / config.simulation_budget.starting_capital if config.simulation_budget.starting_capital else ZERO)
        ),
        "benchmark_event_count": len(simulated_events),
        "suppressed_signal_count": len(paper_outcome.blocked_signals),
        "win_rate": decimal_str(Decimal(len(wins)) / Decimal(len(simulated_events))) if simulated_events else "",
        "win_rate_percent": decimal_str(percent(Decimal(len(wins)) / Decimal(len(simulated_events)))) if simulated_events else "",
        "profit_factor": decimal_str(profit_factor) if profit_factor is not None else "",
        "simulated_drawdown": money(simulated_drawdown),
        "simulated_drawdown_percent": decimal_str(simulated_drawdown_pct),
    }


def build_per_symbol_rows(symbol_results: tuple[SymbolBacktestResult, ...], paper_outcome: Any) -> list[dict[str, Any]]:
    executed_by_symbol: dict[str, list[Any]] = {}
    blocked_by_symbol: dict[str, list[Any]] = {}
    for item in paper_outcome.executed_trades:
        executed_by_symbol.setdefault(item.instrument.symbol, []).append(item)
    for item in paper_outcome.blocked_signals:
        blocked_by_symbol.setdefault(item.instrument.symbol, []).append(item)

    rows: list[dict[str, Any]] = []
    for result in symbol_results:
        executed = executed_by_symbol.get(result.instrument.symbol, [])
        blocked = blocked_by_symbol.get(result.instrument.symbol, [])
        wins = [item for item in executed if item.pnl_cash > ZERO]
        simulated_result = sum((item.pnl_cash for item in executed), ZERO)
        rows.append(
            {
                "symbol": result.instrument.symbol,
                "label": result.instrument.label,
                "market": result.instrument.market,
                "source": result.source,
                "bars": result.bars_count,
                "benchmark_signal_count": len(result.signals),
                "baseline_event_count": len(result.backtest_report.trades),
                "simulated_event_count": len(executed),
                "suppressed_signal_count": len(blocked),
                "simulated_net_result": money(simulated_result),
                "win_rate": decimal_str(Decimal(len(wins)) / Decimal(len(executed))) if executed else "",
                "win_rate_percent": decimal_str(percent(Decimal(len(wins)) / Decimal(len(executed)))) if executed else "",
                "cache_csv": project_path(result.csv_path),
            }
        )
    return rows


def decide_benchmark(
    config: DailyTrendBenchmarkConfig,
    core: dict[str, Any],
    symbol_results: tuple[SymbolBacktestResult, ...],
    paper_outcome: Any,
) -> tuple[str, str]:
    if not symbol_results:
        return "benchmark_only", "没有可用本地日线缓存，不能评价为 scanner 因子。"
    event_count = int(core["benchmark_event_count"])
    if event_count < config.decision_policy.scanner_factor_min_event_count:
        return "benchmark_only", "模拟事件样本不足，只能保留为 benchmark。"

    try:
        profit_factor = decimal(core["profit_factor"])
    except (InvalidOperation, TypeError):
        profit_factor = ZERO
    if profit_factor < config.decision_policy.scanner_factor_min_profit_factor:
        return "benchmark_only", "profit factor 未超过 scanner factor 最低门槛。"

    total_positive = sum((item.pnl_cash for item in paper_outcome.executed_trades if item.pnl_cash > ZERO), ZERO)
    if total_positive > ZERO:
        symbol_profit: dict[str, Decimal] = {}
        for item in paper_outcome.executed_trades:
            if item.pnl_cash > ZERO:
                symbol_profit[item.instrument.symbol] = symbol_profit.get(item.instrument.symbol, ZERO) + item.pnl_cash
        max_share = max(symbol_profit.values(), default=ZERO) / total_positive
        if max_share > config.decision_policy.scanner_factor_max_symbol_profit_share:
            return "reject_as_overfit", "正向模拟结果过度集中在单一标的，按过拟合风险拒绝。"

    net_result = decimal(core["simulated_net_result"])
    if net_result <= ZERO:
        return "benchmark_only", "长窗口模拟净结果不为正，只能保留为 benchmark。"
    return "scanner_factor_candidate", "长窗口样本、profit factor 与收益集中度满足 scanner 因子候选门槛。"


def build_comparison_rows(config: DailyTrendBenchmarkConfig, paper_outcome: Any, decision: str) -> list[dict[str, str]]:
    rows = [
        {
            "strategy_id": config.strategy_id,
            "title": config.strategy_name,
            "source_family": "early_daily_placeholder_benchmark",
            "capital_test_status": decision,
            "simulated_starting_capital": money(config.simulation_budget.starting_capital),
            "simulated_final_equity": money(paper_outcome.ending_equity),
            "simulated_net_result": money(paper_outcome.ending_equity - config.simulation_budget.starting_capital),
            "simulated_return_percent": decimal_str(
                percent((paper_outcome.ending_equity - config.simulation_budget.starting_capital) / config.simulation_budget.starting_capital)
            ),
            "win_rate": compute_win_rate(paper_outcome.executed_trades),
            "profit_factor": compute_profit_factor(paper_outcome.executed_trades),
            "simulated_drawdown_percent": decimal_str(compute_max_drawdown(paper_outcome.equity_points)[1]),
            "benchmark_event_count": str(len(paper_outcome.executed_trades)),
            "gate_evidence": "false",
            "client_note": "早期截图逻辑，只能作为日线 benchmark 或 scanner 排名因子候选。",
        }
    ]
    rows.extend(load_m10_comparison_rows(config))
    return rows


def load_m10_comparison_rows(config: DailyTrendBenchmarkConfig) -> list[dict[str, str]]:
    if not config.comparison_dashboard_path.exists():
        return []
    with config.comparison_dashboard_path.open(newline="", encoding="utf-8") as handle:
        source_rows = [row for row in csv.DictReader(handle) if row["strategy_id"] in config.comparison_strategy_ids]
    rows: list[dict[str, str]] = []
    for row in source_rows:
        rows.append(
            {
                "strategy_id": row["strategy_id"],
                "title": row["title"],
                "source_family": "m10_clean_room_strategy",
                "capital_test_status": row["capital_test_status"],
                "simulated_starting_capital": row["initial_capital"],
                "simulated_final_equity": row["final_equity"],
                "simulated_net_result": row["net_profit"],
                "simulated_return_percent": row["return_percent"],
                "win_rate": row["win_rate"],
                "profit_factor": row["profit_factor"],
                "simulated_drawdown_percent": row["max_drawdown_percent"],
                "benchmark_event_count": row["trade_count"],
                "gate_evidence": "false",
                "client_note": row["client_note"],
            }
        )
    return rows


def write_comparison_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = (
        "strategy_id",
        "title",
        "source_family",
        "capital_test_status",
        "simulated_starting_capital",
        "simulated_final_equity",
        "simulated_net_result",
        "simulated_return_percent",
        "win_rate",
        "profit_factor",
        "simulated_drawdown_percent",
        "benchmark_event_count",
        "gate_evidence",
        "client_note",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator=CSV_LINE_TERMINATOR)
        writer.writeheader()
        writer.writerows(rows)


def write_equity_curve_csv(path: Path, equity_points: tuple[tuple[str, float], ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("timestamp", "simulated_equity"), lineterminator=ARTIFACT_CSV_LINE_TERMINATOR)
        writer.writeheader()
        for timestamp, equity in equity_points:
            writer.writerow({"timestamp": timestamp, "simulated_equity": money(Decimal(str(equity)))})


def write_simulated_event_ledger(path: Path, simulated_events: tuple[Any, ...]) -> None:
    fieldnames = (
        "symbol",
        "label",
        "market",
        "direction",
        "simulated_opened_at",
        "simulated_closed_at",
        "hypothetical_open_level",
        "hypothetical_close_level",
        "simulated_units",
        "simulated_cash_result",
        "simulated_r_result",
        "simulated_exit_reason",
        "setup_type",
        "hypothetical_entry_trigger",
        "hypothetical_stop_plan",
        "hypothetical_target_plan",
        "source_refs",
        "explanation",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator=CSV_LINE_TERMINATOR)
        writer.writeheader()
        for item in simulated_events:
            writer.writerow(
                {
                    "symbol": item.instrument.symbol,
                    "label": item.instrument.label,
                    "market": item.instrument.market,
                    "direction": item.trade.direction,
                    "simulated_opened_at": item.trade.entry_timestamp.isoformat(),
                    "simulated_closed_at": item.trade.exit_timestamp.isoformat(),
                    "hypothetical_open_level": money(item.trade.entry_price),
                    "hypothetical_close_level": money(item.trade.exit_price),
                    "simulated_units": decimal_str(item.quantity),
                    "simulated_cash_result": money(item.pnl_cash),
                    "simulated_r_result": decimal_str(item.trade.pnl_r),
                    "simulated_exit_reason": item.trade.exit_reason,
                    "setup_type": item.trade.setup_type,
                    "hypothetical_entry_trigger": item.signal.entry_trigger,
                    "hypothetical_stop_plan": item.signal.stop_rule,
                    "hypothetical_target_plan": item.signal.target_rule,
                    "source_refs": " | ".join(item.signal.source_refs),
                    "explanation": item.signal.explanation,
                }
            )


def write_deferred_inputs(path: Path, selections: tuple[CacheSelection, ...]) -> None:
    payload = {
        "schema_version": "m12.daily-trend-benchmark-deferred-inputs.v1",
        "deferred": [
            {
                "symbol": item.instrument.symbol,
                "market": item.instrument.market,
                "reason": item.deferred_reason,
            }
            for item in selections
            if item.deferred_reason
        ],
    }
    write_json(path, payload)


def build_report(summary: dict[str, Any], comparison_rows: list[dict[str, str]]) -> str:
    core = summary["core_results"]
    per_symbol_lines = "\n".join(
        "- `{symbol}`：模拟事件 `{simulated_event_count}` 条，模拟净结果 `${simulated_net_result}`，胜率 `{win_rate_percent}%`，benchmark 信号 `{benchmark_signal_count}` 个，缓存 `{cache_csv}`。".format(
            **row
        )
        for row in summary["per_symbol"]
    )
    comparison_lines = "\n".join(
        f"| {row['strategy_id']} | {row['source_family']} | {row['simulated_return_percent']}% | {row['win_rate']} | {row['simulated_drawdown_percent']}% | {row['benchmark_event_count']} | {row['capital_test_status']} |"
        for row in comparison_rows
    )
    return f"""# M12.7 Daily Trend Momentum Benchmark

## 结论

- Benchmark：`{summary['strategy_id']} {summary['strategy_name']}`
- 决策：`{summary['benchmark_decision']}`
- 原因：{summary['benchmark_decision_reason']}
- 边界：只作为早期日线趋势动量 benchmark / scanner factor 候选；不作为准入证据，不代表 Brooks clean-room 策略。

## 核心成绩

- 模拟初始资金：`${core['simulated_starting_capital']}`
- 模拟最终权益：`${core['simulated_final_equity']}`
- 模拟净结果：`${core['simulated_net_result']}`
- 模拟收益率：`{core['simulated_return_percent']}%`
- benchmark 事件数：`{core['benchmark_event_count']}`
- 胜率：`{core['win_rate_percent']}%`
- Profit factor：`{core['profit_factor']}`
- 模拟峰谷回落：`${core['simulated_drawdown']}` / `{core['simulated_drawdown_percent']}%`
- 被模拟预算规则压制的信号：`{core['suppressed_signal_count']}`

## 分标的

{per_symbol_lines}

## 与 M10 Tier A 对比

| ID | 来源族 | 模拟收益率 | 胜率 | 模拟峰谷回落 | 事件数 | 状态 |
|---|---:|---:|---:|---:|---:|---|
{comparison_lines}

## 交付边界

- 本阶段复用的是早期截图里的 `signal_bar_entry_placeholder`，不是 M10 clean-room catalog。
- 它只能作为 benchmark 或 scanner 排名因子候选，不能单独作为准入证据。
- 所有结果都是 historical simulation，不包含任何执行链路。
"""


def build_handoff(config: DailyTrendBenchmarkConfig, summary: dict[str, Any]) -> str:
    return f"""task_id: M12.7 Daily Trend Benchmark Reuse
role: main_agent
branch_or_worktree: feature/m12-7-daily-trend-benchmark
objective: Reuse early screenshot daily trend logic as {BENCHMARK_ID} benchmark only.
status: success
files_changed:
  - config/examples/m12_daily_trend_benchmark.json
  - scripts/m12_daily_trend_benchmark_lib.py
  - scripts/run_m12_daily_trend_benchmark.py
  - tests/unit/test_m12_daily_trend_benchmark.py
  - docs/status.md
  - docs/acceptance.md
  - plans/active-plan.md
  - README.md
  - reports/strategy_lab/README.md
  - reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_summary.json
  - reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_report.md
  - reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_simulated_events.csv
  - reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_equity_curve.csv
  - reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_comparison.csv
  - reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_deferred_inputs.json
  - reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_handoff.md
interfaces_changed:
  - Added M12.7 benchmark runner and artifacts.
commands_run:
  - python scripts/run_m12_daily_trend_benchmark.py
tests_run:
  - python scripts/validate_kb.py
  - python scripts/validate_kb_coverage.py
  - python scripts/validate_knowledge_atoms.py
  - python -m unittest tests/unit/test_m12_daily_trend_benchmark.py -v
  - python -m unittest discover -s tests/unit -v
  - python -m unittest discover -s tests/reliability -v
  - git diff --check
assumptions:
  - Longbridge local daily cache is available for SPY/QQQ/NVDA/TSLA.
  - The early screenshot strategy remains signal_bar_entry_placeholder and is not clean-room source of truth.
risks:
  - Benchmark may be useful as scanner factor but must not be used as direct gate evidence.
qa_focus:
  - Confirm benchmark_decision is one of {ALLOWED_DECISIONS}.
  - Confirm boundary keeps M12.7 as historical benchmark only.
rollback_notes:
  - Revert M12.7 commit or remove {project_path(config.output_dir)} artifacts.
next_recommended_action: Continue to M12.8 universe kline cache completion after review and tests pass.
needs_user_decision: false
user_decision_needed:
summary:
  benchmark_decision: {summary['benchmark_decision']}
  benchmark_event_count: {summary['core_results']['benchmark_event_count']}
  simulated_net_result: {summary['core_results']['simulated_net_result']}
"""


def selection_payload(selection: CacheSelection) -> dict[str, Any]:
    return {
        "symbol": selection.instrument.symbol,
        "market": selection.instrument.market,
        "source": selection.source,
        "selected_reason": selection.selected_reason,
        "csv_path": project_path(selection.csv_path) if selection.csv_path else None,
        "metadata_path": project_path(selection.metadata_path) if selection.metadata_path else None,
        "cache_start": selection.cache_start.isoformat() if selection.cache_start else None,
        "cache_end": selection.cache_end.isoformat() if selection.cache_end else None,
        "row_count": selection.row_count,
        "deferred_reason": selection.deferred_reason,
    }


def compute_win_rate(trades: tuple[Any, ...]) -> str:
    if not trades:
        return ""
    wins = sum(1 for item in trades if item.pnl_cash > ZERO)
    return decimal_str(Decimal(wins) / Decimal(len(trades)))


def compute_profit_factor(trades: tuple[Any, ...]) -> str:
    wins = [item.pnl_cash for item in trades if item.pnl_cash > ZERO]
    losses = [-item.pnl_cash for item in trades if item.pnl_cash < ZERO]
    gross_profit = sum(wins, ZERO)
    gross_loss = sum(losses, ZERO)
    if gross_loss == ZERO:
        return ""
    return decimal_str(gross_profit / gross_loss)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def assert_no_forbidden_output(output_dir: Path) -> None:
    combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in output_dir.glob("m12_7_*") if path.is_file())
    lowered = combined.lower()
    for forbidden in FORBIDDEN_TEXT:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden M12.7 output text found: {forbidden}")


def money(value: Decimal) -> str:
    return f"{quantize(value):.2f}"


def decimal_str(value: Decimal | str | None) -> str:
    if value is None or value == "":
        return ""
    return format(quantize(decimal(value)), "f")


def decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def quantize(value: Decimal) -> Decimal:
    return value.quantize(QUANT)


def percent(value: Decimal) -> Decimal:
    return value * HUNDRED
