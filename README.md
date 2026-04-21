# Price Action Trader

Price Action Trader 是一个以 Price Action 知识库为核心的交易研究与自动化辅助项目，当前优先服务美股和港股。

本仓库当前已经按 V2 active plan 完成 `M0` 到 `M7` 的既定范围，并已进入 `M8：可靠性验证`。当前主线仍停留在 `paper / simulated`，没有进入真实 broker 接入、真实账户联通或 live execution。

当前同时在 `feature/m9-price-action-strategy-lab` 上推进一条低风险知识提炼支线：`M9：Price Action Strategy Lab`。该支线只负责从 transcript / Brooks PPT / notes 中提炼 strategy cards、测试计划和可回测候选，不改 trigger，不触碰 risk/execution/broker 边界。

## 当前状态

- 长期稳定基线：`main`
- 当前主线阶段：`M8：可靠性验证（进行中）`
- 当前已完成子阶段：
  - `M8A`：测试基线、文档与门禁落盘
  - `M8B`：知识库对齐与 callable/trace 接入
  - `M8C.1`：长周期日线验证
  - `M8C.2`：单标的与第二标的日内试点
  - `M8 shadow/paper baseline`：真实历史数据与录制型实时输入的只读 manifest/runbook 基线
  - `M8D.1`：Artifact & Trace Unification
  - `M8D.2`：Curated Promotion Minimal Expansion
  - `M8D.3`：Repository State Consistency
- 当前结论：`no-go`
- 默认运行边界：`paper / simulated`
- 默认历史回测数据源：`Longbridge simulated account -> local CSV cache`

详细状态见：

- `plans/active-plan.md`
- `docs/status.md`
- `docs/acceptance.md`
- `docs/decisions.md`

## 已完成里程碑

- `M0`：基础设施初始化、仓库结构、Codex agents、测试样本、KB 脚本
- `M1`：知识库 schema、KB 校验、wiki index、资料投放流程
- `M2`：数据 schema、本地 CSV/JSON loader、deterministic replay
- `M3`：research-only 的 PA context / setup / signal 原型
- `M4`：最小回测引擎与报告
- `M5`：paper-only 的模拟执行与风控闭环
- `M6`：新闻过滤与复盘整合
- `M7`：FormalBrokerAdapter assessment-only contract draft、readiness dossier、approval checklist
- `M8`：可靠性验证主线已完成当前检查点：
  - checked-in 关键 run：`m8c1_long_horizon_daily_validation`
  - checked-in intraday runs：`m8c2_intraday_pilot_spy_15m`、`m8c2_intraday_pilot_nvda_15m`
  - trace contract 已统一 actual hit / actual evidence / bundle support
  - 第二轮最小 curated promotion 已完成，但仍保持 research-only / non-trigger

## 关键模块

- `knowledge/`：raw 资料、wiki 知识页、schema
- `src/data/`：数据 schema、清洗、导入、回放
- `src/strategy/`：PA context、setup、signal 原型
- `src/backtest/`：最小回测引擎与报告
- `src/risk/`：paper-only 风控与熔断
- `src/execution/`：paper-only 执行、状态与审计日志
- `src/news/`：新闻过滤、解释与风险提示
- `src/review/`：复盘与报告聚合
- `src/broker/`：assessment-only broker contract draft

## 验证基线

常用验证命令：

```bash
python scripts/validate_kb.py
python scripts/run_reliability_suite.py
python -m unittest discover -s tests/unit -v
```

当前主线常用回归：

```bash
python -m unittest discover -s tests/reliability -v
python -m unittest discover -s tests/integration -v
python -m unittest tests/unit/test_public_backtest_demo.py -v
python -m unittest tests/unit/test_intraday_pilot.py -v
```

## 风险边界

- 不接真实资金
- 不启用实盘自动下单
- 不把付费券商 API 前置化
- 不把浏览器自动化写成生产执行链路
- 未获明确批准前，不进入真实 broker SDK、真实账户联通或 live execution

## 下一步

当前默认下一步不是继续 broker/live，也不是自动扩更多标的或更长窗口，而是保持现有 `M8` 检查点稳定、继续停留在 `paper / simulated`。

M9 支线的当前交付重点是：

- 保存 M8 基线快照
- 盘点 transcript / Brooks PPT / notes 来源
- 产出首批 strategy cards 与测试计划
- 用用户可读的方式说明哪些策略可以准备回测、哪些仍证据不足
- 针对 `PA-SC-002` 完成最小回测闭环与诊断型变体分析
- 后续默认历史回测与 `PA-SC-002` 重测统一使用 Longbridge 只读历史数据链路

如果你是从 GitHub 网页进入，想快速判断当前策略提炼支线做到哪里、应该先看哪些文件，优先看：

- `reports/strategy_lab/README.md`
- `reports/strategy_lab/m9_strategy_lab_summary.md`
- `reports/strategy_lab/pa_sc_002_first_backtest_report.md`
- `reports/strategy_lab/pa_sc_002_variant_suite.md`

只有在用户明确批准以下任一事项后，才允许重新评估后续阶段：

- 外部权限
- 真实账户
- 付费服务
- 真实 broker 接入评估或联通

## 说明

- `knowledge/raw/` 用于用户投放原始资料，raw 层不可随意改写。
- `feature/m7-broker-api-assessment` 只保留为历史阶段/里程碑分支，不再作为未来默认稳定基线。
- 当前未跟踪的 `knowledge/raw/...` 目录属于本地资料输入，不属于已完成里程碑代码产物。
