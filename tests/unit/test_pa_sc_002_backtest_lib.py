from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from src.data.schema import OhlcvRow


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "pa_sc_002_backtest_lib.py"
SPEC = importlib.util.spec_from_file_location("pa_sc_002_backtest_lib", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PASC002BacktestLibUnitTests(unittest.TestCase):
    def test_classify_filter_state_marks_choppy_history_as_range_veto(self) -> None:
        config = MODULE.build_default_config()
        history = (
            build_bar("2026-01-05T09:30:00", "100.0", "100.4", "99.9", "100.1"),
            build_bar("2026-01-05T09:35:00", "100.1", "100.3", "99.8", "99.9"),
            build_bar("2026-01-05T09:40:00", "99.9", "100.2", "99.8", "100.0"),
            build_bar("2026-01-05T09:45:00", "100.0", "100.1", "99.7", "99.8"),
            build_bar("2026-01-05T09:50:00", "99.8", "100.1", "99.7", "99.9"),
            build_bar("2026-01-05T09:55:00", "99.9", "100.0", "99.6", "99.8"),
        )

        snapshot = MODULE.classify_filter_state(history, config=config)

        self.assertEqual(snapshot.state, "range_veto")
        self.assertGreaterEqual(snapshot.flip_count, config.filter_min_flip_count)

    def test_compute_trade_stats_reports_drawdown_and_loss_streak(self) -> None:
        trades = (
            build_trade("trade-1", "0.9000"),
            build_trade("trade-2", "-1.2000"),
            build_trade("trade-3", "-0.8000"),
            build_trade("trade-4", "0.5000"),
        )

        stats = MODULE.compute_trade_stats(trades, starting_capital=Decimal("25000"))

        self.assertEqual(stats["trade_count"], 4)
        self.assertEqual(stats["max_consecutive_losses"], 2)
        self.assertLess(stats["max_drawdown_r"], 0)
        self.assertAlmostEqual(stats["expectancy_r"], -0.15, places=4)
        self.assertEqual(stats["starting_capital"], 25000.0)
        self.assertEqual(stats["ending_equity"], 24940.0)

    def test_apply_cash_sizing_uses_risk_budget_and_updates_equity(self) -> None:
        config = MODULE.build_default_config()
        trades = (
            build_trade("trade-1", "1.0000", risk_per_share="2.00", entry_price="100"),
            build_trade("trade-2", "-1.0000", risk_per_share="4.00", entry_price="120"),
        )

        sized = MODULE.apply_cash_sizing(trades, config=config)

        self.assertEqual(sized[0].quantity, Decimal("50"))
        self.assertEqual(sized[0].pnl_cash, Decimal("100.0000"))
        self.assertEqual(sized[0].equity_after_close, Decimal("25100.0000"))
        self.assertEqual(sized[1].quantity, Decimal("25"))
        self.assertEqual(sized[1].pnl_cash, Decimal("-100.0000"))
        self.assertEqual(sized[1].equity_after_close, Decimal("25000.0000"))

    def test_assign_split_labels_uses_time_order(self) -> None:
        labels = MODULE.assign_split_labels(
            (
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
                "2026-01-09",
                "2026-01-12",
                "2026-01-13",
                "2026-01-14",
            )
        )

        self.assertEqual(labels["2026-01-05"], "in_sample")
        self.assertEqual(labels["2026-01-09"], "validation")
        self.assertEqual(labels["2026-01-14"], "out_of_sample")


def build_bar(timestamp: str, open_price: str, high: str, low: str, close: str) -> OhlcvRow:
    return OhlcvRow(
        symbol="SPY",
        market="US",
        timeframe="5m",
        timestamp=datetime.fromisoformat(timestamp),
        timezone="America/New_York",
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1000"),
    )


def build_trade(
    trade_id: str,
    pnl_r: str,
    *,
    risk_per_share: str = "1",
    entry_price: str = "100",
) -> MODULE.ExecutedTrade:
    timestamp = datetime.fromisoformat("2026-01-05T10:00:00")
    value = Decimal(pnl_r)
    risk_value = Decimal(risk_per_share)
    return MODULE.ExecutedTrade(
        trade_id=trade_id,
        session_key="2026-01-05",
        split="in_sample",
        direction="long",
        filter_state="neutral",
        breakout_timestamp=timestamp,
        follow_through_timestamp=timestamp,
        entry_timestamp=timestamp,
        exit_timestamp=timestamp,
        time_bucket="open_0930_1100",
        raw_entry_price=Decimal(entry_price),
        executed_entry_price=Decimal(entry_price),
        stop_price=Decimal(entry_price) - risk_value,
        target_price=Decimal(entry_price) + risk_value,
        exit_price=Decimal(entry_price),
        executed_exit_price=Decimal(entry_price),
        risk_per_share=risk_value,
        pnl_per_share=value * risk_value,
        pnl_r=value,
        exit_reason="target_hit" if value > 0 else "stop_hit",
        breakout_body_ratio=Decimal("0.5"),
        breakout_close_ratio=Decimal("0.8"),
        breakout_avg_body_multiple=Decimal("1.4"),
        breakout_opposite_wick_ratio=Decimal("0.2"),
        filter_displacement_ratio=Decimal("0.6"),
        filter_flip_count=1,
        filter_doji_count=0,
        quantity=Decimal("100"),
        pnl_cash=(value * risk_value * Decimal("100")),
        equity_after_close=Decimal("25000") + (value * risk_value * Decimal("100")),
    )


if __name__ == "__main__":
    unittest.main()
