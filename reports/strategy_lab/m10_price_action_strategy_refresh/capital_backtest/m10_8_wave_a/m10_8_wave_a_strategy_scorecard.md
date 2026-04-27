# M10.8 Wave A Strategy Scorecard

## Summary

- This report converts M10.4 Wave A candidate events into simulated capital metrics.
- Default model: `100,000 USD` per independent strategy/timeframe/symbol account, `0.5%` risk per trade.
- This is a historical simulation report, not paper trading approval, broker integration, or real order readiness.

## Baseline Strategy Results

| Strategy | Accounts | Final Equity | Net Profit | Return % | Trades | Win Rate | Profit Factor | Max Drawdown | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| M10-PA-001 | 16 | 1995723.86 | 395723.86 | 24.7327 | 19312 | 0.3584 | 1.0580 | 546852.09 | completed_capital_test |
| M10-PA-002 | 16 | 1652496.28 | 52496.28 | 3.2810 | 16303 | 0.3492 | 1.0144 | 376946.88 | completed_capital_test |
| M10-PA-005 | 16 | 1452334.11 | -147665.89 | -9.2291 | 34342 | 0.3401 | 0.9761 | 517254.18 | needs_definition_fix |
| M10-PA-012 | 8 | 1015141.29 | 215141.29 | 26.8927 | 3662 | 0.3815 | 1.1674 | 101931.67 | completed_capital_test |

## Notes

- `M10-PA-005` on `1h / 15m / 5m` keeps `definition_breadth_review`; capital results must not override that status.
- Full detail is in `m10_8_wave_a_metrics.csv` and `m10_8_wave_a_trade_ledger.csv`.
