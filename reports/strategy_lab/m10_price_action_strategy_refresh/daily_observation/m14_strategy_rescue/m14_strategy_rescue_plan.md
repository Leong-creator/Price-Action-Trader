# M14 Strategy Rescue Plan

- Generated at: `2026-05-25T18:30:00Z`
- Challenge progress: `10/10`
- Approved internal sim: `M10-PA-004, M10-PA-005, M10-PA-008`
- Boundary: internal simulated only; no broker connection, no real orders, no live execution.

## Summary

3 strategies can continue into internal simulated trading: M10-PA-004, M10-PA-005, M10-PA-008. 9 strategies need rescue variants: M10-PA-001, M10-PA-002, M10-PA-004-MBF, M10-PA-004-MBF-QC, M10-PA-007, M10-PA-009, M10-PA-012, M10-PA-013, M12-FTD-001. 1 strategies need detector rebuild before abandonment: M10-PA-011.

## External References

- `HKUDS/AI-Trader`: https://github.com/HKUDS/AI-Trader - paper trading, signal feed, leaderboard-style comparison, and agent signal sync can inspire shadow-signal evaluation only Boundary: Do not copy-trade external agents; only ingest authorized public/user-approved signals into local shadow tests.
- `TauricResearch/TradingAgents`: https://github.com/TauricResearch/TradingAgents - separate analyst, researcher, trader, risk, and portfolio-manager roles can inspire local review gates and rescue diagnostics Boundary: Use as architecture inspiration only; no external LLM decision can bypass local ledger, risk, or paper gate.

## Strategy Rows

### AI-TRADER-EXTERNAL

- Decision: `continue_testing` / `external_shadow_research_only`
- Gate: `not_approved_challenge_incomplete`
- Lane: `research_or_plugin`
- Rescue mode: `keep_shadow_or_ab_filter`
- Next variant: `n/a`
- Result: PnL `0.00`, R `0`, drawdown `0%`
- Next action: Keep it in plugin/filter/research coverage; do not present it as an independent trading account.
- Hypothesis: Use as a supporting filter or research source until it has independent detector and account evidence.

### M10-PA-001

- Decision: `modify` / `net_pnl_below_minus_2r`
- Gate: `not_approved_modify_candidate`
- Lane: `rescue_candidate`
- Rescue mode: `entry_quality_and_filter_variant`
- Next variant: `M10-PA-001-m14-modify-20260522`
- Result: PnL `-375.01`, R `-3.7501`, drawdown `4.05%`
- Next action: Freeze baseline semantics, create variant M10-PA-001-m14-modify-20260522, and A/B test it against the old baseline.
- Hypothesis: Negative expectancy crossed the circuit threshold; test stronger trend/context filter, news/event veto, and lower-frequency entry confirmation.

### M10-PA-002

- Decision: `modify` / `net_pnl_below_minus_2r`
- Gate: `not_approved_modify_candidate`
- Lane: `rescue_candidate`
- Rescue mode: `entry_quality_and_filter_variant`
- Next variant: `M10-PA-002-m14-modify-20260522`
- Result: PnL `-217.77`, R `-2.1777`, drawdown `13.73%`
- Next action: Freeze baseline semantics, create variant M10-PA-002-m14-modify-20260522, and A/B test it against the old baseline.
- Hypothesis: Negative expectancy crossed the circuit threshold; test stronger trend/context filter, news/event veto, and lower-frequency entry confirmation.

### M10-PA-003

- Decision: `continue_testing` / `plugin_filter_ab_coverage`
- Gate: `not_approved_challenge_incomplete`
- Lane: `research_or_plugin`
- Rescue mode: `keep_shadow_or_ab_filter`
- Next variant: `n/a`
- Result: PnL `0.00`, R `0`, drawdown `0%`
- Next action: Keep it in plugin/filter/research coverage; do not present it as an independent trading account.
- Hypothesis: Use as a supporting filter or research source until it has independent detector and account evidence.

### M10-PA-004

- Decision: `promote` / `ten_day_positive_expectancy_internal_sim_candidate`
- Gate: `approved_internal_sim_only`
- Lane: `approved_internal_sim`
- Rescue mode: `do_not_change_baseline`
- Next variant: `n/a`
- Result: PnL `200.00`, R `2`, drawdown `0.9%`
- Next action: Keep the approved baseline running in internal simulated trading; monitor fills, risk blocks, drawdown, and slippage sensitivity.
- Hypothesis: No parameter change before new internal-sim evidence contradicts the 10-day challenge.

