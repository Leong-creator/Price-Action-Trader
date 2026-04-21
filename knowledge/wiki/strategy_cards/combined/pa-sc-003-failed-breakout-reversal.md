---
title: 失败突破后回到区间的反转
type: setup
status: candidate
confidence: medium
market: ["US"]
timeframes: ["5m", "15m"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md", "wiki:knowledge/wiki/sources/fangfangtu-breakout-note.md", "wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md"]
tags: ["strategy-card", "failed-breakout", "reversal", "trap", "m9"]
applicability: ["用于研究失败突破回归区间后的反转机会", "用于首批详细测试计划"]
not_applicable: ["不构成自动 trigger", "不代表已验证稳定盈利"]
contradictions: []
missing_visuals: []
open_questions: ["如何稳定区分失败突破后的 pullback 与真正 reversal，仍需参数化测试"]
pa_context: ["failed-breakout", "trading-range", "reversal"]
market_cycle: ["trading-range", "broad-channel", "transition"]
higher_timeframe_context: ["若更大级别本就在强趋势延续阶段，应降低失败突破反转预期"]
bar_by_bar_notes: ["失败突破不能只看回到区间本身，还要看回归后是否有反向 signal bar 与延续"]
signal_bar: ["回到区间后的强反向 signal bar，最好伴随明显失败跟随"]
entry_trigger: ["回归区间并出现反向 signal bar 后，沿反向触发入场"]
entry_bar: ["回到区间后的第一根或第二根有效反向确认 bar"]
stop_rule: ["放在失败突破极值之外或 signal bar 另一侧"]
target_rule: ["优先看区间中轴与区间另一侧，再测试 1R / 1.5R / 2R"]
trade_management: ["若回到区间后形成新的窄通道顺势恢复，应尽快退出反转单"]
measured_move: false
invalidation: ["回到区间后没有反向延续、再次顺着原突破方向脱离区间、或突破极值再次刷新"]
risk_reward_min: 1.5
last_reviewed: 2026-04-20
strategy_id: PA-SC-003
source_family: fangfangtu_transcript
setup_family: failed_breakout_reversal
market_context: ["失败突破", "回归区间反转"]
evidence_quality: medium
chart_dependency: medium
needs_visual_review: false
test_priority: high
last_updated: 2026-04-20
---

# 失败突破后回到区间的反转

## 1. 来源依据

- 方方土 transcript 多次强调：交易区间内大多数突破会失败，极端两段式拉升/杀跌常是 trap。
- Brooks 明确把 failed breakout 作为 signal bar 和 reversal 评估的重要背景。
- 方方土《突破》笔记写到：TR 中 80% 的突破会失败，2nd leg 看起来很强也常是陷阱。
- 现有 promoted rule 页已经把 failed breakout 保留为 explanation-only 的核心主题。

## 2. 核心交易思想

在交易区间或宽通道里，很多看起来很强的突破，其实只是扫止损和制造错觉。只要后面没有继续跟随，价格重新回到区间，原本追突破的一方就会被套，反方向的交易往往更有赔率。

## 3. 适用市场环境

- 适合：交易区间边缘、宽通道边缘、2nd leg trap、假突破后迅速回归区间。
- 不适合：真实强趋势日、突破后 follow-through 很强、市场还处于 Always In 状态。

## 4. 入场前提

- 市场原本更像交易区间或宽通道，而不是纯趋势。
- 已出现向上或向下突破尝试。
- 突破后没有足够 follow-through，且价格重新回到区间内部。

## 5. 入场触发

- 向上失败突破：回到区间后，跌破反向 signal bar 低点做空。
- 向下失败突破：回到区间后，突破反向 signal bar 高点做多。
- 若回到区间后只是来回抖动、没有强反向信号，则等待。

## 6. 止损规则

- 默认放在失败突破的极值之外。
- 或放在反向 signal bar 另一侧。
- 若失败突破极值离入场过远，则跳过。

## 7. 止盈 / 出场规则

- `v0.1`：先看区间中轴
- `v0.2`：再看区间另一侧
- `v0.3`：固定 `1.5R / 2R`
- 若反向走势很弱，优先在中轴减仓而不是死等另一侧

## 8. 失效条件

- 回到区间后没有出现反向延续。
- 价格重新顺着原突破方向脱离区间。
- 反向 signal bar 很快被吞没。

## 9. 禁止交易条件

- 强趋势日、Trend from the Open、紧密通道。
- 财报 / 重大新闻窗口。
- 区间边界本身不清楚。
- 交易区间中间位置。

## 10. 可量化规则草案

- 先定义交易区间：最近 `N` 根 bar 中至少有 `K` 次来回重叠，且高低点未有效脱离。
- breakout 后 `M` 根 bar 内未形成有效 follow-through，并重新收回区间边界内。
- 反向 signal bar 需要大实体、收盘靠近极值、且理论 `RR >= 1:1.5`。

## 11. 参数范围

- 区间识别窗口：`10 / 20 / 30 bars`
- follow-through 缺失判定：`1 / 2 / 3 bars`
- 出场版本：`中轴 / 另一侧 / 1.5R / 2R`
- 对 breakout 极值的缓冲：`0 / 1 / 2 ticks`

## 12. 回测假设

- 在 `SPY / QQQ / NVDA 5m` 上，失败突破反转是否优于直接顺势追突破。
- 区间边缘做反转与区间中部反转，差异是否足够大。
- 2nd leg trap 是否能显著提高反转质量。

## 13. 测试计划

- 测试目标：
  - 验证“失败突破 + 回归区间 + 反向 signal bar”是否有稳定正期望。
- 测试标的：
  - `SPY / QQQ / NVDA`
- 时间周期：
  - `5m` 主测
  - `15m` 复核
- 时间范围：
  - 优先 regular session 样本；后续补更长 intraday 样本
- 数据需求：
  - OHLCV
  - regular session 标记
  - 财报 / 重大新闻排除标签
- 交易成本假设：
  - ETF：`1bp + 1 tick/side`
  - 高波动个股：`2bp + 2 ticks/side`
- 滑点假设：
  - 失败突破反转按最不利 `1~2 ticks` 测试
- 样本切分：
  - 时间顺序 `50 / 25 / 25`
- 最低交易次数要求：
  - 总交易数至少 `100`
  - 任一 split 少于 `20` 笔标为 `insufficient_sample`
- 评价指标：
  - 交易次数、胜率、平均 R、期望值、PF、最大回撤、最大连续亏损
  - 按环境 / 时间段 / 标的拆分
  - `skip` 原因统计
- 通过标准：
  - 成本后 `expectancy > 0`
  - 整体 `PF >= 1.15`
  - 验证与样本外不显著转负
- 淘汰标准：
  - 只有样本内有效
  - 回测收益主要来自极少数大单
  - 成本后 PF 跌破 `1.0`

## 14. 预期失败模式

- 把真实趋势突破误判成失败突破。
- 在区间中部做反转，而不是边缘。
- 回归区间后没有反向信号就过早进场。

## 15. 当前结论

- `candidate`
- 规则边界已较清楚，适合进入详细回测计划。
