# M14 Rescue Target/Stop Diagnostics

- Generated at: `2026-05-26T17:15:00Z`
- Diagnosed rescue runtimes: `1`
- Target/stop issue runtimes: `1`
- Shadow-candidate runtimes: `0`
- Reward >= 1.0R runtime count: `0`
- Boundary: internal simulated only; no broker connection, no real orders, no live execution.

## Plain Result

Target/stop diagnostics reviewed 1 rescue runtimes that were reward/R candidates. Target/stop issues remain on 1 runtimes. Issue counts: {'target_reward_below_1r_after_quality_gates': 1}. This is read-only and simulated; no broker connection, real order, live execution, or paper-trading approval is enabled.

## Runtime Diagnostics

### M10-PA-012-m14-modify-20260522-5m

- Parent/timeframe: `M10-PA-012 / 5m`
- Dominant target/stop issue: `target_reward_below_1r_after_quality_gates`
- Source rows: `47`
- Valid geometry: `47`
- Bullish rows: `16`
- Non-leveraged bullish valid rows: `15`
- Risk gate pass: `12`
- Reward pass counts: `1.0R=0, 1.1R=0, 1.2R=0`
- Reward/R min/median/max: `0.7159 / 0.9568 / 0.9819`
- Action: Inspect and shadow-test the ORB target/stop generator before lowering min-R; try measured-move/opening-range-height or normalized 1.0R targets only in simulated diagnostics.

## Summary

- Dominant target/stop issues: `{'target_reward_below_1r_after_quality_gates': 1}`
- Runtime ids: `M10-PA-012-m14-modify-20260522-5m`
