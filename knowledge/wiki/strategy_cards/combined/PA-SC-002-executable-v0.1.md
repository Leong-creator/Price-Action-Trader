---
title: PA-SC-002 Executable v0.1
type: setup
status: tested
confidence: medium
market: ["US"]
timeframes: ["5m"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md", "wiki:knowledge/wiki/sources/fangfangtu-breakout-note.md", "wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md", "wiki:knowledge/wiki/strategy_cards/combined/pa-sc-002-breakout-follow-through.md", "wiki:knowledge/wiki/strategy_cards/combined/pa-sc-009-trend-day-range-day-filter.md"]
tags: ["strategy-card", "executable-spec", "breakout", "follow-through", "m9"]
applicability: ["用于把 PA-SC-002 冻结成可回测的 v0.1 规则", "用于 SPY 5m 最小实验"]
not_applicable: ["不构成实盘 trigger", "不代表该策略已经稳定盈利"]
contradictions: []
missing_visuals: []
open_questions: ["30 分钟 breakout lookback 是否优于 40 / 50 / 60 分钟仍待测试", "1R 是否真的是最合适的 v0.1 默认止盈仍待验证"]
pa_context: ["breakout", "follow-through", "trend-resumption"]
market_cycle: ["breakout", "trading-range", "tight-channel"]
higher_timeframe_context: ["更高周期若紧贴更大级别阻力/支撑，本规则仍可能过度乐观"]
bar_by_bar_notes: ["v0.1 明确把 breakout 后 1 到 2 根 bar 内的 follow-through 作为必选确认，不接受单根大 bar 直接入场"]
signal_bar: ["突破最近 6 根 5m bar 高点/低点，并在本 bar 收盘继续站在突破方向外侧的 breakout bar"]
entry_trigger: ["breakout bar 之后 1 到 2 根 bar 内出现同向 follow-through，确认后下一根 bar 开盘入场"]
entry_bar: ["follow-through bar 后的下一根 5m bar"]
stop_rule: ["long 放在 breakout bar 低点与被突破边界下方的更保守一侧，再减 1 tick；short 对称处理"]
target_rule: ["固定 1R，仅作为 v0.1 最小实验默认值"]
trade_management: ["本版不加移动止盈，不做加仓；若收盘前仍未触及 stop 或 target，则按当日最后一根 5m bar 收盘退出"]
measured_move: false
invalidation: ["follow-through 窗口内回到原区间", "1 到 2 根 bar 内没有合格的 follow-through", "初始 stop 宽度超过最近 6 根 bar 中位波动的 3 倍"]
risk_reward_min:
last_reviewed: 2026-04-20
strategy_id: PA-SC-002
source_family: fangfangtu_transcript
setup_family: breakout_follow_through
market_context: ["regular session breakout continuation"]
evidence_quality: medium
chart_dependency: medium
needs_visual_review: false
test_priority: high
last_updated: 2026-04-20
---

# PA-SC-002 Executable v0.1

## 1. 来源依据

- 方方土 transcript 和 Brooks 一致强调：单根大 bar 不能直接当成有效突破，必须看后续 follow-through。
- Brooks 对 breakout / follow-through 的文字证据足以支撑“突破后 1 到 2 根 bar 内确认”的最小版本。
- 方方土 notes 只用于中文术语澄清，不覆盖 transcript 与 Brooks 的主证据。

## 2. 这版只冻结什么

- 只冻结 `SPY 5m`、`regular session only` 的最小回测规则。
- 只冻结 `PA-SC-002 + PA-SC-009 filter v0.1` 的配对实验，不把 `PA-SC-009` 升级成独立策略。
- 只冻结 `v0.1` 的 entry / stop / target / skip 逻辑，后续参数优化不在本版处理。

## 3. Breakout 定义

- 使用最近 `6` 根 `5m` bar 作为可见边界。
  - 这是为了把 `SPY 5m` 的最小实验客观化而加入的研究假设，不是来源里明确给出的唯一正确窗口。
- long breakout：
  - 当前 bar 的 `high` 突破最近 `6` 根 bar 的最高点；
  - 当前 bar 的 `close` 仍收在该最高点之上。
- short breakout：
  - 当前 bar 的 `low` 跌破最近 `6` 根 bar 的最低点；
  - 当前 bar 的 `close` 仍收在该最低点之下。
- 如果只是区间中部的大 bar，但收盘没有站出边界，不算 breakout。

## 4. Breakout bar 质量要求

- breakout bar 实体至少达到最近 `6` 根 bar 平均实体的 `0.9` 倍。
- `body / range >= 0.35`。
- long 时 `close` 需位于本 bar 上部 `60%` 区域；short 时对称。
- 反向尾巴不能过长：`opposite_wick / range <= 0.40`。
- 不满足上述条件，记为 `weak_breakout_bar`，直接跳过。

## 5. Follow-Through 定义

- 观察 breakout 之后的 `1` 到 `2` 根 `5m` bar。
- long follow-through：
  - `close` 继续站在 breakout 边界上方；
  - `close` 位于本 bar 上部至少 `50%`；
  - `body / range >= 0.20`。
- short follow-through 对称处理。
- 如果在确认窗口内价格重新回到原区间，记为 `returned_to_range`。
- 如果 2 根 bar 内都没有合格的延续，记为 `no_follow_through`。

## 6. 入场触发

- 一旦出现合格 follow-through，下一根 `5m` bar 开盘入场。
- 本版不额外加 `entry buffer`，因为滑点已经单独计入。
- 同一时刻不允许叠加未平仓交易；上一笔结束后才继续扫描下一笔。

## 7. `PA-SC-009` 过滤器 v0.1

- 本轮只做 `negative veto`，不做正向加分。
- 过滤窗口同样使用 breakout 前最近 `6` 根 `5m` bar。
- 触发 `range_veto` 的任一条件成立即跳过：
  - 最近 6 根 bar 里方向翻转次数 `>= 4`，且净位移 / 总区间 `<= 30%`；
  - doji 数量 `>= 3`，且净位移 / 总区间 `<= 30%`。
- 若不触发 veto，则仅输出：
  - `trend_supportive`
  - `neutral`
- 本版只把 `range_veto` 用来禁做，不把 `trend_supportive` 当作单独 trigger。

## 8. 止损规则

- long：
  - `stop = min(breakout_bar.low, breakout_boundary) - 1 tick`
- short：
  - `stop = max(breakout_bar.high, breakout_boundary) + 1 tick`
- 如果初始风险距离超过最近 `6` 根 bar 中位波动的 `3` 倍，记为 `stop_too_wide`，直接跳过。

## 9. 止盈 / 出场规则

- `v0.1` 默认止盈：固定 `1R`。
- 这只是为了先跑最小样本，不代表来源已经证明 `1R` 最优。
- 若在当日 regular session 结束前既没 hit target 也没 hit stop，则按最后一根 `5m` bar 收盘退出。
- 同一根 bar 内若 stop 与 target 都触发，按更保守的 `stop_before_target_same_bar` 处理。

## 10. 成本和滑点

- 只测 `SPY`，成本假设固定为：
  - `0` 佣金
  - `1bp + 1 tick/side`
- 入场和出场都按最不利方向计入。
- 这会让小 stop breakout 的净结果明显恶化，因此本版结果必须看成本后净 R，而不是裸 price action。

## 11. 禁止交易条件

- 盘前盘后全部跳过。
- `range_veto` 成立时跳过。
- breakout bar 自身质量不合格时跳过。
- follow-through 在 2 根 bar 内没有确认时跳过。
- breakout 后迅速回区间时跳过。
- 止损会宽到不成比例时跳过。

## 12. 当前仍属假设的部分

- 最近 `6` 根 bar 是否真的是最合理的 breakout lookback，仍属研究假设。
- `1R` 是否优于 `1.5R / 2R`，仍属待测问题。
- 当前仓库没有可直接复用的 `SPY 5m` 事件标签，因此本版没有排除宏观新闻窗口；这是明确的数据缺口。

## 13. 当前结论

- `tested`
- 这版规则已经足够清晰，能直接回测。
- 第一轮 `SPY 5m` 最小实验已经完成，但当前整体成本后仍为负，下一步应先修改后重测，而不是直接推广。

