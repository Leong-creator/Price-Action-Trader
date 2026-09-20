# Linux实际行情处理链的有限时段诊断

本次补强已有 `run_m15_longbridge_quote_diagnostic.py --mode pipeline`，用于已核验环境中的真实生产模块诊断。独立官方样例与正式系统处理链的验收范围保持区分；本文件不授权连接或调度，不解除正式故障。

## 实际复用与输出边界

诊断启动现有 `official_sdk_quote_worker`，执行官方默认 Config、同步 QuoteContext、原147只单次Quote+Trade、日线初始化、真实回调归一化、回调队列、IPC与原五分钟生成器。父进程沿用 MarketSessionEvidence 的完整边界、及时性和参考行情检查。所有行情、风险和策略阈值不变。

新增父进程 `apply_quote_state_worker_message` 实际调用，确认修后的报价时间能进入 `live_quote_session_state`；保留工作进程发送的 `daily_context`。只有通过现有完整边界检查的实时K线才能进入原 MarketEventContext、报价附注、历史/当日日线组合及 `run_realtime_signal_router`。不调用包含账户、仓位和订单的 `dispatch_completed_rows`，不建立另一套简化策略。

诊断父进程与行情子进程均用拒绝stub保护 TradeContext、AsyncTradeContext、PortfolioContext及存在时的AsyncPortfolioContext构造。允许创建行情上下文；不创建账户/订单上下文，不提交订单。信号仅保存到诊断输出下的 `strategy/signal_events.jsonl`。原router读取既有epoch/迁移状态作为只读输入，不能修改这些状态。

完整worker消息日志支持datetime与Decimal的JSON审计序列化，转换只作用于落盘副本，不修改传给实际处理函数的消息。父报价状态和五分钟生成器仍处理真实类型。

## 调用接口

以合入并核验后的项目 `.venv-m15/bin/python` 运行：

```text
scripts/run_m15_longbridge_quote_diagnostic.py
  --mode pipeline
  --production-universe
  --duration-seconds 1800
  --config /绝对路径/外部case/config.json
  --output-dir /绝对路径/外部case/evidence
  --quote-lock-fd N
  --window-start-utc 2026-09-21T13:50:00Z
  --latest-start-utc 2026-09-21T13:51:00Z
  --window-end-utc 2026-09-21T14:20:00Z
```

窗口参数须同时提供，本次固定值之外拒绝启动。13:51之后不补跑；父循环按14:20绝对UTC结束。SDK退出清理另有最多5秒协作、5秒TERM、5秒KILL。外层runner需保持独立期限及整组进程退出核验。

继承fd须由外层持有项目统一行情flock，并通过pass_fds传入。诊断核对fd与统一锁文件inode后dup同一open-file-description，不另开文件竞争，不关闭外层原fd；子进程继续继承该锁和父进程死亡保护。若无fd，普通诊断入口自行取得统一锁。执行前须由外层核实此前Windows观测已可信退出、跨系统持久标记为空。

私有config必须将 `outputs.output_dir/market_events/runtime_status/readonly_gate` 和 `market_data.daily_context` 指向工作区外；`routing.paper_order_dispatch_enabled=false`。建议case下分开 `unused-runtime/` 与 `evidence/`，因为诊断输出不得位于config.output_dir内部。日线可指定新的不存在路径，沿现有官方日线请求获取；不能复用未来或过期日线。其余股票池、策略合同及风险配置保持原值。实际写入只在evidence及其strategy子目录；不触及正式状态、故障、订单、日报或原epoch。

## 结果口径

`summary.json`增加实际父报价状态覆盖、日线数量/来源、策略调用次数、实际完整边界及K线数量。只有时段正常结束、工作进程正常退出、收到完整输入、真实Trade回调及出队、有成交形成的K线且至少一次合格边界/策略调用时，`bounded_pipeline_observed=true`。没有输入/没有合格边界会返回 `status=incomplete` 与exit4；失败与强制退出不能显示此观察通过。exit0仅适用于正常 `duration_completed`。

每个合格边界保存 `strategy/boundary_decisions.jsonl` 与完整router历史，包括实际输入数量、允许的原策略、信号数、原router阻断原因、短策略诊断及逐策略合同声明的历史长度不足情况。`original_router_no_qualified_signal`只陈述原router结果，不捏造某个尚未记录的具体技术条件。合同声明数量满足也不证明其他条件满足。

30分钟仅提供这段时间真实收到的日内历史。PA002所需20根此前五分钟K线、开盘区间等可能不足，不降低阈值、不补历史盘中数据冒充实时；均标记短时段输入限制。`strategy_full_acceptance=false`、`full_session_acceptance=false`和`production_acceptance=false`始终保持。14:20才关闭的K线可能来不及在截止前形成，退出阶段收到的数据仅记录在shutdown日志，不回填已验收边界。不得把本次计作78边界或完整交易日通过。

## 离线验证及交接

新增禁网假SDK端到端输入：实际worker读取两只测试标的各60根日线，经过真实回调、真实multiprocessing.Queue、父报价状态、原五分钟生成器、完整边界规则和原8条策略router；账户和订单构造受拒绝stub保护。两只仅是离线fixture，不修改生产147只配置。还覆盖无数据不通过、审计序列化不改变原值、继承锁和窗口拒绝。

```yaml
task_id: m15_linux_pipeline_20260921
role: implementer
branch_or_worktree: root_current_integration_branch
objective: 使用正式模块进行无账户订单的有限时段行情与策略判断验证
status: success
files_changed:
  - scripts/run_m15_longbridge_quote_diagnostic.py
  - scripts/m15_marketdata_diagnostics_lib.py
  - tests/unit/test_m15_marketdata_diagnostics.py
  - tests/unit/test_m15_diagnostic_strategy_pipeline.py
  - docs/handoffs/m15-linux-pipeline-20260921.md
interfaces_changed:
  - --quote-lock-fd及三个绝对UTC窗口参数
  - pipeline结果增加实际父状态与策略判断证据
commands_run:
  - .venv-m15/bin/python -m unittest tests.unit.test_m15_diagnostic_strategy_pipeline tests.unit.test_m15_marketdata_diagnostics -q
tests_run:
  - 25项离线测试通过，包含真实模块假SDK端到端测试
assumptions:
  - 环境来源及时间归一修复由其他责任代理完成并集成
risks:
  - 尚未实连，0个新增真实完整交易日
  - 短时段日内历史不足不能宣称全部策略验收
qa_focus:
  - 实际模块复用、私有输出、账户拒绝守卫、短窗不足诚实标注
rollback_notes:
  - 本改动不写正式运行状态，不启动或注册任务
next_recommended_action: 独立复核、冻结源码与配置后由root批准外层runner执行一次
needs_user_decision: false
user_decision_needed: null
```
