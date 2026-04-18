# 决策记录

## D-0001 初始化范围

- 日期：2026-04-16
- 结论：当前轮次只完成基础设施初始化，不开始正式功能开发。

## D-0002 数据源优先级

- 日期：2026-04-16
- 结论：静态 CSV/JSON > 用户导出文件 > 免费公共数据源 > 浏览器临时验证 > 正式券商 API。

## D-0003 风险边界

- 日期：2026-04-16
- 结论：禁止未经批准接入真实资金账户、实盘自动下单和付费券商 API。

## D-0004 M1 知识库契约冻结

- 日期：2026-04-17
- 结论：M1 冻结了 wiki frontmatter 基础字段、setup 额外必填字段、KB 校验约束与 wiki index 最小输出字段，后续 M2/M3 不得随意破坏兼容性。

## D-0005 M2 数据契约冻结

- 日期：2026-04-17
- 结论：M2 冻结了 `src/data/schema.py` 中的 OHLCV、新闻事件、ValidationError、CleanedRecord 最小契约，以及 loader/replay 对这些契约的直接消费方式；后续 M3/M4 不得重新发明并行数据结构。

## D-0006 M3 信号原型契约冻结

- 日期：2026-04-17
- 结论：M3 冻结了 `src/strategy/` 中 research-only 的 `PAContextSnapshot`、`SetupCandidate`、`Signal` 最小契约，以及直接回链到 wiki concept/setup/rule 页面与 source/raw 的 traceability 要求；后续 M4/M5 必须消费该结构化 signal，而不是重新回退到自由文本或并行对象。

## D-0007 M4 回测基线契约冻结

- 日期：2026-04-17
- 结论：M4 冻结了 `src/backtest/` 中的最小交易记录、统计摘要和报告输出，以及 deterministic baseline 假设：next-bar-open entry、signal-bar extremum stop、fixed 2R target、same-bar stop-first、unfinished trade 不进入 closed-trade 收益统计；后续 M5 不得绕开这些结构化输出。

## D-0008 M5 纸面执行与风控契约冻结

- 日期：2026-04-17
- 结论：M5 冻结了 `src/risk/` 与 `src/execution/` 的 paper-only 最小契约、request-binding 校验、重复信号阻断、市场关闭阻断、连续亏损熔断与恢复条件、以及可复盘的 close-path 审计字段；后续 M6 不得绕过这些结构化接口或回退到未绑定的执行语义。

## D-0009 M6 新闻过滤与复盘契约冻结

- 日期：2026-04-17
- 结论：M6 冻结了 `src/news/` 与 `src/review/` 的最小契约，要求新闻只能作为 filter / explanation / risk_hint 辅助因子；`evaluate_news_context(...)` 必须显式接收可验证的 `reference_timestamp` 以阻断 future-event leakage；`ReviewItem` 必须保留结构化 `news_review_notes` 与可追溯 `source_refs`；后续 M7 不得把这些评估输出误接成真实下单或 live execution 语义。

## D-0010 M7 Broker Readiness 评估结论冻结

- 日期：2026-04-17
- 结论：M7 冻结了 `src/broker/` 的 assessment-only contract draft 与 readiness artifact；当前明确结论为 `no-go`，系统继续停留在 paper / simulated。后续只有在用户明确批准外部权限、真实账户、付费服务或下一阶段评估后，才允许重新讨论真实 broker 接入；在此之前不得引入真实 broker SDK、外部网络调用、真实账户联通或 live execution 路径。

## D-0011 M8 可靠性验证优先级冻结

- 日期：2026-04-17
- 结论：在重新评估真实 broker、真实账户或 live execution 之前，必须先完成 `M8：可靠性验证`。M8 的首目标是验证知识约束一致性、研究链可复现、paper-only 执行链安全性，以及真实输入下仍然保守稳定；在 M8 完成前，系统继续停留在 `paper / simulated`，不重开 broker/live 讨论。

