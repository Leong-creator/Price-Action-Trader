# M15 boot state handoff

## Scope and status

Base: `origin/main` at `18a0b44`. Branch: `codex/fix-m15-boot-state-20260908`.
Worktree: `/tmp/pat-m15-boot-state-20260908`.

The boot helper and Windows launcher source fix are implemented and tested.
Runtime integration is intentionally NOT applied: the main task owns
`scripts/run_m15_longbridge_sdk_runtime.py` and
`scripts/start_m15_trading_stack_after_boot.sh`.
This is not a deployed startup recovery or a completed market-data acceptance.
No broker calls, proxy changes, orders, machine task changes or runtime starts.
The main task must integrate, review and update the active plan/status; this
branch does not edit shared status documents concurrently.

## Decision contract

`read_runtime_boot_identity()` reads only `/proc/sys/kernel/random/boot_id`.
Persist ALL three returned fields on NEW runtime status: `runtime_boot_id`,
`runtime_boot_id_source`, `runtime_boot_id_error`. The source must be
`linux_proc_boot_id`. An unavailable, malformed or zero UUID is unknown.
There is no wall-clock, heartbeat-age, PID-start-time or uptime boot fallback.
This identifies the Linux/WSL kernel boot, not a Windows logon. The supported
scope is the same trusted runtime filesystem and visible Linux PID namespace;
copied status from another machine is not an approved migration mechanism.

`classify_runtime_boot_state(previous_status)` collects read-only procfs
evidence and returns `boot_relation`, `action`, `reason`, `fault_markers`,
`allow_reinitialize`, boot IDs, and `process_evidence`.

| Evidence | Action | Automatic reset |
| --- | --- | --- |
| Any `fault*`, `blocked*`, `halted_account*`, accountcircuit status or fault flag | `manual_required` / `explicit_fault_latched` | Never, including changed config |
| Same boot, exact old live PID/start ticks | `existing_runtime` | Never; retain existing health gates |
| Same boot, old process dead/reused/unverified | `manual_required` | Never, even a fresh heartbeat |
| Missing/unreliable old or current boot identity | `manual_required` | Never; legacy state needs manual diagnosis |
| Different reliable boot IDs, old `running/connecting`, no fault flags, proven absence | `reinitialize` | Fresh initialization only |
| Different boots but live runtime anywhere or incomplete process evidence | `manual_required` | Never |
| Other status | `no_boot_recovery` | No boot-based exception; caller must apply ordinary stopped/new-state policy |

Proven absence requires a complete visible `/proc` scan with no matching
`run_m15_longbridge_sdk_runtime.py --watch` instance under ANY config and a
valid old PID that is absent, exited, provably unrelated, or reused by the
current launcher. Permission failures, partial proc entries and changing
process start ticks fail closed. Old PID absence alone is not sufficient.
This snapshot does not replace kernel `flock`; global start/run locks remain
mandatory. No process is signalled, killed, deleted or restarted by the helper.

Fault flags include `market_data_fault_halted`,
`account_snapshot_circuit_open`, `worker_circuit_open`, and `accountcircuit`.
Nonempty malformed flag values conservatively count as faults. Old account
snapshot age alone is stale evidence across a real reboot, not an account
circuit reset; a fresh account snapshot and all current gates are still needed.

`append_runtime_boot_audit(path, decision, previous_status)` appends the FULL
old status snapshot, its canonical-JSON SHA256, the decision and proc evidence
to JSONL, then fsyncs the file and containing directory. Any failure propagates
and must abort startup BEFORE old status is overwritten. Use
`config.output_dir / "m15_runtime_boot_audit.jsonl"`. Never delete the old
fault report to enable boot recovery. Audit access/retention should follow
existing account-status artifacts; this includes the old status contents.

`dispatch_authorized` is always false. The decision grants neither dispatch,
current-date user authorization, complete-session acceptance, account health,
deployment approval nor signal replay permission.

## Exact runtime edits for the main task

These snippets target the base revision above; the owner should reconcile them
with its concurrent runtime edits. They are not a patch already applied here.

### 1. Imports and shared guarded decision

Add after the existing `scripts.*` imports:

```python
from scripts.m15_runtime_boot_identity_lib import (
    append_runtime_boot_audit,
    classify_runtime_boot_state,
    read_runtime_boot_identity,
)
```

Add before `start_runtime_daemon`:

