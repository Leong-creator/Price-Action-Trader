"""Fail-closed boot recovery evidence. No SDK, process control, or state reset.

Call under the runtime's global start/run locks before overwriting old status.
An allowed result only permits fresh initialization, never order dispatch.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

BOOT_ID_SOURCE = "linux_proc_boot_id"
RUNTIME_SCRIPT = "run_m15_longbridge_sdk_runtime.py"
FAULT_FLAGS = (
    "market_data_fault_halted", "account_snapshot_circuit_open",
    "worker_circuit_open", "accountcircuit",
)


def _boot_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = UUID(value.strip())
    except ValueError:
        return ""
    # Only the canonical nonzero kernel UUID format is accepted, not timestamps.
    return str(parsed) if parsed.int and str(parsed) == value.strip().lower() else ""


def read_runtime_boot_identity(proc_root: Path = Path("/proc")) -> dict[str, str]:
    """Read the Linux/WSL kernel boot identity; never estimate it from uptime."""
    try:
        boot_id = _boot_id((proc_root / "sys/kernel/random/boot_id").read_text(encoding="ascii"))
        error = "" if boot_id else "invalid_kernel_boot_id"
    except (OSError, UnicodeError) as exc:
        boot_id, error = "", type(exc).__name__
    return {
        "runtime_boot_id": boot_id,
        "runtime_boot_id_source": BOOT_ID_SOURCE,
        "runtime_boot_id_error": error,
    }


def _pid(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    try:
        result = int(value)
    except ValueError:
        return None
    return result if result > 0 else None


def _process_observation(pid: int, proc_root: Path) -> dict[str, Any]:
    directory = proc_root / str(pid)
    try:
        before = (directory / "stat").read_text(encoding="utf-8")
        argv = (directory / "cmdline").read_bytes().split(b"\0")
        after = (directory / "stat").read_text(encoding="utf-8")
        # comm may contain spaces and parentheses; field 22 follows the final ')'.
        fields = before.rsplit(")", 1)[1].split()
        after_fields = after.rsplit(")", 1)[1].split()
        start_ticks = fields[19]
        if not start_ticks.isdigit() or start_ticks != after_fields[19]:
            raise ValueError("process_identity_changed")
        if fields[0] in {"Z", "X"} and after_fields[0] in {"Z", "X"}:
            kind = "exited"
        elif any(arg.rsplit(b"/", 1)[-1] == RUNTIME_SCRIPT.encode() for arg in argv) and b"--watch" in argv:
            kind = "runtime"
        else:
            kind = "unrelated"
        return {"pid": pid, "kind": kind, "start_ticks": start_ticks}
    except FileNotFoundError:
        # A missing cmdline is not absence if the PID directory is still there.
        try:
            directory.stat()
        except FileNotFoundError:
            return {"pid": pid, "kind": "absent"}
        except OSError:
            pass
        return {"pid": pid, "kind": "unknown", "error": "partial_proc_entry"}
    except (OSError, UnicodeError, ValueError, IndexError) as exc:
        return {"pid": pid, "kind": "unknown", "error": type(exc).__name__}


def collect_runtime_process_evidence(
    previous_status: dict[str, Any], *, proc_root: Path = Path("/proc"),
) -> dict[str, Any]:
    """Scan all visible runtime instances, not just the stale PID/config.

