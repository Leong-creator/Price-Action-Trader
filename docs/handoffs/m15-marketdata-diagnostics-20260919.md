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

## 追加：独立审查整改与 pipeline 模式

- 两种串行模式：默认 raw-sdk；pipeline 必须 --production-universe，只调用原 quote worker，不调用 run_watch 或任何账户/策略/订单客户端。
- 父进程墙钟监督解决同步 OAuth/factory 阻塞无法被 asyncio 取消的问题；phase.json 记录卡点。
- 子进程继承同一行情锁 FD（DupFd），并设置 Linux 父死亡 SIGKILL 和父 PID 竞态复核，阻止父进程被杀后残留无锁行情连接。
- pipeline 复用现有 MarketSessionEvidence 及参考新鲜度规则，独立保存消息/K线计数；所有输出重定向外部目录，不写生产故障/缓存/验收文件。
- 49 项最终聚焦测试通过，包括原生同步创建永久阻塞、父关闭锁FD仍互斥、父 SIGKILL 后子进程退出、纯行情零账户构造，以及隔离真实进程的 boot 测试。
- 待 root 集成：deployment DEFAULT_RUNTIME_FILES 加入 m15_marketdata_diagnostics_lib.py 和 run_m15_longbridge_quote_diagnostic.py；环境实现为其他代理负责，未交叉修改。
