# M14 Strategy Evidence Gap Matrix

- Generated at: `2026-05-26T23:59:52Z`
- Current stage: `M14 stable strategy testing + M14.2 broker readiness dry-run scaffold`
- Challenge: `10/10`
- Strategy gap rows: `20`
- Open evidence gap rows: `20`
- Requires M12.47 fresh refresh: `12`
- First-ledger / 10-day A/B / shadow-review gaps: `2/10/11`
- Final discard allowed: `0`
- Promotion candidates: `0`
- Parameter mutation allowed: `0`
- Boundary: internal simulated accounts only; no broker/live, no real orders, no paper approval, no manual M12.37 once-mode.

## Plain Result

Strategy evidence gap matrix covers 20 strategy rows; 20 still have open evidence gaps and 12 require the next M12.47 fresh refresh. First-ledger gaps: 2; 10-day rescue A/B gaps: 10; shadow-review gaps: 11; final discards allowed now: 0; promotion candidates now: 0. No broker/live, real orders, paper approval, parameter mutation, registry/account-spec mutation, broker-readiness mutation, or manual M12.37 once-mode is enabled.

## Gap Policy

- `approved_rule`: Approved strategies need the next M12.47-supervised internal simulated-account refresh and post-refresh M13/M14 recompute evidence.
- `rescue_rule`: Weak strategies stay in rescue, detector rebuild, or shadow-parameter review until first ledger, 10-day A/B, and M14 review evidence are complete.
- `discard_rule`: Final discard remains blocked for every strategy until rescue and shadow evidence is exhausted and manual M14 review agrees.
- `mutation_rule`: This matrix is read-only and cannot mutate parameters, registries, account specs, or broker readiness.

## Gap Rows

### M10-PA-004

- Route: `approved_internal_sim_continue`
- Ladder state: `approved_continue_internal_sim`
- Gap state: `approved_wait_next_refresh`
- Missing evidence: `m12_47_fresh_refresh, manual_m14_review, post_refresh_m13_m14_recompute`
- Required artifacts: `M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; post-refresh M13/M14 recompute artifacts`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_internal_sim_launch_readiness, refresh_internal_sim_next_session_plan, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `wait_for_m12_47_supervised_internal_sim_refresh`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-005

- Route: `approved_internal_sim_continue`
- Ladder state: `approved_continue_internal_sim`
- Gap state: `approved_wait_next_refresh`
- Missing evidence: `broker_dry_run_watch_recheck, m12_47_fresh_refresh, manual_m14_review, post_refresh_m13_m14_recompute, shadow_parameter_review`
- Required artifacts: `M14.2 broker dry-run blocker recheck; M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; post-refresh M13/M14 recompute artifacts; M14 parameter shadow spec and activation gate`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_next_refresh_readiness, refresh_parameter_experiment_queue, refresh_parameter_activation_gate, refresh_parameter_shadow_specs, refresh_internal_sim_launch_readiness, refresh_internal_sim_next_session_plan, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `wait_for_m12_47_supervised_internal_sim_refresh`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-008

