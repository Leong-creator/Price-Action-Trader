import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import patch

from scripts.m12_29_current_day_scan_dashboard_lib import load_config as load_m12_29_config
from scripts.run_m12_37_intraday_auto_loop import (
    M1237AutoLoopConfig,
    load_auto_config,
    run_once,
    run_post_run_strategy_ledgers,
    session_refresh_policy,
    should_run_m14_finalization,
    validate_generated_at,
)


@dataclass(frozen=True, slots=True)
class FakeM13Config:
    output_dir: Path
    m12_29_output_dir: Path


@dataclass(frozen=True, slots=True)
class FakeM14Config:
    output_dir: Path
    m13_output_dir: Path
    m12_29_output_dir: Path


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
        return replace(
            config,
            source_m12_29_config_path=source_config_path,
            post_run_strategy_ledgers_enabled=False,
        )

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
            self.assertFalse(manifest["session_monitoring_active_now"])
            self.assertFalse(manifest["regular_session_active_now"])
            self.assertIn("主线权益", manifest["plain_language_result"])
            self.assertIn("FTD001", manifest["plain_language_result"])
            self.assertIn("休市快照", manifest["plain_language_result"])
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
            self.assertTrue(outcome["manifest"]["session_monitoring_active_now"])
            self.assertTrue(outcome["manifest"]["regular_session_active_now"])
            self.assertEqual(dashboard["timeframe_views"]["timeframe_order"], ["1d", "5m"])
            self.assertEqual([row["variant_id"] for row in dashboard["ftd001_monitor"]["accounts"]], ["baseline", "loss_streak_guard"])

    def test_session_refresh_policy_prefetches_preopen_and_fetches_only_on_5m_boundaries(self):
        premarket = session_refresh_policy("2026-04-29T13:25:00Z", "盘前", no_fetch=False, no_refresh_quotes=False)
        regular_boundary = session_refresh_policy("2026-04-29T14:00:00Z", "美股常规交易时段", no_fetch=False, no_refresh_quotes=False)
        regular_midbar = session_refresh_policy("2026-04-29T14:01:00Z", "美股常规交易时段", no_fetch=False, no_refresh_quotes=False)
        postmarket = session_refresh_policy("2026-04-29T20:30:00Z", "盘后", no_fetch=False, no_refresh_quotes=False)
        closed = session_refresh_policy("2026-04-29T01:00:00Z", "休市", no_fetch=False, no_refresh_quotes=False)
        self.assertTrue(premarket["execute_fetch"])
        self.assertTrue(premarket["refresh_quotes"])
        self.assertEqual(premarket["max_native_fetches"], 100)
        self.assertTrue(premarket["continue_session"])
        self.assertTrue(regular_boundary["execute_fetch"])
        self.assertTrue(regular_boundary["refresh_quotes"])
        self.assertEqual(regular_boundary["max_native_fetches"], 20)
        self.assertTrue(regular_boundary["continue_session"])
        self.assertFalse(regular_midbar["execute_fetch"])
        self.assertTrue(regular_midbar["refresh_quotes"])
        self.assertFalse(postmarket["execute_fetch"])
        self.assertTrue(postmarket["refresh_quotes"])
        self.assertTrue(postmarket["continue_session"])
        self.assertEqual(regular_midbar["max_native_fetches"], 0)
        self.assertFalse(closed["continue_session"])

    def test_m14_finalization_policy_waits_for_postmarket_by_default(self):
        degraded = {"current_day_runtime_ready": False}
        ready = {"current_day_runtime_ready": True}
        self.assertEqual(
            should_run_m14_finalization("postmarket_only", market_status="美股常规交易时段", m12_summary=ready),
            (False, "not_postmarket"),
        )
        self.assertEqual(
            should_run_m14_finalization("postmarket_only", market_status="盘后", m12_summary=degraded),
            (True, ""),
        )
        self.assertEqual(
            should_run_m14_finalization("postmarket_or_runtime_ready", market_status="美股常规交易时段", m12_summary=ready),
            (True, ""),
        )

    def test_post_run_strategy_ledgers_runs_m13_and_postmarket_m14(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "m12_37"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(
                self.make_config(output_dir),
                post_run_strategy_ledgers_enabled=True,
                post_run_m14_finalize_policy="postmarket_only",
                post_run_m13_config_path=Path(tmp) / "m13_config.json",
                post_run_m14_config_path=Path(tmp) / "m14_config.json",
            )
            fake_m13 = FakeM13Config(output_dir=Path(tmp) / "m13", m12_29_output_dir=Path("old_m12"))
            fake_m14 = FakeM14Config(
                output_dir=Path(tmp) / "m14",
                m13_output_dir=Path("old_m13"),
                m12_29_output_dir=Path("old_m12"),
            )

            with (
                patch("scripts.run_m12_37_intraday_auto_loop.load_m13_config", return_value=fake_m13),
                patch("scripts.run_m12_37_intraday_auto_loop.load_m14_config", return_value=fake_m14),
                patch("scripts.run_m12_37_intraday_auto_loop.run_m13_daily_strategy_test_runner") as run_m13,
                patch("scripts.run_m12_37_intraday_auto_loop.run_m14_strategy_challenge_gate") as run_m14,
            ):
                run_m13.return_value = {"goal_status": {"goal_complete": True}}
                run_m14.return_value = {"goal_status": {"goal_complete": False}}
                payload = run_post_run_strategy_ledgers(
                    config,
                    generated_at="2026-04-29T20:30:00Z",
                    trading_date="2026-04-29",
                    market_status="盘后",
                    m12_29_output_dir=output_dir,
                    m12_summary={"current_day_runtime_ready": False},
                )

            self.assertTrue(payload["m13_ran"])
            self.assertTrue(payload["m14_ran"])
            self.assertTrue(payload["m13_goal_complete"])
            self.assertFalse(payload["m14_goal_complete"])
            m13_config = run_m13.call_args.args[0]
            m14_config = run_m14.call_args.args[0]
            self.assertEqual(m13_config.m12_29_output_dir, output_dir)
            self.assertEqual(m14_config.m13_output_dir, fake_m13.output_dir)
            self.assertEqual(m14_config.m12_29_output_dir, output_dir)

    def test_post_run_strategy_ledgers_records_m13_failure_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "m12_37"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(
                self.make_config(output_dir),
                post_run_strategy_ledgers_enabled=True,
                post_run_m14_finalize_policy="postmarket_only",
            )
            fake_m13 = FakeM13Config(output_dir=Path(tmp) / "m13", m12_29_output_dir=Path("old_m12"))

            with (
                patch("scripts.run_m12_37_intraday_auto_loop.load_m13_config", return_value=fake_m13),
                patch(
                    "scripts.run_m12_37_intraday_auto_loop.run_m13_daily_strategy_test_runner",
                    side_effect=RuntimeError("ledger unavailable"),
                ),
            ):
                payload = run_post_run_strategy_ledgers(
                    config,
                    generated_at="2026-04-29T20:30:00Z",
                    trading_date="2026-04-29",
                    market_status="盘后",
                    m12_29_output_dir=output_dir,
                    m12_summary={"current_day_runtime_ready": False},
                )

            self.assertFalse(payload["m13_ran"])
            self.assertFalse(payload["m14_ran"])
            self.assertEqual(payload["m13_error_type"], "RuntimeError")
            self.assertEqual(payload["m13_error"], "ledger unavailable")
            self.assertEqual(payload["m14_skip_reason"], "m13_post_run_failed")

    def test_cli_generated_at_guard_rejects_future_timestamp(self):
        with self.assertRaises(ValueError):
            validate_generated_at("2999-01-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
