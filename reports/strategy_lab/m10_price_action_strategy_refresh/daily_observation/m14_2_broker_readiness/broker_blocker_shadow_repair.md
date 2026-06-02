# M14.2 Broker Blocker Shadow Repair Plan

- Generated at: `2026-06-01T17:29:00Z`
- Source blocked rows: `3`
- Shadow actions: `{'apply_quantity_cap': 1, 'defer_until_exposure_frees': 1, 'keep_loss_streak_halt': 1}`
- Shadow statuses: `{'defer_not_repair': 2, 'shadow_repair_candidate': 1}`
- Boundary: original readiness rows remain blocked; no broker connection, no real orders, no live execution.

## Strategy Plan

### M10-PA-005

- Blocked rows: `2`
- Symbols: `XLV, XLY`
- Shadow actions: `{'defer_until_exposure_frees': 1, 'keep_loss_streak_halt': 1}`
- Statuses: `{'defer_not_repair': 2}`
- Next action: M10-PA-005: do not add entries after the halt; test cooldown and quality veto in the next internal-sim refresh.

### M10-PA-008

- Blocked rows: `1`
- Symbols: `ADBE`
- Shadow actions: `{'apply_quantity_cap': 1}`
- Statuses: `{'shadow_repair_candidate': 1}`
- Next action: M10-PA-008: add a quantity-cap shadow row and require new M13/M14 evidence before any readiness change.

## Row Actions

### M10-PA-005 / XLV / 5m

- Original reasons: `['consecutive_losses_limit']`
- Shadow action: `keep_loss_streak_halt`
- Status: `defer_not_repair`
- Quantity source/proposed/delta: `137.534 / 0 / 137.534`
- Risk source/proposed/delta: `55.01 / 0 / 55.01`
- Notional source/proposed/delta: `20616.35 / 0 / 20616.35`
- Original readiness remains blocked: `True`
- Action: Keep the halt active; shadow-test same-session cooldown and a quality veto before allowing later simulated entries.

### M10-PA-005 / XLY / 5m

- Original reasons: `['max_total_exposure_exceeded']`
- Shadow action: `defer_until_exposure_frees`
- Status: `defer_not_repair`
- Quantity source/proposed/delta: `173.6422 / 0 / 173.6422`
- Risk source/proposed/delta: `36.46 / 0 / 36.46`
- Notional source/proposed/delta: `20741.56 / 0 / 20741.56`
- Original readiness remains blocked: `True`
- Action: Do not force this entry through; shadow-test ranking so this signal waits for exposure headroom or loses to higher-ranked signals.

### M10-PA-008 / ADBE / 1d

- Original reasons: `['max_risk_per_order_exceeded']`
- Shadow action: `apply_quantity_cap`
- Status: `shadow_repair_candidate`
- Quantity source/proposed/delta: `5.2469 / 5.2083 / 0.0386`
- Risk source/proposed/delta: `100.74 / 100 / 0.74`
- Notional source/proposed/delta: `1290.16 / 1280.67 / 9.49`
- Original readiness remains blocked: `True`
- Action: Run a simulated-only quantity-cap A/B row; keep the original dry-run row blocked until fresh ledger evidence confirms the cap.

## Summary

M14.2 shadow repair plan prepared 3 blocked-row actions across 2 strategies: 1 quantity-cap candidate, 1 exposure deferral, 1 cooldown halt. Original broker readiness rows remain blocked; no broker connection, real order, live execution, or paper-trading approval is enabled.
