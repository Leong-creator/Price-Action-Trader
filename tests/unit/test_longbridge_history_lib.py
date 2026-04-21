from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "longbridge_history_lib.py"
SPEC = importlib.util.spec_from_file_location("longbridge_history_lib", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LongbridgeHistoryLibTests(unittest.TestCase):
    def test_build_symbol_uses_market_suffix(self) -> None:
        self.assertEqual(MODULE.build_longbridge_symbol(ticker="SPY", market="US"), "SPY.US")
        self.assertEqual(MODULE.build_longbridge_symbol(ticker="TSLA.US", market="US"), "TSLA.US")

    def test_fetch_intraday_rows_chunks_one_minute_requests_and_converts_timezone(self) -> None:
        responses = [
            _completed_process(
                [
                    {
                        "time": "2026-01-05 15:30:00",
                        "open": "100.0",
                        "high": "101.0",
                        "low": "99.5",
                        "close": "100.5",
                        "volume": "1000",
                        "turnover": "100500",
                    }
                ]
            ),
            _completed_process(
                [
                    {
                        "time": "2026-01-06 15:31:00",
                        "open": "100.5",
                        "high": "101.2",
                        "low": "100.1",
                        "close": "101.0",
                        "volume": "1200",
                        "turnover": "121200",
                    }
                ]
            ),
        ]
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/longbridge"),
            mock.patch.object(MODULE.subprocess, "run", side_effect=responses) as run_mock,
        ):
            rows = MODULE.fetch_longbridge_intraday_history_rows(
                ticker="SPY",
                symbol="SPY",
                market="US",
                timezone_name="America/New_York",
                start=date.fromisoformat("2026-01-05"),
                end=date.fromisoformat("2026-01-06"),
                interval="1m",
                allow_extended_hours=False,
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["timestamp"], "2026-01-05T10:30:00")
        self.assertEqual(rows[1]["timestamp"], "2026-01-06T10:31:00")
        self.assertEqual(rows[0]["timezone"], "America/New_York")
        self.assertEqual(run_mock.call_count, 2)
        first_command = run_mock.call_args_list[0].args[0]
        second_command = run_mock.call_args_list[1].args[0]
        self.assertIn("--session", first_command)
        self.assertEqual(first_command[first_command.index("--session") + 1], "intraday")
        self.assertEqual(first_command[first_command.index("--start") + 1], "2026-01-05")
        self.assertEqual(second_command[second_command.index("--start") + 1], "2026-01-06")

    def test_fetch_daily_rows_builds_repo_schema(self) -> None:
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/longbridge"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                return_value=_completed_process(
                    [
                        {
                            "time": "2026-01-05 00:00:00",
                            "open": "100.0",
                            "high": "101.0",
                            "low": "99.0",
                            "close": "100.5",
                            "volume": "500000",
                            "turnover": "50250000",
                        }
                    ]
                ),
            ),
        ):
            rows = MODULE.fetch_longbridge_daily_history_rows(
                ticker="SPY",
                symbol="SPY",
                market="US",
                timezone_name="America/New_York",
                start=date.fromisoformat("2026-01-05"),
                end=date.fromisoformat("2026-01-05"),
                interval="1d",
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["timeframe"], "1d")
        self.assertEqual(rows[0]["timestamp"], "2026-01-05T16:00:00-05:00")
        self.assertEqual(rows[0]["volume"], "500000")

    def test_missing_binary_raises_install_hint(self) -> None:
        with mock.patch.object(MODULE.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                MODULE.fetch_longbridge_daily_history_rows(
                    ticker="SPY",
                    symbol="SPY",
                    market="US",
                    timezone_name="America/New_York",
                    start=date.fromisoformat("2026-01-05"),
                    end=date.fromisoformat("2026-01-05"),
                    interval="1d",
                )

    def test_auth_error_raises_clear_hint(self) -> None:
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/longbridge"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                return_value=SimpleNamespace(
                    returncode=1,
                    stdout="",
                    stderr="authentication required",
                ),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "auth login"):
                MODULE.fetch_longbridge_daily_history_rows(
                    ticker="SPY",
                    symbol="SPY",
                    market="US",
                    timezone_name="America/New_York",
                    start=date.fromisoformat("2026-01-05"),
                    end=date.fromisoformat("2026-01-05"),
                    interval="1d",
                )


def _completed_process(payload: list[dict[str, str]]) -> SimpleNamespace:
    return SimpleNamespace(
        returncode=0,
        stdout=json.dumps(payload, ensure_ascii=False),
        stderr="",
    )
