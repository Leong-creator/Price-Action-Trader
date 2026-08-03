# M15 PA002 双版本长桥测试交接

```yaml
task_id: m15-pa002-repaired-dual-test-20260803
role: main_agent
branch_or_worktree: feature/m15-pa002-repaired-dual-test
objective: 为现行 PA002-5m 保留原仓，并新增同规则修复版长桥 SDK 独立仓及自动节点评估
status: success
files_changed:
  - plans/active-plan.md
  - docs/implement.md
  - docs/status.md
  - config/examples/m15_longbridge_realtime_signal_router.json
  - config/examples/m15_longbridge_realtime_execution.json
  - config/examples/m15_longbridge_realtime_execution.paper_orders_enabled.json
  - scripts/m15_longbridge_realtime_signal_router_lib.py
  - scripts/m15_longbridge_realtime_execution_lib.py
  - scripts/m15_longbridge_realtime_position_manager_lib.py
  - scripts/m15_longbridge_fill_attribution_lib.py
  - scripts/m15_pa002_repaired_state_lib.py
  - scripts/m15_pa002_dual_version_milestone_lib.py
  - scripts/run_m15_pa002_dual_version_milestone.py
  - scripts/m15_background_watchdog_lib.py
  - scripts/m15_longbridge_dashboard_lib.py
  - tests/unit/test_m15_pa002_repaired_state.py
  - tests/unit/test_m15_pa002_dual_version_milestone.py
  - tests/unit/test_m15_longbridge_realtime_signal_router.py
  - tests/unit/test_m15_longbridge_realtime_execution.py
  - tests/unit/test_m15_longbridge_realtime_position_manager.py
  - tests/unit/test_m15_background_watchdog.py
  - tests/unit/test_m15_longbridge_dashboard.py
  - docs/handoffs/m15-pa002-repaired-dual-test.md
interfaces_changed:
  - 新增长桥运行单元 M10-PA-002-5m-repaired-v1 和独立资金池 pa002_5m_repaired_v1
  - 新增 PA002 双版本盘后节点状态与复核产物
  - M15 后台看护每300秒随成交归因成功刷新节点状态
commands_run:
  - python -m py_compile 聚焦脚本
  - python -m unittest 聚焦链路153项
  - python -m unittest discover -s tests/unit -p test_m15*.py
  - SDK runtime stop/daemon dispatch/status/check
tests_run:
  - M15 全量单元测试461项通过
  - 当前 SDK 模拟账户行情300/300、日线18000/18000、账户快照健康、dispatch开启
assumptions:
  - 修复版只使用长桥 SDK 实时行情和长桥实际成交，不注册为本地模拟运行单元
  - 后续变体只由节点报告建议，不自动启用
risks:
  - 新版本尚无长桥实际成交样本，成绩必须从零累计
  - 同一长桥账户承载多个虚拟仓，必须持续依赖精确订单号和成交号归因
qa_focus:
  - 首个交易日核对新运行单元的信号、订单号、成交批次和次日退出
  - 核对两连亏后只跳过下一条合格信号
  - 核对5日与15日100笔节点不会被其他PA002周期或其他策略异常污染
rollback_notes:
  - 提交前可丢弃本分支工作区 patch；提交后整体 revert 本次 repaired runtime、独立 bucket、状态机和 milestone evaluator 提交
  - 回退后重启唯一 M15 SDK 模拟账户进程，现行 M10-PA-002-5m 保持原配置
next_recommended_action: 在下一美股常规交易时段只接受实时新信号，并检查第一笔修复版实际成交归因
needs_user_decision: false
user_decision_needed: ""
```
