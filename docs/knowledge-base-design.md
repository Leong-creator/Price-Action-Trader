# 知识库设计

## 分层

- `knowledge/raw/`：原始资料，只归档，不改写。
- `knowledge/wiki/`：整理后的知识页，可检索、可引用、可结构化。
- `knowledge/schema/`：wiki frontmatter、ingestion 规则与校验约束。

## wiki 页面类型

- concepts
- setups
- rules
- indicators
- market-regimes
- risk
- sources
- glossary
- case-studies

## PA 专属要求

- setup 页面需要记录 `pa_context`、`bar_by_bar_notes`、`signal_bar`、`entry_trigger`、`stop_rule`、`target_rule`、`invalidation` 等字段。
- 缺失图表时使用 `missing_visuals` 标记，不阻塞入库。
- 每页必须保留 `source_refs`。
