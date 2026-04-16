---
title: M3 Research Reference Pack
type: rule
status: draft
confidence: low
market: ["US", "HK"]
timeframes: ["5m", "15m", "1h", "multi-timeframe"]
direction: neutral
source_refs: ["wiki:knowledge/wiki/concepts/market-cycle-overview.md", "wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md", "wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md", "wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md"]
tags: ["m3", "research-only", "signal-reference", "knowledge-bridge"]
applicability: ["仅供 M3 signal prototype 建立最小知识引用与字段映射", "仅供研究、回测输入准备和解释性输出占位"]
not_applicable: ["不构成可执行交易规则", "不构成回测结论", "不允许直接驱动模拟执行或实盘决策"]
contradictions: []
missing_visuals: ["市场周期示意图与 signal bar 图例仍待补充"]
open_questions: ["需要从 raw 资料补齐逐页定位后再冻结规则版本", "需要确认 signal bar setup 的明确过滤条件与失效条件"]
pa_context: ["trend", "trading-range", "transition"]
market_cycle: ["pending-source-confirmation"]
higher_timeframe_context: ["pending-source-confirmation"]
bar_by_bar_notes: ["本页只整理引用边界，不输出未经核验的逐K结论"]
signal_bar: ["signal-bar-entry-placeholder"]
entry_trigger: ["pending-source-confirmation"]
entry_bar: ["pending-source-confirmation"]
stop_rule: ["pending-source-confirmation"]
target_rule: ["pending-source-confirmation"]
trade_management: ["pending-source-confirmation"]
measured_move: false
invalidation: ["pending-source-confirmation"]
risk_reward_min:
last_reviewed: 2026-04-17
---

# M3 Research Reference Pack

本页为 M3 提供最小知识引用层，作用是把现有 `concept`、`setup` 和 `source` 页面整理成可追溯、低置信度、research-only 的引用包。

## Research-only Constraints

- 本页不新增任何原始事实，只整理现有 wiki 页面与项目规范中已经明确的字段边界。
- 所有引用都必须保留 `confidence: low`、`source_refs` 和 assumptions。
- 未完成 raw 抽取前，本页不得被当成可执行策略规则、回测结论或订单触发器。

## Interface Alignment

- signal 目标字段对齐 `docs/requirements.md` 与 `docs/pa-strategy-spec.md` 中的最小字段集。
- setup 解释边界以 `knowledge/wiki/setups/signal-bar-entry-placeholder.md` 为准。
- context 候选值以 `knowledge/wiki/concepts/market-cycle-overview.md` 当前可确认范围为准。

## Structured Reference Summary

```yaml
bundle_id: m3-research-reference-pack-v1
research_only: true
confidence: low
references:
  - reference_id: context.market_cycle.overview
    kind: context
    page: knowledge/wiki/concepts/market-cycle-overview.md
    source_refs:
      - wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md
      - raw:knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf
    supported_signal_fields:
      - pa_context
      - explanation
      - source_refs
      - risk_notes
    candidate_values:
      pa_context:
        - trend
        - trading-range
        - transition
    unresolved_fields:
      - market_cycle
      - higher_timeframe_context
      - bar_by_bar_notes
    assumptions:
      - three pa_context labels are placeholders for M3 context bucketing only
      - higher timeframe filters remain unresolved until raw extraction completes
  - reference_id: setup.signal_bar_entry.placeholder
    kind: setup
    page: knowledge/wiki/setups/signal-bar-entry-placeholder.md
    source_refs:
      - wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md
      - raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf
    supported_signal_fields:
      - setup_type
      - pa_context
      - entry_trigger
      - stop_rule
      - target_rule
      - invalidation
      - explanation
      - source_refs
      - risk_notes
    candidate_values:
      setup_type: signal-bar-entry-placeholder
    unresolved_fields:
      - pa_context
      - signal_bar
      - entry_trigger
      - entry_bar
      - stop_rule
      - target_rule
      - trade_management
      - risk_reward_min
      - invalidation
    assumptions:
      - setup_type is a placeholder identifier derived from the current wiki page title
      - pending field values must stay descriptive and non-executable until raw extraction confirms them
```

## Recommended M3 Usage

- 只把 `pa_context` 候选值当作解释标签或 signal 输出字段占位，不把它们当作已验证 market regime 分类器。
- 只把 `setup_type: signal-bar-entry-placeholder` 当作 research-only setup 标识，不把待确认字段转成触发逻辑。
- 所有 signal explanation 都应回链到本页列出的 wiki/source 路径，确保后续 raw 抽取可回填。