The calling launcher/watch process is excluded. The caller must hold the
global locks: a process snapshot alone cannot prevent concurrent launch.
Permission errors, partial procfs data and PID reuse during reads fail closed.
"""
    previous_pid = _pid(previous_status.get("runtime_pid"))
    own_pid = os.getpid()
    evidence: dict[str, Any] = {
        "previous_pid": previous_pid,
        "previous_pid_observation": {"kind": "unknown", "error": "invalid_previous_pid"},
        "matching_runtime_pids": [], "unknown_pids": [], "scan_complete": False,
        "excluded_current_pid": own_pid,
    }
    if previous_pid == own_pid:
        evidence["previous_pid_observation"] = {"pid": own_pid, "kind": "current_launcher"}
    elif previous_pid is not None:
        evidence["previous_pid_observation"] = _process_observation(previous_pid, proc_root)
    try:
        entries = list(proc_root.iterdir())
    except OSError as exc:
        evidence["scan_error"] = type(exc).__name__
        return evidence
    if not any(entry.name.isdigit() for entry in entries):
        evidence["scan_error"] = "empty_proc_snapshot"
        return evidence
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            continue
        observed = _process_observation(int(entry.name), proc_root)
        if observed["kind"] == "runtime":
            evidence["matching_runtime_pids"].append(int(entry.name))
        elif observed["kind"] == "unknown":
            evidence["unknown_pids"].append(int(entry.name))
    evidence["matching_runtime_pids"].sort()
    evidence["unknown_pids"].sort()
    evidence["scan_complete"] = not evidence["unknown_pids"]
    return evidence


def runtime_fault_markers(status: dict[str, Any]) -> list[str]:
    """Faults cannot be cleared by a boot, config change, or status age."""
    value = str(status.get("status") or "").strip().lower()
    markers = []
    if value.startswith(("fault", "blocked", "halted_account")) or "accountcircuit" in value or "account_circuit" in value:
        markers.append(f"status:{value}")
    markers.extend(key for key in FAULT_FLAGS if status.get(key))
    active_flags = set(FAULT_FLAGS) | {
        "fault_halted", "requires_manual_reconciliation", "pending_reconciliation",
        "confirmation_required", "sdk_pending_confirmation", "pending_confirmation",
        "unresolved_submission_count", "pending_confirmation_count",
        "unconfirmed_submission", "unknown_submission",
    }

    def inspect(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            state = str(value.get("status") or "").lower()
            if path and any(token in state for token in (
                "fault_halted", "pending_reconciliation", "submission_state_unknown",
                "submit_unconfirmed", "submission_journal_failed",
            )):
                markers.append(f"{path}.status:{state}")
            if value.get("submission_journal_outcome") in {"intent", "unknown"}:
                markers.append(f"{path + '.' if path else ''}submission_journal_outcome")
            for key, child in value.items():
                # Prior boot decisions are evidence, not the current fault state.
                if key in {"runtime_boot_recovery", "previous_runtime_status"}:
                    continue
                child_path = f"{path}.{key}" if path else key
                if key in active_flags and child and child_path not in markers:
                    markers.append(child_path)
                if isinstance(child, (dict, list)):
                    inspect(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                inspect(child, f"{path}[{index}]")

    inspect(status)
    return markers


def classify_runtime_boot_state(
    previous_status: dict[str, Any], *,
    current_identity: dict[str, str] | None = None,
    process_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an auditable decision without mutating or clearing any state.

manual_required also covers a same-boot crash with a fresh heartbeat. A
same-boot live owner is reported separately; its health gates still apply.
"""
    identity = read_runtime_boot_identity() if current_identity is None else current_identity
    processes = collect_runtime_process_evidence(previous_status) if process_evidence is None else process_evidence
    old_boot = _boot_id(previous_status.get("runtime_boot_id"))
    new_boot = _boot_id(identity.get("runtime_boot_id"))
    reliable = bool(
        old_boot and new_boot
        and previous_status.get("runtime_boot_id_source") == BOOT_ID_SOURCE
        and identity.get("runtime_boot_id_source") == BOOT_ID_SOURCE
        and not previous_status.get("runtime_boot_id_error")
        and not identity.get("runtime_boot_id_error")
    )
    relation = ("same_boot" if old_boot == new_boot else "cross_boot") if reliable else "unknown_boot"
    faults = runtime_fault_markers(previous_status)
    status_value = previous_status.get("status")
    observation = processes.get("previous_pid_observation") or {}
    complete = processes.get("scan_complete") is True and not processes.get("unknown_pids") and not processes.get("scan_error")
    matching = processes.get("matching_runtime_pids")
    absent = bool(
        complete and matching == []
        and _pid(previous_status.get("runtime_pid")) is not None
        and _pid(previous_status.get("runtime_pid")) == processes.get("previous_pid")
        and observation.get("kind") in {"absent", "exited", "unrelated", "current_launcher"}
    )
    if faults:
        action, reason = "manual_required", "explicit_fault_latched"
    elif status_value not in {"running", "connecting"}:
        action, reason = "no_boot_recovery", "previous_status_not_running_or_connecting"
    elif relation == "unknown_boot":
        action, reason = "manual_required", "reliable_boot_identity_missing"
    elif relation == "same_boot":
        if (
            complete and observation.get("kind") == "runtime"
            and processes.get("previous_pid") == _pid(previous_status.get("runtime_pid"))
            and processes.get("previous_pid") in (matching or [])
            and str(previous_status.get("runtime_process_start_ticks") or "")
            == str(observation.get("start_ticks") or "")
            and str(observation.get("start_ticks") or "").isdigit()
        ):
            action, reason = "existing_runtime", "same_boot_runtime_present_health_check_required"
        else:
            action, reason = "manual_required", "same_boot_crash_or_unverified_owner"
    elif absent:
        action, reason = "reinitialize", "normal_cross_boot_stale_runtime"
    else:
        action, reason = "manual_required", "cross_boot_process_absence_not_proven"
    return {
        "schema_version": 1, "checked_at": datetime.now(UTC).isoformat(),
        "boot_relation": relation, "action": action, "reason": reason,
        "allow_reinitialize": action == "reinitialize", "fault_markers": faults,
        "previous_status": status_value, "previous_boot_id": old_boot,
        "current_identity": dict(identity), "process_evidence": processes,
        "dispatch_authorized": False,
        "authorization_policy": "explicit_dispatch_and_current_authorization_and_all_existing_gates",
    }


def append_runtime_boot_audit(
    path: Path, decision: dict[str, Any], previous_status: dict[str, Any],
) -> None:
    """Durably append the decision and old snapshot before any initialization.

Errors propagate: callers must abort startup on audit failure. The global
start/run locks serialize writers. This function never overwrites runtime status.
"""
    snapshot = json.dumps(previous_status, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    record = {
        "event": "runtime_boot_state_evaluated", "decision": decision,
        "previous_runtime_status": previous_status,
        "previous_status_sha256": hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
    }
    encoded = (json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        if handle.write(encoded) != len(encoded):
            raise OSError("boot_audit_short_write")
        handle.flush()
        os.fsync(handle.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
