# M9 Strategy Lab Summary

## 本轮做了什么

- 先保护了稳定基线：`main` 保持在 M8E.2，M9 工作全部转到 `feature/m9-price-action-strategy-lab`。
- 保存了项目初始快照：[m9_initial_project_snapshot.md](/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/m9_initial_project_snapshot.md)
- 建立了策略卡模板与索引：[strategy_cards/index.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/index.md)
- 盘点了来源清单：[m9_source_inventory.md](/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/m9_source_inventory.md)
- 记录了提炼批次与证据缺口：[m9_strategy_extraction_log.md](/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/m9_strategy_extraction_log.md)
- 完成首批 10 张策略卡，并为其中 3 张写了详细测试计划。

## 安全边界

| 项目 | 当前边界 |
|---|---|
| 开发分支 | `feature/m9-price-action-strategy-lab` |
| 稳定基线 | `main` 保持 M8E.2，不直接改主线 |
| 研究范围 | `research / backtest / paper / simulated` |
| 明确禁止 | 真实 broker、真实账户、真实资金、自动实盘下单、付费 API |
| `knowledge/raw/` | 只读，不改写、不覆盖、不移动原始资料 |

## 已盘点的知识来源

| 优先级 | 来源族 | 说明 | 本轮作用 |
|---|---|---|---|
| 1 | `fangfangtu_transcript` | 方方土 YouTube 转录 | 首批策略卡第一证据来源 |
| 2 | `al_brooks_ppt` | Brooks PPT 1-36 / 37-52 单元 | 补 entry、follow-through、H2/L2、trend day、opening reversal 等边界 |
| 3 | `fangfangtu_notes` | 市场周期、突破、回调、楔形等 notes | 补中文术语、例子、风险提醒和缺口说明 |

## 首批 10 张策略卡

| 策略 ID | 策略名称 | 来源 | 市场环境 | 方向 | 周期 | 状态 | 测试优先级 | 当前结论 |
|---|---|---|---|---|---|---|---|---|
| `PA-SC-001` | 趋势中回调后的顺势恢复 | transcript → Brooks → 回调 notes | 趋势 / 回调恢复 | `both` | `5m / 15m` | `candidate` | `high` | 可准备回测 |
| `PA-SC-002` | 突破后的 Follow-Through 延续 | transcript → Brooks → 突破 notes | 突破 / 延续 | `both` | `5m / 15m` | `candidate` | `high` | 可准备回测 |
| `PA-SC-003` | 失败突破后回到区间的反转 | transcript → Brooks → 突破 notes | 失败突破 / 区间回归 | `both` | `5m / 15m` | `candidate` | `high` | 可准备回测 |
| `PA-SC-004` | 交易区间上沿 / 下沿反转 | transcript → Brooks → 突破 notes | 交易区间边缘 | `both` | `5m / 15m` | `candidate` | `medium` | 可准备回测 |
| `PA-SC-005` | 二次入场 / 两腿回调 H2-L2 | transcript → Brooks → 回调 notes | 趋势回调 / second entry | `both` | `5m / 15m` | `candidate` | `high` | 可准备回测 |
| `PA-SC-006` | 紧密通道中的顺势恢复 | transcript → Brooks → 市场周期 notes | tight channel / Always In | `both` | `5m / 15m` | `candidate` | `medium` | 可准备回测 |
| `PA-SC-007` | 楔形 / 衰竭后的反转 | transcript → Brooks → 楔形 notes | 楔形 / climax / broad channel | `both` | `5m / 15m` | `draft` | `medium` | 缺图表确认 |
| `PA-SC-008` | 开盘区间突破或失败突破 | transcript → Brooks → 楔形 notes | opening range / trend from the open | `both` | `1m / 5m / 15m` | `draft` | `medium` | 缺开盘样本与例图 |
| `PA-SC-009` | 强趋势日 vs 震荡日过滤 | transcript → Brooks → 市场周期 notes | regime filter | `neutral` | `5m / 15m` | `candidate` | `high` | 可作为过滤器测试 |
| `PA-SC-010` | 高波动个股趋势延续与风险过滤 | transcript → Brooks → 楔形 notes | 高波动 / 风险过滤 | `neutral` | `5m / 15m / 1d` | `draft` | `medium` | 仅形成研究假设 |

