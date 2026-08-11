from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.m15_background_watchdog_lib import (
    analytics_refresh_due,
    load_config,
    run_background_watchdog_once,
    m15_runtime_status_step,
    pa002_milestone_refresh_step,
    should_append_watchdog_ledger,
    sdk_runtime_step_is_transient_recovery,
    start_daemon,
    status,
)


class M15BackgroundWatchdogTest(unittest.TestCase):
    def test_sdk_runtime_context_restore_is_transient_recovery(self) -> None:
        self.assertTrue(
            sdk_runtime_step_is_transient_recovery(
                {
                    "returncode": 3,
                    "stderr_tail": "sdk_runtime_not_ready:starting_context_restore",
                }
            )
        )

    def test_pa002_milestone_skips_when_fill_attribution_refresh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp), runtime_engine="sdk")

            def unexpected_runner(_command: list[str], _timeout: int):
                self.fail("milestone evaluator must not read stale attribution after refresh failure")

            step = pa002_milestone_refresh_step(
                config,
                unexpected_runner,
                "2026-08-03T20:30:00Z",
                previous={},
                analytics_step={"returncode": 1, "skipped_due_to_throttle": False},
            )

            self.assertEqual(step["returncode"], 0)
            self.assertTrue(step["skipped_due_to_analytics_failure"])
            self.assertIn("refresh_failed", step["stdout_tail"])

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

    def test_start_daemon_reuses_live_run_lock_owner_without_spawning_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            config.output_dir.mkdir(parents=True, exist_ok=True)
            (config.output_dir / "m15_background_watchdog.run.lock").write_text(
                str(__import__("os").getpid()) + "\n",
                encoding="utf-8",
            )

            with patch("scripts.m15_background_watchdog_lib.subprocess.Popen") as popen:
                result = start_daemon(root / "config.json", config)

            self.assertEqual(result, 0)
            popen.assert_not_called()
            self.assertEqual(
                (config.output_dir / "m15_background_watchdog.pid").read_text(encoding="utf-8").strip(),
                str(__import__("os").getpid()),
            )

    def test_analytics_refresh_due_honors_interval(self) -> None:
        self.assertFalse(
            analytics_refresh_due("2026-06-04T14:04:59Z", "2026-06-04T14:00:00Z", 300)
        )
        self.assertTrue(
            analytics_refresh_due("2026-06-04T14:05:00Z", "2026-06-04T14:00:00Z", 300)
        )

    def test_watchdog_ledger_is_throttled_until_five_minutes_or_status_change(self) -> None:
        previous = {
            "generated_at": "2026-07-18T05:00:00Z",
            "watchdog_status": "healthy",
            "steps": [],
        }
        current = {
            "generated_at": "2026-07-18T05:04:59Z",
            "watchdog_status": "healthy",
            "steps": [],
        }
        self.assertFalse(should_append_watchdog_ledger(previous, current))
        current["generated_at"] = "2026-07-18T05:05:00Z"
        self.assertTrue(should_append_watchdog_ledger(previous, current))
        current["generated_at"] = "2026-07-18T05:01:00Z"
        current["watchdog_status"] = "needs_attention"
        self.assertTrue(should_append_watchdog_ledger(previous, current))

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

    def test_watchdog_preserves_analytics_throttle_across_consecutive_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, runtime_engine="cli")
            config.output_dir.mkdir(parents=True, exist_ok=True)
            (config.output_dir / "m15_background_watchdog_status.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-04T14:00:00Z",
                        "steps": [{"step_id": "m15_account_state_full_refresh", "returncode": 0}],
                    }
                ),
                encoding="utf-8",
            )
            analytics_commands: list[list[str]] = []

            def runner(command: list[str], _timeout: int):
                if "run_m15_longbridge_realtime_account_state.py" in command:
                    analytics_commands.append(command)
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

            first = run_background_watchdog_once(
                config,
                generated_at="2026-06-04T14:01:00Z",
                command_runner=runner,
            )
            second = run_background_watchdog_once(
                config,
                generated_at="2026-06-04T14:02:00Z",
                command_runner=runner,
            )

            first_step = next(row for row in first["steps"] if row["step_id"] == "m15_account_state_full_refresh")
            second_step = next(row for row in second["steps"] if row["step_id"] == "m15_account_state_full_refresh")
            self.assertTrue(first_step["skipped_due_to_throttle"])
            self.assertTrue(second_step["skipped_due_to_throttle"])
            self.assertEqual(second_step["last_success_generated_at"], "2026-06-04T14:00:00Z")
            self.assertEqual(analytics_commands, [])

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

    def test_sdk_watchdog_refreshes_analytics_without_legacy_cli_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp), runtime_engine="sdk")
            commands: list[list[str]] = []

            def runner(command: list[str], _timeout: int):
                commands.append(command)
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

            run_background_watchdog_once(
                config,
                generated_at="2026-07-18T05:00:00Z",
                command_runner=runner,
            )

            joined = [" ".join(command) for command in commands]
            self.assertTrue(any("run_m15_longbridge_sdk_analytics.py" in command for command in joined))
            self.assertFalse(any("run_m15_longbridge_realtime_account_state.py" in command for command in joined))

    def test_sdk_watchdog_keeps_healthy_when_analytics_reports_statistics_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp), runtime_engine="sdk")

            def runner(command: list[str], _timeout: int):
                script = command[1] if len(command) > 1 else ""
                if script.endswith("run_m15_longbridge_sdk_runtime.py") and "--status" in command:
                    stdout = json.dumps(
                        {
                            "runtime_process_alive": True,
                            "status": "running",
                            "sdk_connected": True,
                            "account_snapshot_healthy": True,
                        }
                    )
                elif script.endswith("run_m15_longbridge_sdk_analytics.py"):
                    stdout = json.dumps({"statistics_stale": True, "history_refresh_mode": "trusted_cache_plus_fresh_snapshot_statistics_stale_history_orders_timeout"})
                else:
                    stdout = "ok"
                return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

            payload = run_background_watchdog_once(
                config,
                generated_at="2026-08-11T16:00:00Z",
                command_runner=runner,
            )

            analytics_step = next(step for step in payload["steps"] if step["step_id"] == "m15_account_state_full_refresh")
            self.assertEqual(payload["watchdog_status"], "healthy")
            self.assertEqual(analytics_step["returncode"], 0)

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

    def test_watchdog_runs_pa002_postmarket_milestone_evaluator_as_non_blocking_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, runtime_engine="sdk")
            commands: list[list[str]] = []

            def runner(command: list[str], _timeout: int):
                commands.append(command)
                script = command[1] if len(command) > 1 else ""
                if script.endswith("run_m15_longbridge_sdk_runtime.py") and "--status" in command:
                    stdout = json.dumps(
                        {
                            "runtime_process_alive": True,
                            "status": "running",
                            "sdk_connected": True,
                            "account_snapshot_healthy": True,
                        }
                    )
                elif script.endswith("run_m15_pa002_dual_version_milestone.py"):
                    stdout = json.dumps(
                        {
                            "evaluation_status": "waiting_for_postmarket_cutoff",
                            "notification": {"notification_dedup_key": "pa002:dedup"},
                        }
                    )
                else:
                    stdout = "ok"
                return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

            payload = run_background_watchdog_once(
                config,
                generated_at="2026-07-28T16:00:00Z",
                command_runner=runner,
            )

            self.assertEqual(payload["watchdog_status"], "healthy")
            self.assertTrue(
                any(
                    len(command) > 1 and command[1] == "scripts/run_m15_pa002_dual_version_milestone.py"
                    for command in commands
                )
            )
            milestone_step = next(
                step for step in payload["steps"] if step["step_id"] == "m15_pa002_dual_version_milestone"
            )
            self.assertEqual(milestone_step["returncode"], 0)

    def test_watchdog_reports_connecting_sdk_runtime_as_needs_attention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp), runtime_engine="sdk")

            def runner(command: list[str], _timeout: int):
                if "--status" in command and any(
                    token.endswith("run_m15_longbridge_sdk_runtime.py") for token in command
                ):
                    stdout = json.dumps(
                        {
                            "runtime_process_alive": True,
                            "status": "connecting",
                            "sdk_connected": False,
                            "account_snapshot_healthy": True,
                        }
                    )
                else:
                    stdout = "ok"
                return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

            payload = run_background_watchdog_once(
                config,
                generated_at="2026-07-28T16:00:00Z",
                command_runner=runner,
            )

            status_step = next(
                step for step in payload["steps"] if step["step_id"] == "m15_sdk_runtime_status"
            )
            self.assertEqual(payload["watchdog_status"], "needs_attention")
            self.assertEqual(status_step["returncode"], 3)
            self.assertIn("sdk_runtime_not_ready:connecting", status_step["stderr_tail"])

    def test_sdk_runtime_status_waits_for_transient_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(
                Path(tmp), runtime_engine="sdk", runtime_recovery_grace_seconds=20
            )
            responses = iter(
                [
                    {"runtime_process_alive": True, "status": "connecting", "sdk_connected": False},
                    {"runtime_process_alive": True, "status": "connecting", "sdk_connected": False},
                    {
                        "runtime_process_alive": True,
                        "status": "running",
                        "sdk_connected": True,
                        "account_snapshot_healthy": True,
                    },
                ]
            )
            clock = [0.0]

            def runner(_command: list[str], _timeout: int):
                return type(
                    "Result",
                    (),
                    {"returncode": 0, "stdout": json.dumps(next(responses)), "stderr": ""},
                )()

            def sleep(seconds: float) -> None:
                clock[0] += seconds

            step = m15_runtime_status_step(
                config,
                runner,
                sleep=sleep,
                monotonic=lambda: clock[0],
            )

            self.assertEqual(step["returncode"], 0)
            self.assertEqual(step["recovery_check_attempts"], 3)
            self.assertTrue(step["recovered_within_grace"])

    def test_watchdog_reports_logically_blocked_acceptance_as_needs_attention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp), runtime_engine="sdk")

            def runner(command: list[str], _timeout: int):
                script = command[1] if len(command) > 1 else ""
                if script.endswith("run_m15_longbridge_sdk_runtime.py") and "--status" in command:
                    stdout = json.dumps(
                        {
                            "runtime_process_alive": True,
                            "status": "running",
                            "sdk_connected": True,
                            "account_snapshot_healthy": True,
                        }
                    )
                elif script.endswith("run_m15_opening_trade_readiness.py"):
                    stdout = json.dumps({"readiness_status": "blocked_opening_trade_watch"})
                elif script.endswith("run_m15_monday_refresh_acceptance.py"):
                    stdout = json.dumps({"acceptance_status": "blocked_monday_acceptance"})
                else:
                    stdout = "ok"
                return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

            payload = run_background_watchdog_once(
                config,
                generated_at="2026-07-28T16:00:00Z",
                command_runner=runner,
            )

            self.assertEqual(payload["watchdog_status"], "needs_attention")
            failed = {
                step["step_id"]: step["stderr_tail"]
                for step in payload["steps"]
                if step["returncode"] != 0
            }
            self.assertIn("opening_readiness_blocked", failed["m15_opening_readiness"])
            self.assertIn("monday_acceptance_blocked", failed["m15_monday_acceptance"])

    def make_config(
        self,
        root: Path,
        *,
        runtime_engine: str = "sdk",
        runtime_recovery_grace_seconds: int = 0,
    ):
        payload = {
            "stage": "M15.background_watchdog",
            "inputs": {
                "m15_realtime_supervisor_config": str(root / "supervisor.json"),
                "m15_runtime_engine": runtime_engine,
                "m15_sdk_runtime_config": str(root / "sdk_runtime.json"),
                "m15_account_state_config": str(root / "account_state.json"),
                "m15_dashboard_config": str(root / "dashboard.json"),
                "readiness_config": str(root / "readiness.json"),
                "monday_acceptance_config": str(root / "monday_acceptance.json"),
            },
            "outputs": {
                "output_dir": str(root / "out"),
            },
            "watchdog": {
                "check_interval_seconds": 60,
                "command_timeout_seconds": 30,
                "analytics_refresh_interval_seconds": 300,
                "runtime_recovery_grace_seconds": runtime_recovery_grace_seconds,
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
