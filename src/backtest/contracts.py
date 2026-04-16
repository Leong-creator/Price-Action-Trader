from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SlippageResult:
    label: str
    total_pnl_r: Decimal
    delta_from_baseline_r: Decimal


@dataclass(frozen=True, slots=True)
class TradeRecord:
    signal_id: str
    symbol: str
    market: str
    timeframe: str
    direction: str
    setup_type: str
    signal_bar_index: int
    signal_bar_timestamp: datetime
    entry_bar_index: int
    entry_timestamp: datetime
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    exit_bar_index: int
    exit_timestamp: datetime
    exit_price: Decimal
    exit_reason: str
    risk_per_share: Decimal
    pnl_per_share: Decimal
    pnl_r: Decimal
    bars_held: int
    source_refs: tuple[str, ...]
    explanation: str
    risk_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BacktestStats:
    total_signals: int
    trade_count: int
    closed_trade_count: int
    win_count: int
    loss_count: int
    win_rate: Decimal
    average_win_r: Decimal
    average_loss_r: Decimal
    expectancy_r: Decimal
    total_pnl_r: Decimal
    profit_factor: Decimal | None
    max_drawdown_r: Decimal
    trades_per_100_bars: Decimal
    slippage_sensitivity: tuple[SlippageResult, ...]


@dataclass(frozen=True, slots=True)
class BacktestReport:
    trades: tuple[TradeRecord, ...]
    stats: BacktestStats
    summary: str
    warnings: tuple[str, ...]
    assumptions: tuple[str, ...]
