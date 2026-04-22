# SF-003 Test Plan

- `provider`: `longbridge`
- `dataset_count`: `4`
- `symbols`: `SPY, QQQ, NVDA, TSLA`
- `coverage_window`: `2025-04-01 ~ 2026-04-21`
- `timeframe`: `5m`
- `variants`: `baseline`, `quality_filter`
- `sample gates`: probe>=60 trades with validation/OOS>=15; formal>=100 trades with validation/OOS>=20

## Data Requirements
- OHLCV with session labels
- range edge and failed follow-through detection

## Expected Failure Modes
- 把 broad channel continuation 误当 range reversal
- 在强 breakout 中过早逆势
