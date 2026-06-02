# M14 Strategy Decision Ladder

- Generated at: `2026-06-01T17:29:01Z`
- Current stage: `M14 stable strategy testing + M14.2 broker readiness dry-run scaffold`
- Challenge: `10/10`
- Strategy rows: `25`
- Approved next-step count: `2`
- Rescue continue count: `0`
- Promotion candidates: `0`
- Final discard allowed: `0`
- Candidate variants linked: `20`
- Boundary: internal simulated accounts only; no broker/live, no real orders, no paper approval, no manual M12.37 once-mode.

## Plain Result

Strategy decision ladder covers 25 strategies. 2 can advance only to the next internal simulated-account refresh; 0 must continue rescue or detector work; 0 stay as shadow/plugin/research coverage. Final discard allowed now: 0. Promotion candidates now: 0. No broker/live, real orders, paper approval, parameter mutation, registry/account-spec mutation, broker-readiness mutation, or manual M12.37 once-mode is enabled.

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

### M10-PA-013

- Route: `approved_internal_sim_continue`
- Ladder state: `approved_continue_internal_sim`
- Next decision: `advance_internal_sim_next_refresh`
- Can advance next step: `True`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists, strategy_is_approved_for_internal_sim`
- Shadow specs / variants: `1/1`
- Next action: Continue only in the next M12.47-supervised internal simulated-account refresh.

### AI-TRADER-EXTERNAL

- Route: `manual_review_required`
- Ladder state: `manual_review_required`
- Next decision: `inspect_before_state_change`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required`
- Shadow specs / variants: `0/0`
- Next action: Manual review required before inspect_before_state_change.

### M10-PA-001

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-001

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-002

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-002

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-003

- Route: `manual_review_required`
- Ladder state: `manual_review_required`
- Next decision: `inspect_before_state_change`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required`
- Shadow specs / variants: `0/0`
- Next action: Manual review required before inspect_before_state_change.

### M10-PA-004-MBF

- Route: `manual_review_required`
- Ladder state: `manual_review_required`
- Next decision: `inspect_before_state_change`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required`
- Shadow specs / variants: `0/0`
- Next action: Manual review required before inspect_before_state_change.

### M10-PA-004-MBF-QC

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-005

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, shadow_parameter_spec_exists`
- Shadow specs / variants: `2/2`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-005

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, shadow_parameter_spec_exists`
- Shadow specs / variants: `2/2`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-006

- Route: `manual_review_required`
- Ladder state: `manual_review_required`
- Next decision: `inspect_before_state_change`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required`
- Shadow specs / variants: `0/0`
- Next action: Manual review required before inspect_before_state_change.

### M10-PA-007

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-008

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `2/2`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-009

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-010

- Route: `manual_review_required`
- Ladder state: `manual_review_required`
- Next decision: `inspect_before_state_change`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required`
- Shadow specs / variants: `0/0`
- Next action: Manual review required before inspect_before_state_change.

### M10-PA-011

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-012

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `2/2`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-013

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M10-PA-014

- Route: `manual_review_required`
- Ladder state: `manual_review_required`
- Next decision: `inspect_before_state_change`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required`
- Shadow specs / variants: `0/0`
- Next action: Manual review required before inspect_before_state_change.

### M10-PA-015

- Route: `manual_review_required`
- Ladder state: `manual_review_required`
- Next decision: `inspect_before_state_change`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required`
- Shadow specs / variants: `0/0`
- Next action: Manual review required before inspect_before_state_change.

### M10-PA-016

- Route: `manual_review_required`
- Ladder state: `manual_review_required`
- Next decision: `inspect_before_state_change`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required`
- Shadow specs / variants: `0/0`
- Next action: Manual review required before inspect_before_state_change.

### M12-FTD-001

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.

### M12-FTD-001

- Route: `manual_review_required`
- Ladder state: `continue_rescue_with_shadow_specs`
- Next decision: `continue_ab_and_shadow_parameter_review`
- Can advance next step: `False`
- Continue rescue: `False`
- Final discard allowed: `False`
- Final discard blockers: `manual_m14_final_review_required, rescue_10_day_ab_window_incomplete, rescue_runtime_exists, shadow_parameter_spec_exists`
- Shadow specs / variants: `1/1`
- Next action: Keep rescue A/B collection and use shadow specs after fresh evidence.
