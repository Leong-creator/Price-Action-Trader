from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import m12_28_trading_session_dashboard_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1228TradingSessionDashboardTests(unittest.TestCase):
    def test_temp_run_builds_readonly_session_dashboard_with_pa004_long(self) -> None:
        config = MODULE.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            dashboard = MODULE.run_m12_28_trading_session_dashboard(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T14:44:30Z",
                refresh_quotes=False,
            )

        summary = dashboard["summary"]
        self.assertEqual(dashboard["stage"], "M12.28.trading_session_dashboard")
        self.assertFalse(dashboard["paper_trading_approval"])
        self.assertFalse(dashboard["trading_connection"])
        self.assertFalse(dashboard["real_money_actions"])
        self.assertFalse(dashboard["live_execution"])
        self.assertGreater(summary["mainline_opportunity_count"], 0)
        self.assertGreater(summary["pa004_long_observation_count"], 0)
        self.assertEqual(summary["candidate_quote_time_alignment"], "live_quote_overlay_on_prior_candidate_set")
        self.assertFalse(summary["current_day_scanner_complete"])
        self.assertIn("上一轮 M12.12 扫描", summary["candidate_source_warning"])
        self.assertEqual(summary["quote_market_date"], "2026-04-28")
        self.assertEqual({row["variant_id"] for row in dashboard["pa004_long_observation_rows"]}, {"pa004_long_only_observation"})
        self.assertEqual({row["direction"] for row in dashboard["pa004_long_observation_rows"]}, {"看涨"})

    def test_generated_outputs_are_chinese_and_warn_about_prior_candidates(self) -> None:
        config = MODULE.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            MODULE.run_m12_28_trading_session_dashboard(
                replace(config, output_dir=output_dir),
                generated_at="2026-04-28T14:44:30Z",
                refresh_quotes=False,
            )

            html = (output_dir / "m12_28_trading_session_dashboard.html").read_text(encoding="utf-8")
            report = (output_dir / "m12_28_session_report.md").read_text(encoding="utf-8")
            data = json.loads((output_dir / "m12_28_session_dashboard_data.json").read_text(encoding="utf-8"))
            handoff = (output_dir / "m12_28_handoff.md").read_text(encoding="utf-8")

        for expected in (
            "今日机会",
            "盘中模拟盈亏",
            "模拟收益率",
            "浮盈机会占比",
            "PA004 做多版状态",
            "重要提示",
            "只读行情 + 模拟盈亏",
        ):
            self.assertIn(expected, html)
        self.assertIn("当前主线候选日期", report)
        self.assertEqual(data["summary"]["candidate_quote_time_alignment"], "live_quote_overlay_on_prior_candidate_set")
        self.assertFalse(data["summary"]["current_day_scanner_complete"])
        self.assertIn("commands_run:", handoff)
        self.assertIn("tests_run:", handoff)
        self.assertIn("上一轮 M12.12 扫描", handoff)

    def test_pa004_lookback_days_filters_old_observation_events(self) -> None:
        config = MODULE.load_config()
        strict_config = replace(
            config,
            pa004_long_observation=replace(config.pa004_long_observation, lookback_days=1),
        )
        with tempfile.TemporaryDirectory() as tmp:
            dashboard = MODULE.run_m12_28_trading_session_dashboard(
                replace(strict_config, output_dir=Path(tmp)),
                generated_at="2026-04-28T14:44:30Z",
                refresh_quotes=False,
            )

        self.assertEqual(dashboard["pa004_long_observation_rows"], [])
        self.assertEqual(dashboard["summary"]["pa004_long_observation_count"], 0)

    def test_checked_in_outputs_keep_readonly_boundaries(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_28_trading_session_dashboard.py before full validation")
        expected = {
            "m12_28_session_dashboard_data.json",
            "m12_28_session_quote_manifest.json",
            "m12_28_session_trade_view.csv",
            "m12_28_pa004_long_observation.csv",
            "m12_28_trading_session_dashboard.html",
            "m12_28_session_report.md",
            "m12_28_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})

        dashboard = json.loads((OUTPUT_DIR / "m12_28_session_dashboard_data.json").read_text(encoding="utf-8"))
        self.assertEqual(dashboard["summary"]["candidate_quote_time_alignment"], "live_quote_overlay_on_prior_candidate_set")
        self.assertFalse(dashboard["paper_trading_approval"])
        self.assertFalse(dashboard["trading_connection"])
        self.assertFalse(dashboard["real_money_actions"])
        self.assertFalse(dashboard["live_execution"])

        combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in OUTPUT_DIR.glob("m12_28_*") if path.is_file())
        for forbidden in (
            "PA-SC-",
            "SF-",
            "live-ready",
            "real_orders=true",
            "broker_connection=true",
            "paper approval",
            "order_id",
            "fill_id",
            "account_id",
            "cash_balance",
            "position_qty",
        ):
            self.assertNotIn(forbidden.lower(), combined.lower())

    def test_config_rejects_trading_boundary_drift(self) -> None:
        config = MODULE.load_config()
        with self.assertRaises(ValueError):
            MODULE.validate_config(replace(config, boundary=replace(config.boundary, trading_connection=True)))
        with self.assertRaises(ValueError):
            MODULE.validate_config(replace(config, boundary=replace(config.boundary, real_money_actions=True)))
        with self.assertRaises(ValueError):
            MODULE.validate_config(replace(config, boundary=replace(config.boundary, live_execution=True)))
        with self.assertRaises(ValueError):
            MODULE.validate_config(replace(config, boundary=replace(config.boundary, paper_trading_approval=True)))


if __name__ == "__main__":
    unittest.main()
