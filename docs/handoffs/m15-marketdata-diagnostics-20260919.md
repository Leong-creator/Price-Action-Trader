# 行情诊断实现交接

```yaml
task_id: m15-marketdata-diagnostics-20260919
role: implementer
branch_or_worktree: codex/fix-marketdata-diagnostics-20260919 / /home/hgl/projects/pat-active/diagnostics
objective: 区分原始回调与本地处理停滞，提供隔离只读探针并保留故障证据
status: success
files_changed:
  - scripts/m15_marketdata_diagnostics_lib.py
  - scripts/run_m15_longbridge_quote_diagnostic.py
  - scripts/m15_longbridge_sdk_quote_transport_lib.py
  - scripts/run_m15_longbridge_sdk_runtime.py
  - tests/unit/test_m15_marketdata_diagnostics.py
  - tests/unit/test_m15_longbridge_sdk_quote_transport.py
  - tests/unit/test_m15_boot_runtime_integration.py
  - docs/m15-marketdata-diagnostics.md
interfaces_changed:
  - pipeline_diagnostics adds per-symbol stages, UTC and monotonic evidence, bounded samples
  - transport_reader_errors is null for unobservable SDK native reader; unknown states explicit
  - fault status preserves timestamped prior observed snapshot; status CLI preserves original fault
  - standalone diagnostic accepts config, symbols or production-universe, duration-seconds, output-dir
  - CLI verifies official environment before SDK/OAuth; formal interpreter is .venv-m15/bin/python
  - shared existing global quote ownership lock blocks simultaneous diagnostic and production
commands_run:
  - py_compile changed Python files
  - git diff --check
tests_run:
  - 199 combined diagnostics/transport/runtime/session-evidence/boot tests passed with clean official interpreter
  - 19 final focused diagnostics/transport tests passed after adding callback-conversion failure coverage
assumptions:
  - official provenance module is integrated from environment worker commit 1b66c69
  - main agent synchronizes active-plan implement status architecture
risks:
  - SDK native close is not observable; caller must verify probe process exited before next connection
  - raw probe does not aggregate bars or prove session acceptance
  - runtime uses existing global PID lock format for old-version compatibility
  - production diagnostic journal full snapshot every 30 seconds; one-second heartbeat remains in-memory IPC
  - high-risk runtime startup and fault reporting changes require independent review before deployment
qa_focus:
  - blocked provenance prevents any SDK or OAuth access
  - failed callback still records raw entry even without normalization/enqueue
  - lock conflict, old runtime and orphan child do not trigger killing or new connection
  - existing worker child cleanup still runs on own shutdown
  - real cross-open evidence remains required and not run by this worker
rollback_notes:
  - no fallback runtime or second data source introduced
  - source changes isolated in branch; no production state/environment touched
next_recommended_action: integrate provenance dependency, independent review, main agent sole-owner real read-only probe
needs_user_decision: false
user_decision_needed: null
```