```python
def checked_runtime_boot_startup(config: Any) -> dict[str, Any]:
    # Called only while holding the global start lock or global run lock.
    try:
        previous = json.loads(config.runtime_status_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        previous = {}
    if not isinstance(previous, dict):
        raise RuntimeError("m15_runtime_status_invalid_manual_diagnosis_required")
    decision = classify_runtime_boot_state(previous)
    append_runtime_boot_audit(
        config.output_dir / "m15_runtime_boot_audit.jsonl", decision, previous,
    )
    if decision["action"] == "manual_required":
        raise RuntimeError("m15_runtime_fault_latched_manual_diagnosis_required:" + decision["reason"])
    if decision["action"] == "no_boot_recovery" and previous and previous.get("status") not in {"stopped", "operator_stopped"}:
        raise RuntimeError("m15_runtime_status_unrecognized_manual_diagnosis_required")
    if not decision["allow_reinitialize"] and runtime_requires_health_replacement(previous, config):
        raise RuntimeError("m15_runtime_fault_latched_manual_diagnosis_required")
    return decision
```

Invalid JSON, encoding/permission errors and audit write errors deliberately
propagate. Do NOT use `_read_runtime_status`'s catch-all `{}` fallback for a
startup decision. Do NOT gate the explicit-fault decision on fingerprint equality.

### 2. Replace the daemon's fingerprint-scoped terminal lock

In `start_runtime_daemon`, inside `GLOBAL_RUNTIME_START_LOCK`, replace exactly
the block from `terminal_same_build = bool(` through its following
`if terminal_same_build: raise RuntimeError(...)` with:

```python
        boot_decision = checked_runtime_boot_startup(config)
        if boot_decision["allow_reinitialize"]:
            # Old lock/PID file numbers may belong to unrelated current-boot
            # processes. Do not signal them or reuse old dispatch intent.
            existing = None
```

Keep the existing instance checks, global lock, child command construction and
`if args.dispatch: command.append("--dispatch")`. Never append `--dispatch`
from old status. Do not clear runtime status in the parent; the child rechecks
under the kernel run lock and initializes afresh only after durable audit.

### 3. Guard direct watch and write connecting identity before SDK work

In `run_watch`, immediately after the `run_lock is None` return and BEFORE
`run_lock.seek(0)`, add:

```python
    try:
        boot_decision = checked_runtime_boot_startup(config)
        runtime_boot_identity = read_runtime_boot_identity()
    except BaseException:
        fcntl.flock(run_lock.fileno(), fcntl.LOCK_UN)
        run_lock.close()
        raise
```

Move the existing local initialization of `run_id`, `runtime_started_at` and
`runtime_process_start_ticks` above `cleanup_orphaned_sdk_runtime_children`
and `require_sdk_contract()`. After those identity variables are initialized,
but before any SDK/child work, write an initial status:

```python
    build_status(
        config, status="connecting", reason="fresh_runtime_initialization",
        extra={
            **runtime_boot_identity,
            "runtime_boot_recovery": boot_decision,
            "run_id": run_id,
            "runtime_pid": os.getpid(),
            "runtime_started_at": runtime_started_at,
            "runtime_process_start_ticks": runtime_process_start_ticks,
            "dispatch_requested": bool(dispatch_requested),
            "dispatch_enabled": False,
        },
    )
```

Move the startup block inside a cleanup/exception boundary as part of the
runtime owner's change: every initialization failure must preserve a
`fault_halted` report and release the run lock, including failures before the
existing main loop's `try/finally`. Do not leave a known SDK initialization
failure marked `connecting`. Audit failure must not overwrite old status.

At BOTH existing `build_status(..., status="fault_halted", extra={...})`
in `halt_market_data` and `build_status(..., status="running" if worker_ready
else "connecting", extra={...})`, insert the following first in `extra`:

```python
                    **runtime_boot_identity,
                    "runtime_boot_recovery": boot_decision,
```

All other status-writing paths that create new runtime/fault state must also
persist this process's identity. Do NOT stamp old status with the current boot
in `--status`, startup inspection, or an automatic migration. In particular,
an old status without boot fields cannot be made eligible by backfilling them.
`main()` currently writes `blocked_sdk_prerequisite` before the daemon/watch
guard; preserve/audit the old snapshot before that replacement too, without
letting a prerequisite error clear the earlier terminal fault.

### 4. Follow-through checks

- Parent AND direct `--watch` must pass the guard before SDK/account calls.
- Hold kernel run lock through initialization; proc evidence is not a lock.
- After cross-boot eligibility ignore stale PID/lock numbers only, never
  signal a reused unrelated process. Do not bypass a currently held run lock.
