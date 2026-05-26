# M14 Rescue Next Refresh Readiness

- Generated at: `2026-05-26T22:30:00Z`
- Watch rows: `13`
- Fresh-quote rechecks: `7`
- First-ledger watches: `2`
- Broker-rule shadow rechecks: `2`
- Target/stop shadow comparisons: `1`
- Parent-detector waits: `1`
- Parameter changes allowed now: `0`
- Boundary: next-refresh readiness only; no runtime registration, registry mutation, account spec mutation, or broker readiness mutation.

## Watch Rows

### M10-PA-005 / M10-PA-005-5m

- Priority: `P0`
- Family: `broker_rule_shadow_recheck`
- State: `ready_for_next_m12_47_refresh`
- Trigger: Next internal-sim risk check produces comparable PA005 broker-blocker rows.
- Expected evidence: Preserve the loss-streak halt and compare later same-session entries against cooldown/quality-veto checks; the blocked source row remains blocked.
- Pass action: Record whether exposure ranking or cooldown/quality veto would reduce blockers without unblocking readiness.
- Fail action: Keep original broker readiness blocked and refine only the rule contract.
- Parameter change allowed now: `False`

### M10-PA-005 / M10-PA-005-5m

- Priority: `P0`
- Family: `broker_rule_shadow_recheck`
- State: `ready_for_next_m12_47_refresh`
- Trigger: Next internal-sim risk check produces comparable PA005 broker-blocker rows.
- Expected evidence: Compare future same-strategy internal-sim signals by total exposure headroom and rank; lower-ranked entries remain deferred until headroom exists.
- Pass action: Record whether exposure ranking or cooldown/quality veto would reduce blockers without unblocking readiness.
- Fail action: Keep original broker readiness blocked and refine only the rule contract.
- Parameter change allowed now: `False`

### M10-PA-008-broker-risk-cap-shadow / M10-PA-008-broker-risk-cap-shadow-1d

- Priority: `P0`
- Family: `first_rescue_ledger_watch`
- State: `ready_for_next_m12_47_refresh`
- Trigger: Next M12.47/M13 refresh writes the first rescue signal/account ledger row.
- Expected evidence: M13 signal/account ledger row count becomes greater than zero for this rescue runtime.
- Pass action: Start counting its own 10 rescue A/B trading days from the fresh ledger evidence.
- Fail action: Audit M13 registry, M12 account specs input mapping, and ledger write path.
- Parameter change allowed now: `False`

### M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow / M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow-5m

- Priority: `P0`
- Family: `first_rescue_ledger_watch`
- State: `ready_for_next_m12_47_refresh`
- Trigger: Next M12.47/M13 refresh writes the first rescue signal/account ledger row.
- Expected evidence: M13 signal/account ledger row count becomes greater than zero for this rescue runtime.
- Pass action: Start counting its own 10 rescue A/B trading days from the fresh ledger evidence.
- Fail action: Audit M13 registry, M12 account specs input mapping, and ledger write path.
- Parameter change allowed now: `False`

### M10-PA-001-m14-modify-20260522 / M10-PA-001-m14-modify-20260522-1d

- Priority: `P0`
- Family: `fresh_quote_recheck`
- State: `ready_for_next_m12_47_refresh`
- Trigger: Next M12.47-owned fresh Longbridge quote refresh produces current source rows.
- Expected evidence: 12 eligible candidates if the stale quote gate clears.
- Pass action: Continue 10-day rescue A/B evidence collection without changing parameters.
- Fail action: Audit quote-refresh path before changing detector thresholds or risk settings.
- Parameter change allowed now: `False`

### M10-PA-002-m14-modify-20260522 / M10-PA-002-m14-modify-20260522-1d

- Priority: `P0`
- Family: `fresh_quote_recheck`
- State: `ready_for_next_m12_47_refresh`
- Trigger: Next M12.47-owned fresh Longbridge quote refresh produces current source rows.
- Expected evidence: 2 eligible candidates if the stale quote gate clears.
- Pass action: Continue 10-day rescue A/B evidence collection without changing parameters.
- Fail action: Audit quote-refresh path before changing detector thresholds or risk settings.
- Parameter change allowed now: `False`

### M10-PA-004-MBF-QC-m14-modify-20260522 / M10-PA-004-MBF-QC-m14-modify-20260522-1d

