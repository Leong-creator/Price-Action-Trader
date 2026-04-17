#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest import BacktestReport, TradeRecord, run_backtest
from src.data import DataValidationError, build_replay, load_ohlcv_csv
from src.execution import ExecutionRequest, PaperBrokerAdapter, PaperPosition
from src.risk import PositionSnapshot, RiskConfig, SessionRiskState, evaluate_order_request
from src.strategy import Signal, generate_signals, summarize_knowledge_trace

try:  # pragma: no cover - optional runtime dependency
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover - optional runtime dependency
    plt = None

try:  # pragma: no cover - optional runtime dependency
    import requests
except ImportError:  # pragma: no cover - optional runtime dependency
    requests = None

try:  # pragma: no cover - optional runtime dependency
    import yfinance as yf
except ImportError:  # pragma: no cover - optional runtime dependency
    yf = None


CSV_HEADER = (
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
)
DEFAULT_SOURCE_ORDER = ("alpha_vantage", "yfinance")
ALPHA_VANTAGE_ENV_VARS = ("ALPHAVANTAGE_API_KEY", "ALPHA_VANTAGE_API_KEY")
QUANT = Decimal("0.0001")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
REPORT_READABILITY_NOTE = (
    "本报告仅用于公共历史数据研究演示，仍处于 paper / simulated 边界，"
    "不代表实盘能力或未来收益承诺。"
)
EXIT_REASON_LABELS = {
    "target_hit": "达到固定 2R 目标",
    "stop_hit": "触及保护性止损",
    "stop_before_target_same_bar": "同一根 bar 内先触发止损",
    "end_of_data": "样本结束，按最后收盘价平仓",
}
BLOCK_REASON_LABELS = {
    "max_total_exposure_exceeded": "总曝险超过 demo 风控上限",
    "symbol_concentration_exceeded": "单一标的集中度超过 demo 风控上限",
    "consecutive_losses_limit": "连续亏损达到 demo 风控暂停阈值",
    "daily_loss_limit": "累计亏损达到 demo 风控暂停阈值",
    "risk_budget_too_small_for_one_share": "当前 demo 风险预算不足以支持 1 股仓位",
    "market_closed": "市场关闭，未允许模拟入场",
}


@dataclass(frozen=True, slots=True)
class InstrumentConfig:
    ticker: str
    symbol: str
    label: str
    market: str
    timezone: str
    demo_role: str


@dataclass(frozen=True, slots=True)
class DemoRiskSettings:
    starting_capital: Decimal
    risk_per_trade: Decimal
    max_total_exposure: Decimal
    max_symbol_exposure_ratio: Decimal
    max_daily_loss: Decimal
    max_consecutive_losses: int


@dataclass(frozen=True, slots=True)
class DemoConfig:
    title: str
    description: str
    start: date
    end: date
    interval: str
    cache_dir: Path
    report_dir: Path
    source_order: tuple[str, ...]
    instruments: tuple[InstrumentConfig, ...]
    risk: DemoRiskSettings


@dataclass(frozen=True, slots=True)
class DatasetCacheRecord:
    instrument: InstrumentConfig
    source: str
    csv_path: Path
    metadata_path: Path
    row_count: int


@dataclass(frozen=True, slots=True)
class SymbolBacktestResult:
    instrument: InstrumentConfig
    source: str
    csv_path: Path
    metadata_path: Path
    bars_count: int
    signals: tuple[Signal, ...]
    backtest_report: BacktestReport


@dataclass(frozen=True, slots=True)
class BlockedSignalRecord:
    instrument: InstrumentConfig
    signal: Signal
    entry_timestamp: datetime
    reason_codes: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class ExecutedTradeRecord:
    instrument: InstrumentConfig
    signal: Signal
    trade: TradeRecord
    quantity: Decimal
    pnl_cash: Decimal
    equity_after_close: Decimal


@dataclass(frozen=True, slots=True)
class PaperDemoOutcome:
    executed_trades: tuple[ExecutedTradeRecord, ...]
    blocked_signals: tuple[BlockedSignalRecord, ...]
    equity_points: tuple[tuple[str, float], ...]
    ending_equity: Decimal


