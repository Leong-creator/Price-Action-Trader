import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m12_29_current_day_scan_dashboard_lib import (
    MAINLINE_STRATEGIES,
    load_config,
    run_m12_29_current_day_scan_dashboard,
)


class M1229CurrentDayScanDashboardTest(unittest.TestCase):
    def run_stage(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        output_dir = Path(tmp.name) / "m12_29"
        config = replace(load_config(), output_dir=output_dir)
        result = run_m12_29_current_day_scan_dashboard(
            config,
            generated_at="2026-04-29T02:30:00Z",
            execute_fetch=False,
            refresh_quotes=False,
        )
        return config, result, output_dir

    def test_scan_date_rolls_to_current_us_trading_day(self):
        _, result, _ = self.run_stage()
        summary = result["summary"]
        self.assertEqual(summary["scan_date"], "2026-04-28")
        self.assertEqual(summary["stage"], "M12.29.current_day_scan_dashboard")
        self.assertIn("source_m12_12_candidate_count", summary)

    def test_strategy_closure_has_unique_plain_statuses(self):
        _, result, _ = self.run_stage()
        rows = result["strategy_closure_rows"]
        by_id = {row["strategy_id"]: row for row in rows}
        for strategy_id in [f"M10-PA-{idx:03d}" for idx in range(1, 17)]:
            self.assertIn(strategy_id, by_id)
            self.assertTrue(by_id[strategy_id]["final_status"])
        self.assertIn("M12-FTD-001", by_id)
        self.assertEqual({row["strategy_id"] for row in rows if row["daily_realtime_test"] == "true"} & set(MAINLINE_STRATEGIES), set(MAINLINE_STRATEGIES))
        self.assertEqual(by_id["M10-PA-004"]["final_status"], "观察队列：只做多版")
        self.assertEqual(by_id["M10-PA-004"]["return_percent"], "0.5530")
        self.assertEqual(by_id["M10-PA-005"]["final_status"], "研究项：定义仍弱")
        self.assertEqual(by_id["M10-PA-014"]["final_status"], "辅助规则")
        self.assertEqual(by_id["M10-PA-015"]["final_status"], "辅助规则")

    def test_visual_final_review_does_not_block_mainline(self):
        _, result, _ = self.run_stage()
        rows = result["visual_definition_rows"]
        self.assertEqual({row["needs_user_manual_review"] for row in rows}, {"false"})
        self.assertEqual({row["blocks_mainline"] for row in rows}, {"false"})
        by_id = {row["strategy_id"]: row for row in rows}
        self.assertEqual(by_id["M10-PA-008"]["final_status"], "观察队列")
        self.assertEqual(by_id["M10-PA-009"]["final_status"], "观察队列")

    def test_dashboard_is_chinese_readonly_and_gate_stays_closed(self):
        _, result, output_dir = self.run_stage()
        dashboard_path = output_dir / "m12_32_minute_readonly_dashboard.html"
        dashboard = json.loads((output_dir / "m12_32_minute_readonly_dashboard_data.json").read_text(encoding="utf-8"))
        html = dashboard_path.read_text(encoding="utf-8")
        self.assertIn("今日新机会", html)
        self.assertIn("盘中模拟盈亏", html)
        self.assertIn("最大回撤参考", html)
        self.assertIn("不接真实账户", html)
        self.assertEqual(dashboard["refresh_seconds"], 60)
        self.assertFalse(dashboard["trading_connection"])
        self.assertFalse(dashboard["real_money_actions"])
        self.assertFalse(dashboard["live_execution"])
        gate = result["gate_recheck"]
        self.assertFalse(gate["paper_trial_approval"])
        self.assertIn("还没满 10 个交易日", gate["plain_language_result"])

    def test_forbidden_runtime_terms_are_not_written(self):
        _, _, output_dir = self.run_stage()
        forbidden = ["PA-SC-", "SF-", "live-ready", "real_orders=true", "broker_connection=true", "order_id", "fill_id", "account_id", "cash_balance", "position_qty"]
        for path in output_dir.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in forbidden:
                self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
