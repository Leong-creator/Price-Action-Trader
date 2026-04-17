---
title: Market Cycle Overview
type: concept
status: draft
confidence: low
market: ["US", "HK"]
timeframes: ["5m", "15m", "1h", "multi-timeframe"]
direction: neutral
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md", "raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf", "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md"]
applicability: ["用于 research-only 的 market cycle / context 解释、traceability 和 no-trade / wait 审计", "用于 M8 知识引用修复阶段的 evidence-backed curated promotion"]
not_applicable: ["未完成字段级抽取前，不作为可执行交易规则", "不作为已验证的 market cycle 判定器或自动 regime 分类器"]
contradictions: []
missing_visuals: ["原始市场周期示意图和逐页截图待补"]
open_questions: ["trend / transition / trading-range 的切换阈值仍需进一步字段级抽取，不得直接转成 trigger 逻辑", "tight channel 与 trading-range 之间的边界在不同周期上仍需补充例外条件"]
tags: ["concept", "market-cycle", "pa-context", "research-only", "curated-promotion-minimal-set"]
pa_context: ["trend", "trading-range", "transition", "tight-channel"]
market_cycle: ["pending-source-confirmation"]
higher_timeframe_context: ["待从原始资料补充更高周期确认方法", "tight channel / trading-range 的高周期过滤仍待细化"]
bar_by_bar_notes: ["当前只补字段级 evidence-backed 摘要，不补写未经核验的逐K结论"]
signal_bar: []
entry_trigger: []
entry_bar: []
stop_rule: []
target_rule: []
trade_management: []
measured_move: false
invalidation: []
risk_reward_min:
last_reviewed: 2026-04-18
---

# Market Cycle Overview

本页是当前 `market cycle / context` 的最小 evidence-backed curated `concept` 页。它仍保持 `draft + low confidence + research-only` 边界，只用于解释、traceability 和 no-trade / wait 审计，不用于 trigger。

## 当前最小可确认范围

- FangFangTu 笔记当前支持把 `trend / trading-range / wide-channel / tight-channel` 作为 bar-by-bar 解释时的 context bucket，而不是自动 regime classifier。
- FangFangTu transcript 与 Brooks PPT 都提供了“通常先有交易区间，再形成更可靠趋势腿”的补充证据，因此本页不再只依赖笔记占位链。
- `tight-channel` 被保留为 context bucket，而不是单独的 executable setup。

## Evidence-backed Promotion Notes

- 见 `knowledge/indices/curated_promotion_map.json` 中的 `market_cycle_context`。
- 当前 promotion 只确认：
  - `pa_context` 可以继续使用 `trend / trading-range / transition` 作为 explanation bucket。
  - trading range 与 trend 之间的过渡经常需要先出现整理，而不是直接把任意强 bar 解释成新趋势已经确立。
  - tight channel 的解释权重可以保留在 context 层，但不能直接升级成 executable trigger。

## Research-only Boundaries

- 本页仍不是自动 regime 判定规则。
- `transition`、`tight-channel`、higher timeframe 过滤条件仍缺少足够窄化的字段级证据，不得直接当作 signal gate。
- 如 FangFangTu / Brooks 对 context 的优先级或边界出现冲突，必须保留为 `open_question` 或后续 `contradiction`，而不是强行扁平化。
