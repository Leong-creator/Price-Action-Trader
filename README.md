# Price Action Trader

Price Action Trader 是一个以 Price Action 知识库为核心的交易研究与自动化辅助项目，当前优先服务美股和港股。

本仓库当前已经按 V2 active plan 完成 `M0` 到 `M9` 的既定研究阶段，并已完成 `M10：Price Action Strategy Refresh`、`M11 Paper Gate`、`M12.0-M12.10` 的只读观察、benchmark、universe cache coverage、visual review closure 与 definition fix/retest 检查点。当前主线仍停留在 `paper / simulated / read-only`，没有进入真实 broker 接入、真实账户联通或 live execution。

当前在 M10/M11/M12 分支族上推进低风险知识刷新与只读观察支线：从 Brooks v2 manual transcript、方方土 YouTube transcript、方方土 notes 重新提炼 `M10-PA-*` strategy catalog，并完成 M10 capital backtest、M10.13 read-only observation runbook、M11/M11.5 paper gate report、M12.0-M12.6 只读输入/观察/scanner/周报链路、M12.7 早期日线截图逻辑 benchmark 复测、M12.8 147 只 universe cache coverage / deferred / fetch plan、M12.9 图形策略 agent-side closure，以及 M12.10 定义修复复测；这些工作不改真实执行 trigger，不触碰 risk/execution/broker 边界。

自 M10 起，旧 `PA-SC-*` 与 M9 `SF-*` strategy factory 产物均仅作为 legacy / historical comparison 保留；M10 clean-room 提炼不得以旧编号、聚类或 triage 结论作为先验。

## 当前状态

- 长期稳定基线：`main`
- 当前主线阶段：`M12.10：Definition Fix and Retest（005 已补几何字段后 reject_for_now；004/007 已正式降级；paper gate 仍未批准）`
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
  - `M10.8`：Wave A Capital Backtest
  - `M10.9`：Definition Tightening
  - `M10.10`：Visual Wave B Gate
  - `M10.11`：Wave B Capital Backtest
  - `M10.12`：All Strategy Scorecard
  - `M10.13`：Read-only Observation Runbook
  - `M11`：Paper Gate Report
- 当前新增检查点：
  - `M12.0`：Longbridge 只读授权预检
  - `M12.1`：Longbridge 只读 K 线/feed 原型
  - `M12.2`：Tier A 核心策略每日只读观察
  - `M12.3`：图形策略预审包
  - `M12.4`：定义修正与复测记录
  - `M12.5`：147 只高流动性股票/ETF scanner 原型
  - `M12.6`：甲方周报成绩单
  - `M11.5`：Paper Gate Recheck，结论仍为 `not_approved`
  - `M12.7`：早期日线截图策略复用为 `M12-BENCH-001` benchmark，只可作为 scanner factor candidate
  - `M12.8`：147 只 universe K 线 coverage / deferred / fetch plan，当前完整覆盖目标窗口标的为 `0`
  - `M12.9`：`M10-PA-008/009` 图形策略 agent-side closure 与用户复核包；`M10-PA-004/007` 保持 definition evidence only
  - `M12.10`：`M10-PA-005` 补齐 34651 条 range 几何字段事件后仍 `reject_for_now`；`M10-PA-004/007` 正式降级为 visual-only / manual-labeling
- 当前结论：`no-go`
- 默认运行边界：`paper / simulated / read-only`
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

当前默认下一步不是继续 broker/live。M11.5 已形成 paper gate recheck，结论为 `not_approved`：M12.8 已把 M12.5 的 `147` 只 seed 全部入账，并明确当前完整覆盖目标窗口标的为 `0`，后续需要按 fetch plan 分批补齐只读 K 线缓存。M12.9 已把 `M10-PA-008/009` 整理为优先用户复核图例包，M12.10 已处理 `M10-PA-005/004/007` definition blocker；但用户确认、真实只读观察窗口、scanner cache 覆盖和人工业务审批都未完成前，仍不允许重新讨论 paper trading。

M10 支线的当前交付重点是：