### M10-PA-004-MBF

- Decision: `continue_testing` / `parallel_modify_variant_started_continue_original_to_10d`
- Gate: `not_approved_parallel_modify_testing`
- Lane: `rescue_candidate`
- Rescue mode: `entry_quality_and_filter_variant`
- Next variant: `M10-PA-004-MBF-QC`
- Result: PnL `-586.66`, R `-5.8666`, drawdown `2.68%`
- Next action: Freeze baseline semantics, create variant M10-PA-004-MBF-QC, and A/B test it against the old baseline.
- Hypothesis: Negative expectancy crossed the circuit threshold; test stronger trend/context filter, news/event veto, and lower-frequency entry confirmation.

### M10-PA-004-MBF-QC

- Decision: `modify` / `net_pnl_below_minus_2r`
- Gate: `not_approved_modify_candidate`
- Lane: `rescue_candidate`
- Rescue mode: `entry_quality_and_filter_variant`
- Next variant: `M10-PA-004-MBF-QC-m14-modify-20260522`
- Result: PnL `-234.66`, R `-2.3466`, drawdown `1.51%`
- Next action: Freeze baseline semantics, create variant M10-PA-004-MBF-QC-m14-modify-20260522, and A/B test it against the old baseline.
- Hypothesis: Negative expectancy crossed the circuit threshold; test stronger trend/context filter, news/event veto, and lower-frequency entry confirmation.

### M10-PA-005

- Decision: `promote` / `ten_day_positive_expectancy_internal_sim_candidate`
- Gate: `approved_internal_sim_only`
- Lane: `approved_internal_sim`
- Rescue mode: `do_not_change_baseline`
- Next variant: `n/a`
- Result: PnL `643.12`, R `6.4312`, drawdown `2.17%`
- Next action: Keep the approved baseline running in internal simulated trading; monitor fills, risk blocks, drawdown, and slippage sensitivity.
- Hypothesis: No parameter change before new internal-sim evidence contradicts the 10-day challenge.

### M10-PA-006

- Decision: `continue_testing` / `plugin_filter_ab_coverage`
- Gate: `not_approved_challenge_incomplete`
- Lane: `research_or_plugin`
- Rescue mode: `keep_shadow_or_ab_filter`
- Next variant: `n/a`
- Result: PnL `0.00`, R `0`, drawdown `0%`
- Next action: Keep it in plugin/filter/research coverage; do not present it as an independent trading account.
- Hypothesis: Use as a supporting filter or research source until it has independent detector and account evidence.

### M10-PA-007

- Decision: `modify` / `net_pnl_below_minus_2r`
- Gate: `not_approved_modify_candidate`
- Lane: `rescue_candidate`
- Rescue mode: `entry_quality_and_filter_variant`
- Next variant: `M10-PA-007-m14-modify-20260522`
- Result: PnL `-213.10`, R `-2.131`, drawdown `1.27%`
- Next action: Freeze baseline semantics, create variant M10-PA-007-m14-modify-20260522, and A/B test it against the old baseline.
- Hypothesis: Negative expectancy crossed the circuit threshold; test stronger trend/context filter, news/event veto, and lower-frequency entry confirmation.

### M10-PA-008

- Decision: `promote` / `ten_day_positive_expectancy_internal_sim_candidate`
- Gate: `approved_internal_sim_only`
- Lane: `approved_internal_sim`
- Rescue mode: `do_not_change_baseline`
- Next variant: `n/a`
- Result: PnL `200.00`, R `2`, drawdown `1.36%`
- Next action: Keep the approved baseline running in internal simulated trading; monitor fills, risk blocks, drawdown, and slippage sensitivity.
- Hypothesis: No parameter change before new internal-sim evidence contradicts the 10-day challenge.

### M10-PA-009

- Decision: `modify` / `ten_day_losing_modify_candidate`
- Gate: `not_approved_modify_candidate`
- Lane: `rescue_candidate`
- Rescue mode: `expectancy_repair_variant`
- Next variant: `M10-PA-009-m14-modify-20260522`
- Result: PnL `-100.38`, R `-1.0038`, drawdown `1.8%`
- Next action: Freeze baseline semantics, create variant M10-PA-009-m14-modify-20260522, and A/B test it against the old baseline.
- Hypothesis: Loss is not catastrophic but expectancy is weak; test parameter grid on entry confirmation, stop distance, and profit-taking.

### M10-PA-010

