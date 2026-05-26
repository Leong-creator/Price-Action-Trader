# M14 Rescue Parameter Activation Gate

- Generated at: `2026-05-26T21:00:00Z`
- Fresh refresh observed: `False`
- Quote source: `fallback_quotes_only`
- Gate rows: `14`
- Shadow-review candidates: `0`
- First-ledger ready rows: `0`
- Waiting for fresh refresh: `13`
- Evidence failed: `0`
- Parameter mutation allowed: `0`
- Boundary: read-only gate; no parameter mutation, no registry/account-spec/broker-readiness mutation, no broker/live, no manual M12.37 once-mode.

## Plain Result

Parameter activation gate checked 14 experiment rows. Fresh refresh observed: False with quote_source=fallback_quotes_only. Shadow-review candidates: 0; first-ledger ready rows: 0; waiting for fresh refresh: 13; evidence failed: 0. Implementation mutation, parameter mutation, M13 registry mutation, M12 account-spec mutation, broker readiness mutation, broker connection, real orders, live execution, paper approval, and manual M12.37 once-mode remain disabled.

## Gate Rows

### M10-PA-001-m14-modify-20260522 / fresh_quote_gate_recheck

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-002-m14-modify-20260522 / fresh_quote_gate_recheck

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-004-MBF-QC-m14-modify-20260522 / fresh_quote_gate_recheck

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-005 / cooldown_quality_veto_shadow

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-005 / exposure_ranker_shadow

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-007-m14-modify-20260522 / fresh_quote_gate_recheck

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-008 / quantity_cap_shadow

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-008-broker-risk-cap-shadow / ledger_path_mapping_audit

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-009-m14-modify-20260522 / fresh_quote_gate_recheck

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-012-m14-modify-20260522 / target_stop_reward_geometry_shadow

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow / ledger_path_mapping_audit

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-013-m14-modify-20260522 / parent_detector_timeframe_mapping_review

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M12-FTD-001-m14-modify-20260522 / fresh_quote_gate_recheck

- Gate state: `waiting_for_m12_47_fresh_refresh`
- Outcome: `waiting_for_m12_47_fresh_refresh`
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: No fresh M12.47-owned refresh is visible yet.
- Next action: Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.

### M10-PA-011-ORB-R1 / continue_ab_evidence_collection

- Gate state: `continue_ab_collection_only`
- Outcome: ``
- Shadow-review candidate: `False`
- Parameter mutation allowed: `False`
- Reason: This row already has active rescue evidence; keep collecting the 10-day A/B window.
- Next action: Continue A/B evidence collection; no parameter activation.
