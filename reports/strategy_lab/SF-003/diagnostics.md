# SF-003 Diagnostics

- `triage_status`: `modify_and_retest`
- `triage_reason`: `quality_filter` is a `diagnostic_selected_variant`; it improved on the baseline, but both baseline and best variant remain negative in R. Cash-layer positivity comes from independent per-trade sizing and does not justify promotion beyond `modify_and_retest`.
- `baseline_variant`: `baseline`
- `best_variant`: `quality_filter`
- `best_variant_role`: `diagnostic_selected_variant`

## Variant Snapshot
- `baseline`: trades=1707, sample_status=robust_candidate, expectancy=-0.0422R, pnl=-72.0000R
- `quality_filter`: trades=1119, sample_status=robust_candidate, expectancy=-0.0214R, pnl=-24.0000R
