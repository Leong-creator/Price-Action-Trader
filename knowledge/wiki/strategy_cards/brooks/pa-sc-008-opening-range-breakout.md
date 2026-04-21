---
title: 开盘区间突破或失败突破
type: setup
status: draft
confidence: low
market: ["US"]
timeframes: ["1m", "5m", "15m"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-37-52-units.md", "wiki:knowledge/wiki/sources/fangfangtu-wedge-note.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md"]
tags: ["strategy-card", "opening-range", "trend-from-the-open", "failed-breakout", "m9"]
applicability: ["用于研究开盘区间突破与失败突破的首批草案", "当前主要用于标准化开盘 regular-session 场景"]
not_applicable: ["不构成自动 trigger", "不代表已验证稳定盈利", "未补齐开盘例图前不进入程序化回测"]
contradictions: ["方方土 notes 给出开盘早段强趋势常有小反转/大反转的经验数字，但当前不能直接固化为统一概率规则"]
missing_visuals: ["需要补 Trend From The Open、opening reversal、opening range failed breakout 的标准例图"]
open_questions: ["opening range 应定义为前 5 分钟、15 分钟还是前几根 bar 仍待统一", "开盘失败突破与普通开盘噪音的界限仍需更多样本"]
pa_context: ["opening-range", "breakout", "failed-breakout", "trend-from-the-open"]
market_cycle: ["breakout", "trading-range", "transition"]
higher_timeframe_context: ["开盘区间方向若与更高周期强阻力/支撑冲突，突破成功率可能明显下降"]
bar_by_bar_notes: ["开盘 bar 噪音高，不应仅凭第一根大 bar 就认定为 trend from the open"]
signal_bar: ["开盘区间边界附近的强 breakout bar 或失败突破后的强反向 bar"]
entry_trigger: ["突破开盘区间并出现 follow-through，或失败突破重新回到区间内后沿反向入场"]
entry_bar: ["开盘前几根 bar 中的 breakout / failure confirmation bar"]
stop_rule: ["默认放在开盘区间另一侧、signal bar 另一侧或开盘极值外侧"]
target_rule: ["先测试 1R / 1.5R / 2R，再比较是否能走出 trend-from-the-open 或回到区间另一侧"]
trade_management: ["开盘阶段若突破后快速停滞，应更快止盈或退出，避免把噪音当趋势"]
measured_move: true
invalidation: ["突破后无 follow-through、迅速回到区间内、或开盘前几根 bar 出现高度重叠"]
risk_reward_min: 1.5
last_reviewed: 2026-04-20
strategy_id: PA-SC-008
source_family: fangfangtu_transcript
setup_family: opening_range_breakout_failure
market_context: ["开盘区间", "突破", "失败突破"]
evidence_quality: low
chart_dependency: high
needs_visual_review: true
test_priority: medium
last_updated: 2026-04-20
---

# 开盘区间突破或失败突破

## 1. 来源依据

- 方方土 transcript 把 gap、开盘第一段走势和随后是否衰竭/反转作为关键观察点。
- Brooks 的 opening reversal / Trend From The Open 相关页给出了开盘突破、失败突破和开盘早段趋势是否延续的案例。
- 方方土《楔形》笔记补充了“刚开盘第一个趋势也可能快速反转”的经验判断，但具体数字和条件仍需图表确认。
- 当前来源更适合形成“开盘先观察，再决定是顺势突破还是失败突破反向”的草案，不足以直接冻结成统一规则。

## 2. 核心交易思想

开盘前几根 bar 会快速暴露当天是要走趋势、走失败突破，还是直接进入双向拉扯。真正可做的不是“无脑追开盘第一根”，而是先看开盘区间边界怎么被突破，以及突破后有没有 follow-through；没有跟随时，失败突破往往反而更有交易价值。

## 3. 适用市场环境

- 适合：regular session 开盘、开盘区间边界清晰、第一段突破后有明显跟随或明显失败。
- 不适合：开盘过度乱跳、几根 bar 高度重叠、重大新闻刚释放、盘前盘后。

## 4. 入场前提

- 已定义开盘区间。
- 开盘后出现向上或向下的首次明显突破，或出现突破后迅速收回区间的失败行为。
- 市场至少给出一段可以辨认的方向性，而不是完全无序波动。

## 5. 入场触发

- 顺势版本：突破开盘区间边界后，下一根或随后一两根 bar 继续同方向 follow-through。
- 失败版本：价格突破区间边界后快速回到区间内，并由强反向 signal bar 触发。
- 若第一根大 bar 之后马上变成多根重叠 doji，则不做。

## 6. 止损规则

- 顺势突破：默认放在 breakout signal bar 另一侧，或开盘区间对侧。
- 失败突破：默认放在失败突破极值外侧。
- 若开盘波动过大导致 stop 过宽，本次交易跳过。

## 7. 止盈 / 出场规则

- `v0.1`：固定 `1R`
- `v0.2`：固定 `1.5R`
- `v0.3`：顺势突破看 trend from the open，失败突破看回到区间中轴或另一侧
- `v0.4`：时间止损，开盘后一段时间未展开即退出

## 8. 失效条件

- 突破后 1 至 2 根 bar 内没有 follow-through。
- 失败突破信号出现后，价格仍持续贴着突破方向推进。
- 开盘区间定义被不断重画，说明噪音过高。

## 9. 禁止交易条件

- 盘前盘后。
- 财报与重大新闻刚发布的剧烈波动时段。
- 开盘第一段波动异常大，止损无法接受。
- 无法统一定义 opening range 或看不清开盘边界时。

## 10. 可量化规则草案

- opening range 候选：前 `5 / 10 / 15` 分钟，或前 `3 / 5` 根 bar。
- 顺势突破需满足：突破后 `1 / 2` 根 bar 继续脱离区间，且收盘维持在区间外。
- 失败突破需满足：突破区间后在 `M` 根 bar 内重新收回区间内，并出现强反向 bar。
- 若开盘区间过宽、理论 `RR < 1:1.5`，则跳过。

## 11. 参数范围

- opening range 定义：`前 3 / 5 根 bar`、`前 5 / 10 / 15 分钟`
- follow-through 观察窗口：`1 / 2 / 3 bars`
- 出场：`1R / 1.5R / 2R / 区间另一侧`
- 禁做时间：开盘后 `5 / 10 / 15` 分钟内直接跳过或仅观察

## 12. 回测假设

- 顺势开盘突破和失败突破，哪一种在 `SPY / QQQ / NVDA / TSLA` 更稳定。
- `1m` 与 `5m` 的噪音差异是否会让信号质量显著变化。
- regular session 前 15 分钟是否噪音过高，必须等待更清晰结构。

## 13. 测试计划

- 测试标的：`SPY / QQQ / NVDA / TSLA`
- 时间周期：`1m` 与 `5m` 探索，`15m` 只作背景确认
- 时间范围：仅 regular session 开盘前 `60` 分钟相关样本
- 数据需求：OHLCV、regular session 精确开盘时间、新闻/财报排除标签、最好附图表回放
- 交易成本假设：ETF `1bp + 1 tick/side`，高波动个股 `2bp + 2 ticks/side`
- 滑点假设：开盘订单额外加 `2~3 ticks`
- 最低交易次数要求：每种定义至少 `80` 笔，否则记 `insufficient_sample`
- 评价指标：交易次数、胜率、平均 R、期望值、开盘前 15 分钟 vs 后 15 分钟表现、skip 原因统计
- 通过标准：先完成开盘区间定义与标准样本复核，再进入程序化评估
- 淘汰标准：无法把开盘噪音与真实突破分开，或成本后优势消失

## 14. 预期失败模式

- 追开盘第一根大 bar，被快速反向吞没。
- 把普通开盘噪音误判成失败突破。
- 开盘波动太大，止损和滑点直接吃掉优势。

## 15. 当前结论

- `draft`
- 逻辑方向清楚，但当前仍需要人工补图确认与统一 opening range 定义，不能直接进入回测。
