# M14 Strategy Decision Ladder

- Generated at: `2026-05-26T23:35:00Z`
- Current stage: `M14 stable strategy testing + M14.2 broker readiness dry-run scaffold`
- Challenge: `10/10`
- Strategy rows: `20`
- Approved next-step count: `3`
- Rescue continue count: `10`
- Promotion candidates: `0`
- Final discard allowed: `0`
- Candidate variants linked: `14`
- Boundary: internal simulated accounts only; no broker/live, no real orders, no paper approval, no manual M12.37 once-mode.

## Plain Result

Strategy decision ladder covers 20 strategies. 3 can advance only to the next internal simulated-account refresh; 10 must continue rescue or detector work; 7 stay as shadow/plugin/research coverage. Final discard allowed now: 0. Promotion candidates now: 0. No broker/live, real orders, paper approval, parameter mutation, registry/account-spec mutation, broker-readiness mutation, or manual M12.37 once-mode is enabled.

## Decision Policy

- `approved_strategy_rule`: Approved strategies can advance only to the next internal simulated-account refresh.
- `rescue_rule`: Weak strategies stay in rescue A/B, shadow spec, or detector rebuild until rescue evidence is complete.
- `discard_rule`: Final discard is allowed only after rescue routes, shadow specs, first-ledger checks, and 10-day A/B evidence are exhausted and manual M14 review agrees.
- `external_reference_rule`: External projects can provide review patterns only; they cannot override local M13/M14 gates.

## Ladder Rows

### M10-PA-004

- Route: `approved_internal_sim_continue`
- Ladder state: `approved_continue_internal_sim`
- Next decision: `advance_internal_sim_next_refresh`
- Can advance next step: `True`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, strategy_is_approved_for_internal_sim`
- Shadow specs / variants: `0/0`
- Next action: Continue only in the next M12.47-supervised internal simulated-account refresh.

### M10-PA-005

- Route: `approved_internal_sim_continue`
- Ladder state: `approved_continue_internal_sim`
- Next decision: `advance_internal_sim_next_refresh`
- Can advance next step: `True`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, shadow_parameter_spec_exists, strategy_is_approved_for_internal_sim`
- Shadow specs / variants: `2/2`
- Next action: Continue only in the next M12.47-supervised internal simulated-account refresh.

### M10-PA-008

- Route: `approved_internal_sim_continue`
- Ladder state: `approved_continue_internal_sim`
- Next decision: `advance_internal_sim_next_refresh`
- Can advance next step: `True`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `first_m13_rescue_ledger_missing, manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists, strategy_is_approved_for_internal_sim`
- Shadow specs / variants: `2/2`
- Next action: Continue only in the next M12.47-supervised internal simulated-account refresh.

### M10-PA-001

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `True`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-002

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `True`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-004-MBF-QC

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `True`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-007

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `True`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-009

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `True`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-012

- Route: `rescue_ab_collect`
- Ladder state: `wait_first_rescue_ledger`
- Next decision: `collect_first_m13_rescue_ledger`
- Can advance next step: `False`
- Continue rescue: `True`
- Final discard allowed: `False`
- Final discard blockers: `first_m13_rescue_ledger_missing, manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `2/2`
- Next action: Wait for first rescue-specific M13 ledger evidence from M12.47-owned refresh.

### M10-PA-013

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `True`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M12-FTD-001

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `True`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-004-MBF

- Route: `parallel_ab_collect`
- Ladder state: `continue_rescue_ab_collection`
- Next decision: `collect_10_day_rescue_ab_evidence`
- Can advance next step: `False`
- Continue rescue: `True`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, required_rescue_evidence_missing`
- Shadow specs / variants: `0/0`
- Next action: Continue rescue-specific 10 trading-day A/B evidence collection.

### M10-PA-011

- Route: `rebuild_detector_then_ab`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `True`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### AI-TRADER-EXTERNAL

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Next decision: `keep_shadow_research_coverage`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, strategy_is_shadow_plugin_or_research_coverage`
- Shadow specs / variants: `0/0`
- Next action: Keep as shadow/plugin/research coverage; do not present as an independent trading account.

### M10-PA-003

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Next decision: `keep_shadow_research_coverage`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, strategy_is_shadow_plugin_or_research_coverage`
- Shadow specs / variants: `0/0`
- Next action: Keep as shadow/plugin/research coverage; do not present as an independent trading account.

### M10-PA-006

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Next decision: `keep_shadow_research_coverage`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, strategy_is_shadow_plugin_or_research_coverage`
- Shadow specs / variants: `0/0`
- Next action: Keep as shadow/plugin/research coverage; do not present as an independent trading account.

### M10-PA-010

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Next decision: `keep_shadow_research_coverage`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, strategy_is_shadow_plugin_or_research_coverage`
- Shadow specs / variants: `0/0`
- Next action: Keep as shadow/plugin/research coverage; do not present as an independent trading account.

### M10-PA-014

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Next decision: `keep_shadow_research_coverage`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, strategy_is_shadow_plugin_or_research_coverage`
- Shadow specs / variants: `0/0`
- Next action: Keep as shadow/plugin/research coverage; do not present as an independent trading account.

### M10-PA-015

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Next decision: `keep_shadow_research_coverage`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, strategy_is_shadow_plugin_or_research_coverage`
- Shadow specs / variants: `0/0`
- Next action: Keep as shadow/plugin/research coverage; do not present as an independent trading account.

### M10-PA-016

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Next decision: `keep_shadow_research_coverage`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, strategy_is_shadow_plugin_or_research_coverage`
- Shadow specs / variants: `0/0`
- Next action: Keep as shadow/plugin/research coverage; do not present as an independent trading account.
