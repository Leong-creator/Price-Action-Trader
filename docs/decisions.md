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
