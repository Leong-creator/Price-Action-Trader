import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.run_m12_47_session_supervisor import (
    apply_dashboard_longbridge_overlay,
    apply_dashboard_status_overlay,
    active_refresh_timeout_for_step,
    artifact_refresh_age_seconds,
    build_failure_payload,
    build_status_payload,
    build_window_state,
    load_config,
    maybe_refresh_longbridge_account_state_for_dashboard,
    pid_path,
    print_status,
    read_json_if_exists,
    should_trip_failure_breaker,
    stale_dashboard_restart_reason,
    status_path,
    stop_existing_supervisor,
    sync_dashboard_status_overlay,
    sync_manifest_status_overlay,
)


class M1247SessionSupervisorTest(unittest.TestCase):
    def test_window_state_covers_preopen_regular_and_after_hours(self):
        config = load_config()
        preopen = build_window_state(config, "2026-05-05T13:26:00Z")
        regular = build_window_state(config, "2026-05-05T14:00:00Z")
        after = build_window_state(config, "2026-05-05T21:30:00Z")
        self.assertEqual(preopen["market_status"], "开盘前预热窗口")
        self.assertEqual(preopen["session_should_run"], "true")
        self.assertEqual(regular["market_status"], "美股常规交易时段")
        self.assertEqual(regular["session_should_run"], "true")
        self.assertEqual(after["market_status"], "收盘后收尾窗口")
        self.assertEqual(after["session_should_run"], "true")

    def test_window_state_skips_configured_market_holiday(self):
        config = load_config()
        phase = build_window_state(config, "2026-05-25T13:26:00Z")
        self.assertEqual(phase["market_status"], "非交易日等待")
        self.assertEqual(phase["market_holiday"], "true")
        self.assertEqual(phase["session_should_run"], "false")
        self.assertEqual(phase["next_session_start_new_york"], "2026-05-26 09:25:00 EDT")
        self.assertEqual(phase["next_session_start_beijing"], "2026-05-26 21:25:00 CST")

    def test_window_state_after_friday_skips_monday_holiday(self):
        config = load_config()
        phase = build_window_state(config, "2026-05-23T00:01:00Z")
        self.assertEqual(phase["market_status"], "等待下一交易日")
        self.assertEqual(phase["session_should_run"], "false")
        self.assertEqual(phase["next_session_start_new_york"], "2026-05-26 09:25:00 EDT")

    def test_stop_existing_supervisor_terminates_pidfile_and_discovered_sessions(self):
        config = load_config()
        with patch("scripts.run_m12_47_session_supervisor.read_existing_pid", return_value=101):
            with patch("scripts.run_m12_47_session_supervisor.process_alive", return_value=True):
                with patch("scripts.run_m12_47_session_supervisor.discover_child_session_pids", return_value=[202]):
                    with patch("scripts.run_m12_47_session_supervisor.discover_supervisor_pids", return_value=[303]):
                        with patch("scripts.run_m12_47_session_supervisor.terminate_pids", return_value=True) as terminate:
                            with patch("scripts.run_m12_47_session_supervisor.remove_pid_file") as remove_pid:
                                stopped = stop_existing_supervisor(config)

        self.assertTrue(stopped)
        terminate.assert_called_once_with([101, 202, 303])
        remove_pid.assert_called_once_with(config)

    def test_dashboard_status_overlay_marks_holiday_snapshot_audit_only(self):
        dashboard = {
            "generated_at": "2026-05-25T14:09:30Z",
            "summary": {
                "generated_at": "2026-05-25T14:09:30Z",
                "current_day_runtime_ready": True,
                "current_day_scan_complete": True,
                "data_freshness_warning": "",
                "plain_language_result": "第一批 50 只股票仍有缺口：日线 0/50，当日 5m 0/50。",
                "market_session": {
                    "status": "美股常规交易时段",
                    "new_york_time": "2026-05-25 10:09:30 EDT",
                    "beijing_time": "2026-05-25 22:09:30 CST",
                },
            },
            "update_status": {
                "market_status": "美股常规交易时段",
                "runtime_status": "交易时段自动运行中",
                "freshness_state": "fresh",
            },
            "top_metrics": {"运行状态": "交易时段自动运行中"},
            "broker_terminal_view": {
                "top_status": {
                    "market_status": "美股常规交易时段",
                    "fully_ready_for_trading_display": "true",
                }
            },
        }
        changed = apply_dashboard_status_overlay(
            dashboard,
            {
                "supervisor_generated_at": "2026-05-25T16:02:29Z",
                "market_status": "非交易日等待",
                "session_should_run": False,
                "child_running": False,
                "supervisor_process_alive": True,
                "new_york_time": "2026-05-25 12:02:29 EDT",
                "beijing_time": "2026-05-26 00:02:29 CST",
            },
            m14_context={
                "m13_goal_status": "complete",
                "m14_goal_status": "M14 effective challenge progress is 10/10.",
                "paper_trial_gate_approved_count": "3",
            },
        )
        self.assertTrue(changed)
        self.assertEqual(dashboard["update_status"]["market_status"], "非交易日等待")
        self.assertEqual(dashboard["summary"]["market_session"]["status"], "非交易日等待")
        self.assertFalse(dashboard["summary"]["current_day_runtime_ready"])
        self.assertEqual(dashboard["broker_terminal_view"]["top_status"]["fully_ready_for_trading_display"], "false")
        self.assertEqual(dashboard["summary"]["data_freshness_warning"], "")
        self.assertTrue(dashboard["summary"]["audit_only_snapshot"])
        self.assertIn("上一有效审计快照", dashboard["summary"]["audit_only_snapshot_note"])
        self.assertIn("当前不是新的交易日测试", dashboard["summary"]["plain_language_result"])
        self.assertNotIn("0/50", dashboard["summary"]["plain_language_result"])
        self.assertEqual(dashboard["top_metrics"]["数据快照状态"], "非交易日审计快照")
        self.assertEqual(dashboard["broker_terminal_view"]["top_status"]["audit_only_snapshot_note"], dashboard["summary"]["audit_only_snapshot_note"])
        self.assertEqual(
            dashboard["broker_terminal_view"]["top_status"]["m13_goal_status"],
            "audit_only_snapshot; last_m13_status=complete; not_counted_as_new_trading_day",
        )

    def test_dashboard_status_overlay_preserves_ready_flag_during_regular_session(self):
        dashboard = {
            "generated_at": "2026-05-26T14:09:30Z",
            "summary": {
                "generated_at": "2026-05-26T14:09:30Z",
                "current_day_runtime_ready": True,
                "current_day_scan_complete": True,
                "data_freshness_warning": "",
                "market_session": {"status": "美股常规交易时段"},
            },
            "update_status": {"market_status": "美股常规交易时段", "freshness_state": "fresh"},
            "top_metrics": {"运行状态": "交易时段自动运行中"},
            "broker_terminal_view": {"top_status": {"fully_ready_for_trading_display": "true"}},
        }
        with patch("scripts.run_m12_47_session_supervisor.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = datetime.fromisoformat("2026-05-26T14:09:30+00:00")
            mocked_datetime.fromisoformat = datetime.fromisoformat
            mocked_datetime.combine = datetime.combine
            changed = apply_dashboard_status_overlay(
                dashboard,
                {
                    "supervisor_generated_at": "2026-05-26T14:09:30Z",
                    "market_status": "美股常规交易时段",
                    "session_should_run": True,
                    "child_running": True,
                    "supervisor_process_alive": True,
                    "new_york_time": "2026-05-26 10:09:30 EDT",
                    "beijing_time": "2026-05-26 22:09:30 CST",
                },
            )
        self.assertTrue(changed)
        self.assertTrue(dashboard["summary"]["current_day_runtime_ready"])
        self.assertEqual(dashboard["broker_terminal_view"]["top_status"]["fully_ready_for_trading_display"], "true")
        self.assertEqual(dashboard["summary"]["data_freshness_warning"], "")
        self.assertFalse(dashboard["summary"]["audit_only_snapshot"])
        self.assertEqual(dashboard["top_metrics"]["数据快照状态"], "交易窗口刷新中")

    def test_dashboard_status_overlay_labels_preheat_wait_separately_from_holiday(self):
        dashboard = {
            "generated_at": "2026-05-26T12:00:00Z",
            "summary": {
                "generated_at": "2026-05-26T12:00:00Z",
                "current_day_runtime_ready": True,
                "current_day_scan_complete": True,
                "data_freshness_warning": "",
                "market_session": {"status": "美股常规交易时段"},
            },
            "update_status": {"market_status": "美股常规交易时段", "freshness_state": "fresh"},
            "top_metrics": {"运行状态": "交易时段自动运行中"},
            "broker_terminal_view": {"top_status": {"fully_ready_for_trading_display": "true"}},
        }

        changed = apply_dashboard_status_overlay(
            dashboard,
            {
                "supervisor_generated_at": "2026-05-26T12:00:00Z",
                "market_status": "等待开盘前预热",
                "session_should_run": False,
                "child_running": False,
                "supervisor_process_alive": True,
                "new_york_time": "2026-05-26 08:00:00 EDT",
                "beijing_time": "2026-05-26 20:00:00 CST",
            },
        )

        self.assertTrue(changed)
        self.assertTrue(dashboard["summary"]["audit_only_snapshot"])
        self.assertEqual(
            dashboard["top_metrics"]["数据快照状态"],
            "等待开盘前预热：保留上一有效快照，未进入新交易日刷新窗口",
        )

    def test_dashboard_status_overlay_normalizes_longbridge_warning_backup(self):
        dashboard = {
            "generated_at": "2026-06-05T23:42:51Z",
            "summary": {
                "generated_at": "2026-06-05T23:42:51Z",
                "current_day_runtime_ready": True,
                "current_day_scan_complete": False,
                "data_freshness_warning": (
                    "看板已生成但数据源降级 / fallback quotes / no-fetch："
                    "quote_source=longbridge_quote_readonly，"
                    "current_day_runtime_ready=true，current_day_scan_complete=false。"
                ),
                "market_session": {"status": "美股常规交易时段"},
            },
            "update_status": {"market_status": "美股常规交易时段"},
            "top_metrics": {},
            "broker_terminal_view": {"top_status": {}},
        }

        changed = apply_dashboard_status_overlay(
            dashboard,
            {
                "supervisor_generated_at": "2026-06-06T05:33:13Z",
                "market_status": "非交易日等待",
                "session_should_run": False,
                "child_running": False,
                "supervisor_process_alive": True,
                "new_york_time": "2026-06-06 01:33:13 EDT",
                "beijing_time": "2026-06-06 13:33:13 CST",
            },
        )

        self.assertTrue(changed)
        self.assertEqual(dashboard["summary"]["data_freshness_warning"], "")
        self.assertIn("严格全量扫描口径未完成", dashboard["summary"]["data_freshness_warning_before_audit_overlay"])
        self.assertIn("长桥只读行情没有降级", dashboard["summary"]["data_freshness_warning_before_audit_overlay"])
        self.assertNotIn("数据源降级", dashboard["summary"]["data_freshness_warning_before_audit_overlay"])

    def test_dashboard_status_overlay_marks_regular_session_stale_dashboard(self):
        dashboard = {
            "generated_at": "2026-05-26T14:00:00Z",
            "summary": {
                "generated_at": "2026-05-26T14:00:00Z",
                "current_day_runtime_ready": True,
                "current_day_scan_complete": True,
                "data_freshness_warning": "",
                "market_session": {"status": "美股常规交易时段"},
            },
            "update_status": {
                "market_status": "美股常规交易时段",
                "freshness_state": "fresh",
                "stale_after_seconds": "600",
            },
            "top_metrics": {"运行状态": "交易时段自动运行中"},
            "broker_terminal_view": {"top_status": {"fully_ready_for_trading_display": "true"}},
        }
        with patch("scripts.run_m12_47_session_supervisor.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = datetime.fromisoformat("2026-05-26T14:20:30+00:00")
            mocked_datetime.fromisoformat = datetime.fromisoformat
            mocked_datetime.combine = datetime.combine
            changed = apply_dashboard_status_overlay(
                dashboard,
                {
                    "supervisor_generated_at": "2026-05-26T14:20:30Z",
                    "market_status": "美股常规交易时段",
                    "session_should_run": True,
                    "child_running": True,
                    "supervisor_process_alive": True,
                    "new_york_time": "2026-05-26 10:20:30 EDT",
                    "beijing_time": "2026-05-26 22:20:30 CST",
                },
            )

        self.assertTrue(changed)
        self.assertEqual(dashboard["update_status"]["freshness_state"], "stale")
        self.assertEqual(dashboard["update_status"]["dashboard_age_seconds"], "1230")
        self.assertIn("交易窗口刷新滞后", dashboard["top_metrics"]["数据快照状态"])
        self.assertTrue(dashboard["summary"]["current_day_runtime_ready"])

    def test_dashboard_status_overlay_marks_in_progress_refresh_without_faking_core_time(self):
        dashboard = {
            "generated_at": "2026-05-26T14:00:00Z",
            "summary": {
                "generated_at": "2026-05-26T14:00:00Z",
                "current_day_runtime_ready": True,
                "current_day_scan_complete": True,
                "data_freshness_warning": "",
                "market_session": {"status": "美股常规交易时段"},
            },
            "update_status": {
                "market_status": "美股常规交易时段",
                "freshness_state": "fresh",
                "stale_after_seconds": "600",
            },
            "top_metrics": {"运行状态": "交易时段自动运行中"},
            "broker_terminal_view": {"top_status": {"fully_ready_for_trading_display": "true"}},
        }
        with patch("scripts.run_m12_47_session_supervisor.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = datetime.fromisoformat("2026-05-26T14:20:30+00:00")
            mocked_datetime.fromisoformat = datetime.fromisoformat
            mocked_datetime.combine = datetime.combine
            changed = apply_dashboard_status_overlay(
                dashboard,
                {
                    "supervisor_generated_at": "2026-05-26T14:20:30Z",
                    "market_status": "美股常规交易时段",
                    "session_should_run": True,
                    "child_running": True,
                    "supervisor_process_alive": True,
                    "new_york_time": "2026-05-26 10:20:30 EDT",
                    "beijing_time": "2026-05-26 22:20:30 CST",
                    "m12_37_refresh_state": "refresh_in_progress",
                    "m12_37_refresh_started_at": "2026-05-26T14:18:30Z",
                    "m12_37_active_step": "m12_29_current_day_scan_dashboard",
                },
            )

        self.assertTrue(changed)
        self.assertEqual(dashboard["update_status"]["beijing_time"], "2026-05-26 22:00:00 CST")
        self.assertEqual(dashboard["update_status"]["freshness_state"], "refreshing")
        self.assertIn("正在刷新中", dashboard["top_metrics"]["数据快照状态"])
        self.assertEqual(dashboard["broker_terminal_view"]["top_status"]["m12_37_refresh_state"], "refresh_in_progress")

    def test_dashboard_status_overlay_marks_light_heartbeat(self):
        dashboard = {
            "generated_at": "2026-05-26T14:00:00Z",
            "summary": {
                "generated_at": "2026-05-26T14:00:00Z",
                "current_day_runtime_ready": True,
                "current_day_scan_complete": True,
                "data_freshness_warning": "",
                "market_session": {"status": "美股常规交易时段"},
            },
            "update_status": {
                "market_status": "美股常规交易时段",
                "freshness_state": "fresh",
                "stale_after_seconds": "600",
            },
            "top_metrics": {"运行状态": "交易时段自动运行中"},
            "broker_terminal_view": {"top_status": {"fully_ready_for_trading_display": "true"}},
        }
        with patch("scripts.run_m12_47_session_supervisor.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = datetime.fromisoformat("2026-05-26T14:03:30+00:00")
            mocked_datetime.fromisoformat = datetime.fromisoformat
            mocked_datetime.combine = datetime.combine
            changed = apply_dashboard_status_overlay(
                dashboard,
                {
                    "supervisor_generated_at": "2026-05-26T14:03:30Z",
                    "market_status": "美股常规交易时段",
                    "session_should_run": True,
                    "child_running": True,
                    "supervisor_process_alive": True,
                    "new_york_time": "2026-05-26 10:03:30 EDT",
                    "beijing_time": "2026-05-26 22:03:30 CST",
                    "m12_37_refresh_state": "light_heartbeat_waiting_next_5m_bar",
                    "m12_37_active_step": "light_heartbeat",
                },
            )

        self.assertTrue(changed)
        self.assertEqual(dashboard["update_status"]["freshness_state"], "light_heartbeat")
        self.assertIn("轻量心跳", dashboard["top_metrics"]["数据快照状态"])
        self.assertIn("等待下一根 5 分钟 K 线", dashboard["top_metrics"]["运行状态"])
        self.assertEqual(
            dashboard["broker_terminal_view"]["top_status"]["m12_37_refresh_state"],
            "light_heartbeat_waiting_next_5m_bar",
        )

    def test_dashboard_longbridge_overlay_updates_top_metrics_and_panel(self):
        dashboard = {"top_metrics": {"运行状态": "旧状态"}}
        apply_dashboard_longbridge_overlay(
            dashboard,
            {
                "schema_version": "m15.longbridge-paper-dashboard-panel.v1",
                "top_metric": "模拟账户已连接 / 1持仓 / 2挂单",
                "submit_ready_count": "3",
                "account_total_equity_estimate": "102375.57",
                "account_total_pnl_estimate": "基准未确认",
                "longbridge_account_total_pnl": "269.866",
                "longbridge_account_intraday_pnl": "12.34",
                "longbridge_account_today_total_pnl": "234.00",
                "longbridge_app_display_today_pnl": "等待长桥字段对齐",
                "longbridge_stock_total_pnl": "-154.18",
                "longbridge_symbol_win_rate_label": "38.46%",
                "longbridge_closed_trade_win_rate_label": "33.33%",
                "longbridge_max_drawdown_label": "10.00%",
                "longbridge_worst_symbol_loss_label": "-6.58%",
                "project_model_exposure_label": "4638.96 / 10000.00 (46.39%)",
                "real_money_actions": False,
                "live_execution": False,
            },
        )

        self.assertEqual(dashboard["top_metrics"]["长桥模拟账户"], "模拟账户已连接 / 1持仓 / 2挂单")
        self.assertNotIn("长桥可提交订单", dashboard["top_metrics"])
        self.assertEqual(dashboard["top_metrics"]["长桥账户总资产"], "102375.57")
        self.assertEqual(dashboard["top_metrics"]["长桥当前持仓总盈亏"], "269.866")
        self.assertEqual(dashboard["top_metrics"]["长桥账户当日盈亏"], "12.34")
        self.assertEqual(dashboard["top_metrics"]["长桥接口持仓今日浮动"], "234.00")
        self.assertEqual(dashboard["top_metrics"]["长桥交易累计盈亏"], "-154.18")
        self.assertNotIn("长桥当日总盈亏", dashboard["top_metrics"])
        self.assertNotIn("长桥App当日盈亏", dashboard["top_metrics"])
        self.assertNotIn("长桥账户总盈亏", dashboard["top_metrics"])
        self.assertNotIn("长桥今日盈亏", dashboard["top_metrics"])
        self.assertNotIn("长桥总盈亏", dashboard["top_metrics"])
        self.assertNotIn("长桥交易总盈亏", dashboard["top_metrics"])
        self.assertEqual(dashboard["top_metrics"]["长桥逐标的胜率"], "38.46%")
        self.assertEqual(dashboard["top_metrics"]["长桥交易胜率"], "33.33%")
        self.assertEqual(dashboard["top_metrics"]["长桥最大回撤"], "10.00%")
        self.assertNotIn("长桥回撤代理", dashboard["top_metrics"])
        self.assertEqual(dashboard["top_metrics"]["长桥项目资金占用"], "4638.96 / 10000.00 (46.39%)")
        self.assertEqual(dashboard["top_metrics"]["长桥本轮可新开仓"], "3")
        self.assertFalse(dashboard["longbridge_paper_account"]["real_money_actions"])
        self.assertFalse(dashboard["longbridge_paper_account"]["live_execution"])

    def test_maybe_refreshes_longbridge_account_state_when_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(load_config(), output_dir=Path(tmp) / "m12")
            submitter_config = SimpleNamespace(output_dir=Path(tmp) / "m15")

            with patch("scripts.run_m12_47_session_supervisor.load_m15_paper_submitter_config", return_value=submitter_config):
                with patch("scripts.run_m12_47_session_supervisor.artifact_refresh_age_seconds", return_value=999):
                    with patch("scripts.run_m12_47_session_supervisor.now_utc_iso", return_value="2026-06-04T15:00:01Z"):
                        with patch("scripts.run_m12_47_session_supervisor.refresh_paper_account_state", return_value={}) as refresh:
                            refreshed = maybe_refresh_longbridge_account_state_for_dashboard(
                                config,
                                {"supervisor_generated_at": "2026-06-04T15:00:00Z"},
                            )

        self.assertTrue(refreshed)
        refresh.assert_called_once_with(submitter_config, generated_at="2026-06-04T15:00:01Z")

    def test_refreshes_longbridge_account_state_when_generated_at_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            account_state_path = Path(tmp) / "account_state.json"
            account_state_path.write_text(json.dumps({"generated_at": "2026-06-04T14:00:00Z"}), encoding="utf-8")

            with patch("scripts.run_m12_47_session_supervisor.artifact_mtime_age_seconds", return_value=5):
                with patch("scripts.run_m12_47_session_supervisor.datetime") as mocked_datetime:
                    mocked_datetime.now.return_value.timestamp.return_value = 1_780_000_000
                    mocked_datetime.fromisoformat.return_value.timestamp.return_value = 1_779_999_000
                    age_seconds = artifact_refresh_age_seconds(account_state_path)

        self.assertEqual(age_seconds, 1000)

    def test_refresh_age_is_stale_when_generated_at_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            account_state_path = Path(tmp) / "account_state.json"
            account_state_path.write_text(json.dumps({"schema_version": "test"}), encoding="utf-8")

            with patch("scripts.run_m12_47_session_supervisor.artifact_mtime_age_seconds", return_value=5):
                age_seconds = artifact_refresh_age_seconds(account_state_path)

        self.assertEqual(age_seconds, 10**9)

    def test_partial_dashboard_json_does_not_crash_supervisor_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "m12"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            dashboard_path = output_dir / "m12_32_minute_readonly_dashboard_data.json"
            dashboard_path.write_text('{"generated_at": "2026-05-25T14:09:30Z", "summary": {"broken"', encoding="utf-8")

            self.assertEqual(read_json_if_exists(dashboard_path), {})
            self.assertEqual(artifact_refresh_age_seconds(dashboard_path), 10**9)
            changed = sync_dashboard_status_overlay(
                config,
                {
                    "supervisor_generated_at": "2026-05-25T16:02:29Z",
                    "market_status": "美股常规交易时段",
                    "session_should_run": True,
                    "child_running": True,
                    "supervisor_process_alive": True,
                },
            )

        self.assertFalse(changed)

    def test_read_json_if_exists_treats_loader_value_error_as_transient(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_path = Path(tmp) / "dashboard.json"
            dashboard_path.write_text('{"generated_at": "2026-05-25T14:09:30Z"}', encoding="utf-8")

            with patch("scripts.run_m12_47_session_supervisor.load_json", side_effect=ValueError("partial json")):
                self.assertEqual(read_json_if_exists(dashboard_path), {})

    def test_skips_longbridge_account_state_refresh_when_recent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(load_config(), output_dir=Path(tmp) / "m12")
            submitter_config = SimpleNamespace(output_dir=Path(tmp) / "m15")

            with patch("scripts.run_m12_47_session_supervisor.load_m15_paper_submitter_config", return_value=submitter_config):
                with patch("scripts.run_m12_47_session_supervisor.artifact_refresh_age_seconds", return_value=5):
                    with patch("scripts.run_m12_47_session_supervisor.refresh_paper_account_state", return_value={}) as refresh:
                        refreshed = maybe_refresh_longbridge_account_state_for_dashboard(
                            config,
                            {"supervisor_generated_at": "2026-06-04T15:00:00Z"},
                        )

        self.assertFalse(refreshed)
        refresh.assert_not_called()

    def test_dashboard_status_overlay_refreshes_m14_gate_context(self):
        dashboard = {
            "generated_at": "2026-05-26T14:09:30Z",
            "summary": {
                "generated_at": "2026-05-26T14:09:30Z",
                "current_day_runtime_ready": True,
                "current_day_scan_complete": True,
                "data_freshness_warning": "",
                "market_session": {"status": "美股常规交易时段"},
            },
            "update_status": {"market_status": "美股常规交易时段", "freshness_state": "fresh"},
            "top_metrics": {"运行状态": "交易时段自动运行中"},
            "broker_terminal_view": {
                "top_status": {
                    "m14_goal_status": "old",
                    "paper_trial_gate_approved_count": "0",
                    "fully_ready_for_trading_display": "true",
                },
                "strategy_accounts": [
                    {
                        "strategy_id": "M10-PA-004",
                        "m14_decision": "continue_testing",
                        "paper_trial_gate": "not_approved_pending",
                    },
                    {
                        "strategy_id": "M10-PA-012",
                        "m14_decision": "continue_testing",
                        "paper_trial_gate": "not_approved_pending",
                    },
                ],
                "pa004_comparison": {
                    "rows": [
                        {
                            "strategy_id": "M10-PA-004",
                            "m14_decision": "continue_testing",
                            "paper_trial_gate": "not_approved_pending",
                        }
                    ]
                },
            },
        }
        changed = apply_dashboard_status_overlay(
            dashboard,
            {
                "supervisor_generated_at": "2026-05-26T14:09:30Z",
                "market_status": "美股常规交易时段",
                "session_should_run": True,
                "child_running": True,
                "supervisor_process_alive": True,
                "new_york_time": "2026-05-26 10:09:30 EDT",
                "beijing_time": "2026-05-26 22:09:30 CST",
            },
            m14_context={
                "m13_goal_status": "complete",
                "m14_goal_status": "M14 effective challenge progress is 10/10. 3 strategies are approved.",
                "paper_trial_gate_approved_count": "3",
                "paper_gate_by_strategy": {
                    "M10-PA-004": {
                        "paper_trial_gate": "approved_internal_sim_only",
                        "gate_reason": "ten_day_positive_expectancy_internal_sim_candidate",
                    }
                },
                "decision_by_strategy": {
                    "M10-PA-004": {
                        "decision": "promote",
                        "decision_reason": "ten_day_positive_expectancy_internal_sim_candidate",
                    }
                },
            },
        )
        self.assertTrue(changed)
        terminal = dashboard["broker_terminal_view"]
        self.assertEqual(terminal["top_status"]["paper_trial_gate_approved_count"], "3")
        self.assertIn("10/10", terminal["top_status"]["m14_goal_status"])
        self.assertEqual(terminal["strategy_accounts"][0]["m14_decision"], "promote")
        self.assertEqual(terminal["strategy_accounts"][0]["paper_trial_gate"], "approved_internal_sim_only")
        self.assertEqual(terminal["strategy_accounts"][1]["m14_decision"], "continue_testing")
        self.assertEqual(terminal["pa004_comparison"]["rows"][0]["m14_decision"], "promote")
        self.assertEqual(terminal["pa004_comparison"]["rows"][0]["paper_trial_gate"], "approved_internal_sim_only")

    def test_status_payload_reads_latest_dashboard_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_47"
            output_dir.mkdir(parents=True, exist_ok=True)
            dashboard_path = output_dir / "m12_32_minute_readonly_dashboard_data.json"
            dashboard_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-05T17:15:30Z",
                        "update_status": {
                            "beijing_time": "2026-05-06 01:15:30 CST",
                            "runtime_status": "交易时段自动运行中，每 60 秒刷新报价，5m 收盘更新信号。",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = replace(load_config(), output_dir=output_dir)
            phase = build_window_state(config, "2026-05-05T17:16:00Z")
            payload = build_status_payload(
                config,
                phase=phase,
                supervisor_pid=123,
                supervisor_process_alive=True,
                child_pid=456,
                child_running=True,
                child_started_at="2026-05-05T13:25:00Z",
                child_last_exit_code=None,
                restart_count=0,
            )
        self.assertEqual(payload["latest_dashboard_generated_at"], "2026-05-05T17:15:30Z")
        self.assertEqual(payload["child_pid"], 456)
        self.assertTrue(payload["child_running"])
        self.assertTrue(payload["supervisor_process_alive"])
        self.assertIn("自动调度器正在运行", payload["plain_language_result"])

    def test_status_payload_marks_dead_supervisor_plainly(self):
        config = load_config()
        phase = build_window_state(config, "2026-05-05T14:00:00Z")
        payload = build_status_payload(
            config,
            phase=phase,
            supervisor_pid=999999,
            supervisor_process_alive=False,
            child_pid=None,
            child_running=False,
            child_started_at="",
            child_last_exit_code=None,
            restart_count=0,
        )
        self.assertFalse(payload["supervisor_process_alive"])
        self.assertIn("自动调度器没有运行", payload["plain_language_result"])

    def test_failure_breaker_trips_after_three_child_failures(self):
        config = load_config()
        phase = build_window_state(config, "2026-05-05T14:00:00Z")
        self.assertFalse(should_trip_failure_breaker(2))
        self.assertTrue(should_trip_failure_breaker(3))
        payload = build_failure_payload(
            config,
            phase=phase,
            consecutive_failures=3,
            child_last_exit_code=1,
        )
        self.assertIn("连续 3 次", payload["failure_reason"])
        self.assertFalse(payload["live_execution"])

    def test_stale_dashboard_restart_reason_detects_alive_child_without_refresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_47"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            (output_dir / "m12_32_minute_readonly_dashboard_data.json").write_text(
                json.dumps({"generated_at": "2026-05-05T14:00:00Z"}, ensure_ascii=False),
                encoding="utf-8",
            )
            phase = build_window_state(config, "2026-05-05T14:20:30Z")

            reason = stale_dashboard_restart_reason(config, phase, "2026-05-05T14:00:00Z")

        self.assertIn("dashboard_stale", reason)

    def test_stale_dashboard_restart_reason_respects_child_start_grace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_47"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            (output_dir / "m12_32_minute_readonly_dashboard_data.json").write_text(
                json.dumps({"generated_at": "2026-05-05T14:00:00Z"}, ensure_ascii=False),
                encoding="utf-8",
            )
            phase = build_window_state(config, "2026-05-05T14:20:30Z")

            reason = stale_dashboard_restart_reason(config, phase, "2026-05-05T14:18:00Z")

        self.assertEqual(reason, "")

    def test_stale_dashboard_restart_reason_ignores_cache_writes_when_dashboard_is_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_47"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            (output_dir / "m12_32_minute_readonly_dashboard_data.json").write_text(
                json.dumps({"generated_at": "2026-05-05T14:00:00Z"}, ensure_ascii=False),
                encoding="utf-8",
            )
            phase = build_window_state(config, "2026-05-05T14:20:30Z")

            with patch("scripts.run_m12_47_session_supervisor.child_has_recent_artifact_activity", return_value=True):
                reason = stale_dashboard_restart_reason(config, phase, "2026-05-05T14:00:00Z")

        self.assertIn("dashboard_stale", reason)

    def test_stale_dashboard_restart_reason_allows_active_refresh_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_47"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            (output_dir / "m12_32_minute_readonly_dashboard_data.json").write_text(
                json.dumps({"generated_at": "2026-05-05T14:00:00Z"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (output_dir / "m12_37_auto_runner_manifest.json").write_text(
                json.dumps(
                    {
                        "refresh_state": "refresh_in_progress",
                        "refresh_started_at": "2026-05-05T14:18:00Z",
                        "active_step": "m12_29_current_day_scan_dashboard",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            phase = build_window_state(config, "2026-05-05T14:25:30Z")

            reason = stale_dashboard_restart_reason(config, phase, "2026-05-05T14:17:30Z")

        self.assertEqual(reason, "")

    def test_stale_dashboard_restart_reason_allows_long_m1229_refresh_activity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_47"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            (output_dir / "m12_32_minute_readonly_dashboard_data.json").write_text(
                json.dumps({"generated_at": "2026-05-05T14:00:00Z"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (output_dir / "m12_37_auto_runner_manifest.json").write_text(
                json.dumps(
                    {
                        "refresh_state": "refresh_in_progress",
                        "refresh_started_at": "2026-05-05T14:10:00Z",
                        "active_step": "m12_29_current_day_scan_dashboard",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            phase = {
                "session_should_run": "true",
                "generated_at": "2026-05-05T15:05:00Z",
            }

            reason = stale_dashboard_restart_reason(config, phase, "2026-05-05T14:00:00Z")

        self.assertEqual(reason, "")

    def test_active_refresh_timeout_for_m1229_allows_full_universe_scan(self):
        self.assertGreaterEqual(active_refresh_timeout_for_step("m12_29_current_day_scan_dashboard", 60), 5400)
        self.assertEqual(active_refresh_timeout_for_step("unknown", 60), 1800)

    def test_print_status_persists_dead_supervisor_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_47"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            status_path(config).write_text(
                json.dumps(
                    {
                        "supervisor_pid": 999999,
                        "supervisor_process_alive": True,
                        "child_pid": 999998,
                        "child_running": True,
                        "child_started_at": "2026-05-05T13:25:00Z",
                        "child_last_exit_code": "",
                        "restart_count": 0,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch("sys.stdout", new=StringIO()):
                print_status(config)
            payload = json.loads(status_path(config).read_text(encoding="utf-8"))
        self.assertFalse(payload["supervisor_process_alive"])
        self.assertFalse(payload["child_running"])
        self.assertIn("自动调度器没有运行", payload["plain_language_result"])

    def test_print_status_prefers_live_pidfile_over_stale_status_pid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_47"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            status_path(config).write_text(
                json.dumps(
                    {
                        "supervisor_pid": 111,
                        "supervisor_process_alive": True,
                        "child_pid": 0,
                        "child_running": False,
                        "child_started_at": "",
                        "child_last_exit_code": "",
                        "restart_count": 0,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            pid_path(config).write_text("222", encoding="utf-8")
            with patch("scripts.run_m12_47_session_supervisor.process_alive", side_effect=lambda pid: pid == 222):
                with patch("sys.stdout", new=StringIO()):
                    print_status(config)
            payload = json.loads(status_path(config).read_text(encoding="utf-8"))

        self.assertEqual(payload["supervisor_pid"], 222)
        self.assertTrue(payload["supervisor_process_alive"])

    def test_print_status_reports_dashboard_timestamp_after_overlay(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_47"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            status_path(config).write_text(
                json.dumps(
                    {
                        "supervisor_pid": 999999,
                        "supervisor_process_alive": False,
                        "child_pid": 0,
                        "child_running": False,
                        "child_started_at": "",
                        "child_last_exit_code": "",
                        "restart_count": 0,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (output_dir / "m12_32_minute_readonly_dashboard_data.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-25T14:09:30Z",
                        "summary": {
                            "generated_at": "2026-05-25T14:09:30Z",
                            "current_day_runtime_ready": True,
                            "current_day_scan_complete": True,
                            "data_freshness_warning": "",
                            "market_session": {"status": "美股常规交易时段"},
                        },
                        "update_status": {"beijing_time": "old", "market_status": "美股常规交易时段"},
                        "top_metrics": {},
                        "broker_terminal_view": {"top_status": {"fully_ready_for_trading_display": "true"}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            phase = build_window_state(config, "2026-05-25T16:02:29Z")
            with patch("scripts.run_m12_47_session_supervisor.build_window_state", return_value=phase):
                with patch("sys.stdout", new=StringIO()):
                    print_status(config)
            payload = json.loads(status_path(config).read_text(encoding="utf-8"))
        self.assertEqual(payload["latest_dashboard_beijing_time"], "2026-05-25 22:09:30 CST")
        self.assertEqual(payload["latest_dashboard_runtime_status"], "非交易日等待，M12.37 不会启动；当前面板保留上一有效审计快照。")

    def test_non_trading_status_does_not_report_stale_refresh_in_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_47"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            (output_dir / "m12_32_minute_readonly_dashboard_data.json").write_text(
                json.dumps({"generated_at": "2026-06-05T23:42:51Z", "update_status": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (output_dir / "m12_37_auto_runner_manifest.json").write_text(
                json.dumps(
                    {
                        "refresh_state": "refresh_in_progress",
                        "refresh_started_at": "2026-06-05T23:57:52Z",
                        "active_step": "m12_29_current_day_scan_dashboard",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            phase = build_window_state(config, "2026-06-06T05:17:22Z")

            payload = build_status_payload(
                config,
                phase=phase,
                supervisor_pid=123,
                supervisor_process_alive=True,
                child_pid=None,
                child_running=False,
                child_started_at="2026-06-05T23:57:52Z",
                child_last_exit_code=-15,
                restart_count=14,
            )

        self.assertFalse(payload["session_should_run"])
        self.assertFalse(payload["child_running"])
        self.assertEqual(payload["m12_37_refresh_state"], "idle_waiting_market_window")
        self.assertEqual(payload["m12_37_refresh_started_at"], "")
        self.assertEqual(payload["m12_37_active_step"], "idle")

    def test_manifest_overlay_clears_stale_refresh_state_when_market_is_idle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_47"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            manifest_path = output_dir / "m12_37_auto_runner_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "refresh_state": "refresh_in_progress",
                        "refresh_started_at": "2026-06-05T23:57:52Z",
                        "active_step": "m12_29_current_day_scan_dashboard",
                        "market_session": {"status": "美股常规交易时段"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload = {
                "market_status": "非交易日等待",
                "new_york_time": "2026-06-06 01:17:22 EDT",
                "beijing_time": "2026-06-06 13:17:22 CST",
                "session_should_run": False,
                "child_running": False,
            }

            self.assertTrue(sync_manifest_status_overlay(config, payload))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["refresh_state"], "idle_waiting_market_window")
        self.assertEqual(manifest["refresh_started_at"], "")
        self.assertEqual(manifest["active_step"], "idle")
        self.assertEqual(manifest["status_overlay"]["manifest_refresh_state"], "idle_waiting_market_window")


if __name__ == "__main__":
    unittest.main()
