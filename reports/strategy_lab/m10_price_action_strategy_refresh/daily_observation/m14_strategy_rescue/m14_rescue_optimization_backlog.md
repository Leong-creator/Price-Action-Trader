# M14 Rescue Optimization Backlog

- Generated at: `2026-05-26T18:50:00Z`
- Rescue rows: `10`
- Actionable before 10-day A/B completion: `9`
- Zero-signal connected variants: `8`
- Signal without account operation variants: `0`
- Broker dry-run blockers: `3`
- Boundary: internal simulated only; no broker connection, no real orders, no live execution.

## Rescue Backlog

### M10-PA-001-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Work state: `actionable_before_10d`
- Evidence days: `1/10`
- Signal/source/open/close/risk-blocked: `0 / 0 / 0 / 0 / 0`
- Optimization family: `detector_threshold_source_mapping_timeframe`
- Action: Audit detector thresholds, source-row mapping, universe coverage, and timeframe routing; test one relax/quality parameter family in shadow before changing risk.

### M10-PA-002-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Work state: `actionable_before_10d`
- Evidence days: `1/10`
- Signal/source/open/close/risk-blocked: `0 / 0 / 0 / 0 / 0`
- Optimization family: `detector_threshold_source_mapping_timeframe`
- Action: Audit detector thresholds, source-row mapping, universe coverage, and timeframe routing; test one relax/quality parameter family in shadow before changing risk.

### M10-PA-004-MBF-QC-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Work state: `actionable_before_10d`
- Evidence days: `1/10`
- Signal/source/open/close/risk-blocked: `0 / 0 / 0 / 0 / 0`
- Optimization family: `detector_threshold_source_mapping_timeframe`
- Action: Audit detector thresholds, source-row mapping, universe coverage, and timeframe routing; test one relax/quality parameter family in shadow before changing risk.

### M10-PA-007-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Work state: `actionable_before_10d`
- Evidence days: `1/10`
- Signal/source/open/close/risk-blocked: `0 / 0 / 0 / 0 / 0`
- Optimization family: `detector_threshold_source_mapping_timeframe`
- Action: Audit detector thresholds, source-row mapping, universe coverage, and timeframe routing; test one relax/quality parameter family in shadow before changing risk.

### M10-PA-009-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Work state: `actionable_before_10d`
- Evidence days: `1/10`
- Signal/source/open/close/risk-blocked: `0 / 0 / 0 / 0 / 0`
- Optimization family: `detector_threshold_source_mapping_timeframe`
- Action: Audit detector thresholds, source-row mapping, universe coverage, and timeframe routing; test one relax/quality parameter family in shadow before changing risk.

### M10-PA-012-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Work state: `actionable_before_10d`
- Evidence days: `1/10`
- Signal/source/open/close/risk-blocked: `0 / 0 / 0 / 0 / 0`
- Optimization family: `detector_threshold_source_mapping_timeframe`
- Action: Audit detector thresholds, source-row mapping, universe coverage, and timeframe routing; test one relax/quality parameter family in shadow before changing risk.

### M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow

- Priority: `P0`
- Issue: `missing_rescue_ledger`
- Work state: `actionable_before_10d`
- Evidence days: `0/10`
- Signal/source/open/close/risk-blocked: `0 / 0 / 0 / 0 / 0`
- Optimization family: `volatility_filter_risk_sizing_trailing_exit`
- Action: Let the next M12.47-owned refresh generate the first M13 rescue ledger row; if it is still absent after that run, audit the ledger path.

### M10-PA-013-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Work state: `actionable_before_10d`
- Evidence days: `1/10`
- Signal/source/open/close/risk-blocked: `0 / 0 / 0 / 0 / 0`
- Optimization family: `detector_threshold_source_mapping_timeframe`
- Action: Audit detector thresholds, source-row mapping, universe coverage, and timeframe routing; test one relax/quality parameter family in shadow before changing risk.

### M12-FTD-001-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Work state: `actionable_before_10d`
- Evidence days: `1/10`
- Signal/source/open/close/risk-blocked: `0 / 0 / 0 / 0 / 0`
- Optimization family: `detector_threshold_source_mapping_timeframe`
- Action: Audit detector thresholds, source-row mapping, universe coverage, and timeframe routing; test one relax/quality parameter family in shadow before changing risk.

### M10-PA-011-ORB-R1

- Priority: `P2`
- Issue: `collect_more_ab_evidence`
- Work state: `wait_for_more_ab_evidence`
- Evidence days: `1/10`
- Signal/source/open/close/risk-blocked: `18 / 18 / 2 / 0 / 0`
- Optimization family: `detector_contract_rebuild`
- Action: Continue collecting rescue A/B ledger days without changing the frozen variant.

## Broker Dry-run Blockers

- `M10-PA-005` priority `P0`, blocked `2`, reasons `{'consecutive_losses_limit': 1, 'max_total_exposure_exceeded': 1}`. Action: Keep the loss-streak guard active and add cooldown/quality veto diagnostics before allowing further simulated entries.
- `M10-PA-008` priority `P0`, blocked `1`, reasons `{'max_risk_per_order_exceeded': 1}`. Action: Reduce per-order risk through quantity cap, wider source validation, or strategy-specific stop/target normalization before any broker-paper review.

## Summary

Rescue optimization backlog has 10 rescue rows; 9 can be worked before the 10-day A/B window completes. Zero-signal connected variants: 8; signal-without-account-operation variants: 0. Broker dry-run blockers remain 3 events across 2 strategies. No broker connection, real order, live execution, or paper-trading approval is enabled.
