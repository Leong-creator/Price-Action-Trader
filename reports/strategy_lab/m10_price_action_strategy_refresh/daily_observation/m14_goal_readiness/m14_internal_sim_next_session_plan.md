# M14 Internal Sim Next Session Plan

- Generated at: `2026-05-26T06:11:39Z`
- Mode: `m12_47_supervised_fresh_refresh_only`
- Can run next internal sim session: `True`
- Approved launch-ready strategies: `3/3`
- Approved runtime input coverage: `4/4`
- Broker watch strategies: `2`
- Rescue watch rows: `13`
- Manual M12.37 once-mode allowed: `False`
- Broker paper start allowed: `False`
- Boundary: internal simulated accounts only; no broker connection, no real orders, no live execution.

## Plain Result

Next internal simulated-account session is ready in m12_47_supervised_fresh_refresh_only mode: 3/3 approved strategies and 4/4 approved runtimes are connected. 2 approved strategies need broker dry-run blocker watch; 13 rescue watch rows and 2 first-ledger watches remain for the next fresh refresh. Manual M12.37 once-mode, broker paper, live execution, real orders, and paper-trading approval remain disabled.

## Strategy Session Rows

### M10-PA-004

- Action: `continue_internal_simulated_account_testing`
- Runtimes: `M10-PA-004-long-1d`
- Runtime input coverage: `1/1`
- M13 signal/open/close: `0/0/0`
- Broker dry-run ready/blocked: `0/0`
- Linked next-refresh watches: `0`
- Acceptance checks: `m12_47_supervised_fresh_refresh_only, m13_signal_and_account_ledgers_refresh_after_session, m14_gate_stays_approved_internal_sim_only, no_broker_connection_no_real_order_no_live_execution`

### M10-PA-005

- Action: `continue_internal_sim_and_watch_broker_dry_run_blockers`
- Runtimes: `M10-PA-005-1d, M10-PA-005-5m`
- Runtime input coverage: `2/2`
- M13 signal/open/close: `329/8/8`
- Broker dry-run ready/blocked: `5/2`
- Linked next-refresh watches: `2`
- Acceptance checks: `m12_47_supervised_fresh_refresh_only, m13_signal_and_account_ledgers_refresh_after_session, m14_gate_stays_approved_internal_sim_only, no_broker_connection_no_real_order_no_live_execution, broker_dry_run_blockers_remain_watch_only, pa005_rule_shadow_recheck_after_fresh_refresh`

### M10-PA-008

- Action: `continue_internal_sim_and_watch_broker_dry_run_blockers`
- Runtimes: `M10-PA-008-1d`
- Runtime input coverage: `1/1`
- M13 signal/open/close: `1/1/0`
- Broker dry-run ready/blocked: `0/1`
- Linked next-refresh watches: `1`
- Acceptance checks: `m12_47_supervised_fresh_refresh_only, m13_signal_and_account_ledgers_refresh_after_session, m14_gate_stays_approved_internal_sim_only, no_broker_connection_no_real_order_no_live_execution, broker_dry_run_blockers_remain_watch_only, first_rescue_ledger_watch_after_fresh_refresh`

## Global Watch Rows

- `P0` `approved_internal_sim_launch_recheck`: Approved strategies remain launch-ready and all approved runtime inputs stay connected.
- `P0` `rescue_next_refresh_matrix`: 13 rescue watch rows can be evaluated after the next fresh run.
- `P0` `first_rescue_ledger_watch`: 2 rescue runtimes currently need first M13 ledger evidence.
- `P0` `broker_live_boundary_check`: broker_connection=false, real_order=false, live_execution=false, paper_trading_approval=false.

## Execution Protocol

- `wait_for_m12_47_supervisor_window` owner `M12.47 supervisor`: Do not manually run scripts/run_m12_37_intraday_auto_loop.py --once.
- `refresh_m12_dashboard_and_m13_ledgers` owner `M12.47 post_run_strategy_ledgers`: Use fresh readonly market data only when the supervisor owns the trading-window refresh.
- `rebuild_m14_readiness_artifacts` owner `M14 scripts`: Recompute launch readiness, next-refresh readiness, and goal readiness from current artifacts.
- `review_internal_sim_and_rescue_evidence` owner `Codex/read-only review`: Continue internal simulation and rescue evidence collection; do not enable broker/live.