## 目前最值得先测的 3 个策略

| 策略 ID | 优先原因 | 当前状态 | 备注 |
|---|---|---|---|
| `PA-SC-002` | 证据最完整，规则较清楚，适合直接做 breakout + FT 过滤测试 | `candidate` | 已写详细测试计划 |
| `PA-SC-003` | 能和 `PA-SC-002` 形成正反对照，便于比较突破成功与失败两类情景 | `candidate` | 已写详细测试计划 |
| `PA-SC-005` | second entry / H2-L2 是价格行为体系里最经典、也最容易参数化的一类 | `candidate` | 已写详细测试计划 |

## 每个高优先策略准备怎么测

| 策略 ID | 测试标的 | 测试周期 | 样本要求 | 成本假设 | 关键指标 | 通过标准 | 淘汰标准 |
|---|---|---|---|---|---|---|---|
| `PA-SC-002` | `SPY / QQQ / NVDA / TSLA` | `5m` 主测，`15m` 复核 | 总交易数至少 `100`；任一 split 少于 `20` 记 `insufficient_sample` | ETF `1bp + 1 tick/side`；高波动个股 `2bp + 2 ticks/side` | 交易次数、胜率、平均 R、期望值、PF、最大回撤、skip 统计 | 成本后 `expectancy > 0`，整体 `PF >= 1.15`，验证/样本外 `PF >= 1.00` | 样本外转负、结果只靠单一标的、成本后优势消失 |
| `PA-SC-003` | `SPY / QQQ / NVDA` | `5m` 主测，`15m` 复核 | 同上 | 同上 | 同上，另看失败突破 vs 普通回调区分 | 成本后期望值为正，且区间回归表现稳定 | 区分不清失败突破与普通 pullback，或样本外失效 |
| `PA-SC-005` | `SPY / QQQ / NVDA / TSLA` | `5m` 主测，`15m` 复核 | 同上 | 同上 | 同上，另看 H2/L2 参数敏感性 | 不同参数下仍保留正期望，且不依赖单一时间段 | 只在单一参数或单一标的有效 |

## 哪些策略还缺图表或证据

| 策略 ID | 当前缺口 | 当前处理 |
|---|---|---|
| `PA-SC-007` | 三推识别、nested wedge、truncated wedge 高度依赖图表 | 保留 `draft`，`needs_visual_review: true` |
| `PA-SC-008` | opening range 定义、开盘失败突破与开盘噪音的边界不清 | 保留 `draft`，`needs_visual_review: true` |
| `PA-SC-010` | 高波动过滤更像风险提醒集合，缺统一字段和事件标签 | 保留 `draft`，`needs_visual_review: true` |

## 本轮还不能证明什么

- 还不能证明任何策略“稳定盈利”。
- 还不能证明楔形、开盘区间和高波动过滤已经足够清楚到可以自动回测。
- 还不能证明当前数据覆盖足以支撑样本外结论。

## 回测 / 模拟盘结果

本轮没有新增回测或模拟盘结果。原因不是“忘了做”，而是本轮目标先把知识来源转成策略卡和测试计划，避免在规则还不清楚时粗暴开跑回测。

当前已知的数据缺口：

- 开盘区间类策略需要更标准化的 regular-session 开盘样本。
- 高波动过滤需要财报 / 重大新闻与波动标签。
- 楔形类策略需要先补人工图表复核，再决定是否值得程序化。

## 建议保留、修改或淘汰

| 类别 | 策略 ID | 建议 |
|---|---|---|
| 优先保留并先测 | `PA-SC-002`、`PA-SC-003`、`PA-SC-005` | 直接进入第一轮回测准备 |
| 保留，作为第二批 | `PA-SC-001`、`PA-SC-004`、`PA-SC-006`、`PA-SC-009` | 先看高优先策略结果，再决定是否扩测 |
| 暂不淘汰，但先降级 | `PA-SC-007`、`PA-SC-008`、`PA-SC-010` | 先补图表/标签/定义，未补齐前不进回测 |

## 下一轮建议优先测试的 3 个策略

1. `PA-SC-002` 突破后的 Follow-Through 延续
2. `PA-SC-003` 失败突破后回到区间的反转
3. `PA-SC-005` 二次入场 / 两腿回调 H2-L2
