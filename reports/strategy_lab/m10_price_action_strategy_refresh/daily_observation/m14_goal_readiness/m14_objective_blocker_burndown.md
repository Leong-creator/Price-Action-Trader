# M14 Objective Blocker Burndown

- Generated at: `2026-05-26T20:09:02Z`
- Current stage: `M14 stable strategy testing + M14.2 broker readiness dry-run scaffold`
- Objective complete: `False`
- Challenge: `10/10`
- Blocker rows P0/P1/P2: `4/3/0`
- Approved internal-sim strategies: `3` (`M10-PA-004, M10-PA-005, M10-PA-008`)
- Rescue first-ledger / 10-day A/B / shadow-review gaps: `2/10/11`
- Visual confirmation pending questions / cases: `6/10`
- Future source-reextract spec prep rows/drafts/unblocked/blocked/pending: `2/2/0/2/16`
- Legacy history metric planning inputs: `0`
- Boundary: internal simulated accounts only; no broker/live, no real orders, no paper approval, no manual M12.37 once-mode, no parameter mutation.

## Plain Result

Objective blocker burndown has 7 rows with P0/P1/P2=4/3/0. The project is still not complete: 10-day challenge is 10/10, 3 strategies may continue internal simulation, but 2 rescue runtimes need first ledger evidence, 10 rescue A/B gaps remain, and 6 question plus 10 case visual confirmations are pending. Future source-reextract prep has 2 rows, 0 unblocked, and 0 legacy-history planning inputs. Legacy historical net-profit/history-return dashboard fields are explicitly ignored for planning. Broker/live, real orders, paper approval, parameter mutation, and manual M12.37 once-mode remain disabled.

## Legacy Metric Exclusion

- Excluded metrics: `historical_net_profit, historical_profit_factor, historical_return_percent, 历史净利润, 历史收益`
- Excluded from: `strategy_promotion, rescue_priority, parameter_activation, broker_readiness, objective_completion`
- Reason: The account drilldown historical net-profit/history-return fields can contain old-version contaminated values and must not steer M14 strategy planning.

## Blocker Rows

### P0 legacy_historical_profit_contamination_guardrail

- Category: `metric_exclusion_guardrail`
- State: `active_guardrail`
- Evidence: Legacy account dashboard historical_net_profit/history return fields are treated as old-version display artifacts and are excluded from every M14 planning decision.
- Next action: Keep planning tied to M13/M14 ledger, gate, evidence-gap, and M12.47 fresh-refresh artifacts only.
- Waiting on: `none`
- Allowed now: `artifact_review`
- Strategy promotion / discard allowed: `False/False`
- Parameter activation allowed: `False`
- Broker paper start allowed: `False`
- Legacy history metric planning input: `False`

### P0 fresh_refresh_required_before_parameter_activation

- Category: `fresh_refresh`
- State: `waiting_for_m12_47_fresh_refresh`
- Evidence: 13 post-refresh watch rows are still waiting; source quote state is fallback_quotes_only.
- Next action: Wait for the M12.47 supervisor to own the next fresh refresh, then run the read-only post-refresh recompute checklist.
- Waiting on: `m12_47_supervised_fresh_refresh`
- Allowed now: `artifact_review, post_refresh_checklist_review`
- Strategy promotion / discard allowed: `False/False`
- Parameter activation allowed: `False`
- Broker paper start allowed: `False`
- Legacy history metric planning input: `False`

### P0 rescue_first_ledger_gap

- Category: `rescue_evidence`
- State: `waiting_for_first_m13_ledger`
- Evidence: 2 rescue runtimes still need first M13 ledger evidence; 9/11 have ledger evidence.
- Next action: After the next M12.47-owned refresh, verify first strategy/account ledger rows before any promotion or discard decision.
- Waiting on: `m12_47_supervised_fresh_refresh, m13_rescue_ledger_rows`
- Allowed now: `runtime_registry_readonly_review, ledger_mapping_review`
- Strategy promotion / discard allowed: `False/False`
- Parameter activation allowed: `False`
- Broker paper start allowed: `False`
- Legacy history metric planning input: `False`

### P0 rescue_10_day_ab_gap

- Category: `rescue_evidence`
- State: `rescue_ab_window_incomplete`
- Evidence: 10 rescue 10-day A/B gaps remain; promotion allowed count is 0.
- Next action: Continue collecting rescue A/B evidence under M12.47/M13/M14; do not promote or abandon weak strategies from old history metrics.
- Waiting on: `rescue_10_day_ab_window, manual_m14_review`
- Allowed now: `artifact_review, ab_contract_review`
- Strategy promotion / discard allowed: `False/False`
- Parameter activation allowed: `False`
- Broker paper start allowed: `False`
- Legacy history metric planning input: `False`

### P1 parameter_shadow_activation_gap

- Category: `parameter_optimization`
- State: `waiting_for_fresh_evidence_no_mutation`
- Evidence: 14 parameter experiment rows exist; 13 activation rows are waiting for fresh refresh; mutation allowed count is 0.
- Next action: Keep parameter variants in shadow review until fresh M13/M14 evidence clears activation gates.
- Waiting on: `fresh_m13_m14_evidence, activation_gate_review`
- Allowed now: `shadow_spec_review, activation_gate_readonly_review`
- Strategy promotion / discard allowed: `False/False`
- Parameter activation allowed: `False`
- Broker paper start allowed: `False`
- Legacy history metric planning input: `False`

### P1 source_visual_manual_confirmation_gap

- Category: `source_reextract`
- State: `manual_visual_confirmation_pending`
- Evidence: Review pack ready=True with 10/10 local case assets; 6 question responses and 10 case responses are pending; future spec unblocked count is 0; spec-prep conditional/unblocked/blocked rows are 2/0/2, pending confirmations=16, legacy-history planning inputs=0.
- Next action: Use the static visual review pack for manual confirmation, rerun the response gate and future spec prep, then draft only after manual M14 review.
- Waiting on: `manual_visual_confirmation_response`
- Allowed now: `manual_review_pack_review, conditional_spec_prep_review`
- Strategy promotion / discard allowed: `False/False`
- Parameter activation allowed: `False`
- Broker paper start allowed: `False`
- Legacy history metric planning input: `False`

### P1 broker_dry_run_watch_only

- Category: `broker_readiness`
- State: `dry_run_preview_only`
- Evidence: Broker dry-run rows: ready=5, blocked=3; broker paper start is disabled.
- Next action: Keep broker readiness as dry-run engineering preview until internal-sim evidence and blockers are clean.
- Waiting on: `internal_sim_evidence, broker_blocker_repair_review`
- Allowed now: `dry_run_artifact_review`
- Strategy promotion / discard allowed: `False/False`
- Parameter activation allowed: `False`
- Broker paper start allowed: `False`
- Legacy history metric planning input: `False`