## D-0012 阶段整合与高风险合并规则冻结

- 日期：2026-04-17
- 结论：对于低/中风险阶段，验收通过、相关测试全绿、文档同步完成、且无未解决 blocker 后，合并到稳定基线分支是最后一个必做动作，不得拖到整个项目结束后再统一合并。`src/execution/`、`src/risk/`、`src/broker/` 及任何 `live / real-money / real-account` 路径属于高风险模块，只能自动准备合并材料，不得自动最终合并，必须等待用户明确批准。当前 `M8B` 已通过 merge commit `0047100` 从 `integration/m8-reliability-validation` 整合进 `feature/m7-broker-api-assessment`；`M8C` 尚未开始。

## D-0013 用户可读历史回测演示边界冻结

- 日期：2026-04-17
- 结论：为提供用户可直接理解的真实历史数据回测演示，优先使用公共、低成本、无需 broker 权限的数据源，并将下载结果缓存为本地 CSV。若环境无 Alpha Vantage key，则允许回退到 `yfinance` 作为 research-only fallback。该演示链路只服务于历史研究与 `paper / simulated` 报告输出，不代表 broker/live/real-money 能力。

## D-0014 M8B.1 知识来源 traceability 门禁冻结

- 日期：2026-04-17
- 结论：raw 层 transcript / PPT 只有在对应 `knowledge/wiki/sources/*.md` 登记页存在、wiki index 收录、active rule pack 明确接入、且默认 strategy knowledge bundle 真正加载该 rule pack 后，才允许出现在 `signal.source_refs` / `signal.explanation` 中。只有 raw 文件而未完成结构化接线时，strategy 不得编造其引用；完成最小接线后，这些来源仍只代表“已登记且可追溯”，不代表其内容已被抽取成正式规则。

## D-0015 M8B.2 两阶段知识原子化门禁冻结

- 日期：2026-04-17
- 结论：`M8B.2` 拆分为 `M8B.2a` 与 `M8B.2b`。`M8B.2a` 只允许建设 source registry、chunk registry、knowledge atom schema、builders/validators 与 callable index；`M8B.2b` 只有在 `2a` 全部测试通过、未触发熔断、且 reviewer / qa 通过后，才允许接 strategy / explanation / review / report。`statement` 是中间层 callable atom，默认 `draft`，不是 executable rule，不得参与 trigger 判定。若 10 个 in-scope source 中 `blocked >= 4`、关键 curated atoms 无法形成稳定 evidence-backed atom、或 `statement` 抽取无法稳定回溯证据，则必须停在 `M8B.2a`，不得进入 `2b`。

## D-0016 M8B.2a 审计与整合门禁冻结

- 日期：2026-04-17
- 结论：`M8B.2a` 在进入稳定基线前必须先经过 statement 质量审计；只有当审计结论达到 `pass` 或 `pass_with_small_fixes`、相关测试通过、文档同步完成、且无 blocker 时，才允许作为低/中风险子阶段整合进稳定基线。当前 `M8B.2a.1` 的审计结论为 `pass_with_small_fixes`：已通过最小修复去除明显页眉页脚 / 时间轴 / 起始标点 / 未完成碎片并做保守去重，随后通过 merge commit `23755c0` 从 `feature/m8b2-knowledge-atomization-callable-access` 整合进 `feature/m7-broker-api-assessment`。后续 `M8B.2b` 已从最新稳定基线独立分支启动并整合回稳定基线。

## D-0017 M8B.2b Knowledge Trace 接入门禁冻结

