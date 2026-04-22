# SF-001 Test Plan

- `provider`: `longbridge`
- `dataset_count`: `4`
- `symbols`: `SPY, QQQ, NVDA, TSLA`
- `coverage_window`: `2025-04-01 ~ 2026-04-21`
- `timeframe`: `5m`
- `variants`: `baseline`, `quality_filter`
- `sample gates`: probe>=60 trades with validation/OOS>=15; formal>=100 trades with validation/OOS>=20

## Data Requirements
- OHLCV with session labels
- bar-level high/low for stop placement

## Expected Failure Modes
- 把 broad channel 误当 tight trend
- 在 MM 附近或 climax 后继续追价
