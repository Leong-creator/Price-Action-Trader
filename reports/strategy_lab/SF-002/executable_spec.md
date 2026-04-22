# SF-002 Executable Spec

- `run_id`: `m9_strategy_factory_batch_backtest_20260422_035151`
- `setup_family`: `breakout_follow_through_continuation`
- `provider`: `longbridge`
- `dataset_count`: 4
- `dataset_paths`: `local_data/longbridge_intraday/us_SPY_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_QQQ_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_NVDA_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_TSLA_5m_2025-04-01_2026-04-21_longbridge.csv`
- `timeframe`: `5m`
- `boundary`: `paper/simulated`

## Entry
确认 breakout 后的 good follow-through，再用 market/stop order 顺势跟进。

## Stop
放在 breakout bar 或 follow-through cluster 的 opposite extreme 外侧。

## Target
优先看 measured move 与后续 second leg continuation。

## Invalidation
- breakout 后 follow-through 很差
- 出现 deep pullback 或 gap 被迅速回补

## No-Trade
- 突破没有急迫感或没有连续性
- 处于明显 trading range 且 follow-through 质量差

## Parameter Candidates
- minimum breakout bar body size
- follow-through bars within 2~3 bars
- gap persistence requirement

## Notes
- Research-only executable proxy for the controlled batch backtest wave.
