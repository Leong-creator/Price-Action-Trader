# M10-PA-005 1h Failure Mode Notes

- candidate_event_count: `1469`
- executed_trade_count: `1469`
- outcome: `continue_testing`
- This is a paper/simulated pilot artifact, not a profitability claim.

## Skip Counts

- `m10_005_breakout_not_failed`: 1120

## Notes

- If event counts are low, prefer `needs_definition_fix` or `continue_testing` rather than interpreting performance.
- If OHLCV approximation misses source context, route to `needs_visual_review`.
- `retain/promote/live` conclusions are forbidden in M10.4.
