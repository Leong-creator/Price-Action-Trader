from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .contracts import BacktestStats, SlippageResult


ZERO = Decimal("0")
HUNDRED = Decimal("100")
QUANT = Decimal("0.0001")


def default_assumptions() -> tuple[str, ...]:
    return (
        "deterministic next-bar-open entry after each structured signal",
        "signal-bar low/high is used as the protective stop anchor",
        "target is fixed at 2R because current M3 target_rule is still research-only text",
        "if stop and target are both hit within one bar, the stop is taken first",
        "no slippage, fees, partial fills, leverage, or position sizing is modeled in this baseline",
    )


def build_summary(stats: BacktestStats, warnings: tuple[str, ...]) -> str:
    if stats.trade_count == 0:
        if warnings:
            return (
                "No trades were recorded in the deterministic backtest. "
                f"Warnings: {' | '.join(warnings)}"
            )
        return "No trades were recorded in the deterministic backtest."

    parts = [
        f"{stats.trade_count} trade(s) from {stats.total_signals} signal(s)",
        f"win_rate={format_decimal(stats.win_rate * HUNDRED)}%",
        f"expectancy={format_decimal(stats.expectancy_r)}R",
        f"total_pnl={format_decimal(stats.total_pnl_r)}R",
        f"max_drawdown={format_decimal(stats.max_drawdown_r)}R",
    ]
    if stats.slippage_sensitivity:
        slippage = ", ".join(
            f"{item.label}:{format_decimal(item.total_pnl_r)}R"
            for item in stats.slippage_sensitivity
        )
        parts.append(f"slippage=[{slippage}]")
    if warnings:
        parts.append(f"warnings={len(warnings)}")
    return "; ".join(parts)


def build_slippage_sensitivity(
    *,
    baseline_total_pnl_r: Decimal,
    trade_count: int,
    per_trade_penalty_r: Decimal = Decimal("0.0500"),
) -> tuple[SlippageResult, ...]:
    baseline = quantize(baseline_total_pnl_r)
    if trade_count == 0:
        stressed = baseline
    else:
        stressed = quantize(baseline - (per_trade_penalty_r * Decimal(trade_count)))

    return (
        SlippageResult(
            label="baseline_0r",
            total_pnl_r=baseline,
            delta_from_baseline_r=ZERO,
        ),
        SlippageResult(
            label="stress_0.05r_per_trade",
            total_pnl_r=stressed,
            delta_from_baseline_r=quantize(stressed - baseline),
        ),
    )


def quantize(value: Decimal) -> Decimal:
    return value.quantize(QUANT, rounding=ROUND_HALF_UP)


def format_decimal(value: Decimal) -> str:
    return format(quantize(value), "f")
