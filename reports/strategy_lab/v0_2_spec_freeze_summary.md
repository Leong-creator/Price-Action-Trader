# M9I.1 v0.2 Candidate Spec Freeze Summary

- `freeze_scope`: `SF-001 ~ SF-004`
- `excluded`: `SF-005`
- `source_basis`: `Wave2 quality_filter diagnostics only`
- `run_id`: `m9_strategy_factory_batch_backtest_20260422_035151`
- `boundary`: `paper/simulated`

## Global Summary

- 本轮只冻结 `v0.2-candidate` 候选规格，不新增策略、不跑新回测、不引入未测试过的过滤器。
- 现有 `reports/strategy_lab/specs/SF-001.yaml ~ SF-004.yaml` 继续保留为 `v0.1` 基线；`strategy_catalog.json` 与历史 `Wave2` triage 结果不改写。
- `quality_filter` 在本轮一律解释为 `diagnostic_selected_variant`，只能为下一轮更窄的 `Wave3 robustness validation` 提供候选规格，不能被写成 validated strategy。
- `SF-005` 继续保持 `deferred_single_source_risk`，本轮不生成 `v0.2-candidate`。
- 本轮未新增任何未测试过滤器。
- 本轮不自动启动 `Wave3`，只把仓库状态推进到 `v0.2-candidate specs frozen; eligible to plan Wave3 robustness validation`。

## SF-001

- `v0.1 -> v0.2-candidate` 一句话：收紧 signal bar 质量，并把允许的 pullback 深度从 `3` 根缩到 `2` 根。
- 候选文件：`reports/strategy_lab/specs/SF-001-v0.2-candidate.yaml`
- 证据来源：
  - `reports/strategy_lab/SF-001/variants/quality_filter/summary.json`
  - `reports/strategy_lab/SF-001/summary.json`
  - `reports/strategy_lab/SF-001/diagnostics.md`
  - `reports/strategy_lab/backtest_batch_summary.json`
- 预期改善：
  - 减少弱 signal bar
  - 减少过深 pullback 被误判为顺势恢复
- 残余风险：
  - 现金口径回撤未同步改善
  - 更窄过滤可能牺牲部分高频但边际有效信号
- 下一步验证建议：在 Wave3 中优先看多标的 split 下 drawdown 与 expectancy 是否同步改善，而不是只看总收益。

## SF-002

- `v0.1 -> v0.2-candidate` 一句话：把 breakout bar 和 follow-through bar 的实体阈值一起提高到 `0.60`。
- 候选文件：`reports/strategy_lab/specs/SF-002-v0.2-candidate.yaml`
- 证据来源：
  - `reports/strategy_lab/SF-002/variants/quality_filter/summary.json`
  - `reports/strategy_lab/SF-002/summary.json`
  - `reports/strategy_lab/SF-002/diagnostics.md`
  - `reports/strategy_lab/backtest_batch_summary.json`
- 预期改善：
  - 减少 weak breakout 被误判为 continuation
  - 减少区间内假突破追价
- 残余风险：
  - 样本会继续收缩
  - 美元层改善未与 R 改善同步放大
- 下一步验证建议：在 Wave3 中重点检验更强 breakout 过滤是否在不同标的上都保留正 expectancy，而不只是缩减交易数。

## SF-003

- `v0.1 -> v0.2-candidate` 一句话：先更严格限定“必须是 trading range”，再要求 reversal confirmation bar 更强。
- 候选文件：`reports/strategy_lab/specs/SF-003-v0.2-candidate.yaml`
- 证据来源：
  - `reports/strategy_lab/SF-003/variants/quality_filter/summary.json`
  - `reports/strategy_lab/SF-003/summary.json`
  - `reports/strategy_lab/SF-003/diagnostics.md`
  - `reports/strategy_lab/backtest_batch_summary.json`
- 预期改善：
  - 减少 broad directional move 被误当成 range-edge reversal
  - 减少 reversal confirmation 太弱时的继续逆势
- 残余风险：
  - `R` 口径仍为负
  - cash 正值只属于 sizing 解释层，不能当作策略转正
- 下一步验证建议：Wave3 应优先验证“亏损是否继续收敛”，而不是以 cash 正值作为晋级依据。

## SF-004

- `v0.1 -> v0.2-candidate` 一句话：只保留更紧的 tight-channel / Always-In 结构，把 channel overlap 上限收紧到 `0.35`。
- 候选文件：`reports/strategy_lab/specs/SF-004-v0.2-candidate.yaml`
- 证据来源：
  - `reports/strategy_lab/SF-004/variants/quality_filter/summary.json`
  - `reports/strategy_lab/SF-004/summary.json`
  - `reports/strategy_lab/SF-004/diagnostics.md`
  - `reports/strategy_lab/backtest_batch_summary.json`
- 预期改善：
  - 减少 weak channel / broad channel 被误当 tight channel continuation
- 残余风险：
  - `R` 口径仍为负
  - 交易笔数下降明显，Wave3 可能需要更长窗口补足验证
- 下一步验证建议：Wave3 应优先验证 tighter overlap 过滤是否真实降低回撤，而不是只看 cash 层是否重新转正。

## Excluded Strategy

- `SF-005` 继续 `deferred_single_source_risk`。
- 原因保持不变：`single-source corroboration and coarse family boundary`。
- 本轮明确不把 `SF-005` 纳入 `v0.2` freeze。
