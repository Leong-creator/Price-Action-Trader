from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "public_backtest_demo_lib.py"
SPEC = importlib.util.spec_from_file_location("public_backtest_demo_lib", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PublicBacktestDemoTests(unittest.TestCase):
    def test_build_ohlcv_row_round_trip_schema(self) -> None:
        instrument = MODULE.InstrumentConfig(
            ticker="NVDA",
            symbol="NVDA",
            label="NVIDIA",
            market="US",
            timezone="America/New_York",
            demo_role="trend",
        )
        row = MODULE.build_ohlcv_row(
            instrument=instrument,
            interval="1d",
            trading_date=MODULE.date.fromisoformat("2024-01-02"),
            open_value="10.10",
            high_value="11.20",
            low_value="9.90",
            close_value="10.80",
            volume_value="1200",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "cache.csv"
            MODULE.write_cache_csv(csv_path, [row])
            loaded = MODULE.load_ohlcv_csv(csv_path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].symbol, "NVDA")
        self.assertEqual(loaded[0].market, "US")
        self.assertEqual(loaded[0].timeframe, "1d")
        self.assertEqual(loaded[0].timezone, "America/New_York")

    def test_compute_demo_quantity_uses_risk_budget_and_equity(self) -> None:
        trade = MODULE.TradeRecord(
            signal_id="sig-1",
            symbol="NVDA",
            market="US",
            timeframe="1d",
            direction="long",
            setup_type="demo_setup",
            signal_bar_index=1,
            signal_bar_timestamp=MODULE.datetime.now(MODULE.UTC),
            entry_bar_index=2,
            entry_timestamp=MODULE.datetime.now(MODULE.UTC),
            entry_price=MODULE.Decimal("50"),
            stop_price=MODULE.Decimal("48"),
            target_price=MODULE.Decimal("54"),
            exit_bar_index=3,
            exit_timestamp=MODULE.datetime.now(MODULE.UTC),
            exit_price=MODULE.Decimal("54"),
            exit_reason="target_hit",
            risk_per_share=MODULE.Decimal("2"),
            pnl_per_share=MODULE.Decimal("4"),
            pnl_r=MODULE.Decimal("2"),
            bars_held=1,
            source_refs=("wiki:test",),
            explanation="demo",
            risk_notes=("demo",),
        )
        quantity = MODULE.compute_demo_quantity(
            trade=trade,
            current_equity=MODULE.Decimal("1000"),
            risk_per_trade=MODULE.Decimal("100"),
        )
        self.assertEqual(quantity, MODULE.Decimal("20"))

    @unittest.skipUnless(MODULE.plt is not None, "matplotlib not available in the active interpreter")
    def test_create_backtest_run_from_cached_fixture_generates_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            cache_dir = temp_root / "cache"
            report_dir = temp_root / "reports"
            config_path = temp_root / "demo.json"
            config_path.write_text(
                json.dumps(
                    {
                        "title": "Unit Demo",
                        "description": "Unit-test smoke demo.",
                        "start": "2026-01-05",
                        "end": "2026-01-05",
                        "interval": "5m",
                        "cache_dir": str(cache_dir),
                        "report_dir": str(report_dir),
                        "source_order": ["yfinance"],
                        "instruments": [
                            {
                                "ticker": "SAMPLE",
                                "symbol": "SAMPLE",
                                "label": "Sample",
                                "market": "US",
                                "timezone": "America/New_York",
                                "demo_role": "smoke"
                            }
                        ],
                        "risk": {
                            "starting_capital": "10000",
                            "risk_per_trade": "100",
                            "max_total_exposure": "10000",
                            "max_symbol_exposure_ratio": "1.00",
                            "max_daily_loss": "500",
                            "max_consecutive_losses": 4
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = MODULE.load_demo_config(config_path)
            cache_path = MODULE.build_cache_path(config, config.instruments[0], source="yfinance")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "tests" / "test_data" / "ohlcv_sample_5m.csv", cache_path)
            cache_path.with_suffix(".metadata.json").write_text(
                json.dumps({"source": "yfinance", "row_count": 5}, ensure_ascii=False),
                encoding="utf-8",
            )

            outcome = MODULE.create_backtest_run(config, refresh_data=False, run_id="unit_demo")
            output_dir = Path(outcome["report_dir"])

            self.assertTrue((output_dir / "summary.json").exists())
            self.assertTrue((output_dir / "report.md").exists())
            self.assertTrue((output_dir / "trades.csv").exists())
            self.assertTrue((output_dir / "equity_curve.png").exists())
            self.assertEqual(outcome["summary"]["boundary"], "paper/simulated")


if __name__ == "__main__":
    unittest.main()
