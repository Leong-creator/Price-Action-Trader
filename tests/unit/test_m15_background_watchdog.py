from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.m15_background_watchdog_lib import (
    assert_safe_watchdog_command,
    load_config,
    run_background_watchdog_once,
)


class M15BackgroundWatchdogTest(unittest.TestCase):
    def test_watchdog_runs_only_safe_daemon_status_and_readiness_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "watchdog.json"
            config_path.write_text(
                json.dumps(
                    {
                        "stage": "M15.background_watchdog",
                        "inputs": {
                            "m12_47_config": str(root / "m12_47.json"),
                            "m15_realtime_supervisor_config": str(root / "m15_supervisor.json"),
                            "readiness_config": str(root / "readiness.json"),
                        },
                        "outputs": {"output_dir": str(root / "watchdog")},
                        "watchdog": {"check_interval_seconds": 60, "command_timeout_seconds": 5},
                        "hard_boundaries": {
                            "paper_simulated_only": True,
                            "live_execution": False,
                            "real_money_actions": False,
                            "manual_m12_37_once": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            seen: list[list[str]] = []

            def runner(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
                seen.append(command)
                return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

            payload = run_background_watchdog_once(
                load_config(config_path),
                generated_at="2026-06-30T02:30:00Z",
                command_runner=runner,
            )

            self.assertEqual(payload["watchdog_status"], "healthy")
            self.assertEqual(payload["failed_step_count"], 0)
            joined = "\n".join(" ".join(command) for command in seen)
            self.assertIn("run_m12_47_session_supervisor.py --daemon", joined)
            self.assertIn("run_m15_longbridge_realtime_session_supervisor.py --daemon", joined)
            self.assertIn("run_m15_opening_trade_readiness.py", joined)
            self.assertNotIn("run_m12_37_intraday_auto_loop.py --once", joined)
            self.assertNotIn("--no-fetch", joined)
            self.assertNotIn(" order buy ", joined)

    def test_watchdog_blocks_unsafe_command_shapes(self) -> None:
        with self.assertRaises(ValueError):
            assert_safe_watchdog_command(["python", "scripts/run_m12_37_intraday_auto_loop.py", "--once"])
        with self.assertRaises(ValueError):
            assert_safe_watchdog_command(["longbridge", "order", "buy", "AAPL.US", "1"])


if __name__ == "__main__":
    unittest.main()
