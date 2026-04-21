from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.backtest.contracts import BacktestReport, BacktestStats, TradeRecord
from src.data.schema import OhlcvRow
from src.strategy_factory.batch_backtest import (
    PRIMARY_DATASET_SYMBOL,
    SPLIT_NAMES,
    SUPPORTED_TIMEFRAME,
    StrategyVariant,
    _classify_sample_status,
    _count_split_trades,
    _evaluate_sf003,
    _select_primary_intraday_dataset,
)


def _build_bar(
    *,
    timestamp: datetime,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
) -> OhlcvRow:
    return OhlcvRow(
        symbol="SPY",
        market="US",
        timeframe=SUPPORTED_TIMEFRAME,
        timestamp=timestamp,
        timezone="America/New_York",
        open=Decimal(open_price),
        high=Decimal(high_price),
        low=Decimal(low_price),
        close=Decimal(close_price),
        volume=Decimal("1000"),
    )


def _build_trade(*, entry_timestamp: datetime, exit_reason: str) -> TradeRecord:
    return TradeRecord(
        signal_id=f"sig-{entry_timestamp.isoformat()}-{exit_reason}",
        symbol="SPY",
        market="US",
        timeframe=SUPPORTED_TIMEFRAME,
        direction="long",
        setup_type="fixture",
        signal_bar_index=0,
        signal_bar_timestamp=entry_timestamp - timedelta(minutes=5),
        entry_bar_index=1,
        entry_timestamp=entry_timestamp,
        entry_price=Decimal("100"),
        stop_price=Decimal("99"),
        target_price=Decimal("102"),
        exit_bar_index=2,
        exit_timestamp=entry_timestamp + timedelta(minutes=5),
        exit_price=Decimal("102") if exit_reason != "end_of_data" else Decimal("101"),
        exit_reason=exit_reason,
        risk_per_share=Decimal("1"),
        pnl_per_share=Decimal("2") if exit_reason != "end_of_data" else Decimal("1"),
        pnl_r=Decimal("2") if exit_reason != "end_of_data" else Decimal("1"),
        bars_held=2,
        source_refs=("wiki:test",),
        explanation="fixture trade",
        risk_notes=("paper only",),
    )


class TestStrategyFactoryBacktestLogic(unittest.TestCase):
    def test_select_primary_intraday_dataset_uses_provider_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_dir = root / "local_data" / "custom_provider_intraday"
            cache_dir.mkdir(parents=True)
            older = cache_dir / f"us_{PRIMARY_DATASET_SYMBOL}_{SUPPORTED_TIMEFRAME}_2026-01-01_2026-02-01_custom.csv"
            newer = cache_dir / f"us_{PRIMARY_DATASET_SYMBOL}_{SUPPORTED_TIMEFRAME}_2026-02-02_2026-03-01_custom.csv"
            older.write_text("stub\n", encoding="utf-8")
            newer.write_text("stub\n", encoding="utf-8")

            selected = _select_primary_intraday_dataset(root, provider="custom_provider")

        self.assertEqual(selected.name, newer.name)

    def test_sf003_can_emit_failed_breakout_reversal(self) -> None:
        start = datetime(2026, 3, 2, 9, 30, tzinfo=UTC)
        bars = []
        for offset in range(19):
            base = Decimal("100") + (Decimal(offset % 3) * Decimal("0.2"))
            bars.append(
                _build_bar(
                    timestamp=start + timedelta(minutes=5 * offset),
                    open_price=str(base),
                    high_price=str(base + Decimal("1.0")),
                    low_price=str(base - Decimal("1.0")),
                    close_price=str(base + Decimal("0.1")),
                )
            )
        bars.append(
            _build_bar(
                timestamp=start + timedelta(minutes=5 * 19),
                open_price="99.8",
                high_price="100.8",
                low_price="98.2",
                close_price="99.4",
            )
        )
        bars.append(
            _build_bar(
                timestamp=start + timedelta(minutes=5 * 20),
                open_price="99.5",
                high_price="101.2",
                low_price="99.3",
                close_price="101.1",
            )
        )

        status, direction, reason, _, _ = _evaluate_sf003(
            tuple(bars),
            20,
            StrategyVariant(strategy_id="SF-003", variant_id="baseline", label="baseline", rule_overrides={}),
        )

        self.assertEqual(status, "emitted")
        self.assertEqual(direction, "long")
        self.assertEqual(reason, "signal_confirmed")

    def test_end_of_data_trades_do_not_count_toward_closed_sample_gate(self) -> None:
        split_labels = {
            "2026-03-02": SPLIT_NAMES[0],
            "2026-03-03": SPLIT_NAMES[1],
        }
        report = BacktestReport(
            trades=(
                _build_trade(entry_timestamp=datetime(2026, 3, 2, 10, 0, tzinfo=UTC), exit_reason="target_hit"),
                _build_trade(entry_timestamp=datetime(2026, 3, 3, 10, 0, tzinfo=UTC), exit_reason="end_of_data"),
            ),
            stats=BacktestStats(
                total_signals=2,
                trade_count=2,
                closed_trade_count=1,
                win_count=1,
                loss_count=0,
                win_rate=Decimal("1"),
                average_win_r=Decimal("2"),
                average_loss_r=Decimal("0"),
                expectancy_r=Decimal("2"),
                total_pnl_r=Decimal("2"),
                profit_factor=None,
                max_drawdown_r=Decimal("0"),
                trades_per_100_bars=Decimal("1"),
                slippage_sensitivity=(),
            ),
            summary="fixture",
            warnings=(),
            assumptions=(),
        )

        closed_counts = _count_split_trades(report, split_labels, closed_only=True)
        executed_counts = _count_split_trades(report, split_labels, closed_only=False)

        self.assertEqual(closed_counts, {"in_sample": 1, "validation": 0, "out_of_sample": 0})
        self.assertEqual(executed_counts, {"in_sample": 1, "validation": 1, "out_of_sample": 0})

    def test_single_symbol_single_regime_batch_stays_exploratory(self) -> None:
        split_counts = {"in_sample": 40, "validation": 40, "out_of_sample": 40}
        self.assertEqual(
            _classify_sample_status(
                trade_count=120,
                split_trade_counts=split_counts,
                symbol_count=1,
                regime_count=1,
            ),
            "exploratory_probe",
        )
        self.assertEqual(
            _classify_sample_status(
                trade_count=120,
                split_trade_counts=split_counts,
                symbol_count=2,
                regime_count=2,
            ),
            "formal_candidate",
        )


if __name__ == "__main__":
    unittest.main()
