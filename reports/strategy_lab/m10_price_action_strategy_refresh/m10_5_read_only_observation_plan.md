# M10.5 Read-only Observation Plan

## Summary

- This plan converts M10.4 Wave A pilot outputs into a read-only observation design.
- It does not start live observation, connect to a broker, place orders, or approve M11 paper trading.
- M10.4 outcomes remain quality-routing signals only: every Wave A strategy/timeframe is still `continue_testing`.

## Candidate Scope

| strategy | timeframes | observation cadence |
|---|---|---|
| M10-PA-001 | `1d / 1h / 15m / 5m` | `1d` after close; intraday at regular-session bar close |
| M10-PA-002 | `1d / 1h / 15m / 5m` | `1d` after close; intraday at regular-session bar close |
| M10-PA-005 | `1d / 1h / 15m / 5m` | `1d` after close; intraday at regular-session bar close |
| M10-PA-012 | `15m / 5m` | intraday at regular-session bar close |

Excluded from M10.5 read-only queue:

- Visual-first: `M10-PA-003/004/007/008/009/010/011`
- Wave B candidate: `M10-PA-013`
- Supporting-only: `M10-PA-014/015`
- Research-only: `M10-PA-006/016`

## Observation Event Requirements

Each future observation event must include:

- strategy id, symbol, timeframe, and bar timestamp
- event or skip code
- hypothetical entry, stop, and target values when applicable
- source refs and M10.3 spec ref
- data source and lineage
- review status from the M10.5 allowed status set

Allowed review status values:

- `needs_definition_fix`
- `needs_visual_review`
- `continue_testing`
- `reject_for_now`
- `continue_observation`

## Data And Timing Rules

- `1d` is observed only after the regular session close.
- `1h / 15m / 5m` are observed only after regular-session bar close.
- `15m / 1h` lineage must remain `derived_from_5m` if sourced from the current M10.4 data approach.
- M10.5 has no configured real-time read-only input. Until a separate input plan exists, the observation input status is `observation_input_deferred`.
- Missing input must create a deferred observation artifact, not synthetic events.

## Quality Gates

- Candidate density above `100` events per `1000` bars is marked `definition_breadth_review`.
- `M10-PA-005` on `1h / 15m / 5m` must receive definition breadth review before any future observation run.
- PnL, cash result, or historical pilot performance must not be used as the approval basis.
- Human review is required before any M11 paper gate discussion.

## Boundary

- No broker connection.
- No real account.
- No live execution.
- No real orders.
- No strategy status upgrade.
