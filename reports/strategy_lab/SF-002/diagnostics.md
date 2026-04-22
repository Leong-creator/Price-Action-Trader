# SF-002 Diagnostics

- `triage_status`: `modify_and_retest`
- `triage_reason`: `quality_filter` is a `diagnostic_selected_variant`; it improved on the baseline and should guide a narrower `v0.2 spec freeze`, not be treated as a validated production rule
- `baseline_variant`: `baseline`
- `best_variant`: `quality_filter`
- `best_variant_role`: `diagnostic_selected_variant`

## Variant Snapshot
- `baseline`: trades=1560, sample_status=robust_candidate, expectancy=0.0173R, pnl=27.0000R
- `quality_filter`: trades=988, sample_status=robust_candidate, expectancy=0.0354R, pnl=35.0000R
