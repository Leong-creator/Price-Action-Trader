# M14 Internal Sim Trial Acceptance Gate

- Generated at: `2026-05-26T16:00:00Z`
- Current stage: `M14 stable strategy testing + M14.2 broker readiness dry-run scaffold`
- Challenge progress: `10/10`
- Approved trial strategies: `3`
- Trial start ready: `3`
- Can start internal sim trial now: `True`
- Fresh-refresh-required rows: `3`
- Post-refresh observed/source/waiting: `False/fallback_quotes_only/13`
- Legacy history metric planning inputs: `0`
- Broker paper/live/manual M12.37/parameter mutation: `False/False/False/0`

## Plain Result

- Internal simulated-account trial start gate is ready for 3/3 approved strategies.
- Fresh refresh still required for 3 trial rows; post-refresh observed=False source_quote=fallback_quotes_only.
- Broker paper/live/manual M12.37/parameter mutation remain disabled; legacy historical profit planning inputs=0.

## Global Gates

- `pass` `internal_sim_trial_start_gate`: 3/3 approved strategies launch-ready; 4/4 approved runtime inputs connected. Pass: Wait for M12.47 to own the next trading-window refresh. Fail: Hold affected strategy until gate/runtime/input mapping is repaired.
- `waiting` `m12_47_fresh_refresh_gate`: fresh_refresh_observed=False; source_quote=fallback_quotes_only Pass: Evaluate post-refresh trial rows and rescue watches. Fail: Keep current plan as waiting; do not manually run M12.37 once-mode.
- `waiting` `post_fresh_recompute_gate`: checklist steps=26; acceptance gates=8; two_pass_required=True. Pass: Rerun M14 read-only recompute sequence and then refresh project stage assessment. Fail: Do not declare objective complete until recompute artifacts are refreshed.
- `pass` `legacy_history_metric_exclusion_gate`: legacy inputs blocker/next-step=0/0 Pass: Keep account-dashboard history metrics display-only. Fail: Block strategy planning until legacy history input is removed.
- `pass` `broker_live_boundary_gate`: can_start_broker_paper=False; manual_m12_37_once_allowed=False Pass: Continue internal simulated-account trial only. Fail: Stop and inspect boundary regression before further readiness work.

## Trial Rows

| Strategy | Start status | Fresh required | Broker watch | Legacy input | Post-refresh checks |
| --- | --- | --- | --- | --- | --- |
| M10-PA-004 | ready_internal_sim_trial | True | 0 | False | fresh_longbridge_quote_readonly_observed, m12_47_owned_m12_m13_refresh, m13_signal_and_account_ledgers_updated, m14_post_fresh_recompute_checklist_rerun, strategy_remains_approved_internal_sim_only, legacy_history_metric_planning_input_false, +1 more |
| M10-PA-005 | ready_internal_sim_trial_with_broker_watch_only | True | 2 | False | fresh_longbridge_quote_readonly_observed, m12_47_owned_m12_m13_refresh, m13_signal_and_account_ledgers_updated, m14_post_fresh_recompute_checklist_rerun, strategy_remains_approved_internal_sim_only, legacy_history_metric_planning_input_false, +3 more |
| M10-PA-008 | ready_internal_sim_trial_with_broker_watch_only | True | 1 | False | fresh_longbridge_quote_readonly_observed, m12_47_owned_m12_m13_refresh, m13_signal_and_account_ledgers_updated, m14_post_fresh_recompute_checklist_rerun, strategy_remains_approved_internal_sim_only, legacy_history_metric_planning_input_false, +4 more |

## Post-Trial Recompute Protocol

- `2` `review_post_refresh_outcomes`: `python scripts/run_m14_rescue_post_refresh_outcome_review.py`
- `14` `refresh_internal_sim_next_session_plan`: `python scripts/run_m14_internal_sim_next_session_plan.py`
- `23` `strategy_next_step_readiness_matrix_refresh`: `python scripts/run_m14_strategy_next_step_readiness_matrix.py`
- `26` `project_stage_assessment_refresh`: `python scripts/run_m14_project_stage_assessment.py`
