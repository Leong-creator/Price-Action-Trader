# M10.8 Wave A Client Report

## Executive Summary

- Coverage: `M10-PA-001`, `M10-PA-002`, `M10-PA-005`, `M10-PA-012`.
- Symbols: `SPY / QQQ / NVDA / TSLA`.
- Account model: `100,000 USD` per independent strategy/timeframe/symbol account, `0.5%` risk per trade.
- This report shows historical simulation results only.
- Best baseline strategy by net profit: `M10-PA-001` (395723.86 USD).
- Weakest baseline strategy by net profit: `M10-PA-005` (-147665.89 USD).

## Strategy-Timeframe Baseline Results

| Strategy | Timeframe | Accounts | Final Equity | Net Profit | Return % | Trades | Win Rate | Max Drawdown | Status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| M10-PA-001 | 15m | 4 | 549589.13 | 149589.13 | 37.3973 | 4331 | 0.3653 | 174805.43 | completed_capital_test |
| M10-PA-001 | 1d | 4 | 500652.36 | 100652.36 | 25.1631 | 1518 | 0.3768 | 73595.14 | completed_capital_test |
| M10-PA-001 | 1h | 4 | 382041.63 | -17958.37 | -4.4896 | 1011 | 0.3274 | 83464.77 | completed_capital_test |
| M10-PA-001 | 5m | 4 | 563440.74 | 163440.74 | 40.8602 | 12452 | 0.3562 | 214986.75 | completed_capital_test |
| M10-PA-002 | 15m | 4 | 468993.75 | 68993.75 | 17.2484 | 3534 | 0.3645 | 85620.49 | completed_capital_test |
| M10-PA-002 | 1d | 4 | 430154.40 | 30154.40 | 7.5386 | 1196 | 0.3537 | 50092.68 | completed_capital_test |
| M10-PA-002 | 1h | 4 | 412534.72 | 12534.72 | 3.1337 | 814 | 0.3587 | 56948.30 | completed_capital_test |
| M10-PA-002 | 5m | 4 | 340813.41 | -59186.59 | -14.7966 | 10759 | 0.3430 | 184285.41 | completed_capital_test |
| M10-PA-005 | 15m | 4 | 450820.21 | 50820.21 | 12.7051 | 7511 | 0.3474 | 113914.37 | needs_definition_fix |
| M10-PA-005 | 1d | 4 | 365869.04 | -34130.96 | -8.5327 | 1481 | 0.3201 | 85559.02 | completed_capital_test |
| M10-PA-005 | 1h | 4 | 399386.91 | -613.09 | -0.1533 | 1469 | 0.3302 | 60231.57 | needs_definition_fix |
| M10-PA-005 | 5m | 4 | 236257.95 | -163742.05 | -40.9355 | 23881 | 0.3397 | 257549.22 | needs_definition_fix |
| M10-PA-012 | 15m | 4 | 493195.55 | 93195.55 | 23.2989 | 1762 | 0.3768 | 48665.45 | completed_capital_test |
| M10-PA-012 | 5m | 4 | 521945.74 | 121945.74 | 30.4864 | 1900 | 0.3858 | 53266.22 | completed_capital_test |

## Delivery Files

- `m10_8_wave_a_metrics.csv`: metrics by strategy, timeframe, symbol, and cost tier.
- `m10_8_wave_a_trade_ledger.csv`: trade-level simulated capital ledger.
- `m10_8_wave_a_equity_curves/`: baseline equity curve CSV/SVG attachments.

## Boundary

No broker, real account, automatic execution, or real order path is enabled by this report.