- 登记 Brooks v2 manual transcript、方方土 YouTube transcript、方方土 notes 的来源优先级
- 产出 `M10-PA-*` clean-room strategy catalog
- 把 ChatGPT BPA 只作为 external comparison
- 把 M8/M9、`PA-SC-*`、`SF-*` 只作为 legacy inventory / comparison
- 跑通 M10.4 Wave A historical pilot：`1d` 使用 `2010-06-29 ~ 2026-04-21` 长窗口，`15m / 1h` 从本地 `5m` cache 聚合并记录 lineage
- 完成 M10.5 只读观察规划：不启动 observation runner，不接 broker，不下单，不批准 paper trading
- 完成 M10.6 recorded replay observation ledger：只用本地 cached OHLCV，记录 bar-close observation event，不生成执行或盈亏结论
- 完成 M10.7 甲方报告口径冻结：默认 `100,000 USD` 初始本金、`0.5%` 单笔风险、`1 / 2 / 5 bps` 成本压力，不接 broker、不批准 paper trading
- 完成 M10.8 Wave A capital backtest：输出 `M10-PA-001/002/005/012` 的模拟资金曲线、交易明细、胜率、回撤、分标的/分周期与成本压力成绩单
- 完成 M10.9 definition tightening：`M10-PA-005` 日内触发密度已通过重复确认去重和 20-bar 冷却降低，但因 range geometry 字段缺失，仍保持 `needs_definition_fix`
- 完成 M10.10 visual Wave B gate：`M10-PA-003/008/009/011` 与 `M10-PA-013` 进入 Wave B queue；`M10-PA-004/007/010` 暂不进入自动回测
- 完成 M10.11 Wave B capital backtest：`M10-PA-013/003/008/009/011` 已输出模拟资金曲线、交易明细、胜率、回撤和客户报告；视觉策略结果仍需人工图形复核
- 完成 M10.12 all-strategy scorecard：16 条 `M10-PA-*` 已汇总为甲方矩阵，其中 8 条完成资金测试、3 条需要定义修正、1 条图形复核保留、2 条只能辅助、2 条 research-only；组合 proxy 只纳入已完成资金测试策略，排除仍需定义修正的 `M10-PA-005`，期末权益为 `105728.18 USD`，但不是可执行组合回测
- 完成 M10.13 read-only observation runbook：主观察队列为 `M10-PA-001/002/012/008/009`，共 `13` 个策略周期；`M10-PA-005` 因定义未闭合排除，`M10-PA-003/011/013` 保留 watchlist/deferred
- 完成 M11 paper gate：候选池为 `M10-PA-001/002/012/008/009`，其中 `001/002/012` 是 Tier A 核心观察候选，`008/009` 是 Tier B 视觉条件候选；当前没有任何候选可作为 paper trading approval evidence，gate 保持关闭
- 完成 M12.0-M12.10：Longbridge 只读 feed、每日只读观察、图形预审、定义修正记录、scanner 原型、周报、M11.5 gate recheck、早期日线截图 benchmark 复测、147 只 universe cache coverage / deferred / fetch plan、visual review closure overlay 与 definition fix/retest 均已落盘；`M12-BENCH-001` 当前只是 `scanner_factor_candidate` benchmark，不是 M10 clean-room 策略，也不作为准入证据
- 下一步 `M12.11 Read-only Trading Dashboard`：建设本地只读 Web 看板，显示 scanner 候选、只读观察、hypothetical/simulated PnL、策略状态和 blocker；同时 M12.8 fetch plan 可并行分批执行；在 cache 真实补齐前，不得把 scanner 结果描述为 full universe 可用

如果你是从 GitHub 网页进入，想快速判断当前策略提炼支线做到哪里、应该先看哪些文件，优先看：

- `reports/strategy_lab/README.md`
- `reports/strategy_lab/m10_price_action_strategy_refresh/all_strategy_scorecard/m10_12/m10_12_client_final_report.md`
- `reports/strategy_lab/m10_price_action_strategy_refresh/read_only_observation/m10_13/m10_13_read_only_observation_runbook.md`
- `reports/strategy_lab/m10_price_action_strategy_refresh/paper_gate/m11/m11_paper_gate_report.md`
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
