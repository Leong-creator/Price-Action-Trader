# Knowledge Atom Schema

`knowledge_atoms.jsonl` 是 `M8B.2a` 的原子层。

## 支持的 `atom_type`

- `concept`
- `setup`
- `rule`
- `statement`
- `contradiction`
- `open_question`
- `source_note`

## 通用字段

每条 atom 至少包含：

- `atom_id`
- `atom_type`
- `content`
- `status`
- `confidence`
- `market`
- `timeframes`
- `pa_context`
- `signal_bar`
- `entry_bar`
- `applicability`
- `not_applicable`
- `contradictions`
- `derived_from`
- `source_ref`
- `raw_locator`
- `evidence_chunk_ids`
- `callable_tags`
- `reviewed_at`
- `last_updated`

## `statement` 定义

`statement` 是首轮新增的中间层 callable atom：

- 是 evidence-backed 的最小可调用知识点
- 不是 executable rule
- 不参与 trigger 判定
- 允许被 query / filter / explanation / review 调用
- 一个 chunk 可产出 `0..n` 个 `statement`
- 若无法保守提取，则不产出

每个 `statement` 必须至少满足：

- `atom_type = statement`
- `status = draft`
- `source_ref` 非空
- `raw_locator` 非空
- `evidence_chunk_ids` 非空
- `callable_tags` 非空

## Curated Atom 约束

首轮 `concept / setup / rule` 只从现有 curated wiki 页面生成：

- `knowledge/wiki/concepts/market-cycle-overview.md`
- `knowledge/wiki/setups/signal-bar-entry-placeholder.md`
- `knowledge/wiki/rules/m3-research-reference-pack.md`

这些 atom 必须是 evidence-backed：

- 不允许没有 `source_ref`
- 不允许没有 `raw_locator`
- 不允许没有 `evidence_chunk_ids`

## 保守性约束

- `source_note / statement / contradiction / open_question` 默认不得带 `strategy_candidate`
- 无证据不产出 atom
- 不允许把 source-level 或 statement-level atom 冒充成 executable rule
