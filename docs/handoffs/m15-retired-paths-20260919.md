# 2026-09-19 退役行情入口与看板清理

仅清理旧入口和读文件看板，不请求长桥网络、不修改账户/策略/订单逻辑。高风险正式部署仍须独立复核。

- 删除额外创建SDK环境的旧安装脚本、无统一锁及来源校验的旧同步行情canary入口、专属库和专属测试。删除前引用扫描确认库仅被该入口与专属测试导入；账户CLI与历史工具未删。
- 长桥看板不再读取退役的 `market_event_ingestor`、`realtime_session_supervisor` 文件；行情状态只来自 `m15_longbridge_sdk_runtime.json`。旧守护器“等待窗口”不再豁免旧账户、执行快照的过期检查。
- `fault_halted` 原因即使过期仍展示；缺失、过期、未来时间及未知接收状态不能称正常。新鲜运行记录须同时报告连接与参考行情健康，才显示“SDK报告行情更新”；30秒为看板记录显示期限，不改变生产行情或订单门禁。
- SDK记录缺字段显示未知，不把原处理通知累计数改称原生接收数。行情故障/未知时执行与信号卡片不再显示旧健康摘要，账户及订单保留独立审计用途。
- 旧输出引用/过期字段改为 `refs.sdk_runtime`、`sdk_runtime_state_stale`、`sdk_runtime_status`、`sdk_runtime_reason`；仓库检索未发现其他Python消费者依赖被移除的字段。市场窗口按现行交易日历计算，不沿用旧守护器时间。

## 验证

使用主工作区 `.venv-m15/bin/python`，socket连接在看板测试中禁止：

- 10项相关看板状态测试全部通过，含故障覆盖旧健康文件、退休守护器不能续期、SDK缺失/过期/未来时间/未知/停止等场景。
- 全看板69项：62项通过、7项失败。相同工作区载入修改前HEAD模块运行原67项：60项通过、相同7项失败；不是本次新增失败。旧失败涉及研究运行样本、scope和PA002历史标题，未扩大任务去修改这些逻辑。
- 基线日志 `/tmp/pat-retired-dashboard-baseline.log`；最终日志 `/tmp/pat-retired-dashboard-verified.log`。不将此结果称为全仓测试通过或真实行情通过。
- 改动Python编译和差异检查通过；暂存删除后仓库治理通过（6项测试、敏感信息和大文件扫描）。暂存前大文件检查曾因已删文件仍在索引报路径缺失，暂存后消除。

## 交接

```yaml
task_id: retired_marketdata_paths_20260919
role: implementer
branch_or_worktree: codex/fix-retired-marketdata-paths-20260919
objective: 删除退役行情探针入口并停止看板读取旧健康文件
status: success
files_changed:
  - scripts/install_m15_quote_canary_tools.sh (deleted)
  - scripts/run_m15_quote_transport_canary.py (deleted)
  - scripts/m15_quote_transport_canary_lib.py (deleted)
  - tests/unit/test_m15_quote_transport_canary.py (deleted)
  - scripts/m12_29_current_day_scan_dashboard_lib.py
  - tests/unit/test_m12_29_current_day_scan_dashboard.py
  - docs/handoffs/m15-retired-paths-20260919.md
interfaces_changed: [看板SDK状态字段替代旧supervisor/ingestor字段]
commands_run: [引用扫描, HEAD模块基线对照, Python编译, git diff --check]
tests_run: [相关禁网测试10项通过, 全看板62通过7个既有失败, 仓库治理6项及扫描通过]
assumptions: [正式SDK运行记录为行情状态来源, 本轮不操作长桥账户或订单]
risks: [全看板存在7个既有失败, 读文件显示不等于完整交易日或活进程验收]
qa_focus: [SDK原始故障优先, 退役文件不可续期, 缺失状态不可健康, 独立账户审计不丢失]
rollback_notes: [删除文件保存在Git历史, 不建立旧行情自动回退路径]
next_recommended_action: 独立复核后集成并同步主代理本轮结果
needs_user_decision: false
user_decision_needed: null
```
