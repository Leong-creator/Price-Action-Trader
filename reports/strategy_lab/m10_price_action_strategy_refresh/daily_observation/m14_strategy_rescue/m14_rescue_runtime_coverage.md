# M14 Rescue Runtime Coverage

- Generated at: `2026-05-26T22:10:00Z`
- Registered rescue strategies connected: `11/11`
- Registered rescue accounts: `12`
- Planned rescue/rebuild actions covered: `10/10`
- Boundary: internal simulated only; no broker connection, no real orders, no live execution.
- Policy: Connected does not mean passed or approved; 10 trading-day A/B ledger evidence is still required.

## Registered Rescue Runtimes

### M10-PA-001-m14-modify-20260522

- Parent: `M10-PA-001`
- Detector: `m14_rescue_parent_quality_filter_adapter` / `connected`
- Runtime ids: `M10-PA-001-m14-modify-20260522-1d`
- Input source types: `m14_rescue_parent_quality_filter_adapter`
- Coverage: `connected_not_promoted`
- Promotion status: `not_promoted_requires_10_day_ab_evidence`

### M10-PA-002-m14-modify-20260522

- Parent: `M10-PA-002`
- Detector: `m14_rescue_parent_quality_filter_adapter` / `connected`
- Runtime ids: `M10-PA-002-m14-modify-20260522-1d`
- Input source types: `m14_rescue_parent_quality_filter_adapter`
- Coverage: `connected_not_promoted`
- Promotion status: `not_promoted_requires_10_day_ab_evidence`

### M10-PA-004-MBF-QC-m14-modify-20260522

- Parent: `M10-PA-004-MBF-QC`
- Detector: `m14_rescue_pa004_mbf_qc_risk_compression_adapter` / `connected`
- Runtime ids: `M10-PA-004-MBF-QC-m14-modify-20260522-1d`
- Input source types: `m14_rescue_pa004_mbf_qc_risk_compression_adapter`
- Coverage: `connected_not_promoted`
- Promotion status: `not_promoted_requires_10_day_ab_evidence`

### M10-PA-007-m14-modify-20260522

- Parent: `M10-PA-007`
- Detector: `m14_rescue_parent_quality_filter_adapter` / `connected`
- Runtime ids: `M10-PA-007-m14-modify-20260522-1d`
- Input source types: `m14_rescue_parent_quality_filter_adapter`
- Coverage: `connected_not_promoted`
- Promotion status: `not_promoted_requires_10_day_ab_evidence`

### M10-PA-008-broker-risk-cap-shadow

- Parent: `M10-PA-008`
- Detector: `m14_broker_blocker_pa008_quantity_cap_adapter` / `connected`
- Runtime ids: `M10-PA-008-broker-risk-cap-shadow-1d`
- Input source types: `m14_broker_blocker_pa008_quantity_cap_adapter`
- Coverage: `connected_not_promoted`
- Promotion status: `not_promoted_requires_10_day_ab_evidence`

### M10-PA-009-m14-modify-20260522

- Parent: `M10-PA-009`
- Detector: `m14_rescue_parent_quality_filter_adapter` / `connected`
- Runtime ids: `M10-PA-009-m14-modify-20260522-1d`
- Input source types: `m14_rescue_parent_quality_filter_adapter`
- Coverage: `connected_not_promoted`
- Promotion status: `not_promoted_requires_10_day_ab_evidence`

### M10-PA-011-ORB-R1

- Parent: `M10-PA-011`
- Detector: `m14_rescue_pa011_failed_orb_retest_adapter` / `connected`
- Runtime ids: `M10-PA-011-ORB-R1-5m`
- Input source types: `m14_rescue_pa011_failed_orb_retest_adapter`
- Coverage: `connected_not_promoted`
- Promotion status: `not_promoted_requires_10_day_ab_evidence`

### M10-PA-012-m14-modify-20260522

- Parent: `M10-PA-012`
- Detector: `m14_rescue_orb_quality_filter_adapter` / `connected`
- Runtime ids: `M10-PA-012-m14-modify-20260522-5m`
- Input source types: `m14_rescue_orb_quality_filter_adapter`
- Coverage: `connected_not_promoted`
- Promotion status: `not_promoted_requires_10_day_ab_evidence`

