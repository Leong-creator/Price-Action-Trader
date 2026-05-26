# M14 Rescue Zero-Signal Diagnostics

- Generated at: `2026-05-26T22:10:00Z`
- Zero-signal rescue runtimes: `9`
- Parent source available: `8`
- Quote-refresh candidates: `7`
- Quality/filter blocked: `1`
- Parent source absent: `0`
- Parent detector same-timeframe zero-signal: `1`
- Potential entries if fresh quote gate clears: `63`
- Boundary: internal simulated only; no broker connection, no real orders, no live execution.

## Plain Result

Zero-signal rescue diagnostics reviewed 9 rescue runtimes. 7 are blocked mainly by stale/non-fresh quote source and should be rechecked on the next M12.47 fresh refresh; 1 need parameter/filter work; 0 have no parent source rows for the configured timeframe; 1 have parent detectors that were also zero-signal on the same timeframe. Potential entries if fresh quote gate clears: 63. No broker connection, real order, live execution, or paper-trading approval is enabled.

## Runtime Diagnostics

### M10-PA-013-m14-modify-20260522-1d

- Parent/timeframe: `M10-PA-013 / 1d`
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
- Parent source rows: `47`
- Parent audit: `connected_with_signal_today` / `47` rows
- Eligible if fresh quote: `0`
- Shadow reward min-R pass counts: `{'1.0R': 0, '1.1R': 0, '1.2R': 0}`
- Rejection reasons: `{'direction_not_long': 31, 'leveraged_etf_excluded': 2, 'reward_r_below_min': 47, 'risk_percent_above_limit': 5, 'stale_quote_source': 47}`
- Quote sources: `{'candidate_reference_fallback': 5, 'm12_12_cached_reference_fallback': 38, 'm12_27_readonly_kline_fallback': 4}`
- Sample symbols: `AAPL, ADBE, AMD, AMZN, ARKK, AVGO, CRM, DIA`
- Action: Reward failure remains even at shadow-only 1.0R after other quality gates; inspect target/stop generation before lowering the frozen rescue threshold.

### M10-PA-001-m14-modify-20260522-1d

- Parent/timeframe: `M10-PA-001 / 1d`
- Dominant issue: `stale_quote_source_blocks_candidate`
- Parent source rows: `22`
- Parent audit: `connected_with_signal_today` / `22` rows
- Eligible if fresh quote: `12`
- Shadow reward min-R pass counts: `{'1.0R': 12, '1.1R': 12, '1.2R': 12}`
- Rejection reasons: `{'direction_not_long': 1, 'risk_percent_above_limit': 9, 'stale_quote_source': 22}`
- Quote sources: `{'candidate_reference_fallback': 4, 'm12_12_cached_reference_fallback': 17, 'm12_27_readonly_kline_fallback': 1}`
- Sample symbols: `ADBE, AMD, AMZN, ARKK, DIA, EEM, HYG, INTC`
- Action: Wait for the next M12.47-owned fresh Longbridge quote refresh before changing rescue parameters.

### M10-PA-002-m14-modify-20260522-1d

- Parent/timeframe: `M10-PA-002 / 1d`
- Dominant issue: `stale_quote_source_blocks_candidate`
- Parent source rows: `2`
- Parent audit: `connected_with_signal_today` / `2` rows
- Eligible if fresh quote: `2`
- Shadow reward min-R pass counts: `{'1.0R': 2, '1.1R': 2, '1.2R': 2}`
- Rejection reasons: `{'stale_quote_source': 2}`
- Quote sources: `{'m12_12_cached_reference_fallback': 2}`
- Sample symbols: `PANW, XLV`
- Action: Wait for the next M12.47-owned fresh Longbridge quote refresh before changing rescue parameters.

### M10-PA-004-MBF-QC-m14-modify-20260522-1d

- Parent/timeframe: `M10-PA-004-MBF-QC / 1d`
- Dominant issue: `stale_quote_source_blocks_candidate`
- Parent source rows: `1`
- Parent audit: `connected_with_signal_today` / `1` rows
- Eligible if fresh quote: `1`
- Shadow reward min-R pass counts: `{'1.0R': 1, '1.1R': 1, '1.2R': 1}`
- Rejection reasons: `{'stale_quote_source': 1}`
- Quote sources: `{'m12_12_cached_reference_fallback': 1}`
- Sample symbols: `SNOW`
- Action: Wait for the next M12.47-owned fresh Longbridge quote refresh before changing rescue parameters.

