from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts import m15_runtime_boot_identity_lib as boot
from scripts import run_m15_longbridge_sdk_runtime as runtime


OLD_BOOT = "ee94d3c7-8215-4f33-a202-cfa0a369a525"
NEW_BOOT = "ed085ce1-848e-4c45-a644-8071dfffd8eb"


class BootRuntimeIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory()))
        self.config = replace(
            runtime.load_config(), output_dir=self.root / "output",
            runtime_status_path=self.root / "output/status.json",
            market_events_path=self.root / "events.jsonl",
            readonly_gate_path=self.root / "gate.json",
        )
        self.config.output_dir.mkdir()
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.proc_entry(os.getpid(), [b"python", boot.RUNTIME_SCRIPT.encode(), b"--watch"])
        self.identity = {
            "runtime_boot_id": NEW_BOOT, "runtime_boot_id_source": boot.BOOT_ID_SOURCE,
            "runtime_boot_id_error": "",
        }
        self.stack.enter_context(patch.object(runtime, "GLOBAL_RUNTIME_START_LOCK", self.root / "start.lock"))
        self.stack.enter_context(patch.object(runtime, "GLOBAL_QUOTE_SUBSCRIPTION_LOCK", self.root / "run.lock"))
        self.stack.enter_context(patch.object(runtime, "read_runtime_boot_identity", return_value=self.identity))
        self.stack.enter_context(patch.object(boot, "read_runtime_boot_identity", return_value=self.identity))
        collect = boot.collect_runtime_process_evidence
        self.stack.enter_context(patch.object(boot, "collect_runtime_process_evidence",
                                             side_effect=lambda previous: collect(previous, proc_root=self.proc)))
        self.sdk = self.stack.enter_context(patch.object(runtime, "require_sdk_contract", side_effect=RuntimeError("offline_sdk_sentinel")))
        self.orphans = self.stack.enter_context(patch.object(runtime, "cleanup_orphaned_sdk_runtime_children", return_value=[]))
        self.popen = self.stack.enter_context(patch.object(runtime.subprocess, "Popen", return_value=SimpleNamespace(pid=987654)))
        self.shutdown = self.stack.enter_context(patch.object(runtime, "request_runtime_shutdown"))
        self.account = self.stack.enter_context(patch.object(runtime, "SdkAccountProcessCoordinator"))
        self.clients = self.stack.enter_context(patch.object(runtime, "build_sdk_trade_clients"))
        self.args = SimpleNamespace(config=str(self.config.config_path), dispatch=False,
                                    status=False, stop=False, check=False, daemon=False)

    def proc_entry(self, pid, argv):
        directory = self.proc / str(pid)
        directory.mkdir(exist_ok=True)
        (directory / "stat").write_text(f"{pid} (python) S " + "0 " * 18 + "12345\n")
        (directory / "cmdline").write_bytes(b"\0".join(argv) + b"\0")

    def previous(self, **changes):
        return {
            **self.identity, "runtime_boot_id": OLD_BOOT,
            "status": "running", "runtime_pid": 321,
            "runtime_process_start_ticks": "12345",
            "generated_at": "2000-01-01T00:00:00+00:00",
            "account_snapshot_age_seconds": 999999,
            "config_fingerprint": "different_config", "dispatch_requested": True,
            **changes,
        }

    def save(self, value):
        self.config.runtime_status_path.write_text(json.dumps(value))

    def read_status(self):
        return json.loads(self.config.runtime_status_path.read_text())

    def audit(self):
        return [json.loads(line) for line in (self.config.output_dir / "m15_runtime_boot_audit.jsonl").read_text().splitlines()]

    def assert_lock_released(self):
        lock = runtime.acquire_runtime_run_lock(self.config.output_dir)
        self.assertIsNotNone(lock)
        lock.close()

    def test_checked_cross_boot_audits_exact_old_state_and_leaves_it_unchanged(self):
        previous = self.previous()
        self.save(previous)
        decision = runtime.checked_runtime_boot_startup(self.config)
        self.assertTrue(decision["allow_reinitialize"])
        self.assertFalse(decision["dispatch_authorized"])
        self.assertEqual(self.read_status(), previous)
        self.assertEqual(self.audit()[0]["previous_runtime_status"], previous)

    def test_explicit_faults_cannot_be_unlocked_by_boot_or_changed_fingerprint(self):
        for status in ("fault_halted", "blocked_sdk_prerequisite", "blocked", "halted_account_snapshot_circuit"):
            with self.subTest(status=status):
                previous = self.previous(status=status)
                self.save(previous)
                with self.assertRaisesRegex(RuntimeError, "manual_diagnosis_required"):
                    runtime.start_runtime_daemon(self.args, self.config)
                self.assertEqual(self.read_status(), previous)
                self.assertEqual(self.audit()[-1]["decision"]["reason"], "explicit_fault_latched")
        self.popen.assert_not_called()
        self.shutdown.assert_not_called()

    def test_account_circuit_flag_blocks_running_boot_recovery(self):
        self.save(self.previous(account_snapshot_circuit_open=True))
        with self.assertRaisesRegex(RuntimeError, "explicit_fault_latched"):
            runtime.run_watch(self.config, dispatch_requested=True)
        self.sdk.assert_not_called()
        self.account.assert_not_called()
        self.assert_lock_released()

    def test_same_boot_fresh_crash_and_missing_boot_are_manual(self):
        for changes in ({"runtime_boot_id": NEW_BOOT, "generated_at": datetime.now(UTC).isoformat(), "account_snapshot_age_seconds": 1},
                        {"runtime_boot_id": ""}, {"runtime_boot_id_source": ""}):
            with self.subTest(changes=changes):
                previous = self.previous(**changes)
                self.save(previous)
                with self.assertRaisesRegex(RuntimeError, "manual_diagnosis_required"):
                    runtime.run_watch(self.config, dispatch_requested=False)
                self.assertEqual(self.read_status(), previous)
                self.assert_lock_released()
        self.sdk.assert_not_called()
        self.orphans.assert_not_called()

    def test_corrupt_and_non_object_status_are_not_treated_as_first_start(self):
        for raw in ("broken", "[]", "null"):
            with self.subTest(raw=raw):
                self.config.runtime_status_path.write_text(raw)
                with self.assertRaises((RuntimeError, json.JSONDecodeError)):
                    runtime.run_watch(self.config, dispatch_requested=False)
                self.assertEqual(self.config.runtime_status_path.read_text(), raw)
                self.assert_lock_released()
        self.sdk.assert_not_called()

    def test_audit_failure_prevents_all_startup_side_effects(self):
        previous = self.previous()
        self.save(previous)
        runtime.GLOBAL_QUOTE_SUBSCRIPTION_LOCK.write_text("old_owner\n")
        with patch.object(runtime, "append_runtime_boot_audit", side_effect=OSError("audit_full")):
            with self.assertRaisesRegex(OSError, "audit_full"):
                runtime.run_watch(self.config, dispatch_requested=True)
        self.assertEqual(self.read_status(), previous)
        self.assertEqual(runtime.GLOBAL_QUOTE_SUBSCRIPTION_LOCK.read_text(), "old_owner\n")
        self.assertFalse(runtime.pid_path(self.config).exists())
        self.sdk.assert_not_called()
        self.orphans.assert_not_called()
        self.assert_lock_released()

    def test_unknown_process_evidence_blocks_before_sdk(self):
        self.save(self.previous())
        (self.proc / "666").mkdir()
        with self.assertRaisesRegex(RuntimeError, "absence_not_proven"):
            runtime.run_watch(self.config, dispatch_requested=False)
        self.sdk.assert_not_called()
        self.assert_lock_released()

    def test_another_config_runtime_blocks_cross_boot(self):
        self.save(self.previous())
        self.proc_entry(666, [b"python", boot.RUNTIME_SCRIPT.encode(), b"--watch", b"--config", b"other.json"])
        with self.assertRaisesRegex(RuntimeError, "absence_not_proven"):
            runtime.start_runtime_daemon(self.args, self.config)
        self.popen.assert_not_called()

    def test_same_boot_existing_owner_still_requires_health_gate(self):
        self.proc_entry(321, [b"python", boot.RUNTIME_SCRIPT.encode(), b"--watch"])
        self.save(self.previous(runtime_boot_id=NEW_BOOT))
        with self.assertRaisesRegex(RuntimeError, "manual_diagnosis_required"):
            runtime.checked_runtime_boot_startup(self.config)
        self.assertEqual(self.audit()[-1]["decision"]["action"], "existing_runtime")

    def test_main_repeated_daemon_dispatch_reuses_same_healthy_runtime(self):
        self.proc_entry(321, [b"python", boot.RUNTIME_SCRIPT.encode(), b"--watch", b"--dispatch"])
        self.save(self.previous(
            runtime_boot_id=NEW_BOOT, generated_at=datetime.now(UTC).isoformat(),
            account_snapshot_age_seconds=1,
            config_fingerprint=runtime.config_fingerprint(self.config),
        ))
        runtime.GLOBAL_QUOTE_SUBSCRIPTION_LOCK.write_text("321\n")
        runtime.pid_path(self.config).write_text("321\n")
        self.args.daemon = True
        self.args.dispatch = True
        self.sdk.side_effect = None
        with patch.object(runtime, "read_client_id", return_value="offline"), \
             patch.object(runtime, "process_alive", return_value=True), \
             patch.object(runtime, "is_expected_sdk_runtime_process", return_value=True), \
             patch.object(runtime, "runtime_status_process_matches", return_value=True):
            for _ in range(2):
                self.assertEqual(self.call_main_with_prerequisite_failure(), 0)
        self.popen.assert_not_called()
        self.shutdown.assert_not_called()
        self.assertEqual(self.read_status()["status"], "running")
        self.assertEqual([row["decision"]["action"] for row in self.audit()], ["existing_runtime"] * 2)

    def test_main_normal_stop_then_new_daemon_is_allowed(self):
        self.save(self.previous(
            runtime_boot_id=NEW_BOOT, generated_at=datetime.now(UTC).isoformat(),
            account_snapshot_age_seconds=1,
        ))
        runtime.pid_path(self.config).write_text("321\n")
        self.args.stop = True
        self.shutdown.return_value = True
        with patch.object(runtime, "process_alive", return_value=True):
            self.assertEqual(self.call_main_with_prerequisite_failure(), 0)
        self.shutdown.assert_called_once_with(321)
        self.assertEqual(self.read_status()["status"], "operator_stopped")
        self.assertFalse(runtime.pid_path(self.config).exists())
        self.sdk.assert_not_called()

        self.args.stop = False
        self.args.daemon = True
        self.sdk.side_effect = None
        with patch.object(runtime, "read_client_id", return_value="offline"):
            self.assertEqual(self.call_main_with_prerequisite_failure(), 0)
        self.popen.assert_called_once()
        self.assertNotIn("--dispatch", self.popen.call_args.args[0])
        self.assertEqual(self.audit()[-1]["decision"]["action"], "no_boot_recovery")

    def test_daemon_never_kills_reused_pid_or_inherits_old_dispatch(self):
        self.save(self.previous(runtime_pid=os.getpid()))
        runtime.GLOBAL_QUOTE_SUBSCRIPTION_LOCK.write_text(str(os.getpid()))
        for dispatch in (False, True):
            with self.subTest(dispatch=dispatch):
                self.args.dispatch = dispatch
                runtime.start_runtime_daemon(self.args, self.config)
                command = self.popen.call_args.args[0]
                self.assertEqual("--dispatch" in command, dispatch)
        self.shutdown.assert_not_called()

    def test_parent_child_double_check_excludes_current_child_and_preserves_original_until_child(self):
        previous = self.previous(runtime_pid=os.getpid())
        self.save(previous)

        def spawned(*args, **kwargs):
            self.assertEqual(self.read_status(), previous)
            with patch.object(runtime, "_run_watch_after_boot_check", return_value=0):
                self.assertEqual(runtime.run_watch(self.config, dispatch_requested=False), 0)
            return SimpleNamespace(pid=987654)

        self.popen.side_effect = spawned
        self.assertEqual(runtime.start_runtime_daemon(self.args, self.config), 0)
        records = self.audit()
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(record["decision"]["action"], "reinitialize")
            self.assertEqual(record["previous_runtime_status"], previous)
            self.assertEqual(record["decision"]["process_evidence"]["matching_runtime_pids"], [])
        self.assertEqual(self.read_status()["runtime_boot_id"], NEW_BOOT)
        self.assertFalse(self.read_status()["dispatch_enabled"])

    def test_held_global_run_lock_stops_direct_watch_before_boot_audit(self):
        self.save(self.previous())
        lock = runtime.acquire_runtime_run_lock(self.config.output_dir)
        try:
            with patch.object(runtime, "checked_runtime_boot_startup") as check:
                self.assertEqual(runtime.run_watch(self.config, dispatch_requested=True), 0)
            check.assert_not_called()
            self.sdk.assert_not_called()
        finally:
            lock.close()

    def test_child_rechecks_fault_recorded_after_parent_validation(self):
        self.save(self.previous())

        def spawned(*args, **kwargs):
            self.save(self.previous(status="fault_halted", reason="concurrent_fault"))
            return runtime.run_watch(self.config, dispatch_requested=False)

        self.popen.side_effect = spawned
        with self.assertRaisesRegex(RuntimeError, "explicit_fault_latched"):
            runtime.start_runtime_daemon(self.args, self.config)
        self.assertEqual(self.read_status()["reason"], "concurrent_fault")
        self.sdk.assert_not_called()
        self.assertEqual([r["decision"]["action"] for r in self.audit()], ["reinitialize", "manual_required"])
        self.assert_lock_released()

    def test_early_sdk_failure_writes_connecting_first_then_fault_and_releases(self):
        previous = self.previous()
        self.save(previous)

        def sdk_failure():
            status = self.read_status()
            self.assertEqual(status["status"], "connecting")
            self.assertEqual(status["runtime_boot_id"], NEW_BOOT)
            self.assertFalse(status["dispatch_enabled"])
            raise RuntimeError("sdk_init_failed")

        self.sdk.side_effect = sdk_failure
        with self.assertRaisesRegex(RuntimeError, "sdk_init_failed"):
            runtime.run_watch(self.config, dispatch_requested=True)
        status = self.read_status()
        self.assertEqual(status["status"], "fault_halted")
        self.assertEqual(status["runtime_boot_id"], NEW_BOOT)
        self.assertTrue(status["market_data_fault_halted"])
        self.assertFalse(status["dispatch_enabled"])
        self.assertEqual(self.audit()[0]["previous_runtime_status"], previous)
        self.assertTrue((self.config.output_dir / "m15_runtime_startup_failure.json").exists())
        self.assertFalse(runtime.pid_path(self.config).exists())
        self.assert_lock_released()
        self.account.assert_not_called()

    def test_fault_evidence_write_failure_still_releases_run_lock(self):
        self.save(self.previous())
        with patch.object(runtime, "build_status", side_effect=OSError("status_disk_full")):
            with self.assertRaisesRegex(OSError, "status_disk_full"):
                runtime.run_watch(self.config, dispatch_requested=False)
        self.assert_lock_released()
        self.assertTrue((self.config.output_dir / "m15_runtime_startup_failure.json").exists())
        self.assertEqual(self.read_status()["status"], "fault_halted")
        self.sdk.assert_not_called()

    def test_diagnostic_sidecar_failure_still_attempts_atomic_fault_latch(self):
        self.save(self.previous())
        write = runtime.write_json_atomic

        def fail_sidecar(path, payload):
            if path.name == "m15_runtime_startup_failure.json":
                raise OSError("diagnostic_disk_failure")
            return write(path, payload)

        with patch.object(runtime, "write_json_atomic", side_effect=fail_sidecar):
            with self.assertRaisesRegex(OSError, "diagnostic_disk_failure"):
                runtime.run_watch(self.config, dispatch_requested=False)
        self.assertEqual(self.read_status()["status"], "fault_halted")
        self.assert_lock_released()

    def test_partial_connecting_status_write_is_replaced_by_atomic_fault_evidence(self):
        self.save(self.previous())

        def broken_status(*args, **kwargs):
            self.config.runtime_status_path.write_text('{"partial":')
            raise OSError("status_partial_write")

        with patch.object(runtime, "build_status", side_effect=broken_status):
            with self.assertRaisesRegex(OSError, "status_partial_write"):
                runtime.run_watch(self.config, dispatch_requested=False)
        status = self.read_status()
        self.assertEqual(status["status"], "fault_halted")
        self.assertEqual(status["runtime_status_read_error"], "JSONDecodeError")
        self.assertEqual(status["runtime_boot_id"], NEW_BOOT)
        self.assert_lock_released()

    def test_partial_account_start_failure_unwinds_before_existing_loop_finally(self):
        self.save(self.previous())
        self.sdk.side_effect = None
        self.sdk.return_value = object()
        coordinator = MagicMock()
        coordinator.start.side_effect = RuntimeError("account_start_failed")
        self.account.return_value = coordinator
        with patch.object(runtime, "readonly_gate_passed", return_value=(False, 0, 1)), \
             patch.object(runtime, "verify_manifest", return_value={"verified": False}), \
             patch.object(runtime, "read_jsonl_tail_rows", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "account_start_failed"):
                runtime.run_watch(self.config, dispatch_requested=False)
        coordinator.stop.assert_called_once()
        self.clients.assert_not_called()
        self.assertEqual(self.read_status()["status"], "fault_halted")
        self.assert_lock_released()

    def test_initialization_failure_does_not_replace_more_specific_fault(self):
        self.save(self.previous())

        def sdk_failure():
            self.save({**self.identity, "status": "fault_halted", "reason": "specific_cause"})
            raise RuntimeError("secondary_failure")

        self.sdk.side_effect = sdk_failure
        with self.assertRaisesRegex(RuntimeError, "secondary_failure"):
            runtime.run_watch(self.config, dispatch_requested=False)
        self.assertEqual(self.read_status()["reason"], "specific_cause")
        self.assert_lock_released()

    def call_main_with_prerequisite_failure(self):
        with patch.object(runtime, "parse_args", return_value=self.args), \
             patch.object(runtime, "load_config", return_value=self.config):
            return runtime.main()

    def test_main_prerequisite_error_preserves_explicit_fault_and_records_old_snapshot(self):
        previous = self.previous(status="fault_halted", reason="original_fault")
        self.save(previous)
        self.assertEqual(self.call_main_with_prerequisite_failure(), 2)
        self.assertEqual(self.read_status(), previous)
        self.assertEqual(self.audit()[0]["previous_runtime_status"], previous)
        error = json.loads((self.config.output_dir / "m15_runtime_prerequisite_error.json").read_text())
        self.assertIn("offline_sdk_sentinel", error["reason"])
        self.assert_lock_released()

    def test_main_prerequisite_error_audits_before_replacing_normal_old_state_with_block(self):
        previous = self.previous()
        self.save(previous)
        self.assertEqual(self.call_main_with_prerequisite_failure(), 2)
        self.assertEqual(self.audit()[0]["previous_runtime_status"], previous)
        self.assertEqual(self.read_status()["status"], "blocked_sdk_prerequisite")
        self.assertEqual(self.read_status()["runtime_boot_id"], NEW_BOOT)

    def test_main_failed_probe_never_overwrites_live_run_lock_owner_status(self):
        previous = self.previous(runtime_boot_id=NEW_BOOT)
        self.save(previous)
        lock = runtime.acquire_runtime_run_lock(self.config.output_dir)
        try:
            self.assertEqual(self.call_main_with_prerequisite_failure(), 2)
            self.assertEqual(self.read_status(), previous)
        finally:
            lock.close()

    def test_main_prerequisite_audit_failure_preserves_state_and_releases_lock(self):
        previous = self.previous()
        self.save(previous)
        with patch.object(runtime, "append_runtime_boot_audit", side_effect=OSError("audit_full")):
            with self.assertRaisesRegex(OSError, "audit_full"):
                self.call_main_with_prerequisite_failure()
        self.assertEqual(self.read_status(), previous)
        self.assert_lock_released()


if __name__ == "__main__":
    unittest.main()
