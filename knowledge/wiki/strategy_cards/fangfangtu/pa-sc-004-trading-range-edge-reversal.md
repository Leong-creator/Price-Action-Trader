---
title: 交易区间上沿 / 下沿反转
type: setup
status: candidate
confidence: medium
market: ["US"]
timeframes: ["5m", "15m"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md", "wiki:knowledge/wiki/sources/fangfangtu-breakout-note.md", "wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md"]
tags: ["strategy-card", "trading-range", "range-edge", "reversal", "m9"]
applicability: ["用于研究交易区间边缘的反转机会"]
not_applicable: ["不构成自动 trigger", "不适用于强趋势的中继突破"]
contradictions: []
missing_visuals: []
open_questions: ["区间边缘的最小有效距离应按 ATR、ticks 还是 recent range 百分比定义，仍待测试"]
pa_context: ["trading-range", "reversal", "failed-breakout"]
market_cycle: ["trading-range", "broad-channel"]
higher_timeframe_context: ["更高周期若正处在强趋势突破阶段，应降低区间边缘反转优先级"]
bar_by_bar_notes: ["区间中间不做，优先等价格接近上沿或下沿，再观察反向 signal bar"]
signal_bar: ["区间边缘出现的反向 signal bar，最好伴随长尾或失败突破背景"]
entry_trigger: ["上沿反转跌破 signal bar 低点做空，下沿反转突破 signal bar 高点做多"]
entry_bar: ["区间边缘的第一根有效反向 signal bar 或其确认 bar"]
stop_rule: ["放在区间边缘外侧或 signal bar 另一侧"]
target_rule: ["先看区间中轴，再看区间另一侧"]
trade_management: ["到达中轴可部分止盈，剩余仓位观察是否能走到另一侧"]
measured_move: false
invalidation: ["价格未能离开区间边缘、信号 bar 被快速吞没、或形成顺势真突破"]
risk_reward_min: 1.5
last_reviewed: 2026-04-20
strategy_id: PA-SC-004
source_family: fangfangtu_transcript
setup_family: trading_range_edge_reversal
market_context: ["交易区间边缘", "区间反转"]
evidence_quality: medium
chart_dependency: medium
needs_visual_review: false
test_priority: medium
last_updated: 2026-04-20
---

# 交易区间上沿 / 下沿反转

## 1. 来源依据

- 方方土 transcript 与《突破》笔记都强调：交易区间是限价单市场，多数突破会失败。
- Brooks 对交易区间、TTR 和 failed breakout 的说明补充了“区间上沿/下沿更有意义，区间中间价值很低”的背景。
- transcript 的错误案例还指出，在区间高位追强突破很容易被套。

## 2. 核心交易思想

交易区间里最差的地方是中间，最值得关注的是边缘。上沿附近更容易出现卖压，下沿附近更容易出现买盘；只要边缘突破没有真正延续，反方向往往更有赔率。

## 3. 适用市场环境

- 适合：明确交易区间、宽通道、边缘附近的失败突破。
- 不适合：Trend from the Open、紧密通道、强突破刚形成时。

## 4. 入场前提

- 最近一段价格明显在区间内往返。
- 当前价格接近区间上沿或下沿，而不是中间。
- 有失败突破或弱延续迹象。

## 5. 入场触发

- 上沿反转：跌破反向 signal bar 低点做空。
- 下沿反转：突破反向 signal bar 高点做多。
- 若只有一根 doji、没有明确反向信号，则继续等待。

## 6. 止损规则

- 放在区间边缘外侧，或 signal bar 另一侧。
- 若区间过宽导致止损过远，本次交易跳过。

## 7. 止盈 / 出场规则

- 第一目标：区间中轴。
- 第二目标：区间另一侧。
- 若还未到中轴就失去动能，可提前退出。

## 8. 失效条件

- 入场后价格重新贴着边缘继续突破。
- 区间判定本身失效，转成趋势突破。
- signal bar 很快被吞没。

## 9. 禁止交易条件

- 区间中间位置。
- 重大新闻和财报窗口。
- 刚刚出现很强趋势 bar 且 follow-through 尚未结束。

## 10. 可量化规则草案

- 最近 `N` 根 bar 至少存在 `K` 次重叠与往返，定义为 trading range。
- 当前价格距离区间边缘不超过最近区间高度的 `10% / 20% / 30%`。
- 触发前必须出现失败突破或反向 signal bar。

## 11. 参数范围

- 区间识别窗口：`10 / 20 / 30 bars`
- 边缘接近度：`10% / 20% / 30%`
- 出场版本：`中轴 / 另一侧 / 1.5R`

## 12. 回测假设

- 区间边缘反转是否明显优于区间中间随意反转。
- 上沿做空与下沿做多是否对称。
- ETF 与高波动个股的区间边缘表现是否不同。

## 13. 测试计划

- 标的：`SPY / QQQ / NVDA`
- 周期：`5m` 主测，`15m` 复核
- 时间范围：regular session 优先
- 成本/滑点：ETF `1bp + 1 tick`，高波动个股 `2bp + 2 ticks`
- 最低样本要求：总交易数至少 `80`
- 关键指标：期望值、PF、中轴止盈 vs 另一侧止盈的差异
- 通过标准：成本后期望值为正，样本外不明显失真
- 淘汰标准：只在极少数区间环境有效或成本后失去优势

## 14. 预期失败模式

- 在强趋势日逆势做区间反转。
- 把区间中部误当边缘。
- 看到长尾就抢反转，没有等 signal bar 确认。

## 15. 当前结论

- `candidate`
- 规则已经可测试，但需要依赖 `PA-SC-009` 做环境过滤。
