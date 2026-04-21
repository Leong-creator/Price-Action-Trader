---
title: 强趋势日 vs 震荡日过滤
type: rule
status: candidate
confidence: medium
market: ["US"]
timeframes: ["5m", "15m"]
direction: neutral
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md", "wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md", "wiki:knowledge/wiki/rules/trend-vs-range-filter-minimal.md"]
tags: ["strategy-card", "filter", "trend-day", "range-day", "m9"]
applicability: ["用于判断当天更像强趋势日还是震荡日", "用于作为 setup 的放行/禁做过滤器"]
not_applicable: ["不构成独立入场 trigger", "不代表已验证稳定盈利"]
contradictions: []
missing_visuals: []
open_questions: ["趋势日判定是用开盘前 30 分钟、前 60 分钟还是全日动态更新仍待测试", "过滤器应服务于 breakout setup 还是所有 setup 仍需分开验证"]
pa_context: ["trend-day", "range-day", "filter"]
market_cycle: ["breakout", "tight-channel", "trading-range"]
higher_timeframe_context: ["更高周期若已经在区间边缘，日内趋势日判定也可能被更大级别吸回"]
bar_by_bar_notes: ["过滤器的意义是先判断环境，再决定是否允许追突破或优先等区间反转"]
signal_bar: ["不适用，作为环境过滤卡只关心日内结构强弱"]
entry_trigger: ["当趋势日条件成立时，放行顺势突破/恢复类策略；当震荡日条件成立时，优先禁追突破或降级为 wait"]
entry_bar: ["不适用，依赖下游 setup 自身的入场 bar"]
stop_rule: ["不适用，作为过滤卡不单独定义 stop"]
target_rule: ["不适用，过滤卡只评估是否提升下游策略表现"]
trade_management: ["若日内结构从趋势退化为区间，过滤状态应允许动态切换"]
measured_move: false
invalidation: ["连续突破缺乏 follow-through、bar 大量重叠、gap 迅速回补，说明趋势日判断失效"]
risk_reward_min:
last_reviewed: 2026-04-20
strategy_id: PA-SC-009
source_family: fangfangtu_transcript
setup_family: regime_filter_trend_vs_range
market_context: ["强趋势日", "震荡日", "环境过滤"]
evidence_quality: medium
chart_dependency: medium
needs_visual_review: false
test_priority: high
last_updated: 2026-04-20
---

# 强趋势日 vs 震荡日过滤

## 1. 来源依据

- 方方土 transcript 和《市场周期》笔记都强调“先看背景环境，再看信号 K”，并把 tight channel / breakout 与 trading range 明确区分。
- Brooks 的 trend day / trend from the open 相关页面，以及 `trend-vs-range-filter-minimal` 规则页，都把 follow-through、gap 是否保留、bar 是否重叠，作为区分趋势日与区间日的重要线索。
- 当前证据足以支持“作为过滤器先试用”，但不足以把它包装成独立获利策略。

## 2. 核心交易思想

同样一套 entry，在趋势日和震荡日里的表现可能完全相反。突破延续类 setup 更怕在区间日里被频繁反向，区间边缘反转类 setup 又更怕在趋势日里逆势硬顶。因此先做日内环境过滤，有机会减少错误场景下的交易。

## 3. 适用市场环境

- 适合：需要先判断当天是 trend day 还是 range day 的所有日内 setup。
- 不适合：独立当作交易信号使用；没有下游策略时，本卡不能单独产生交易。

## 4. 入场前提

- 下游 setup 在触发前，先需要环境分类。
- 日内已有足够 bar 用于判断 gap、follow-through、bar 重叠、微型通道或交易区间特征。
- 过滤状态应当允许随市场变化而更新。

## 5. 入场触发

- 放行趋势类 setup：连续同向 bar、收盘靠近极值、gap 或 breakout 能保留、重叠较少。
- 放行区间反转/失败突破类 setup：反向突破频繁失败、gap 快速回补、bar 重叠明显、上下沿反应增强。
- 若两边都不明显，则优先 `wait`。

## 6. 止损规则

- 作为过滤卡不单独定义止损。
- 下游 setup 的 stop 仍由各自策略卡负责。

## 7. 止盈 / 出场规则

- 作为过滤卡不单独定义止盈。
- 评价标准是“是否改善下游策略的风险收益比”，而不是自身盈亏。

## 8. 失效条件

- 趋势日判断后，后续 bar 大量重叠且突破迅速回补。
- 区间日判断后，市场却出现连续强 breakout 和 follow-through。
- 过滤状态长时间滞后，无法跟上日内结构切换。

## 9. 禁止交易条件

- 开盘数据不足以判断环境时，不应强行分类。
- 财报、重大新闻时段导致结构失真时，应优先禁做。
- 午盘极低流动性但缺乏明确信号时，不强行放行任何 setup。

## 10. 可量化规则草案

- 趋势日候选特征：连续同向趋势 bar、收盘更靠近极值、gap 保持、pullback 浅、bar 重叠少。
- 区间日候选特征：突破经常失败、gap 快速回补、bar 重叠增加、上下沿反应明显。
- 若趋势特征分数与区间特征分数都不强，则保持 `unknown / wait`。
- 过滤器应输出：`trend_day`、`range_day`、`unclear` 三类。

## 11. 参数范围

- 判定窗口：`前 30 / 60 / 90 分钟`
- 趋势 bar 连续数量：`3 / 4 / 5`
- 允许 gap 回补幅度：`0% / 25% / 50%`
- `unclear` 阈值：趋势分与区间分差值 `5% / 10% / 15%`

## 12. 回测假设

- 把本过滤器加到 `PA-SC-002 / 005 / 006` 上，是否能减少假突破交易。
- 把本过滤器加到 `PA-SC-004` 上，是否能显著提高区间边缘反转表现。
- `unclear` 状态下强行做交易，是否显著拉低整体期望值。

## 13. 测试计划

- 测试标的：`SPY / QQQ / NVDA / TSLA`
- 时间周期：`5m` 主测，`15m` 复核
- 时间范围：优先覆盖现有 daily/intraday 样本，再扩展到更长 regular-session 窗口
- 数据需求：OHLCV、regular session 标记、下游策略执行日志、skip 原因统计
- 交易成本假设：沿用下游策略成本与滑点
- 最低交易次数要求：过滤前后各自至少 `100` 笔
- 评价指标：交易次数、胜率、平均 R、期望值、PF、最大回撤、按 regime/时间段/标的拆分表现、skip 比例
- 通过标准：至少一个下游策略在验证集和样本外成本后表现改善且回撤不恶化
- 淘汰标准：过滤后只剩极少样本，或结果没有稳定改善

## 14. 预期失败模式

- 趋势日与区间日在早盘频繁切换，导致过滤器过慢。
- 过滤器太严格，虽然减少亏损，也把大部分好交易一起过滤掉。
- 不同标的的 regime 特征差异大，单一阈值失效。

## 15. 当前结论

- `candidate`
- 作为环境过滤卡已经足够清楚，可以优先用于下游 setup 的增益测试。