### M10-PA-007-m14-modify-20260522-1d

- Parent/timeframe: `M10-PA-007 / 1d`
- Dominant issue: `stale_quote_source_blocks_candidate`
- Parent source rows: `6`
- Parent audit: `connected_with_signal_today` / `6` rows
- Eligible if fresh quote: `5`
- Shadow reward min-R pass counts: `{'1.0R': 5, '1.1R': 5, '1.2R': 5}`
- Rejection reasons: `{'direction_not_long': 1, 'risk_percent_above_limit': 1, 'stale_quote_source': 6}`
- Quote sources: `{'candidate_reference_fallback': 2, 'm12_12_cached_reference_fallback': 3, 'm12_27_readonly_kline_fallback': 1}`
- Sample symbols: `IWM, LQD, NVDA, SLV, XLB, XLF`
- Action: Wait for the next M12.47-owned fresh Longbridge quote refresh before changing rescue parameters.

### M10-PA-009-m14-modify-20260522-1d

- Parent/timeframe: `M10-PA-009 / 1d`
- Dominant issue: `stale_quote_source_blocks_candidate`
- Parent source rows: `2`
- Parent audit: `connected_with_signal_today` / `2` rows
- Eligible if fresh quote: `1`
- Shadow reward min-R pass counts: `{'1.0R': 1, '1.1R': 1, '1.2R': 1}`
- Rejection reasons: `{'risk_percent_above_limit': 1, 'stale_quote_source': 2}`
- Quote sources: `{'m12_12_cached_reference_fallback': 2}`
- Sample symbols: `HYG, PLTR`
- Action: Wait for the next M12.47-owned fresh Longbridge quote refresh before changing rescue parameters.

### M10-PA-013-m14-modify-20260522-5m

- Parent/timeframe: `M10-PA-013 / 5m`
- Dominant issue: `stale_quote_source_blocks_candidate`
- Parent source rows: `77`
- Parent audit: `connected_with_signal_today` / `77` rows
- Eligible if fresh quote: `39`
- Shadow reward min-R pass counts: `{'1.0R': 39, '1.1R': 39, '1.2R': 39}`
- Rejection reasons: `{'direction_not_long': 35, 'invalid_risk_reward': 1, 'leveraged_etf_excluded': 4, 'stale_quote_source': 77}`
- Quote sources: `{'candidate_reference_fallback': 8, 'm12_12_cached_reference_fallback': 63, 'm12_27_readonly_kline_fallback': 6}`
- Sample symbols: `AAPL, ADBE, AMD, AMZN, ARKK, AVGO, CRM, DIA`
- Action: Wait for the next M12.47-owned fresh Longbridge quote refresh before changing rescue parameters.

### M12-FTD-001-m14-modify-20260522-1d

- Parent/timeframe: `M12-FTD-001 / 1d`
- Dominant issue: `stale_quote_source_blocks_candidate`
- Parent source rows: `7`
- Parent audit: `connected_with_signal_today` / `7` rows
- Eligible if fresh quote: `3`
- Shadow reward min-R pass counts: `{'1.0R': 3, '1.1R': 3, '1.2R': 3}`
- Rejection reasons: `{'direction_not_long': 3, 'risk_percent_above_limit': 1, 'stale_quote_source': 7}`
- Quote sources: `{'m12_12_cached_reference_fallback': 6, 'm12_27_readonly_kline_fallback': 1}`
- Sample symbols: `GOOG, GOOGL, NVDA, PANW, QCOM, XLU, XLV`
- Action: Wait for the next M12.47-owned fresh Longbridge quote refresh before changing rescue parameters.

## Summary

- Dominant issues: `{'parent_detector_zero_signal_for_timeframe': 1, 'reward_filter_blocks_all': 1, 'stale_quote_source_blocks_candidate': 7}`
- Rejection reasons: `{'direction_not_long': 71, 'invalid_risk_reward': 1, 'leveraged_etf_excluded': 6, 'reward_r_below_min': 47, 'risk_percent_above_limit': 17, 'stale_quote_source': 164}`
- Shadow reward min-R pass counts: `{'1.0R': 63, '1.1R': 63, '1.2R': 63}`
