# M14.2 Broker Blocker Diagnostics

- Generated at: `2026-06-01T17:29:00Z`
- Blocked dry-run rows: `3`
- Blocked strategies: `2`
- Reason counts: `{'consecutive_losses_limit': 1, 'max_risk_per_order_exceeded': 1, 'max_total_exposure_exceeded': 1}`
- Diagnostic families: `{'loss_streak_cooldown_quality_veto': 1, 'portfolio_exposure_ranking': 1, 'quantity_cap_stop_geometry': 1}`
- Internal simulated risk cap: `100` per order; total exposure cap `25000`; max consecutive losses `2`
- Boundary: diagnostics only; rows remain blocked; no broker connection, no real orders, no live execution.

## Strategy Actions

### M10-PA-005

- Blocked rows: `2`
- Symbols: `XLV, XLY`
- Reasons: `{'consecutive_losses_limit': 1, 'max_total_exposure_exceeded': 1}`
- Diagnostic families: `{'loss_streak_cooldown_quality_veto': 1, 'portfolio_exposure_ranking': 1}`
- Next action: M10-PA-005: keep the loss-streak guard and shadow-test cooldown/quality veto before more simulated entries.

### M10-PA-008

- Blocked rows: `1`
- Symbols: `ADBE`
- Reasons: `{'max_risk_per_order_exceeded': 1}`
- Diagnostic families: `{'quantity_cap_stop_geometry': 1}`
- Next action: M10-PA-008: shadow-test quantity capping to max_risk_per_order before any broker-paper review.

## Blocked Rows

### M10-PA-005 / XLV / 5m

- Reason codes: `['consecutive_losses_limit']`
- Family: `loss_streak_cooldown_quality_veto`
- Entry/stop/target: `149.9 / 149.5 / 150.68`
- Quantity/risk/notional: `137.534 / 55.01 / 20616.35`
- Reward R: `1.95`
- Risk cap candidate quantity: `250`; delta `0`
- Shadow fix: `post_loss_cooldown_and_quality_veto_shadow`
- Action: Keep the loss-streak halt active and test a same-session cooldown or quality veto before allowing more simulated entries.

### M10-PA-005 / XLY / 5m

- Reason codes: `['max_total_exposure_exceeded']`
- Family: `portfolio_exposure_ranking`
- Entry/stop/target: `119.45 / 119.66 / 119.03`
- Quantity/risk/notional: `173.6422 / 36.46 / 20741.56`
- Reward R: `2`
- Risk cap candidate quantity: `476.1904`; delta `0`
- Shadow fix: `portfolio_exposure_ranker_shadow`
- Action: Shadow-test exposure allocation and signal ranking so lower-priority entries defer instead of increasing total exposure.

### M10-PA-008 / ADBE / 1d

- Reason codes: `['max_risk_per_order_exceeded']`
- Family: `quantity_cap_stop_geometry`
- Entry/stop/target: `245.89 / 265.09 / 207.49`
- Quantity/risk/notional: `5.2469 / 100.74 / 1290.16`
- Reward R: `2`
- Risk cap candidate quantity: `5.2083`; delta `0.0386`
- Shadow fix: `risk_budget_quantity_cap_without_setup_change`
- Action: Shadow-test a quantity cap to the existing max risk per order; do not raise the risk limit or change broker readiness status.

## Summary

M14.2 broker blocker diagnostics found 3 blocked dry-run rows across 2 strategies. Sizing candidates: 1; exposure ranking candidates: 1; cooldown candidates: 1. Rows stay blocked; no broker connection, real order, live execution, or paper-trading approval is enabled.
