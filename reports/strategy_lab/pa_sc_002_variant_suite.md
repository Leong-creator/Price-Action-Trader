# PA-SC-002 Variant Suite

本报告只做诊断型对照，不代表已经确认新的正式规则。

## 变体摘要

| 变体 | 交易数 | 胜率 | Expectancy | 净盈亏(USD) | PF | 样本结论 | 结论 |
|---|---:|---:|---:|---:|---:|---|---|
| Baseline v0.1 | 98 | 53.06% | -0.1066R | $-374.65 | 0.7938 | 达到最小实验样本要求，但未达到正式 promotion 门槛 | 当前基线 |
| Midday Block | 65 | 55.38% | -0.0637R | $-209.62 | 0.8651 | 达到最小实验样本要求，但未达到正式 promotion 门槛 | 比基线更好，但仍未完全成立 |
| Stronger Negative Veto | 80 | 52.50% | -0.0934R | $-415.82 | 0.8141 | 达到最小实验样本要求，但未达到正式 promotion 门槛 | 比基线更好，但仍未完全成立 |
| Midday Block + Stronger Veto | 55 | 54.55% | -0.0808R | $-137.13 | 0.8357 | 未达到最小实验样本要求 | 比基线更好，但仍未完全成立 |
| Late Only Upper Bound | 45 | 57.78% | -0.0162R | $-80.35 | 0.9626 | 未达到最小实验样本要求 | 比基线更好，但仍未完全成立 |

## 关键观察

- 当前 baseline 仍然亏损：`-0.1066R`，净盈亏 `$-374.65`。
- `Midday Block` 是当前唯一既改善明显、又仍达到最小 probe 门槛的单因素变体：`Expectancy -0.0637R`、净盈亏 `$-209.62`，相对 baseline 改善 `ΔExpectancy +0.0429R / ΔCash $+165.03`
- `Stronger Negative Veto` 单独使用时，只带来轻微 Expectancy 改善，但净盈亏反而更差：`Expectancy -0.0934R`、净盈亏 `$-415.82`，相对 baseline 改善 `ΔExpectancy +0.0132R / ΔCash $-41.17`
- `Midday Block + Stronger Veto` 的净亏损收缩最多，但交易数只有 `55` 笔，低于本轮最小 probe 门槛，因此暂时只能视为 underpowered 诊断结果：`Expectancy -0.0808R`、净盈亏 `$-137.13`，相对 baseline 改善 `ΔExpectancy +0.0258R / ΔCash $+237.52`
- `Late Only Upper Bound` 最接近盈亏平衡，但它本质上是后验诊断上限，不应直接当作正式升级版：`Expectancy -0.0162R`、净盈亏 `$-80.35`，相对 baseline 改善 `ΔExpectancy +0.0904R / ΔCash $+294.30`

## 推荐顺序

1. 若下一轮只能正式推进一个版本，优先选 `Midday Block`。它是当前最清楚、最少后验、且仍保留最小样本门槛的改善方向。
2. `Midday Block + Stronger Veto` 可以作为第二优先的后续诊断，但需要更长样本或更多标的补足交易数后，才适合升格成正式 retest 版本。
3. `Stronger Negative Veto` 单独使用不应作为下一轮主方向，因为它没有带来足够稳健的成本后改善。
4. `Late Only` 只适合作为诊断上限，不应直接当作正式升级版，因为它大幅压缩了可交易时间。
5. 这轮仍不建议先把主要精力放在改 `1R / 1.5R / 2R`，因为时段和过滤问题更主导结果。
