---
title: Trend vs Range Filter (Minimal Curated Promotion)
type: rule
status: draft
confidence: low
market: ["US", "HK"]
timeframes: ["5m", "15m", "1h", "multi-timeframe"]
direction: neutral
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md", "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md"]
tags: ["rule", "trend-vs-range", "context-filter", "research-only", "curated-promotion-minimal-set"]
applicability: ["用于 signal explanation、no-trade / wait、knowledge trace 和 M8 最小 curated promotion", "只作为 context filter 解释，不作为 trigger 输入"]
not_applicable: ["不构成可执行交易规则", "不直接驱动自动信号、回测优化、模拟执行或实盘决策"]
contradictions: []
missing_visuals: []
open_questions: ["tight trading range 与可交易 breakout context 的量化阈值仍未冻结", "trend direction filter 是否需要更高周期一致性确认仍待补充"]
pa_context: ["trend", "trading-range", "tight-channel", "transition"]
market_cycle: ["pending-source-confirmation"]
higher_timeframe_context: ["pending-source-confirmation"]
bar_by_bar_notes: ["本页只定义最小 context filter 解释，不写成 executable rule"]
signal_bar: []
entry_trigger: []
entry_bar: []
stop_rule: []
target_rule: []
trade_management: []
measured_move: false
invalidation: ["在 tight trading range 或 context 不足时，应优先保守解释为 wait / no-trade，而不是强行升级为 breakout trade"]
risk_reward_min:
last_reviewed: 2026-04-18
---

# Trend vs Range Filter (Minimal Curated Promotion)

本页是阶段 B 新增的最小 curated `rule` 页。它只做一件事：把 FangFangTu transcript / Brooks PPT 中与 “trend vs range filter” 直接相关的少量证据提升到 curated 层，用于 actual trace 的真实性修复。

## 当前最小可确认范围

- `tight-channel` 仍属于 context / filter 语义，不是单独的 executable setup。
- 当市场处于过紧的 trading range、或 breakout 缺少 good context 时，应优先保守地解释为 `wait / no-trade`。
- 在 tight channel 语境中，只能沿趋势方向解释 setup，而不是把反向信号强行解释成等价机会。

## Research-only Boundaries

- 本页不是 executable rule。
- 本页不会进入 trigger。
- 本页只用于 actual trace、no-trade / wait explanation 与 report / review 的 evidence-backed 修复。
