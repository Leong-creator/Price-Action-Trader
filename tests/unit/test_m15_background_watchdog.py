from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_background_watchdog_lib import analytics_refresh_due, load_config, run_background_watchdog_once


class M15BackgroundWatchdogTest(unittest.TestCase):
    def test_analytics_refresh_due_honors_interval(self) -> None:
        self.assertFalse(
            analytics_refresh_due("2026-06-04T14:04:59Z", "2026-06-04T14:00:00Z", 300)
        )
        self.assertTrue(
            analytics_refresh_due("2026-06-04T14:05:00Z", "2026-06-04T14:00:00Z", 300)
        )

    def test_watchdog_skips_account_analytics_refresh_before_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            config.output_dir.mkdir(parents=True, exist_ok=True)
            (config.output_dir / "m15_background_watchdog_status.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-04T14:00:00Z",
                        "steps": [
                            {
                                "step_id": "m15_account_state_full_refresh",
                                "returncode": 0,
                                "skipped_due_to_throttle": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            commands: list[list[str]] = []

            def runner(command: list[str], _timeout: int):
                commands.append(command)
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

            payload = run_background_watchdog_once(
                config,
                generated_at="2026-06-04T14:04:00Z",
                command_runner=runner,
            )

            analytics_step = next(step for step in payload["steps"] if step["step_id"] == "m15_account_state_full_refresh")
            self.assertTrue(analytics_step["skipped_due_to_throttle"])
            self.assertFalse(any(command[1] == "scripts/run_m15_longbridge_realtime_account_state.py" for command in commands))

    def test_watchdog_runs_account_analytics_refresh_after_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            commands: list[list[str]] = []
            timeouts: list[int] = []

            def runner(command: list[str], timeout: int):
                commands.append(command)
                timeouts.append(timeout)
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

            payload = run_background_watchdog_once(
                config,
                generated_at="2026-06-04T14:05:00Z",
                command_runner=runner,
            )

            analytics_step = next(step for step in payload["steps"] if step["step_id"] == "m15_account_state_full_refresh")
            self.assertFalse(analytics_step["skipped_due_to_throttle"])
            self.assertTrue(any(command[1] == "scripts/run_m15_longbridge_realtime_account_state.py" for command in commands))
            self.assertIn(90, timeouts)

    def make_config(self, root: Path):
        payload = {
            "stage": "M15.background_watchdog",
            "inputs": {
                "m12_47_config": str(root / "m12_47.json"),
                "m15_realtime_supervisor_config": str(root / "supervisor.json"),
                "m15_account_state_config": str(root / "account_state.json"),
                "readiness_config": str(root / "readiness.json"),
            },
            "outputs": {
                "output_dir": str(root / "out"),
            },
            "watchdog": {
                "check_interval_seconds": 60,
                "command_timeout_seconds": 30,
                "analytics_refresh_interval_seconds": 300,
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "manual_m12_37_once": False,
                "margin_financing": False,
            },
        }
        config_path = root / "config.json"
        config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return load_config(config_path)


if __name__ == "__main__":
    unittest.main()
