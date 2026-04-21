---
title: 趋势中回调后的顺势恢复
type: setup
status: candidate
confidence: medium
market: ["US"]
timeframes: ["5m", "15m"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md", "wiki:knowledge/wiki/sources/fangfangtu-pullback-counting-bars-note.md", "wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md"]
tags: ["strategy-card", "trend", "pullback", "resumption", "m9"]
applicability: ["用于研究趋势内回调后的顺势恢复机会", "用于后续回测候选策略准备"]
not_applicable: ["不构成自动 trigger", "不代表已验证稳定盈利"]
contradictions: []
missing_visuals: []
open_questions: ["回调深度阈值应以 swing 百分比、EMA 偏离还是 bar 数量定义，仍待测试"]
pa_context: ["trend", "pullback", "trend-resumption"]
market_cycle: ["breakout", "tight-channel", "broad-channel"]
higher_timeframe_context: ["更高周期需与当前方向一致，至少不能与当前 setup 明显冲突"]
bar_by_bar_notes: ["回调后必须出现重新转强的 signal bar 与 follow-through，不能仅凭单根反向尾巴入场"]
signal_bar: ["顺势方向的趋势 bar 或 reversal bar，收盘靠近极值且背景支持顺势恢复"]
entry_trigger: ["做多在 signal bar 高点上方触发，做空在 signal bar 低点下方触发"]
entry_bar: ["signal bar 后一根确认 bar 或次级周期更低风险触发 bar"]
stop_rule: ["默认放在 signal bar 另一侧，或最近回调 swing 外侧"]
target_rule: ["先测试 1R / 1.5R / 2R，再比较是否保留部分仓位跟随趋势恢复"]
trade_management: ["若 1 至 2 根 bar 内无 follow-through，则优先降级处理"]
measured_move: false
invalidation: ["回调继续加深并破坏最近 swing 结构，或触发后 1 至 2 根 bar 仍无 follow-through"]
risk_reward_min: 1.5
last_reviewed: 2026-04-20
strategy_id: PA-SC-001
source_family: fangfangtu_transcript
setup_family: trend_pullback_resumption
market_context: ["趋势恢复", "回调后顺势继续"]
evidence_quality: medium
chart_dependency: medium
needs_visual_review: false
test_priority: high
last_updated: 2026-04-20
---

# 趋势中回调后的顺势恢复

## 1. 来源依据

- 方方土 transcript 的市场周期与背景章节明确区分 `tight channel / broad channel / trading range`，并强调顺势恢复优先于逆势摸顶抄底。
- transcript 中的开盘强势案例描述了“高开后回踩 EMA20，再沿缺口方向恢复”的典型恢复逻辑。
- Brooks `H2 / L2` 页与 `small TTR trend resumption` 页补充了“回调后等第二次恢复”的量化表达。
- 方方土《回调&数K线》笔记补充了回调定义、H1/H2/L1/L2 计数和“回调 vs 反转”的区分。

## 2. 核心交易思想

趋势行情里，大多数回调并不是新趋势的开始，而是顺势交易者重新进场、把价格拉回原方向的机会。关键不是“看到回调就抄底或摸顶”，而是等回调结束后重新出现顺势信号，再跟随主方向。

## 3. 适用市场环境

- 适合：强趋势、紧密通道、突破后的第一段回调、宽通道中的顺势恢复。
- 不适合：明确交易区间中部、强烈反向突破已经形成时、午盘低波动且方向不清楚时。

## 4. 入场前提

- 已经存在清晰方向的趋势背景。
- 回调没有彻底破坏最近一个有效 swing 结构。
- 背景仍偏顺势，而不是已经切回交易区间或反转模式。

## 5. 入场触发

- 做多：上涨趋势中的回调结束后，signal bar 高点被突破。
- 做空：下跌趋势中的回调结束后，signal bar 低点被跌破。
- 若 lower timeframe 可读性更好，可用更低周期做风险更小的同向触发。

## 6. 止损规则

- 默认放在 signal bar 另一侧。
- 若回调 swing 明确，可放在最近回调低点/高点外侧。
- 若 signal bar 过大导致止损过宽，本次交易跳过。

## 7. 止盈 / 出场规则

- 先测试 `1R / 1.5R / 2R` 三档固定目标。
- 若行情恢复成强趋势，可测试保留部分仓位并用结构移动止盈。
- 若触发后迟迟没有 follow-through，则优先时间止损或减仓。

## 8. 失效条件

- 触发后 1 到 2 根 bar 内没有顺势 follow-through。
- 价格重新跌回/涨回回调区，且破坏最近 swing。
- 背景从 trend 退化为明显 trading range。

## 9. 禁止交易条件

- 盘前盘后。
- 财报和重大新闻窗口。
- 交易区间中间位置。
- 趋势不明确或 signal bar 太大导致止损不合理。

## 10. 可量化规则草案

- 最近 `N` 根 bar 的高低点总体沿同方向抬高/降低，定义为趋势。
- 回调期间不能收盘穿越最近 swing 结构过深。
- signal bar 实体必须大于最近 `M` 根平均实体的一定比例，且收盘靠近极值。
- 触发后 `1~2` 根 bar 内必须出现同方向 follow-through，否则视为弱恢复。

## 11. 参数范围

- 趋势识别窗口：`10 / 20 / 30 bars`
- 回调最大深度：`25% / 38% / 50%`
- follow-through 确认：`1 / 2 / 3 bars`
- 目标位：`1R / 1.5R / 2R`

## 12. 回测假设

- 该策略在 `SPY / QQQ / NVDA / TSLA 5m` 上是否优于直接追突破。
- 紧密通道中的恢复是否明显优于宽通道中的恢复。
- 1R 与 2R 哪种出场更稳定。

## 13. 测试计划

- 标的：`SPY / QQQ / NVDA / TSLA`
- 周期：`5m` 主测，`15m` 复核
- 时间范围：优先使用现有 public history / intraday pilot 可覆盖区间
- 成本/滑点：ETF `1bp + 1 tick`，高波动个股 `2bp + 2 ticks`
- 最低样本要求：总交易数至少 `100`
- 通过标准：成本后期望值为正、`PF >= 1.10`
- 淘汰标准：验证集或样本外显著转负，或信号过少不足参考

## 14. 预期失败模式

- 在宽通道末端把衰竭误判成恢复。
- 回调太深其实已进入反转。
- 触发太早，买在回调中继而不是恢复点。

## 15. 当前结论

- `candidate`
- 当前已能整理成可测试规则，但仍需回测确认回调深度和 follow-through 阈值。
