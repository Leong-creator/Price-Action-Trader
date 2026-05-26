# M14 Rescue Target/Stop Shadow Normalization

- Generated at: `2026-05-26T18:00:00Z`
- Diagnosed runtimes: `1`
- Runtime with shadow candidate: `1`
- Best candidate rows: `12/12`
- Best variant counts: `{'risk_normalized_1_0r': 1}`
- Boundary: shadow-only design; no broker connection, no real orders, no live execution.

## Plain Result

Target/stop shadow normalization reviewed 1 reward/R-blocked runtimes. 1 have a shadow-only candidate; best candidate rows: 12/12. Best variant counts: {'risk_normalized_1_0r': 1}. No broker connection, real order, live execution, or paper-trading approval is enabled.

## Runtime Candidates

### M10-PA-012-m14-modify-20260522-5m

- Parent/timeframe: `M10-PA-012 / 5m`
- Eligible source rows: `12/47`
- Current reward/R min/median/max: `0.7159 / 0.9569 / 0.9819`
- Best variant: `risk_normalized_1_0r`
- Shadow runtime id candidate: `M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow`
- Best candidate rows: `12`
- Action: Create a shadow-only PA012 target/stop candidate using `risk_normalized_1_0r`; rerun after the next fresh M12.47 quote refresh, then require 10 rescue A/B trading days before any M14 promote/modify/reject decision.

- Variant `risk_normalized_1_0r`: candidates `12/12`, reward/R `1.0000 / 1.0000 / 1.0000`, median target shift `0.0410%`
- Variant `risk_normalized_1_1r`: candidates `12/12`, reward/R `1.1000 / 1.1000 / 1.1000`, median target shift `0.1558%`
- Variant `risk_normalized_1_2r`: candidates `12/12`, reward/R `1.2000 / 1.2000 / 1.2000`, median target shift `0.2704%`
- Variant `opening_range_height_30m`: candidates `0/12`, reward/R `0.7159 / 0.9568 / 0.9819`, median target shift `0.0000%`

## Summary

- Runtime ids: `M10-PA-012-m14-modify-20260522-5m`
