---
title: Signal Bar Entry Placeholder
type: setup
status: draft
confidence: low
market: ["US", "HK"]
timeframes: ["5m", "15m", "1h"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md", "raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf", "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md"]
applicability: ["用于 research-only 的 signal bar / entry explanation、traceability 和回测解释摘要", "用于 M8 最小 curated promotion，不作为自动信号或执行规则"]
not_applicable: ["未完成字段级抽取前，不用于自动信号、回测优化或执行", "不作为已验证的 signal bar entry 规则"]
contradictions: []
missing_visuals: ["缺少原始图表截图与逐页转录定位"]
open_questions: ["多空两侧 signal bar 的严格阈值仍未冻结，当前只保留最小 evidence-backed 解释", "entry trigger 与 invalidation 的精确量化阈值仍需后续补齐"]
tags: ["setup", "signal-bar", "entry", "research-only", "curated-promotion-minimal-set"]
pa_context: ["trend", "trading-range"]
market_cycle: ["pending-source-confirmation"]
higher_timeframe_context: ["待确认 higher timeframe 方向一致性与过滤条件"]
bar_by_bar_notes: ["当前只补最小 evidence-backed 解释，不把 setup 写成可执行规则"]
signal_bar: ["当前只确认 signal bar 需要方向性、上下文与质量约束，不把任意 reversal bar 升格成 setup"]
entry_trigger: ["当前只确认 close-adjacent / breakout-adjacent 的最小 entry 语义，不引入新的自动执行逻辑"]
entry_bar: ["待确认"]
stop_rule: ["待确认保护性止损位置与无效化处理"]
target_rule: ["待确认初始目标、measured move 或分批出场规则"]
trade_management: ["待确认移动止损、保本或分批管理要求"]
measured_move: false
invalidation: ["若 signal bar 的方向性与背景不一致，应优先保守解释为 wait / no-trade"]
risk_reward_min:
last_reviewed: 2026-04-18
---

# Signal Bar Entry Placeholder

本页仍是 `research-only placeholder setup`，但当前已补上最小的 evidence-backed curated promotion：它不再只依赖标题占位，而是明确记录哪些 signal bar / entry 解释来自 FangFangTu 笔记与 Brooks PPT。

## 当前最小可确认范围

- signal bar 不能脱离背景单独解释。
- 在下降趋势中，带长下影线的 bar 不是天然的做多 signal bar；需要先区分“下降中的反弹”与真正的反转背景。
- entry 仍是 placeholder，但当前可确认“靠近 prior close / 方向性收盘”的最小 entry 语义，只能用于 explanation，不得直接升级为 executable trigger。

## Evidence-backed Promotion Notes

- 见 `knowledge/indices/curated_promotion_map.json` 中的 `signal_bar_entry_minimal`。
- 当前 promotion 只确认：
  - `signal_bar`：signal bar 需要好背景，不能把任意 reversal-looking bar 直接当成可执行 setup。
  - `entry_trigger`：当前只保留 close-adjacent / directional close 的最小解释，不增加新的自动入场条件。
  - `invalidation`：若 signal bar 与背景不一致，应优先降级为 `wait / no-trade` 的解释，而不是硬给方向。

## Research-only Boundaries

- 本页仍不构成自动 signal 规则。
- 多空两侧的精细阈值、stop/target、trade management 仍未冻结。
- 若 FangFangTu 与 Brooks 对具体 signal bar 质量判断存在边界差异，必须先保留为 `open_question`，不得强行合并。
