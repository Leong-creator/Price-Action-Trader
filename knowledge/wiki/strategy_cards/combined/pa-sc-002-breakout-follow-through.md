---
title: 突破后的 Follow-Through 延续
type: setup
status: candidate
confidence: medium
market: ["US"]
timeframes: ["5m", "15m"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md", "wiki:knowledge/wiki/sources/fangfangtu-breakout-note.md", "wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md"]
tags: ["strategy-card", "breakout", "follow-through", "continuation", "m9"]
applicability: ["用于研究突破后是否出现可跟随的延续", "用于首批详细测试计划"]
not_applicable: ["不构成自动 trigger", "不代表已验证稳定盈利"]
contradictions: []
missing_visuals: []
open_questions: ["follow-through 至少需要 1 根还是 2 根确认 bar，仍需回测"]
pa_context: ["breakout", "trend", "trend-resumption"]
market_cycle: ["breakout", "tight-channel"]
higher_timeframe_context: ["更高周期若正处于明显阻力/支撑边界，应降低突破延续预期"]
bar_by_bar_notes: ["不能把单根大 bar 直接当作有效突破，必须观察后续 bar 是否继续脱离密集区"]
signal_bar: ["大实体、收盘靠近极值、上/下影线短的 breakout bar"]
entry_trigger: ["突破 bar 之后出现 follow-through，再沿突破方向入场"]
entry_bar: ["突破 bar 后的第一根或第二根确认 bar"]
stop_rule: ["放在 breakout signal bar 另一侧，或突破前结构边界内侧"]
target_rule: ["先测试 1R / 1.5R / 2R，再比较 measured move 是否更有利"]
trade_management: ["若 follow-through 后迅速衰竭，应优先减仓或退出，不强扛"]
measured_move: true
invalidation: ["突破后无 follow-through、迅速回到区间、或出现明显 opposite breakout 证据"]
risk_reward_min: 1.5
last_reviewed: 2026-04-20
strategy_id: PA-SC-002
source_family: fangfangtu_transcript
setup_family: breakout_follow_through
market_context: ["突破", "follow-through 延续"]
evidence_quality: medium
chart_dependency: medium
needs_visual_review: false
test_priority: high
last_updated: 2026-04-20
---

# 突破后的 Follow-Through 延续

## 1. 来源依据

- 方方土 transcript 把突破缺口定义为趋势确立信号，并强调突破后应看到额外的跟随 bar。
- Brooks 说明突破可以是一串连续的小趋势 bar，不一定只有一根惊喜 bar。
- 方方土《突破》笔记明确写出“好的突破需要有好的跟随”“突破需要确认 FT”。
- 现有 `breakout-follow-through-failed-breakout-minimal` 规则页也把 follow-through 作为突破质量的核心。

## 2. 核心交易思想

真正有价值的突破，不只是“冲出去”，而是冲出去之后还有人继续在同方向买/卖。没有 follow-through 的突破，经常只是区间里的假动作；有 follow-through 的突破，更可能演变成可交易的趋势腿。

## 3. 适用市场环境

- 适合：突破刚发生、方向明确、突破 bar 质量高、后续 bar 继续脱离密集区。
- 不适合：交易区间中部、前方阻力/支撑太近、突破后马上停住或回落。

## 4. 入场前提

- 已有明确的区间边界、趋势线、前高/前低或紧密整理。
- 出现强 breakout bar，且市场背景支持朝该方向脱离。
- 后续至少出现一根可辨认的 follow-through bar。

## 5. 入场触发

- 做多：向上突破后，第一根或第二根继续创新高、收盘强势的 follow-through bar 触发。
- 做空：向下突破后，第一根或第二根继续创新低、收盘强势的 follow-through bar 触发。
- 如果 breakout bar 很强但下一根是明显 doji 或反向 bar，则不入场。

## 6. 止损规则

- 默认放在 breakout signal bar 另一侧。
- 若突破的是明确交易区间，可把止损放回区间内部或区间边界外侧。
- 若 breakout bar 过大导致止损不合理，跳过本次交易。

## 7. 止盈 / 出场规则

- 基础版本：
  - `v0.1`：固定 `1R`
  - `v0.2`：固定 `1.5R`
  - `v0.3`：固定 `2R`
- 扩展版本：
  - `v0.4`：前高/前低或 measured move
  - `v0.5`：follow-through 走弱时移动止盈

## 8. 失效条件

- 突破后 1 至 2 根 bar 内没有延续。
- 价格快速重新回到原区间内。
- 突破 bar 被下一根强反向 bar 吞没。

## 9. 禁止交易条件

- 盘前盘后。
- 财报、重大新闻和事件窗口。
- breakout bar 太大导致风险回报不合适。
- 突破前方近距离还有更大级别阻力/支撑。

## 10. 可量化规则草案

- breakout bar 实体大于最近 `N` 根平均实体，且收盘位于本 bar 上/下 `20%` 区域。
- breakout 后 `M` 根 bar 内，至少一根同向 bar 创出新高/新低且收盘继续靠近极值。
- 若 breakout 后 `M` 根内重新收回区间，则视为失效。
- 入场前要求理论 `RR >= 1:1.5`。

## 11. 参数范围

- breakout 强度阈值：最近平均实体的 `1.2 / 1.5 / 2.0 倍`
- follow-through 观察窗口：`1 / 2 / 3 bars`
- 目标位：`1R / 1.5R / 2R / measured move`
- 允许的回踩深度：`0 / 25% / 38%`

## 12. 回测假设

- 在 `SPY / QQQ / NVDA / TSLA 5m` 上，follow-through 过滤是否明显优于只看 breakout bar。
- 同样的规则在 ETF 和高波动个股上，滑点差异是否会吃掉优势。
- 突破日与震荡日拆开后，哪类环境的延续更稳定。

## 13. 测试计划

- 测试目标：
  - 验证“突破 + follow-through”是否比“裸 breakout”更有正期望。
- 测试标的：
  - `SPY / QQQ / NVDA / TSLA`
- 时间周期：
  - `5m` 主测
  - `15m` 复核
  - `1m` 只做探索，不纳入验收
- 时间范围：
  - 优先使用现有 public history 与 intraday pilot 可覆盖窗口；后续补更长 regular-session 样本
- 数据需求：
  - OHLCV
  - 财报 / 重大新闻排除标签
  - regular session 标记
- 交易成本假设：
  - ETF：`1bp + 1 tick/side`
  - 高波动个股：`2bp + 2 ticks/side`
- 滑点假设：
  - breakout 入场按最不利 1 到 2 tick 测试敏感性
- 样本切分：
  - 时间顺序 `50 / 25 / 25`（样本内 / 验证 / 样本外）
- 最低交易次数要求：
  - 总交易数至少 `100`
  - 任一 split 少于 `20` 笔记为 `insufficient_sample`
- 评价指标：
  - 交易次数、胜率、平均 R、期望值、Profit Factor、最大回撤、最大连续亏损
  - 按市场环境 / 时间段 / 标的拆分表现
  - 扣除成本和滑点后的表现
  - `no-trade / skip` 原因统计
- 通过标准：
  - 成本后整体 `expectancy > 0`
  - 整体 `PF >= 1.15`
  - 验证集与样本外 `PF >= 1.00`
  - 最大回撤不超过 `12R`
- 淘汰标准：
  - 样本外明显转负
  - 结果只靠单一标的支撑
  - 成本后优势消失

## 14. 预期失败模式

- 在震荡区间中追单根强 breakout bar。
- follow-through 实际很弱，却被误判成趋势延续。
- 前方空间不足，止盈太近或止损太远。

## 15. 当前结论

- `candidate`
- 规则已经足够清楚，可直接进入详细回测计划。
