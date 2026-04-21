---
title: Strategy Factory Index
type: source
status: draft
confidence: medium
market: ["US"]
timeframes: ["5m", "15m", "1d"]
direction: neutral
source_refs: ["internal/strategy-factory-index", "internal/source-manifest", "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md"]
tags: ["strategy-factory", "m9g", "research-only", "contract-freeze"]
applicability: ["用于汇总 M9G Strategy Factory 的目录、contract 与当前运行台账"]
not_applicable: ["不构成可执行交易规则", "不直接驱动 trigger 或模拟执行"]
contradictions: []
missing_visuals: []
open_questions: ["何时开始首轮 SF-* clustering，取决于 M9G.1 coverage ledger 完成情况"]
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
last_reviewed: 2026-04-21
---

# Strategy Factory Index

`knowledge/wiki/strategy_factory/` 是 `M9G` 之后的新 catalog 根目录。

## 当前边界

- 新 catalog 只使用 `SF-*` 编号。
- 新提炼只从 `knowledge/indices/source_manifest.json` 与相关台账重新开始。
- 旧 `knowledge/wiki/strategy_cards/` 目录只作为 legacy / historical baseline。
- 当前冻结结果与人读卡片落在 `reports/strategy_lab/cards/` 与 `reports/strategy_lab/specs/`，而不是回退到 legacy `PA-SC-*` 目录。

## 当前目录

- `strategies/`
- `specs/`
- `test_plans/`

## 当前参考

- provider contract: [docs/strategy-factory.md](/home/hgl/projects/Price-Action-Trader/docs/strategy-factory.md)
- plan report: [strategy_factory_plan.md](/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/strategy_factory_plan.md)
- coverage ledger: [coverage_ledger.json](/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/strategy_factory/coverage_ledger.json)
- run state: [run_state.json](/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/strategy_factory/run_state.json)
- audit summary: [factory_summary.md](/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/factory_summary.md)
- frozen catalog: [strategy_catalog.json](/home/hgl/projects/Price-Action-Trader/reports/strategy_lab/strategy_catalog.json)
