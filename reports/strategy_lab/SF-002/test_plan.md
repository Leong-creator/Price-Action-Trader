# SF-002 Test Plan

- `provider`: `longbridge`
- `dataset_count`: `4`
- `symbols`: `SPY, QQQ, NVDA, TSLA`
- `coverage_window`: `2025-04-01 ~ 2026-04-21`
- `timeframe`: `5m`
- `variants`: `baseline`, `quality_filter`
- `sample gates`: probe>=60 trades with validation/OOS>=15; formal>=100 trades with validation/OOS>=20

## Data Requirements
- OHLCV with session labels
- gap detection based on bar overlap

## Expected Failure Modes
- TR 内追 breakout 被 80-20 假突破打回
- 把 weak breakout 误判成 strong breakout
