#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M10_4_DIR = M10_DIR / "historical_pilot" / "m10_4_wave_a_pilot"
M10_8_DIR = M10_DIR / "capital_backtest" / "m10_8_wave_a"
CAPITAL_MODEL_PATH = M10_DIR / "m10_7_capital_model.json"
SUMMARY_PATH = M10_4_DIR / "m10_4_wave_a_pilot_summary.json"
WAVE_A_IDS = ("M10-PA-001", "M10-PA-002", "M10-PA-005", "M10-PA-012")
FORBIDDEN_OUTPUT_STRINGS = ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true")
QUANT_2 = Decimal("0.01")
QUANT_4 = Decimal("0.0001")
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class CapitalModel:
    initial_capital: Decimal
    risk_fraction: Decimal
    max_notional_fraction: Decimal
    cost_tiers: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class CandidateTrade:
    strategy_id: str
    symbol: str
    timeframe: str
    direction: str
    signal_timestamp: str
    entry_timestamp: str
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    risk_per_share: Decimal
    exit_timestamp: str
    exit_price: Decimal
    exit_reason: str
    gross_r: Decimal
    baseline_net_r: Decimal
    setup_notes: str


@dataclass(frozen=True, slots=True)
class CapitalTrade:
    strategy_id: str
    symbol: str
    timeframe: str
    cost_tier: str
    sequence: int
    event_id: str
    trade_id: str
    direction: str
    signal_timestamp: str
    entry_timestamp: str
    exit_timestamp: str
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    exit_price: Decimal
    risk_per_share: Decimal
    risk_budget: Decimal
    risk_budget_quantity: Decimal
    notional_cap_quantity: Decimal
    quantity: Decimal
    equity_before: Decimal
    gross_pnl: Decimal
    cost_pnl: Decimal
    pnl: Decimal
    equity_after: Decimal
    win: bool
    exit_reason: str
    holding_bars_approx: Decimal
    quality_flag: str
    spec_ref: str
    source_ledger_ref: str
    skip_reason: str


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_capital_model(path: Path = CAPITAL_MODEL_PATH) -> CapitalModel:
    payload = load_json(path)
    return CapitalModel(
        initial_capital=Decimal(payload["initial_capital"]),
        risk_fraction=Decimal(payload["risk_per_trade_percent_of_equity"]) / Decimal("100"),
        max_notional_fraction=Decimal(payload["max_notional_percent_of_equity"]) / Decimal("100"),
        cost_tiers=tuple(payload["cost_sensitivity_bps"]),
    )


def load_wave_a_summary(path: Path = SUMMARY_PATH) -> dict[str, Any]:
    return load_json(path)


def load_candidate_trades(path: Path) -> list[CandidateTrade]:
    trades: list[CandidateTrade] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            trades.append(
                CandidateTrade(
                    strategy_id=row["strategy_id"],
                    symbol=row["symbol"],
                    timeframe=row["timeframe"],
                    direction=row["direction"],
                    signal_timestamp=row["signal_timestamp"],
                    entry_timestamp=row["entry_timestamp"],
                    entry_price=Decimal(row["entry_price"]),
                    stop_price=Decimal(row["stop_price"]),
                    target_price=Decimal(row["target_price"]),
                    risk_per_share=Decimal(row["risk_per_share"]),
                    exit_timestamp=row["exit_timestamp"],
                    exit_price=Decimal(row["exit_price"]),
                    exit_reason=row["exit_reason"],
                    gross_r=Decimal(row["gross_r"]),
                    baseline_net_r=Decimal(row["baseline_net_r"]),
                    setup_notes=row["setup_notes"],
                )
            )
    return trades


