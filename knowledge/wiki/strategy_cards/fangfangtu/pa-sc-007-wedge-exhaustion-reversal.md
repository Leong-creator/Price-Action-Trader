---
title: 楔形 / 衰竭后的反转
type: setup
status: draft
confidence: low
market: ["US"]
timeframes: ["5m", "15m"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-37-52-units.md", "wiki:knowledge/wiki/sources/fangfangtu-wedge-note.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md"]
tags: ["strategy-card", "wedge", "exhaustion", "reversal", "m9"]
applicability: ["用于研究楔形或衰竭走势后的反转机会", "当前主要用于图表复核与策略草案沉淀"]
not_applicable: ["不构成自动 trigger", "不代表已验证稳定盈利", "未完成图表复核前不进入程序化回测"]
contradictions: ["方方土 notes 提供了较多楔形变体与经验数字，但不少规则高度依赖图示，当前不能直接固化成统一触发器"]
missing_visuals: ["需要补三推顶/底、nested wedge、truncated wedge 与 parabolic wedge 的标准例图"]
open_questions: ["三推计数应以摆动高低点、收盘价还是重叠区趋势线为准仍未冻结", "楔形反转应做 first entry、second entry 还是等强反向突破确认仍待图表核验"]
pa_context: ["wedge", "exhaustion", "reversal", "climax"]
market_cycle: ["broad-channel", "trend", "trading-range"]
higher_timeframe_context: ["若更高周期仍处于 tight channel 强趋势，本卡应降级处理，避免逆势过早"]
bar_by_bar_notes: ["楔形大多不完美，不能只凭肉眼数到三推就入场，必须结合动能衰减与反向信号 bar"]
signal_bar: ["楔形末端的强反向 signal bar，或衰竭后出现的明显 opposite breakout bar"]
entry_trigger: ["优先等待反向 signal bar 被突破；若只有概念描述而无清晰 signal bar，保持观望"]
entry_bar: ["楔形第三推后的第一根或第二根有效反向确认 bar"]
stop_rule: ["默认放在楔形极值外侧，但具体放法仍依赖图表确认"]
target_rule: ["先看 scalp + swing 的组合目标，或先回测到前一摆动点 / 区间中轴"]
trade_management: ["若反转突破失败，应快速退出，避免被顺势 measured move 反向吞没"]
measured_move: true
invalidation: ["反向突破没有 follow-through、价格迅速回到楔形方向、或更大级别 tight channel 仍强势压制"]
risk_reward_min: 1.5
last_reviewed: 2026-04-20
strategy_id: PA-SC-007
source_family: fangfangtu_transcript
setup_family: wedge_exhaustion_reversal
market_context: ["楔形", "衰竭", "反转尝试"]
evidence_quality: low
chart_dependency: high
needs_visual_review: true
test_priority: medium
last_updated: 2026-04-20
---

# 楔形 / 衰竭后的反转

## 1. 来源依据

- 方方土 transcript 把衰竭、第二段陷阱和趋势末端的反转风险作为重要主题，但逐段定位仍不完整。
- Brooks 在 wedge / climax / failed breakout 相关页面强调：强趋势往往以楔形结束，但大多数反转在出现足够 opposite strength 前都会失败。
- 方方土《楔形》笔记给出了三推、nested wedge、truncated wedge、parabolic wedge 等分类，并提醒大部分楔形都不完美。
- 目前证据更偏概念和图形阅读，缺少统一的、低歧义的文字触发规则，因此本卡只能保留为 `draft`。

## 2. 核心交易思想

趋势走到后段时，市场会出现“还在创新高/新低，但推进效率越来越差”的情况。楔形或衰竭的意义，不是说第三推一定反转，而是提醒顺势动能可能已经减弱，随后更容易出现至少一段反向修正，甚至进入交易区间。

## 3. 适用市场环境

- 适合：宽通道末端、明显 buy/sell climax、三推后动能减弱、区间边缘的楔形。
- 不适合：tight channel 强趋势、开盘刚形成的单边爆发行情、没有明显重叠与衰竭痕迹的普通趋势。

## 4. 入场前提

- 至少存在可辨认的多次同向推动。
- 后续推动虽然创新高/新低，但 follow-through 变差、尾巴增多、重叠增加或突破效果变弱。
- 最好位于更大级别阻力/支撑、区间边缘或前期测量目标附近。

## 5. 入场触发

- 做多：下跌楔形末端出现强多头 signal bar，被突破后入场。
- 做空：上涨楔形末端出现强空头 signal bar，被跌破后入场。
- 若只看得到“三推”而没有明确反向 signal bar，则不入场。

## 6. 止损规则

- 初步假设放在楔形极值外侧。
- 若是 parabolic wedge，可测试放在最后一推极值外侧与结构止损两种版本。
- 由于图表依赖高，当前止损规则仍属于待测试假设。

## 7. 止盈 / 出场规则

- `v0.1`：先看 `1R`
- `v0.2`：先看回到前一个摆动低点/高点或区间中轴
- `v0.3`：scalp + swing 组合，先止盈一部分，再观察是否扩展成更大反转

## 8. 失效条件

- 反向 signal bar 很快被吞没。
- 反转突破没有 follow-through。
- 出现失败楔形反转，价格回到原趋势方向并加速。

## 9. 禁止交易条件

- 盘前盘后。
- 财报、重大新闻窗口。
- tight channel 强趋势中仅凭数楔形逆势入场。
- 看不清推数、重叠与极值定义时。

## 10. 可量化规则草案

- 候选定义：最近 `N` 根 bar 出现 `3` 次同向推进，但每次推进的实体质量或 follow-through 递减。
- 反向 trigger 需要一根或两根明显 opposite strength bar。
- 若反向突破后 `M` 根 bar 内重新回到原趋势方向，则视为失败反转。
- 在更高周期仍为 tight channel 时，默认不放行。

## 11. 参数范围

- 推数：`2 / 3 / 4`
- 允许的极值容差：`0 / 0.25 ATR / 0.5 ATR`
- follow-through 确认：`1 / 2 bars`
- 出场：`1R / 区间中轴 / 前一摆动点`

## 12. 回测假设

- 三推楔形在 `SPY / QQQ / NVDA / TSLA` 的 `5m` 上，是否只产生小反转而非真正趋势反转。
- 区间边缘的楔形是否明显优于 tight channel 内的楔形。
- first entry、second entry、breakout close 三种入场方式，哪种更稳。

## 13. 测试计划

- 测试标的：`SPY / QQQ / NVDA / TSLA`
- 时间周期：`5m` 主看，`15m` 辅助图表复核
- 时间范围：优先从已有 chart-heavy 案例中人工标注样本，再决定是否程序化
- 数据需求：OHLCV、regular session 标记、截图或可回放图表
- 交易成本假设：ETF `1bp + 1 tick/side`，高波动个股 `2bp + 2 ticks/side`
- 滑点假设：反转入场额外加 `1~2 ticks`
- 最低交易次数要求：人工标注样本至少 `50` 个，未达标不进入程序化评估
- 评价指标：命中率、平均 R、失败楔形占比、按 tight/broad channel 拆分表现
- 通过标准：先完成图表复核并把规则降到可实现歧义范围内
- 淘汰标准：无法形成统一可量化定义，或结果高度依赖个案解释

## 14. 预期失败模式

- 在强趋势中过早逆势。
- 误把普通两腿调整或随机重叠当成楔形。
- 三推出现了，但没有足够反向力量，结果只是小回调后继续顺势。

## 15. 当前结论

- `draft`
- 来源支持概念与图形逻辑，但当前仍需要人工补图确认，不能直接进入回测。
