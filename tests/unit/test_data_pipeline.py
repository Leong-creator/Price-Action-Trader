from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.data import (
    DataValidationError,
    build_replay,
    load_news_events,
    load_ohlcv_csv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DATA_DIR = PROJECT_ROOT / "tests" / "test_data"


class DataPipelineTests(unittest.TestCase):
    def test_load_sample_ohlcv_csv(self) -> None:
        bars = load_ohlcv_csv(TEST_DATA_DIR / "ohlcv_sample_5m.csv")

        self.assertEqual(len(bars), 5)
        self.assertEqual(bars[0].symbol, "SAMPLE")
        self.assertEqual(bars[0].timestamp.isoformat(), "2026-01-05T09:30:00-05:00")
        self.assertEqual(bars[-1].close, 100.6)

    def test_load_sample_news_json(self) -> None:
        events = load_news_events(TEST_DATA_DIR / "news_sample.json")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].severity, "medium")
        self.assertEqual(events[0].timestamp.isoformat(), "2026-01-05T09:00:00-05:00")

    def test_duplicate_bars_are_rejected(self) -> None:
        duplicate_csv = """symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume
SAMPLE,US,5m,2026-01-05T09:30:00,America/New_York,100.00,101.20,99.80,100.90,120000
SAMPLE,US,5m,2026-01-05T09:30:00,America/New_York,100.90,102.00,100.70,101.80,135000
"""

        path = self._write_temp_file("bars.csv", duplicate_csv)
        with self.assertRaisesRegex(DataValidationError, "duplicate OHLCV row"):
            load_ohlcv_csv(path)

    def test_invalid_price_relationship_is_rejected(self) -> None:
        invalid_csv = """symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume
SAMPLE,US,5m,2026-01-05T09:30:00,America/New_York,100.00,99.00,98.80,100.90,120000
"""

        path = self._write_temp_file("bars.csv", invalid_csv)
        with self.assertRaisesRegex(DataValidationError, "high must be >="):
            load_ohlcv_csv(path)

    def test_invalid_numeric_values_are_rejected(self) -> None:
        invalid_csv = """symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume
SAMPLE,US,5m,2026-01-05T09:30:00,America/New_York,-1,101.20,99.80,100.90,120000
"""

        path = self._write_temp_file("bars.csv", invalid_csv)
        with self.assertRaisesRegex(DataValidationError, "field 'open'"):
            load_ohlcv_csv(path)

    def test_invalid_news_payload_is_rejected(self) -> None:
        invalid_json = json.dumps(
            [
                {
                    "symbol": "SAMPLE",
                    "market": "US",
                    "timestamp": "2026-01-05T09:00:00",
                    "source": "synthetic-test-fixture",
                    "event_type": "earnings_related_volatility",
                    "headline": "missing notes and timezone",
                    "severity": "medium",
                    "notes": "",
                }
            ]
        )

        path = self._write_temp_file("events.json", invalid_json)
        with self.assertRaisesRegex(DataValidationError, "missing required fields"):
            load_news_events(path)

    def test_deterministic_replay_orders_unsorted_bars_and_attaches_news(self) -> None:
        bars = load_ohlcv_csv(TEST_DATA_DIR / "ohlcv_sample_5m.csv")
        events = load_news_events(TEST_DATA_DIR / "news_sample.json")

        replay = build_replay(reversed(bars), events)
        steps = list(replay)

        self.assertEqual([step.index for step in steps], [0, 1, 2, 3, 4])
        self.assertEqual(steps[0].bar.timestamp.isoformat(), "2026-01-05T09:30:00-05:00")
        self.assertEqual(len(steps[0].news_events), 0)
        self.assertEqual(len(replay), 5)
        self.assertEqual(replay.remaining(), 0)

        replay.reset()
        snapshot = replay.snapshot()
        self.assertEqual(len(snapshot), 5)
        self.assertEqual(snapshot[0].bar.timestamp.isoformat(), steps[0].bar.timestamp.isoformat())

    def _write_temp_file(self, filename: str, content: str) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="pat-data-pipeline-"))
        path = temp_dir / filename
        path.write_text(content, encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