def run_m10_wave_a_capital_backtest(output_dir: Path = M10_8_DIR) -> dict[str, Any]:
    model = load_capital_model()
    summary = load_wave_a_summary()
    output_dir.mkdir(parents=True, exist_ok=True)
    curve_dir = output_dir / "m10_8_wave_a_equity_curves"
    curve_dir.mkdir(parents=True, exist_ok=True)

    all_trades: list[CapitalTrade] = []
    curve_points: dict[tuple[str, str, str, str], list[tuple[int, str, Decimal]]] = {}
    for result in summary["strategy_timeframe_results"]:
        strategy_id = result["strategy_id"]
        timeframe = result["timeframe"]
        if strategy_id not in WAVE_A_IDS:
            raise ValueError(f"Unexpected non-Wave-A strategy in M10.8 input: {strategy_id}")
        candidate_path = ROOT / result["artifacts"]["candidate_events"]
        spec_ref = f"reports/strategy_lab/m10_price_action_strategy_refresh/backtest_specs/{strategy_id}.json"
        source_ledger_ref = (
            f"reports/strategy_lab/m10_price_action_strategy_refresh/historical_pilot/"
            f"m10_4_wave_a_pilot/{strategy_id}/{timeframe}/source_ledger.json"
        )
        candidates = load_candidate_trades(candidate_path)
        grouped: dict[str, list[CandidateTrade]] = defaultdict(list)
        for candidate in candidates:
            grouped[candidate.symbol].append(candidate)
        for symbol, symbol_trades in sorted(grouped.items()):
            for tier in model.cost_tiers:
                key = (strategy_id, timeframe, symbol, tier["tier"])
                simulated = simulate_account(
                    candidates=symbol_trades,
                    model=model,
                    tier=tier,
                    spec_ref=spec_ref,
                    source_ledger_ref=source_ledger_ref,
                    quality_flag=quality_flag_for(strategy_id, timeframe),
                )
                all_trades.extend(simulated)
                curve_points[key] = [(0, "start", model.initial_capital)] + [
                    (trade.sequence, trade.exit_timestamp, trade.equity_after) for trade in simulated
                ]

    metrics = build_metric_rows(all_trades, model)
    baseline_trades = [trade for trade in all_trades if trade.cost_tier == "baseline"]
    write_trade_ledger(output_dir / "m10_8_wave_a_trade_ledger.csv", baseline_trades)
    write_metrics(output_dir / "m10_8_wave_a_metrics.csv", metrics)
    write_equity_curves(curve_dir, curve_points)
    write_scorecard(output_dir / "m10_8_wave_a_strategy_scorecard.md", metrics)
    write_client_report(output_dir / "m10_8_wave_a_client_report.md", metrics)
    summary_payload = build_summary(metrics, all_trades, baseline_trades, output_dir)
    write_json(output_dir / "m10_8_wave_a_capital_summary.json", summary_payload)
    validate_outputs(output_dir)
    return summary_payload


def simulate_account(
    *,
    candidates: Iterable[CandidateTrade],
    model: CapitalModel,
    tier: dict[str, Any],
    spec_ref: str,
    source_ledger_ref: str,
    quality_flag: str,
) -> list[CapitalTrade]:
    equity = model.initial_capital
    trades: list[CapitalTrade] = []
    slippage_fraction = Decimal(str(tier["slippage_bps"])) / Decimal("10000")
    fee_per_order = Decimal(str(tier.get("fee_per_order", "0.00")))
    for sequence, candidate in enumerate(sorted(candidates, key=lambda item: item.entry_timestamp), start=1):
        skip_reason = skip_reason_for(candidate, equity)
        if skip_reason:
            trades.append(
                skipped_trade(
                    candidate=candidate,
                    tier=tier["tier"],
                    sequence=sequence,
                    equity=equity,
                    quality_flag=quality_flag,
                    spec_ref=spec_ref,
                    source_ledger_ref=source_ledger_ref,
                    skip_reason=skip_reason,
                )
            )
            continue

        risk_budget = equity * model.risk_fraction
        risk_quantity = risk_budget / candidate.risk_per_share
        notional_quantity = (equity * model.max_notional_fraction) / candidate.entry_price
        quantity = min(risk_quantity, notional_quantity)
        if quantity <= ZERO:
            trades.append(
                skipped_trade(
                    candidate=candidate,
                    tier=tier["tier"],
                    sequence=sequence,
                    equity=equity,
                    quality_flag=quality_flag,
                    spec_ref=spec_ref,
                    source_ledger_ref=source_ledger_ref,
                    skip_reason="non_positive_quantity_after_notional_cap",
                )
            )
            continue

        gross_per_share = pnl_per_share(candidate)
        slippage_cost_per_share = (candidate.entry_price + candidate.exit_price) * slippage_fraction
        gross_pnl = gross_per_share * quantity
        cost_pnl = (slippage_cost_per_share * quantity) + (fee_per_order * Decimal("2"))
        pnl = gross_pnl - cost_pnl
        equity_after = equity + pnl
        event_id = build_event_id(candidate)
        trade = CapitalTrade(
            strategy_id=candidate.strategy_id,
            symbol=candidate.symbol,
            timeframe=candidate.timeframe,
            cost_tier=tier["tier"],
            sequence=sequence,
            event_id=event_id,
            trade_id=f"{event_id}:{tier['tier']}",
            direction=candidate.direction,
            signal_timestamp=candidate.signal_timestamp,
            entry_timestamp=candidate.entry_timestamp,
            exit_timestamp=candidate.exit_timestamp,
            entry_price=q4(candidate.entry_price),
            stop_price=q4(candidate.stop_price),
            target_price=q4(candidate.target_price),
            exit_price=q4(candidate.exit_price),
            risk_per_share=q4(candidate.risk_per_share),
            risk_budget=q2(risk_budget),
            risk_budget_quantity=q4(risk_quantity),
            notional_cap_quantity=q4(notional_quantity),
            quantity=q4(quantity),
            equity_before=q2(equity),
            gross_pnl=q2(gross_pnl),
            cost_pnl=q2(cost_pnl),
            pnl=q2(pnl),
            equity_after=q2(equity_after),
            win=pnl > ZERO,
            exit_reason=candidate.exit_reason,
            holding_bars_approx=holding_bars_approx(candidate.entry_timestamp, candidate.exit_timestamp, candidate.timeframe),
            quality_flag=quality_flag,
            spec_ref=spec_ref,
            source_ledger_ref=source_ledger_ref,
            skip_reason="",
        )
        trades.append(trade)
        equity = equity_after
    return trades


