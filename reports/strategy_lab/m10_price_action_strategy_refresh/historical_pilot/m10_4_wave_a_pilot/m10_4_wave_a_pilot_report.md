# M10.4 Wave A Historical Backtest Pilot

## Summary

- This pilot validates M10.3 executable specs and output plumbing.
- It remains paper / simulated only.
- It does not prove profitability and does not allow retain/promote/live conclusions.

## Results

| strategy | timeframe | candidates | trades | sample gate | outcome |
|---|---|---:|---:|---|---|
| M10-PA-001 | 1d | 1518 | 1518 | pass | `continue_testing` |
| M10-PA-001 | 1h | 1011 | 1011 | pass | `continue_testing` |
| M10-PA-001 | 15m | 4331 | 4331 | pass | `continue_testing` |
| M10-PA-001 | 5m | 12452 | 12452 | pass | `continue_testing` |
| M10-PA-002 | 1d | 1196 | 1196 | pass | `continue_testing` |
| M10-PA-002 | 1h | 814 | 814 | pass | `continue_testing` |
| M10-PA-002 | 15m | 3534 | 3534 | pass | `continue_testing` |
| M10-PA-002 | 5m | 10759 | 10759 | pass | `continue_testing` |
| M10-PA-005 | 1d | 1481 | 1481 | pass | `continue_testing` |
| M10-PA-005 | 1h | 1469 | 1469 | pass | `continue_testing` |
| M10-PA-005 | 15m | 7511 | 7511 | pass | `continue_testing` |
| M10-PA-005 | 5m | 23881 | 23881 | pass | `continue_testing` |
| M10-PA-012 | 15m | 1762 | 1762 | pass | `continue_testing` |
| M10-PA-012 | 5m | 1900 | 1900 | pass | `continue_testing` |

## Boundary

- No broker connection.
- No real account.
- No live execution.
- No real orders.