- 日期：2026-04-17
- 结论：`M8B.2b` 只允许把 callable atom 层接入 `Signal / Review / report` 的 trace 能力，不允许改 trigger 逻辑。`statement`、`source_note`、`contradiction`、`open_question` 只进入 `knowledge_trace` / `kb_trace` / machine-readable report，不得参与 trigger，不得因为 source family statement 数量更多而提高 confidence 或影响触发结果。legacy `source_refs` 继续保留，`knowledge_trace.json` 作为全量机器产物落盘，Markdown 报告只展示精简 trace 摘要。当前 `M8B.2b` 已整合进稳定基线，且 trigger 逻辑未改变。

## D-0018 M8C.1 长周期日线验证边界冻结

- 日期：2026-04-17
- 结论：`M8C.1` 只允许在 `paper / simulated` 边界内，把现有 daily public history demo 扩展为更长周期、多 split、多 regime 的验证套件；不得进入 intraday、期权、broker/live/real-money，也不得修改 trigger 逻辑。`knowledge_trace` 与 legacy `source_refs` 继续兼容，`statement` / `source_note` 只作 trace 与报告证据，不得进入 trigger 或影响 confidence。验证必须输出 per-symbol breakdown、walk-forward split、regime 摘要、structured `no_trade / wait`、blocked signals 汇总，以及 curated vs statement trace 占比摘要。由于 Al Brooks statement 数量偏大，`M8C.1` 的 trace 审计必须继续使用 curated-first 与 source family 多样性控制；任何结论都不得使用 statement 数量作为收益、权重或质量代理。`M8C.2` 只有在 `M8C.1` 验收通过并整合进稳定基线后才允许启动。

## D-0019 M8C.1 整合结论冻结

- 日期：2026-04-17
- 结论：`M8C.1` 已作为低/中风险验证子阶段通过验收，允许整合进稳定基线 `feature/m7-broker-api-assessment`。其整合只代表 long-horizon daily validation、walk-forward split、regime 摘要、structured `no_trade / wait` 与 knowledge trace coverage 已进入稳定基线；不代表 `M8C.2` 已启动，不代表进入期权，不代表 trigger 逻辑发生变化，也不代表 broker/live/real-money 边界被放宽。

## D-0020 主线正规化到 main

- 日期：2026-04-17
- 结论：自当前轮次起，`main` 是唯一长期稳定基线。所有新的 `feature/*`、`fix/*`、`docs/*`、`test/*`、`integration/*` 分支都从 `main` 切出；低/中风险阶段验收通过后的默认合并目标也改为 `main`。`src/execution/`、`src/risk/`、`src/broker/` 及任何 `live / real-money / real-account` 路径仍属于高风险模块，可以自动准备合并，但未经用户明确批准不得最终合并到 `main`。`feature/m7-broker-api-assessment` 只保留为历史阶段/里程碑分支，不再作为未来默认合并目标。

## D-0021 M8C.2 Intraday Pilot 边界冻结

- 日期：2026-04-17
- 结论：`M8C.2` 只允许在 `paper / simulated` 边界内完成单标的 intraday pilot。当前冻结范围为 `SPY / 15m / America/New_York / 2026-03-30 ~ 2026-04-16`，验证目标是 session open/close、market hours / timezone、日内风险重置、duplicate signal protection、slippage / fee 最小模型、`no-trade / wait` 结构化输出，以及 intraday 下的 `knowledge_trace` 稳定表现。`statement`、`source_note`、`contradiction`、`open_question` 仍只进入 trace，不得进入 trigger；Brooks statement 数量不得成为 confidence、权重或排序代理。当前 `M8C.2` 已通过 merge gate 合并进 `main`；仍未进入期权、broker、live、real-money。

## D-0022 M8D.1 Artifact & Trace Unification 边界冻结

