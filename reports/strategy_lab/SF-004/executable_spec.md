# SF-004 Executable Spec

- `run_id`: `m9_strategy_factory_batch_backtest_20260422_035151`
- `setup_family`: `tight_channel_trend_continuation`
- `provider`: `longbridge`
- `dataset_count`: 4
- `dataset_paths`: `local_data/longbridge_intraday/us_SPY_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_QQQ_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_NVDA_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_TSLA_5m_2025-04-01_2026-04-21_longbridge.csv`
- `timeframe`: `5m`
- `boundary`: `paper/simulated`

## Entry
在 Tight Channel / Always In 背景中只顺势做，等待微回调或 signal bar 后继续跟随。

## Stop
放在最近短回调极值之外；若 channel 重叠明显增加则失效。

## Target
以前高/前低、measured move 或 trend day extension 为主。

## Invalidation
- channel 退化成 broad channel / trading range
- 出现清晰的二次反转并伴随强 follow-through

## No-Trade
- 在强窄通道里逆势数 wedge 或抢第一次反转
- 回调 bar 数和重叠度已经明显失去 tight-channel 特征

## Parameter Candidates
- max pullback bars <= 3
- channel overlap threshold
- trend day session filter

## Notes
- Research-only executable proxy for the controlled batch backtest wave.
