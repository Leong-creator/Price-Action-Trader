import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.run_m12_47_session_supervisor import (
    build_status_payload,
    build_window_state,
    load_config,
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
        self.assertIn(after["market_status"], {"收盘后收尾窗口", "等待下一交易日"})

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
                child_pid=456,
                child_running=True,
                child_started_at="2026-05-05T13:25:00Z",
                child_last_exit_code=None,
                restart_count=0,
            )
        self.assertEqual(payload["latest_dashboard_generated_at"], "2026-05-05T17:15:30Z")
        self.assertEqual(payload["child_pid"], 456)
        self.assertTrue(payload["child_running"])
        self.assertIn("自动调度器正在运行", payload["plain_language_result"])


if __name__ == "__main__":
    unittest.main()
