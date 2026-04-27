# M10.6 Read-only Observation Recorded Replay

## Summary

- Recorded replay only.
- Uses local cached OHLCV input.
- The ledger validates input, schema, and bar-close observation flow.
- It does not prove strategy effectiveness.
- M11 paper gate remains closed.

## Counts

- event_count: `108640`
- candidate_event_count: `73619`
- skip_no_trade_count: `35021`
- deferred_input_count: `0`

## Strategy Timeframes

| strategy | timeframe | candidates | skips | deferred symbols | review status |
|---|---|---:|---:|---:|---|
| M10-PA-001 | 1d | 1518 | 36 | 0 | `continue_observation` |
| M10-PA-001 | 1h | 1011 | 19 | 0 | `continue_observation` |
| M10-PA-001 | 15m | 4331 | 166 | 0 | `continue_observation` |
| M10-PA-001 | 5m | 12452 | 472 | 0 | `continue_observation` |
| M10-PA-002 | 1d | 1196 | 1290 | 0 | `continue_observation` |
| M10-PA-002 | 1h | 814 | 818 | 0 | `continue_observation` |
| M10-PA-002 | 15m | 3534 | 3084 | 0 | `continue_observation` |
| M10-PA-002 | 5m | 10759 | 8862 | 0 | `continue_observation` |
| M10-PA-005 | 1d | 1481 | 1085 | 0 | `continue_observation` |
| M10-PA-005 | 1h | 1469 | 1120 | 0 | `needs_definition_fix` |
| M10-PA-005 | 15m | 7511 | 4721 | 0 | `needs_definition_fix` |
| M10-PA-005 | 5m | 23881 | 13348 | 0 | `needs_definition_fix` |
| M10-PA-012 | 15m | 1762 | 0 | 0 | `continue_observation` |
| M10-PA-012 | 5m | 1900 | 0 | 0 | `continue_observation` |