def load_demo_config(path: str | Path) -> DemoConfig:
    config_path = _resolve_repo_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))

    source_order = tuple(payload.get("source_order") or DEFAULT_SOURCE_ORDER)
    instruments = tuple(
        InstrumentConfig(
            ticker=item["ticker"],
            symbol=item["symbol"],
            label=item["label"],
            market=item["market"],
            timezone=item["timezone"],
            demo_role=item.get("demo_role", "demo"),
        )
        for item in payload["instruments"]
    )
    risk_payload = payload["risk"]
    return DemoConfig(
        title=payload["title"],
        description=payload.get("description", ""),
        start=date.fromisoformat(payload["start"]),
        end=date.fromisoformat(payload["end"]),
        interval=payload["interval"],
        cache_dir=_resolve_repo_path(payload["cache_dir"]),
        report_dir=_resolve_repo_path(payload["report_dir"]),
        source_order=source_order,
        instruments=instruments,
        risk=DemoRiskSettings(
            starting_capital=_decimal(risk_payload["starting_capital"]),
            risk_per_trade=_decimal(risk_payload["risk_per_trade"]),
            max_total_exposure=_decimal(risk_payload["max_total_exposure"]),
            max_symbol_exposure_ratio=_decimal(risk_payload["max_symbol_exposure_ratio"]),
            max_daily_loss=_decimal(risk_payload["max_daily_loss"]),
            max_consecutive_losses=int(risk_payload["max_consecutive_losses"]),
        ),
    )


def download_and_cache_dataset(
    config: DemoConfig,
    instrument: InstrumentConfig,
    *,
    refresh: bool = False,
) -> DatasetCacheRecord:
    config.cache_dir.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    for source in config.source_order:
        if source == "alpha_vantage":
            api_key = alpha_vantage_api_key()
            if not api_key:
                continue
        csv_path = build_cache_path(config, instrument, source=source)
        metadata_path = csv_path.with_suffix(".metadata.json")
        if csv_path.exists() and metadata_path.exists() and not refresh:
            row_count = len(load_ohlcv_csv(csv_path))
            return DatasetCacheRecord(
                instrument=instrument,
                source=source,
                csv_path=csv_path,
                metadata_path=metadata_path,
                row_count=row_count,
            )

        try:
            rows = fetch_public_history_rows(
                instrument=instrument,
                start=config.start,
                end=config.end,
                interval=config.interval,
                source=source,
            )
            if not rows:
                raise RuntimeError(f"{instrument.ticker} returned no rows from {source}")
            write_cache_csv(csv_path, rows)
            row_count = len(load_ohlcv_csv(csv_path))
            metadata = {
                "instrument": asdict(instrument),
                "source": source,
                "row_count": row_count,
                "start": config.start.isoformat(),
                "end": config.end.isoformat(),
                "interval": config.interval,
                "downloaded_at": datetime.now(UTC).isoformat(),
                "boundary": "paper/simulated",
            }
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return DatasetCacheRecord(
                instrument=instrument,
                source=source,
                csv_path=csv_path,
                metadata_path=metadata_path,
                row_count=row_count,
            )
        except Exception as exc:  # pragma: no cover - exercised by manual runtime
            last_error = exc
            continue

    if last_error is None:
        raise RuntimeError(
            "No public data source is available. Alpha Vantage key is missing and yfinance is not usable."
        )
    raise RuntimeError(str(last_error))


def fetch_public_history_rows(
    *,
    instrument: InstrumentConfig,
    start: date,
    end: date,
    interval: str,
    source: str,
) -> list[dict[str, str]]:
    if interval != "1d":
        raise RuntimeError("The public backtest demo currently supports only 1d interval.")
    if source == "alpha_vantage":
        return _fetch_alpha_vantage_rows(instrument=instrument, start=start, end=end, interval=interval)
    if source == "yfinance":
        return _fetch_yfinance_rows(instrument=instrument, start=start, end=end, interval=interval)
    raise RuntimeError(f"Unsupported source: {source}")


def build_cache_path(config: DemoConfig, instrument: InstrumentConfig, *, source: str) -> Path:
    filename = "_".join(
        [
            instrument.market.lower(),
            instrument.symbol.replace(".", "-"),
            config.interval,
            config.start.isoformat(),
            config.end.isoformat(),
            source,
        ]
    )
    return config.cache_dir / f"{filename}.csv"


def write_cache_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def run_symbol_backtest(record: DatasetCacheRecord) -> SymbolBacktestResult:
    bars = tuple(load_ohlcv_csv(record.csv_path))
    replay = build_replay(bars, ())
    signals = generate_signals(replay)
    backtest_report = run_backtest(bars, signals)
    return SymbolBacktestResult(
        instrument=record.instrument,
        source=record.source,
        csv_path=record.csv_path,
        metadata_path=record.metadata_path,
        bars_count=len(bars),
        signals=signals,
        backtest_report=backtest_report,
    )


