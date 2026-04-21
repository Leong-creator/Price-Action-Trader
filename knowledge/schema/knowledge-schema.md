# Knowledge Schema

本文件定义 M1 阶段知识库页面的统一字段契约。`scripts/validate_kb.py` 与
`scripts/build_kb_index.py` 必须与此文件保持一致。

## 1. 支持页面类型

- `concept`
- `setup`
- `rule`
- `indicator`
- `market-regime`
- `risk`
- `source`
- `glossary`
- `case-study`

## 2. 允许值

### `status`

- `draft`
- `active`
- `experimental`
- `superseded`
- `candidate`
- `tested`
- `promoted`
- `rejected`

### `confidence`

- `low`
- `medium`
- `high`

### `direction`

- `long`
- `short`
- `both`
- `neutral`

## 3. 所有 wiki 页面必填字段

- `title`
- `type`
- `status`
- `confidence`
- `source_refs`
- `last_reviewed`

## 4. 所有 wiki 页面通用字段

- `market`
- `timeframes`
- `direction`
- `tags`
- `applicability`
- `not_applicable`
- `contradictions`
- `missing_visuals`
- `open_questions`
- `market_context`

说明：

- `source_refs`、`market`、`timeframes`、`tags`、`applicability`、`not_applicable`、
  `contradictions`、`missing_visuals`、`open_questions`、`market_context`
  必须为列表。
- `last_reviewed` 为非空标量值，当前阶段按字符串日期存储。

## 5. setup 页面额外必填字段

当 `type: setup` 时，以下字段必须存在且非空：

- `pa_context`
- `signal_bar`
- `entry_trigger`
- `stop_rule`
- `invalidation`

## 6. PA 专属字段

以下字段用于 `setup`、`concept`、`rule` 等页面的 PA 表达；如出现，必须与
frontmatter 模板保持同名：

- `pa_context`
- `market_cycle`
- `higher_timeframe_context`
- `bar_by_bar_notes`
- `signal_bar`
- `entry_trigger`
- `entry_bar`
- `stop_rule`
- `target_rule`
- `trade_management`
- `measured_move`
- `invalidation`
- `risk_reward_min`
- `strategy_id`
- `source_family`
- `setup_family`
- `market_context`
- `evidence_quality`
- `chart_dependency`
- `needs_visual_review`
- `test_priority`
- `last_updated`

说明：

- `measured_move` 为布尔值。
- `needs_visual_review` 为布尔值。
- `risk_reward_min` 为数值或空值。
- 其余 PA 字段按列表处理。

## 7. Strategy Card 补充约束

位于 `knowledge/wiki/strategy_cards/brooks/`、`fangfangtu/`、`combined/`
目录下的页面视为 strategy card，除通用字段外还必须补齐：

- `strategy_id`
- `source_family`
- `setup_family`
- `market_context`
- `evidence_quality`
- `chart_dependency`
- `needs_visual_review`
- `test_priority`
- `last_updated`

说明：

- `source_family`、`setup_family`、`evidence_quality`、`chart_dependency`、
  `test_priority`、`last_updated` 必须为非空标量值。
- `market_context` 必须为非空列表。
- `templates/` 目录中的 Markdown 文件只作模板，不参与 KB 校验与索引。

## 8. wiki index 输出字段

`scripts/build_kb_index.py` 生成的 `knowledge/wiki_index.json` 至少保留以下字段：

- `path`
- `title`
- `type`
- `status`
- `confidence`
- `market`
- `timeframes`
- `direction`
- `source_refs`
- `pa_context`
- `tags`
- `open_questions`
- `strategy_id`
- `source_family`
- `setup_family`
- `market_context`
- `evidence_quality`
- `chart_dependency`
- `needs_visual_review`
- `test_priority`
- `last_updated`

## 9. M1 / M9 验证约束

- 空 wiki 目录必须返回成功，不视为错误。
- 非空 wiki 目录至少应支持 `concept`、`setup`、`source` 三类页面。
- 校验脚本必须对缺失 frontmatter、非法枚举值、列表字段类型错误、`setup`
  必填字段缺失给出稳定报错。
- 索引脚本必须能在空 wiki 与非空 wiki 两条路径下重复执行。
- `templates/` 目录中的 Markdown 文件不得导致 KB 校验失败，也不得进入
  `knowledge/wiki_index.json`。
