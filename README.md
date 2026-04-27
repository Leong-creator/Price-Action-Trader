# Price Action Trader

Price Action Trader 是一个以 Price Action 知识库为核心的交易研究与自动化辅助项目，当前优先服务美股和港股。

本仓库当前已经按 V2 active plan 完成 `M0` 到 `M9` 的既定研究阶段，并已启动 `M10：Price Action Strategy Refresh`。当前主线仍停留在 `paper / simulated`，没有进入真实 broker 接入、真实账户联通或 live execution。

当前在 `codex/m10-price-action-strategy-refresh` 上推进低风险知识刷新支线：从 Brooks v2 manual transcript、方方土 YouTube transcript、方方土 notes 重新提炼 `M10-PA-*` strategy catalog、source ledger、visual gap ledger、visual golden case pack、Wave A backtest spec freeze、M10.4 historical pilot、M10.5 read-only observation plan、M10.6 recorded replay observation ledger、M10.7 client-facing business metric policy 与后续测试规划，不改 trigger，不触碰 risk/execution/broker 边界。

自 M10 起，旧 `PA-SC-*` 与 M9 `SF-*` strategy factory 产物均仅作为 legacy / historical comparison 保留；M10 clean-room 提炼不得以旧编号、聚类或 triage 结论作为先验。

## 当前状态

- 长期稳定基线：`main`
- 当前主线阶段：`M10：Price Action Strategy Refresh（进行中）`
- 当前已完成子阶段：
  - `M8A`：测试基线、文档与门禁落盘
  - `M8B`：知识库对齐与 callable/trace 接入
  - `M8C.1`：长周期日线验证
  - `M8C.2`：单标的与第二标的日内试点
  - `M8 shadow/paper baseline`：真实历史数据与录制型实时输入的只读 manifest/runbook 基线
  - `M8D.1`：Artifact & Trace Unification
  - `M8D.2`：Curated Promotion Minimal Expansion
  - `M8D.3`：Repository State Consistency
  - `M10.1`：策略目录复审与测试承接
  - `M10.2`：Visual Golden Case Pack
  - `M10.3`：Backtest Spec Freeze
  - `M10.4`：Historical Backtest Pilot
  - `M10.5`：Read-only Observation Plan
  - `M10.6`：Read-only Observation Input / Ledger Prototype
  - `M10.7`：Business Metric Policy
- 当前结论：`no-go`
- 默认运行边界：`paper / simulated`
- 默认历史回测入口：以 Strategy Factory 的 active provider config 解析出的 `primary_provider` 为准
- 当前 M10 重点产物：`reports/strategy_lab/m10_price_action_strategy_refresh/`

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

当前默认下一步不是继续 broker/live，也不是自动扩更多标的或更长窗口，而是进入 `M10.8 Wave A Capital Backtest`，把现有 Wave A 事件链路转成甲方可读的模拟资金曲线、交易明细、胜率、回撤和分标的/分周期成绩单，继续停留在 `paper / simulated`。

M10 支线的当前交付重点是：

- 登记 Brooks v2 manual transcript、方方土 YouTube transcript、方方土 notes 的来源优先级
- 产出 `M10-PA-*` clean-room strategy catalog
- 把 ChatGPT BPA 只作为 external comparison
- 把 M8/M9、`PA-SC-*`、`SF-*` 只作为 legacy inventory / comparison
- 跑通 M10.4 Wave A historical pilot：`1d` 使用 `2010-06-29 ~ 2026-04-21` 长窗口，`15m / 1h` 从本地 `5m` cache 聚合并记录 lineage
- 完成 M10.5 只读观察规划：不启动 observation runner，不接 broker，不下单，不批准 paper trading
- 完成 M10.6 recorded replay observation ledger：只用本地 cached OHLCV，记录 bar-close observation event，不生成执行或盈亏结论
- 完成 M10.7 甲方报告口径冻结：默认 `100,000 USD` 初始本金、`0.5%` 单笔风险、`1 / 2 / 5 bps` 成本压力，不接 broker、不批准 paper trading

如果你是从 GitHub 网页进入，想快速判断当前策略提炼支线做到哪里、应该先看哪些文件，优先看：

- `reports/strategy_lab/README.md`
- `reports/strategy_lab/m10_price_action_strategy_refresh/strategy_catalog_m10.json`
- `reports/strategy_lab/m10_price_action_strategy_refresh/source_support_matrix_m10.json`
- `reports/strategy_lab/m10_price_action_strategy_refresh/m10_test_plan.md`
- `reports/strategy_lab/m10_price_action_strategy_refresh/workspace_audit_legacy_inventory_m10.md`

只有在用户明确批准以下任一事项后，才允许重新评估后续阶段：

- 外部权限
- 真实账户
- 付费服务
- 真实 broker 接入评估或联通

## 说明

- `knowledge/raw/` 用于用户投放原始资料，raw 层不可随意改写。
- `feature/m7-broker-api-assessment` 只保留为历史阶段/里程碑分支，不再作为未来默认稳定基线。
- 当前未跟踪的 `knowledge/raw/...` 目录属于本地资料输入，不属于已完成里程碑代码产物。
