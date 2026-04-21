# Strategy Lab Guide

本文件用于帮助 GitHub 网页读者快速理解 `M9: Price Action Strategy Lab` 的当前阶段、重点文件和阅读顺序。

## 先看这条边界

- 自 `M9G.0` 起，旧 `PA-SC-*` strategy cards、测试计划与回测报告都只作为 legacy / historical baseline 保留。
- 新一轮 Strategy Factory 不再以旧 10 张卡或 `PA-SC-002` 为 seed；新 catalog 使用 `SF-*` 编号空间。
- 当前应优先阅读：
  - `docs/strategy-factory.md`
  - `reports/strategy_lab/strategy_factory_plan.md`
  - `reports/strategy_lab/strategy_factory/final_summary.md`

## 先看哪个分支

- 当前策略提炼与 `PA-SC-002` 回测实验都在：`feature/m9-price-action-strategy-lab`
- 长期稳定基线仍是：`main`

如果你的目标是判断“项目现在做到哪里了，以及下一步最该提炼/测试什么策略”，应优先查看 `feature/m9-price-action-strategy-lab`，不要只看 `main`。

## 当前阶段

- `M9A`~`M9F` 首轮已完成，但当前全部视为 legacy / historical baseline：
  - 已建立 strategy cards 目录与模板
  - 已盘点 transcript / Brooks PPT / notes
  - 已产出首批 `10` 张策略卡
  - 已为优先策略写测试计划
  - 已输出普通人可读的 strategy lab 总结
- `M9G.0` 已完成：
  - 已冻结 Strategy Factory 的 legacy boundary、provider contract、`SF-*` 命名空间与 ledger/run_state 模板

## 当前最重要的阅读顺序

1. 项目整体状态：
   - `docs/status.md`
   - `plans/active-plan.md`
2. Strategy Factory 契约：
   - `docs/strategy-factory.md`
   - `reports/strategy_lab/strategy_factory_plan.md`
   - `knowledge/wiki/strategy_factory/index.md`
3. Legacy 对照基线：
   - `reports/strategy_lab/m9_strategy_lab_summary.md`
   - `knowledge/wiki/strategy_cards/index.md`
4. `PA-SC-002` 历史 benchmark：
   - `knowledge/wiki/strategy_cards/combined/pa-sc-002-breakout-follow-through.md`
   - `knowledge/wiki/strategy_cards/combined/PA-SC-002-executable-v0.1.md`
5. `PA-SC-002` 第一轮实验：
   - `reports/strategy_lab/pa_sc_002_minimum_experiment_v0.1.md`
   - `reports/strategy_lab/pa_sc_002_first_backtest_report.md`
6. `PA-SC-002` 深入诊断：
   - `reports/strategy_lab/pa_sc_002_diagnostic_analysis.md`
   - `reports/strategy_lab/pa_sc_002_variant_suite.md`

## 当前最重要的业务结论

- 当前没有任何策略可以被表述为“已稳定盈利”。
- `PA-SC-002 v0.1` 已经可以被客观化并完成最小回测，但当前成本后仍为亏损。
- 当前更像是“全天候版本过宽”，不是“breakout follow-through 这个策略族必然无效”。
- 目前最值得继续正式重测的方向是：
  - `Midday Block`
- 但这仍然只是“下一轮候选假设”，不是已经确认的正式升级版。
- `Late Only` 只可视为 diagnostic upper bound，不能直接当作正式方案。

## 如果要让 ChatGPT 网页版继续给策略建议

最值得让它重点分析的是这几份文件：

- `reports/strategy_lab/m9_strategy_lab_summary.md`
- `knowledge/wiki/strategy_cards/index.md`
- `knowledge/wiki/strategy_cards/combined/pa-sc-002-breakout-follow-through.md`
- `knowledge/wiki/strategy_cards/combined/PA-SC-002-executable-v0.1.md`
- `reports/strategy_lab/pa_sc_002_first_backtest_report.md`
- `reports/strategy_lab/pa_sc_002_diagnostic_analysis.md`
- `reports/strategy_lab/pa_sc_002_variant_suite.md`

建议让它重点回答：

- `PA-SC-002` 当前亏损更像是规则太宽、时段不对，还是过滤器不够强？
- `Midday Block` 是否值得作为 `v0.2` 的唯一正式重测版本？
- 在不扩成大规模调参项目的前提下，`PA-SC-002` 下一轮最小改动应该是什么？
- 在 `PA-SC-002` 还未收敛前，是否应该暂缓 `PA-SC-003 / PA-SC-005`？

## 关于原始资料

- `knowledge/raw/` 仍保持只读。
- 本仓库的 GitHub 分支主要展示“策略提炼方案、策略卡、测试计划、回测与诊断报告”。
- 部分超大 raw PDF 不适合直接推送到普通 GitHub 仓库；即使不在远端，当前 strategy lab 的提炼进度和研究结论也已经完整体现在上述 Markdown 与实验产物中。
