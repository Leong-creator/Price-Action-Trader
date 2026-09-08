from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import m15_runtime_boot_identity_lib as boot


OLD_BOOT = "ee94d3c7-8215-4f33-a202-cfa0a369a525"
NEW_BOOT = "ed085ce1-848e-4c45-a644-8071dfffd8eb"


def identity(value: str = NEW_BOOT) -> dict:
    return {"runtime_boot_id": value, "runtime_boot_id_source": boot.BOOT_ID_SOURCE}


def state(**changes) -> dict:
    return {
        **identity(OLD_BOOT), "status": "running", "runtime_pid": 321,
        "runtime_process_start_ticks": "12345", "run_id": "old-run",
        "generated_at": "2026-09-07T22:00:00+00:00",
        "config_fingerprint": "old-config", "dispatch_requested": True,
        "dispatch_enabled": True, **changes,
    }


def processes(kind: str = "absent", **changes) -> dict:
    return {
        "previous_pid": 321, "previous_pid_observation": {
            "pid": 321, "kind": kind, "start_ticks": "12345",
        },
        "matching_runtime_pids": [321] if kind == "runtime" else [],
        "unknown_pids": [], "scan_complete": True, **changes,
    }


def classify(previous=None, evidence=None, current=None) -> dict:
    return boot.classify_runtime_boot_state(
        state() if previous is None else previous,
        current_identity=identity() if current is None else current,
        process_evidence=processes() if evidence is None else evidence,
    )


def proc_entry(root: Path, pid: int, argv=None, *, name="python", status="S", ticks="12345") -> None:
    directory = root / str(pid)
    directory.mkdir(parents=True, exist_ok=True)
    fields = [status] + ["0"] * 18 + [ticks]
    (directory / "stat").write_text(f"{pid} ({name}) {' '.join(fields)}\n", encoding="utf-8")
    (directory / "cmdline").write_bytes(b"\0".join(argv or [b"python", b"unrelated.py"]) + b"\0")


class BootDecisionTest(unittest.TestCase):
    def test_only_normal_cross_boot_is_eligible_and_does_not_authorize_dispatch(self):
        for status in ("running", "connecting"):
            for kind in ("absent", "exited", "unrelated", "current_launcher"):
                with self.subTest(status=status, kind=kind):
                    result = classify(state(status=status), processes(kind))
                    self.assertTrue(result["allow_reinitialize"])
                    self.assertEqual(result["boot_relation"], "cross_boot")
                    self.assertFalse(result["dispatch_authorized"])

    def test_fault_statuses_override_boot_pid_and_config(self):
        for status in ("fault_halted", "blocked", "blocked_sdk_prerequisite",
                       "halted_account_snapshot_circuit", "accountcircuit", "account_circuit_open"):
            for current in (identity(), identity(OLD_BOOT), identity("")):
                for fingerprint in ("old-config", "different-config", ""):
                    with self.subTest(status=status, current=current, fingerprint=fingerprint):
                        result = classify(state(status=status, config_fingerprint=fingerprint), current=current)
                        self.assertEqual(result["reason"], "explicit_fault_latched")
                        self.assertEqual(result["action"], "manual_required")
                        self.assertFalse(result["allow_reinitialize"])

    def test_fault_flags_override_running_even_after_reboot(self):
        for flag in boot.FAULT_FLAGS:
            for value in (True, 1, "true", "false", {"reason": "fault"}):
                with self.subTest(flag=flag, value=value):
                    result = classify(state(**{flag: value}))
                    self.assertIn(flag, result["fault_markers"])
                    self.assertFalse(result["allow_reinitialize"])

    def test_false_fault_flags_do_not_block_normal_reboot(self):
        for value in (False, None, 0, ""):
            self.assertTrue(classify(state(**dict.fromkeys(boot.FAULT_FLAGS, value)))["allow_reinitialize"])

    def test_same_boot_crash_never_recovers_even_with_fresh_heartbeat(self):
        for status in ("running", "connecting"):
            for timestamp in ("2026-09-08T12:00:00+00:00", "2000-01-01T00:00:00Z", "", "invalid"):
                for kind in ("absent", "exited", "unrelated", "unknown", "current_launcher"):
                    with self.subTest(status=status, timestamp=timestamp, kind=kind):
                        result = classify(state(status=status, generated_at=timestamp), processes(kind), identity(OLD_BOOT))
                        self.assertEqual(result["boot_relation"], "same_boot")
                        self.assertEqual(result["action"], "manual_required")

    def test_same_boot_live_owner_requires_health_checks_not_reinitialization(self):
        result = classify(evidence=processes("runtime"), current=identity(OLD_BOOT))
        self.assertEqual(result["action"], "existing_runtime")
        self.assertFalse(result["allow_reinitialize"])

    def test_same_boot_pid_reused_by_another_runtime_is_not_existing_owner(self):
        for ticks in ("", "different", "999"):
            result = classify(state(runtime_process_start_ticks=ticks), processes("runtime"), identity(OLD_BOOT))
            self.assertEqual(result["action"], "manual_required")

    def test_live_runtime_blocks_cross_boot_even_when_old_pid_absent(self):
        for evidence in (processes("runtime"), processes(matching_runtime_pids=[777])):
            result = classify(evidence=evidence)
            self.assertEqual(result["reason"], "cross_boot_process_absence_not_proven")
            self.assertFalse(result["allow_reinitialize"])

    def test_incomplete_or_inconsistent_process_evidence_fails_closed(self):
        for evidence in ({}, processes("unknown"), processes(scan_complete=False),
                         processes(scan_complete="true"), processes(unknown_pids=[77]),
                         processes(scan_error="PermissionError"), processes(previous_pid=111),
                         processes(matching_runtime_pids=None)):
            with self.subTest(evidence=evidence):
                self.assertFalse(classify(evidence=evidence)["allow_reinitialize"])

    def test_invalid_old_pid_is_not_absence(self):
        for pid in (None, "", "bad", 0, -1, True, 321.0):
            self.assertFalse(classify(state(runtime_pid=pid))["allow_reinitialize"])

    def test_missing_malformed_or_untrusted_boot_identity_is_manual(self):
        for changes in ({"runtime_boot_id": ""}, {"runtime_boot_id": None},
                        {"runtime_boot_id": "2026-09-08"}, {"runtime_boot_id_source": "uptime"},
                        {"runtime_boot_id_source": ""}, {"runtime_boot_id_error": "read_failure"},
                        {"runtime_boot_id": "00000000-0000-0000-0000-000000000000"}):
            for previous, current in ((state(**changes), identity()), (state(), {**identity(), **changes})):
                with self.subTest(previous=previous, current=current):
                    result = classify(previous, current=current)
                    self.assertEqual(result["boot_relation"], "unknown_boot")
                    self.assertEqual(result["action"], "manual_required")

    def test_legacy_status_without_boot_fields_cannot_be_migrated_automatically(self):
        previous = state()
        for key in identity():
            del previous[key]
        self.assertEqual(classify(previous)["action"], "manual_required")

    def test_other_statuses_never_grant_boot_recovery(self):
        for status in (None, "", "stopped", "operator_stopped", "unknown", "subscribed"):
            self.assertEqual(classify(state(status=status))["action"], "no_boot_recovery")

    def test_no_mutation_or_reuse_of_dispatch_snapshot_age_and_gate_results(self):
        previous = state(account_snapshot_age_seconds=999999, complete_session_gate_passed=True)
        original = copy.deepcopy(previous)
        result = classify(previous)
        self.assertTrue(result["allow_reinitialize"])
        self.assertFalse(result["dispatch_authorized"])
        self.assertEqual(previous, original)