- Decision: `continue_testing` / `research_only_blocker`
- Gate: `not_approved_challenge_incomplete`
- Lane: `research_or_plugin`
- Rescue mode: `keep_shadow_or_ab_filter`
- Next variant: `n/a`
- Result: PnL `0.00`, R `0`, drawdown `0%`
- Next action: Keep it in plugin/filter/research coverage; do not present it as an independent trading account.
- Hypothesis: Use as a supporting filter or research source until it has independent detector and account evidence.

### M10-PA-011

- Decision: `reject` / `ten_days_no_viable_signal`
- Gate: `not_approved_rejected`
- Lane: `detector_rebuild`
- Rescue mode: `rebuild_detector_before_abandon`
- Next variant: `M10-PA-011-m14-rescue-v1`
- Result: PnL `0.00`, R `0`, drawdown `0%`
- Next action: Do not discard yet; rebuild the detector contract and run a new shadow variant before final rejection.
- Hypothesis: The problem is likely no actionable detector coverage, not proven negative expectancy.

### M10-PA-012

- Decision: `modify` / `max_drawdown_above_3_percent`
- Gate: `not_approved_modify_candidate`
- Lane: `rescue_candidate`
- Rescue mode: `drawdown_control_variant`
- Next variant: `M10-PA-012-m14-modify-20260522`
- Result: PnL `346.12`, R `3.4612`, drawdown `6.5%`
- Next action: Freeze baseline semantics, create variant M10-PA-012-m14-modify-20260522, and A/B test it against the old baseline.
- Hypothesis: Positive PnL with unacceptable drawdown; test volatility regime filter, lower per-trade risk, and trailing stop/target cleanup.

### M10-PA-013

- Decision: `modify` / `max_drawdown_above_3_percent`
- Gate: `not_approved_modify_candidate`
- Lane: `rescue_candidate`
- Rescue mode: `drawdown_control_variant`
- Next variant: `M10-PA-013-m14-modify-20260522`
- Result: PnL `459.20`, R `4.592`, drawdown `4.09%`
- Next action: Freeze baseline semantics, create variant M10-PA-013-m14-modify-20260522, and A/B test it against the old baseline.
- Hypothesis: Positive PnL with unacceptable drawdown; test volatility regime filter, lower per-trade risk, and trailing stop/target cleanup.

### M10-PA-014

- Decision: `continue_testing` / `plugin_filter_ab_coverage`
- Gate: `not_approved_challenge_incomplete`
- Lane: `research_or_plugin`
- Rescue mode: `keep_shadow_or_ab_filter`
- Next variant: `n/a`
- Result: PnL `0.00`, R `0`, drawdown `0%`
- Next action: Keep it in plugin/filter/research coverage; do not present it as an independent trading account.
- Hypothesis: Use as a supporting filter or research source until it has independent detector and account evidence.

### M10-PA-015

- Decision: `continue_testing` / `plugin_filter_ab_coverage`
- Gate: `not_approved_challenge_incomplete`
- Lane: `research_or_plugin`
- Rescue mode: `keep_shadow_or_ab_filter`
- Next variant: `n/a`
- Result: PnL `0.00`, R `0`, drawdown `0%`
- Next action: Keep it in plugin/filter/research coverage; do not present it as an independent trading account.
- Hypothesis: Use as a supporting filter or research source until it has independent detector and account evidence.

### M10-PA-016

- Decision: `continue_testing` / `plugin_filter_ab_coverage`
- Gate: `not_approved_challenge_incomplete`
- Lane: `research_or_plugin`
- Rescue mode: `keep_shadow_or_ab_filter`
- Next variant: `n/a`
- Result: PnL `0.00`, R `0`, drawdown `0%`
- Next action: Keep it in plugin/filter/research coverage; do not present it as an independent trading account.
- Hypothesis: Use as a supporting filter or research source until it has independent detector and account evidence.

### M12-FTD-001

- Decision: `modify` / `net_pnl_below_minus_2r`
- Gate: `not_approved_modify_candidate`
- Lane: `rescue_candidate`
- Rescue mode: `entry_quality_and_filter_variant`
- Next variant: `M12-FTD-001-m14-modify-20260522`
- Result: PnL `-1016.29`, R `-10.1629`, drawdown `5.45%`
- Next action: Freeze baseline semantics, create variant M12-FTD-001-m14-modify-20260522, and A/B test it against the old baseline.
- Hypothesis: Negative expectancy crossed the circuit threshold; test stronger trend/context filter, news/event veto, and lower-frequency entry confirmation.
