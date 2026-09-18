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

## 追加：原始探针订阅证据精度

- raw-sdk 原先固定30秒请求等待，与正式45秒配置不等价；统一使用配置 subscription_deadline_seconds，且仍受总剩余时间与父进程墙钟监督限制。生产配置未修改。
- 每批记录 offset、size、total、sub_types、timeout、outcome、elapsed，独立 phases.jsonl；phase.json 标记当前或刚失败的一批。
- SDK错误正文不落盘，仅保存错误类型和 request_timeout/sdk_or_runtime_error 分类。
- 最终50项聚焦测试通过，新增首批成功/后批超时、45秒一致性及敏感异常正文不泄露验证。
- 未执行任何真实行情连接。官方文档500证券/单连接/10req每秒/并发5限制不能解释50一批为违规；SDK未改HEAD源码first_push=true，但本机旧源码工作树有补丁，不能用其内容当官方依据或重新编译部署。

## 追加：安全供应商错误与具体标的

- 原始探针每批新增 batch_symbols，失败保留 OpenApiException 数值 code、固定 kind、category、classification_basis 和有界 causal_chain。
- 不保存异常正文、trace_id 或任意属性字符串；codeNone且关键词分类标注为启发式，不冒充权限/限频根因证据。
- worker新增 safe_error，pipeline父进程保留；父墙钟超时单列supervisor_safe_error，不覆盖子进程已经保存的供应商原因。
- 新增安全字段、因果循环、secret正文/trace注入不泄露测试；仍未建立任何真实行情连接。

- 本追加51项聚焦测试通过；独立review亦51项通过，分类来源引用已核正。