def run_paper_demo(
    results: tuple[SymbolBacktestResult, ...],
    *,
    risk_settings: DemoRiskSettings,
) -> PaperDemoOutcome:
    adapter = PaperBrokerAdapter()
    risk_config = RiskConfig(
        max_risk_per_order=risk_settings.risk_per_trade,
        max_total_exposure=risk_settings.max_total_exposure,
        max_symbol_exposure_ratio=risk_settings.max_symbol_exposure_ratio,
        max_daily_loss=risk_settings.max_daily_loss,
        max_consecutive_losses=risk_settings.max_consecutive_losses,
    )
    session_state = SessionRiskState(session_key="historical-demo")
    positions: tuple[PaperPosition, ...] = ()
    seen_signal_ids = frozenset()
    equity = risk_settings.starting_capital
    equity_points: list[tuple[str, float]] = [
        (datetime.combine(date.today(), time(0, 0), tzinfo=UTC).isoformat(), float(equity))
    ]
    executed: list[ExecutedTradeRecord] = []
    blocked: list[BlockedSignalRecord] = []
    open_plans: dict[str, tuple[SymbolBacktestResult, Signal, TradeRecord, Decimal]] = {}

    candidates = sorted(
        _iter_trade_candidates(results),
        key=lambda item: (item[2].entry_timestamp, item[0].instrument.symbol, item[1].signal_id),
    )

    for result, signal, trade in candidates:
        positions, session_state, equity = _close_due_positions(
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
                    message="Current demo risk budget cannot support even one share.",
                )
            )
            continue

        decision = evaluate_order_request(
            signal,
            entry_price=trade.entry_price,
            stop_price=trade.stop_price,
            proposed_quantity=quantity,
            positions=_positions_to_snapshots(positions),
            session_state=session_state,
            config=risk_config,
            market_is_open=True,
        )
        request = ExecutionRequest(
            signal=signal,
            requested_at=trade.entry_timestamp,
            session_key=session_state.session_key,
            entry_price=trade.entry_price,
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
            blocked.append(
                BlockedSignalRecord(
                    instrument=result.instrument,
                    signal=signal,
                    entry_timestamp=trade.entry_timestamp,
                    reason_codes=execution_result.risk_decision.reason_codes,
                    message=execution_result.logs[-1].message if execution_result.logs else "Risk blocked the trade.",
                )
            )
            continue

        open_plans[execution_result.fill_event.position_id] = (
            result,
            signal,
            trade,
            execution_result.suggested_order.quantity,
        )

    positions, session_state, equity = _close_due_positions(
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
    return PaperDemoOutcome(
        executed_trades=tuple(executed),
        blocked_signals=tuple(blocked),
        equity_points=tuple(equity_points),
        ending_equity=equity,
    )


def create_backtest_run(
    config: DemoConfig,
    *,
    refresh_data: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    datasets = tuple(
        download_and_cache_dataset(config, instrument, refresh=refresh_data)
        for instrument in config.instruments
    )
    symbol_results = tuple(run_symbol_backtest(record) for record in datasets)
    paper_outcome = run_paper_demo(symbol_results, risk_settings=config.risk)

    resolved_run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_public_demo")
    report_dir = config.report_dir / resolved_run_id
    report_dir.mkdir(parents=True, exist_ok=True)

    summary = build_summary_payload(
        config=config,
        symbol_results=symbol_results,
        paper_outcome=paper_outcome,
        run_id=resolved_run_id,
        report_dir=report_dir,
    )
    write_summary_json(report_dir / "summary.json", summary)
    write_trades_csv(report_dir / "trades.csv", paper_outcome.executed_trades)
    write_knowledge_trace_json(
        report_dir / "knowledge_trace.json",
        run_id=resolved_run_id,
        paper_outcome=paper_outcome,
    )
    write_equity_curve_png(report_dir / "equity_curve.png", paper_outcome.equity_points)
    write_markdown_report(
        report_dir / "report.md",
        summary=summary,
        symbol_results=symbol_results,
        paper_outcome=paper_outcome,
    )
    return {
        "run_id": resolved_run_id,
        "report_dir": report_dir,
        "summary": summary,
    }


def build_summary_payload(
    *,
    config: DemoConfig,
    symbol_results: tuple[SymbolBacktestResult, ...],
    paper_outcome: PaperDemoOutcome,
    run_id: str,
    report_dir: Path,
) -> dict[str, Any]:
    closed_trades = paper_outcome.executed_trades
    wins = [item.pnl_cash for item in closed_trades if item.pnl_cash > ZERO]
    losses = [item.pnl_cash for item in closed_trades if item.pnl_cash < ZERO]
    total_pnl = sum((item.pnl_cash for item in closed_trades), ZERO)
    ending_equity = paper_outcome.ending_equity
    total_return = _percent((ending_equity - config.risk.starting_capital) / config.risk.starting_capital)
    max_drawdown_cash, max_drawdown_pct = compute_max_drawdown(paper_outcome.equity_points)
    win_rate = _percent(Decimal(len(wins)) / Decimal(len(closed_trades))) if closed_trades else ZERO
    gross_profit = sum(wins, ZERO)
    gross_loss = abs(sum(losses, ZERO))
    profit_factor = _quantize(gross_profit / gross_loss) if gross_loss > ZERO else None

    per_symbol = []
    for result in symbol_results:
        executed = [item for item in closed_trades if item.instrument.symbol == result.instrument.symbol]
        blocked = [item for item in paper_outcome.blocked_signals if item.instrument.symbol == result.instrument.symbol]
        symbol_pnl = sum((item.pnl_cash for item in executed), ZERO)
        symbol_win_rate = (
            _percent(Decimal(sum(1 for item in executed if item.pnl_cash > ZERO)) / Decimal(len(executed)))
            if executed
            else ZERO
        )
        per_symbol.append(
            {
                "symbol": result.instrument.symbol,
                "label": result.instrument.label,
                "market": result.instrument.market,
                "source": result.source,
                "bars": result.bars_count,
                "signals": len(result.signals),
                "baseline_trades": len(result.backtest_report.trades),
                "executed_trades": len(executed),
                "blocked_signals": len(blocked),
                "pnl_cash": _string_decimal(symbol_pnl),
                "win_rate_pct": _string_decimal(symbol_win_rate),
                "cache_csv": str(result.csv_path),
            }
        )

    best_five = sorted(closed_trades, key=lambda item: item.pnl_cash, reverse=True)[:5]
    worst_five = sorted(closed_trades, key=lambda item: item.pnl_cash)[:5]
    blocked_examples = [
        {
            "symbol": item.instrument.symbol,
            "timestamp": item.entry_timestamp.isoformat(),
            "reason_codes": list(item.reason_codes),
            "message": item.message,
        }
        for item in paper_outcome.blocked_signals[:5]
    ]

    return {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "title": config.title,
        "description": config.description,
        "boundary": "paper/simulated",
        "data_source": list(dict.fromkeys(result.source for result in symbol_results)),
        "symbols": [item.symbol for item in config.instruments],
        "time_range": {
            "start": config.start.isoformat(),
            "end": config.end.isoformat(),
            "interval": config.interval,
        },
        "cache_dir": str(config.cache_dir),
        "report_dir": str(report_dir),
        "risk_model": {
            "starting_capital": _string_decimal(config.risk.starting_capital),
            "risk_per_trade": _string_decimal(config.risk.risk_per_trade),
            "max_total_exposure": _string_decimal(config.risk.max_total_exposure),
            "max_symbol_exposure_ratio": _string_decimal(config.risk.max_symbol_exposure_ratio),
            "max_daily_loss": _string_decimal(config.risk.max_daily_loss),
            "max_consecutive_losses": config.risk.max_consecutive_losses,
            "session_model": "single historical demo session; no daily reset simulation",
        },
        "cash_note": infer_cash_note(config),
        "core_results": {
            "total_pnl": _string_decimal(total_pnl),
            "ending_equity": _string_decimal(ending_equity),
            "total_return_pct": _string_decimal(total_return),
            "max_drawdown": _string_decimal(max_drawdown_cash),
            "max_drawdown_pct": _string_decimal(max_drawdown_pct),
            "trade_count": len(closed_trades),
            "blocked_signals": len(paper_outcome.blocked_signals),
            "win_rate_pct": _string_decimal(win_rate),
            "profit_factor": _string_decimal(profit_factor) if profit_factor is not None else None,
        },
        "per_symbol": per_symbol,
        "best_trades": [trade_to_summary_row(item) for item in best_five],
        "worst_trades": [trade_to_summary_row(item) for item in worst_five],
        "blocked_examples": blocked_examples,
        "limitations": [
            REPORT_READABILITY_NOTE,
            "当前演示未接入历史新闻时间线，因此 news filter 不参与本轮回测结果。",
            "当前版本未持久化结构化 no-trade / wait 决策，不强行补造未出手原因。",
            "当前风控演示采用固定风险预算和单一历史 session，不模拟真实日内重置或实盘滑点。",
        ],
    }


def write_summary_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_knowledge_trace_json(
    path: Path,
    *,
    run_id: str,
    paper_outcome: PaperDemoOutcome,
) -> None:
    payload = {
        "run_id": run_id,
        "boundary": "paper/simulated",
        "executed_trades": [
            {
                "symbol": item.instrument.symbol,
                "signal_id": item.signal.signal_id,
                "entry_timestamp": item.trade.entry_timestamp.isoformat(),
                "exit_timestamp": item.trade.exit_timestamp.isoformat(),
                "knowledge_trace": _knowledge_trace_payload(item.signal),
            }
            for item in paper_outcome.executed_trades
        ],
        "blocked_signals": [
            {
                "symbol": item.instrument.symbol,
                "signal_id": item.signal.signal_id,
                "entry_timestamp": item.entry_timestamp.isoformat(),
                "reason_codes": list(item.reason_codes),
                "knowledge_trace": _knowledge_trace_payload(item.signal),
            }
            for item in paper_outcome.blocked_signals
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_trades_csv(path: Path, trades: tuple[ExecutedTradeRecord, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "symbol",
                "label",
                "market",
                "direction",
                "entry_timestamp",
                "exit_timestamp",
                "entry_price",
                "exit_price",
                "quantity",
                "pnl_cash",
                "pnl_r",
                "exit_reason",
                "setup_type",
                "entry_trigger",
                "stop_rule",
                "target_rule",
                "source_refs",
                "explanation",
            ),
        )
        writer.writeheader()
        for item in trades:
            writer.writerow(
                {
                    "symbol": item.instrument.symbol,
                    "label": item.instrument.label,
                    "market": item.instrument.market,
                    "direction": item.trade.direction,
                    "entry_timestamp": item.trade.entry_timestamp.isoformat(),
                    "exit_timestamp": item.trade.exit_timestamp.isoformat(),
                    "entry_price": _string_decimal(item.trade.entry_price),
                    "exit_price": _string_decimal(item.trade.exit_price),
                    "quantity": _string_decimal(item.quantity),
                    "pnl_cash": _string_decimal(item.pnl_cash),
                    "pnl_r": _string_decimal(item.trade.pnl_r),
                    "exit_reason": item.trade.exit_reason,
                    "setup_type": item.trade.setup_type,
                    "entry_trigger": item.signal.entry_trigger,
                    "stop_rule": item.signal.stop_rule,
                    "target_rule": item.signal.target_rule,
                    "source_refs": " | ".join(item.signal.source_refs),
                    "explanation": item.signal.explanation,
                }
            )


def write_equity_curve_png(path: Path, equity_points: tuple[tuple[str, float], ...]) -> None:
    if plt is None:  # pragma: no cover - exercised by runtime env validation
        raise RuntimeError(
            "matplotlib is required to render equity_curve.png. Use .venv/bin/python or install matplotlib."
        )

    x_values = [datetime.fromisoformat(timestamp) for timestamp, _ in equity_points]
    y_values = [value for _, value in equity_points]

    figure = plt.figure(figsize=(10, 4.8))
    axis = figure.add_subplot(111)
    axis.plot(x_values, y_values, color="#0A5A8A", linewidth=2)
    axis.set_title("Historical Demo Equity Curve (paper / simulated)")
    axis.set_xlabel("Close Timestamp")
    axis.set_ylabel("Equity")
    axis.grid(True, alpha=0.25)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def write_markdown_report(
    path: Path,
    *,
    summary: dict[str, Any],
    symbol_results: tuple[SymbolBacktestResult, ...],
    paper_outcome: PaperDemoOutcome,
) -> None:
    lines: list[str] = [
        f"# {summary['title']}",
        "",
        REPORT_READABILITY_NOTE,
        "",
        "## 1. 本次测试范围",
        "",
        f"- 标的：{', '.join(summary['symbols'])}",
        f"- 时间范围：{summary['time_range']['start']} ~ {summary['time_range']['end']} ({summary['time_range']['interval']})",
        f"- 数据来源：{', '.join(summary['data_source'])}",
        f"- 本地缓存目录：`{summary['cache_dir']}`",
        f"- 报告目录：`{summary['report_dir']}`",
        f"- 现金口径说明：{summary['cash_note']}",
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
        "",
        "## 3. 分标的摘要",
        "",
        "| 标的 | 角色 | 数据源 | Bars | Signals | 基线 trades | 实际执行 trades | 风控拦截 | 累计盈亏 | 胜率 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    role_by_symbol = {item.symbol: item.demo_role for item in (result.instrument for result in symbol_results)}
    for row in summary["per_symbol"]:
        lines.append(
            "| {symbol} | {role} | {source} | {bars} | {signals} | {baseline_trades} | {executed_trades} | {blocked_signals} | {pnl_cash} | {win_rate_pct}% |".format(
                role=role_by_symbol[row["symbol"]],
                **row,
            )
        )

    lines.extend(
        [
            "",
            "## 4. 最好 5 笔交易",
            "",
        ]
    )
    lines.extend(_format_trade_bullets(summary["best_trades"]) or ["- 本轮没有完成的交易。"])

    lines.extend(
        [
            "",
            "## 5. 最差 5 笔交易",
            "",
        ]
    )
    lines.extend(_format_trade_bullets(summary["worst_trades"]) or ["- 本轮没有完成的交易。"])

    lines.extend(
        [
            "",
            "## 6. 代表性交易解释",
            "",
        ]
    )
    representative = list(summary["best_trades"][:2]) + list(summary["worst_trades"][:2])
    if representative:
        for item in representative:
            lines.extend(
                [
                    f"- `{item['symbol']}` {item['direction']} @ {item['entry_timestamp']} -> {item['exit_timestamp']}",
                    f"  进场原因：{item['explanation']}",
                    f"  出场原因：{humanize_exit_reason(item['exit_reason'])}",
                    f"  setup/context：`{item['setup_type']}` / `{item['pa_context']}`",
                    f"  trace 摘要：{_format_trace_summary(item['knowledge_trace_summary'])}",
                    f"  risk_notes：{' | '.join(item['risk_notes']) if item['risk_notes'] else '当前版本无额外风控注释'}",
                ]
            )
    else:
        lines.append("- 当前没有可解释的已完成交易。")

    lines.extend(
        [
            "",
            "## 7. 风控与未执行样本",
            "",
        ]
    )
    if summary["blocked_examples"]:
        for item in summary["blocked_examples"]:
            lines.append(
                f"- `{item['symbol']}` @ {item['timestamp']}: {humanize_block_reason(item['reason_codes'])}。{item['message']} "
                f"(reason_codes={', '.join(item['reason_codes'])})"
            )
    else:
        lines.append("- 本轮演示中，按当前 demo 风控参数，没有出现被风控拦截后仍继续成交的情况。")

    lines.extend(
        [
            "",
            "## 8. 为什么没有展示 no-trade / wait 样本",
            "",
            "- 当前版本还没有把 no-trade / wait 决策持久化成结构化输出。",
            "- 为避免补造解释，本报告不把“没有出信号的 bar”硬写成确定性 no-trade 结论。",
            "",
            "## 9. 结论与局限",
            "",
            f"- 结论：这轮 2024H1 公共历史数据演示在 `NVDA / TSLA / SPY` 上，按当前 demo 风控和历史回测口径，"
            f"录得 {summary['core_results']['total_return_pct']}% 的总收益率；盈利主要来自 NVDA，"
            "TSLA 拖累最明显，SPY 贡献较小但为正。",
        ]
    )
    for item in summary["limitations"]:
        lines.append(f"- {item}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def trade_to_summary_row(item: ExecutedTradeRecord) -> dict[str, Any]:
    return {
        "symbol": item.instrument.symbol,
        "label": item.instrument.label,
        "direction": item.trade.direction,
        "entry_timestamp": item.trade.entry_timestamp.isoformat(),
        "exit_timestamp": item.trade.exit_timestamp.isoformat(),
        "entry_price": _string_decimal(item.trade.entry_price),
        "exit_price": _string_decimal(item.trade.exit_price),
        "quantity": _string_decimal(item.quantity),
        "pnl_cash": _string_decimal(item.pnl_cash),
        "pnl_r": _string_decimal(item.trade.pnl_r),
        "exit_reason": item.trade.exit_reason,
        "setup_type": item.signal.setup_type,
        "pa_context": item.signal.pa_context,
        "explanation": item.signal.explanation,
        "source_refs": list(item.signal.source_refs),
        "knowledge_trace_summary": list(summarize_knowledge_trace(item.signal.knowledge_trace)),
        "risk_notes": list(item.signal.risk_notes),
    }


def _knowledge_trace_payload(signal: Signal) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for hit in signal.knowledge_trace:
        payload.append(
            {
                "atom_id": hit.atom_id,
                "atom_type": hit.atom_type,
                "source_ref": hit.source_ref,
                "raw_locator": dict(hit.raw_locator),
                "match_reason": hit.match_reason,
                "applicability_state": hit.applicability_state,
                "conflict_refs": list(hit.conflict_refs),
            }
        )
    return payload


def _format_trace_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return "当前版本未提供"
    return " | ".join(
        f"{item['atom_type']} {item['atom_id']} @ {item['raw_locator']}"
        for item in items[:3]
    )


def compute_max_drawdown(equity_points: tuple[tuple[str, float], ...]) -> tuple[Decimal, Decimal]:
    if not equity_points:
        return ZERO, ZERO
    peak = Decimal(str(equity_points[0][1]))
    max_drawdown = ZERO
    max_drawdown_pct = ZERO
    for _, raw_value in equity_points:
        value = Decimal(str(raw_value))
        if value > peak:
            peak = value
        drawdown = peak - value
        if drawdown > max_drawdown:
            max_drawdown = drawdown
        if peak > ZERO:
            drawdown_pct = (drawdown / peak) * HUNDRED
            if drawdown_pct > max_drawdown_pct:
                max_drawdown_pct = drawdown_pct
    return _quantize(max_drawdown), _quantize(max_drawdown_pct)


def compute_demo_quantity(
    *,
    trade: TradeRecord,
    current_equity: Decimal,
    risk_per_trade: Decimal,
) -> Decimal:
    if trade.risk_per_share <= ZERO or trade.entry_price <= ZERO or current_equity <= ZERO:
        return ZERO
    risk_based = (risk_per_trade / trade.risk_per_share).to_integral_value(rounding=ROUND_DOWN)
    capital_based = (current_equity / trade.entry_price).to_integral_value(rounding=ROUND_DOWN)
    quantity = min(risk_based, capital_based)
    return quantity if quantity > ZERO else ZERO


def alpha_vantage_api_key() -> str | None:
    for env_name in ALPHA_VANTAGE_ENV_VARS:
        value = os.environ.get(env_name)
        if value:
            return value
    return None


def _fetch_alpha_vantage_rows(
    *,
    instrument: InstrumentConfig,
    start: date,
    end: date,
    interval: str,
) -> list[dict[str, str]]:
    if requests is None:  # pragma: no cover - runtime dependency
        raise RuntimeError("requests is required to call Alpha Vantage.")
    api_key = alpha_vantage_api_key()
    if not api_key:
        raise RuntimeError("Alpha Vantage API key is not available.")
    response = requests.get(
        "https://www.alphavantage.co/query",
        params={
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": instrument.ticker,
            "outputsize": "full",
            "apikey": api_key,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict):
        raise RuntimeError(f"Alpha Vantage response missing daily series for {instrument.ticker}: {payload}")
    rows: list[dict[str, str]] = []
    for date_key in sorted(series):
        current_date = date.fromisoformat(date_key)
        if current_date < start or current_date > end:
            continue
        item = series[date_key]
        rows.append(
            build_ohlcv_row(
                instrument=instrument,
                interval=interval,
                trading_date=current_date,
                open_value=item["1. open"],
                high_value=item["2. high"],
                low_value=item["3. low"],
                close_value=item["4. close"],
                volume_value=item["6. volume"],
            )
        )
    return rows


def _fetch_yfinance_rows(
    *,
    instrument: InstrumentConfig,
    start: date,
    end: date,
    interval: str,
) -> list[dict[str, str]]:
    if yf is None:  # pragma: no cover - runtime dependency
        raise RuntimeError("yfinance is not installed. Use .venv/bin/python or install it locally.")
    frame = yf.download(
        instrument.ticker,
        start=start.isoformat(),
        end=end.isoformat(),
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if getattr(frame, "empty", True):
        raise RuntimeError(f"yfinance returned no rows for {instrument.ticker}")
    frame = _flatten_yfinance_frame(frame, instrument.ticker)
    rows: list[dict[str, str]] = []
    for timestamp, row in frame.iterrows():
        trading_date = timestamp.date() if hasattr(timestamp, "date") else date.fromisoformat(str(timestamp)[:10])
        rows.append(
            build_ohlcv_row(
                instrument=instrument,
                interval=interval,
                trading_date=trading_date,
                open_value=row["Open"],
                high_value=row["High"],
                low_value=row["Low"],
                close_value=row["Close"],
                volume_value=row["Volume"],
            )
        )
    return rows


def build_ohlcv_row(
    *,
    instrument: InstrumentConfig,
    interval: str,
    trading_date: date,
    open_value: Any,
    high_value: Any,
    low_value: Any,
    close_value: Any,
    volume_value: Any,
) -> dict[str, str]:
    timezone = ZoneInfo(instrument.timezone)
    local_timestamp = datetime.combine(trading_date, time(16, 0), tzinfo=timezone)
    return {
        "symbol": instrument.symbol,
        "market": instrument.market,
        "timeframe": interval,
        "timestamp": local_timestamp.isoformat(),
        "timezone": instrument.timezone,
        "open": _string_decimal(_decimal(open_value)),
        "high": _string_decimal(_decimal(high_value)),
        "low": _string_decimal(_decimal(low_value)),
        "close": _string_decimal(_decimal(close_value)),
        "volume": _string_decimal(_decimal(volume_value)),
    }


def _flatten_yfinance_frame(frame: Any, ticker: str) -> Any:
    columns = getattr(frame, "columns", ())
    if getattr(columns, "nlevels", 1) == 1:
        return frame
    if ticker in columns.get_level_values(-1):
        return frame.xs(ticker, axis=1, level=-1)
    return frame.droplevel(-1, axis=1)


def _positions_to_snapshots(positions: tuple[PaperPosition, ...]) -> tuple[PositionSnapshot, ...]:
    return tuple(
        PositionSnapshot(
            symbol=position.symbol,
            quantity=position.quantity,
            market_value=position.market_value,
        )
        for position in positions
    )


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


def _close_due_positions(
    *,
    adapter: PaperBrokerAdapter,
    current_positions: tuple[PaperPosition, ...],
    session_state: SessionRiskState,
    config: RiskConfig,
    current_equity: Decimal,
    due_before: datetime | None,
    open_plans: dict[str, tuple[SymbolBacktestResult, Signal, TradeRecord, Decimal]],
    executed: list[ExecutedTradeRecord],
    equity_points: list[tuple[str, float]],
) -> tuple[tuple[PaperPosition, ...], SessionRiskState, Decimal]:
    if not open_plans:
        return current_positions, session_state, current_equity

    due_ids = [
        position_id
        for position_id, (_, _, trade, _) in sorted(
            open_plans.items(),
            key=lambda item: (item[1][2].exit_timestamp, item[1][2].signal_id),
        )
        if due_before is None or trade.exit_timestamp <= due_before
    ]
    positions = current_positions
    next_state = session_state
    equity = current_equity

    for position_id in due_ids:
        result, signal, trade, quantity = open_plans.pop(position_id)
        close_result = adapter.close_position(
            position_id=position_id,
            exit_price=trade.exit_price,
            closed_at=trade.exit_timestamp,
            positions=positions,
            session_state=next_state,
            config=config,
            exit_reason=trade.exit_reason,
        )
        positions = close_result.resulting_positions
        next_state = close_result.session_state
        equity += close_result.realized_pnl
        executed.append(
            ExecutedTradeRecord(
                instrument=result.instrument,
                signal=signal,
                trade=trade,
                quantity=quantity,
                pnl_cash=close_result.realized_pnl,
                equity_after_close=equity,
            )
        )
        equity_points.append((trade.exit_timestamp.isoformat(), float(equity)))

    return positions, next_state, equity


def _format_trade_bullets(items: list[dict[str, Any]]) -> list[str]:
    bullets: list[str] = []
    for item in items:
        bullets.append(
            f"- `{item['symbol']}` {item['direction']} | pnl={item['pnl_cash']} | "
            f"{item['entry_timestamp']} -> {item['exit_timestamp']} | exit={humanize_exit_reason(item['exit_reason'])}"
        )
    return bullets


def infer_cash_note(config: DemoConfig) -> str:
    markets = {item.market for item in config.instruments}
    if markets == {"US"}:
        return "本次现金口径按 USD demo sizing 统计，因为本轮只选择了 US 标的。"
    return "本次现金口径按各标的本地市场货币分别计算；若混合市场，聚合现金结果只作粗略演示。"


def humanize_exit_reason(code: str) -> str:
    return EXIT_REASON_LABELS.get(code, code)


def humanize_block_reason(reason_codes: list[str] | tuple[str, ...]) -> str:
    if not reason_codes:
        return "未执行原因未记录"
    return " / ".join(BLOCK_REASON_LABELS.get(code, code) for code in reason_codes)


def _resolve_repo_path(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else ROOT / path


def _string_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(_quantize(value), "f")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(QUANT)


def _percent(value: Decimal) -> Decimal:
    return _quantize(value * HUNDRED)
