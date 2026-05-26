# M14 Rescue External Reference Map

- Generated at: `2026-05-26T19:00:00Z`
- Project stage: `M14 stable strategy testing + M14.2 broker readiness dry-run scaffold`
- 10-day challenge complete: `True`
- Rescue rows mapped: `11`
- Broker blocker rows mapped: `2`
- P0 reference rows: `12`
- Next-refresh dependent checks: `13`
- Parameter changes allowed now: `0`
- Boundary: external projects are architecture references only; No copy trading, broker sync, external override, real orders, live execution, or manual M12.37 once-mode.

## Plain Result

External-reference map covered 11 rescue rows and 2 broker-blocker rows using 2 external projects as architecture references only. 13 checks still depend on the next M12.47-owned fresh refresh, parameter changes allowed now remain 0, and copy trading, external override, broker connection, real orders, live execution, paper approval, and manual M12.37 once-mode stay disabled.

## External Reference Patterns

### ai_trader_shadow_signal_scoreboard

- Project: `HKUDS/AI-Trader`
- URL: https://github.com/HKUDS/AI-Trader
- Allowed use: Use as a local shadow signal scoreboard and experiment-exposure ledger after M12.47-owned refreshes.
- Forbidden use: No copy trading, broker sync, external operations, or direct execution.

### tradingagents_role_decomposed_review

- Project: `TauricResearch/TradingAgents`
- URL: https://github.com/TauricResearch/TradingAgents
- Allowed use: Use as a local review checklist that separates technical evidence, bull/bear objections, risk, and portfolio constraints.
- Forbidden use: No external LLM decision can override local M13/M14 ledgers, risk gates, or manual approval.

### tradingagents_persistent_decision_log

- Project: `TauricResearch/TradingAgents`
- URL: https://github.com/TauricResearch/TradingAgents
- Allowed use: Use as a local audit trail for why a rescue parameter family is held, shadow-tested, promoted, modified, or rejected.
- Forbidden use: No automatic promotion, no parameter mutation, and no paper/live approval from an external review alone.

## Rescue Rows

### M10-PA-001-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Dominant zero-signal issue: `stale_quote_source_blocks_candidate`
- Patterns: `ai_trader_shadow_signal_scoreboard, tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Use a shadow signal scoreboard only after fresh M12.47 data; stale/fallback source rows cannot justify parameter changes.
- Pre-refresh action: Do not tune thresholds now; wait for fresh quote evidence and compare source/signal counts.
- Post-refresh check: Fresh quote run produces nonzero source or signal evidence without using fallback quotes.

### M10-PA-002-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Dominant zero-signal issue: `stale_quote_source_blocks_candidate`
- Patterns: `ai_trader_shadow_signal_scoreboard, tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Use a shadow signal scoreboard only after fresh M12.47 data; stale/fallback source rows cannot justify parameter changes.
- Pre-refresh action: Do not tune thresholds now; wait for fresh quote evidence and compare source/signal counts.
- Post-refresh check: Fresh quote run produces nonzero source or signal evidence without using fallback quotes.

### M10-PA-004-MBF-QC-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Dominant zero-signal issue: `stale_quote_source_blocks_candidate`
- Patterns: `ai_trader_shadow_signal_scoreboard, tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Use a shadow signal scoreboard only after fresh M12.47 data; stale/fallback source rows cannot justify parameter changes.
- Pre-refresh action: Do not tune thresholds now; wait for fresh quote evidence and compare source/signal counts.
- Post-refresh check: Fresh quote run produces nonzero source or signal evidence without using fallback quotes.

### M10-PA-007-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Dominant zero-signal issue: `stale_quote_source_blocks_candidate`
- Patterns: `ai_trader_shadow_signal_scoreboard, tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Use a shadow signal scoreboard only after fresh M12.47 data; stale/fallback source rows cannot justify parameter changes.
- Pre-refresh action: Do not tune thresholds now; wait for fresh quote evidence and compare source/signal counts.
- Post-refresh check: Fresh quote run produces nonzero source or signal evidence without using fallback quotes.

### M10-PA-008-broker-risk-cap-shadow

