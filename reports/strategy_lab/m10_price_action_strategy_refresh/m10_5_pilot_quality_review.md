# M10.5 Pilot Quality Review

## Summary

- Input baseline: M10 clean-room frozen catalog, M10.3 specs, and M10.4 Wave A pilot artifacts.
- M10.4 不证明盈利，也不证明任何策略可升级或可实盘。
- M10.4 only shows that the Wave A specs and output plumbing can continue into read-only observation planning.
- All `14` strategy/timeframe combinations ended with `continue_testing`.
- Dataset availability was complete for the pilot: `available_count=16 / deferred_count=0`.

## Data Lineage

- Daily default window: `2010-06-29 ~ 2026-04-21`.
- `1d` and `5m` are recorded as `native_cache`.
- `15m` and `1h` must remain labeled as `derived_from_5m`; they must not be presented as native cached datasets.
- M10.5 does not configure a live read-only feed. Observation inputs remain `observation_input_deferred` until a separate read-only input plan is approved.

## Candidate Density Review

Definition breadth review threshold: `candidate_events_per_1000_bars > 100`.

| strategy | timeframe | candidates | trades | candidates / 1000 bars | quality flag | M10.5 action |
|---|---:|---:|---:|---:|---|---|
| M10-PA-001 | 1d | 1518 | 1518 | 95.43 | normal_density_review | continue observation planning |
| M10-PA-001 | 1h | 1011 | 1011 | 82.12 | normal_density_review | continue observation planning |
| M10-PA-001 | 15m | 4331 | 4331 | 81.14 | normal_density_review | continue observation planning |
| M10-PA-001 | 5m | 12452 | 12452 | 77.76 | normal_density_review | continue observation planning |
| M10-PA-002 | 1d | 1196 | 1196 | 75.19 | normal_density_review | continue observation planning |
| M10-PA-002 | 1h | 814 | 814 | 66.11 | normal_density_review | continue observation planning |
| M10-PA-002 | 15m | 3534 | 3534 | 66.21 | normal_density_review | continue observation planning |
| M10-PA-002 | 5m | 10759 | 10759 | 67.18 | normal_density_review | continue observation planning |
| M10-PA-005 | 1d | 1481 | 1481 | 93.10 | normal_density_review | continue observation planning |
| M10-PA-005 | 1h | 1469 | 1469 | 119.31 | definition_breadth_review | review event definition before observation |
| M10-PA-005 | 15m | 7511 | 7511 | 140.72 | definition_breadth_review | review event definition before observation |
| M10-PA-005 | 5m | 23881 | 23881 | 149.12 | definition_breadth_review | review event definition before observation |
| M10-PA-012 | 15m | 1762 | 1762 | 33.01 | normal_density_review | continue observation planning |
| M10-PA-012 | 5m | 1900 | 1900 | 11.86 | normal_density_review | continue observation planning |

## Review Notes

- `M10-PA-005` on `1h / 15m / 5m` is not rejected by this review, but its event definition is broad enough to require `definition_breadth_review`.
- No result is interpreted from PnL or cash performance.
- M10.5 should only decide whether the observation design is structurally ready, whether the definition needs tightening, or whether a visual/manual review is needed.
