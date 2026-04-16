from __future__ import annotations

from collections.abc import Iterable, Sequence
from hashlib import sha256
from decimal import Decimal, ROUND_HALF_UP

from src.data.replay import DeterministicReplay
from src.data.schema import OhlcvRow
from src.strategy.contracts import Signal

from .contracts import BacktestReport, BacktestStats, TradeRecord
from .reporting import build_slippage_sensitivity, build_summary, default_assumptions


DEFAULT_TARGET_R_MULTIPLE = Decimal("2")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
QUANT = Decimal("0.0001")


def run_backtest(
    bars: DeterministicReplay | Sequence[OhlcvRow] | Iterable[OhlcvRow],
    signals: Sequence[Signal] | Iterable[Signal],
) -> BacktestReport:
    ordered_bars = _normalize_bars(bars)
    ordered_signals = tuple(signals)
    warnings: list[str] = []

    if not ordered_bars:
        warnings.append("no bars supplied; backtest report is empty")
        return BacktestReport(
            trades=(),
            stats=_compute_stats((), bar_count=0, signal_count=len(ordered_signals)),
            summary="No bars were available, so the deterministic backtest did not run.",
            warnings=tuple(warnings),
            assumptions=default_assumptions(),
        )

    if not ordered_signals:
        warnings.append("no structured signals provided; no trades were simulated")

    signal_bar_index = _index_signal_bars(ordered_bars, ordered_signals)
    trades: list[TradeRecord] = []

    for signal in ordered_signals:
        signal_index = signal_bar_index.get(signal.signal_id)
        if signal_index is None:
            warnings.append(
                f"signal {signal.signal_id} could not be aligned to a bar; trade skipped"
            )
            continue

        if signal_index + 1 >= len(ordered_bars):
            warnings.append(
                f"signal {signal.signal_id} has no next bar for deterministic entry; data is insufficient"
            )
            continue

        trade = _simulate_trade(ordered_bars, signal, signal_index, warnings)
        if trade is not None:
            trades.append(trade)

    stats = _compute_stats(tuple(trades), bar_count=len(ordered_bars), signal_count=len(ordered_signals))
    summary = build_summary(stats, tuple(warnings))
    return BacktestReport(
        trades=tuple(trades),
        stats=stats,
        summary=summary,
        warnings=tuple(warnings),
        assumptions=default_assumptions(),
    )


def _simulate_trade(
    bars: Sequence[OhlcvRow],
    signal: Signal,
    signal_index: int,
    warnings: list[str],
) -> TradeRecord | None:
    signal_bar = bars[signal_index]
    entry_index = signal_index + 1
    entry_bar = bars[entry_index]
    entry_price = entry_bar.open

    if signal.direction == "long":
        stop_price = signal_bar.low
        risk = entry_price - stop_price
        target_price = entry_price + (risk * DEFAULT_TARGET_R_MULTIPLE)
    else:
        stop_price = signal_bar.high
        risk = stop_price - entry_price
        target_price = entry_price - (risk * DEFAULT_TARGET_R_MULTIPLE)

    if risk <= ZERO:
        warnings.append(
            f"signal {signal.signal_id} produced non-positive risk using signal-bar extremum; trade skipped"
        )
        return None

    exit_index, exit_price, exit_reason = _find_exit(
        bars=bars,
        direction=signal.direction,
        start_index=entry_index,
        stop_price=stop_price,
        target_price=target_price,
    )
    pnl_per_share = _pnl_per_share(signal.direction, entry_price, exit_price)
    pnl_r = _quantize(pnl_per_share / risk)
    if exit_reason == "end_of_data":
        warnings.append(
            f"signal {signal.signal_id} reached the end of available bars before stop or target; trade closed at last close"
        )

    return TradeRecord(
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        market=signal.market,
        timeframe=signal.timeframe,
        direction=signal.direction,
        setup_type=signal.setup_type,
        signal_bar_index=signal_index,
        signal_bar_timestamp=signal_bar.timestamp,
        entry_bar_index=entry_index,
        entry_timestamp=bars[entry_index].timestamp,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        exit_bar_index=exit_index,
        exit_timestamp=bars[exit_index].timestamp,
        exit_price=exit_price,
        exit_reason=exit_reason,
        risk_per_share=_quantize(risk),
        pnl_per_share=_quantize(pnl_per_share),
        pnl_r=pnl_r,
        bars_held=(exit_index - entry_index) + 1,
        source_refs=signal.source_refs,
        explanation=(
            f"deterministic backtest assumed next-bar-open entry after signal {signal.signal_id}; "
            f"stop anchored to signal-bar extremum and target fixed at {DEFAULT_TARGET_R_MULTIPLE}R. "
            f"{signal.explanation}"
        ),
        risk_notes=signal.risk_notes,
    )