- `--status` should expose persisted fault and boot decision alongside observed
  liveness, not misleadingly hide a real fault as merely `stopped`.
- Add the new helper to the deployment source-hash manifest list in
  `scripts/m15_deployment_governance_lib.py`; this branch does not sign or
  regenerate production deployment manifests.
- Keep current-date explicit dispatch authorization owned by the main task.
  Preserve complete real-session, quote integrity, SDK lifecycle, account-age,
  account-circuit, deployment and risk gates, and no historical signal replay.
- Existing legacy reports remain manual-only on the first deployment. There is
  no automatic one-time bootstrap cleanup for missing boot IDs.

## Windows return-code fix

Only `scripts/install_m15_windows_startup_task.ps1` was edited. The generated
VBS now uses `exitCode = shell.Run(command, 0, True)` followed by
`WScript.Quit exitCode`; WSL executable/distro/script arguments are quoted.
The direct scheduled-task WSL action already reports its process exit status.
The fallback used to run asynchronously (`False`) and report only launcher
success, hiding a failed bootstrap. The source change does not repair an
already installed VBS until a separately authorized install/update is performed.
No installer was run. No task was created, changed, started or deleted.
Native PowerShell/VBS execution remains unverified (`pwsh` unavailable).

## Standard handoff

```yaml
task_id: m15-boot-state-20260908
role: boot-helper-implementation
branch_or_worktree: codex/fix-m15-boot-state-20260908 /tmp/pat-m15-boot-state-20260908
objective: Permit proven normal cross-kernel-boot initialization without clearing actual faults
status: partial
files_changed:
  - scripts/m15_runtime_boot_identity_lib.py
  - tests/unit/test_m15_boot_identity.py
  - scripts/install_m15_windows_startup_task.ps1
  - docs/handoffs/m15-boot-state-runtime-integration-20260908.md
interfaces_changed:
  - read_runtime_boot_identity(proc_root=Path('/proc')) -> dict
  - collect_runtime_process_evidence(previous_status, proc_root=Path('/proc')) -> dict
  - runtime_fault_markers(status) -> list[str]
  - classify_runtime_boot_state(previous_status, current_identity=None, process_evidence=None) -> dict
  - append_runtime_boot_audit(path, decision, previous_status) -> None
commands_run:
  - git fetch origin main
  - git worktree add -b codex/fix-m15-boot-state-20260908 /tmp/pat-m15-boot-state-20260908 origin/main
  - python -m unittest tests.unit.test_m15_boot_identity -v
  - python -m unittest tests.unit.test_m15_boot_identity tests.unit.test_m15_longbridge_sdk_runtime tests.unit.test_m15_background_watchdog tests.unit.test_m15_deployment_governance
  - python -m py_compile scripts/m15_runtime_boot_identity_lib.py tests/unit/test_m15_boot_identity.py
  - bash scripts/run_repository_governance_ci.sh
  - git diff --cached --check
tests_run:
  - 31 boot-helper/Windows-source tests passed, including parameterized fault/boot/PID matrices
  - 178 combined boot/runtime/watchdog/deployment tests passed
  - Repository governance passed including 6 deployment tests, compile, secret scan, tracked large-file check and diff check
assumptions:
  - Persisted status and procfs are trusted local Linux/WSL data
  - Callers retain global locks and abort if durable audit fails
  - Existing legacy status cannot be auto-migrated
risks:
  - High-risk startup boundary requires main-task integration and human review before deployment
  - No native PowerShell or VBS execution was available
  - No callable subagent tool was available; independent reviewer must be supplied by main task
  - A successful hidden bootstrap exit code is not proof of completed SDK initialization
qa_focus:
  - Integrate helper in daemon and direct watch, before SDK calls and state overwrite
  - Persist boot identity during early connecting, normal heartbeat and all faults
  - Initialization failure must fault and release lock; audit failure must preserve prior state
  - Fault flags and changed fingerprints never unlock automatically
  - Same-boot crash, legacy state, cross-boot duplicate and unknown process evidence remain manual
  - Cross-boot unrelated PID reuse must not invoke shutdown or reuse dispatch
  - Date-limited authorization, all market/account gates and source-hash manifest remain enforced
rollback_notes:
  - Revert this topic commit before runtime integration; after integration revert its dependent changes together
  - No machine task or production artifact rollback is needed for this branch
next_recommended_action: Main task integrates the snippets, adds mocked startup tests, reviews, and merges; do not deploy this helper alone as a completed repair
needs_user_decision: false
user_decision_needed: null
```
