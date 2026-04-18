---
title: Breakout Follow-Through / Failed Breakout (Minimal Curated Promotion)
type: rule
status: draft
confidence: low
market: ["US", "HK"]
timeframes: ["5m", "15m", "1h", "multi-timeframe"]
direction: neutral
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-breakout-note.md", "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md"]
tags: ["rule", "breakout", "follow-through", "failed-breakout", "research-only", "curated-promotion-minimal-set"]
applicability: ["用于 actual trace、signal explanation、no-trade / wait、knowledge review 的第二轮最小 curated promotion", "只描述 breakout quality、follow-through 与 failed breakout 的 evidence-backed 解释层，不作为 trigger 输入"]
not_applicable: ["不构成可执行交易规则", "不直接驱动自动信号、回测优化、模拟执行或实盘决策"]
contradictions: []
missing_visuals: []
open_questions: ["follow-through 需要几根 bar 才能从观察性描述升格为稳定确认条件仍未冻结", "failed breakout 在何时应解释为 pullback、何时应解释为 reversal 仍待更细字段映射"]
pa_context: ["breakout", "trend", "trading-range", "transition"]
market_cycle: ["pending-source-confirmation"]
higher_timeframe_context: ["pending-source-confirmation"]
bar_by_bar_notes: ["本页只把 breakout quality / failed breakout 提升为 explanation-only trace theme，不写成 executable setup rule"]
signal_bar: []
entry_trigger: ["突破需要 follow-through 与方向性确认；缺少后续跟进时，应优先保守解释而不是把突破直接当成可执行入场"]
entry_bar: []
stop_rule: []
target_rule: []
trade_management: []
measured_move: false
invalidation: ["当 follow-through 不足、或 failed breakout / opposite breakout 风险占优时，应优先进入 wait / review 解释层"]
risk_reward_min:
last_reviewed: 2026-04-18
---

# Breakout Follow-Through / Failed Breakout (Minimal Curated Promotion)

本页是 `M8D.2` 新增的最小 curated `rule` 页，只用于把 breakout quality、follow-through 与 failed breakout 的少量交叉证据提升到 curated 层。

## 当前最小可确认范围

- breakout 不能只看单根强 bar，还要看后续是否有 follow-through。
- follow-through 不足时，trace 应优先解释为 wait / review，而不是把 broad support 伪装成 actual hit。
- failed breakout 仍然只进入 explanation / no-trade / review，不进入 trigger。

## Research-only Boundaries

- 本页不是 executable rule。
- 本页不会进入 trigger。
- 本页只用于 actual trace、signal explanation、no-trade / wait 与 report / review 的 evidence-backed 修复。