def _find_exit(
    *,
    bars: Sequence[OhlcvRow],
    direction: str,
    start_index: int,
    stop_price: Decimal,
    target_price: Decimal,
) -> tuple[int, Decimal, str]:
    for index in range(start_index, len(bars)):
        bar = bars[index]
        if direction == "long":
            stop_hit = bar.low <= stop_price
            target_hit = bar.high >= target_price
        else:
            stop_hit = bar.high >= stop_price
            target_hit = bar.low <= target_price

        if stop_hit and target_hit:
            return index, stop_price, "stop_before_target_same_bar"
        if stop_hit:
            return index, stop_price, "stop_hit"
        if target_hit:
            return index, target_price, "target_hit"

    last_bar = bars[-1]
    return len(bars) - 1, last_bar.close, "end_of_data"


def _compute_stats(
    trades: Sequence[TradeRecord],
    *,
    bar_count: int,
    signal_count: int,
) -> BacktestStats:
    closed_trades = tuple(trade for trade in trades if trade.exit_reason != "end_of_data")
    trade_count = len(trades)
    closed_trade_count = len(closed_trades)
    win_values = [trade.pnl_r for trade in closed_trades if trade.pnl_r > ZERO]
    loss_values = [trade.pnl_r for trade in closed_trades if trade.pnl_r < ZERO]
    total_pnl = sum((trade.pnl_r for trade in closed_trades), ZERO)
    win_rate = _quantize(Decimal(len(win_values)) / Decimal(closed_trade_count)) if closed_trade_count else ZERO
    average_win = _quantize(sum(win_values, ZERO) / Decimal(len(win_values))) if win_values else ZERO
    average_loss = _quantize(sum(loss_values, ZERO) / Decimal(len(loss_values))) if loss_values else ZERO
    expectancy = _quantize(total_pnl / Decimal(closed_trade_count)) if closed_trade_count else ZERO
    gross_profit = sum(win_values, ZERO)
    gross_loss = abs(sum(loss_values, ZERO))
    profit_factor = _quantize(gross_profit / gross_loss) if gross_loss > ZERO else None
    max_drawdown = _compute_max_drawdown(closed_trades)
    trades_per_100_bars = (
        _quantize((Decimal(closed_trade_count) / Decimal(bar_count)) * HUNDRED) if bar_count else ZERO
    )

    return BacktestStats(
        total_signals=signal_count,
        trade_count=trade_count,
        closed_trade_count=closed_trade_count,
        win_count=len(win_values),
        loss_count=len(loss_values),
        win_rate=win_rate,
        average_win_r=average_win,
        average_loss_r=average_loss,
        expectancy_r=expectancy,
        total_pnl_r=_quantize(total_pnl),
        profit_factor=profit_factor,
        max_drawdown_r=max_drawdown,
        trades_per_100_bars=trades_per_100_bars,
        slippage_sensitivity=build_slippage_sensitivity(
            baseline_total_pnl_r=_quantize(total_pnl),
            trade_count=trade_count,
        ),
    )


def _compute_max_drawdown(trades: Sequence[TradeRecord]) -> Decimal:
    equity = ZERO
    peak = ZERO
    max_drawdown = ZERO
    for trade in trades:
        equity += trade.pnl_r
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return _quantize(max_drawdown)


def _index_signal_bars(
    bars: Sequence[OhlcvRow],
    signals: Sequence[Signal],
) -> dict[str, int]:
    lookup: dict[str, int] = {}
    setup_types = {signal.setup_type for signal in signals}
    for index, bar in enumerate(bars):
        for setup_type in setup_types:
            for direction in ("long", "short"):
                signal_id = _build_signal_id(setup_type, bar, direction)
                lookup[signal_id] = index
    return lookup


def _build_signal_id(setup_type: str, bar: OhlcvRow, direction: str) -> str:
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
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def _pnl_per_share(direction: str, entry_price: Decimal, exit_price: Decimal) -> Decimal:
    if direction == "long":
        return exit_price - entry_price
    return entry_price - exit_price


def _normalize_bars(
    bars: DeterministicReplay | Sequence[OhlcvRow] | Iterable[OhlcvRow],
) -> tuple[OhlcvRow, ...]:
    if isinstance(bars, DeterministicReplay):
        return tuple(step.bar for step in bars.snapshot())
    return tuple(sorted(tuple(bars), key=lambda bar: (bar.timestamp, bar.symbol, bar.timeframe)))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(QUANT, rounding=ROUND_HALF_UP)
