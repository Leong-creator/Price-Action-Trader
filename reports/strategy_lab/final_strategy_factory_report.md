# M9 Controlled Batch Backtest + Strategy Triage

- `run_id`: `m9_strategy_factory_batch_backtest_20260421_175408`
- `provider`: `longbridge`
- `dataset_path`: `local_data/longbridge_intraday/us_SPY_5m_2026-02-20_2026-04-17_longbridge.csv`
- `frozen_strategy_count`: 5
- `eligible_strategy_count`: 4
- `tested_strategy_count`: 4
- `boundary`: `paper/simulated`
- `scope`: `exploratory single-symbol intraday batch; not live / not real-money`

## Triage Counts
- `deferred_single_source_risk`: 1
- `insufficient_sample`: 3
- `modify_and_retest`: 1

## Eligibility
- `SF-001`: eligible_for_batch_backtest (frozen text-extractable family with multi-source corroboration)
- `SF-002`: eligible_for_batch_backtest (frozen text-extractable family with multi-source corroboration)
- `SF-003`: eligible_for_batch_backtest (frozen text-extractable family with multi-source corroboration)
- `SF-004`: eligible_for_batch_backtest (frozen text-extractable family with multi-source corroboration)
- `SF-005`: deferred_single_source_risk (single-source corroboration and coarse family boundary)

## Best Next Wave Candidates
- `SF-001`: modify_and_retest (a stricter diagnostic variant materially outperformed the baseline and should guide the next exploratory spec freeze before any broader wave)
- `SF-002`: insufficient_sample (baseline trade count or split coverage did not clear the minimum probe gate)
- `SF-003`: insufficient_sample (baseline trade count or split coverage did not clear the minimum probe gate)
- `SF-004`: insufficient_sample (baseline trade count or split coverage did not clear the minimum probe gate)
- `SF-005`: deferred_single_source_risk (single-source corroboration and coarse family boundary)

