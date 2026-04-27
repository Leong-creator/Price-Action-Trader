# M10.13 Weekly Observation Template

## Week

- week range:
- reviewer:
- data source and lineage notes:

## 本周触发策略

| Strategy | Symbol | Timeframe | Candidate Events | Skip/No-trade | Manual Review Status |
|---|---|---:|---:|---:|---|

## 历史基线指标

| Strategy | Timeframe | Initial Capital | Final Equity | Net Profit | Return % | Trade Count | Win Rate | Profit Factor | Max Drawdown | Max Consecutive Losses | Average Holding Bars |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

## 观察质量指标

| Strategy | Timeframe | Observed Bars | Candidate Events | Skip/No-trade | Deferred Inputs | Schema Pass Rate | Source/Spec Ref Completeness | Review Status | Quality Flag | Lineage | Week-over-week Status |
|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|

## 策略和标的分布

| Strategy | Symbols Seen | Timeframes Seen | Notes |
|---|---|---|---|

## 资金曲线偏离

| Strategy | Historical Baseline Ref | Observation Equity Proxy | Deviation | Action |
|---|---:|---:|---:|---|

## 暂停条件

| Condition | Hit? | Evidence | Action |
|---|---|---|---|
| queue_contract_violation |  |  | reject the event artifact and fix queue generation before continuing |
| schema_or_ref_failure |  |  | pause affected queue item and repair event writer before review |
| lineage_or_timing_drift |  |  | pause affected timeframe and correct input lineage/timing |
| input_missing_or_lineage_unknown |  |  | pause observation for affected strategy/timeframe and write deferred input note |
| deferred_input_streak |  |  | remove from active weekly review until data input is restored |
| definition_density_drift |  |  | pause affected strategy/timeframe for definition review |
| review_status_regression |  |  | move item out of active observation until manual review is closed |
| equity_curve_deviation |  |  | pause new observations and require manual review |
| manual_review_backlog |  |  | pause expansion and clear review backlog first |
| visual_context_unresolved |  |  | keep event as needs_visual_review and do not include it in paper gate evidence |
| live_or_broker_request |  |  | stop M10.13 path and require explicit user approval |

## 人工复核结论

- continue_observation:
- needs_definition_fix:
- needs_visual_review:
- reject_for_now:

## 边界

本周报模板不批准 paper trading、broker connection、live execution 或 real orders。
