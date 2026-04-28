from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_25_daily_observation_continuity_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1225DailyObservationContinuityTests(unittest.TestCase):
    def test_temp_run_keeps_day_count_when_source_day_is_not_new(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_25_daily_observation_continuity(
                generated_at="2026-04-28T12:00:00Z",
                output_dir=Path(tmp),
            )

        self.assertEqual(summary["day_count_recorded"], 1)
        self.assertEqual(summary["days_remaining_for_paper_trial_review"], 9)
        self.assertFalse(summary["paper_trial_review_ready"])
        self.assertEqual(set(summary["mainline_strategy_scope"]), {"M10-PA-001", "M10-PA-002", "M10-PA-012", "M12-FTD-001"})
        self.assertEqual(summary["observation_only_strategy_scope"], ["M10-PA-007"])
        self.assertEqual(summary["excluded_from_daily_observation"], ["M10-PA-004"])
        self.assertFalse(summary["paper_trading_approval"])

    def test_checked_in_outputs_add_pa007_without_adding_pa004_to_daily_observation(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_25_daily_observation_continuity.py before full validation")
        expected = {
            "m12_25_daily_observation_continuity_summary.json",
            "m12_25_daily_observation_ledger.jsonl",
            "m12_25_dashboard_snapshot.json",
            "m12_25_dashboard_snapshot.html",
            "m12_25_today_trade_details.csv",
            "m12_25_observation_day_counter.json",
            "m12_25_strategy_observation_queue.json",
            "m12_25_strategy_observation_queue.csv",
            "m12_25_daily_client_report.md",
            "m12_25_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_25_daily_observation_continuity_summary.json").read_text(encoding="utf-8"))
        queue = {row["strategy_id"]: row for row in summary["observation_queue"]}
        self.assertEqual(queue["M10-PA-007"]["queue"], "新增观察队列")
        self.assertEqual(queue["M10-PA-007"]["today_in_dashboard"], "false")
        self.assertEqual(queue["M10-PA-007"]["paper_trial_candidate_now"], "false")
        self.assertEqual(queue["M10-PA-004"]["queue"], "不进入每日观察")
        self.assertEqual(queue["M10-PA-004"]["status"], "保留图形研究")
        self.assertNotIn("M10-PA-004", summary["mainline_strategy_scope"])
        self.assertNotIn("M10-PA-007", summary["mainline_strategy_scope"])

    def test_dashboard_prioritizes_client_metrics_and_uses_chinese_copy(self) -> None:
        snapshot = json.loads((OUTPUT_DIR / "m12_25_dashboard_snapshot.json").read_text(encoding="utf-8"))
        for label in ("今日机会", "今日估算盈亏", "今日估算收益率", "FTD增强版历史胜率", "FTD增强版最大回撤", "连续记录天数", "观察中策略数"):
            self.assertIn(label, snapshot["homepage_metrics"])
        html = (OUTPUT_DIR / "m12_25_dashboard_snapshot.html").read_text(encoding="utf-8")
        for expected_text in ("每日只读测试看板", "今日机会", "今日估算盈亏", "胜率", "最大回撤", "策略队列", "模拟盈亏"):
            self.assertIn(expected_text, html)
        all_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in OUTPUT_DIR.glob("*") if path.is_file())
        for forbidden in ("live-ready", "real_orders=true", "broker_connection=true", "order_id", "fill_id", "account_id"):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
