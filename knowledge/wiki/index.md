---
title: Knowledge Wiki Index
type: source
status: draft
confidence: medium
market: []
timeframes: []
direction: neutral
source_refs: ["internal/wiki-index"]
tags: ["wiki-index", "internal"]
applicability: []
not_applicable: []
contradictions: []
missing_visuals: []
open_questions: []
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
last_reviewed: 2026-04-17
---

# Knowledge Wiki Index

当前 wiki 已初始化。

## M1 说明

- 当前页作为 wiki 根索引占位页，用于验证 `source` 类型页面契约。
- 后续请在对应类型目录下新增知识页，并保持 frontmatter 与
  `knowledge/schema/` 中的契约一致。
- `scripts/validate_kb.py` 与 `scripts/build_kb_index.py` 必须能处理仅有本页的
  wiki，以及完全空的临时 wiki 目录。

## M3 说明

- 当前已新增面向 M3 的 `research-only` 引用页与最小结构化索引。
- 所有 M3 知识引用必须保留 `low confidence`、`source_refs` 和 assumptions，不得把占位页升级成已验证交易规则。

## M6 说明

- 当前已新增 `knowledge/wiki/rules/m6-news-review-evidence-pack.md`，作为 M6 新闻过滤与复盘整合的最小 evidence pack。
- M6 中新闻只允许作为 `filter`、`explanation` 或 `risk hint`，不得升级为主信号源、订单触发器或执行指令。
- M6 evidence pack 只复用现有 wiki/source 页面；若后续需要新增新闻来源页或事件样本登记，必须先补来源追溯再扩展规则页。
