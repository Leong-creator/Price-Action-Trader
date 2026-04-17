from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.backtest import BacktestReport, BacktestStats
from src.backtest import TradeRecord
from src.data.replay import build_replay
from src.data.schema import OhlcvRow
from src.strategy import generate_signals


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "public_backtest_demo_lib.py"
SPEC = importlib.util.spec_from_file_location("public_backtest_demo_lib", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class KnowledgeTraceFidelityTests(unittest.TestCase):
    def test_actual_and_bundle_support_refs_are_separated(self) -> None:
        signal = generate_signals(build_replay(self._trend_bars()))[0]

        self.assertTrue(signal.actual_source_refs)
        self.assertTrue(signal.bundle_support_refs)
        self.assertTrue(set(signal.actual_source_refs).isdisjoint(set(signal.bundle_support_refs)))
        self.assertNotIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", signal.actual_source_refs)
        self.assertIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", signal.bundle_support_refs)

    def test_no_trade_wait_keeps_support_refs_out_of_actual_refs(self) -> None:
        result = MODULE.SymbolBacktestResult(
            instrument=MODULE.InstrumentConfig(
                ticker="SAMPLE",
                symbol="SAMPLE",
                label="Sample",
                market="US",
                timezone="America/New_York",
                demo_role="fixture",
            ),
            source="fixture",
            csv_path=ROOT / "tests" / "test_data" / "ohlcv_sample_5m.csv",
            metadata_path=ROOT / "tests" / "test_data" / "README.md",
            bars=self._insufficient_bars(),
            bars_count=3,
            signals=(),
            backtest_report=BacktestReport(
                trades=(),
                stats=BacktestStats(
                    total_signals=0,
                    trade_count=0,
                    closed_trade_count=0,
                    win_count=0,
                    loss_count=0,
                    win_rate=Decimal("0.0000"),
                    average_win_r=Decimal("0.0000"),
                    average_loss_r=Decimal("0.0000"),
                    expectancy_r=Decimal("0.0000"),
                    total_pnl_r=Decimal("0.0000"),
                    profit_factor=None,
                    max_drawdown_r=Decimal("0.0000"),
                    trades_per_100_bars=Decimal("0.0000"),
                    slippage_sensitivity=(),
                ),
                summary="unit",
                warnings=(),
                assumptions=(),
            ),
        )
        paper_outcome = MODULE.PaperDemoOutcome(
            executed_trades=(),
            blocked_signals=(),
            equity_points=((datetime.now(UTC).isoformat(), 10000.0),),
            ending_equity=Decimal("10000"),
        )
        records = MODULE.build_no_trade_wait_records((result,), paper_outcome)

        insufficient = next(item for item in records if item.reason_code == "insufficient_evidence")
        self.assertEqual(insufficient.actual_source_refs, ())
        self.assertEqual(insufficient.bundle_support_refs, insufficient.source_refs)

    def test_trace_json_and_coverage_distinguish_actual_vs_bundle_support(self) -> None:
        signal = generate_signals(build_replay(self._trend_bars()))[0]
        executed = MODULE.ExecutedTradeRecord(
            instrument=MODULE.InstrumentConfig(
                ticker=signal.symbol,
                symbol=signal.symbol,
                label="Sample",
                market=signal.market,
                timezone="America/New_York",
                demo_role="fixture",
            ),
            signal=signal,
            trade=self._trade(signal),
            quantity=Decimal("1"),
            pnl_cash=Decimal("2"),
            equity_after_close=Decimal("10002"),
        )
        paper_outcome = MODULE.PaperDemoOutcome(
            executed_trades=(executed,),
            blocked_signals=(),
            equity_points=((datetime.now(UTC).isoformat(), 10002.0),),
            ending_equity=Decimal("10002"),
        )
        result = MODULE.SymbolBacktestResult(
            instrument=executed.instrument,
            source="fixture",
            csv_path=ROOT / "tests" / "test_data" / "ohlcv_sample_5m.csv",
            metadata_path=ROOT / "tests" / "test_data" / "README.md",
            bars=self._trend_bars(),
            bars_count=3,
            signals=(signal,),
            backtest_report=BacktestReport(
                trades=(executed.trade,),
                stats=BacktestStats(
                    total_signals=1,
                    trade_count=1,
                    closed_trade_count=1,
                    win_count=1,
                    loss_count=0,
                    win_rate=Decimal("1.0000"),
                    average_win_r=Decimal("2.0000"),
                    average_loss_r=Decimal("0.0000"),
                    expectancy_r=Decimal("2.0000"),
                    total_pnl_r=Decimal("2.0000"),
                    profit_factor=None,
                    max_drawdown_r=Decimal("0.0000"),
                    trades_per_100_bars=Decimal("33.3333"),
                    slippage_sensitivity=(),
                ),
                summary="unit",
                warnings=(),
                assumptions=(),
            ),
        )

        coverage = MODULE.build_knowledge_trace_coverage((result,), paper_outcome)
        self.assertIn("actual_hit_source_family_presence", coverage["overall"])
        self.assertIn("bundle_support_family_presence", coverage["overall"])
        self.assertTrue(coverage["overall"]["actual_hit_source_family_presence"])
        self.assertTrue(coverage["overall"]["bundle_support_family_presence"])

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "knowledge_trace.json"
            MODULE.write_knowledge_trace_json(
                output_path,
                run_id="unit_trace_fidelity",
                paper_outcome=paper_outcome,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        executed_payload = payload["executed_trades"][0]
        self.assertEqual(executed_payload["knowledge_trace"], executed_payload["visible_trace"])
        self.assertTrue(executed_payload["actual_source_refs"])
        self.assertTrue(executed_payload["bundle_support_refs"])
        self.assertTrue(executed_payload["debug_trace"])

    def _trend_bars(self) -> tuple[OhlcvRow, ...]:
        timestamps = (
            datetime(2026, 1, 5, 9, 30, tzinfo=MODULE.ZoneInfo("America/New_York")),
            datetime(2026, 1, 5, 9, 35, tzinfo=MODULE.ZoneInfo("America/New_York")),
            datetime(2026, 1, 5, 9, 40, tzinfo=MODULE.ZoneInfo("America/New_York")),
        )
        values = (
            ("100.0", "100.6", "99.8", "100.3"),
            ("100.3", "100.9", "100.1", "100.7"),
            ("100.7", "101.4", "100.6", "101.2"),
        )
        return tuple(
            OhlcvRow(
                symbol="SAMPLE",
                market="US",
                timeframe="5m",
                timestamp=timestamp,
                timezone="America/New_York",
                open=Decimal(open_),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
                volume=Decimal("100000"),
            )
            for timestamp, (open_, high, low, close) in zip(timestamps, values, strict=True)
        )

    def _insufficient_bars(self) -> tuple[OhlcvRow, ...]:
        timestamps = (
            datetime(2026, 1, 5, 9, 30, tzinfo=MODULE.ZoneInfo("America/New_York")),
            datetime(2026, 1, 5, 9, 35, tzinfo=MODULE.ZoneInfo("America/New_York")),
            datetime(2026, 1, 5, 9, 40, tzinfo=MODULE.ZoneInfo("America/New_York")),
        )
        values = (
            ("100.0", "100.6", "99.8", "100.3"),
            ("100.3", "100.9", "100.1", "100.7"),
            ("100.7", "101.1", "100.6", "100.88"),
        )
        return tuple(
            OhlcvRow(
                symbol="SAMPLE",
                market="US",
                timeframe="5m",
                timestamp=timestamp,
                timezone="America/New_York",
                open=Decimal(open_),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
                volume=Decimal("100000"),
            )
            for timestamp, (open_, high, low, close) in zip(timestamps, values, strict=True)
        )

    def _trade(self, signal) -> TradeRecord:
        return TradeRecord(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            market=signal.market,
            timeframe=signal.timeframe,
            direction=signal.direction,
            setup_type=signal.setup_type,
            signal_bar_index=1,
            signal_bar_timestamp=self._trend_bars()[1].timestamp,
            entry_bar_index=2,
            entry_timestamp=self._trend_bars()[2].timestamp,
            entry_price=Decimal("101"),
            stop_price=Decimal("100"),
            target_price=Decimal("103"),
            exit_bar_index=3,
            exit_timestamp=datetime(2026, 1, 5, 9, 45, tzinfo=MODULE.ZoneInfo("America/New_York")),
            exit_price=Decimal("103"),
            exit_reason="target_hit",
            risk_per_share=Decimal("1"),
            pnl_per_share=Decimal("2"),
            pnl_r=Decimal("2"),
            bars_held=1,
            source_refs=signal.source_refs,
            explanation=signal.explanation,
            risk_notes=signal.risk_notes,
        )


if __name__ == "__main__":
    unittest.main()
