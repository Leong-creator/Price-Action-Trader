from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_17_daily_observation_continuity_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1217DailyObservationContinuityTests(unittest.TestCase):
    def test_temp_run_builds_first_continuity_day_without_paper_trial_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_17_daily_observation_continuity(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(tmp),
            )

        self.assertEqual(summary["day_count_recorded"], 1)
        self.assertEqual(summary["required_day_count_for_paper_trial_review"], 10)
        self.assertEqual(summary["days_remaining_for_paper_trial_review"], 9)
        self.assertEqual(summary["selected_ftd_variant"], "pullback_guard")
        self.assertEqual(set(summary["daily_strategy_scope"]), {"M10-PA-001", "M10-PA-002", "M10-PA-012", "M12-FTD-001"})
        self.assertFalse(summary["paper_trading_approval"])

    def test_checked_in_dashboard_prioritizes_client_metrics_and_no_real_trading_fields(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_17_daily_observation_continuity.py before full validation")
        expected = {
            "m12_17_daily_observation_continuity_summary.json",
            "m12_17_daily_observation_ledger.jsonl",
            "m12_17_dashboard_snapshot.json",
            "m12_17_dashboard_snapshot.html",
            "m12_17_today_trade_details.csv",
            "m12_17_observation_day_counter.json",
            "m12_17_daily_client_report.md",
            "m12_17_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_17_daily_observation_continuity_summary.json").read_text(encoding="utf-8"))
        snapshot = json.loads((OUTPUT_DIR / "m12_17_dashboard_snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["homepage_metrics"]["连续记录天数"], 1)
        for label in ("今日机会", "今日估算盈亏", "今日估算收益率", "FTD增强版历史收益率", "FTD增强版历史胜率", "FTD增强版最大回撤"):
            self.assertIn(label, snapshot["homepage_metrics"])
        self.assertEqual(summary["selected_ftd_variant"], "pullback_guard")
        html = (OUTPUT_DIR / "m12_17_dashboard_snapshot.html").read_text(encoding="utf-8")
        for expected_text in ("每日只读测试看板", "今日机会", "今日估算盈亏", "胜率", "最大回撤", "今日机会明细"):
            self.assertIn(expected_text, html)
        all_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in OUTPUT_DIR.glob("*") if path.is_file())
        for forbidden in ("live-ready", "real_orders=true", "broker_connection=true", "order_id", "fill_id", "account_id"):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
