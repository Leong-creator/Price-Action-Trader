---
title: 高波动个股趋势延续与风险过滤
type: rule
status: draft
confidence: low
market: ["US"]
timeframes: ["5m", "15m", "1d"]
direction: neutral
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md", "wiki:knowledge/wiki/sources/fangfangtu-wedge-note.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-37-52-units.md"]
tags: ["strategy-card", "filter", "high-volatility", "risk", "m9"]
applicability: ["用于评估高波动个股是否适合放行趋势延续类策略", "用于研究 risk-on / risk-off 与波动过滤"]
not_applicable: ["不构成独立入场 trigger", "不代表已验证稳定盈利", "当前只形成研究假设"]
contradictions: ["Brooks 的 risk-on/risk-off 主要是风险偏好视角，方方土 notes 的 TSLA parabolic wedge 更偏个案警示，两者尚未统一成稳定字段"]
missing_visuals: ["需要补高波动个股的 trend continuation、climax、parabolic wedge 与 earnings 前后样本图"]
open_questions: ["高波动应以 ATR、日内区间、gap 频率还是事件标签定义仍待统一", "过滤器应该是完全禁做，还是只在特定 regime 下放行，仍待验证"]
pa_context: ["high-volatility", "risk-filter", "trend-continuation", "climax"]
market_cycle: ["breakout", "trend", "climax", "trading-range"]
higher_timeframe_context: ["若日线已出现 parabolic wedge 或重大事件前后，高波动个股的日内延续策略应大幅降级"]
bar_by_bar_notes: ["高波动并不自动等于更好机会；没有 follow-through 时，滑点和过宽 stop 往往先吃掉优势"]
signal_bar: ["不适用，作为过滤卡只判断是否允许下游 setup 在高波动个股上放行"]
entry_trigger: ["仅当高波动个股同时满足趋势清晰、regular session、无事件窗口且风险回报合理时，才放行下游 trend setup"]
entry_bar: ["不适用，依赖下游 setup 自身入场"]
stop_rule: ["不适用，过滤卡不单独定义 stop"]
target_rule: ["不适用，重点是判断成本、滑点与回撤是否可接受"]
trade_management: ["若标的出现 climax、gap 扩大、连续大 bar 失真，应主动降级或禁做"]
measured_move: false
invalidation: ["波动过高但无趋势结构、财报/重大新闻临近、gap 与滑点过大、或出现 parabolic wedge 衰竭迹象"]
risk_reward_min:
last_reviewed: 2026-04-20
strategy_id: PA-SC-010
source_family: fangfangtu_transcript
setup_family: high_volatility_risk_filter
market_context: ["高波动个股", "风险过滤", "趋势延续"]
evidence_quality: low
chart_dependency: high
needs_visual_review: true
test_priority: medium
last_updated: 2026-04-20
---

# 高波动个股趋势延续与风险过滤

## 1. 来源依据

- 方方土 transcript 对强单边和风险预案有概念性提醒，但对“高波动个股过滤”的直接文字证据较弱。
- Brooks 的 risk-on / risk-off 页面明确区分了低波动与高波动标的在不同情绪阶段的风险承受差异。
- 方方土《楔形》笔记中的 TSLA parabolic wedge 例子强调：高波动个股在 climax 后容易出现深回调或直接转入交易区间。
- 目前来源更像“风险提醒的拼图”，还不足以形成稳定、可执行的统一过滤规则，因此本卡保持 `draft`。

## 2. 核心交易思想

高波动个股的确更容易出现大趋势腿，但它们也更容易出现大滑点、过宽止损、事件驱动跳空和情绪化冲刺。这个过滤器不是为了证明“高波动更赚钱”，而是为了判断什么时候值得放行趋势延续类 setup，什么时候应该直接跳过。

## 3. 适用市场环境

