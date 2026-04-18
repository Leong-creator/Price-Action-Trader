---
title: Tight Channel / Trend Resumption (Minimal Curated Promotion)
type: rule
status: draft
confidence: low
market: ["US", "HK"]
timeframes: ["5m", "15m", "1h", "multi-timeframe"]
direction: neutral
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-breakout-note.md", "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md"]
tags: ["rule", "tight-channel", "trend-resumption", "always-in", "research-only", "curated-promotion-minimal-set"]
applicability: ["用于 actual trace、signal explanation、no-trade / wait、knowledge review 的第二轮最小 curated promotion", "只描述 tight channel / trend resumption 的 context 与 invalidation 解释层，不作为 trigger 输入"]
not_applicable: ["不构成可执行交易规则", "不直接驱动自动信号、回测优化、模拟执行或实盘决策"]
contradictions: []
missing_visuals: []
open_questions: ["tight channel 与 broad channel 的量化分界仍未冻结", "trend resumption 与 exhaustion / reversal 的切换阈值仍待更细字段映射"]
pa_context: ["tight-channel", "trend", "trend-resumption", "always-in"]
market_cycle: ["pending-source-confirmation"]
higher_timeframe_context: ["pending-source-confirmation"]
bar_by_bar_notes: ["本页只把 tight channel / trend resumption 作为 explanation-only context，不扩成新的 executable setup family"]
signal_bar: []
entry_trigger: []
entry_bar: []
stop_rule: []
target_rule: []
trade_management: []
measured_move: false
invalidation: ["当 tight channel 退化成 broad channel、或突破后的恢复走势缺少延续时，应优先解释为 wait / review，而不是强行升级为新 setup"]
risk_reward_min:
last_reviewed: 2026-04-18
---

# Tight Channel / Trend Resumption (Minimal Curated Promotion)

本页是 `M8D.2` 新增的最小 curated `rule` 页，只把 tight channel、always-in 方向性与 trend resumption 的少量交叉证据提升到 curated 层。

## 当前最小可确认范围

- tight channel 仍然是 context / filter 语义，不是新的 setup family。
- 当市场仍处在 tight channel / breakout-stage 延续语境时，trace 应优先解释为顺势与 trend-resumption 语义。
- 当 tight channel 退化成 broad channel 或 follow-through 不足时，应回到 wait / review，而不是把它包装成稳定可执行规则。

## Research-only Boundaries

- 本页不是 executable rule。
- 本页不会进入 trigger。
- 本页只用于 actual trace、signal explanation、no-trade / wait 与 report / review 的 evidence-backed 修复。
