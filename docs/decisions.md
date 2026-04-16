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