- 适合：NVDA / TSLA 一类高波动个股的 regular-session 趋势延续研究。
- 不适合：财报前后、重大新闻窗口、盘前盘后、明显 parabolic climax 或流动性失真时段。

## 4. 入场前提

- 下游 strategy card 已经给出明确的 setup。
- 标的已被识别为高波动个股，且当日波动处于可接受区间。
- 事件风险、gap 风险和止损距离都已评估。

## 5. 入场触发

- 过滤器只负责“放行或禁做”。
- 放行条件候选：趋势清晰、follow-through 充足、regular session、无财报/重大新闻、理论 `RR` 仍可接受。
- 禁做条件候选：gap 过大、滑点预估过高、走势已 parabolic、或事件窗口临近。

## 6. 止损规则

- 过滤卡不单独定义止损。
- 若下游 setup 所需 stop 已超出预设风险上限，应直接拒绝交易。

## 7. 止盈 / 出场规则

- 过滤卡不单独定义止盈。
- 主要评估的是：高波动场景下，趋势延续策略的成本后表现是否还成立。

## 8. 失效条件

- 波动虽高，但没有清晰趋势结构。
- 波动来自财报/重大新闻而非可持续趋势。
- 下游 setup 的成本后期望值被滑点和止损宽度吞没。

## 9. 禁止交易条件

- 盘前盘后。
- 财报、重大新闻前后。
- 日内 gap 和点差异常大。
- 已出现 parabolic wedge / buy climax / sell climax 的衰竭特征。

## 10. 可量化规则草案

- 高波动定义候选：ATR 百分位、近 `N` 日平均日内振幅、开盘 gap 大小、或单 bar 极端实体比例。
- 放行候选：高波动 + 趋势清晰 + follow-through 充足 + `RR >= 1:1.5`。
- 禁做候选：高波动 + 事件窗口 + 滑点预估过高 + gap 过大。
- 过滤器输出：`allow_high_vol_trend`、`skip_event_risk`、`skip_slippage_risk`、`skip_climax_risk`。

## 11. 参数范围

- ATR 阈值：`70 / 80 / 90` 百分位
- 开盘 gap 阈值：`1% / 2% / 3%`
- 允许最大 stop：`1R` 对应的绝对价格区间或 `0.5 / 1.0 / 1.5 ATR`
- 事件禁做窗口：财报前后 `1 / 2 / 3` 天

## 12. 回测假设

- 在 `NVDA / TSLA 5m` 上，加上高波动风险过滤后，趋势延续类 setup 是否更稳定。
- 风险过滤能否减少大回撤，但不过度砍掉盈利交易。
- 是否只有在 risk-on 环境里，高波动个股的趋势延续才更有优势。

## 13. 测试计划

- 测试标的：`NVDA / TSLA` 为主，`SPY / QQQ` 作为低波动对照
- 时间周期：`5m` 主测，`15m` 复核，`1d` 用于事件与更大级别背景
- 时间范围：优先覆盖含财报季和非财报季的样本
- 数据需求：OHLCV、regular session 标记、财报/重大新闻标签、ATR/日内波动统计
- 交易成本假设：高波动个股 `2bp + 2 ticks/side` 起步，并做更差情景敏感性测试
- 最低交易次数要求：过滤前后各自至少 `80` 笔
- 评价指标：交易次数、平均 R、PF、最大回撤、滑点敏感性、skip 原因统计、事件期与非事件期拆分
- 通过标准：成本后样本外表现改善且回撤下降，不仅依赖单一标的
- 淘汰标准：过滤后样本过少、结果高度不稳定，或主要收益来自事件赌方向

## 14. 预期失败模式

- 把所有高波动都当机会，忽略事件风险。
- 过滤器太保守，几乎不再放行任何交易。
- 高波动带来的收益被滑点、点差和更宽 stop 全部抵消。

## 15. 当前结论

- `draft`
- 当前主要是研究假设，必须补图表和事件标签后，才能判断是否值得进入正式过滤测试。
