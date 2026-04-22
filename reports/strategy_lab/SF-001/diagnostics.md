# SF-001 Diagnostics

- `triage_status`: `modify_and_retest`
- `triage_reason`: `quality_filter` is a `diagnostic_selected_variant`; it improved on the baseline and should guide a narrower `v0.2 spec freeze`, not be treated as a validated production rule
- `baseline_variant`: `baseline`
- `best_variant`: `quality_filter`
- `best_variant_role`: `diagnostic_selected_variant`

## Variant Snapshot
- `baseline`: trades=9164, sample_status=robust_candidate, expectancy=0.0017R, pnl=16.0000R
- `quality_filter`: trades=8037, sample_status=robust_candidate, expectancy=0.0112R, pnl=90.0000R
