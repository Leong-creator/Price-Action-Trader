task_id: m15-fill-attribution-account-stability-20260722
role: main_agent
branch_or_worktree: fix/m15-monday-stability
objective: 修复跨策略同标的成交归因和账户快照长期过期，并建立自动熔断恢复与可观测性。
status: success
files_changed:
  - scripts/m15_longbridge_fill_attribution_lib.py
  - scripts/m15_longbridge_sdk_account_worker_lib.py
  - scripts/m15_longbridge_sdk_account_lib.py
  - scripts/m15_longbridge_sdk_runtime_lib.py
  - scripts/run_m15_longbridge_sdk_runtime.py
  - scripts/m15_longbridge_realtime_account_state_lib.py
  - scripts/m15_longbridge_realtime_position_manager_lib.py
  - scripts/m15_longbridge_realtime_execution_lib.py
  - scripts/m15_longbridge_dashboard_lib.py
  - scripts/m15_opening_trade_readiness_lib.py
interfaces_changed:
  - 正式分仓归因改为长桥订单号和成交编号的精确批次接口。
  - 账户快照改为独立子进程，新增启动期限、刷新期限、熔断和进程状态字段。
  - M15 SDK 运行层新增单实例文件锁，后台看护只管理锁持有者。
  - 看板和开盘验收新增归因异常、账户工作进程及熔断状态。
commands_run:
  - python -m py_compile 覆盖全部改动脚本
  - python -m unittest 聚焦 M15 成交归因、账户、执行、持仓、看板、验收和看护模块
  - git diff --check
tests_run:
  - 236 tests in 67.056s, OK
  - git diff --check passed
assumptions:
  - 只使用长桥模拟账户，不接实盘、真实资金、期权或融资。
  - 长桥实际订单、成交和持仓是最终事实源。
risks:
  - 历史订单缺少原开仓成交编号时，只允许在对应订单恰有一个长桥成交批次时确定性补齐，否则保持未归因。
  - 非交易时段只能验证连接、账户和状态恢复，不能证明下一笔自然信号一定成交。
qa_focus:
  - 同标的跨资金池和跨策略的部分成交不得互相核销。
  - 账户工作进程首次启动不得被常规 8 秒期限误杀。
  - 归因不一致必须冻结受影响标的，不能冻结整个系统或自动猜测平仓。
rollback_notes:
  - 回退前先停止 scripts/run_m15_longbridge_sdk_runtime.py 的当前模拟账户进程，并保留长桥订单、成交和归因审计文件。
  - 已物化任务开始前完整工作区归档 /tmp/price-action-trader-pre-attribution-stability-20260722.tar.gz，SHA256 为 06f67869365092b37d3edc2d71f7ced47b8daf9d51e38c0f306f86e0a53c05b5。
  - 回退时先删除本轮新增的 docs/handoffs/m15-fill-attribution-account-stability-20260722.md、scripts/m15_longbridge_fill_attribution_lib.py、scripts/m15_longbridge_sdk_account_worker_lib.py、tests/unit/test_m15_longbridge_fill_attribution.py、tests/unit/test_m15_longbridge_sdk_account_worker.py。
  - 然后执行 tar --strip-components=1 -xzf /tmp/price-action-trader-pre-attribution-stability-20260722.tar.gz -C /home/hgl/projects/Price-Action-Trader，恢复任务开始前的 tracked 和原有 untracked 文件；归档已在独立 /tmp 目录完成解包和成员核验。
  - 回退后必须重新做模拟账户验收，且会重新暴露线程不可终止、多实例状态覆盖和同标的误归因风险。
next_recommended_action: 重启 M15 SDK 正式进程，确认工作进程健康、熔断关闭、账户快照小于45秒并生成新的精确归因状态。
needs_user_decision: false
user_decision_needed:
