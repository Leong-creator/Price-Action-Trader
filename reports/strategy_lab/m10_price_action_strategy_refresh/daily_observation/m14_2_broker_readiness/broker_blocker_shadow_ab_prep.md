# M14.2 Broker Blocker Shadow A/B Prep

- Generated at: `2026-06-01T17:29:00Z`
- Source shadow repair rows: `3`
- Runtime-registration candidates: `1`
- Rule-only shadow candidates: `2`
- Prep action counts: `{'prepare_cooldown_quality_veto_shadow_rule': 1, 'prepare_exposure_ranker_shadow_rule': 1, 'prepare_quantity_cap_shadow_runtime': 1}`
- Boundary: prep only; no registry mutation, no account spec mutation, no broker readiness mutation.

## Strategy Prep

### M10-PA-005

- Symbols: `XLV, XLY`
- Prep rows: `2`
- Runtime-registration candidates: `0`
- Rule-only candidates: `2`
- Prep actions: `{'prepare_cooldown_quality_veto_shadow_rule': 1, 'prepare_exposure_ranker_shadow_rule': 1}`
- Next action: M10-PA-005: keep loss-streak halt active and shadow-test cooldown/quality veto rules.

### M10-PA-008

- Symbols: `ADBE`
- Prep rows: `1`
- Runtime-registration candidates: `1`
- Rule-only candidates: `0`
- Prep actions: `{'prepare_quantity_cap_shadow_runtime': 1}`
- Next action: M10-PA-008: prepare a separate quantity-cap shadow runtime only after review; do not mutate baseline readiness.

## Prep Rows

### M10-PA-005 / XLV / 5m

- Prep action: `prepare_cooldown_quality_veto_shadow_rule`
- Prep status: `rule_only_prep_not_runtime`
- Proposed shadow strategy: `M10-PA-005-broker-cooldown-quality-shadow`
- Proposed shadow runtime: `none`
- Quantity source/proposed: `137.534 / 0`
- Risk source/proposed: `55.01 / 0`
- Original readiness remains blocked: `True`
- Hypothesis: Cooldown and quality-veto rules should preserve the loss-streak halt while testing whether later same-session entries can be filtered more cleanly.
- Next action: Do not create a runtime that bypasses the halt; keep the halt and test veto evidence after fresh ledger rows.

### M10-PA-005 / XLY / 5m

- Prep action: `prepare_exposure_ranker_shadow_rule`
- Prep status: `rule_only_prep_not_runtime`
- Proposed shadow strategy: `M10-PA-005-broker-exposure-ranker-shadow`
- Proposed shadow runtime: `none`
- Quantity source/proposed: `173.6422 / 0`
- Risk source/proposed: `36.46 / 0`
- Original readiness remains blocked: `True`
- Hypothesis: A portfolio exposure ranker should defer this signal until headroom exists instead of forcing an entry that would exceed total exposure.
- Next action: Keep this as rule-only shadow prep and compare later fresh internal-sim ranking decisions.

### M10-PA-008 / ADBE / 1d

- Prep action: `prepare_quantity_cap_shadow_runtime`
- Prep status: `ready_for_shadow_runtime_design`
- Proposed shadow strategy: `M10-PA-008-broker-risk-cap-shadow`
- Proposed shadow runtime: `M10-PA-008-broker-risk-cap-shadow-1d`
- Quantity source/proposed: `5.2469 / 5.2083`
- Risk source/proposed: `100.74 / 100`
- Original readiness remains blocked: `True`
- Hypothesis: Capping quantity to the existing risk limit can preserve the signal while reducing max_risk_per_order blocks; original broker readiness remains blocked until fresh A/B evidence exists.
- Next action: Register only after code review as a separate simulated A/B runtime; do not mutate the approved baseline.

## Summary

Broker-blocker shadow A/B prep converted 3 repair rows into 1 runtime-registration candidate and 2 rule-only shadow candidates. Risk-cap candidates: 1; exposure-ranker rules: 1; cooldown/quality rules: 1. No M13 registry, M12 account specs, broker readiness, broker connection, real order, live execution, or paper approval is changed.
