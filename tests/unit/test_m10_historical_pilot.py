from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from scripts.m10_historical_pilot_lib import (
    ALLOWED_OUTCOMES,
    EXCLUDED_IDS,
    WAVE_A_IDS,
    DataWindow,
    aggregate_bars,
    find_dataset_file,
    load_dataset_for_timeframe,
    load_pilot_config,
    load_wave_a_specs,
    run_m10_historical_pilot,
    validate_wave_a_specs,
)
from src.data import OhlcvRow


class M10HistoricalPilotTest(unittest.TestCase):
    def test_default_daily_window_uses_long_horizon(self) -> None:
        config = load_pilot_config()

        self.assertEqual(config.data_windows["1d"].start, date(2010, 6, 29))
        self.assertEqual(config.data_windows["1d"].end, date(2026, 4, 21))
        self.assertIn(Path("/home/hgl/projects/Price-Action-Trader/local_data"), config.cache_roots)
        self.assertTrue(config.paper_simulated_only)

    def test_sibling_main_local_cache_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "local_data" / "longbridge_history"
            root.mkdir(parents=True)
            csv_path = root / "us_SPY_1d_2010-06-29_2026-04-21_longbridge.csv"
            csv_path.write_text("symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume\n", encoding="utf-8")

            resolved = find_dataset_file(
                symbol="SPY",
                timeframe="1d",
                window=DataWindow(start=date(2010, 6, 29), end=date(2026, 4, 21)),
                cache_roots=(Path(tmp) / "missing", Path(tmp) / "local_data"),
            )

        self.assertEqual(resolved, csv_path)

    def test_derived_15m_lineage_from_5m(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp) / "local_data" / "longbridge_history"
            cache_root.mkdir(parents=True)
            csv_path = cache_root / "us_SPY_5m_2024-04-01_2026-04-21_longbridge.csv"
            write_csv_rows(csv_path, "SPY", "5m", datetime(2024, 4, 1, 9, 30), 6)
            config = replace(
                load_pilot_config(),
                data_windows={
                    "5m": DataWindow(start=date(2024, 4, 1), end=date(2026, 4, 21)),
                    "15m": DataWindow(start=date(2024, 4, 1), end=date(2026, 4, 21), derive_from="5m"),
                    "1h": DataWindow(start=date(2024, 4, 1), end=date(2026, 4, 21), derive_from="5m"),
                    "1d": DataWindow(start=date(2010, 6, 29), end=date(2026, 4, 21)),
                },
                cache_roots=(Path(tmp) / "local_data",),
            )

            bars, record = load_dataset_for_timeframe(symbol="SPY", timeframe="15m", config=config)

        self.assertEqual(record.lineage, "derived_from_5m")
        self.assertEqual(record.status, "available")
        self.assertEqual(record.csv_path, csv_path)
        self.assertEqual([bar.timeframe for bar in bars], ["15m", "15m"])

    def test_aggregate_bars_uses_ohlcv_boundaries(self) -> None:
        bars = [
            OhlcvRow(
                symbol="SPY",
                market="US",
                timeframe="5m",
                timestamp=datetime(2024, 4, 1, 9, 30) + timedelta(minutes=5 * idx),
                timezone="America/New_York",
                open=Decimal("100") + Decimal(idx),
                high=Decimal("101") + Decimal(idx),
                low=Decimal("99") + Decimal(idx),
                close=Decimal("100.5") + Decimal(idx),
                volume=Decimal("1000") + Decimal(idx),
            )
            for idx in range(3)
        ]

        derived = aggregate_bars(bars, "15m")

        self.assertEqual(len(derived), 1)
        self.assertEqual(derived[0].timeframe, "15m")
        self.assertEqual(derived[0].open, Decimal("100"))
        self.assertEqual(derived[0].high, Decimal("103"))
        self.assertEqual(derived[0].low, Decimal("99"))
        self.assertEqual(derived[0].close, Decimal("102.5"))
        self.assertEqual(derived[0].volume, Decimal("3003"))

    def test_wave_a_spec_scope_and_m10_012_timeframes(self) -> None:
        specs = load_wave_a_specs(load_pilot_config().spec_index_path)
        validate_wave_a_specs(specs)

        self.assertEqual({spec["strategy_id"] for spec in specs}, set(WAVE_A_IDS))
        m10_012 = next(spec for spec in specs if spec["strategy_id"] == "M10-PA-012")
        self.assertEqual(m10_012["timeframes"], ["15m", "5m"])

    def test_missing_data_generates_deferred_record_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(load_pilot_config(), cache_roots=(Path(tmp) / "empty_cache",))

            bars, record = load_dataset_for_timeframe(symbol="SPY", timeframe="1d", config=config)

        self.assertEqual(bars, [])
        self.assertEqual(record.status, "data_unavailable_deferred")
        self.assertEqual(record.row_count, 0)
        self.assertEqual(record.deferred_reason, "no_local_cache_and_download_disabled")

    def test_deferred_pilot_scope_and_legacy_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(load_pilot_config(), cache_roots=(Path(tmp) / "empty_cache",), output_dir=Path(tmp) / "pilot")

            summary = run_m10_historical_pilot(config)

            serialized = json.dumps(summary, ensure_ascii=False)
            self.assertEqual(summary["wave_a_strategy_ids"], list(WAVE_A_IDS))
            self.assertEqual(set(summary["excluded_strategy_ids"]), set(EXCLUDED_IDS))
            self.assertNotIn("PA-SC-", serialized)
            self.assertNotIn("SF-", serialized)
            self.assertEqual(summary["allowed_outcomes"], list(ALLOWED_OUTCOMES))
            self.assertFalse(summary["broker_connection"])
            self.assertFalse(summary["live_execution"])
            self.assertFalse(summary["real_orders"])
            self.assertFalse(summary["retain_or_promote_allowed"])


def write_csv_rows(path: Path, symbol: str, timeframe: str, start: datetime, count: int) -> None:
    rows = ["symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume"]
    for idx in range(count):
        timestamp = start + timedelta(minutes=5 * idx)
        open_price = Decimal("100") + Decimal(idx)
        rows.append(
            ",".join(
                [
                    symbol,
                    "US",
                    timeframe,
                    timestamp.isoformat(),
                    "America/New_York",
                    str(open_price),
                    str(open_price + Decimal("1")),
                    str(open_price - Decimal("1")),
                    str(open_price + Decimal("0.5")),
                    "1000",
                ]
            )
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
