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
- `SF-001`: modify_and_retest (a stricter diagnostic variant materially outperformed the baseline and should guide the next exploratory spec freeze before any broader wave)
- `SF-002`: modify_and_retest (a stricter diagnostic variant materially outperformed the baseline and should guide the next exploratory spec freeze before any broader wave)
- `SF-003`: modify_and_retest (a stricter diagnostic variant materially outperformed the baseline and should guide the next exploratory spec freeze before any broader wave)
- `SF-004`: modify_and_retest (a stricter diagnostic variant materially outperformed the baseline and should guide the next exploratory spec freeze before any broader wave)
- `SF-005`: deferred_single_source_risk (single-source corroboration and coarse family boundary)

