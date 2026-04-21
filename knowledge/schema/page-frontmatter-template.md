# Wiki Page Frontmatter Template

```yaml
---
title:
type: concept | setup | rule | indicator | market-regime | risk | source | glossary | case-study
status: draft | active | experimental | superseded | candidate | tested | promoted | rejected
confidence: low | medium | high
market: []
timeframes: []
direction: long | short | both | neutral
source_refs: []
tags: []
applicability: []
not_applicable: []
contradictions: []
missing_visuals: []
open_questions: []

# PA-specific fields
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

last_reviewed:

# Strategy-card specific fields
strategy_id:
source_family:
setup_family:
market_context: []
evidence_quality: low | medium | high
chart_dependency: low | medium | high
needs_visual_review: true | false
test_priority: high | medium | low
last_updated:

# Strategy-factory specific fields
factory_stage:
readiness_gate: ready | needs_visual_review | needs_event_labels | needs_definition_freeze | blocked_source | blocked_provider
factory_decision: retain | modify_and_retest | insufficient_sample | parked | rejected_variant
decision_reason:
legacy_overlap_refs: []
historical_comparison_refs: []
historical_benchmark_refs: []
---
```

## Required For All Pages

- `title`
- `type`
- `status`
- `confidence`
- `source_refs`
- `last_reviewed`

## Required When `type: setup`

- `pa_context`
- `signal_bar`
- `entry_trigger`
- `stop_rule`
- `invalidation`

## Field Notes

- `source_refs`、`market`、`timeframes`、`tags`、`applicability`、
  `not_applicable`、`contradictions`、`missing_visuals`、`open_questions`
  必须写为列表。
- `market_context` 在 strategy card 中也必须写为列表。
- `measured_move` 为布尔值。
- `needs_visual_review` 为布尔值。
- `risk_reward_min` 可留空；填值时应使用数值。
- `strategy_id`、`source_family`、`setup_family`、`evidence_quality`、
  `chart_dependency`、`test_priority`、`last_updated` 为 strategy card 常用字段。
- `factory_stage`、`readiness_gate`、`factory_decision`、`decision_reason` 为
  strategy factory 常用标量字段。
- `legacy_overlap_refs`、`historical_comparison_refs`、
  `historical_benchmark_refs` 为 strategy factory 常用列表字段。
- `knowledge/wiki/**/templates/*.md` 为模板目录，校验脚本与索引脚本应跳过。
- 空 wiki 验证路径允许没有页面；一旦存在页面，就必须满足本模板契约。
