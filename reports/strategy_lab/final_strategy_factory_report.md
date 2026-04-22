# M9 Controlled Batch Backtest + Strategy Triage

- `run_id`: `m9_strategy_factory_batch_backtest_20260422_035151`
- `provider`: `longbridge`
- `dataset_path`: `local_data/longbridge_intraday/us_SPY_5m_2025-04-01_2026-04-21_longbridge.csv`
- `dataset_count`: 4
- `symbols`: SPY, QQQ, NVDA, TSLA
- `coverage_window`: `2025-04-01 ~ 2026-04-21`
- `frozen_strategy_count`: 5
- `eligible_strategy_count`: 4
- `tested_strategy_count`: 4
- `boundary`: `paper/simulated`
- `scope`: `exploratory multi-symbol intraday batch; not live / not real-money`

## Triage Counts
- `deferred_single_source_risk`: 1
- `modify_and_retest`: 4

## Eligibility
- `SF-001`: eligible_for_batch_backtest (frozen text-extractable family with multi-source corroboration)
- `SF-002`: eligible_for_batch_backtest (frozen text-extractable family with multi-source corroboration)
- `SF-003`: eligible_for_batch_backtest (frozen text-extractable family with multi-source corroboration)
- `SF-004`: eligible_for_batch_backtest (frozen text-extractable family with multi-source corroboration)
- `SF-005`: deferred_single_source_risk (single-source corroboration and coarse family boundary)

## Best Next Wave Candidates
- `SF-001`: modify_and_retest (`quality_filter` is a `diagnostic_selected_variant`; it improved on the baseline and should guide a narrower `v0.2 spec freeze`, not be treated as a validated production rule)
- `SF-002`: modify_and_retest (`quality_filter` is a `diagnostic_selected_variant`; it improved on the baseline and should guide a narrower `v0.2 spec freeze`, not be treated as a validated production rule)
- `SF-003`: modify_and_retest (`quality_filter` improved on the baseline but the best variant remains negative in R; cash-layer positivity is an independent sizing effect and does not justify promotion beyond `modify_and_retest`)
- `SF-004`: modify_and_retest (`quality_filter` improved on the baseline but the best variant remains negative in R; cash-layer positivity is an independent sizing effect and does not justify promotion beyond `modify_and_retest`)
- `SF-005`: deferred_single_source_risk (single-source corroboration and coarse family boundary)

## Integrity Notes
- `quality_filter` must be read as `diagnostic_selected_variant` across `SF-001 ~ SF-004`; it is not a formal frozen strategy version and not a validated default rule.
- The cash report is an independent sizing interpretation, not `R * $100`. `SF-003 baseline`, `SF-003 quality_filter`, and `SF-004 quality_filter` are negative in aggregate R but positive in cash because each closed trade is re-sized by `risk_per_share` and `entry_price`.
- After merge gate, the next step is `v0.2 spec freeze`, not automatic expansion into another batch backtest wave.
