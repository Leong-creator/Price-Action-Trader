import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from scripts.m12_29_current_day_scan_dashboard_lib import (
    DEFAULT_ACCOUNT_EQUITY,
    current_us_scan_date,
    load_config,
    run_m12_29_current_day_scan_dashboard,
)


class M1229CurrentDayScanDashboardTest(unittest.TestCase):
    def run_stage(self, *, output_dir: Path | None = None, generated_at: str = "2026-04-29T02:30:00Z"):
        temp_dir = None
        if output_dir is None:
            temp_dir = tempfile.TemporaryDirectory()
            self.addCleanup(temp_dir.cleanup)
            output_dir = Path(temp_dir.name) / "m12_29"
        config = replace(load_config(), output_dir=output_dir)
        result = run_m12_29_current_day_scan_dashboard(
            config,
            generated_at=generated_at,
            execute_fetch=False,
            refresh_quotes=False,
        )
        return config, result, output_dir

    def test_scan_date_rolls_to_current_us_trading_day(self):
        _, result, _ = self.run_stage()
        summary = result["summary"]
        self.assertEqual(summary["scan_date"], "2026-04-28")
        self.assertEqual(summary["stage"], "M12.46.accountized_realtime_testing")

    def test_scan_date_uses_prior_session_before_regular_open(self):
        self.assertEqual(current_us_scan_date("2026-04-29T12:00:00Z").isoformat(), "2026-04-28")
        self.assertEqual(current_us_scan_date("2026-04-29T14:00:00Z").isoformat(), "2026-04-29")

    def test_strategy_closure_reflects_mainline_experimental_and_supporting_lanes(self):
        _, result, _ = self.run_stage()
        rows = {row["strategy_id"]: row for row in result["strategy_closure_rows"] if not row["strategy_id"].startswith("M12-SRC-")}
        self.assertEqual(rows["M10-PA-004"]["final_status"], "主线正式账户：只做多版")
        self.assertEqual(rows["M10-PA-005"]["final_status"], "实验账户测试")
        self.assertEqual(rows["M10-PA-007"]["final_status"], "实验账户测试")
        self.assertEqual(rows["M10-PA-014"]["final_status"], "挂件 A/B")
        self.assertEqual(rows["M10-PA-010"]["final_status"], "研究项")
        self.assertEqual(rows["M12-FTD-001"]["final_status"], "主线正式账户")

    def test_dashboard_uses_20000_independent_accounts_and_1d_5m_only(self):
        _, result, output_dir = self.run_stage()
        dashboard = json.loads((output_dir / "m12_32_minute_readonly_dashboard_data.json").read_text(encoding="utf-8"))
        html = (output_dir / "m12_32_minute_readonly_dashboard.html").read_text(encoding="utf-8")
        self.assertEqual(dashboard["schema_version"], "m12.46.accountized-readonly-dashboard.v1")
        self.assertEqual(dashboard["timeframe_views"]["timeframe_order"], ["1d", "5m"])
        self.assertIn("主线正式账户", html)
        self.assertIn("实验账户", html)
        self.assertIn("FTD001 双版本对照", html)
        self.assertIn("信号观察清单", html)
        self.assertNotIn("1h 小时线测试", html)
        self.assertNotIn("15m 十五分钟测试", html)
        mainline = dashboard["mainline_account_view"]
        experimental = dashboard["experimental_account_view"]
        self.assertEqual(mainline["strategy_account_count"], "8")
        self.assertEqual(experimental["strategy_account_count"], "9")
        self.assertEqual(mainline["starting_capital"], "160000.00")
        self.assertEqual(experimental["starting_capital"], "180000.00")
        first_account = dashboard["mainline_accounts"][0]
        self.assertEqual(first_account["starting_capital"], "20000.00")
        self.assertEqual(Decimal(first_account["starting_capital"]), DEFAULT_ACCOUNT_EQUITY)

    def test_mainline_and_experimental_accounts_are_separated(self):
        _, result, _ = self.run_stage()
        dashboard = result["dashboard"]
        mainline_ids = {row["strategy_id"] for row in dashboard["mainline_accounts"]}
        experimental_ids = {row["strategy_id"] for row in dashboard["experimental_accounts"]}
        self.assertIn("M10-PA-004", mainline_ids)
        self.assertIn("M10-PA-005", experimental_ids)
        self.assertIn("M10-PA-007", experimental_ids)
        self.assertIn("M10-PA-013", experimental_ids)
        self.assertNotIn("M10-PA-005", mainline_ids)
        self.assertNotIn("M10-PA-004", experimental_ids)
        self.assertEqual(
            result["run_status"]["daily_realtime_strategy_ids"],
            ["M10-PA-001", "M10-PA-002", "M10-PA-004", "M10-PA-012", "M12-FTD-001"],
        )
        self.assertEqual(
            result["run_status"]["experimental_strategy_ids"],
            ["M10-PA-005", "M10-PA-007", "M10-PA-008", "M10-PA-009", "M10-PA-011", "M10-PA-013"],
        )
        self.assertEqual(
            result["gate_recheck"]["candidate_strategy_ids"],
            ["M10-PA-001", "M10-PA-002", "M10-PA-004", "M10-PA-012", "M12-FTD-001"],
        )

    def test_ftd_monitor_shows_baseline_and_loss_streak_guard(self):
        _, result, output_dir = self.run_stage()
        monitor = result["dashboard"]["ftd001_monitor"]
        self.assertEqual([row["variant_id"] for row in monitor["accounts"]], ["baseline", "loss_streak_guard"])
        self.assertIn("原版", monitor["plain_language_summary"])
        self.assertIn("连亏保护", monitor["plain_language_summary"])
        self.assertTrue((output_dir / "m12_36_ftd001_monitor.json").exists())
        self.assertTrue((output_dir / "m12_46_supporting_rule_ab_results.json").exists())

    def test_runtime_trade_view_and_detail_views_use_runtime_id_not_real_account_terms(self):
        _, result, output_dir = self.run_stage()
        dashboard = result["dashboard"]
        self.assertTrue(dashboard["trade_rows"])
        self.assertIn("runtime_id", dashboard["trade_rows"][0])
        self.assertNotIn("account_id", dashboard["trade_rows"][0])
        detail_views = dashboard["strategy_detail_views"]
        self.assertTrue(detail_views)
        first_key = next(iter(detail_views))
        self.assertTrue(first_key)
        text = (output_dir / "m12_29_trade_view.csv").read_text(encoding="utf-8")
        self.assertIn("runtime_id", text)
        self.assertNotIn("account_id", text)

    def test_observed_trading_days_accumulate_by_new_york_trading_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_29"
            self.run_stage(output_dir=output_dir, generated_at="2026-04-29T14:00:00Z")
            _, result_same_day, _ = self.run_stage(output_dir=output_dir, generated_at="2026-04-29T18:00:00Z")
            _, result_next_day, _ = self.run_stage(output_dir=output_dir, generated_at="2026-04-30T14:00:00Z")
        self.assertEqual(result_same_day["run_status"]["observed_trading_days"], 1)
        self.assertEqual(result_next_day["run_status"]["observed_trading_days"], 2)


if __name__ == "__main__":
    unittest.main()