def skip_reason_for(candidate: CandidateTrade, equity: Decimal) -> str:
    if equity <= ZERO:
        return "non_positive_equity"
    if candidate.entry_price <= ZERO:
        return "non_positive_entry_price"
    if candidate.risk_per_share <= ZERO:
        return "non_positive_stop_distance"
    if candidate.exit_price <= ZERO:
        return "non_positive_exit_price"
    return ""


def skipped_trade(
    *,
    candidate: CandidateTrade,
    tier: str,
    sequence: int,
    equity: Decimal,
    quality_flag: str,
    spec_ref: str,
    source_ledger_ref: str,
    skip_reason: str,
) -> CapitalTrade:
    return CapitalTrade(
        strategy_id=candidate.strategy_id,
        symbol=candidate.symbol,
        timeframe=candidate.timeframe,
        cost_tier=tier,
        sequence=sequence,
        event_id=build_event_id(candidate),
        trade_id=f"{build_event_id(candidate)}:{tier}",
        direction=candidate.direction,
        signal_timestamp=candidate.signal_timestamp,
        entry_timestamp=candidate.entry_timestamp,
        exit_timestamp=candidate.exit_timestamp,
        entry_price=q4(candidate.entry_price),
        stop_price=q4(candidate.stop_price),
        target_price=q4(candidate.target_price),
        exit_price=q4(candidate.exit_price),
        risk_per_share=q4(candidate.risk_per_share),
        risk_budget=ZERO,
        risk_budget_quantity=ZERO,
        notional_cap_quantity=ZERO,
        quantity=ZERO,
        equity_before=q2(equity),
        gross_pnl=ZERO,
        cost_pnl=ZERO,
        pnl=ZERO,
        equity_after=q2(equity),
        win=False,
        exit_reason=candidate.exit_reason,
        holding_bars_approx=ZERO,
        quality_flag=quality_flag,
        spec_ref=spec_ref,
        source_ledger_ref=source_ledger_ref,
        skip_reason=skip_reason,
    )


def pnl_per_share(candidate: CandidateTrade) -> Decimal:
    if candidate.direction == "long":
        return candidate.exit_price - candidate.entry_price
    if candidate.direction == "short":
        return candidate.entry_price - candidate.exit_price
    raise ValueError(f"Unsupported direction: {candidate.direction}")


