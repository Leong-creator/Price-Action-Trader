---
title: Signal Bar Entry Placeholder (M1 Sample)
type: setup
status: draft
confidence: low
market: ["US", "HK"]
timeframes: ["5m", "15m", "1h"]
direction: both
source_refs: ["raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf"]
applicability: ["用于 M1 校验 setup 页 frontmatter、索引字段和后续资料抽取流程"]
not_applicable: ["未完成原始资料抽取前，不用于自动信号、回测或执行"]
contradictions: []
missing_visuals: ["缺少原始图表截图与逐页转录定位"]
open_questions: ["需要确认 signal bar 形态要求、entry trigger、stop rule、target rule 和 invalidation"]
tags: ["m1-sample", "setup", "signal-bar", "entry"]
pa_context: ["待从原始笔记确认趋势或震荡下的适用上下文"]
market_cycle: ["pending-source-confirmation"]
higher_timeframe_context: ["待确认 higher timeframe 方向一致性与过滤条件"]
bar_by_bar_notes: ["当前仅建立结构化占位，不补写未经核验的逐K细节"]
signal_bar: ["待确认 signal bar 的实体、尾部、收盘位置与前置背景要求"]
entry_trigger: ["待确认 entry trigger；当前只保留结构字段供后续抽取"]
entry_bar: ["待确认"]
stop_rule: ["待确认保护性止损位置与无效化处理"]
target_rule: ["待确认初始目标、measured move 或分批出场规则"]
trade_management: ["待确认移动止损、保本或分批管理要求"]
measured_move: false
invalidation: ["待确认 setup 失效条件与取消触发情形"]
risk_reward_min:
last_reviewed: 2026-04-17
---

# Signal Bar Entry Placeholder

本页是 M1 的最小代表性 `setup` 样例页，用于让 `validate_kb.py` 和 `build_kb_index.py` 覆盖 setup 类 frontmatter。

## 当前可确认范围

- 原始来源是 `knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf`。
- 当前内容只建立结构化字段和待抽取事项，不把任何具体入场条件写成已验证规则。
- 本页后续应在原始资料抽取完成后补充 signal bar、entry、stop、target 和 invalidation 的准确定义。

## 待后续补充

- signal bar 的形态定义与前置 context。
- entry trigger 与 entry bar 的执行顺序。
- stop rule、target rule、trade management 和 minimum risk/reward 要求。