### M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow

- Parent: `M10-PA-012`
- Detector: `m14_rescue_pa012_target_stop_risk_normalized_1_0r_adapter` / `connected`
- Runtime ids: `M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow-5m`
- Input source types: `m14_rescue_pa012_target_stop_risk_normalized_1_0r_adapter`
- Coverage: `connected_not_promoted`
- Promotion status: `not_promoted_requires_10_day_ab_evidence`

### M10-PA-013-m14-modify-20260522

- Parent: `M10-PA-013`
- Detector: `m14_rescue_parent_quality_filter_adapter` / `connected`
- Runtime ids: `M10-PA-013-m14-modify-20260522-1d, M10-PA-013-m14-modify-20260522-5m`
- Input source types: `m14_rescue_parent_quality_filter_adapter`
- Coverage: `connected_not_promoted`
- Promotion status: `not_promoted_requires_10_day_ab_evidence`

### M12-FTD-001-m14-modify-20260522

- Parent: `M12-FTD-001`
- Detector: `m14_rescue_parent_quality_filter_adapter` / `connected`
- Runtime ids: `M12-FTD-001-m14-modify-20260522-1d`
- Input source types: `m14_rescue_parent_quality_filter_adapter`
- Coverage: `connected_not_promoted`
- Promotion status: `not_promoted_requires_10_day_ab_evidence`

## Planned Action Coverage

### M10-PA-001

- Plan lane: `rescue_candidate`
- Next variant: `M10-PA-001-m14-modify-20260522`
- Coverage: `covered_by_rescue_runtime`
- Covered by: `M10-PA-001-m14-modify-20260522`

### M10-PA-002

- Plan lane: `rescue_candidate`
- Next variant: `M10-PA-002-m14-modify-20260522`
- Coverage: `covered_by_rescue_runtime`
- Covered by: `M10-PA-002-m14-modify-20260522`

### M10-PA-004-MBF

- Plan lane: `rescue_candidate`
- Next variant: `M10-PA-004-MBF-QC`
- Coverage: `covered_by_existing_runtime`
- Covered by: `M10-PA-004-MBF-QC`

### M10-PA-004-MBF-QC

- Plan lane: `rescue_candidate`
- Next variant: `M10-PA-004-MBF-QC-m14-modify-20260522`
- Coverage: `covered_by_rescue_runtime`
- Covered by: `M10-PA-004-MBF-QC-m14-modify-20260522`

### M10-PA-007

- Plan lane: `rescue_candidate`
- Next variant: `M10-PA-007-m14-modify-20260522`
- Coverage: `covered_by_rescue_runtime`
- Covered by: `M10-PA-007-m14-modify-20260522`

### M10-PA-009

- Plan lane: `rescue_candidate`
- Next variant: `M10-PA-009-m14-modify-20260522`
- Coverage: `covered_by_rescue_runtime`
- Covered by: `M10-PA-009-m14-modify-20260522`

### M10-PA-011

- Plan lane: `detector_rebuild`
- Next variant: `M10-PA-011-m14-rescue-v1`
- Coverage: `covered_by_rescue_runtime`
- Covered by: `M10-PA-011-ORB-R1`

### M10-PA-012

- Plan lane: `rescue_candidate`
- Next variant: `M10-PA-012-m14-modify-20260522`
- Coverage: `covered_by_rescue_runtime`
- Covered by: `M10-PA-012-m14-modify-20260522, M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow`

### M10-PA-013

- Plan lane: `rescue_candidate`
- Next variant: `M10-PA-013-m14-modify-20260522`
- Coverage: `covered_by_rescue_runtime`
- Covered by: `M10-PA-013-m14-modify-20260522`

### M12-FTD-001

- Plan lane: `rescue_candidate`
- Next variant: `M12-FTD-001-m14-modify-20260522`
- Coverage: `covered_by_rescue_runtime`
- Covered by: `M12-FTD-001-m14-modify-20260522`

## Summary

Registered rescue runtime coverage is 11/11 strategies and 12 accounts. Planned rescue/rebuild action coverage is 10/10. Connected does not mean passed or approved; every rescue runtime still needs 10 trading-day A/B ledger evidence. No broker connection, real order, live execution, or paper-trading approval was enabled.