def build_event_id(candidate: CandidateTrade) -> str:
    payload = "|".join(
        [
            candidate.strategy_id,
            candidate.symbol,
            candidate.timeframe,
            candidate.direction,
            candidate.signal_timestamp,
            candidate.entry_timestamp,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def holding_bars_approx(entry_timestamp: str, exit_timestamp: str, timeframe: str) -> Decimal:
    entry = datetime.fromisoformat(entry_timestamp)
    exit_ = datetime.fromisoformat(exit_timestamp)
    minutes = max((exit_ - entry).total_seconds() / 60, 0)
    timeframe_minutes = {"5m": 5, "15m": 15, "1h": 60, "1d": 390}[timeframe]
    return q4(Decimal(str(minutes)) / Decimal(str(timeframe_minutes)))


def quality_flag_for(strategy_id: str, timeframe: str) -> str:
    if strategy_id == "M10-PA-005" and timeframe in {"1h", "15m", "5m"}:
        return "definition_breadth_review"
    return "normal_density_review"


def build_metric_rows(trades: list[CapitalTrade], model: CapitalModel) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    executable = [trade for trade in trades if not trade.skip_reason]
    group_specs: list[tuple[str, tuple[str, ...]]] = [
        ("strategy_timeframe_symbol", ("strategy_id", "timeframe", "symbol", "cost_tier")),
        ("strategy_timeframe", ("strategy_id", "timeframe", "cost_tier")),
        ("strategy", ("strategy_id", "cost_tier")),
    ]
    for grain, fields in group_specs:
        grouped: dict[tuple[str, ...], list[CapitalTrade]] = defaultdict(list)
        for trade in executable:
            grouped[tuple(getattr(trade, field) for field in fields)].append(trade)
        for key, group in sorted(grouped.items()):
            field_values = dict(zip(fields, key, strict=True))
            rows.append(metric_row(grain, field_values, group, model))
    return rows


def metric_row(
    grain: str,
    field_values: dict[str, str],
    trades: list[CapitalTrade],
    model: CapitalModel,
) -> dict[str, str]:
    initial_accounts = len({(trade.strategy_id, trade.timeframe, trade.symbol) for trade in trades})
    initial_capital = model.initial_capital * Decimal(initial_accounts)
    final_equity = sum_final_equity(trades, model.initial_capital)
    net_profit = final_equity - initial_capital
    wins = [trade for trade in trades if trade.pnl > ZERO]
    losses = [trade for trade in trades if trade.pnl < ZERO]
    gross_profit = sum((trade.pnl for trade in wins), ZERO)
    gross_loss = abs(sum((trade.pnl for trade in losses), ZERO))
    profit_factor = "" if gross_loss == ZERO else fmt4(gross_profit / gross_loss)
    max_dd = max_drawdown_across_accounts(trades, model.initial_capital)
    row = {
        "grain": grain,
        "strategy_id": field_values.get("strategy_id", ""),
        "timeframe": field_values.get("timeframe", ""),
        "symbol": field_values.get("symbol", ""),
        "cost_tier": field_values.get("cost_tier", ""),
        "account_count": str(initial_accounts),
        "initial_capital": fmt2(initial_capital),
        "final_equity": fmt2(final_equity),
        "net_profit": fmt2(net_profit),
        "return_percent": fmt4((net_profit / initial_capital) * Decimal("100")) if initial_capital else "0.0000",
        "trade_count": str(len(trades)),
        "win_rate": fmt4(Decimal(len(wins)) / Decimal(len(trades))) if trades else "0.0000",
        "profit_factor": profit_factor,
        "max_drawdown": fmt2(max_dd),
        "max_drawdown_percent": fmt4((max_dd / initial_capital) * Decimal("100")) if initial_capital else "0.0000",
        "max_consecutive_losses": str(max_consecutive_losses(trades)),
        "average_win": fmt2(gross_profit / Decimal(len(wins))) if wins else "0.00",
        "average_loss": fmt2(sum((trade.pnl for trade in losses), ZERO) / Decimal(len(losses))) if losses else "0.00",
        "average_holding_bars": fmt4(
            sum((trade.holding_bars_approx for trade in trades), ZERO) / Decimal(len(trades))
        ) if trades else "0.0000",
        "best_symbol": best_dimension(trades, "symbol"),
        "worst_symbol": worst_dimension(trades, "symbol"),
        "best_timeframe": best_dimension(trades, "timeframe"),
        "worst_timeframe": worst_dimension(trades, "timeframe"),
        "quality_flag": quality_flag_for_group(trades),
        "status": status_for_group(trades),
    }
    return row


def sum_final_equity(trades: list[CapitalTrade], initial_capital: Decimal) -> Decimal:
    latest: dict[tuple[str, str, str], Decimal] = {}
    for trade in trades:
        latest[(trade.strategy_id, trade.timeframe, trade.symbol)] = trade.equity_after
    return sum(latest.values(), ZERO) if latest else initial_capital


def max_drawdown_across_accounts(trades: list[CapitalTrade], initial_capital: Decimal) -> Decimal:
    grouped: dict[tuple[str, str, str], list[CapitalTrade]] = defaultdict(list)
    for trade in trades:
        grouped[(trade.strategy_id, trade.timeframe, trade.symbol)].append(trade)
    return sum((max_drawdown(group, initial_capital) for group in grouped.values()), ZERO)


def max_drawdown(trades: list[CapitalTrade], initial_capital: Decimal) -> Decimal:
    peak = initial_capital
    max_dd = ZERO
    for trade in sorted(trades, key=lambda item: (item.entry_timestamp, item.sequence)):
        equity = trade.equity_after
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_dd:
            max_dd = drawdown
    return q2(max_dd)


def max_consecutive_losses(trades: list[CapitalTrade]) -> int:
    max_count = 0
    current = 0
    for trade in sorted(trades, key=lambda item: (item.entry_timestamp, item.sequence)):
        if trade.pnl < ZERO:
            current += 1
            max_count = max(max_count, current)
        elif trade.pnl > ZERO:
            current = 0
    return max_count


def best_dimension(trades: list[CapitalTrade], field: str) -> str:
    scores = dimension_scores(trades, field)
    if not scores:
        return ""
    return max(scores.items(), key=lambda item: (item[1], item[0]))[0]


def worst_dimension(trades: list[CapitalTrade], field: str) -> str:
    scores = dimension_scores(trades, field)
    if not scores:
        return ""
    return min(scores.items(), key=lambda item: (item[1], item[0]))[0]


def dimension_scores(trades: list[CapitalTrade], field: str) -> dict[str, Decimal]:
    scores: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for trade in trades:
        scores[getattr(trade, field)] += trade.pnl
    return dict(scores)


def quality_flag_for_group(trades: list[CapitalTrade]) -> str:
    if any(trade.quality_flag == "definition_breadth_review" for trade in trades):
        return "definition_breadth_review"
    return "normal_density_review"


def status_for_group(trades: list[CapitalTrade]) -> str:
    if quality_flag_for_group(trades) == "definition_breadth_review":
        return "needs_definition_fix"
    return "completed_capital_test"


def write_trade_ledger(path: Path, trades: list[CapitalTrade]) -> None:
    fields = [
        "strategy_id",
        "symbol",
        "timeframe",
        "cost_tier",
        "sequence",
        "event_id",
        "trade_id",
        "direction",
        "signal_timestamp",
        "entry_timestamp",
        "exit_timestamp",
        "entry_price",
        "stop_price",
        "target_price",
        "exit_price",
        "risk_per_share",
        "risk_budget",
        "risk_budget_quantity",
        "notional_cap_quantity",
        "quantity",
        "equity_before",
        "gross_pnl",
        "cost_pnl",
        "pnl",
        "equity_after",
        "win",
        "exit_reason",
        "holding_bars_approx",
        "quality_flag",
        "spec_ref",
        "source_ledger_ref",
        "skip_reason",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            writer.writerow({field: serialize(getattr(trade, field)) for field in fields})


def write_metrics(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "grain",
        "strategy_id",
        "timeframe",
        "symbol",
        "cost_tier",
        "account_count",
        "initial_capital",
        "final_equity",
        "net_profit",
        "return_percent",
        "trade_count",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "max_drawdown_percent",
        "max_consecutive_losses",
        "average_win",
        "average_loss",
        "average_holding_bars",
        "best_symbol",
        "worst_symbol",
        "best_timeframe",
        "worst_timeframe",
        "quality_flag",
        "status",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_equity_curves(
    curve_dir: Path,
    curve_points: dict[tuple[str, str, str, str], list[tuple[int, str, Decimal]]],
) -> None:
    baseline_curves = {key: points for key, points in curve_points.items() if key[3] == "baseline"}
    grouped: dict[tuple[str, str], list[tuple[int, str, Decimal]]] = defaultdict(list)
    for (strategy_id, timeframe, symbol, _tier), points in baseline_curves.items():
        csv_path = curve_dir / f"{strategy_id}_{timeframe}_{symbol}_baseline_equity.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sequence", "timestamp", "equity"])
            writer.writerows((sequence, timestamp, fmt2(equity)) for sequence, timestamp, equity in points)
        grouped[(strategy_id, timeframe)].extend(points)
    for (strategy_id, timeframe), points in grouped.items():
        write_svg_curve(curve_dir / f"{strategy_id}_{timeframe}_baseline_equity.svg", points, strategy_id, timeframe)


def write_svg_curve(path: Path, points: list[tuple[int, str, Decimal]], strategy_id: str, timeframe: str) -> None:
    if not points:
        path.write_text("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"640\" height=\"260\"></svg>\n", encoding="utf-8")
        return
    values = [float(point[2]) for point in points]
    lo, hi = min(values), max(values)
    span = hi - lo if hi != lo else 1.0
    width, height, pad = 640, 260, 30
    step = (width - pad * 2) / max(len(values) - 1, 1)
    coords = []
    for index, value in enumerate(values):
        x = pad + index * step
        y = height - pad - ((value - lo) / span) * (height - pad * 2)
        coords.append(f"{x:.2f},{y:.2f}")
    polyline = " ".join(coords)
    text = (
        f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" "
        "viewBox=\"0 0 640 260\">"
        "<rect width=\"640\" height=\"260\" fill=\"white\"/>"
        f"<text x=\"30\" y=\"22\" font-size=\"14\" fill=\"#111\">{strategy_id} {timeframe} baseline equity</text>"
        "<line x1=\"30\" y1=\"230\" x2=\"610\" y2=\"230\" stroke=\"#ccc\"/>"
        "<line x1=\"30\" y1=\"30\" x2=\"30\" y2=\"230\" stroke=\"#ccc\"/>"
        f"<polyline points=\"{polyline}\" fill=\"none\" stroke=\"#2563eb\" stroke-width=\"1.5\"/>"
        f"<text x=\"30\" y=\"252\" font-size=\"11\" fill=\"#555\">min {lo:.2f} / max {hi:.2f}</text>"
        "</svg>\n"
    )
    path.write_text(text, encoding="utf-8")


def write_scorecard(path: Path, rows: list[dict[str, str]]) -> None:
    strategy_rows = [
        row for row in rows if row["grain"] == "strategy" and row["cost_tier"] == "baseline"
    ]
    lines = [
        "# M10.8 Wave A Strategy Scorecard",
        "",
        "## Summary",
        "",
        "- This report converts M10.4 Wave A candidate events into simulated capital metrics.",
        "- Default model: `100,000 USD` per independent strategy/timeframe/symbol account, `0.5%` risk per trade.",
        "- This is a historical simulation report, not paper trading approval, broker integration, or real order readiness.",
        "",
        "## Baseline Strategy Results",
        "",
        "| Strategy | Accounts | Final Equity | Net Profit | Return % | Trades | Win Rate | Profit Factor | Max Drawdown | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in sorted(strategy_rows, key=lambda item: item["strategy_id"]):
        lines.append(
            "| {strategy_id} | {account_count} | {final_equity} | {net_profit} | {return_percent} | "
            "{trade_count} | {win_rate} | {profit_factor} | {max_drawdown} | {status} |".format(**row)
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `M10-PA-005` on `1h / 15m / 5m` keeps `definition_breadth_review`; capital results must not override that status.",
            "- Full detail is in `m10_8_wave_a_metrics.csv` and `m10_8_wave_a_trade_ledger.csv`.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_client_report(path: Path, rows: list[dict[str, str]]) -> None:
    baseline = [row for row in rows if row["cost_tier"] == "baseline"]
    strategy_rows = [row for row in baseline if row["grain"] == "strategy"]
    tf_rows = [row for row in baseline if row["grain"] == "strategy_timeframe"]
    best = max(strategy_rows, key=lambda row: Decimal(row["net_profit"])) if strategy_rows else None
    worst = min(strategy_rows, key=lambda row: Decimal(row["net_profit"])) if strategy_rows else None
    lines = [
        "# M10.8 Wave A Client Report",
        "",
        "## Executive Summary",
        "",
        "- Coverage: `M10-PA-001`, `M10-PA-002`, `M10-PA-005`, `M10-PA-012`.",
        "- Symbols: `SPY / QQQ / NVDA / TSLA`.",
        "- Account model: `100,000 USD` per independent strategy/timeframe/symbol account, `0.5%` risk per trade.",
        "- This report shows historical simulation results only.",
    ]
    if best and worst:
        lines.extend(
            [
                f"- Best baseline strategy by net profit: `{best['strategy_id']}` ({best['net_profit']} USD).",
                f"- Weakest baseline strategy by net profit: `{worst['strategy_id']}` ({worst['net_profit']} USD).",
            ]
        )
    lines.extend(
        [
            "",
            "## Strategy-Timeframe Baseline Results",
            "",
            "| Strategy | Timeframe | Accounts | Final Equity | Net Profit | Return % | Trades | Win Rate | Max Drawdown | Status |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in sorted(tf_rows, key=lambda item: (item["strategy_id"], item["timeframe"])):
        lines.append(
            "| {strategy_id} | {timeframe} | {account_count} | {final_equity} | {net_profit} | "
            "{return_percent} | {trade_count} | {win_rate} | {max_drawdown} | {status} |".format(**row)
        )
    lines.extend(
        [
            "",
            "## Delivery Files",
            "",
            "- `m10_8_wave_a_metrics.csv`: metrics by strategy, timeframe, symbol, and cost tier.",
            "- `m10_8_wave_a_trade_ledger.csv`: trade-level simulated capital ledger.",
            "- `m10_8_wave_a_equity_curves/`: baseline equity curve CSV/SVG attachments.",
            "",
            "## Boundary",
            "",
            "No broker, real account, automatic execution, or real order path is enabled by this report.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_summary(
    rows: list[dict[str, str]],
    all_cost_trades: list[CapitalTrade],
    baseline_trades: list[CapitalTrade],
    output_dir: Path,
) -> dict[str, Any]:
    strategy_rows = [row for row in rows if row["grain"] == "strategy" and row["cost_tier"] == "baseline"]
    return {
        "schema_version": "m10.8.wave-a-capital-summary.v1",
        "generated_at": "2026-04-27T00:00:00Z",
        "stage": "M10.8.wave_a_capital_backtest",
        "wave_a_strategy_ids": list(WAVE_A_IDS),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_account": False,
        "real_orders": False,
        "paper_trading_approval": False,
        "capital_model_ref": "reports/strategy_lab/m10_price_action_strategy_refresh/m10_7_capital_model.json",
        "output_dir": output_dir.relative_to(ROOT).as_posix(),
        "simulated_trade_rows_all_cost_tiers": len(all_cost_trades),
        "trade_ledger_rows": len(baseline_trades),
        "metric_rows": len(rows),
        "baseline_strategy_results": strategy_rows,
        "quality_flags": sorted({trade.quality_flag for trade in all_cost_trades}),
        "boundary_note": "Historical capital simulation only; results do not approve paper trading or real execution.",
    }


def validate_outputs(output_dir: Path) -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in [
            output_dir / "m10_8_wave_a_capital_summary.json",
            output_dir / "m10_8_wave_a_strategy_scorecard.md",
            output_dir / "m10_8_wave_a_client_report.md",
        ]
        if path.exists()
    )
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_STRINGS:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden output string found: {forbidden}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def serialize(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def fmt2(value: Decimal) -> str:
    return format(q2(value), "f")


def fmt4(value: Decimal) -> str:
    return format(q4(value), "f")


def q2(value: Decimal) -> Decimal:
    return value.quantize(QUANT_2, rounding=ROUND_HALF_UP)


def q4(value: Decimal) -> Decimal:
    if value.is_nan() or value == Decimal("Infinity") or value == Decimal("-Infinity"):
        return ZERO
    return value.quantize(QUANT_4, rounding=ROUND_HALF_UP)
