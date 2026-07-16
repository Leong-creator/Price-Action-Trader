from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_background_watchdog_lib import analytics_refresh_due, load_config, run_background_watchdog_once, status


class M15BackgroundWatchdogTest(unittest.TestCase):
    def test_status_never_reports_stale_health_when_process_is_dead(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            config.output_dir.mkdir(parents=True, exist_ok=True)
            (config.output_dir / "m15_background_watchdog_status.json").write_text(
                json.dumps({"watchdog_status": "healthy", "plain_language_result": "old healthy"}),
                encoding="utf-8",
            )

            payload = status(config)

            self.assertFalse(payload["process_alive"])
            self.assertEqual(payload["watchdog_status"], "stopped")
            self.assertIn("历史健康结果已失效", payload["plain_language_result"])

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
            config = self.make_config(root, runtime_engine="cli")
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
            config = self.make_config(root, runtime_engine="cli")
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

    def test_watchdog_no_longer_runs_or_requires_m12_47_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            commands: list[list[str]] = []

            def runner(command: list[str], _timeout: int):
                commands.append(command)
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

            payload = run_background_watchdog_once(
                config,
                generated_at="2026-06-04T14:05:00Z",
                command_runner=runner,
            )

            self.assertTrue(all("run_m12_47_session_supervisor.py" not in " ".join(command) for command in commands))
            self.assertFalse(any(step["step_id"].startswith("m12_47_") for step in payload["steps"]))
            self.assertEqual(payload["watchdog_status"], "healthy")
            self.assertTrue(payload["local_research_non_blocking"]["m12_47_managed_elsewhere"])

    def make_config(self, root: Path, *, runtime_engine: str = "sdk"):
        payload = {
            "stage": "M15.background_watchdog",
            "inputs": {
                "m15_realtime_supervisor_config": str(root / "supervisor.json"),
                "m15_runtime_engine": runtime_engine,
                "m15_sdk_runtime_config": str(root / "sdk_runtime.json"),
                "m15_account_state_config": str(root / "account_state.json"),
                "m15_dashboard_config": str(root / "dashboard.json"),
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
