# M10-PA-002 5m Failure Mode Notes

- candidate_event_count: `10759`
- executed_trade_count: `10759`
- outcome: `continue_testing`
- This is a paper/simulated pilot artifact, not a profitability claim.

## Skip Counts

- `m10_002_no_follow_through`: 2424
- `m10_002_weak_breakout_bar`: 6438

## Notes

- If event counts are low, prefer `needs_definition_fix` or `continue_testing` rather than interpreting performance.
- If OHLCV approximation misses source context, route to `needs_visual_review`.
- `retain/promote/live` conclusions are forbidden in M10.4.