- Priority: `P0`
- Issue: `missing_rescue_ledger`
- Dominant zero-signal issue: ``
- Patterns: `ai_trader_shadow_signal_scoreboard, tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Treat external signal-sync ideas as a local ledger-chain checklist: registry, input spec, signal ledger, account ledger.
- Pre-refresh action: Prepare mapping audit fields now; actual pass/fail waits for the next M12.47-owned fresh refresh.
- Post-refresh check: A first M13 signal or account ledger row appears for the rescue runtime; then start its own 10-day evidence count.

### M10-PA-009-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Dominant zero-signal issue: `stale_quote_source_blocks_candidate`
- Patterns: `ai_trader_shadow_signal_scoreboard, tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Use a shadow signal scoreboard only after fresh M12.47 data; stale/fallback source rows cannot justify parameter changes.
- Pre-refresh action: Do not tune thresholds now; wait for fresh quote evidence and compare source/signal counts.
- Post-refresh check: Fresh quote run produces nonzero source or signal evidence without using fallback quotes.

### M10-PA-012-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Dominant zero-signal issue: `reward_filter_blocks_all`
- Patterns: `tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Use role-decomposed review to separate entry geometry, stop/target geometry, and reward/R policy before changing thresholds.
- Pre-refresh action: Keep frozen runtime unchanged; use the existing target/stop shadow runtime as the only local comparison hook.
- Post-refresh check: Normalized target/stop shadow runtime emits comparable M13 ledger evidence against the frozen rescue runtime.

### M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow

- Priority: `P0`
- Issue: `missing_rescue_ledger`
- Dominant zero-signal issue: ``
- Patterns: `ai_trader_shadow_signal_scoreboard, tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Treat external signal-sync ideas as a local ledger-chain checklist: registry, input spec, signal ledger, account ledger.
- Pre-refresh action: Prepare mapping audit fields now; actual pass/fail waits for the next M12.47-owned fresh refresh.
- Post-refresh check: A first M13 signal or account ledger row appears for the rescue runtime; then start its own 10-day evidence count.

### M10-PA-013-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Dominant zero-signal issue: `stale_quote_source_blocks_candidate`
- Patterns: `ai_trader_shadow_signal_scoreboard, tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Use a shadow signal scoreboard only after fresh M12.47 data; stale/fallback source rows cannot justify parameter changes.
- Pre-refresh action: Do not tune thresholds now; wait for fresh quote evidence and compare source/signal counts.
- Post-refresh check: Fresh quote run produces nonzero source or signal evidence without using fallback quotes.

### M12-FTD-001-m14-modify-20260522

- Priority: `P0`
- Issue: `zero_signal_after_connection`
- Dominant zero-signal issue: `stale_quote_source_blocks_candidate`
- Patterns: `ai_trader_shadow_signal_scoreboard, tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Use a shadow signal scoreboard only after fresh M12.47 data; stale/fallback source rows cannot justify parameter changes.
- Pre-refresh action: Do not tune thresholds now; wait for fresh quote evidence and compare source/signal counts.
- Post-refresh check: Fresh quote run produces nonzero source or signal evidence without using fallback quotes.

### M10-PA-011-ORB-R1

- Priority: `P2`
- Issue: `collect_more_ab_evidence`
- Dominant zero-signal issue: ``
- Patterns: `ai_trader_shadow_signal_scoreboard, tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Use a local scoreboard and decision log to keep baseline-vs-rescue evidence comparable until the 10-day rescue window is complete.
- Pre-refresh action: Keep collecting A/B evidence; no promotion or rejection before the 10-day rescue window is proven.
- Post-refresh check: Continue local A/B evidence collection and record the decision-log reason for hold/modify/reject.

## Broker Blocker Rows

### M10-PA-005

- Priority: `P0`
- Blocked count: `2`
- Reasons: `{'consecutive_losses_limit': 1, 'max_total_exposure_exceeded': 1}`
- Patterns: `tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Use a TradingAgents-style risk/portfolio split to decide whether the blocker is a sizing, exposure, or cooldown issue; keep broker readiness rows blocked until internal-sim evidence improves.

### M10-PA-008

- Priority: `P0`
- Blocked count: `1`
- Reasons: `{'max_risk_per_order_exceeded': 1}`
- Patterns: `ai_trader_shadow_signal_scoreboard, tradingagents_persistent_decision_log, tradingagents_role_decomposed_review`
- Local application: Use a TradingAgents-style risk/portfolio split to decide whether the blocker is a sizing, exposure, or cooldown issue; keep broker readiness rows blocked until internal-sim evidence improves.
