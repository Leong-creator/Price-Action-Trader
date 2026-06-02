# M14 Rescue Parameter Activation Gate

- Generated at: `2026-06-01T17:29:00Z`
- Fresh refresh observed: `True`
- Quote source: `longbridge_quote_readonly`
- Gate rows: `14`
- Shadow-review candidates: `3`
- First-ledger ready rows: `0`
- Waiting for fresh refresh: `0`
- Evidence failed: `3`
- Parameter mutation allowed: `0`
- Boundary: read-only gate; no parameter mutation, no registry/account-spec/broker-readiness mutation, no broker/live, no manual M12.37 once-mode.

## Plain Result

Parameter activation gate checked 14 experiment rows. Fresh refresh observed: True with quote_source=longbridge_quote_readonly. Shadow-review candidates: 3; first-ledger ready rows: 0; waiting for fresh refresh: 0; evidence failed: 3. Implementation mutation, parameter mutation, M13 registry mutation, M12 account-spec mutation, broker readiness mutation, broker connection, real orders, live execution, paper approval, and manual M12.37 once-mode remain disabled.

## Gate Rows

### M10-PA-001-m14-modify-20260522 / signal_to_account_bridge_audit

- Gate state: `waiting_for_matching_post_refresh_evidence`
- Outcome: ``
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: Fresh refresh exists, but no matching post-refresh outcome row was found.
- Next action: Add or inspect the matching post-refresh watch row before using this parameter family.

### M10-PA-002-m14-modify-20260522 / parent_detector_timeframe_mapping_review

- Gate state: `evidence_failed_keep_blocked`
- Outcome: `still_waiting_parent_detector_after_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: Post-refresh outcome is still_waiting_parent_detector_after_fresh_refresh; keep the family blocked.
- Next action: Keep same-timeframe wait; do not hard-map across timeframes.

### M10-PA-005 / cooldown_quality_veto_shadow

- Gate state: `ready_for_shadow_parameter_review`
- Outcome: `evidence_observed`
- Shadow-review candidate: `True`
- Parameter mutation allowed: `False`
- Reason: Required post-refresh evidence exists; this family can be reviewed for a later shadow-only parameter experiment.
- Next action: Prepare manual M14 shadow-review notes; implementation still requires a separate audited change.

### M10-PA-005 / exposure_ranker_shadow

- Gate state: `ready_for_shadow_parameter_review`
- Outcome: `evidence_observed`
- Shadow-review candidate: `True`
- Parameter mutation allowed: `False`
- Reason: Required post-refresh evidence exists; this family can be reviewed for a later shadow-only parameter experiment.
- Next action: Prepare manual M14 shadow-review notes; implementation still requires a separate audited change.

### M10-PA-008 / quantity_cap_shadow

- Gate state: `waiting_for_matching_post_refresh_evidence`
- Outcome: ``
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: Fresh refresh exists, but no matching post-refresh outcome row was found.
- Next action: Add or inspect the matching post-refresh watch row before using this parameter family.

### M10-PA-008-broker-risk-cap-shadow / parent_detector_timeframe_mapping_review

- Gate state: `evidence_failed_keep_blocked`
- Outcome: `still_waiting_parent_detector_after_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: Post-refresh outcome is still_waiting_parent_detector_after_fresh_refresh; keep the family blocked.
- Next action: Keep same-timeframe wait; do not hard-map across timeframes.

### M10-PA-009-m14-modify-20260522 / parent_detector_timeframe_mapping_review

- Gate state: `evidence_failed_keep_blocked`
- Outcome: `still_waiting_parent_detector_after_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: Post-refresh outcome is still_waiting_parent_detector_after_fresh_refresh; keep the family blocked.
- Next action: Keep same-timeframe wait; do not hard-map across timeframes.

### M10-PA-012-m14-modify-20260522 / target_stop_reward_geometry_shadow

- Gate state: `ready_for_shadow_parameter_review`
- Outcome: `passed`
- Shadow-review candidate: `True`
- Parameter mutation allowed: `False`
- Reason: Required post-refresh evidence exists; this family can be reviewed for a later shadow-only parameter experiment.
- Next action: Prepare manual M14 shadow-review notes; implementation still requires a separate audited change.

### M12-FTD-001-m14-modify-20260522 / signal_to_account_bridge_audit

- Gate state: `waiting_for_matching_post_refresh_evidence`
- Outcome: ``
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: Fresh refresh exists, but no matching post-refresh outcome row was found.
- Next action: Add or inspect the matching post-refresh watch row before using this parameter family.

### M10-PA-004-MBF-QC-m14-modify-20260522 / continue_ab_evidence_collection

- Gate state: `continue_ab_collection_only`
- Outcome: ``
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: This row already has active rescue evidence; keep collecting the 10-day A/B window.
- Next action: Continue A/B evidence collection; no parameter activation.

### M10-PA-007-m14-modify-20260522 / continue_ab_evidence_collection

- Gate state: `continue_ab_collection_only`
- Outcome: ``
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: This row already has active rescue evidence; keep collecting the 10-day A/B window.
- Next action: Continue A/B evidence collection; no parameter activation.

### M10-PA-011-ORB-R1 / continue_ab_evidence_collection

- Gate state: `continue_ab_collection_only`
- Outcome: ``
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: This row already has active rescue evidence; keep collecting the 10-day A/B window.
- Next action: Continue A/B evidence collection; no parameter activation.

### M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow / continue_ab_evidence_collection

- Gate state: `continue_ab_collection_only`
- Outcome: ``
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: This row already has active rescue evidence; keep collecting the 10-day A/B window.
- Next action: Continue A/B evidence collection; no parameter activation.

### M10-PA-013-m14-modify-20260522 / continue_ab_evidence_collection

- Gate state: `continue_ab_collection_only`
- Outcome: ``
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: This row already has active rescue evidence; keep collecting the 10-day A/B window.
- Next action: Continue A/B evidence collection; no parameter activation.
