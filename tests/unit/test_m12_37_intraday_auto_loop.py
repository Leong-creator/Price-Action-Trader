import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m12_29_current_day_scan_dashboard_lib import load_config as load_m12_29_config
from scripts.run_m12_37_intraday_auto_loop import (
    M1237AutoLoopConfig,
    load_auto_config,
    run_once,
)


class M1237IntradayAutoLoopTest(unittest.TestCase):
    def make_config(self, output_dir: Path) -> M1237AutoLoopConfig:
        source_config_path = output_dir / "m12_29_config.json"
        source_config_path.write_text(
            """
{
  "title": "M12.29 test",
  "run_id": "m12_29_current_day_scan_dashboard",
  "stage": "M12.29.current_day_scan_dashboard",
  "market": "US",
  "output_dir": "__OUTPUT_DIR__",
  "source_m12_12_config_path": "config/examples/m12_12_daily_observation_loop.json",
  "m12_16_source_candidate_plan_path": "reports/strategy_lab/m10_price_action_strategy_refresh/source_candidate_test_plan/m12_16/m12_16_source_candidate_test_plan.json",
  "m10_12_all_strategy_metrics_path": "reports/strategy_lab/m10_price_action_strategy_refresh/all_strategy_scorecard/m10_12/m10_12_all_strategy_metrics.csv",
  "m12_24_small_pilot_metrics_path": "reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_24_small_pilot/m12_24_pa004_pa007_metrics.csv",
  "m12_27_pa004_long_metrics_path": "reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_27_pa004_retest_live_snapshot/m12_27_pa004_retest_metrics.csv",
  "m12_15_best_variant_path": "reports/strategy_lab/m10_price_action_strategy_refresh/ftd_v02_ab_retest/m12_15/m12_15_best_variant.json",
  "dashboard_refresh_seconds": 60,
  "first_batch_size": 50,
  "min_observation_days_for_trial": 10,
  "boundary": {
    "paper_simulated_only": true,
    "trading_connection": false,
    "real_money_actions": false,
    "live_execution": false,
    "paper_trading_approval": false
  }
}
""".replace("__OUTPUT_DIR__", output_dir.as_posix()),
            encoding="utf-8",
        )
        config = load_auto_config()
        return replace(config, source_m12_29_config_path=source_config_path)

    def test_once_writes_runner_manifest_and_observer_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "m12_37"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = self.make_config(output_dir)
            outcome = run_once(
                config,
                generated_at="2026-04-29T02:30:00Z",
                execute_fetch=False,
                refresh_quotes=False,
            )
            manifest = outcome["manifest"]
            self.assertEqual(manifest["schema_version"], "m12.37.auto-runner-manifest.v1")
            self.assertEqual(manifest["refresh_seconds"], 60)
            self.assertEqual(manifest["observer_interval_minutes"], 15)
            self.assertFalse(manifest["loop_can_continue_now"])
            self.assertIn("主线权益", manifest["plain_language_result"])
            self.assertIn("FTD001", manifest["plain_language_result"])
            self.assertFalse(manifest["trading_connection"])
            self.assertFalse(manifest["real_money_actions"])
            self.assertFalse(manifest["live_execution"])
            self.assertTrue((output_dir / "m12_37_auto_runner_manifest.json").exists())
            self.assertTrue((output_dir / "m12_38_codex_observer_latest.json").exists())
            self.assertTrue((output_dir / "m12_38_codex_observer_inbox.jsonl").exists())

    def test_regular_session_manifest_allows_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "m12_37"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = self.make_config(output_dir)
            outcome = run_once(
                config,
                generated_at="2026-04-29T14:00:00Z",
                execute_fetch=False,
                refresh_quotes=False,
            )
            dashboard = outcome["result"]["dashboard"]
            self.assertEqual(outcome["manifest"]["market_session"]["status"], "美股常规交易时段")
            self.assertTrue(outcome["manifest"]["loop_can_continue_now"])
            self.assertEqual(dashboard["timeframe_views"]["timeframe_order"], ["1d", "5m"])
            self.assertEqual([row["variant_id"] for row in dashboard["ftd001_monitor"]["accounts"]], ["baseline", "loss_streak_guard"])


if __name__ == "__main__":
    unittest.main()