class BootProcEvidenceTest(unittest.TestCase):
    def test_boot_id_read_is_stable_normalized_and_kernel_only(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "sys/kernel/random/boot_id"
            path.parent.mkdir(parents=True)
            path.write_text(NEW_BOOT.upper() + "\n", encoding="ascii")
            first = boot.read_runtime_boot_identity(root)
            self.assertEqual(first["runtime_boot_id"], NEW_BOOT)
            self.assertEqual(first, boot.read_runtime_boot_identity(root))
            self.assertEqual(first["runtime_boot_id_error"], "")

    def test_invalid_boot_id_no_uptime_fallback(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(boot.read_runtime_boot_identity(root)["runtime_boot_id"], "")
            path = root / "sys/kernel/random/boot_id"
            path.parent.mkdir(parents=True)
            for value in (b"", b"1234", b"\xff", b"0" * 32, NEW_BOOT.replace("-", "").encode()):
                path.write_bytes(value)
                result = boot.read_runtime_boot_identity(root)
                self.assertEqual(result["runtime_boot_id"], "")
                self.assertTrue(result["runtime_boot_id_error"])

    def test_boot_read_permission_error_is_unknown(self):
        with patch.object(Path, "read_text", side_effect=PermissionError):
            self.assertEqual(boot.read_runtime_boot_identity()["runtime_boot_id_error"], "PermissionError")

    def test_absent_old_pid_and_no_runtime(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc_entry(root, 10)
            evidence = boot.collect_runtime_process_evidence(state(), proc_root=root)
            self.assertEqual(evidence["previous_pid_observation"]["kind"], "absent")
            self.assertTrue(classify(evidence=evidence)["allow_reinitialize"])

    def test_pid_reuse_unrelated_process_and_comm_with_spaces_parentheses(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc_entry(root, 321, name="worker (daily) refresh)", ticks="555")
            evidence = boot.collect_runtime_process_evidence(state(), proc_root=root)
            self.assertEqual(evidence["previous_pid_observation"]["start_ticks"], "555")
            self.assertTrue(classify(evidence=evidence)["allow_reinitialize"])

    def test_global_scan_finds_other_config_runtime_without_stale_pid(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc_entry(root, 456, [b"python", b"/other/repo/" + boot.RUNTIME_SCRIPT.encode(), b"--watch", b"--config", b"other.json"])
            evidence = boot.collect_runtime_process_evidence(state(), proc_root=root)
            self.assertEqual(evidence["matching_runtime_pids"], [456])
            self.assertFalse(classify(evidence=evidence)["allow_reinitialize"])

    def test_status_daemon_and_substring_script_names_are_not_watch_instances(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for pid, argv in enumerate((
                [b"python", boot.RUNTIME_SCRIPT.encode(), b"--status"],
                [b"python", boot.RUNTIME_SCRIPT.encode(), b"--daemon"],
                [b"python", b"test_" + boot.RUNTIME_SCRIPT.encode(), b"--watch"],
            ), 10):
                proc_entry(root, pid, argv)
            evidence = boot.collect_runtime_process_evidence(state(), proc_root=root)
            self.assertEqual(evidence["matching_runtime_pids"], [])

    def test_current_launcher_is_excluded_including_reused_old_pid(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc_entry(root, os.getpid(), [b"python", boot.RUNTIME_SCRIPT.encode(), b"--watch"])
            previous = state(runtime_pid=os.getpid())
            evidence = boot.collect_runtime_process_evidence(previous, proc_root=root)
            self.assertEqual(evidence["previous_pid_observation"]["kind"], "current_launcher")
            self.assertTrue(classify(previous, evidence)["allow_reinitialize"])

    def test_zombie_is_exited(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc_entry(root, 321, [b"python", boot.RUNTIME_SCRIPT.encode(), b"--watch"], status="Z")
            evidence = boot.collect_runtime_process_evidence(state(), proc_root=root)
            self.assertEqual(evidence["previous_pid_observation"]["kind"], "exited")
            self.assertTrue(classify(evidence=evidence)["allow_reinitialize"])

    def test_missing_partial_malformed_proc_data_and_empty_scan_block(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertFalse(boot.collect_runtime_process_evidence(state(), proc_root=root)["scan_complete"])
            (root / "321").mkdir()
            evidence = boot.collect_runtime_process_evidence(state(), proc_root=root)
            self.assertEqual(evidence["unknown_pids"], [321])
            proc_entry(root, 321)
            (root / "321/stat").write_text("bad", encoding="utf-8")
            self.assertFalse(boot.collect_runtime_process_evidence(state(), proc_root=root)["scan_complete"])

    def test_scan_permission_failure_blocks(self):
        with patch.object(Path, "iterdir", side_effect=PermissionError):
            evidence = boot.collect_runtime_process_evidence(state())
        self.assertFalse(evidence["scan_complete"])
        self.assertEqual(evidence["scan_error"], "PermissionError")

    def test_cmdline_permission_failure_blocks(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc_entry(root, 321)
            with patch.object(Path, "read_bytes", side_effect=PermissionError):
                evidence = boot.collect_runtime_process_evidence(state(), proc_root=root)
            self.assertFalse(classify(evidence=evidence)["allow_reinitialize"])

    def test_pid_reused_during_proc_read_is_unknown(self):
        prefix = "321 (python) S " + "0 " * 18
        with patch.object(Path, "read_text", side_effect=[prefix + "123", prefix + "999"]), patch.object(Path, "read_bytes", return_value=b"python\0"):
            result = boot._process_observation(321, Path("/proc"))
        self.assertEqual(result["kind"], "unknown")


class BootAuditAndStartupTest(unittest.TestCase):
    def test_audit_retains_fault_and_reboot_snapshots_and_hashes_without_mutation(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "audit/events.jsonl"
            for previous in (state(), state(status="fault_halted")):
                original = copy.deepcopy(previous)
                boot.append_runtime_boot_audit(path, classify(previous), previous)
                self.assertEqual(previous, original)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(records), 2)
            for record in records:
                snapshot = json.dumps(record["previous_runtime_status"], ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                self.assertEqual(record["previous_status_sha256"], hashlib.sha256(snapshot.encode()).hexdigest())
            self.assertEqual(records[0]["decision"]["action"], "reinitialize")
            self.assertEqual(records[1]["decision"]["reason"], "explicit_fault_latched")

    def test_audit_write_and_fsync_errors_propagate(self):
        with TemporaryDirectory() as temporary:
            with self.assertRaises(OSError):
                boot.append_runtime_boot_audit(Path(temporary), classify(), state())
            with patch.object(boot.os, "fsync", side_effect=OSError("disk_failure")):
                with self.assertRaisesRegex(OSError, "disk_failure"):
                    boot.append_runtime_boot_audit(Path(temporary) / "audit.jsonl", classify(), state())

    def test_helper_has_no_sdk_process_control_or_dispatch_path(self):
        source = inspect.getsource(boot)
        self.assertNotIn("import longbridge", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("os.kill", source)
        self.assertNotIn("unlink(", source)

    def test_windows_fallback_waits_hidden_and_propagates_exit_code(self):
        source = (Path(__file__).resolve().parents[2] / "scripts/install_m15_windows_startup_task.ps1").read_text()
        self.assertIn('exitCode = shell.Run("$escapedWslCommand", 0, True)', source)
        self.assertIn("WScript.Quit exitCode", source)
        self.assertNotIn('shell.Run "$escapedWslCommand", 0, False', source)
        self.assertIn('`"$wslPath`" -d `"$Distro`" --exec bash `"$scriptPath`"', source)


if __name__ == "__main__":
    unittest.main()
