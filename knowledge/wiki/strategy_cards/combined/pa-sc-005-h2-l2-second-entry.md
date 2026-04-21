---
title: 二次入场 / 两腿回调 H2-L2
type: setup
status: candidate
confidence: medium
market: ["US"]
timeframes: ["5m", "15m"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md", "wiki:knowledge/wiki/sources/fangfangtu-pullback-counting-bars-note.md"]
tags: ["strategy-card", "h2", "l2", "second-entry", "two-legs", "m9"]
applicability: ["用于研究 H2 / L2 与 second entry 的顺势恢复机会", "用于首批详细测试计划"]
not_applicable: ["不构成自动 trigger", "不代表已验证稳定盈利"]
contradictions: []
missing_visuals: []
open_questions: ["H1 直接入场与 H2/L2 二次入场的收益差异，仍需分环境比较"]
pa_context: ["trend", "pullback", "second-entry"]
market_cycle: ["trend", "tight-channel", "broad-channel"]
higher_timeframe_context: ["更高周期不能明显与当前 H2/L2 方向冲突"]
bar_by_bar_notes: ["出现新高/新低后需重新计数，不把旧 H1/H2 生搬硬套到新结构"]
signal_bar: ["H2/L2 对应的顺势 signal bar，要求背景支持且收盘质量足够好"]
entry_trigger: ["上涨趋势中突破 H2 signal bar 高点做多；下跌趋势中跌破 L2 signal bar 低点做空"]
entry_bar: ["H2/L2 signal bar 之后的触发 bar"]
stop_rule: ["默认在 H2/L2 signal bar 另一侧，或最近 swing 外侧"]
target_rule: ["先测试 1R / 1.5R / 2R，再比较 swing 持有版本"]
trade_management: ["若 H2/L2 触发后没有 follow-through，则优先快速降级处理"]
measured_move: false
invalidation: ["H2/L2 触发后立刻回到计数区间、或出现 bull/bear trap 证据"]
risk_reward_min: 1.5
last_reviewed: 2026-04-20
strategy_id: PA-SC-005
source_family: fangfangtu_transcript
setup_family: h2_l2_second_entry
market_context: ["两腿回调", "二次入场", "顺势恢复"]
evidence_quality: medium
chart_dependency: medium
needs_visual_review: false
test_priority: high
last_updated: 2026-04-20
---

# 二次入场 / 两腿回调 H2-L2

## 1. 来源依据

- 方方土 transcript 对“强趋势首次反转容易失败，需等 second entry”给出了明确提醒。
- Brooks `ABC Pullback in Bull Trend: H2` 与 `ABC Pullback in Bear Trend: L2` 给出了最直接的入场表达。
- 方方土《回调&数K线》笔记明确解释了 H1/H2/H3、L1/L2/L3 的计数规则，并强调创新高/创新低后要重新计数。

## 2. 核心交易思想

第一次反向尝试经常只是趋势里的暂时喘息，第二次尝试失败后，原趋势一方更容易重新掌控节奏。H2/L2 的价值不在于“数字本身”，而在于它把“第二次失败的回调”转成可观察、可测试的入场模板。

## 3. 适用市场环境

- 适合：明确趋势、回调呈两腿结构、背景仍偏顺势。
- 不适合：交易区间、强反转刚起步、回调已经演变成更大级别反转。

## 4. 入场前提

- 已有清晰趋势。
- 回调至少形成两段。
- 当前仍未破坏原趋势关键 swing 结构。

## 5. 入场触发

- 上涨趋势：H2 signal bar 高点被突破做多。
- 下跌趋势：L2 signal bar 低点被跌破做空。
- 若 H1 极强也可单独测试，但不与 H2/L2 混淆统计。

## 6. 止损规则

- 默认放在 H2/L2 signal bar 另一侧。
- 或放在最近回调 swing 外侧。
- 若 H2/L2 bar 过大，跳过。

## 7. 止盈 / 出场规则

- `v0.1`：固定 `1R`
- `v0.2`：固定 `1.5R`
- `v0.3`：固定 `2R`
- `v0.4`：前高/前低或趋势恢复 swing 持有

## 8. 失效条件

- H2/L2 触发后没有 follow-through。
- 价格迅速回到回调区间并形成 trap。
- 创出新极值后没有按规则重计数，仍硬套旧的 H2/L2。

## 9. 禁止交易条件

- 盘前盘后。
- 财报 / 重大新闻窗口。
- 交易区间中间或趋势不清晰时。
- 回调太深、止损太宽时。

## 10. 可量化规则草案

- 用最近 `N` 根高低点方向定义趋势。
- 以破前一根高/低点作为 H1/L1 开始计数。
- 出现新高/新低后重置计数。
- H2/L2 signal bar 要求实体与收盘质量达到阈值，且触发后 `1~2` 根 bar 内必须出现同向延续。

## 11. 参数范围

- 趋势识别窗口：`10 / 20 / 30 bars`
- 计数重置规则：`新高/新低即重置` vs `有效 swing 后重置`
- follow-through：`1 / 2 / 3 bars`
- 目标位：`1R / 1.5R / 2R`

## 12. 回测假设

- H2/L2 是否优于 H1/L1。
- 同样的 second entry 逻辑在 ETF 与高波动个股上的稳定性是否不同。
- 严格 second entry 是否能过滤掉 transcript 提醒的“首次反转失败”噪音。

## 13. 测试计划

- 测试目标：
  - 验证 H2/L2 是否是比 H1/L1 更稳健的顺势恢复模板。
- 测试标的：
  - `SPY / QQQ / NVDA / TSLA`
- 时间周期：
  - `5m` 主测
  - `15m` 复核
  - `1m` 不纳入验收
- 时间范围：
  - 使用 regular session 为主，后续再扩更长样本
- 数据需求：
  - OHLCV
  - regular session 标记
  - 财报 / 重大新闻排除标签
- 交易成本假设：
  - ETF：`1bp + 1 tick/side`
  - 高波动个股：`2bp + 2 ticks/side`
- 滑点假设：
  - 入场与止损均测试 `1~2 ticks`
- 样本切分：
  - 时间顺序 `50 / 25 / 25`
- 最低交易次数要求：
  - 总交易数至少 `100`
  - 任一 split 少于 `20` 笔则标 `insufficient_sample`
- 评价指标：
  - 交易次数、胜率、平均 R、期望值、PF、最大回撤、最大连续亏损
  - H1/H2/L1/L2 分组比较
  - 按环境 / 时间段 / 标的拆分
  - `skip` 原因统计
- 通过标准：
  - 成本后 `expectancy > 0`
  - 整体 `PF >= 1.15`
  - 样本外不显著转负
- 淘汰标准：
  - 结果只在单一标的有效
  - H2/L2 不优于更简单的 pullback 版本
  - 成本后优势消失

## 14. 预期失败模式

- 错把反转当二次入场。
- 计数没有重置，导致伪 H2/L2。
- 背景其实是交易区间，却按趋势恢复交易。

## 15. 当前结论

- `candidate`
- 规则可量化程度高，适合进入首批详细回测计划。
