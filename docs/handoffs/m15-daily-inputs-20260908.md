# M15 Daily Inputs Handoff

```yaml
task_id: m15-daily-inputs-20260908
role: implementation-and-offline-qa
branch_or_worktree: codex/fix-m15-daily-inputs-20260908 / /tmp/pat-daily-inputs-20260908
objective: Preserve daily detector history and separate sealed OHLCV from next-bar entry quotes.
status: success
files_changed:
  - scripts/m15_longbridge_realtime_signal_router_lib.py
  - scripts/m15_longbridge_sdk_runtime_lib.py
  - scripts/run_m15_longbridge_sdk_runtime.py
  - tests/unit/test_m15_daily_inputs.py
  - docs/status.md
  - docs/handoffs/m15-daily-inputs-20260908.md
interfaces_changed:
  - realtime_relevant_market_events accepts optional generated_at.
  - attach_next_bar_first_quotes accepts optional now.
  - quote_for_bar_boundary selects separate sealed and entry snapshots.
  - Parent quote state retains first/last snapshots for two five-minute buckets.
commands_run:
  - git fetch origin; verify origin/main is 18a0b4409965c94386adb44c0527fd8ee59a97bc
  - git worktree add -b codex/fix-m15-daily-inputs-20260908 /tmp/pat-daily-inputs-20260908 origin/main
  - Project virtualenv Python -B unittest with socket connect/connect_ex/create_connection forbidden
  - In-memory compilation, changed-file secret and size scans, git diff --check
tests_run:
  - Combined result: 216/216 passed in 37.748 seconds with network connections forbidden.
  - tests.unit.test_m15_daily_inputs (17 new tests)
  - tests.unit.test_m15_full_strategy_detectors
  - tests.unit.test_m15_longbridge_realtime_signal_router
  - tests.unit.test_m15_longbridge_sdk_runtime
  - tests.unit.test_m15_session_evidence (unchanged)
  - tests.unit.test_m15_preopen_bar_integrity
assumptions:
  - Base is origin/main 18a0b44; date authorization and async trade/boot changes integrate separately.
  - Offline synthetic fixtures are test-only and are not runtime acceptance evidence.
risks:
  - First quote means first observed by parent; worker coalescing can omit earlier raw SDK ticks.
  - Missing sealed or entry snapshot remains unavailable; no fabricated quote, deferred signal replay, or order is introduced.
  - Full-session evidence, account/market gates, strategy thresholds, risk rules and configuration are unchanged.
  - System Python lacks longbridge; use the existing project virtualenv for the SDK import contract test.
qa_focus:
  - PA001 rejects 21 bars and accepts its qualifying 22-bar fixture; FTD rejects 23 and accepts 24.
  - Router retains 60 unique historical daily timestamps despite duplicate cache inputs and intraday initialization.
  - Prior-bucket last quote seals daily OHLCV; next-bucket first quote supplies entry only.
  - Exact boundary belongs to next bucket; future/naive/inconsistent timestamps, old annotations and inactive signal IDs cannot refresh entry.
  - Repeated active boundary signal IDs do not emit again; prior-session quotes do not replay.
  - Cherry-pick must preserve other agents' boot, async trade and date authorization hunks; rerun integrated regressions.
rollback_notes:
  - Revert this isolated commit; no config, account, market connection or runtime process changes need reversal.
next_recommended_action: Cherry-pick this branch commit, independently review the input-path hunks, then run final integrated offline regression.
needs_user_decision: false
user_decision_needed: null
```

## Input Contract

Daily history uses market `event_time`, not cache load `received_at`. For a
currently active symbol/day, the router retains up to 60 unique prior timestamps;
other timeframes retain their existing 20-row lookback. Detector rules are not
modified. The actual router tests exercise current-event gating and emitted-ID
deduplication in temporary directories, without entering the execution layer.

For five-minute close `B`, daily OHLCV comes from the latest observed official
push in `[B-5m, B)`. Entry comes from the first observed official push in
`[B, B+5m)`. Each quote must satisfy `source_at <= received_at <= checked_at`,
have a timezone, and belong to the same New York date as `B`. Initial snapshots
cannot fill either role. The current blocked state overrides cached quotes.

The bounded cache does not recover callbacks already coalesced before the parent
observed them. If either required snapshot is unavailable, the system must not
manufacture an entry or replay an old signal to compensate. This patch makes no
claim about a real full-session pass or tonight's natural order count.
