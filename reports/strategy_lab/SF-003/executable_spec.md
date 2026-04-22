# SF-003 Executable Spec

- `run_id`: `m9_strategy_factory_batch_backtest_20260422_035151`
- `setup_family`: `failed_breakout_range_reversal`
- `provider`: `longbridge`
- `dataset_count`: 4
- `dataset_paths`: `local_data/longbridge_intraday/us_SPY_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_QQQ_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_NVDA_5m_2025-04-01_2026-04-21_longbridge.csv, local_data/longbridge_intraday/us_TSLA_5m_2025-04-01_2026-04-21_longbridge.csv`
- `timeframe`: `5m`
- `boundary`: `paper/simulated`

## Entry
在区间边缘或第二段 trap 明确失败后，等反转 signal 再逆势进场。

## Stop
放在 failed breakout extreme 之外，若重新获得连续 follow-through 则失效。

## Target
先看回到 TR 中轴或 opposite edge，再视 broad channel 结构决定是否延伸。

## Invalidation
- breakout 重新得到连续 follow-through
- 区间结构被 surprise bar 直接改写

## No-Trade
- 仍在 Always In 强趋势的第一次反转里抢顶/抢底
- 没有足够 range context 就把单根 reversal bar 当失败突破

## Parameter Candidates
- range edge proximity
- second leg trap confirmation
- follow-through failure within 2 bars

## Notes
- Research-only executable proxy for the controlled batch backtest wave.
