---
title: 紧密通道中的顺势恢复
type: setup
status: candidate
confidence: medium
market: ["US"]
timeframes: ["5m", "15m"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md", "wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md", "wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md"]
tags: ["strategy-card", "tight-channel", "trend-resumption", "always-in", "m9"]
applicability: ["用于研究 tight channel 内的顺势恢复机会", "用于后续 continuation setup 候选策略准备"]
not_applicable: ["不构成自动 trigger", "不代表已验证稳定盈利"]
contradictions: []
missing_visuals: []
open_questions: ["tight channel 与 broad channel 的量化分界仍需回测和人工图表复核", "回调不超过 2 至 3 根 bar 的阈值是否需要按品种调整仍待验证"]
pa_context: ["tight-channel", "trend", "trend-resumption", "always-in"]
market_cycle: ["tight-channel", "breakout"]
higher_timeframe_context: ["更高周期若正处于明显反向阻力/支撑位，tight channel 内的继续上涨/下跌成功率会下降"]
bar_by_bar_notes: ["tight channel 内反转大多失败，优先等小回调后顺势恢复，而不是提前逆势猜顶猜底"]
signal_bar: ["顺势方向的小回调结束 bar，收盘靠近极值、上下影线不过分夸张"]
entry_trigger: ["做多在恢复 bar 高点上方触发，做空在恢复 bar 低点下方触发"]
entry_bar: ["短回调后的第一根或第二根顺势恢复 bar"]
stop_rule: ["默认放在 signal bar 另一侧，或最近一次小回调 swing 外侧"]
target_rule: ["先测试 1R / 1.5R / 2R，再比较前高/前低续推与移动止盈"]
trade_management: ["若恢复后迅速出现连续 opposite bar，应先减仓或退出，不把 tight channel 错当成永续单边"]
measured_move: false
invalidation: ["通道开始明显变宽、出现连续强反向 bar、或恢复后无 follow-through"]
risk_reward_min: 1.5
last_reviewed: 2026-04-20
strategy_id: PA-SC-006
source_family: fangfangtu_transcript
setup_family: tight_channel_resumption
market_context: ["紧密通道", "顺势恢复", "Always In"]
evidence_quality: medium
chart_dependency: medium
needs_visual_review: false
test_priority: medium
last_updated: 2026-04-20
---

# 紧密通道中的顺势恢复

## 1. 来源依据

- 方方土 transcript 把 tight channel 视作市场周期中的强趋势阶段，核心含义是“单边还没结束，反转大多先失败”。
- Brooks 在 tight channel / Always In 相关页强调：通道内更优先寻找顺势恢复，而不是把每次小反弹都当成反转。
- `tight-channel-trend-resumption-minimal` 规则页已经把 tight channel 仅作为解释层 promoted theme，明确要求弱恢复或通道变宽时降级为 wait / review。
- 方方土《市场周期》笔记补充了紧密通道的中文定义：回调幅度小、bar 数少、通常只能顺势做。

## 2. 核心交易思想

当市场处在紧密通道里，回调往往又浅又短，逆势方很难把价格真正拉回区间。这个时候更高胜率的做法不是抢反转，而是等回调露出衰竭迹象后，顺着原方向重新进场。

## 3. 适用市场环境

- 适合：tight channel、Always In Long / Short、突破后的持续推进、微型通道或小回调趋势。
- 不适合：通道已经明显变宽、进入交易区间、出现连续强反向趋势 bar、或临近大级别关键阻力/支撑。

## 4. 入场前提

- 价格已经处于可辨认的 tight channel 中。
- 回调持续时间短，通常不超过少量 bar，且没有破坏最近趋势 swing。
- 仍能判断市场处于 Always In 同方向，而不是已经切回双向博弈。

## 5. 入场触发

- 做多：上涨 tight channel 中，小回调后 signal bar 高点被突破。
- 做空：下跌 tight channel 中，小回调后 signal bar 低点被跌破。
- 如果回调结束后第一根恢复 bar 很弱，可等第二根确认 bar 再入场。

## 6. 止损规则

- 默认放在 signal bar 另一侧。
- 若最近小回调 swing 清晰，可放在 swing 低点/高点外侧。
- 若 stop 超出可接受风险，跳过本次交易。

## 7. 止盈 / 出场规则

- `v0.1`：固定 `1R`
- `v0.2`：固定 `1.5R`
- `v0.3`：固定 `2R`
- `v0.4`：以前高/前低或通道继续推进作为动态目标
- `v0.5`：出现连续 opposite bar 或通道变宽时退出

## 8. 失效条件

- 回调后恢复 bar 没有 follow-through。
- 通道从 tight channel 退化为 broad channel。
- 对侧出现连续强趋势 bar，破坏 Always In 判断。

## 9. 禁止交易条件

- 盘前盘后。
- 财报、重大新闻窗口。
- 已接近大级别阻力/支撑且理论空间不足。
- 通道定义不清，或 signal bar 太大导致止损过宽。

## 10. 可量化规则草案

- 紧密通道定义候选：最近 `N` 根 bar 同方向推进，逆向回调不超过 `2 / 3 / 4` 根 bar，且多数收盘保持在均线一侧。
- 最近 `M` 根 bar 内顺势实体占优，收盘更靠近趋势方向极值。
- 回调不能深度穿透最近 swing，也不能连续出现多个强反向收盘 bar。
- 触发后 `1~2` 根 bar 必须继续同方向推进，否则视为弱恢复。

## 11. 参数范围

- 通道识别窗口：`8 / 12 / 20 bars`
- 最大回调 bar 数：`2 / 3 / 4`
- 最大回调深度：最近 swing 的 `20% / 25% / 33%`
- 目标位：`1R / 1.5R / 2R / 前高前低`

## 12. 回测假设

- tight channel 内的小回调顺势恢复，是否明显优于普通 trend pullback。
- `SPY / QQQ` 与 `NVDA / TSLA` 在同样规则下，滑点和假突破差异多大。
- 通道一旦变宽后继续按 tight channel 处理，是否会显著拉低期望值。

## 13. 测试计划

- 测试标的：`SPY / QQQ / NVDA / TSLA`
- 时间周期：`5m` 主测，`15m` 复核
- 时间范围：优先覆盖现有 intraday pilot 与后续 regular-session 扩展窗口
- 数据需求：OHLCV、regular session 标记、新闻/财报排除标签
- 交易成本假设：ETF `1bp + 1 tick/side`，高波动个股 `2bp + 2 ticks/side`
- 滑点假设：恢复 bar 触发额外加 `1~2 ticks`
- 最低交易次数要求：总交易数至少 `80`
- 评价指标：交易次数、胜率、平均 R、期望值、Profit Factor、最大回撤、按通道宽窄拆分表现
- 通过标准：成本后 `expectancy > 0` 且 `PF >= 1.10`
- 淘汰标准：通道定义一改就失效，或样本外明显转负

## 14. 预期失败模式

- 把 broad channel 误判成 tight channel。
- 回调虽短，但实际已经在大级别阻力/支撑前衰竭。
- 顺势恢复 bar 过弱，仍被当成继续推进。

## 15. 当前结论

- `candidate`
- 规则已经足够形成可测草案，但 tight channel 的量化阈值仍需系统回测。
