# M15 boot runtime integration

Implemented directly in `/tmp/pat-paper-session-20260908` at the main task's
request. These edits are NOT committed. The main task owns final review,
source manifest, shared status documents, commit and deployment.

## Final regression checkpoint

Final boot handoff status: **success**. The main task reports that its current
743-test integrated suite passes and Goodall has independently rechecked all
three boot fixes successfully. This is main-task/reviewer confirmation, not an
additional test run by this task. Earlier failed regression snapshots below
are historical. This task has stopped integration-code writes and has no
running tests. Commit, daily-input cherry-picks, liveclock integration and
deployment remain with the main task; no further code changes are planned here.

### Goodall follow-up: three scoped fixes

- Active nested `trade_context_health` faults, manual-reconciliation flags,
  unconfirmed responses and unresolved submission counts now latch boot recovery.
  Historical `runtime_boot_recovery` / `previous_runtime_status` audit objects
  are excluded; ordinary nested market-window blocks are not treated as faults.
- Startup also checks an existing submission journal locally. Durable `intent`
  or `unknown` records and corrupt journal evidence require manual reconciliation
  before initialization, even if the last runtime heartbeat predates the request.
  Acknowledged journal entries alone do not block a normal cross-boot start.
- Daemon process reuse/replacement requires the current boot identity, positive
  matching PID/start ticks, expected runtime command and matching configuration
  fingerprint. Identity mismatch raises before any shutdown or Popen. Shutdown
  receives the expected status and rechecks it before signalling/escalation.
- An unstarted worker (`pid is None`) is never joined. Resource cleanup attempts
  stop event, worker, queue, trade, account and signal restoration independently;
  cleanup errors do not replace an exception already propagating from startup.
- Added `tests/unit/test_m15_boot_review_regressions.py`: all 14 offline tests
  passed, including Goodall's exact three cases and a real unstarted multiprocessing
  Process with mocked `start` failure. No SDK connection or child was started.
- Scoped combined regression: 227 tests passed in 0.447 seconds across review,
  boot runtime, boot helper, existing runtime, async-trade integration and submission
  journal modules. Compile and diff checks passed. Test command fully exited.
- This follow-up touched only `scripts/m15_runtime_boot_identity_lib.py`, boot/
  identity/shutdown/cleanup blocks of `scripts/run_m15_longbridge_sdk_runtime.py`,
  the new review test file and this handoff. Monday fixtures and the budget code
  remain with their owners. All changes remain uncommitted in the integration tree.

- Added CLI tests for two repeated `--daemon --dispatch` invocations reusing
  the same healthy runtime and normal `--stop` followed by a new daemon.
  Boot runtime-interface tests now total 25, all passing.
- Updated four legacy source inspections to target `_run_watch_after_boot_check`
  and the WatchLoop fixture to return a mocked trade context with `check_health`
  and `close`. Original assertions are retained. These previous failures are resolved.
- Full `python -m unittest discover -s tests/unit -p 'test_m15*.py'` finished:
  703 tests, 697 passed, 6 failures, 44.915 seconds. Supplemental generation/
  rollout modules passed 7/7. Total observed: 710 tests, 704 passed, 6 failures.
- All six failures are in `test_m15_monday_refresh_acceptance`, on
  `marketdata_integrity_gate`: fixtures enable new positions without either
  `complete_session_gate_passed=true` or current explicit validation evidence.
  The gate reports 0 complete boundaries / 0 realtime bars and correctly does
  not infer acceptance from dispatch alone. This task changed neither the
  acceptance code nor its fixtures; the owner must reconcile their contract.
- Compilation and `git diff --check` passed. All commands/test sessions ended;
  the full-suite PID 19608 was confirmed absent. No test process remains from
  this task. Existing production processes were not controlled or stopped.
- The main task's subsequent shared 5-second execution-budget work is NOT
  included in this regression checkpoint. No budget code was edited here.

## Boundaries

- `checked_runtime_boot_startup` strictly reads status, audits the previous
  snapshot before mutation, and enforces the helper decision independently of
  configuration fingerprint. Corrupt/legacy/unverified state is not reset.
- The daemon checks under the start lock without rewriting old status; the
  child checks again under the run lock. The helper excludes the current child
  PID. A new fault recorded between the two checks blocks the child.
- `run_watch` owns boot validation, initial `connecting` identity, failure
  evidence and run-lock release. Existing initialization and trading loop live
  in `_run_watch_after_boot_check`; the trading algorithm was not changed by
  this task. An `ExitStack` owns partial startup resources until the original
  loop's `try/finally` takes over.
- New `connecting`, `running` and `fault_halted` statuses include current boot
  identity and the boot decision. Dispatch remains from this invocation and
  current gates, never the old report's `dispatch_requested` value.
- Startup errors write `m15_runtime_startup_failure.json` and atomically latch
  `fault_halted` in runtime status. A diagnostic write failure still attempts
  the fault latch. An existing more specific fault is preserved. Lock release
  is in an outer `finally`, including audit and fault-write failures.
- A `main` prerequisite error audits the old snapshot and records
  `m15_runtime_prerequisite_error.json`. An existing fault or live run-lock
  owner's status is not overwritten. When no process owns the run lock, a new
  prerequisite failure becomes `blocked_sdk_prerequisite`, not normal running.
