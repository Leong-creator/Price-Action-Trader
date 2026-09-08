# M15 Submission Journal And Shared Trade Budget Handoff

```yaml
task_id: M15-paper-durable-submit-20260908
role: implementation
branch_or_worktree: /tmp/pat-paper-session-20260908
objective: Close the submit-before-batch-ledger crash window and enforce shared SDK admission deadlines
status: success
files_changed:
  - scripts/m15_submission_journal_lib.py
  - scripts/m15_longbridge_sdk_runtime_lib.py
  - scripts/m15_official_async_trade_lib.py
  - scripts/run_m15_longbridge_sdk_runtime.py
  - tests/unit/test_m15_submission_journal.py
  - tests/unit/test_m15_async_trade_runtime_integration.py
  - tests/unit/test_m15_paper_order_timeouts.py
  - docs/handoffs/m15-submission-journal-integrated-20260908.md
interfaces_changed:
  - SdkRealtimePaperClient optional submission_journal_path
  - SubmissionJournal begin/finish/snapshot/reconcile
  - BoundedTradeRequestGate.begin_cycle(deadline_monotonic, reserve_seconds=2.0)
  - OfficialAsyncTradeBridge.maximum_request_wait_seconds
commands_run:
  - unittest (full command below)
  - compile seven changed Python files in memory
  - git diff --check
tests_run:
  - 330 combined tests passed in 41.399 seconds
  - Final diagnostic-field change verified by 65 focused tests in 0.606 seconds
  - Includes 21 journal tests, 15 timeout/budget tests and 15 runtime trade integration tests
assumptions:
  - Local filesystem honors fsync; journal file and parent directory are retained
  - Runtime passes verified fresh lb_papertrading account snapshots to reconciliation
  - Production uses the mandatory journal path passed by build_sdk_trade_clients
risks:
  - No actual broker connection, order, quote subscription, power-loss or native SDK cancellation test
  - Corrupt/torn journals fail closed without automatic truncation or repair
  - Journal deletion, external replacement or rollback of durable evidence is not supported
  - Legacy signal IDs too long for intact PAT-RT attribution fail before SDK invocation
  - SDK wait reservation excludes disk fsync, CPU work and native transport lifecycle
qa_focus:
  - Before SDK invocation, fsync intent containing stable key, exact transmitted remark and allowlisted order payload
  - After receipt, fsync acknowledged/unknown result, never Filled or profit data
  - Before-write storage failure forbids send; after-write storage failure remains unknown and halts
  - Restarted unresolved intents block same-key resubmission and all new submit/cancel/replace calls
  - Unique exact full remark plus broker order ID releases unresolved state; empty or ambiguous orders do not
  - Admission refused before SDK callback is durable not_sent and permits later fresh keys, not replay
  - Shared gate reserves 2 seconds per call within each 5-second runtime loop cycle and never sleeps
rollback_notes:
  - No commit or staging; preserve other agents' edits in shared files
  - Do not delete the production journal or disable its gate as a rollback technique
next_recommended_action: Main agent adds journal module to deployment manifest, reviews high-risk changes, then commits and deploys together
needs_user_decision: false
user_decision_needed: null
```

## Integration

Production build uses `config.output_dir / "m15_sdk_submission_journal.jsonl"`.
Both paper and flatten references share one client, journal and gate. The bridge
uses an explicit `request_timeout=2.0`; it reports that same value through
`maximum_request_wait_seconds`. The runtime starts each while iteration with
`execution_request_gate.begin_cycle(time.monotonic() + 5, reserve_seconds=2.0)`.
When `now + reserve > deadline`, the gate raises `TradeRequestNotSent` before
invoking the SDK; it does not poison/rebuild the bridge or reset rate quota.

Startup `ExitStack` closes a created bridge if subsequent initialization fails;
the loop's finally calls Tesla's `cleanup_runtime_resources`, which also closes
the bridge even when quote cleanup fails. All three former runtime trade rebuild
sites now reuse/check the original bridge or stay fault halted. These patches do
not change the attribution protocol, strategy quantity limits or performance
calculation, and do not replay legacy orders.

Runtime status now includes `trade_execution.api`, `adapter`,
`request_deadline_seconds`, `cycle_budget_seconds`, `call_reserve_seconds` and
`submission_journal` (pending count/error). `begin_cycle` is called exactly once
at the parent loop start, never for individual requests. Recovered journal
responses explicitly carry `sdk_request_sent=false`,
`submission_journal_reused=true` and, for known IDs, `recovered_order=true`.
When acknowledgement fsync fails, `observed_broker_order_id` preserves the SDK
diagnostic ID separately; `submitted=false`, empty canonical `order_id` and
`confirmation_required=true` remain unchanged.

## Evidence

The executor-only baseline fault injection accepted a fake submission, failed at
the end-of-batch ledger append, then submitted again on the next run. With the
production journal-enabled client, the same failure/restart leaves an unresolved
durable intent and the total fake SDK submit count stays at one. A successful
acknowledgement that was journaled before a ledger failure is also recovered by
key without a second SDK call. This verifies the targeted offline crash window,
not every form of hardware/storage loss or native broker behavior.

Actual ID generators for modern entry, exit, PA004 cleanup and the authorized
account cleanup path pass begin(). A 60-character legacy signal ID cannot fit an
intact signal token in the 64-character SDK remark and is deliberately rejected
before sending. No alternate remark protocol or legacy replay was introduced.

## Reproduce

```bash
cd /tmp/pat-paper-session-20260908
/home/hgl/projects/Price-Action-Trader/.venv/bin/python -B -m unittest tests.unit.test_m15_submission_journal tests.unit.test_m15_paper_order_timeouts tests.unit.test_m15_async_trade_runtime_integration tests.unit.test_m15_longbridge_sdk_runtime tests.unit.test_m15_longbridge_realtime_execution tests.unit.test_m15_longbridge_sdk_account_worker tests.unit.test_m15_boot_runtime_integration tests.unit.test_m15_boot_review_regressions tests.unit.test_m15_session_evidence tests.unit.test_m15_deployment_governance
```
