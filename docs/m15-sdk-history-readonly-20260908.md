# M15 SDK History Read-Only Fix

## Scope and Status

Candidate implementation and read-only validation completed on 2026-09-08.
Integration, deployment, and tonight's paper-order acceptance belong to the main
task. This branch does not authorize, submit, cancel, or replace orders. It does
not edit runtime code, production configuration, active plan, or project status.
Human review is required because the module connects to an account.

Base: `origin/main` at `18a0b44`. Branch:
`codex/fix-m15-sdk-history-readonly-20260908`.

## Verified SDK Evidence

Installed official Python package: `longbridge==4.5.0`. Official tag `v4.5.0`
resolves to `68080b64ee02836e2fec625e9605dc5389abdb17`.

- [Python synchronous binding](https://github.com/longbridge/openapi/blob/v4.5.0/python/src/trade/context.rs):
  `history_orders` accepts `start_at` / `end_at`, not `start` / `end`.
  It calls the blocking context without releasing the GIL.
- [Rust blocking runtime](https://github.com/longbridge/openapi/blob/v4.5.0/rust/src/blocking/runtime.rs):
  the synchronous caller waits in `reply_rx.recv()` for the async Rust operation.
- [Python async binding](https://github.com/longbridge/openapi/blob/v4.5.0/python/src/trade/context_async.rs):
  `AsyncTradeContext.create(config)` is synchronous construction; history methods
  return Python awaitables through `future_into_py`. Invocation and awaiting must
  occur in the same running Python loop.
- [History orders API](https://open.longbridge.com/docs/trade/order/history_orders)
  and [history executions API](https://open.longbridge.com/docs/trade/execution/history_executions):
  each response is limited to 1000 rows and HTTP exposes `has_more`. The 4.5.0
  Python history methods return rows only, losing that completeness indicator.
- [Async portfolio binding](https://github.com/longbridge/openapi/blob/v4.5.0/python/src/portfolio/context_async.rs)
  lacks `profit_analysis_by_market`. The installed package confirms this. The
  candidate retains the original synchronous `PortfolioContext` method, market,
  page size, date boundaries, normalization, P&L and fee algorithms.

The synchronous GIL-blocking risk is source-confirmed. Async read-only history
requests succeeded quickly on this account. No new synchronous 60-second probe
was run, so this is not proof that every earlier timeout had only a GIL cause;
remote endpoint and networking failures remain possible. No proxy or endpoint
settings were changed.

## Implementation Contract

`OfficialAsyncAnalyticsReader` is history-only despite the module-level name.
It owns one caller-thread event loop and at most one `AsyncTradeContext`, created
lazily inside that loop. It creates no extra Python thread, quote context,
subscription, or CLI process. OAuth uses the official asynchronous builder and
existing credentials and region configuration. A fresh SDK `stock_positions`
response must identify only `lb_papertrading` before the first history request.

- Defaults: 10 seconds per history operation (including initial OAuth and paper
  verification), 40 seconds total reader lifetime, 1 second cancellation cleanup.
- Each history endpoint is requested once. Timeout, SDK error, malformed result,
  late result or saturated response permanently invalidates that reader.
- 1000 or more rows fail with `possibly_truncated`. No automatic partitioning or
  retry is attempted. This is deliberately conservative even if exactly 1000
  rows might be complete. A cache-free full bootstrap on this account therefore
  requires a separately reviewed bounded history backfill before acceptance.
- Existing two-day incremental merge and successful empty-response semantics are
  preserved. Both endpoints must actually succeed before cached rows are merged.
  Neither old cache nor account snapshots can substitute for a failed refresh.
- History failure or cleanup failure prevents subsequent portfolio I/O and all
  analytics publication. A portfolio failure also prevents publication.
- Context exit cancels pending tasks, drains them within the cleanup limit,
  drops SDK references and closes the owned loop. Native transport closure and
  SDK internal reconnection cannot be acknowledged/disabled by this API.
- Both initial and pre-publication runtime/account freshness checks are required.
  Publication uses the original query timestamp; it is not advanced to disguise
  the age of the account snapshot.
- The old `read_with_timeout_recovery` helper remains for compatibility with
  existing imports/tests, but the production analytics path no longer calls it.
  `build_trade` in `refresh_order_and_execution_history` is an unused compatibility
  argument. No runtime caller or public entry-point signature was changed.

Important boundary: the history reader's deadlines do **not** bound the existing
synchronous portfolio calls. Those may still hold the GIL and need the existing
external process deadline. This change does not claim to make all analytics I/O
asynchronous. No replacement P&L API or formula was introduced.

## Bounded Read-Only Evidence

Only counts, elapsed times and status were printed. No credentials, account IDs,
holdings, order identifiers, or profit amounts are included here. No production
report/cache was written and no full `run_sdk_analytics` publication was executed.

1. Direct official async discovery, external cap 55 seconds, each request capped
   at 12 seconds: paper stock positions 0.674s; today orders 0.388s / 0 rows;
   two-day history orders 0.402s / 0 rows; history executions 0.385s / 0 rows.
2. Candidate full-range investigation, external cap 48 seconds, history reader
   cap 10s per call: June 1 through September 8 orders 4.455s / 1000 rows,
   executions 0.874s / 986 rows. The orders result is **not** accepted as complete.
   Independent Python heartbeat recorded 525 ticks with a maximum 0.010s gap.
   The proposed async portfolio call raised `AttributeError` immediately. That
   path was stopped and removed, not retried or replaced with another formula.
3. Final corrected candidate, `2026-09-08T11:34:15.976457+00:00`, external cap
   25 seconds: two-day history orders 1.119s / 0 rows (includes OAuth, context and
   SDK paper verification), executions 0.392s / 0 rows; original cumulative
   portfolio API 0.585s; original single-market-date portfolio API 0.401s.
   All four calls succeeded. No cache was read for these calls. No new order was
   expected or manufactured to make an empty response look nonempty.

These are read-only query checks, not evidence of a completed paper order, a full
trading day, complete historical bootstrap, or production deployment. There were
no new historical query timeouts and no repeated 60-second synchronous probes.

## Offline Verification

Use the existing repository virtualenv, without installing/upgrading packages:

```bash
/home/hgl/projects/Price-Action-Trader/.venv/bin/python -m unittest \
  tests.unit.test_m15_sdk_history_readonly_async \
  tests.unit.test_m15_longbridge_sdk_analytics \
  tests.unit.test_m15_official_async_quote \
  tests.unit.test_m15_sdk_validation_flatten \
  tests.unit.test_m15_longbridge_sdk_runtime \
  tests.unit.test_m15_longbridge_sdk_quote_transport \
  tests.unit.test_m15_longbridge_sdk_account_worker -q
```

Result: 213 tests passed, including 23 independent new tests. The new fake-SDK
suite forbids socket connections. It covers SDK signatures, loop ownership,
paper-only verification, per-call and total deadlines, cancellation, late results,
1000-row saturation, no rebuild/retry, no cache publication on partial failure,
snapshot expiry, unchanged date/formula inputs, and loop/thread cleanup.

Both changed Python files passed `py_compile`. Repository governance passed,
including six governance unit tests, sensitive-material scanning, the 50 MiB
tracked-file limit and `git diff --check`. The three changed/new files were also
explicitly scanned and measured; none contains a matching secret pattern or is
larger than 35 KiB.

## Handoff

```yaml
task_id: m15-sdk-history-readonly-20260908
role: implementation-and-readonly-validation
branch_or_worktree: codex/fix-m15-sdk-history-readonly-20260908
objective: remove synchronous SDK history blocking without changing trading or PnL
status: success
files_changed:
  - scripts/m15_longbridge_sdk_analytics_lib.py
  - tests/unit/test_m15_sdk_history_readonly_async.py
  - docs/m15-sdk-history-readonly-20260908.md
interfaces_changed:
  - new internal OfficialAsyncAnalyticsReader
  - history refresh no longer rebuilds a context after timeout
  - saturated history responses fail closed
commands_run:
  - git fetch origin main
  - git worktree add -b codex/fix-m15-sdk-history-readonly-20260908 /home/hgl/projects/Price-Action-Trader-m15-sdk-history-20260908 origin/main
  - bounded read-only probes documented above
tests_run:
  - 213 focused unit tests passed
  - changed Python files compiled
  - repository governance including 6 tests passed
  - changed-file secret scan, size check and git diff --check passed
assumptions:
  - official longbridge 4.5.0 and existing OAuth credentials remain installed
  - synchronous analytics entry point runs outside an asyncio loop
  - existing trusted history is used only after successful incremental queries
risks:
  - human account-connection review required before integration
  - synchronous portfolio remains outside history deadlines
  - full bootstrap returned 1000 orders and cannot be certified complete
  - historical cache provenance and older gaps are not audited by this fix
  - SDK native close and internal reconnect limitations remain
  - no separate subagent tool was available; review was serial
qa_focus:
  - integrate with the main task's paper authorization and tests without changing them
  - confirm actual reporting refresh exits successfully and advances only fresh outputs
  - retain external analytics subprocess deadline
  - never treat readonly empty-history evidence as a completed paper-order test
rollback_notes:
  - revert this isolated commit in the integration branch, not unrelated changes
  - do not restart production or reenable the legacy blocked path automatically
next_recommended_action: main task reviews and integrates this pushed branch, then validates the authorized paper workflow
needs_user_decision: false
user_decision_needed: null
```
