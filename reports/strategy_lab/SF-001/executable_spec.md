# SF-001 Executable Spec

- `run_id`: `m9_strategy_factory_batch_backtest_20260422_035151`
- `setup_family`: `trend_pullback_second_entry`
- `provider`: `longbridge`
- `dataset_count`: 4
- `dataset_paths`: `local_data/longbridge_intraday/us_SPY_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_QQQ_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_NVDA_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_TSLA_5m_2025-04-01_2026-04-21_longbridge.csv`
- `timeframe`: `5m`
- `boundary`: `paper/simulated`

## Entry
在顺势背景中等待 H1/H2/L1/L2 或 second-entry 触发，再用 buy/sell stop 跟进。

## Stop
放在 signal bar 或失败 second-entry 的 opposite extreme 外侧。

## Target
先看 1R~2R，若趋势与 channel 仍强则允许转成 swing。

## Invalidation
- 后续 follow-through 很差
- 出现 bull trap / bear trap 或关键低点/高点被反向突破

## No-Trade
- 背景不是顺势 pullback
- 在强趋势第一次反转就逆势抢反转

## Parameter Candidates
- pullback bar count <= 3
- signal bar quality >= close near extreme
- minimum R multiple >= 1.0

## Notes
- Research-only executable proxy for the controlled batch backtest wave.
