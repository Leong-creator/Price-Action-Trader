from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests._intraday_support import build_session_rows, write_intraday_csv, write_metadata


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "intraday_pilot_lib.py"
SPEC = importlib.util.spec_from_file_location("intraday_pilot_lib_reliability", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class IntradayPilotReliabilityTests(unittest.TestCase):
    def test_intraday_pilot_run_generates_required_outputs_from_cached_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            config_path = temp_root / "intraday.json"
            config_path.write_text(
                json.dumps(
                    {
                        "title": "Intraday Fixture Pilot",
                        "description": "Fixture-backed intraday pilot.",
                        "start": "2026-01-05",
                        "end": "2026-01-06",
                        "interval": "15m",
                        "cache_dir": str(temp_root / "cache"),
                        "report_dir": str(temp_root / "reports"),
                        "source_order": ["yfinance"],
                        "instrument": {
                            "ticker": "SPY",
                            "symbol": "SPY",
                            "label": "SPDR S&P 500 ETF",
                            "market": "US",
                            "timezone": "America/New_York",
                            "demo_role": "fixture"
                        },
                        "risk": {
                            "starting_capital": "25000",
                            "risk_per_trade": "100",
                            "max_total_exposure": "25000",
                            "max_symbol_exposure_ratio": "1.00",
                            "max_daily_loss": "1000",
                            "max_consecutive_losses": 4
                        },
                        "session": {
                            "timezone": "America/New_York",
                            "regular_open": "09:30",
                            "regular_close": "16:00",
                            "expected_bars_per_session": 26,
                            "allow_extended_hours": False
                        },
                        "costs": {
                            "slippage_bps": "2",
                            "fee_per_order": "0"
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = MODULE.load_intraday_pilot_config(config_path)
            cache_path = MODULE.build_intraday_cache_path(config, source="yfinance")
            rows = build_session_rows(date.fromisoformat("2026-01-05")) + build_session_rows(
                date.fromisoformat("2026-01-06"),
                start_price="110",
            )
            write_intraday_csv(cache_path, rows)
            write_metadata(cache_path.with_suffix(".metadata.json"), source="fixture", row_count=len(rows))

            outcome = MODULE.create_intraday_pilot_run(
                config,
                refresh_data=False,
                run_id="intraday_fixture",
            )
            report_dir = Path(outcome["report_dir"])

            self.assertTrue((report_dir / "summary.json").exists())
            self.assertTrue((report_dir / "session_summary.json").exists())
            self.assertTrue((report_dir / "session_quality.json").exists())
            self.assertTrue((report_dir / "knowledge_trace_coverage.json").exists())
            self.assertTrue((report_dir / "knowledge_trace.json").exists())
            self.assertTrue((report_dir / "no_trade_wait.jsonl").exists())
            self.assertTrue((report_dir / "trades.csv").exists())
            self.assertTrue((report_dir / "report.md").exists())

            summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
            session_summary = json.loads((report_dir / "session_summary.json").read_text(encoding="utf-8"))
            session_quality = json.loads((report_dir / "session_quality.json").read_text(encoding="utf-8"))
            report_text = (report_dir / "report.md").read_text(encoding="utf-8")

            self.assertEqual(summary["boundary"], "paper/simulated")
            self.assertEqual(summary["symbol"], "SPY")
            self.assertEqual(summary["interval"], "15m")
            self.assertEqual(summary["session_count"], 2)
            self.assertEqual(session_quality["overall"]["complete_sessions"], 2)
            self.assertEqual(len(session_summary["sessions"]), 2)
            self.assertIn("paper / simulated", report_text)
            self.assertIn("当前仍未进入期权、broker、live、real-money", report_text)

    def test_incomplete_session_is_skipped_and_logged_as_no_trade_wait(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            config_path = temp_root / "intraday.json"
            config_path.write_text(
                json.dumps(
                    {
                        "title": "Intraday Incomplete Fixture",
                        "description": "Fixture-backed incomplete-session audit.",
                        "start": "2026-01-05",
                        "end": "2026-01-06",
                        "interval": "15m",
                        "cache_dir": str(temp_root / "cache"),
                        "report_dir": str(temp_root / "reports"),
                        "source_order": ["yfinance"],
                        "instrument": {
                            "ticker": "SPY",
                            "symbol": "SPY",
                            "label": "SPDR S&P 500 ETF",
                            "market": "US",
                            "timezone": "America/New_York",
                            "demo_role": "fixture"
                        },
                        "risk": {
                            "starting_capital": "25000",
                            "risk_per_trade": "100",
                            "max_total_exposure": "25000",
                            "max_symbol_exposure_ratio": "1.00",
                            "max_daily_loss": "1000",
                            "max_consecutive_losses": 4
                        },
                        "session": {
                            "timezone": "America/New_York",
                            "regular_open": "09:30",
                            "regular_close": "16:00",
                            "expected_bars_per_session": 26,
                            "allow_extended_hours": False
                        },
                        "costs": {
                            "slippage_bps": "2",
                            "fee_per_order": "0"
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = MODULE.load_intraday_pilot_config(config_path)
            cache_path = MODULE.build_intraday_cache_path(config, source="yfinance")
            rows = build_session_rows(date.fromisoformat("2026-01-05")) + build_session_rows(
                date.fromisoformat("2026-01-06"),
                drop_bar_at="11:00",
            )
            write_intraday_csv(cache_path, rows)
            write_metadata(cache_path.with_suffix(".metadata.json"), source="fixture", row_count=len(rows))

            outcome = MODULE.create_intraday_pilot_run(
                config,
                refresh_data=False,
                run_id="intraday_incomplete",
            )
            report_dir = Path(outcome["report_dir"])
            session_quality = json.loads((report_dir / "session_quality.json").read_text(encoding="utf-8"))
            session_summary = json.loads((report_dir / "session_summary.json").read_text(encoding="utf-8"))
            no_trade_lines = (report_dir / "no_trade_wait.jsonl").read_text(encoding="utf-8").splitlines()

            self.assertEqual(session_quality["overall"]["skipped_sessions"], 1)
            skipped = [item for item in session_summary["sessions"] if not item["used_for_pilot"]]
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0]["skipped_reason"], "data_gap_or_incomplete_session")
            self.assertTrue(
                any("data_gap_or_incomplete_session" in line for line in no_trade_lines)
            )


if __name__ == "__main__":
    unittest.main()
