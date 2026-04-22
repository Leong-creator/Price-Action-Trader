# SF-004 Diagnostics

- `triage_status`: `modify_and_retest`
- `triage_reason`: `quality_filter` is a `diagnostic_selected_variant`; it improved on the baseline, but the best variant remains negative in R. Cash-layer positivity comes from independent per-trade sizing and does not justify promotion beyond `modify_and_retest`.
- `baseline_variant`: `baseline`
- `best_variant`: `quality_filter`
- `best_variant_role`: `diagnostic_selected_variant`

## Variant Snapshot
- `baseline`: trades=1198, sample_status=robust_candidate, expectancy=-0.0184R, pnl=-22.0000R
- `quality_filter`: trades=301, sample_status=robust_candidate, expectancy=-0.0133R, pnl=-4.0000R
