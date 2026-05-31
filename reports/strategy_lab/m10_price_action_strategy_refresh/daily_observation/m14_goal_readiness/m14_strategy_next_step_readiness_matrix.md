# M14 下一步推进矩阵

- 生成时间: `2026-05-31T09:34:25Z`
- 当前阶段: `M14 stable strategy testing + M14.2 broker readiness dry-run scaffold`
- 挑战进度: `10/10`
- 策略行数: `20`
- 内部模拟 / 直接升级 / 最终淘汰 / 参数启用 / 长桥模拟账户: `3/0/0/0/0`
- 辅助模块行数: `7`
- 旧历史利润参与规划数量: `0`
- 来源重提炼规格 行数/草案/已解除/阻断/待确认: `2/2/0/2/16`
- 是否允许手动跑 M12.37 once-mode: `False`
- 是否启用券商/实盘: `False`

## 旧历史利润口径

旧账户看板历史利润字段按错误旧产物处理，不能影响策略推进、修复优先级、参数启用、券商准备或目标完成判断。

## 明细

| 策略 | 当前分组 | 下一步 | 角色 | 能否继续内部模拟 | 直接升级 | 最终淘汰 | 旧历史字段参与 | 需要的证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M10-PA-004 | approved_internal_sim_continue | continue_next_internal_sim_refresh | trading_runtime | True | False | False | False | M12.47-supervised M12/M13 refreshed artifacts, Next M12.47-supervised fresh refresh and post-run M13 ledger update., m12_47_fresh_refresh, manual M14 review after machine evidence is complete, manual_m14_review, 另有 2 项 |
| M10-PA-005 | approved_internal_sim_continue | continue_next_internal_sim_refresh | trading_runtime | True | False | False | False | M12.47-supervised M12/M13 refreshed artifacts, M14 parameter shadow spec and activation gate, M14.2 broker dry-run blocker recheck, Next M12.47-supervised fresh refresh and post-run M13 ledger update., broker_dry_run_watch_recheck, 另有 6 项 |
| M10-PA-008 | approved_internal_sim_continue | continue_next_internal_sim_refresh | trading_runtime | True | False | False | False | M12.47-supervised M12/M13 refreshed artifacts, M14 parameter shadow spec and activation gate, M14.2 broker dry-run blocker recheck, Next M12.47-supervised fresh refresh and post-run M13 ledger update., broker_dry_run_watch_recheck, 另有 8 项 |
| M10-PA-012 | rescue_or_shadow_review | collect_first_rescue_ledger | trading_runtime | False | False | False | False | 10 trading-day rescue A/B evidence, M12.47-supervised M12/M13 refreshed artifacts, M14 parameter shadow spec and activation gate, Next M12.47-supervised fresh refresh and post-run M13 ledger update., first_m13_rescue_ledger, 另有 6 项 |
| M10-PA-001 | rescue_or_shadow_review | complete_shadow_parameter_review | trading_runtime | False | False | False | False | 10 trading-day rescue A/B evidence, M12.47-supervised M12/M13 refreshed artifacts, M14 parameter shadow spec and activation gate, Next M12.47-supervised fresh refresh and post-run M13 ledger update., m12_47_fresh_refresh, 另有 4 项 |
| M10-PA-002 | rescue_or_shadow_review | complete_shadow_parameter_review | trading_runtime | False | False | False | False | 10 trading-day rescue A/B evidence, M12.47-supervised M12/M13 refreshed artifacts, M14 parameter shadow spec and activation gate, Next M12.47-supervised fresh refresh and post-run M13 ledger update., m12_47_fresh_refresh, 另有 4 项 |
| M10-PA-004-MBF-QC | rescue_or_shadow_review | complete_shadow_parameter_review | trading_runtime | False | False | False | False | 10 trading-day rescue A/B evidence, M12.47-supervised M12/M13 refreshed artifacts, M14 parameter shadow spec and activation gate, Next M12.47-supervised fresh refresh and post-run M13 ledger update., m12_47_fresh_refresh, 另有 4 项 |
| M10-PA-007 | rescue_or_shadow_review | complete_shadow_parameter_review | trading_runtime | False | False | False | False | 10 trading-day rescue A/B evidence, M12.47-supervised M12/M13 refreshed artifacts, M14 parameter shadow spec and activation gate, Next M12.47-supervised fresh refresh and post-run M13 ledger update., m12_47_fresh_refresh, 另有 4 项 |
| M10-PA-009 | rescue_or_shadow_review | complete_shadow_parameter_review | trading_runtime | False | False | False | False | 10 trading-day rescue A/B evidence, M12.47-supervised M12/M13 refreshed artifacts, M14 parameter shadow spec and activation gate, Next M12.47-supervised fresh refresh and post-run M13 ledger update., m12_47_fresh_refresh, 另有 4 项 |
| M10-PA-013 | rescue_or_shadow_review | complete_shadow_parameter_review | trading_runtime | False | False | False | False | 10 trading-day rescue A/B evidence, M12.47-supervised M12/M13 refreshed artifacts, M14 parameter shadow spec and activation gate, Next M12.47-supervised fresh refresh and post-run M13 ledger update., m12_47_fresh_refresh, 另有 4 项 |
| M12-FTD-001 | rescue_or_shadow_review | complete_shadow_parameter_review | trading_runtime | False | False | False | False | 10 trading-day rescue A/B evidence, M12.47-supervised M12/M13 refreshed artifacts, M14 parameter shadow spec and activation gate, Next M12.47-supervised fresh refresh and post-run M13 ledger update., m12_47_fresh_refresh, 另有 4 项 |
| M10-PA-004-MBF | rescue_or_shadow_review | continue_rescue_ab_collection | trading_runtime | False | False | False | False | 10 trading-day rescue A/B evidence, 10 trading-day rescue A/B evidence window., manual M14 review after machine evidence is complete, manual_m14_review, rescue_10_day_ab_window |
| M10-PA-011 | rescue_or_shadow_review | rebuild_detector_then_ab | trading_runtime | False | False | False | False | 10 trading-day rescue A/B evidence, M12.47-supervised M12/M13 refreshed artifacts, M14 parameter shadow spec and activation gate, Next M12.47-supervised fresh refresh and post-run M13 ledger update., m12_47_fresh_refresh, 另有 4 项 |
| AI-TRADER-EXTERNAL | auxiliary_module_support | auxiliary_module_support | auxiliary_module | False | False | False | False | Independent strategy evidence beyond auxiliary-module coverage., independent strategy evidence beyond shadow/auxiliary-module coverage, independent_strategy_evidence_missing, manual M14 review after machine evidence is complete, manual_m14_review |
| M10-PA-003 | auxiliary_module_support | auxiliary_module_support | auxiliary_module | False | False | False | False | Independent strategy evidence beyond auxiliary-module coverage., future_source_reextract_spec_manual_visual_confirmation, future_source_reextract_spec_prep_review_only, independent strategy evidence beyond shadow/auxiliary-module coverage, independent_strategy_evidence_missing, 另有 4 项 |
| M10-PA-006 | auxiliary_module_support | auxiliary_module_support | auxiliary_module | False | False | False | False | Independent strategy evidence beyond auxiliary-module coverage., independent strategy evidence beyond shadow/auxiliary-module coverage, independent_strategy_evidence_missing, manual M14 review after machine evidence is complete, manual_m14_review |
| M10-PA-010 | auxiliary_module_support | auxiliary_module_support | auxiliary_module | False | False | False | False | Independent strategy evidence beyond auxiliary-module coverage., future_source_reextract_spec_manual_visual_confirmation, future_source_reextract_spec_prep_review_only, independent strategy evidence beyond shadow/auxiliary-module coverage, independent_strategy_evidence_missing, 另有 4 项 |
| M10-PA-014 | auxiliary_module_support | auxiliary_module_support | auxiliary_module | False | False | False | False | Independent strategy evidence beyond auxiliary-module coverage., independent strategy evidence beyond shadow/auxiliary-module coverage, independent_strategy_evidence_missing, manual M14 review after machine evidence is complete, manual_m14_review |
| M10-PA-015 | auxiliary_module_support | auxiliary_module_support | auxiliary_module | False | False | False | False | Independent strategy evidence beyond auxiliary-module coverage., independent strategy evidence beyond shadow/auxiliary-module coverage, independent_strategy_evidence_missing, manual M14 review after machine evidence is complete, manual_m14_review |
| M10-PA-016 | auxiliary_module_support | auxiliary_module_support | auxiliary_module | False | False | False | False | Independent strategy evidence beyond auxiliary-module coverage., independent strategy evidence beyond shadow/auxiliary-module coverage, independent_strategy_evidence_missing, manual M14 review after machine evidence is complete, manual_m14_review |
