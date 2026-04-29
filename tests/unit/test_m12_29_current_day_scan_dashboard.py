import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from scripts.m12_29_current_day_scan_dashboard_lib import (
    MAINLINE_STRATEGIES,
    current_us_scan_date,
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

    def test_scan_date_uses_prior_session_before_regular_open(self):
        self.assertEqual(current_us_scan_date("2026-04-29T12:00:00Z").isoformat(), "2026-04-28")
        self.assertEqual(current_us_scan_date("2026-04-29T14:00:00Z").isoformat(), "2026-04-29")

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
        self.assertIn("共享模拟账户", html)
        self.assertIn("策略成绩单", html)
        self.assertIn("单策略下钻", html)
        self.assertIn("今日机会明细", html)
        self.assertIn("最大回撤参考", html)
        self.assertIn("不接真实账户", html)
        self.assertEqual(dashboard["refresh_seconds"], 60)
        self.assertEqual(dashboard["dashboard_layout"]["home"], "共享模拟账户总览")
        self.assertIn("shared_account_view", dashboard)
        self.assertEqual(dashboard["shared_account_view"]["starting_capital"], "100000.00")
        self.assertTrue(dashboard["shared_account_view"]["account_purpose"].startswith("像一个真实模拟账户一样"))
        self.assertIn("strategy_scorecard_rows", dashboard)
        self.assertTrue(dashboard["strategy_scorecard_rows"])
        self.assertIn("strategy_detail_views", dashboard)
        by_strategy = {row["strategy_id"]: row for row in dashboard["strategy_scorecard_rows"]}
        self.assertFalse(any(strategy_id.startswith("M12-SRC-") for strategy_id in by_strategy))
        self.assertEqual(dashboard["top_metrics"]["策略可用数"], 4)
        self.assertEqual(dashboard["shared_account_view"]["strategy_count_daily_test"], 4)
        for strategy_id in MAINLINE_STRATEGIES:
            self.assertEqual(by_strategy[strategy_id]["current_status"], "每日测试")
        self.assertEqual(by_strategy["M10-PA-004"]["current_status"], "观察")
        self.assertEqual(by_strategy["M10-PA-004"]["historical_return_percent"], "0.5530")
        self.assertEqual(by_strategy["M10-PA-007"]["historical_return_percent"], "0.6473")
        self.assertEqual(by_strategy["M12-FTD-001"]["historical_return_percent"], "610.44")
        for key in ["historical_profit_factor", "historical_net_profit", "historical_final_equity", "historical_best_symbol", "historical_worst_symbol"]:
            self.assertIn(key, by_strategy["M10-PA-001"])
        self.assertFalse(dashboard["trading_connection"])
        self.assertFalse(dashboard["real_money_actions"])
        self.assertFalse(dashboard["live_execution"])
        gate = result["gate_recheck"]
        self.assertFalse(gate["paper_trial_approval"])
        self.assertIn("还没满 10 个交易日", gate["plain_language_result"])
        self.assertEqual(gate["candidate_strategy_ids"], list(MAINLINE_STRATEGIES))
        self.assertEqual(result["run_status"]["daily_realtime_strategy_ids"], list(MAINLINE_STRATEGIES))
        self.assertFalse(any(strategy_id.startswith("M12-SRC-") for strategy_id in gate["candidate_strategy_ids"]))

    def test_dashboard_account_strategy_and_detail_views_are_consistent(self):
        _, result, output_dir = self.run_stage()
        dashboard = json.loads((output_dir / "m12_32_minute_readonly_dashboard_data.json").read_text(encoding="utf-8"))
        summary = dashboard["summary"]
        account = dashboard["shared_account_view"]
        scorecards = dashboard["strategy_scorecard_rows"]
        total_pnl = Decimal(summary["total_simulated_pnl"])
        self.assertEqual(Decimal(account["current_equity"]), Decimal("100000.00") + total_pnl)
        self.assertEqual(
            sum(Decimal(row["simulated_pnl_today"]) for row in scorecards),
            total_pnl,
        )
        self.assertEqual(
            summary["visible_opportunity_count"],
            len(dashboard["trade_rows"]) + len(dashboard["pa004_long_rows"]),
        )
        detail_views = dashboard["strategy_detail_views"]
        self.assertEqual(set(detail_views), {row["strategy_id"] for row in scorecards})
        for row in scorecards:
            detail = detail_views[row["strategy_id"]]
            self.assertEqual(detail["summary"]["today_opportunity_count"], row["today_opportunity_count"])
            self.assertEqual(int(detail["summary"]["today_opportunity_count"]), len(detail["opportunity_rows"]))
        first_mainline_row = detail_views["M10-PA-012"]["opportunity_rows"][0]
        for key in ["candidate_status", "queue_action", "risk_level", "spec_ref", "data_path", "data_lineage", "source_refs"]:
            self.assertIn(key, first_mainline_row)
        first_pa004_row = detail_views["M10-PA-004"]["opportunity_rows"][0]
        self.assertEqual(first_pa004_row["variant_id"], "pa004_long_only_observation")

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
