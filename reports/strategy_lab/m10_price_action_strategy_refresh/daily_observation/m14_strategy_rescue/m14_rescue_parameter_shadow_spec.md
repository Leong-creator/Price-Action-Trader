# M14 Rescue Parameter Shadow Spec

- Generated at: `2026-06-01T17:29:00Z`
- Project stage: `M14 stable strategy testing + M14.2 broker readiness dry-run scaffold`
- Fresh refresh observed: `True`
- Quote source: `longbridge_quote_readonly`
- Spec rows: `14`
- Candidate variants: `14`
- Waiting for fresh refresh: `1`
- Target/stop shadow variants: `1`
- Broker quantity/rule shadow variants: `1/2`
- Parameter mutation allowed: `0`
- Boundary: spec/review only; no implementation or parameter mutation, no registry/account-spec/broker-readiness mutation, no broker/live, no manual M12.37 once-mode.

## Plain Result

Parameter shadow spec prepared 14 rows and 14 candidate variants. 1 rows still wait for M12.47-owned fresh evidence, 1 target/stop shadow variant and 3 broker-blocker shadow variants are specified. This is a review/spec artifact only: parameter mutation, implementation mutation, registry/account-spec mutation, broker readiness mutation, broker/live, real orders, paper approval, and manual M12.37 once-mode remain disabled.

## Spec Rows

### M10-PA-001-m14-modify-20260522 / signal_to_account_bridge_audit

- State: `review_spec_prepared_no_mutation`
- Gate state: `waiting_for_matching_post_refresh_evidence`
- Candidate parameter family: `signal_account_bridge_mapping`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `False`

Variants:
- `manual_review_m10-pa-001-m14-modify-20260522` / `manual_review_only`: Manual M14 review must decide whether a later shadow spec is warranted.

### M10-PA-002-m14-modify-20260522 / parent_detector_timeframe_mapping_review

- State: `wait_parent_detector_evidence_before_spec`
- Gate state: `evidence_failed_keep_blocked`
- Candidate parameter family: `same_timeframe_parent_detector_mapping`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `False`

Variants:
- `same_timeframe_parent_detector_evidence` / `parent_detector_review`: Require same-timeframe parent detector evidence before remapping or rebuilding the rescue detector.

### M10-PA-005 / cooldown_quality_veto_shadow

- State: `ready_for_manual_shadow_review_no_mutation`
- Gate state: `ready_for_shadow_parameter_review`
- Candidate parameter family: `cooldown_quality_veto`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `True`

Variants:
- `broker_cooldown_quality_shadow` / `broker_cooldown_quality_shadow`: Preserve the loss-streak halt and compare later same-session entries against cooldown/quality-veto checks; the blocked source row remains blocked.

### M10-PA-005 / exposure_ranker_shadow

- State: `ready_for_manual_shadow_review_no_mutation`
- Gate state: `ready_for_shadow_parameter_review`
- Candidate parameter family: `portfolio_exposure_ranker`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `True`

Variants:
- `broker_exposure_ranker_shadow` / `broker_exposure_ranker_shadow`: Compare future same-strategy internal-sim signals by total exposure headroom and rank; lower-ranked entries remain deferred until headroom exists.

### M10-PA-008 / quantity_cap_shadow

- State: `shadow_spec_prepared_wait_fresh_refresh`
- Gate state: `waiting_for_matching_post_refresh_evidence`
- Candidate parameter family: `position_size_quantity_cap`
- Variant count: `1`
- Fresh refresh required: `True`
- Ready for manual shadow review: `False`

Variants:
- `broker_risk_cap_shadow` / `broker_quantity_cap_shadow`: Shadow-test the quantity cap that brings per-order risk back to the existing internal limit.

### M10-PA-008-broker-risk-cap-shadow / parent_detector_timeframe_mapping_review