- Priority: `P0`
- Family: `fresh_quote_recheck`
- State: `ready_for_next_m12_47_refresh`
- Trigger: Next M12.47-owned fresh Longbridge quote refresh produces current source rows.
- Expected evidence: 1 eligible candidates if the stale quote gate clears.
- Pass action: Continue 10-day rescue A/B evidence collection without changing parameters.
- Fail action: Audit quote-refresh path before changing detector thresholds or risk settings.
- Parameter change allowed now: `False`

### M10-PA-007-m14-modify-20260522 / M10-PA-007-m14-modify-20260522-1d

- Priority: `P0`
- Family: `fresh_quote_recheck`
- State: `ready_for_next_m12_47_refresh`
- Trigger: Next M12.47-owned fresh Longbridge quote refresh produces current source rows.
- Expected evidence: 5 eligible candidates if the stale quote gate clears.
- Pass action: Continue 10-day rescue A/B evidence collection without changing parameters.
- Fail action: Audit quote-refresh path before changing detector thresholds or risk settings.
- Parameter change allowed now: `False`

### M10-PA-009-m14-modify-20260522 / M10-PA-009-m14-modify-20260522-1d

- Priority: `P0`
- Family: `fresh_quote_recheck`
- State: `ready_for_next_m12_47_refresh`
- Trigger: Next M12.47-owned fresh Longbridge quote refresh produces current source rows.
- Expected evidence: 1 eligible candidates if the stale quote gate clears.
- Pass action: Continue 10-day rescue A/B evidence collection without changing parameters.
- Fail action: Audit quote-refresh path before changing detector thresholds or risk settings.
- Parameter change allowed now: `False`

### M10-PA-013-m14-modify-20260522 / M10-PA-013-m14-modify-20260522-5m

- Priority: `P0`
- Family: `fresh_quote_recheck`
- State: `ready_for_next_m12_47_refresh`
- Trigger: Next M12.47-owned fresh Longbridge quote refresh produces current source rows.
- Expected evidence: 39 eligible candidates if the stale quote gate clears.
- Pass action: Continue 10-day rescue A/B evidence collection without changing parameters.
- Fail action: Audit quote-refresh path before changing detector thresholds or risk settings.
- Parameter change allowed now: `False`

### M12-FTD-001-m14-modify-20260522 / M12-FTD-001-m14-modify-20260522-1d

- Priority: `P0`
- Family: `fresh_quote_recheck`
- State: `ready_for_next_m12_47_refresh`
- Trigger: Next M12.47-owned fresh Longbridge quote refresh produces current source rows.
- Expected evidence: 3 eligible candidates if the stale quote gate clears.
- Pass action: Continue 10-day rescue A/B evidence collection without changing parameters.
- Fail action: Audit quote-refresh path before changing detector thresholds or risk settings.
- Parameter change allowed now: `False`

### M10-PA-012-m14-modify-20260522 / M10-PA-012-m14-modify-20260522-5m

- Priority: `P0`
- Family: `target_stop_shadow_compare`
- State: `covered_by_shadow_runtime_wait_refresh`
- Trigger: Next fresh run can compare the frozen rescue runtime with the normalized target/stop shadow runtime.
- Expected evidence: Frozen runtime remains unchanged; normalized shadow runtime should produce its own M13 ledger evidence.
- Pass action: Compare the normalized 1.0R shadow ledger against the frozen PA012 rescue runtime.
- Fail action: Inspect target/stop generation again; do not lower the frozen reward threshold directly.
- Parameter change allowed now: `False`

### M10-PA-013-m14-modify-20260522 / M10-PA-013-m14-modify-20260522-1d

- Priority: `P1`
- Family: `parent_detector_evidence_wait`
- State: `wait_same_timeframe_parent_evidence`
- Trigger: Parent detector produces same-timeframe source rows in a fresh run.
- Expected evidence: Parent detector must show valid same-timeframe source rows before rescue remapping.
- Pass action: Only then evaluate a same-timeframe rescue variant; do not remap across timeframes.
- Fail action: Keep waiting for parent evidence or start a separate detector redesign review.
- Parameter change allowed now: `False`

## Summary

Next-refresh rescue readiness tracks 13 rows: 7 fresh-quote rechecks, 2 first-ledger watches, 2 PA005 broker-rule shadow rechecks, 1 target/stop shadow comparisons, and 1 parent-detector waits. Parameter changes allowed now: 0. No registry, account-spec, broker readiness, broker connection, real order, live execution, or paper approval is changed.
