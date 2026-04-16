# Wiki Page Frontmatter Template

```yaml
---
title:
type: concept | setup | rule | indicator | market-regime | risk | source | glossary | case-study
status: draft | active | experimental | superseded
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
- `measured_move` 为布尔值。
- `risk_reward_min` 可留空；填值时应使用数值。
- 空 wiki 验证路径允许没有页面；一旦存在页面，就必须满足本模板契约。
