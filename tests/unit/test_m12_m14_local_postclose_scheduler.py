from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.m12_m14_local_postclose_scheduler_lib import (
    load_scheduler_config,
    run_scheduler_once,
    start_daemon,
    status,
    stop_daemon,
)


class LocalPostcloseSchedulerTest(unittest.TestCase):
    def make_scheduler_config(self, root: Path) -> Path:
        batch_payload = json.loads((Path("config/examples/m12_m14_local_postclose_batch.json")).read_text(encoding="utf-8"))
        batch_payload["local_repair"]["output_dir"] = (root / "batch_output").as_posix()
        batch_config_path = root / "batch.json"
        batch_config_path.write_text(json.dumps(batch_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        scheduler_payload = json.loads(
            (Path("config/examples/m12_m14_local_postclose_scheduler.json")).read_text(encoding="utf-8")
        )
        scheduler_payload["output_dir"] = (root / "scheduler_output").as_posix()
        scheduler_payload["batch_config_path"] = batch_config_path.as_posix()
        scheduler_payload["visual_shadow_session_config_path"] = None
        scheduler_payload["formal_test_evidence_config_path"] = None
        scheduler_config_path = root / "scheduler.json"
        scheduler_config_path.write_text(json.dumps(scheduler_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return scheduler_config_path

    def test_scheduler_waits_until_postclose_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_scheduler_config(self.make_scheduler_config(Path(tmp)))
            result = run_scheduler_once(config, generated_at="2026-07-16T19:59:00Z")

            self.assertEqual(result["scheduler_status"], "waiting_for_window")
            self.assertFalse(result["triggered"])
            self.assertEqual(result["skip_reason"], "before_trigger_window")

    def test_scheduler_triggers_only_once_per_business_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_scheduler_config(self.make_scheduler_config(Path(tmp)))
            calls: list[str | None] = []

            def runner(_config_path: Path, generated_at: str | None) -> dict[str, object]:
                calls.append(generated_at)
                return {
                    "summary": {
                        "completed": True,
                        "attempt_count": 1,
                    }
                }

            first = run_scheduler_once(config, generated_at="2026-07-16T20:15:00Z", batch_runner=runner)
            second = run_scheduler_once(config, generated_at="2026-07-16T21:30:00Z", batch_runner=runner)

            self.assertEqual(first["scheduler_status"], "triggered_successfully")
            self.assertEqual(second["scheduler_status"], "already_triggered_today")
            self.assertEqual(calls, ["2026-07-16T20:15:00Z"])

    def test_scheduler_failure_is_non_blocking_for_m15_and_persists_daily_idempotence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_scheduler_config(self.make_scheduler_config(Path(tmp)))

            def failing_runner(_config_path: Path, _generated_at: str | None) -> dict[str, object]:
                raise RuntimeError("batch exploded")

            failed = run_scheduler_once(config, generated_at="2026-07-16T20:15:00Z", batch_runner=failing_runner)
            repeated = run_scheduler_once(config, generated_at="2026-07-16T21:15:00Z", batch_runner=failing_runner)

            self.assertEqual(failed["scheduler_status"], "triggered_with_batch_failure")
            self.assertFalse(failed["m15_isolation"]["failure_blocks_m15"])
            self.assertFalse(failed["m15_isolation"]["starts_or_stops_m15"])
            self.assertEqual(repeated["scheduler_status"], "already_triggered_today")
            self.assertEqual(repeated["last_outcome"], "failed")

    def test_visual_shadow_sidecar_runs_once_and_does_not_block_local_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.make_scheduler_config(root)
            scheduler_payload = json.loads(config_path.read_text(encoding="utf-8"))
            visual_path = root / "visual.json"
            visual_path.write_text(
                json.dumps({"stage": "M15.visual_strategy_shadow_session"}),
                encoding="utf-8",
            )
            scheduler_payload["visual_shadow_session_config_path"] = visual_path.as_posix()
            config_path.write_text(json.dumps(scheduler_payload), encoding="utf-8")
            config = load_scheduler_config(config_path)
            visual_calls: list[tuple[str, str | None]] = []

            def batch_runner(_config_path: Path, _generated_at: str | None) -> dict[str, object]:
                return {"summary": {"completed": True}}

            def visual_runner(
                _config_path: Path,
                business_date: str,
                generated_at: str | None,
            ) -> dict[str, object]:
                visual_calls.append((business_date, generated_at))
                raise RuntimeError("visual sidecar failed")

            first = run_scheduler_once(
                config,
                generated_at="2026-07-16T20:15:00Z",
                batch_runner=batch_runner,
                visual_shadow_runner=visual_runner,
            )
            second = run_scheduler_once(
                config,
                generated_at="2026-07-16T21:15:00Z",
                batch_runner=batch_runner,
                visual_shadow_runner=visual_runner,
            )
            next_day = run_scheduler_once(
                config,
                generated_at="2026-07-17T20:15:00Z",
                batch_runner=batch_runner,
                visual_shadow_runner=visual_runner,
            )

            self.assertEqual(first["scheduler_status"], "triggered_successfully")
            self.assertEqual(first["visual_shadow_status"], "failed")
            self.assertIn("visual sidecar failed", first["visual_shadow_error"])
            self.assertEqual(second["scheduler_status"], "already_triggered_today")
            self.assertEqual(next_day["visual_shadow_status"], "failed")
            self.assertEqual(
                visual_calls,
                [
                    ("2026-07-16", "2026-07-16T20:15:00Z"),
                    ("2026-07-17", "2026-07-17T20:15:00Z"),
                ],
            )

    def test_formal_evidence_sidecar_runs_even_when_local_batch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.make_scheduler_config(root)
            scheduler_payload = json.loads(config_path.read_text(encoding="utf-8"))
            evidence_path = root / "formal-evidence.json"
            evidence_path.write_text(
                json.dumps({"stage": "M15.formal_test_evidence"}),
                encoding="utf-8",
            )
            scheduler_payload["formal_test_evidence_config_path"] = evidence_path.as_posix()
            config_path.write_text(json.dumps(scheduler_payload), encoding="utf-8")
            config = load_scheduler_config(config_path)
            calls: list[str | None] = []

            def failing_batch(_config_path: Path, _generated_at: str | None) -> dict[str, object]:
                raise RuntimeError("local batch failed")

            def evidence_runner(
                _config_path: Path,
                generated_at: str | None,
            ) -> dict[str, object]:
                calls.append(generated_at)
                return {"layers": {"market_session": {"status": "complete"}}}

            result = run_scheduler_once(
                config,
                generated_at="2026-07-16T20:15:00Z",
                batch_runner=failing_batch,
                formal_evidence_runner=evidence_runner,
            )

            self.assertEqual(result["scheduler_status"], "triggered_with_batch_failure")
            self.assertEqual(result["formal_test_evidence_status"], "complete")
            self.assertEqual(calls, ["2026-07-16T20:15:00Z"])

    def test_daemon_status_stop_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_scheduler_config(self.make_scheduler_config(Path(tmp)))

            self.assertEqual(stop_daemon(config), 0)
            stopped_status = status(config, generated_at="2026-07-16T20:15:00Z")
            self.assertEqual(stopped_status["scheduler_status"], "stopped")

            pid_path = config.output_dir / "m12_m14_local_postclose_scheduler.pid"
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text("4321\n", encoding="utf-8")
            with patch("scripts.m12_m14_local_postclose_scheduler_lib.process_alive", return_value=True), patch(
                "scripts.m12_m14_local_postclose_scheduler_lib.subprocess.Popen"
            ) as popen_mock:
                self.assertEqual(start_daemon("ignored.json", config), 0)
            popen_mock.assert_not_called()

    def test_startup_script_only_references_m15_and_local_postclose_scheduler(self) -> None:
        script = Path("scripts/start_m15_trading_stack_after_boot.sh").read_text(encoding="utf-8")

        self.assertIn("run_m12_m14_local_postclose_scheduler.py", script)
        self.assertIn("m15_longbridge_sdk_runtime.contract_v1.json", script)
        self.assertIn("m15_background_watchdog.contract_v1.json", script)
        self.assertIn('if [[ "${1:-}" == "--keep-alive" ]]', script)
        self.assertIn("m15_windows_hidden_keeper.heartbeat", script)
        self.assertIn("sleep 60", script)
        self.assertIn("Removing stale startup lock", script)
        keeper_loop = script.rsplit('if [[ "$KEEP_ALIVE" == true ]]', 1)[1]
        self.assertIn("ensure_supporting_daemons", keeper_loop)
        self.assertNotIn("start_stack", keeper_loop)
        self.assertNotIn("run_m12_47_session_supervisor.py", script)
        self.assertNotIn("run_m12_37_intraday_auto_loop.py", script)

    def test_windows_hidden_launcher_uses_direct_wsl_exec(self) -> None:
        script = Path("scripts/install_m15_windows_startup_task.ps1").read_text(encoding="utf-8")

        self.assertIn("--exec bash", script)
        self.assertIn("--keep-alive", script)
        self.assertIn("Install-WeekdayWakeFallback", script)
        self.assertIn("schtasks.exe", script)
        self.assertIn('"20:45"', script)
        self.assertIn("DisallowStartIfOnBatteries = $false", script)
        self.assertIn("StartWhenAvailable = $true", script)
        self.assertNotIn("bash -lc", script)
        self.assertNotIn("300", script)


if __name__ == "__main__":
    unittest.main()