- Route: `approved_internal_sim_continue`
- Ladder state: `approved_continue_internal_sim`
- Gap state: `approved_wait_next_refresh`
- Missing evidence: `broker_dry_run_watch_recheck, first_m13_rescue_ledger, m12_47_fresh_refresh, manual_m14_review, post_refresh_m13_m14_recompute, shadow_parameter_review`
- Required artifacts: `M14.2 broker dry-run blocker recheck; rescue-specific M13 signal/account ledger row; M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; post-refresh M13/M14 recompute artifacts; M14 parameter shadow spec and activation gate`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_rescue_ab_evidence, refresh_rescue_optimization_backlog, refresh_next_refresh_readiness, refresh_parameter_experiment_queue, refresh_parameter_activation_gate, refresh_parameter_shadow_specs, refresh_internal_sim_launch_readiness, refresh_internal_sim_next_session_plan, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `wait_for_m12_47_supervised_internal_sim_refresh`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-001

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Gap state: `wait_shadow_parameter_review`
- Missing evidence: `m12_47_fresh_refresh, manual_m14_review, rescue_10_day_ab_window, shadow_parameter_review`
- Required artifacts: `M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; 10 trading-day rescue A/B evidence; M14 parameter shadow spec and activation gate`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_rescue_ab_evidence, refresh_rescue_optimization_backlog, refresh_next_refresh_readiness, refresh_parameter_experiment_queue, refresh_parameter_activation_gate, refresh_parameter_shadow_specs, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `continue_rescue_ab_and_shadow_spec_review`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-002

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Gap state: `wait_shadow_parameter_review`
- Missing evidence: `m12_47_fresh_refresh, manual_m14_review, rescue_10_day_ab_window, shadow_parameter_review`
- Required artifacts: `M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; 10 trading-day rescue A/B evidence; M14 parameter shadow spec and activation gate`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_rescue_ab_evidence, refresh_rescue_optimization_backlog, refresh_next_refresh_readiness, refresh_parameter_experiment_queue, refresh_parameter_activation_gate, refresh_parameter_shadow_specs, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `continue_rescue_ab_and_shadow_spec_review`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-004-MBF-QC

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Gap state: `wait_shadow_parameter_review`
- Missing evidence: `m12_47_fresh_refresh, manual_m14_review, rescue_10_day_ab_window, shadow_parameter_review`
- Required artifacts: `M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; 10 trading-day rescue A/B evidence; M14 parameter shadow spec and activation gate`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_rescue_ab_evidence, refresh_rescue_optimization_backlog, refresh_next_refresh_readiness, refresh_parameter_experiment_queue, refresh_parameter_activation_gate, refresh_parameter_shadow_specs, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `continue_rescue_ab_and_shadow_spec_review`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-007

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Gap state: `wait_shadow_parameter_review`
- Missing evidence: `m12_47_fresh_refresh, manual_m14_review, rescue_10_day_ab_window, shadow_parameter_review`
- Required artifacts: `M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; 10 trading-day rescue A/B evidence; M14 parameter shadow spec and activation gate`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_rescue_ab_evidence, refresh_rescue_optimization_backlog, refresh_next_refresh_readiness, refresh_parameter_experiment_queue, refresh_parameter_activation_gate, refresh_parameter_shadow_specs, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `continue_rescue_ab_and_shadow_spec_review`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-009

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Gap state: `wait_shadow_parameter_review`
- Missing evidence: `m12_47_fresh_refresh, manual_m14_review, rescue_10_day_ab_window, shadow_parameter_review`
- Required artifacts: `M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; 10 trading-day rescue A/B evidence; M14 parameter shadow spec and activation gate`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_rescue_ab_evidence, refresh_rescue_optimization_backlog, refresh_next_refresh_readiness, refresh_parameter_experiment_queue, refresh_parameter_activation_gate, refresh_parameter_shadow_specs, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `continue_rescue_ab_and_shadow_spec_review`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-012

- Route: `rescue_ab_collect`
- Ladder state: `wait_first_rescue_ledger`
- Gap state: `wait_first_rescue_ledger`
- Missing evidence: `first_m13_rescue_ledger, m12_47_fresh_refresh, manual_m14_review, rescue_10_day_ab_window, shadow_parameter_review`
- Required artifacts: `rescue-specific M13 signal/account ledger row; M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; 10 trading-day rescue A/B evidence; M14 parameter shadow spec and activation gate`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_rescue_ab_evidence, refresh_rescue_optimization_backlog, refresh_next_refresh_readiness, refresh_parameter_experiment_queue, refresh_parameter_activation_gate, refresh_parameter_shadow_specs, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `wait_for_first_rescue_specific_m13_ledger`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-013

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Gap state: `wait_shadow_parameter_review`
- Missing evidence: `m12_47_fresh_refresh, manual_m14_review, rescue_10_day_ab_window, shadow_parameter_review`
- Required artifacts: `M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; 10 trading-day rescue A/B evidence; M14 parameter shadow spec and activation gate`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_rescue_ab_evidence, refresh_rescue_optimization_backlog, refresh_next_refresh_readiness, refresh_parameter_experiment_queue, refresh_parameter_activation_gate, refresh_parameter_shadow_specs, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `continue_rescue_ab_and_shadow_spec_review`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M12-FTD-001

- Route: `rescue_ab_collect`
- Ladder state: `continue_rescue_with_shadow_specs`
- Gap state: `wait_shadow_parameter_review`
- Missing evidence: `m12_47_fresh_refresh, manual_m14_review, rescue_10_day_ab_window, shadow_parameter_review`
- Required artifacts: `M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; 10 trading-day rescue A/B evidence; M14 parameter shadow spec and activation gate`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_rescue_ab_evidence, refresh_rescue_optimization_backlog, refresh_next_refresh_readiness, refresh_parameter_experiment_queue, refresh_parameter_activation_gate, refresh_parameter_shadow_specs, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `continue_rescue_ab_and_shadow_spec_review`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-004-MBF

