# M10.13 Read-only Observation Runbook

## 摘要

- 本文件是后续只读观察的执行手册，本阶段不启动真实观察。
- broker connection、real account、live execution、real orders 和 paper trading approval 继续关闭。
- 主观察队列只纳入已完成资金测试、整体收益为正、且分周期筛选为正的策略周期。
- M10.13 在 M10.5 的 Wave A 观察计划基础上，允许 M10.11/M10.12 筛选通过的 Wave B 策略进入观察队列；视觉策略必须保留人工图形语境复核。

## 主观察队列

| Strategy | Timeframes | Symbols | Review Notes |
|---|---|---|---|
| M10-PA-001 | `1d / 15m / 5m` | `SPY / QQQ / NVDA / TSLA` | 常规人工复核 |
| M10-PA-002 | `1d / 1h / 15m` | `SPY / QQQ / NVDA / TSLA` | 常规人工复核 |
| M10-PA-012 | `15m / 5m` | `SPY / QQQ / NVDA / TSLA` | 常规人工复核 |
| M10-PA-008 | `1h / 15m / 5m` | `SPY / QQQ / NVDA / TSLA` | 需要人工图形语境复核 |
| M10-PA-009 | `1h / 15m` | `SPY / QQQ / NVDA / TSLA` | 需要人工图形语境复核 |

## Reserve Timeframes

| Strategy | Reserve Timeframes | Reason |
|---|---|---|
| M10-PA-001 | `1h` | timeframe historical return is not positive |
| M10-PA-002 | `5m` | timeframe historical return is not positive |
| M10-PA-008 | `1d` | timeframe historical return is not positive |
| M10-PA-009 | `1d / 5m` | timeframe historical return is not positive |

## 观察节奏

- `1d`：只在 regular session 收盘后观察。
- `1h / 15m / 5m`：只在 regular-session bar close 后观察。
- 每周在人工复核完成后生成一次周报。

## 暂停条件

| Code | Trigger | Action |
|---|---|---|
| queue_contract_violation | strategy/timeframe is outside the M10.13 queue contract or contains a legacy id | reject the event artifact and fix queue generation before continuing |
| schema_or_ref_failure | observation event schema fails or source_refs/spec_ref/bar_timestamp is missing | pause affected queue item and repair event writer before review |
| lineage_or_timing_drift | 15m/1h lineage is not derived_from_5m, or 1d event is not after close | pause affected timeframe and correct input lineage/timing |
| input_missing_or_lineage_unknown | required OHLCV cache, feed, or lineage is missing | pause observation for affected strategy/timeframe and write deferred input note |
| deferred_input_streak | same strategy/timeframe has deferred inputs for two consecutive weekly cycles | remove from active weekly review until data input is restored |
| definition_density_drift | weekly event density exceeds 2x M10.12 baseline or crosses 100 events per 1000 bars | pause affected strategy/timeframe for definition review |
| review_status_regression | review status regresses to needs_definition_fix, needs_visual_review, or reject_for_now | move item out of active observation until manual review is closed |
| equity_curve_deviation | hypothetical observation drawdown exceeds 1.25x corresponding M10.12 historical max drawdown | pause new observations and require manual review |
| manual_review_backlog | unreviewed observation events remain open for more than one weekly cycle | pause expansion and clear review backlog first |
| visual_context_unresolved | visual-review strategy has ambiguous chart context | keep event as needs_visual_review and do not include it in paper gate evidence |
| live_or_broker_request | any workflow requires broker connection, live feed subscription, real account, or real order | stop M10.13 path and require explicit user approval |

## 排除说明

- `M10-PA-005` 在 range-geometry 定义修正完成前不进入主观察队列。
- supporting 和 research-only 条目不作为独立观察触发器。
- 整体资金测试为负的策略只保留在 watchlist/deferred，不进入主观察队列。