- No edits by this task to the shell, Windows generator, `build_sdk_trade_clients`
  or loop trading logic. Concurrent main-task changes in those areas remain.
- No broker connections, machine task operations, runtime startup, proxy changes,
  actual VBS edits or orders. Test PIDs/processes and SDK interfaces are mocks;
  file evidence and locks are in temporary directories.

## Windows clarification

Both inspected copies of `start_m15_trading_stack_after_boot.sh`, in this
integration worktree and `/home/hgl/projects/Price-Action-Trader`, currently
treat `--keep-alive` as a retired compatibility argument. Neither contains a
keepalive loop. Therefore waiting for THAT script means waiting for one
bootstrap, not for the daemon's lifetime; it still does not prove SDK readiness.

The generator sets unlimited execution time (`PT0S` / zero TimeSpan), not a
finite timeout. Microsoft documents [PT0S as indefinite](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-executiontimelimit-settingstype-element).
The normal registration path uses `IgnoreNew`; the schtasks fallback does not
explicitly override the instance policy. The documented [IgnoreNew default
skips a new instance while the old one is running](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-multipleinstancespolicy-settingstype-element).

The installed VBS target and actual task settings were NOT queried or modified
by this task. The main task subsequently confirmed that the actual target is
the retired-keepalive one-shot bootstrap, backed up its VBS, and will deploy
the synchronous wait/exit-code change itself without rebuilding tasks.
If that VBS points to an older genuinely persistent keepalive script, `Run True`
would indeed keep the task running and `IgnoreNew` could suppress future
triggers; an actual finite timeout could stop that task. Do not extrapolate
generator settings to installed tasks. The return-code source improvement is
optional and not required for the boot-state repair. Leave actual Windows
launchers alone for this integration; no new keepalive/task design is needed.

## Handoff

```yaml
task_id: m15-boot-runtime-integration-20260908
role: boot-runtime-integration
branch_or_worktree: /tmp/pat-paper-session-20260908
objective: Integrate fail-closed cross-boot initialization and preserve early failure evidence
status: success
files_changed:
  - scripts/m15_runtime_boot_identity_lib.py
  - scripts/run_m15_longbridge_sdk_runtime.py
  - tests/unit/test_m15_boot_review_regressions.py
  - tests/unit/test_m15_boot_runtime_integration.py
  - tests/unit/test_m15_longbridge_sdk_runtime.py
  - tests/unit/test_m15_session_evidence.py
  - docs/handoffs/m15-boot-runtime-integrated-20260908.md
interfaces_changed:
  - checked_runtime_boot_startup(config)
  - _read_runtime_status_for_startup(config)
  - _run_watch_after_boot_check(config, dispatch_requested, runtime_identity, boot_decision, startup_cleanup)
commands_run:
  - python -m unittest tests.unit.test_m15_boot_runtime_integration tests.unit.test_m15_boot_identity tests.unit.test_m15_deployment_governance
  - python -m py_compile scripts/run_m15_longbridge_sdk_runtime.py tests/unit/test_m15_boot_runtime_integration.py
  - git diff --check
  - python -m unittest discover -s tests/unit -p 'test_m15*.py'
  - python -m unittest tests.unit.test_generate_m15_contract_v1_configs tests.unit.test_run_m15_contract_v1_rollout
tests_run:
  - Goodall follow-up scoped regression passed all 227 tests, including 14 new review reproductions
  - 25 new offline runtime-interface tests passed, including duplicate daemon and normal stop/restart
  - Full 703-test M15 discovery finished with 697 passed and 6 Monday-acceptance failures
  - Supplemental generation/rollout modules passed 7 tests
  - Earlier source-inspection and async-trade fixture failures resolved without weakening assertions
  - All test sessions exited; full-suite PID 19608 confirmed absent
assumptions:
  - Main task owns concurrent trade-client and trading-loop edits and final integration review
  - Existing WatchLoop fixture mocks checked_runtime_boot_startup and uses temporary output paths
risks:
  - Six Monday acceptance fixtures enable new positions without explicit complete-session or current-authorization evidence
  - Concurrent main-task execution-budget changes need a new regression after integration
  - No installed Windows task or native VBS validation was performed
  - High-risk startup changes require human review before deployment
qa_focus:
  - Nested faults and unresolved disk submission intents must forbid cross-boot initialization
  - A stale operator-stopped PID with different start ticks must trigger neither shutdown nor Popen
  - Unstarted worker cleanup must preserve the original error and still close the queue
  - Double boot check must exclude child self but reject any intervening fault
  - Early failures release run lock and stop partial account/queue resources
  - Running and fault heartbeat fields remain present after concurrent loop integration
  - Never overwrite prior fault or live owner on CLI prerequisite errors
  - No old dispatch inheritance or quote/account gate relaxation
rollback_notes:
  - Uncommitted shared worktree; reverse only boot-specific hunks, never reset concurrent changes
next_recommended_action: Main task owns commit, daily-input cherry-picks, liveclock integration and subsequent deployment validation; boot handoff is complete
needs_user_decision: false
user_decision_needed: null
```
