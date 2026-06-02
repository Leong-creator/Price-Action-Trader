# M14 Rescue Post-Refresh Outcome Review

- Generated at: `2026-06-01T17:29:00Z`
- Fresh refresh observed: `True`
- Quote source: `longbridge_quote_readonly`
- Scan date / latest ledger date: `2026-06-01 / 2026-06-01`
- Watch rows: `6`
- Passed or evidence observed: `3`
- Waiting: `0`
- Failed: `3`
- Manual M12.37 once-mode allowed: `False`
- Boundary: read-only review; no registry/account-spec/broker readiness mutation, no broker connection, no real order, no live execution.

## Plain Result

Post-refresh outcome review checked 6 rescue watch rows; a fresh M12.47 refresh is visible. Passed/evidence observed: 3; waiting: 0; failed: 3. First-ledger passed 0, fresh-quote rechecks passed 0, broker-rule evidence observed 2, target/stop shadow passed 1. No parameter change, registry mutation, account-spec mutation, broker readiness mutation, broker connection, real order, live execution, or paper approval is enabled.

## Outcome Rows

### M10-PA-005 / M10-PA-005-5m

- Family: `broker_rule_shadow_recheck`
- Status: `evidence_observed`
- Current signal/source rows: `79 / 79`
- Current ledger rows: `2 signal / 33 account`
- Comparable broker rows: `1`
- Next action: Record rule-only comparison evidence; keep original broker readiness rows unchanged.

### M10-PA-005 / M10-PA-005-5m

- Family: `broker_rule_shadow_recheck`
- Status: `evidence_observed`
- Current signal/source rows: `79 / 79`
- Current ledger rows: `2 signal / 33 account`
- Comparable broker rows: `1`
- Next action: Record rule-only comparison evidence; keep original broker readiness rows unchanged.

### M10-PA-012-m14-modify-20260522 / M10-PA-012-m14-modify-20260522-5m

- Family: `target_stop_shadow_compare`
- Status: `passed`
- Current signal/source rows: `0 / 0`
- Current ledger rows: `1 signal / 1 account`
- Comparable broker rows: `0`
- Next action: Compare normalized target/stop shadow ledger against frozen rescue runtime.

### M10-PA-002-m14-modify-20260522 / M10-PA-002-m14-modify-20260522-1d

- Family: `parent_detector_evidence_wait`
- Status: `still_waiting_parent_detector_after_fresh_refresh`
- Current signal/source rows: `0 / 0`
- Current ledger rows: `1 signal / 1 account`
- Comparable broker rows: `0`
- Next action: Keep same-timeframe wait; do not hard-map across timeframes.

### M10-PA-008-broker-risk-cap-shadow / M10-PA-008-broker-risk-cap-shadow-1d

- Family: `parent_detector_evidence_wait`
- Status: `still_waiting_parent_detector_after_fresh_refresh`
- Current signal/source rows: `0 / 0`
- Current ledger rows: `1 signal / 1 account`
- Comparable broker rows: `0`
- Next action: Keep same-timeframe wait; do not hard-map across timeframes.

### M10-PA-009-m14-modify-20260522 / M10-PA-009-m14-modify-20260522-1d

- Family: `parent_detector_evidence_wait`
- Status: `still_waiting_parent_detector_after_fresh_refresh`
- Current signal/source rows: `0 / 0`
- Current ledger rows: `1 signal / 1 account`
- Comparable broker rows: `0`
- Next action: Keep same-timeframe wait; do not hard-map across timeframes.
