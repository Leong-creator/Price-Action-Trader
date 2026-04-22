# M9 Trading-Style Batch Report

- `run_id`: `m9_strategy_factory_batch_backtest_20260422_035151`
- `provider`: `longbridge`
- `symbols`: SPY, QQQ, NVDA, TSLA
- `coverage_window`: `2025-04-01 ~ 2026-04-21`
- `timeframe`: `5m`
- `capital_model`: `notional capital not modeled in this runner; all PnL is reported in R`
- `boundary`: `paper/simulated`

| Strategy | Baseline Trades | Baseline Win Rate | Baseline PnL | Baseline Max DD | Best Variant | Best Trades | Best Win Rate | Best PnL | Best Max DD | Sample Status | Triage |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- |
| SF-001 | 9164 | 0.3339 | 16.0000R | 234.0000R | quality_filter | 8037 | 0.3371 | 90.0000R | 145.0000R | robust_candidate | modify_and_retest |
| SF-002 | 1560 | 0.3391 | 27.0000R | 88.0000R | quality_filter | 988 | 0.3451 | 35.0000R | 50.0000R | robust_candidate | modify_and_retest |
| SF-003 | 1707 | 0.3193 | -72.0000R | 128.0000R | quality_filter | 1119 | 0.3262 | -24.0000R | 65.0000R | robust_candidate | modify_and_retest |
| SF-004 | 1198 | 0.3272 | -22.0000R | 80.0000R | quality_filter | 301 | 0.3289 | -4.0000R | 39.0000R | robust_candidate | modify_and_retest |
| SF-005 | 0 | - | - | - | - | 0 | - | - | - | not_run | deferred_single_source_risk |

## Notes
- 本报告按交易报告口径展示交易笔数、胜率、总盈亏与最大回撤，但当前 runner 仍使用 R 倍数口径，不输出美元本金权益曲线。
- 表中的 `quality_filter` 必须读作 `diagnostic_selected_variant`，只用于指示下一轮更窄的 `v0.2 spec freeze`，不是已验证正式策略。
- 若与现金口径同一策略出现正负号不一致，应以“cash layer 为独立 sizing 解释层”解读，不得把现金口径当成 R 结果的美元等价物。
- `robust_candidate` 仅表示样本覆盖更充分，不代表稳定盈利、实盘 readiness 或自动交易能力。
