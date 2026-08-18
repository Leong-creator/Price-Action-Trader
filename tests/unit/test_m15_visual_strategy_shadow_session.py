from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.m15_visual_strategy_shadow_session_lib import load_config, run_visual_shadow_session


class VisualStrategyShadowSessionTest(unittest.TestCase):
    def test_production_shadow_session_follows_stable_147_realtime_universe(self) -> None:
        config = load_config()

        self.assertEqual(config.required_symbol_count, 147)
        self.assertTrue(config.universe_path.name.endswith("snapshot_147.json"))

    def write_fixture(
        self,
        root: Path,
        *,
        omit_last_msft_bar: bool = False,
        duplicate_aapl_bar: bool = False,
        source_mode: str = "longbridge_sdk_snapshot_poll",
        symbol_count: int = 2,
        expected_bars_per_symbol: int = 3,
    ) -> Path:
        universe_path = root / "universe.json"
        symbols = (
            ["AAPL", "MSFT"]
            if symbol_count == 2
            else [f"S{index:03d}" for index in range(symbol_count)]
        )
        universe_path.write_text(json.dumps({"symbols": symbols}), encoding="utf-8")

        rows: list[dict[str, object]] = []
        session_start = datetime(2026, 8, 4, 13, 35, tzinfo=UTC)
        for symbol_index, symbol in enumerate(symbols):
            base = 100 + symbol_index
            for offset in range(expected_bars_per_symbol):
                event_at = session_start + timedelta(minutes=offset * 5)
                if (
                    omit_last_msft_bar
                    and symbol == "MSFT"
                    and offset == expected_bars_per_symbol - 1
                ):
                    continue
                price = base + offset
                rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": "5m",
                        "event_time": event_at.isoformat().replace("+00:00", "Z"),
                        "bar_final": True,
                        "source_mode": source_mode,
                        "market_data_blocked_reason": "",
                        "open": str(price),
                        "high": str(price + 2),
                        "low": str(price - 1),
                        "close": str(price + 1),
                        "volume": "10",
                    }
                )
        if duplicate_aapl_bar:
            rows.append(dict(rows[0]))
        market_events_path = root / "events.jsonl"
        market_events_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

        shadow_config_path = root / "shadow.json"
        shadow_config_path.write_text(
            json.dumps(
                {
                    "stage": "M15.visual_strategy_shadow",
                    "contract": {"stage": "shadow-v1"},
                    "inputs": {"bars": market_events_path.as_posix()},
                    "state": {"path": (root / "shadow_state.json").as_posix(), "history_limit": 64},
                    "outputs": {
                        "audit_jsonl": (root / "audit.jsonl").as_posix(),
                        "run_summary": (root / "shadow_summary.json").as_posix(),
                    },
                    "detector": {
                        "channel_lookback": 12,
                        "trend_short_window": 3,
                        "trend_long_window": 6,
                    },
                    "hard_boundaries": {
                        "order_generation": False,
                        "broker_connection": False,
                        "real_orders": False,
                        "live_execution": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        config_path = root / "session.json"
        config_path.write_text(
            json.dumps(
                {
                    "stage": "M15.visual_strategy_shadow_session",
                    "inputs": {
                        "market_events": market_events_path.as_posix(),
                        "universe": universe_path.as_posix(),
                        "shadow_config": shadow_config_path.as_posix(),
                    },
                    "outputs": {
                        "session_ledger_jsonl": (root / "session_ledger.jsonl").as_posix(),
                        "session_summary_json": (root / "session_summary.json").as_posix(),
                        "aggregated_daily_bars_jsonl": (root / "daily.jsonl").as_posix(),
                    },
                    "session": {
                        "market_timezone": "America/New_York",
                        "regular_open_time": "09:30",
                        "regular_close_time": (
                            "16:00" if expected_bars_per_symbol == 78 else "09:45"
                        ),
                        "timeframe_minutes": 5,
                        "expected_bars_per_symbol": expected_bars_per_symbol,
                        "required_symbol_count": symbol_count,
                        "allowed_source_modes": ["longbridge_sdk_snapshot_poll"],
                    },
                    "hard_boundaries": {
                        "order_generation": False,
                        "broker_connection": False,
                        "real_orders": False,
                        "live_execution": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def test_full_300_symbol_regular_session_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(
                self.write_fixture(
                    root,
                    symbol_count=300,
                    expected_bars_per_symbol=78,
                )
            )

            result = run_visual_shadow_session(
                config,
                business_date="2026-08-04",
                generated_at="2026-08-04T20:15:00Z",
            )

            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["session_complete"])
            self.assertEqual(result["accepted_five_minute_bar_count"], 23_400)
            self.assertEqual(result["aggregated_daily_bar_count"], 300)
            self.assertEqual(result["shadow_accepted_daily_bar_count"], 300)

    def test_complete_sdk_session_aggregates_and_advances_shadow_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(self.write_fixture(root))

            first = run_visual_shadow_session(
                config,
                business_date="2026-08-04",
                generated_at="2026-08-04T20:15:00Z",
            )
            second = run_visual_shadow_session(
                config,
                business_date="2026-08-04",
                generated_at="2026-08-04T20:20:00Z",
            )

            self.assertEqual(first["status"], "completed")
            self.assertTrue(first["session_complete"])
            self.assertEqual(first["accepted_five_minute_bar_count"], 6)
            self.assertEqual(first["aggregated_daily_bar_count"], 2)
            self.assertEqual(first["shadow_accepted_daily_bar_count"], 2)
            self.assertEqual(second["status"], "already_completed")
            bars = [json.loads(line) for line in config.aggregated_daily_bars_path.read_text().splitlines()]
            aapl = next(row for row in bars if row["symbol"] == "AAPL")
            self.assertEqual(aapl["open"], "100")
            self.assertEqual(aapl["high"], "104")
            self.assertEqual(aapl["low"], "99")
            self.assertEqual(aapl["close"], "103")
            self.assertEqual(aapl["volume"], "30")

    def test_incomplete_session_is_blocked_without_advancing_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(self.write_fixture(root, omit_last_msft_bar=True))

            result = run_visual_shadow_session(
                config,
                business_date="2026-08-04",
                generated_at="2026-08-04T20:15:00Z",
            )

            self.assertEqual(result["status"], "blocked_incomplete_session")
            self.assertFalse(result["session_complete"])
            self.assertEqual(result["diagnostics"]["complete_symbol_count"], 1)
            self.assertEqual(result["expected_five_minute_bar_count"], 6)
            self.assertEqual(result["accepted_five_minute_bar_count"], 5)
            self.assertEqual(result["missing_five_minute_bar_count"], 1)
            self.assertEqual(result["incomplete_symbol_count"], 1)
            self.assertIn("2只标的", result["plain_language_result"])
            self.assertFalse((root / "shadow_state.json").exists())

    def test_duplicate_or_non_sdk_rows_are_fail_closed(self) -> None:
        for kwargs, diagnostic in (
            ({"duplicate_aapl_bar": True}, "duplicate_count"),
            ({"source_mode": "fallback_quotes"}, "invalid_source_count"),
        ):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                config = load_config(self.write_fixture(root, **kwargs))
                result = run_visual_shadow_session(
                    config,
                    business_date="2026-08-04",
                    generated_at="2026-08-04T20:15:00Z",
                )
                self.assertEqual(result["status"], "blocked_incomplete_session")
                self.assertGreater(result["diagnostics"][diagnostic], 0)

    def test_context_only_rows_do_not_invalidate_realtime_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(self.write_fixture(root))
            context_row = {
                "symbol": "AAPL",
                "timeframe": "5m",
                "event_time": "2026-08-04T13:35:00Z",
                "bar_final": True,
                "source_mode": "longbridge_sdk_intraday_context",
                "context_only": True,
                "market_data_blocked_reason": "",
                "open": "1",
                "high": "1",
                "low": "1",
                "close": "1",
                "volume": "1",
            }
            with config.market_events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(context_row) + "\n")

            result = run_visual_shadow_session(
                config,
                business_date="2026-08-04",
                generated_at="2026-08-04T20:15:00Z",
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result.get("diagnostics", {}).get("invalid_source_count", 0), 0)


if __name__ == "__main__":
    unittest.main()