- 日期：2026-04-18
- 结论：`M8D.1` 只允许统一旧 daily run 与当前 intraday run 的 artifact / trace 语义，不允许做 curated promotion，不允许进入仓库状态整齐化。自本决策起，user-facing `source_refs` 在 artifact 中只代表 actual refs，`bundle_support_refs` 必须单独存在；若需要兼容旧语义，只能通过 `legacy_source_refs` 单独保留。`m3-research-reference-pack` 这类 broad support / registry ref 不得继续以 visible actual hit 身份主导 `summary.json`、`report.md`、`knowledge_trace.json` 或 `knowledge_trace_coverage.json`。`knowledge_trace_coverage.json` 必须区分 `actual_hit_*`、`actual_evidence_*` 与 `bundle_support_*` 家族统计。`M8D.1` 不改 trigger、不改 `knowledge/raw`、不进入 broker/live/real-money，且已把 `reports/backtests/m8c1_long_horizon_daily_validation/` 重算到该 canonical contract。

## D-0023 M8D.2 / M8D.3 后续阶段冻结

- 日期：2026-04-18
- 结论：在 `M8D.1` 完成并整合进 `main` 之前，`M8D.2 Curated Promotion Minimal Expansion` 与 `M8D.3 Repository State Consistency` 都不得启动。`M8D.2` 未来仍只允许做最小 curated promotion，且不得改 trigger、不得改 `knowledge/raw`；`M8D.3` 未来只允许做 README / status / plan / acceptance / decisions 的仓库口径对齐。当前这两个阶段均未开始，不得在 `M8D.1` 的实现、测试或合并中夹带执行。

## D-0024 M8C.2 第二标的日内验证边界冻结

- 日期：2026-04-18
- 结论：在首轮 `SPY / 15m` intraday pilot 完成后，允许在不改 trigger 的前提下扩一个第二高流动性标的做同边界验证。当前冻结的第二标的扩展为 `NVDA / 15m / America/New_York / 2026-03-30 ~ 2026-04-16`。该扩展继续只验证 session open/close、market hours / timezone、日内风险重置、duplicate signal protection、slippage / fee、`no-trade / wait` 与 `knowledge_trace` 的跨标的一致性；`statement`、`source_note`、`contradiction`、`open_question` 仍不得进入 trigger，Brooks statement 数量也不得成为 confidence、权重或排序代理。当前第二标的扩展已整合进 `main`；仍未进入期权、broker、live、real-money。

## D-0025 M8D.2 Curated Promotion Minimal Expansion 边界冻结

- 日期：2026-04-18
- 结论：`M8D.2` 只允许做第二轮最小 curated promotion，不做 full promotion，不改 trigger，不改 `knowledge/raw`，不进入 broker/live/real-money。当前只新增两个 promoted curated `rule` theme：`breakout_follow_through_failed_breakout` 与 `tight_channel_trend_resumption`。它们只进入 actual trace、signal explanation、`no-trade / wait`、report / review 层；`statement`、`source_note`、`contradiction`、`open_question` 仍不得进入 trigger。当前 `reports/backtests/m8c1_long_horizon_daily_validation/` 已重算到该最小 promotion contract，且 `tests/reliability` / `tests/unit` 全绿；`M8D.3` 尚未开始。

## D-0026 M8D.3 Repository State Consistency 冻结

- 日期：2026-04-18
- 结论：`M8D.3` 只用于修复仓库级状态口径漂移，不得借机修改 trigger、knowledge promotion、`knowledge/raw`、broker/live/real-money 或新增验证窗口。自本决策起，仓库主显示口径统一为：`main` 是唯一长期稳定基线；当前主线阶段是 `M8：可靠性验证`；`M8 shadow/paper baseline` 视为已完成前置基线；`M8D.1 Artifact & Trace Unification`、`M8D.2 Curated Promotion Minimal Expansion` 与 `M8D.3 Repository State Consistency` 均已完成。`README.md`、`docs/status.md`、`plans/active-plan.md`、`docs/acceptance.md`、`docs/decisions.md`、`docs/roadmap.md` 与相关 reliability/shadow README 现已按该口径同步；`feature/m7-broker-api-assessment` 只保留为历史阶段/里程碑分支，不再作为当前分支或稳定基线表述。
