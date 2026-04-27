# M11.5 Blockers and Required Approvals

## Approval State

- approval_state: `not_approved`
- paper_trading_approval: `false`
- broker_connection: `false`
- real_orders: `false`
- live_execution: `false`

## Blocking Conditions

- `m12_2_has_no_completed_strategy_candidate_events`: 5
- `manual_visual_review_still_pending`: 2
- `no_completed_real_read_only_observation_window`: 5
- `no_human_business_approval_for_paper_trading`: 5
- `scanner_universe_cache_coverage_incomplete`: 5
- `unresolved_definition_blockers`: 5

## Required Before Next Gate

- `completed_real_read_only_observation_window`
- `manual_visual_review_closed_for_m10_pa_008_009`
- `definition_blockers_closed_or_formally_deferred`
- `scanner_cache_coverage_plan_or_deferred_scope_approval`
- `human_business_approval_for_paper_trading`
