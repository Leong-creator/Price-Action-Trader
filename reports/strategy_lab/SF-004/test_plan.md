# SF-004 Test Plan

- `provider`: `longbridge`
- `dataset_path`: `local_data/longbridge_intraday/us_SPY_5m_2026-02-20_2026-04-17_longbridge.csv`
- `timeframe`: `5m`
- `variants`: `baseline`, `quality_filter`
- `sample gates`: probe>=60 trades with validation/OOS>=15; formal>=100 trades with validation/OOS>=20

## Data Requirements
- OHLCV with session labels
- channel overlap and pullback depth stats

## Expected Failure Modes
- 把 weak channel 误当 tight channel
- 进入 broad channel 后仍按 Always In 持有
