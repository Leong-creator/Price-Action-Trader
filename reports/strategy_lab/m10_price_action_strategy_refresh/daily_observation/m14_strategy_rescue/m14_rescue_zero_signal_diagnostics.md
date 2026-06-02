# M14 Rescue Zero-Signal Diagnostics

- Generated at: `2026-06-01T17:29:00Z`
- Zero-signal rescue runtimes: `5`
- Parent source available: `2`
- Quote-refresh candidates: `0`
- Quality/filter blocked: `2`
- Parent source absent: `0`
- Parent detector same-timeframe zero-signal: `3`
- Potential entries if fresh quote gate clears: `0`
- Boundary: internal simulated only; no broker connection, no real orders, no live execution.

## Plain Result

Zero-signal rescue diagnostics reviewed 5 rescue runtimes. 0 are blocked mainly by stale/non-fresh quote source and should be rechecked on the next M12.47 fresh refresh; 2 need parameter/filter work; 0 have no parent source rows for the configured timeframe; 3 have parent detectors that were also zero-signal on the same timeframe. Potential entries if fresh quote gate clears: 0. No broker connection, real order, live execution, or paper-trading approval is enabled.

## Runtime Diagnostics

### M10-PA-002-m14-modify-20260522-1d

- Parent/timeframe: `M10-PA-002 / 1d`
- Dominant issue: `parent_detector_zero_signal_for_timeframe`
- Parent source rows: `0`
- Parent audit: `connected_zero_signal_today` / `0` rows
- Eligible if fresh quote: `0`
- Shadow reward min-R pass counts: `{'1.0R': 0, '1.1R': 0, '1.2R': 0}`
- Rejection reasons: `{}`
- Quote sources: `{}`
- Sample symbols: `none`
- Action: Keep same-timeframe mapping and wait for the parent detector to produce a valid same-timeframe signal; do not remap across timeframes.

### M10-PA-008-broker-risk-cap-shadow-1d

- Parent/timeframe: `M10-PA-008 / 1d`
- Dominant issue: `parent_detector_zero_signal_for_timeframe`
- Parent source rows: `0`
- Parent audit: `connected_zero_signal_today` / `0` rows
- Eligible if fresh quote: `0`
- Shadow reward min-R pass counts: `{'1.0R': 0, '1.1R': 0, '1.2R': 0}`
- Rejection reasons: `{}`
- Quote sources: `{}`
- Sample symbols: `none`
- Action: Keep same-timeframe mapping and wait for the parent detector to produce a valid same-timeframe signal; do not remap across timeframes.

### M10-PA-009-m14-modify-20260522-1d

- Parent/timeframe: `M10-PA-009 / 1d`
- Dominant issue: `parent_detector_zero_signal_for_timeframe`
- Parent source rows: `0`
- Parent audit: `connected_zero_signal_today` / `0` rows
- Eligible if fresh quote: `0`
- Shadow reward min-R pass counts: `{'1.0R': 0, '1.1R': 0, '1.2R': 0}`
- Rejection reasons: `{}`
- Quote sources: `{}`
- Sample symbols: `none`
- Action: Keep same-timeframe mapping and wait for the parent detector to produce a valid same-timeframe signal; do not remap across timeframes.

### M10-PA-012-m14-modify-20260522-5m

- Parent/timeframe: `M10-PA-012 / 5m`
- Dominant issue: `reward_filter_blocks_all`
- Parent source rows: `45`
- Parent audit: `connected_zero_signal_today` / `0` rows
- Eligible if fresh quote: `0`
- Shadow reward min-R pass counts: `{'1.0R': 0, '1.1R': 0, '1.2R': 0}`
- Rejection reasons: `{'direction_not_long': 18, 'leveraged_etf_excluded': 2, 'reward_r_below_min': 45, 'risk_percent_above_limit': 10}`
- Quote sources: `{'longbridge_quote_readonly': 45}`
- Sample symbols: `AAPL, ADBE, AMD, AMZN, ARKK, AVGO, CRM, DIA`
- Action: Reward failure remains even at shadow-only 1.0R after other quality gates; inspect target/stop generation before lowering the frozen rescue threshold.

### M10-PA-013-m14-modify-20260522-1d

- Parent/timeframe: `M10-PA-013 / 1d`
- Dominant issue: `strict_quality_filter_blocks_all`
- Parent source rows: `2`
- Parent audit: `connected_with_signal_today` / `2` rows
- Eligible if fresh quote: `0`
- Shadow reward min-R pass counts: `{'1.0R': 0, '1.1R': 0, '1.2R': 0}`
- Rejection reasons: `{'direction_not_long': 2}`
- Quote sources: `{'longbridge_quote_readonly': 2}`
- Sample symbols: `EFA, LQD`
- Action: Inspect direction, risk-percent, leveraged ETF, and price-validity gates; change only one parameter family at a time in shadow.

## Summary

- Dominant issues: `{'parent_detector_zero_signal_for_timeframe': 3, 'reward_filter_blocks_all': 1, 'strict_quality_filter_blocks_all': 1}`
- Rejection reasons: `{'direction_not_long': 20, 'leveraged_etf_excluded': 2, 'reward_r_below_min': 45, 'risk_percent_above_limit': 10}`
- Shadow reward min-R pass counts: `{'1.0R': 0, '1.1R': 0, '1.2R': 0}`
