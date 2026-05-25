import json
import tempfile
import unittest
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.run_m12_47_session_supervisor import (
    apply_dashboard_status_overlay,
    build_failure_payload,
    build_status_payload,
    build_window_state,
    load_config,
    print_status,
    should_trip_failure_breaker,
    status_path,
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

    def test_dashboard_status_overlay_marks_holiday_snapshot_audit_only(self):
        dashboard = {
            "generated_at": "2026-05-25T14:09:30Z",
            "summary": {
                "generated_at": "2026-05-25T14:09:30Z",
                "current_day_runtime_ready": True,
                "current_day_scan_complete": True,
                "data_freshness_warning": "",
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
        )
        self.assertTrue(changed)
        self.assertEqual(dashboard["update_status"]["market_status"], "非交易日等待")
        self.assertEqual(dashboard["summary"]["market_session"]["status"], "非交易日等待")
        self.assertFalse(dashboard["summary"]["current_day_runtime_ready"])
        self.assertEqual(dashboard["broker_terminal_view"]["top_status"]["fully_ready_for_trading_display"], "false")
        self.assertIn("上一有效审计快照", dashboard["summary"]["data_freshness_warning"])

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


if __name__ == "__main__":
    unittest.main()
