from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.data import (
    DataValidationError,
    OhlcvRow,
    ValidationError,
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
        self.assertIsInstance(bars[0], OhlcvRow)
        self.assertEqual(bars[0].symbol, "SAMPLE")
        self.assertEqual(bars[0].timestamp.isoformat(), "2026-01-05T09:30:00-05:00")
        self.assertEqual(str(bars[-1].close), "100.60")

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
        with self.assertRaises(DataValidationError) as ctx:
            load_ohlcv_csv(path)

        self.assertIn("non_positive_price", str(ctx.exception))
        self.assertTrue(any(issue.field == "open" for issue in ctx.exception.issues))

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
        with self.assertRaises(DataValidationError) as ctx:
            load_news_events(path)

        self.assertIn("missing_required_field", str(ctx.exception))
        self.assertTrue(any(issue.field == "notes" for issue in ctx.exception.issues))

    def test_invalid_news_severity_is_rejected(self) -> None:
        invalid_json = json.dumps(
            [
                {
                    "symbol": "SAMPLE",
                    "market": "US",
                    "timestamp": "2026-01-05T09:00:00-05:00",
                    "source": "synthetic-test-fixture",
                    "event_type": "earnings_related_volatility",
                    "headline": "bad severity",
                    "severity": "urgent",
                    "notes": "bad severity for validation",
                }
            ]
        )

        path = self._write_temp_file("events.json", invalid_json)
        with self.assertRaisesRegex(DataValidationError, "invalid_severity"):
            load_news_events(path)

    def test_invalid_market_is_rejected_for_csv_and_news(self) -> None:
        invalid_csv = """symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume
SAMPLE,EU,5m,2026-01-05T09:30:00,America/New_York,100.00,101.20,99.80,100.90,120000
"""
        csv_path = self._write_temp_file("bars.csv", invalid_csv)
        with self.assertRaisesRegex(DataValidationError, "invalid_market"):
            load_ohlcv_csv(csv_path)

        invalid_json = json.dumps(
            [
                {
                    "symbol": "SAMPLE",
                    "market": "EU",
                    "timestamp": "2026-01-05T09:00:00-05:00",
                    "source": "synthetic-test-fixture",
                    "event_type": "earnings_related_volatility",
                    "headline": "bad market",
                    "severity": "medium",
                    "notes": "bad market for validation",
                }
            ]
        )
        json_path = self._write_temp_file("events.json", invalid_json)
        with self.assertRaisesRegex(DataValidationError, "invalid_market"):
            load_news_events(json_path)

    def test_invalid_timezone_is_rejected(self) -> None:
        invalid_csv = """symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume
SAMPLE,US,5m,2026-01-05T09:30:00,Invalid/Zone,100.00,101.20,99.80,100.90,120000
"""

        path = self._write_temp_file("bars.csv", invalid_csv)
        with self.assertRaisesRegex(DataValidationError, "invalid_timezone"):
            load_ohlcv_csv(path)

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
        self.assertIsInstance(snapshot[0].bar, OhlcvRow)
        self.assertTrue(hasattr(snapshot[0].bar, "identity_key"))

    def test_validation_error_exposes_structured_issues(self) -> None:
        invalid_csv = """symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume
SAMPLE,US,5m,2026-01-05T09:30:00,America/New_York,100.00,99.00,98.80,100.90,120000
"""

        path = self._write_temp_file("bars.csv", invalid_csv)
        with self.assertRaises(DataValidationError) as ctx:
            load_ohlcv_csv(path)

        self.assertTrue(ctx.exception.issues)
        self.assertIsInstance(ctx.exception.issues[0], ValidationError)

    def test_aware_timestamp_is_normalized_to_declared_timezone(self) -> None:
        csv_payload = """symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume
SAMPLE,US,5m,2026-01-05T14:30:00+00:00,America/New_York,100.00,101.20,99.80,100.90,120000
"""

        csv_path = self._write_temp_file("bars.csv", csv_payload)
        bars = load_ohlcv_csv(csv_path)
        self.assertEqual(bars[0].timestamp.isoformat(), "2026-01-05T09:30:00-05:00")
        self.assertEqual(bars[0].timezone, "America/New_York")

    def _write_temp_file(self, filename: str, content: str) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="pat-data-pipeline-"))
        path = temp_dir / filename
        path.write_text(content, encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
