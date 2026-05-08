import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from scripts.m12_29_current_day_scan_dashboard_lib import (
    ACCOUNT_SPECS,
    DEFAULT_ACCOUNT_EQUITY,
    advance_account_runtime,
    bootstrap_account_state,
    build_dashboard_data_freshness_warning,
    build_extended_session_monitor,
    build_accountized_run_status,
    current_us_scan_date,
    load_config,
    pa004_event_is_long,
    run_m12_29_current_day_scan_dashboard,
)
from scripts.run_m12_29_current_day_scan_dashboard import validate_generated_at


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

    def test_cli_generated_at_guard_rejects_future_timestamp(self):
        with self.assertRaises(ValueError):
            validate_generated_at("2999-01-01T00:00:00Z")

    def test_data_freshness_warning_marks_fallback_or_no_fetch_as_not_ready(self):
        warning = build_dashboard_data_freshness_warning(
            quote_source="fallback_quotes_only",
            current_day_runtime_ready=False,
            current_day_scan_complete=False,
            daily_ready_symbols=0,
            current_5m_ready_symbols=0,
            runtime_readiness_note="fixture",
        )
        self.assertIn("看板数据未刷新", warning)
        self.assertIn("fallback quotes / no-fetch", warning)
        self.assertEqual(
            build_dashboard_data_freshness_warning(
                quote_source="longbridge_quote_readonly",
                current_day_runtime_ready=True,
                current_day_scan_complete=True,
                daily_ready_symbols=50,
                current_5m_ready_symbols=50,
                runtime_readiness_note="ready",
            ),
            "",
        )

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
        self.assertIn("正式信号清单", html)
        self.assertIn("北京时间最后更新", html)
        self.assertIn("运行状态", html)
        self.assertIn("自动会话", html)
        self.assertIn("盘前 / 盘后异动", html)
        self.assertIn("看板新鲜度", html)
        self.assertNotIn("1h 小时线测试", html)
        self.assertNotIn("15m 十五分钟测试", html)
        mainline = dashboard["mainline_account_view"]
        experimental = dashboard["experimental_account_view"]
        self.assertEqual(mainline["strategy_account_count"], "8")
        self.assertEqual(experimental["strategy_account_count"], "8")
        self.assertEqual(mainline["starting_capital"], "160000.00")
        self.assertEqual(experimental["starting_capital"], "160000.00")
        first_account = dashboard["mainline_accounts"][0]
        self.assertEqual(first_account["starting_capital"], "20000.00")
        self.assertEqual(Decimal(first_account["starting_capital"]), DEFAULT_ACCOUNT_EQUITY)
        self.assertIn("CST", dashboard["update_status"]["beijing_time"])
        self.assertIn("session_liveness", dashboard["update_status"])
        self.assertIn("freshness_state", dashboard["update_status"])

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

    def test_pa004_mainline_uses_formal_detector_input_and_reference_rows_stay_outside_runtime_watchlist(self):
        _, result, output_dir = self.run_stage()
        dashboard = result["dashboard"]
        audit_rows = {row["runtime_id"]: row for row in dashboard["account_input_audit"]["rows"]}
        self.assertEqual(audit_rows["M10-PA-004-long-1d"]["input_source_type"], "formal_detector_entry")
        self.assertEqual(audit_rows["M10-PA-004-long-1d"]["formal_input_stream"], "true")
        runtime_watchlist = dashboard["signal_watchlist"]
        self.assertTrue(all(row.get("signal_source_type") != "reference_observation" for row in runtime_watchlist))
        self.assertTrue(all("观察版" not in row.get("review_status", "") for row in runtime_watchlist if row["strategy_id"] == "M10-PA-004"))
        reference_watchlist = dashboard["reference_watchlist"]
        self.assertTrue(all(row.get("signal_source_type") == "reference_observation" for row in reference_watchlist))
        audit_path = output_dir / "m12_46_account_input_audit.json"
        self.assertTrue(audit_path.exists())

    def test_pa004_formal_detector_accepts_chinese_and_english_long_direction(self):
        self.assertTrue(pa004_event_is_long({"direction": "long"}))
        self.assertTrue(pa004_event_is_long({"direction": "看涨"}))
        self.assertFalse(pa004_event_is_long({"direction": "short"}))
        self.assertFalse(pa004_event_is_long({"direction": "看跌"}))

    def test_all_runtime_accounts_are_marked_as_formal_input_streams(self):
        _, result, _ = self.run_stage()
        rows = result["dashboard"]["account_input_audit"]["rows"]
        self.assertEqual(len(rows), len(ACCOUNT_SPECS))
        self.assertTrue(all(row["watchlist_only"] == "false" for row in rows))
        mainline_rows = [row for row in rows if row["lane"] == "mainline"]
        experimental_rows = [row for row in rows if row["lane"] == "experimental"]
        self.assertTrue(all(row["formal_input_stream"] == "true" for row in mainline_rows))
        self.assertTrue(all(row["current_scanner_connected"] == "true" for row in mainline_rows))
        self.assertTrue(all(row["formal_input_stream"] == "true" for row in experimental_rows))
        self.assertTrue(all(row["current_scanner_connected"] == "true" for row in experimental_rows))
        self.assertTrue(
            all(row["input_status"] in {"connected_with_signal_today", "connected_zero_signal_today"} for row in experimental_rows)
        )

    def test_postmarket_runtime_uses_postmarket_wording_and_runtime_ready_note(self):
        _, result, _ = self.run_stage(generated_at="2026-05-06T23:59:17Z")
        summary = result["summary"]
        dashboard = result["dashboard"]
        observer = dashboard["codex_observer"]
        self.assertEqual(summary["market_session"]["status"], "盘后")
        self.assertTrue(summary["current_day_runtime_ready"])
        self.assertIsInstance(summary["current_day_scan_complete"], bool)
        self.assertTrue(summary["runtime_readiness_note"])
        self.assertIn("盘后异动", summary["plain_language_result"])
        self.assertNotIn("盘前异动 6 条", observer["recommended_codex_message"])
        self.assertIn("盘后只读快照", observer["recommended_codex_message"])
        self.assertEqual(dashboard["extended_session_monitor"]["active_session"], "盘后")

    def test_observation_lane_does_not_claim_unwired_experimental_accounts_are_running(self):
        _, result, _ = self.run_stage()
        lane = result["dashboard"]["observation_test_lane"]
        self.assertIn("已接入正式输入流", lane["plain_language_result"])

    def test_observed_trading_days_accumulate_by_new_york_trading_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_29"
            self.run_stage(output_dir=output_dir, generated_at="2026-04-29T14:00:00Z")
            _, result_same_day, _ = self.run_stage(output_dir=output_dir, generated_at="2026-04-29T18:00:00Z")
            _, result_next_day, _ = self.run_stage(output_dir=output_dir, generated_at="2026-04-30T14:00:00Z")
        self.assertEqual(result_same_day["run_status"]["observed_trading_days"], 1)
        self.assertEqual(result_next_day["run_status"]["observed_trading_days"], 2)

    def test_success_then_degraded_rerun_does_not_roll_back_observed_trading_days(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_29"
            config, _, _ = self.run_stage(output_dir=output_dir, generated_at="2026-04-29T14:00:00Z")
            degraded_runtime = advance_account_runtime(
                config,
                generated_at="2026-04-29T18:00:00Z",
                scan_date=date.fromisoformat("2026-04-29"),
                trade_rows=[],
                pa004_formal_rows=[],
                closure_rows=[],
                current_day_runtime_ready=False,
            )
            state = json.loads((output_dir / "m12_46_account_runtime_state.json").read_text(encoding="utf-8"))
        self.assertEqual(build_accountized_run_status(config, degraded_runtime)["observed_trading_days"], 1)
        self.assertTrue(state["trading_day_registry"]["2026-04-29"]["counted"])
        self.assertFalse(state["trading_day_registry"]["2026-04-29"]["last_run_complete"])

    def test_today_closed_count_uses_new_york_trading_day_not_utc_calendar_day(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_29"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            spec = next(item for item in ACCOUNT_SPECS if item["account_id"] == "M10-PA-001-1d")
            account = bootstrap_account_state(spec)
            account["cash"] = "19000.00"
            account["open_positions"] = [
                {
                    "position_id": "manual-close-test",
                    "signal_id": "manual-close-test",
                    "strategy_id": spec["strategy_id"],
                    "runtime_id": spec["account_id"],
                    "display_name": spec["display_name"],
                    "lane": spec["lane"],
                    "timeframe": spec["timeframe"],
                    "symbol": "SPY",
                    "direction": "long",
                    "signal_time": "2026-04-28T19:30:00Z",
                    "signal_date": "2026-04-28",
                    "opened_at": "2026-04-28T19:35:00Z",
                    "entry_price": "100.00",
                    "stop_price": "97.00",
                    "target_price": "108.00",
                    "latest_price": "95.00",
                    "quantity": "10.0000",
                    "reserved_notional": "1000.00",
                    "current_pnl": "0.00",
                    "current_state": "持仓中",
                    "review_status": "test",
                    "risk_level": "medium",
                    "source_refs": "manual",
                    "spec_ref": "manual",
                }
            ]
            state = {
                "schema_version": "m12.46.account-runtime-state.v1",
                "stage": "M12.46.accountized_realtime_testing",
                "starting_capital": "20000.00",
                "risk_rate": "0.005",
                "accounts": {spec["account_id"]: account},
                "trading_day_registry": {},
            }
            (output_dir / "m12_46_account_runtime_state.json").write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            runtime = advance_account_runtime(
                config,
                generated_at="2026-04-29T01:05:00Z",
                scan_date=date.fromisoformat("2026-04-28"),
                trade_rows=[],
                pa004_formal_rows=[],
                closure_rows=[],
                current_day_runtime_ready=False,
            )
        row = next(item for item in runtime["account_rows"] if item["runtime_id"] == spec["account_id"])
        self.assertEqual(row["today_closed_count"], "1")
        self.assertEqual(row["today_realized_pnl"], "-50.00")
        self.assertEqual(row["today_total_pnl"], "-50.00")

    def test_extended_session_monitor_detects_premarket_and_postmarket_focus_movers(self):
        quotes = {
            "AMD": {
                "quote_source": "longbridge_quote_readonly",
                "quote_status": "Normal",
                "pre_market_last": "425.58",
                "pre_market_reference_close": "355.26",
                "pre_market_move_amount": "70.32",
                "pre_market_move_percent": "19.79",
                "pre_market_timestamp": "2026-05-06 11:00:45",
                "post_market_last": "414.00",
                "post_market_reference_close": "355.26",
                "post_market_move_amount": "58.74",
                "post_market_move_percent": "16.53",
                "post_market_timestamp": "2026-05-05 23:59:59",
            },
            "MU": {
                "quote_source": "longbridge_quote_readonly",
                "quote_status": "Normal",
                "pre_market_last": "675.72",
                "pre_market_reference_close": "640.20",
                "pre_market_move_amount": "35.52",
                "pre_market_move_percent": "5.55",
                "pre_market_timestamp": "2026-05-06 11:00:45",
            },
        }
        monitor = build_extended_session_monitor(quotes, "盘前")
        self.assertEqual(monitor["premarket_count"], 2)
        self.assertEqual(monitor["postmarket_count"], 1)
        self.assertEqual(monitor["active_session"], "盘前")
        self.assertGreaterEqual(monitor["focus_hit_count"], 2)
        self.assertIn("AMD", monitor["plain_language_summary"])

    def test_dashboard_includes_extended_session_monitor_from_live_quotes(self):
        live_quotes = {
            "AMD": {
                "symbol": "AMD",
                "latest_price": "355.26",
                "previous_close": "341.54",
                "open": "351.51",
                "high": "359.57",
                "low": "344.88",
                "volume": "64235117",
                "quote_status": "Normal",
                "quote_timestamp": "2026-05-06T14:00:00Z",
                "quote_source": "longbridge_quote_readonly",
                "pre_market_last": "425.58",
                "pre_market_reference_close": "355.26",
                "pre_market_move_amount": "70.32",
                "pre_market_move_percent": "19.79",
                "pre_market_timestamp": "2026-05-06 11:00:45",
            }
        }
        with patch("scripts.m12_29_current_day_scan_dashboard_lib.build_quotes", return_value=(live_quotes, {"quote_source": "longbridge_quote_readonly", "quote_count": 1})):
            _, result, output_dir = self.run_stage(generated_at="2026-05-06T14:00:00Z")
        monitor = result["dashboard"]["extended_session_monitor"]
        self.assertEqual(monitor["premarket_count"], 1)
        self.assertEqual(monitor["active_session"], "盘前")
        self.assertEqual(monitor["premarket_rows"][0]["symbol"], "AMD")
        self.assertTrue((output_dir / "m12_48_extended_session_monitor.json").exists())


if __name__ == "__main__":
    unittest.main()
