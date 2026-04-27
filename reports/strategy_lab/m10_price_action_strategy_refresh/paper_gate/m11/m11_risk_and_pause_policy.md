# M11 Risk And Pause Policy

## Status

- policy status: `draft_for_future_paper_only_not_active`
- paper trading approval: `false`
- broker connection: `false`
- real orders: `false`
- live execution: `false`

## 后续如获批准才可使用的资金口径

- currency: `USD`
- initial_capital: `100000.00`
- risk_per_trade_percent_of_equity: `0.50`
- max_simultaneous_risk_percent: `4.00`
- max_simultaneous_positions: `8`
- leverage_allowed: `false`
- real_orders_allowed: `false`

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
| paper_gate_without_observation_results | paper trading is requested before a completed read-only observation review window exists | deny paper gate and continue read-only observation planning |
| manual_approval_missing | human business approval is missing | deny paper gate |
| candidate_status_downgrade | candidate strategy is downgraded to needs_definition_fix, needs_visual_review, or reject_for_now | remove from candidate list until fixed and re-reviewed |

## 边界

本策略不是交易许可。任何 paper trading 或 broker setup 都需要单独明确审批。