- State: `wait_parent_detector_evidence_before_spec`
- Gate state: `evidence_failed_keep_blocked`
- Candidate parameter family: `same_timeframe_parent_detector_mapping`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `False`

Variants:
- `same_timeframe_parent_detector_evidence` / `parent_detector_review`: Require same-timeframe parent detector evidence before remapping or rebuilding the rescue detector.

### M10-PA-009-m14-modify-20260522 / parent_detector_timeframe_mapping_review

- State: `wait_parent_detector_evidence_before_spec`
- Gate state: `evidence_failed_keep_blocked`
- Candidate parameter family: `same_timeframe_parent_detector_mapping`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `False`

Variants:
- `same_timeframe_parent_detector_evidence` / `parent_detector_review`: Require same-timeframe parent detector evidence before remapping or rebuilding the rescue detector.

### M10-PA-012-m14-modify-20260522 / target_stop_reward_geometry_shadow

- State: `ready_for_manual_shadow_review_no_mutation`
- Gate state: `ready_for_shadow_parameter_review`
- Candidate parameter family: `target_stop_geometry_normalization_not_lowering_frozen_min_r`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `True`

Variants:
- `risk_normalized_1_0r` / `target_stop_shadow`: Shadow-test normalized 1.0R target geometry without lowering the frozen runtime min-R threshold.

### M12-FTD-001-m14-modify-20260522 / signal_to_account_bridge_audit

- State: `review_spec_prepared_no_mutation`
- Gate state: `waiting_for_matching_post_refresh_evidence`
- Candidate parameter family: `signal_account_bridge_mapping`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `False`

Variants:
- `manual_review_m12-ftd-001-m14-modify-20260522` / `manual_review_only`: Manual M14 review must decide whether a later shadow spec is warranted.

### M10-PA-004-MBF-QC-m14-modify-20260522 / continue_ab_evidence_collection

- State: `continue_ab_collection_no_new_parameter_spec`
- Gate state: `continue_ab_collection_only`
- Candidate parameter family: `none_ab_evidence_only`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `False`

Variants:
- `continue_current_rescue_ab_window` / `ab_evidence_only`: Keep collecting the current rescue runtime's own 10-trading-day A/B evidence.

### M10-PA-007-m14-modify-20260522 / continue_ab_evidence_collection

- State: `continue_ab_collection_no_new_parameter_spec`
- Gate state: `continue_ab_collection_only`
- Candidate parameter family: `none_ab_evidence_only`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `False`

Variants:
- `continue_current_rescue_ab_window` / `ab_evidence_only`: Keep collecting the current rescue runtime's own 10-trading-day A/B evidence.

### M10-PA-011-ORB-R1 / continue_ab_evidence_collection

- State: `continue_ab_collection_no_new_parameter_spec`
- Gate state: `continue_ab_collection_only`
- Candidate parameter family: `none_ab_evidence_only`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `False`

Variants:
- `continue_current_rescue_ab_window` / `ab_evidence_only`: Keep collecting the current rescue runtime's own 10-trading-day A/B evidence.

### M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow / continue_ab_evidence_collection

- State: `continue_ab_collection_no_new_parameter_spec`
- Gate state: `continue_ab_collection_only`
- Candidate parameter family: `none_ab_evidence_only`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `False`

Variants:
- `continue_current_rescue_ab_window` / `ab_evidence_only`: Keep collecting the current rescue runtime's own 10-trading-day A/B evidence.

### M10-PA-013-m14-modify-20260522 / continue_ab_evidence_collection

- State: `continue_ab_collection_no_new_parameter_spec`
- Gate state: `continue_ab_collection_only`
- Candidate parameter family: `none_ab_evidence_only`
- Variant count: `1`
- Fresh refresh required: `False`
- Ready for manual shadow review: `False`

Variants:
- `continue_current_rescue_ab_window` / `ab_evidence_only`: Keep collecting the current rescue runtime's own 10-trading-day A/B evidence.
