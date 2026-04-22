# SF-005 Executable Spec

- `run_id`: `m9_strategy_factory_batch_backtest_20260422_035151`
- `setup_family`: `gap_continuation_exhaustion`
- `provider`: `longbridge`
- `dataset_count`: 4
- `dataset_paths`: `local_data/longbridge_intraday/us_SPY_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_QQQ_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_NVDA_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_TSLA_5m_2025-04-01_2026-04-21_longbridge.csv`
- `timeframe`: `5m`
- `boundary`: `paper/simulated`

## Entry
先判断 gap 是 breakout / measuring 还是 exhaustion，再决定顺势 continuation 或 gap fill reversal。

## Stop
顺势单放在 gap base 外侧，exhaustion/filled-gap 单放在 gap recovery failure 外侧。

## Target
breakout / measuring gap 看 measured move；exhaustion gap 先看回补与进入 TR。

## Invalidation
- gap 被迅速回补且 follow-through 失败
- 本应 exhaustion 的 gap 反而保持连续 trend bars

## No-Trade
- gap 类型无法区分
- 只看到 gap 但没有 trend / TR 背景

## Parameter Candidates
- gap type classification
- EMA / prior high-low gap persistence
- measured-move target anchor

## Notes
- Research-only executable proxy for the controlled batch backtest wave.
