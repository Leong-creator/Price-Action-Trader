task_id: m15-sdk-session-coverage-stability-20260811
role: implementation
branch_or_worktree: codex/fix-m15-auto-flatten-terminal-retry
objective: 修复M15关键行情消息静默丢失、五分钟整场覆盖不可审计、慢统计超时误伤健康状态和看板口径混淆。
status: success
files_changed:
  - scripts/run_m15_longbridge_sdk_runtime.py
  - scripts/m15_longbridge_sdk_runtime_lib.py
  - scripts/m15_longbridge_sdk_analytics_lib.py
  - scripts/m15_longbridge_dashboard_lib.py
  - tests/unit/test_m15_longbridge_sdk_runtime.py
  - tests/unit/test_m15_longbridge_sdk_analytics.py
  - tests/unit/test_m15_longbridge_dashboard.py
  - tests/unit/test_m15_background_watchdog.py
  - tests/unit/test_m15_visual_strategy_shadow_session.py
  - plans/active-plan.md
  - docs/implement.md
  - docs/status.md
interfaces_changed:
  - M15 runtime状态新增five_minute_session_coverage。
  - 长桥看板runtime新增sdk_push_subscription_coverage和five_minute_session_coverage。
  - SDK慢统计summary、order reconciliation、PNL和trusted history新增statistics_stale。
commands_run:
  - python -m py_compile scripts/m15_longbridge_dashboard_lib.py scripts/m15_longbridge_sdk_analytics_lib.py scripts/m15_longbridge_sdk_runtime_lib.py scripts/run_m15_longbridge_sdk_runtime.py
  - ./.venv/bin/python -m unittest tests.unit.test_m15_longbridge_sdk_runtime tests.unit.test_m15_longbridge_sdk_analytics tests.unit.test_m15_longbridge_dashboard tests.unit.test_m15_background_watchdog tests.unit.test_m15_visual_strategy_shadow_session tests.unit.test_m15_visual_strategy_acceptance tests.unit.test_m15_visual_strategy_shadow tests.unit.test_m15_full_strategy_detectors -v
  - ./.venv/bin/python scripts/run_m15_longbridge_sdk_analytics.py --sdk-config config/examples/m15_longbridge_sdk_runtime.contract_v1.json --account-config config/examples/m15_longbridge_realtime_account_state.json
  - ./.venv/bin/python scripts/run_m15_opening_trade_readiness.py --config config/examples/m15_opening_trade_readiness.paper_contract_v1.json
  - git diff --check
tests_run:
  - M15聚焦回归245项通过。
  - 300只乘78根视觉影子完整会话通过，精确断言23400根。
  - 队列拥塞下完整K线、快照、就绪和行情状态均不得静默丢弃。
  - statistics_stale在新鲜文件上仍会把看板降级为trading_ready_statistics_stale并隐藏陈旧统计。
  - 实机SDK慢统计读取1915张历史订单、1435条成交，归因异常0。
  - 实机开盘验收14项通过、0失败、1项仅等待常规交易时段。
assumptions:
  - 当前300只整场78边界规则用于正常完整美股交易日；提前收盘日继续安全地不计为完整视觉影子日，后续应接入冻结交易日历再计短会话。
  - SDK快照后备300/300是实际行情覆盖，不冒充SDK推送订阅回执。
risks:
  - 三条视觉策略仍缺真实无缺口交易日和人工10正例、10反例、5边界例，继续禁止下单。
  - 关键队列若持续拥塞超过5秒会显式终止行情worker并由父进程恢复；不会静默丢数据，但该事件必须在市场数据健康流水中告警。
qa_focus:
  - 下一个完整交易日确认78个边界逐个达到300/300且进程无重建缺口。
  - 注入慢统计超时后确认交易仍武装、看板显示统计待刷新、陈旧盈亏不展示。
  - 检查SDK推送订阅与实际行情覆盖继续分栏显示。
rollback_notes:
  - 回退慢统计降级提交会恢复统计超时失败行为，但不影响订单事实数据。
  - 回退行情覆盖提交会移除新健康产物和看板字段；无需迁移订单、成交、持仓或本地账本。
  - 任何回退都不得恢复关键行情消息静默丢弃。
next_recommended_action: 下一个正常完整交易日只观察自动运行产物，确认300乘78完整覆盖并生成第一晚可信视觉影子会话。
needs_user_decision: false
user_decision_needed:
