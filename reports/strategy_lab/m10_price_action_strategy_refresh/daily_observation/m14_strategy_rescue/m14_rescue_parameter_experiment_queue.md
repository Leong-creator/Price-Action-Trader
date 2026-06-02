# M14 Rescue Parameter Experiment Queue

- Generated at: `2026-06-01T17:29:00Z`
- Project stage: `M14 stable strategy testing + M14.2 broker readiness dry-run scaffold`
- Fresh refresh observed: `True`
- Quote source: `longbridge_quote_readonly`
- Experiment rows: `14`
- Rescue/broker rows: `11/3`
- Allowed now: `0`
- Blocked until fresh refresh: `4`
- Shadow runtime wait first ledger: `0`
- Target/stop experiment rows: `1`
- Boundary: queue only; no parameter mutation, no registry/account-spec/broker-readiness mutation, no broker/live, no manual M12.37 once-mode.

## Plain Result

Parameter experiment queue prepared 14 rows: 11 rescue rows and 3 broker-blocker rows. Allowed-now changes remain 0; 4 rows wait for the next M12.47-owned fresh refresh and 0 rows wait for first M13 ledger evidence. The queue only defines shadow/review families; it does not mutate M13 registry, M12 account specs, broker readiness, broker connection, paper approval, live execution, real orders, or manual M12.37 once-mode.

## Experiment Rows

### M10-PA-001-m14-modify-20260522 / signal_to_account_bridge_audit

- Priority: `P0`
- Issue: `signal_generated_no_account_operation` / ``
- Status: `review_only`
- Allowed now: `False`
- Candidate parameter family: `signal_account_bridge_mapping`
- Change scope: `signal_to_account_operation_path`
- Activation condition: Signal ledger exists but account operation remains absent after the next refresh.
- Required evidence: Signal-to-account bridge trace.; M13 account ledger proof or explicit no-op reason.; No parameter change before bridge path is explained.

### M10-PA-002-m14-modify-20260522 / parent_detector_timeframe_mapping_review

- Priority: `P0`
- Issue: `zero_signal_after_connection` / `parent_detector_zero_signal_for_timeframe`
- Status: `blocked_until_parent_detector_evidence`
- Allowed now: `False`
- Candidate parameter family: `same_timeframe_parent_detector_mapping`
- Change scope: `same_timeframe_parent_detector`
- Activation condition: Parent detector produces same-timeframe source rows in a fresh run.
- Required evidence: Same-timeframe parent detector evidence.; No cross-timeframe remap without a separate detector redesign review.; 10 rescue A/B trading days after a mapped variant exists.

### M10-PA-005 / cooldown_quality_veto_shadow

- Priority: `P0`
- Issue: `broker_dry_run_blocker` / `consecutive_losses_limit`
- Status: `blocked_until_fresh_refresh`
- Allowed now: `False`
- Candidate parameter family: `cooldown_quality_veto`
- Change scope: `cooldown_quality_veto`
- Activation condition: Internal-sim dry-run preserves loss-streak halt and shows later entries would pass a stricter quality veto.
- Required evidence: Cooldown state remains active where required.; Quality-veto comparison for later same-session entries.; No override of consecutive-loss protection.

### M10-PA-005 / exposure_ranker_shadow

- Priority: `P0`
- Issue: `broker_dry_run_blocker` / `max_total_exposure_exceeded`
- Status: `blocked_until_fresh_refresh`
- Allowed now: `False`
- Candidate parameter family: `portfolio_exposure_ranker`
- Change scope: `portfolio_exposure_ordering`
- Activation condition: Internal-sim dry-run proves exposure ordering or deferral reduces total exposure blockers.
- Required evidence: Exposure-ranked comparison row in internal simulation.; No skipped risk gate or forced readiness unblock.; Decision log explaining kept, deferred, or rejected entries.

### M10-PA-008 / quantity_cap_shadow

- Priority: `P0`
- Issue: `broker_dry_run_blocker` / `max_risk_per_order_exceeded`
- Status: `blocked_until_fresh_refresh`
- Allowed now: `False`
- Candidate parameter family: `position_size_quantity_cap`
- Change scope: `position_sizing_risk_cap`
- Activation condition: Internal-sim dry-run shows risk <= 100 after sizing cap without unblocking broker readiness.
- Required evidence: Same signal with capped quantity in internal simulation.; Risk amount at or below 100.; Original broker readiness row remains blocked until explicit approval.

### M10-PA-008-broker-risk-cap-shadow / parent_detector_timeframe_mapping_review

- Priority: `P0`
- Issue: `zero_signal_after_connection` / `parent_detector_zero_signal_for_timeframe`
- Status: `blocked_until_parent_detector_evidence`
- Allowed now: `False`
- Candidate parameter family: `same_timeframe_parent_detector_mapping`
- Change scope: `same_timeframe_parent_detector`
- Activation condition: Parent detector produces same-timeframe source rows in a fresh run.
- Required evidence: Same-timeframe parent detector evidence.; No cross-timeframe remap without a separate detector redesign review.; 10 rescue A/B trading days after a mapped variant exists.

### M10-PA-009-m14-modify-20260522 / parent_detector_timeframe_mapping_review

- Priority: `P0`
- Issue: `zero_signal_after_connection` / `parent_detector_zero_signal_for_timeframe`
- Status: `blocked_until_parent_detector_evidence`
- Allowed now: `False`
- Candidate parameter family: `same_timeframe_parent_detector_mapping`
- Change scope: `same_timeframe_parent_detector`
- Activation condition: Parent detector produces same-timeframe source rows in a fresh run.
- Required evidence: Same-timeframe parent detector evidence.; No cross-timeframe remap without a separate detector redesign review.; 10 rescue A/B trading days after a mapped variant exists.

### M10-PA-012-m14-modify-20260522 / target_stop_reward_geometry_shadow

- Priority: `P0`
- Issue: `zero_signal_after_connection` / `reward_filter_blocks_all`
- Status: `blocked_until_fresh_refresh`
- Allowed now: `False`
- Candidate parameter family: `target_stop_geometry_normalization_not_lowering_frozen_min_r`
- Change scope: `target_stop_normalization_reward_r`
- Activation condition: Fresh refresh provides comparable ledger evidence for the frozen runtime and normalized target/stop shadow.
- Required evidence: Frozen rescue runtime remains unchanged.; Normalized target/stop shadow runtime emits its own M13 ledger evidence.; 10 rescue A/B trading days before any min-R or target/stop policy decision.

### M12-FTD-001-m14-modify-20260522 / signal_to_account_bridge_audit

- Priority: `P0`
- Issue: `signal_generated_no_account_operation` / ``
- Status: `review_only`
- Allowed now: `False`
- Candidate parameter family: `signal_account_bridge_mapping`
- Change scope: `signal_to_account_operation_path`
- Activation condition: Signal ledger exists but account operation remains absent after the next refresh.
- Required evidence: Signal-to-account bridge trace.; M13 account ledger proof or explicit no-op reason.; No parameter change before bridge path is explained.

### M10-PA-004-MBF-QC-m14-modify-20260522 / continue_ab_evidence_collection

- Priority: `P2`
- Issue: `collect_more_ab_evidence` / ``
- Status: `collect_more_ab_evidence`
- Allowed now: `False`
- Candidate parameter family: `none_ab_evidence_only`
- Change scope: `no_parameter_change`
- Activation condition: Current rescue runtime keeps collecting its own 10-day A/B evidence.
- Required evidence: Comparable baseline-vs-rescue ledger rows.; Full 10 rescue A/B trading-day window.; Manual M14 review before promote/modify/reject.

### M10-PA-007-m14-modify-20260522 / continue_ab_evidence_collection

- Priority: `P2`
- Issue: `collect_more_ab_evidence` / ``
- Status: `collect_more_ab_evidence`
- Allowed now: `False`
- Candidate parameter family: `none_ab_evidence_only`
- Change scope: `no_parameter_change`
- Activation condition: Current rescue runtime keeps collecting its own 10-day A/B evidence.
- Required evidence: Comparable baseline-vs-rescue ledger rows.; Full 10 rescue A/B trading-day window.; Manual M14 review before promote/modify/reject.

### M10-PA-011-ORB-R1 / continue_ab_evidence_collection

- Priority: `P2`
- Issue: `collect_more_ab_evidence` / ``
- Status: `collect_more_ab_evidence`
- Allowed now: `False`
- Candidate parameter family: `none_ab_evidence_only`
- Change scope: `no_parameter_change`
- Activation condition: Current rescue runtime keeps collecting its own 10-day A/B evidence.
- Required evidence: Comparable baseline-vs-rescue ledger rows.; Full 10 rescue A/B trading-day window.; Manual M14 review before promote/modify/reject.

### M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow / continue_ab_evidence_collection

- Priority: `P2`
- Issue: `collect_more_ab_evidence` / ``
- Status: `collect_more_ab_evidence`
- Allowed now: `False`
- Candidate parameter family: `none_ab_evidence_only`
- Change scope: `no_parameter_change`
- Activation condition: Current rescue runtime keeps collecting its own 10-day A/B evidence.
- Required evidence: Comparable baseline-vs-rescue ledger rows.; Full 10 rescue A/B trading-day window.; Manual M14 review before promote/modify/reject.

### M10-PA-013-m14-modify-20260522 / continue_ab_evidence_collection

- Priority: `P2`
- Issue: `collect_more_ab_evidence` / `strict_quality_filter_blocks_all`
- Status: `collect_more_ab_evidence`
- Allowed now: `False`
- Candidate parameter family: `none_ab_evidence_only`
- Change scope: `no_parameter_change`
- Activation condition: Current rescue runtime keeps collecting its own 10-day A/B evidence.
- Required evidence: Comparable baseline-vs-rescue ledger rows.; Full 10 rescue A/B trading-day window.; Manual M14 review before promote/modify/reject.
