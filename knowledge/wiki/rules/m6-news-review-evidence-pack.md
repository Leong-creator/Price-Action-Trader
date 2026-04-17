---
title: M6 News Review Evidence Pack
type: rule
status: draft
confidence: low
market: ["US", "HK"]
timeframes: ["5m", "15m", "1h", "multi-timeframe"]
direction: neutral
source_refs: ["wiki:knowledge/wiki/concepts/market-cycle-overview.md", "wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md", "wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md", "wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md"]
tags: ["m6", "news", "review", "evidence-pack", "research-only"]
applicability: ["仅供 M6 新闻过滤与复盘整合提供最小知识引用边界", "仅供 review evidence、source_refs 追溯和风险提示说明"]
not_applicable: ["不构成主信号源", "不构成订单触发条件", "不构成已验证的新闻交易规则", "不直接驱动模拟执行或实盘决策"]
contradictions: []
missing_visuals: ["缺少新闻事件时间线示意图", "缺少复盘引用示例截图", "缺少原始资料逐页截图与定位"]
open_questions: ["需要补充 M6 将引用的新闻来源页或原始事件样本登记页", "需要确认高风险新闻与仅解释性新闻的边界条件", "需要确认 review evidence 中 news impact 的标准化标签集合"]
pa_context: ["trend", "trading-range", "transition"]
market_cycle: ["pending-source-confirmation"]
higher_timeframe_context: ["沿用 market-cycle-overview 的 research-only 占位，不在本页新增事实"]
bar_by_bar_notes: ["本页不新增逐K事实，只整理 M6 的引用边界与复盘约束"]
signal_bar: ["signal-bar-entry-placeholder"]
entry_trigger: ["新闻在 M6 中只作 filter / explanation / risk hint，不新增 entry trigger"]
entry_bar: ["沿用 signal-bar-entry-placeholder 的 research-only 占位，不在本页补写执行细节"]
stop_rule: ["新闻不定义 stop rule；如需风控约束，应由 M5 risk/execution 与后续 M6 review 输出承接"]
target_rule: ["新闻不定义 target rule；本页只约束复盘中的新闻角色边界"]
trade_management: ["新闻仅补充风险提示与解释，不新增交易管理规则"]
measured_move: false
invalidation: ["若将新闻影响直接写成主信号、订单触发或已验证规则，则超出本 evidence pack 适用范围"]
risk_reward_min:
last_reviewed: 2026-04-17
---

# M6 News Review Evidence Pack

本页为 M6 提供最小知识引用包，目标是把现有 wiki/source 页面整理成可追溯、低置信度、research-only 的 review evidence。

## Boundary

- 新闻在 M6 中只允许作为 `filter`、`explanation` 或 `risk hint`。
- 新闻不能升级为主信号源，不能直接定义 entry、stop、target 或订单动作。
- 本页不新增 raw 层事实，只复用当前已存在的 concept、setup、source 页面。

## Evidence Links

- `knowledge/wiki/concepts/market-cycle-overview.md`
  - 提供可引用的 `pa_context` 占位与 market cycle research-only 上下文。
- `knowledge/wiki/setups/signal-bar-entry-placeholder.md`
  - 提供 signal / entry 结构字段边界，提醒 M6 不得把新闻改写为 setup trigger。
- `knowledge/wiki/sources/fangfangtu-market-cycle-note.md`
  - 提供 market cycle 相关来源登记与追溯入口。
- `knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md`
  - 提供 signal bar / entry 相关来源登记与追溯入口。

## Structured Review Constraints

```yaml
evidence_pack_id: m6-news-review-evidence-pack-v1
research_only: true
confidence: low
news_role:
  allowed:
    - filter
    - explanation
    - risk_hint
  disallowed:
    - primary_signal
    - order_trigger
    - execution_instruction
review_traceability:
  required_links:
    - signal.source_refs
    - knowledge/wiki/concepts/market-cycle-overview.md
    - knowledge/wiki/setups/signal-bar-entry-placeholder.md
  optional_links:
    - knowledge/wiki/sources/fangfangtu-market-cycle-note.md
    - knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md
supported_review_fields:
  - source_refs
  - pa_context
  - explanation
  - risk_notes
  - entry_trigger
  - stop_rule
  - target_rule
  - invalidation
constraints:
  - do_not_promote_news_to_signal
  - do_not_replace_existing_setup_reference
  - do_not_add_unverified_news_facts
open_gaps:
  - missing_news_source_page
  - missing_event_severity_thresholds
  - missing_standardized_news_impact_labels
```

## Usage Notes For M6

- 当 M6 复盘整合引用新闻影响时，必须保留现有 `source_refs` 链路，并同时指出新闻只是辅助因子。
- 当新闻仅用于解释或风险提示时，不应覆盖既有 `pa_context`、`setup_type` 或 `entry_trigger` 的 research-only 占位。
- 若后续需要纳入新的新闻来源或事件样本，应先补来源登记页，再回填本 evidence pack；在此之前用 `open_questions` 标明缺口。
