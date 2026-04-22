# SF-005 Test Plan

- `provider`: `longbridge`
- `dataset_count`: `4`
- `symbols`: `SPY, QQQ, NVDA, TSLA`
- `coverage_window`: `2025-04-01 ~ 2026-04-21`
- `timeframe`: `5m`
- `variants`: `baseline`, `quality_filter`
- `sample gates`: probe>=60 trades with validation/OOS>=15; formal>=100 trades with validation/OOS>=20

## Data Requirements
- OHLCV with gap/overlap detection
- prior-session anchors

## Expected Failure Modes
- 把 exhaustion gap 误当 continuation
- 只看 gap 不看 trend context
