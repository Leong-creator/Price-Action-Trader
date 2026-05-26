# M14.2 Broker Blocker Rule Shadow Evidence

- Generated at: `2026-05-26T22:05:00Z`
- Source A/B prep rows: `3`
- Rule shadow evidence rows: `2`
- Exposure-ranker rules: `1`
- Cooldown/quality rules: `1`
- Runtime registrations: `0`
- Boundary: rule-only evidence; no runtime registration, registry mutation, account spec mutation, or broker readiness mutation.

## Strategy Evidence

### M10-PA-005

- Symbols: `XLV, XLY`
- Rule shadow rows: `2`
- Rule families: `{'cooldown_quality_veto': 1, 'portfolio_exposure_ranker': 1}`
- Original blocked rows preserved: `2`
- Next action: M10-PA-005: observe exposure ranking and cooldown/quality veto evidence together; do not create a runtime or unblock broker readiness.

## Evidence Rows

### M10-PA-005 / XLV / 5m

- Rule family: `cooldown_quality_veto`
- Shadow decision: `preserve_loss_streak_halt_and_veto_lower_quality_later_entries`
- Evidence status: `ready_for_next_internal_sim_refresh`
- Source reason codes: `['consecutive_losses_limit']`
- Quantity / risk / notional: `137.534 / 55.01 / 20616.35`
- Would create runtime: `False`
- Original readiness remains blocked: `True`
- Comparison contract: Preserve the loss-streak halt and compare later same-session entries against cooldown/quality-veto checks; the blocked source row remains blocked.
- Next action: Keep the halt active and collect later same-session veto evidence after fresh ledger rows exist.

### M10-PA-005 / XLY / 5m

- Rule family: `portfolio_exposure_ranker`
- Shadow decision: `defer_until_exposure_headroom_returns`
- Evidence status: `ready_for_next_internal_sim_refresh`
- Source reason codes: `['max_total_exposure_exceeded']`
- Quantity / risk / notional: `173.6422 / 36.46 / 20741.56`
- Would create runtime: `False`
- Original readiness remains blocked: `True`
- Comparison contract: Compare future same-strategy internal-sim signals by total exposure headroom and rank; lower-ranked entries remain deferred until headroom exists.
- Next action: Observe the next fresh internal-sim refresh and compare ranking/defer decisions without creating a runtime.

## Summary

Broker-blocker rule-only shadow evidence opened 2 rows from 3 A/B prep rows: 1 exposure-ranker rule and 1 cooldown/quality rule. Runtime registrations: 0; original blocked rows preserved: 2. No M13 registry, M12 account specs, broker readiness, broker connection, real order, live execution, or paper approval is changed.
