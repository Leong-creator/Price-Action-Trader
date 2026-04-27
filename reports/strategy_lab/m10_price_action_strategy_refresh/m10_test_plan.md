# M10 Test Plan

## Boundaries

- M10 remains `paper / simulated` only.
- No real account, broker connection, live execution, or automated real order path is introduced.
- Daily, 1h, 15m, and 5m are independent test lines; daily is not a 5m auxiliary filter.
- Missing cross-source corroboration changes confidence and review order, not admission, when Brooks v2 or FangFangTu YouTube supports the strategy.

## Source Integrity

- Verify Brooks v2 `README.md`, `units/`, `evidence/`, `manifest.json`, `checksums.sha256`, and `assets_evidence_checksums.sha256` exist.
- Verify FangFangTu YouTube transcript and notes raw PDFs still resolve.
- Rebuild and validate source/chunk/atom/callable indexes after source ingestion.

## Clean-Room Guard

- M10 catalog generation reads only Brooks v2 manual transcript, FangFangTu YouTube transcript, FangFangTu notes, and reference-only ChatGPT summary.
- Legacy `PA-SC-*`, `SF-*`, old strategy cards, old specs, old triage, and old catalog are only read after catalog generation for comparison artifacts.

## Historical Backtest Queue

- M10.1 Wave A IDs: M10-PA-001, M10-PA-002, M10-PA-005, M10-PA-012
- `M10-PA-001`: `1d / 1h / 15m / 5m`.
- `M10-PA-002`: `1d / 1h / 15m / 5m`.
- `M10-PA-005`: `1d / 1h / 15m / 5m`.
- `M10-PA-012`: `15m / 5m`.
- Historical backtest output must include candidate events, skip/no-trade ledger, source ledger, cost/slippage sensitivity, per-symbol, per-regime, and failure-mode notes.
- M10.1 outcomes are limited to `needs_definition_fix`, `needs_visual_review`, `continue_testing`, or `reject_for_now`.
- Wave B is not executed in M10.1; `M10-PA-013` is reserved as a low-visual Wave B candidate, and visual strategies can join only after passing M10.2.

## M10.3 Backtest Spec Freeze

- M10.3 freezes executable specs for Wave A only: `backtest_specs/M10-PA-001.json`, `M10-PA-002.json`, `M10-PA-005.json`, `M10-PA-012.json`.
- The spec index is `m10_backtest_spec_index.json`; event definitions, skip rules, and cost/sample gates are tracked in dedicated ledgers.
- Cost sensitivity tiers are fixed at baseline `1 bps`, stress low `2 bps`, and stress high `5 bps`; fees remain `0` in this policy placeholder.
- Sample gates are fixed at at least 30 candidate events and 10 executed trades after skips per strategy/timeframe before interpreting test quality.
- M10.3 does not run backtests and does not permit `retain/promote` conclusions.

## Visual Review Queue

- Candidate IDs: M10-PA-003, M10-PA-004, M10-PA-007, M10-PA-008, M10-PA-009, M10-PA-010, M10-PA-011
- Visual golden case is not a global prerequisite. It applies only to the listed high-visual strategies.
- Each visual strategy needs 3 Brooks v2 positive cases, 1 counterexample, 1 boundary case, evidence image/source ref, pattern decision points, and OHLCV approximation risk notes.

## Research and Supporting Rules

- Research-only IDs: M10-PA-006, M10-PA-016
- Supporting-rule IDs: M10-PA-014, M10-PA-015
- Supporting rules can modify test reports and risk/target interpretation but cannot create standalone entry triggers in M10.

## Phase Order

1. Historical backtest on eligible OHLCV-approximable strategies.
2. Real-time read-only observation with no order path.
3. Paper trading only after backtest and observation gates pass.
4. Live approval remains out of M10 scope.
