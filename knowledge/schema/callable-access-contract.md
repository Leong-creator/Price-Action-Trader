# Callable Access Contract

`knowledge_callable_index.json` 是 `M8B.2a` 的 machine-readable callable index。

## 目标

本轮只提供原子层的结构化可查询能力，不接 strategy runtime。

## 支持的过滤维度

- `atom_type`
- `source_id`
- `source_family`
- `market`
- `timeframe`
- `pa_context`
- `status`
- `confidence`
- `callable_tags`

## Callable Tags

首轮固定支持：

- `source_family:<family>`
- `source_type:<type>`
- `statement_candidate`
- `curated_callable`
- `explanation_only`
- `review_only`
- `strategy_candidate`

## 约束

- `statement` 默认只能带：
  - `statement_candidate`
  - `explanation_only`
  - `review_only`
- 本轮不允许默认给 `statement` 打 `strategy_candidate`
- 本轮不允许通过 callable index 直接改 strategy / trigger

## Index 结构

`knowledge_callable_index.json` 至少包含：

- `schema_version`
- `generated_at`
- `atom_count`
- `indices`

`indices` 至少包含：

- `by_atom_type`
- `by_source_id`
- `by_source_family`
- `by_market`
- `by_timeframe`
- `by_pa_context`
- `by_status`
- `by_confidence`
- `by_callable_tag`