- Route: `parallel_ab_collect`
- Ladder state: `continue_rescue_ab_collection`
- Gap state: `collect_rescue_ab_evidence`
- Missing evidence: `manual_m14_review, rescue_10_day_ab_window`
- Required artifacts: `manual M14 review after machine evidence is complete; 10 trading-day rescue A/B evidence`
- Recompute steps: `refresh_rescue_ab_evidence, refresh_rescue_optimization_backlog, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `continue_rescue_10_day_ab_collection`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-011

- Route: `rebuild_detector_then_ab`
- Ladder state: `continue_rescue_with_shadow_specs`
- Gap state: `wait_shadow_parameter_review`
- Missing evidence: `m12_47_fresh_refresh, manual_m14_review, rescue_10_day_ab_window, shadow_parameter_review`
- Required artifacts: `M12.47-supervised M12/M13 refreshed artifacts; manual M14 review after machine evidence is complete; 10 trading-day rescue A/B evidence; M14 parameter shadow spec and activation gate`
- Recompute steps: `wait_for_m12_47_supervisor_refresh, review_post_refresh_outcomes, refresh_rescue_ab_evidence, refresh_rescue_optimization_backlog, refresh_next_refresh_readiness, refresh_parameter_experiment_queue, refresh_parameter_activation_gate, refresh_parameter_shadow_specs, objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `continue_rescue_ab_and_shadow_spec_review`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### AI-TRADER-EXTERNAL

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Gap state: `shadow_or_plugin_hold`
- Missing evidence: `independent_strategy_evidence_missing, manual_m14_review`
- Required artifacts: `independent strategy evidence beyond shadow/plugin/research coverage; manual M14 review after machine evidence is complete`
- Recompute steps: `objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `keep_shadow_plugin_or_research_coverage`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-003

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Gap state: `shadow_or_plugin_hold`
- Missing evidence: `independent_strategy_evidence_missing, manual_m14_review`
- Required artifacts: `independent strategy evidence beyond shadow/plugin/research coverage; manual M14 review after machine evidence is complete`
- Recompute steps: `objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `keep_shadow_plugin_or_research_coverage`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-006

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Gap state: `shadow_or_plugin_hold`
- Missing evidence: `independent_strategy_evidence_missing, manual_m14_review`
- Required artifacts: `independent strategy evidence beyond shadow/plugin/research coverage; manual M14 review after machine evidence is complete`
- Recompute steps: `objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `keep_shadow_plugin_or_research_coverage`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-010

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Gap state: `shadow_or_plugin_hold`
- Missing evidence: `independent_strategy_evidence_missing, manual_m14_review`
- Required artifacts: `independent strategy evidence beyond shadow/plugin/research coverage; manual M14 review after machine evidence is complete`
- Recompute steps: `objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `keep_shadow_plugin_or_research_coverage`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-014

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Gap state: `shadow_or_plugin_hold`
- Missing evidence: `independent_strategy_evidence_missing, manual_m14_review`
- Required artifacts: `independent strategy evidence beyond shadow/plugin/research coverage; manual M14 review after machine evidence is complete`
- Recompute steps: `objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `keep_shadow_plugin_or_research_coverage`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-015

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Gap state: `shadow_or_plugin_hold`
- Missing evidence: `independent_strategy_evidence_missing, manual_m14_review`
- Required artifacts: `independent strategy evidence beyond shadow/plugin/research coverage; manual M14 review after machine evidence is complete`
- Recompute steps: `objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `keep_shadow_plugin_or_research_coverage`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`

### M10-PA-016

- Route: `shadow_or_plugin_hold`
- Ladder state: `shadow_or_plugin_hold`
- Gap state: `shadow_or_plugin_hold`
- Missing evidence: `independent_strategy_evidence_missing, manual_m14_review`
- Required artifacts: `independent strategy evidence beyond shadow/plugin/research coverage; manual M14 review after machine evidence is complete`
- Recompute steps: `objective_audit_first_pass, objective_execution_first_pass, strategy_decision_ladder_refresh, objective_audit_after_ladder, objective_execution_after_ladder, project_stage_assessment_refresh`
- Allowed next move: `keep_shadow_plugin_or_research_coverage`
- Final discard allowed: `False`
- Parameter mutation allowed: `False`
