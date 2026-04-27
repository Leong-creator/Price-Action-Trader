# M10.7 Business Metric Policy

## Summary

- M10.7 freezes the client-facing metric policy for the next capital backtest reports.
- The next reports must show strategy results in capital terms, not only R-value ledgers.
- Default account capital is `100,000 USD`.
- Default risk per trade is `0.5%` of current equity.
- Every strategy/timeframe/symbol is tested as an independent simulated account before portfolio aggregation.
- This stage does not approve paper trading, broker connection, real account access, or real orders.

## Capital Model

| Item | Policy |
|---|---:|
| Currency | `USD` |
| Initial capital | `100,000.00` |
| Risk per trade | `0.5%` of current equity |
| Max notional exposure per trade | `100%` of current equity |
| Leverage | Disabled |
| Fractional shares | Enabled for deterministic simulation |
| Commission | `0.00` |
| Cost tiers | `1 / 2 / 5 bps` |

Position size is calculated from stop distance:

`quantity = min((equity * 0.005) / abs(entry - stop), equity / entry)`

Trades with missing prices, invalid stop distance, invalid entry price, or zero quantity after caps must be skipped and written to the trade ledger with a skip reason.

## Required Client Metrics

Every capital test report must include:

- Initial capital
- Final equity
- Net profit
- Return percent
- Trade count
- Win rate
- Profit factor
- Max drawdown
- Max drawdown percent
- Max consecutive losses
- Average win
- Average loss
- Average holding bars
- Best/worst symbol
- Best/worst timeframe

## Reporting Grain

M10.8 and later reports must provide metrics at these levels:

- Strategy
- Strategy + timeframe
- Strategy + timeframe + symbol
- Cost tier

## Boundaries

- Results may show simulated capital gains or losses.
- Results must not be described as strategy promotion, paper trading approval, real execution readiness, or investment advice.
- `M10-PA-014` and `M10-PA-015` remain supporting rules, not standalone entry triggers.
- `M10-PA-006` and `M10-PA-016` remain research-only unless a later stage explicitly changes their status.
- Real broker, real account, live feed, and real order integration remain out of scope.
