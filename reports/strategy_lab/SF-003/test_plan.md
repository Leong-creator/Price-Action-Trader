# SF-003 Test Plan

- `provider`: `longbridge`
- `dataset_path`: `local_data/longbridge_intraday/us_SPY_5m_2026-02-20_2026-04-17_longbridge.csv`
- `timeframe`: `5m`
- `variants`: `baseline`, `quality_filter`
- `sample gates`: probe>=60 trades with validation/OOS>=15; formal>=100 trades with validation/OOS>=20

## Data Requirements
- OHLCV with session labels
- range edge and failed follow-through detection

## Expected Failure Modes
- 把 broad channel continuation 误当 range reversal
- 在强 breakout 中过早逆势
