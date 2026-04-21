---
title: Strategy Cards Index (Legacy Baseline)
type: source
status: superseded
confidence: medium
market: ["US"]
timeframes: ["5m", "15m"]
direction: neutral
source_refs: ["internal/strategy-cards-index", "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md", "wiki:knowledge/wiki/sources/fangfangtu-pullback-counting-bars-note.md"]
tags: ["strategy-cards", "m9", "strategy-lab", "research-only"]
applicability: ["用于汇总 M9 首批 PA-SC strategy cards 的 legacy / historical baseline"]
not_applicable: ["不构成可执行交易规则", "不直接驱动 trigger 或模拟执行", "不得作为 M9G Strategy Factory 的 seed catalog 或 family prior"]
contradictions: []
missing_visuals: []
open_questions: ["如需和新的 SF catalog 建立 overlap，只能在新 catalog 中以 comparison / benchmark 字段显式登记"]
pa_context: []
market_cycle: []
higher_timeframe_context: []
bar_by_bar_notes: []
signal_bar: []
entry_trigger: []
entry_bar: []
stop_rule: []
target_rule: []
trade_management: []
measured_move: false
invalidation: []
risk_reward_min:
last_reviewed: 2026-04-20
---

# Strategy Cards Index (Legacy Baseline)

自 `M9G.0` 起，本目录只作为 legacy / historical baseline 保留。

- 不得作为新一轮 Strategy Factory 的 seed catalog。
- 不得作为新 family 划分、编号或 triage 的默认起点。
- 仅允许用于 overlap tagging、historical comparison 与 regression reference。

本目录中的首批策略卡继续保持 `research-only`、`paper / simulated` 边界。其历史来源优先级固定为：

1. `fangfangtu_transcript`
2. `al_brooks_ppt`
3. `fangfangtu_notes`

| 策略 ID | 策略名称 | 文件 | 类型 | 状态 | 测试优先级 | 当前结论 |
|---|---|---|---|---|---|---|
| `PA-SC-001` | 趋势中回调后的顺势恢复 | [pa-sc-001-trend-pullback-resumption.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/combined/pa-sc-001-trend-pullback-resumption.md) | `setup` | `candidate` | `high` | 可准备回测 |
| `PA-SC-002` | 突破后的 Follow-Through 延续 | [pa-sc-002-breakout-follow-through.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/combined/pa-sc-002-breakout-follow-through.md) | `setup` | `candidate` | `high` | 可准备回测 |
| `PA-SC-003` | 失败突破后回到区间的反转 | [pa-sc-003-failed-breakout-reversal.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/combined/pa-sc-003-failed-breakout-reversal.md) | `setup` | `candidate` | `high` | 可准备回测 |
| `PA-SC-004` | 交易区间上沿 / 下沿反转 | [pa-sc-004-trading-range-edge-reversal.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/fangfangtu/pa-sc-004-trading-range-edge-reversal.md) | `setup` | `candidate` | `medium` | 可准备回测 |
| `PA-SC-005` | 二次入场 / 两腿回调 H2-L2 | [pa-sc-005-h2-l2-second-entry.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/combined/pa-sc-005-h2-l2-second-entry.md) | `setup` | `candidate` | `high` | 可准备回测 |
| `PA-SC-006` | 紧密通道中的顺势恢复 | [pa-sc-006-tight-channel-resumption.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/combined/pa-sc-006-tight-channel-resumption.md) | `setup` | `candidate` | `medium` | 可准备回测 |
| `PA-SC-007` | 楔形 / 衰竭后的反转 | [pa-sc-007-wedge-exhaustion-reversal.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/fangfangtu/pa-sc-007-wedge-exhaustion-reversal.md) | `setup` | `draft` | `medium` | 缺图表确认 |
| `PA-SC-008` | 开盘区间突破或失败突破 | [pa-sc-008-opening-range-breakout.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/brooks/pa-sc-008-opening-range-breakout.md) | `setup` | `draft` | `medium` | 缺图表确认 |
| `PA-SC-009` | 强趋势日 vs 震荡日过滤 | [pa-sc-009-trend-day-range-day-filter.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/combined/pa-sc-009-trend-day-range-day-filter.md) | `rule` | `candidate` | `high` | 可准备过滤测试 |
| `PA-SC-010` | 高波动个股趋势延续与风险过滤 | [pa-sc-010-high-volatility-risk-filter.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/combined/pa-sc-010-high-volatility-risk-filter.md) | `rule` | `draft` | `medium` | 仅形成研究假设 |

## 当前重点

- 新的 Strategy Factory 根目录：[knowledge/wiki/strategy_factory/index.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_factory/index.md)
- `PA-SC-002` 只保留为历史 benchmark：[PA-SC-002-executable-v0.1.md](/home/hgl/projects/Price-Action-Trader/knowledge/wiki/strategy_cards/combined/PA-SC-002-executable-v0.1.md)
- 所有 legacy 卡片都只代表历史研究与测试准备，不代表稳定盈利或实盘可执行。
