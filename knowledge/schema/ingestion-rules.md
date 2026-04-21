# Ingestion Rules

本文件定义 M1 阶段从 `knowledge/raw/` 到 `knowledge/wiki/` 的最小入库规则。

## 1. raw 层

- 原始资料只放在 `knowledge/raw/`。
- raw 层不可改写、覆盖、删减或重命名后再冒充原始来源。
- 如需补充说明、截图整理或规则抽取，只能写入 wiki 层或补充说明文档。

## 2. wiki 层

- 整理结果写入 `knowledge/wiki/`。
- 每个 wiki 页面必须带 YAML frontmatter。
- frontmatter 契约以 `knowledge/schema/knowledge-schema.md` 与
  `knowledge/schema/page-frontmatter-template.md` 为准。
- 每页必须保留 `source_refs`，且条目应能回溯到 raw 层文件、转录、截图或内部索引。
- 缺图不阻塞入库，但必须记录在 `missing_visuals`。
- 已知冲突、版本差异、相互矛盾描述必须记录在 `contradictions`。
- 仍待确认的问题必须记录在 `open_questions`，不得用猜测填补缺口。
- `knowledge/wiki/**/templates/*.md` 仅作为模板占位，不参与 KB 校验与索引。

## 3. 页面类型与最小要求

- `concept`：允许记录概念、定义、适用市场、适用周期和关键规则引用。
- `setup`：必须补齐 `pa_context`、`signal_bar`、`entry_trigger`、`stop_rule`、
  `invalidation`。
- `source`：用于登记来源本身、资料说明或索引页；同样必须保留 `source_refs`。
- `strategy_cards/*/*.md`：继续使用 `setup` 或 `rule` 页面类型；同时补齐
  `strategy_id`、`source_family`、`setup_family`、`market_context`、
  `evidence_quality`、`chart_dependency`、`needs_visual_review`、
  `test_priority`、`last_updated`。该目录自 `M9G.0` 起只作为 legacy /
  historical baseline，不再作为新一轮 strategy extraction 的 seed catalog。
- `strategy_factory/strategies/*.md`：继续使用 `setup` 或 `rule` 页面类型；同时补齐
  `strategy_id`、`source_family`、`setup_family`、`market_context`、
  `evidence_quality`、`chart_dependency`、`needs_visual_review`、
  `test_priority`、`last_updated`、`factory_stage`、`readiness_gate`、
  `factory_decision`、`decision_reason`、`legacy_overlap_refs`、
  `historical_comparison_refs`、`historical_benchmark_refs`。新编号空间固定为
  `SF-*`。

## 4. 可追溯与整理原则

- 来源文件、转录文档、补充资料都要能回溯到 raw 层。
- 不得把推断写成事实；不确定内容必须落在 `open_questions`。
- 不得把 wiki 页面写成“已验证盈利结论”。
- 若同一策略只有 notes 支持、缺少 transcript / Brooks 补证，应明确保留为
  `draft`，不得写成 `promoted`。
- 对同一规则的不同表述，优先保留原始引用，再在 wiki 中做结构化整理。

## 5. 脚本协同规则

- `scripts/validate_kb.py` 负责校验 frontmatter、页面类型、必填字段和
  `setup` 额外必填字段。
- `scripts/build_kb_index.py` 负责从 wiki 页面提取统一索引字段并写入
  `knowledge/wiki_index.json`。
- 两个脚本都必须支持空 wiki 目录路径，不得因“没有页面”而失败。
- 两个脚本都必须跳过 `templates/` 目录中的 Markdown 文件。

## 6. M1 代表性验证路径

- 空目录路径：用于确认脚本可在没有 wiki 页面时稳定返回成功。
- 代表性页面路径：至少覆盖 `concept`、`setup`、`source` 三类页面。
- 任何代表性页面只要缺失必填字段、使用非法枚举值或把列表字段写成非列表，
  校验脚本都必须失败。
