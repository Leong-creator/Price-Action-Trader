# Strategy Lab Guide

本文件用于帮助读者快速理解 Price Action strategy lab 的当前阶段、legacy 边界和阅读顺序。

## 先看这条边界

- 当前新阶段是 `M10: Price Action Strategy Refresh` 到 `M12.12 Daily Observation Loop`，当前阶段分支为 `feature/m12-12-daily-observation-loop`，稳定基线为 `main`。
- M10 使用 `M10-PA-*` namespace，从 Brooks v2 manual transcript、方方土 YouTube transcript、方方土 notes 重新提炼。
- 当前 M10 重点文件：
  - `reports/strategy_lab/m10_price_action_strategy_refresh/strategy_catalog_m10.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/strategy_catalog_m10_frozen.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/source_support_matrix_m10.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_test_plan.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_catalog_review.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_strategy_test_queue.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_visual_golden_case_index.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_2_visual_review_summary.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_3_backtest_spec_handoff.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/backtest_specs/`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_backtest_spec_index.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_event_definition_ledger.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_skip_rule_ledger.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_cost_sample_gate_policy.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_3_backtest_spec_freeze_summary.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/historical_pilot/m10_4_wave_a_pilot/m10_4_data_availability.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/historical_pilot/m10_4_wave_a_pilot/m10_4_dataset_inventory.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/historical_pilot/m10_4_wave_a_pilot/m10_4_wave_a_pilot_summary.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/historical_pilot/m10_4_wave_a_pilot/m10_4_wave_a_pilot_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_5_pilot_quality_review.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_5_observation_candidate_queue.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_5_read_only_observation_plan.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_5_observation_event_schema.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_5_paper_gate_handoff.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/read_only_observation/m10_6_replay/m10_6_input_manifest.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/read_only_observation/m10_6_replay/m10_6_observation_ledger.jsonl`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/read_only_observation/m10_6_replay/m10_6_observation_summary.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/read_only_observation/m10_6_replay/m10_6_deferred_inputs.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/read_only_observation/m10_6_replay/m10_6_observation_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_7_business_metric_policy.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_7_capital_model.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m10_7_client_report_template.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_8_wave_a/m10_8_wave_a_capital_summary.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_8_wave_a/m10_8_wave_a_metrics.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_8_wave_a/m10_8_wave_a_trade_ledger.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_8_wave_a/m10_8_wave_a_strategy_scorecard.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_8_wave_a/m10_8_wave_a_client_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_8_wave_a/m10_8_wave_a_equity_curves/`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_tightening/m10_9_pa_005/m10_9_definition_filter_ledger.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_tightening/m10_9_pa_005/m10_9_before_after_metrics.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_tightening/m10_9_pa_005/m10_9_definition_fix_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_tightening/m10_9_pa_005/m10_9_wave_a_retest_client_summary.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_wave_b_gate/m10_10/m10_10_wave_b_entry_queue.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_wave_b_gate/m10_10/m10_10_visual_strategy_review.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_wave_b_gate/m10_10/m10_10_visual_client_summary.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_11_wave_b/m10_11_wave_b_capital_summary.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_11_wave_b/m10_11_wave_b_metrics.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_11_wave_b/m10_11_wave_b_trade_ledger.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_11_wave_b/m10_11_wave_b_client_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/capital_backtest/m10_11_wave_b/m10_11_wave_b_equity_curves/`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/all_strategy_scorecard/m10_12/m10_12_all_strategy_metrics.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/all_strategy_scorecard/m10_12/m10_12_strategy_decision_matrix.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/all_strategy_scorecard/m10_12/m10_12_portfolio_simulation_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/all_strategy_scorecard/m10_12/m10_12_client_final_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/read_only_observation/m10_13/m10_13_observation_candidate_queue.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/read_only_observation/m10_13/m10_13_read_only_observation_runbook.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/read_only_observation/m10_13/m10_13_weekly_observation_template.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/paper_gate/m11/m11_paper_gate_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/paper_gate/m11/m11_candidate_strategy_list.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/paper_gate/m11/m11_risk_and_pause_policy.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m12_read_only_pipeline/m12_0_auth_preflight/m12_0_longbridge_readonly_auth_check.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m12_read_only_pipeline/m12_1_readonly_feed/m12_1_readonly_feed_manifest.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m12_read_only_pipeline/m12_1_readonly_feed/m12_1_bar_close_observation_ledger.jsonl`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m12_read_only_pipeline/m12_1_readonly_feed/m12_1_feed_health_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m12_read_only_pipeline/m12_2_daily_observation/m12_2_daily_observation_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m12_read_only_pipeline/m12_2_daily_observation/m12_2_observation_events.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/m12_read_only_pipeline/m12_2_daily_observation/m12_2_strategy_status_matrix.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_review/m12_3_precheck/m12_3_visual_precheck_index.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_review/m12_3_precheck/m12_3_user_review_packet.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_review/m12_3_precheck/m12_3_visual_gate_recommendation.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_4_definition_fix_and_retest/m12_4_definition_fix_summary.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_4_definition_fix_and_retest/m12_4_before_after_metrics.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_4_definition_fix_and_retest/m12_4_definition_fix_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_4_definition_fix_and_retest/m12_4_retest_client_summary.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_4_definition_fix_and_retest/m12_4_handoff.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/scanner/m12_5_liquid_universe_scanner/m12_5_universe_definition.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/scanner/m12_5_liquid_universe_scanner/m12_5_cache_inventory.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/scanner/m12_5_liquid_universe_scanner/m12_5_scanner_candidates.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/scanner/m12_5_liquid_universe_scanner/m12_5_scanner_summary.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/scanner/m12_5_liquid_universe_scanner/m12_5_deferred_inputs.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/scanner/m12_5_liquid_universe_scanner/m12_5_scanner_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/scanner/m12_5_liquid_universe_scanner/m12_5_handoff.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/weekly_scorecard/m12_6/m12_6_strategy_dashboard.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/weekly_scorecard/m12_6/m12_6_weekly_client_scorecard.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/weekly_scorecard/m12_6/m12_6_next_week_action_plan.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/weekly_scorecard/m12_6/m12_6_weekly_client_scorecard_summary.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/weekly_scorecard/m12_6/m12_6_handoff.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/paper_gate/m11_5_recheck/m11_5_paper_gate_recheck_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/paper_gate/m11_5_recheck/m11_5_candidate_strategy_list.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/paper_gate/m11_5_recheck/m11_5_blockers_and_approvals.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_summary.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_comparison.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_simulated_events.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_equity_curve.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_daily_trend_benchmark_deferred_inputs.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/benchmark/m12_7_daily_trend_benchmark/m12_7_handoff.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_universe_cache_manifest.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_deferred_or_error_ledger.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_fetch_plan.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_scanner_available_universe.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_cache_completion_summary.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_cache_coverage_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_handoff.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_review/m12_9_closure/m12_9_visual_closure_index.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_review/m12_9_closure/m12_9_case_review_ledger.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_review/m12_9_closure/m12_9_user_review_packet.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_review/m12_9_closure/m12_9_visual_gate_closure_report.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/visual_review/m12_9_closure/m12_9_handoff.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_10_definition_fix_and_retest/m12_10_retest_summary.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_10_definition_fix_and_retest/m12_10_before_after_metrics.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_10_definition_fix_and_retest/m12_10_pa005_geometry_events.csv`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_10_definition_fix_and_retest/m12_10_retest_client_summary.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/definition_fix/m12_10_definition_fix_and_retest/m12_10_handoff.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/dashboard/m12_11_readonly_trading_dashboard/m12_11_dashboard_data.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/dashboard/m12_11_readonly_trading_dashboard/m12_11_readonly_trading_dashboard.html`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/dashboard/m12_11_readonly_trading_dashboard/m12_11_dashboard_snapshot.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/dashboard/m12_11_readonly_trading_dashboard/m12_11_handoff.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/paper_gate/m11_5_recheck/m11_5_blockers_and_approvals.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/paper_gate/m11_5_recheck/m11_5_paper_gate_recheck_summary.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/paper_gate/m11_5_recheck/m11_5_handoff.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/workspace_audit_legacy_inventory_m10.md`
- M10.1 当前冻结 `16` 条 `M10-PA-*` 策略/规则；Visual golden case 只适用于 `M10-PA-003/004/007/008/009/010/011`，不是所有策略的统一门槛。
- M10.2 当前已为上述 7 条策略生成 `visual_golden_cases/` 图例包，`ready_count=7 / blocked_count=0`；该状态只表示 Brooks v2 图例 evidence path 与 checksum 完整，不代表策略有效或盈利。
- M10.3 已为 Wave A 的 `M10-PA-001/002/005/012` 冻结可执行 backtest specs。
- M10.4 已跑通 Wave A historical pilot：`SPY / QQQ / NVDA / TSLA`、`1d / 1h / 15m / 5m` 独立测试线中应跑的 `14` 个 strategy/timeframe 组合均已输出 artifacts；`1d` 使用 `2010-06-29 ~ 2026-04-21` 长窗口，`15m / 1h` 记录为 `derived_from_5m`。
- M10.4 只验证 spec 可执行性和测试链路质量；当前所有组合 outcome 为 `continue_testing`，没有 `retain/promote` 或收益结论。
- M10.5 已完成 read-only observation plan：只读观察候选队列只包含 `M10-PA-001/002/005/012` 的合法 Wave A timeframe；当前输入状态为 `observation_input_deferred`，未启动 observation runner。
- M10.5 已把 `M10-PA-005` 的 `1h / 15m / 5m` 标记为 `definition_breadth_review`；这只是定义宽度复核，不是收益或实盘结论。
- M10.6 已完成 recorded replay observation ledger：当前 `event_count=108640`、`candidate_event_count=73619`、`skip_no_trade_count=35021`、`deferred_input_count=0`。
- M10.6 ledger 只用于输入/schema/bar-close 记录与人工复核流程；不是实时行情观察，不证明策略有效或盈利。
- M10.7 已冻结甲方报告口径：后续资金曲线测试默认使用 `100,000 USD` 初始本金、`0.5%` 单笔风险、`1 / 2 / 5 bps` 成本压力；本阶段未运行新回测，也未批准 paper trading。
- M10.8 已完成 Wave A capital backtest：`M10-PA-001/002/005/012` 已输出 baseline trade ledger、三档成本 metrics、strategy scorecard、client report 和 equity curve CSV/SVG；`M10-PA-005` 仍为 `needs_definition_fix`。
- M10.9 已完成 `M10-PA-005` definition tightening retest：日内 `1h / 15m / 5m` 通过重复确认去重与 20-bar 冷却降低触发密度；因 M10.4 candidate events 未持久化 range geometry，策略仍保持 `needs_definition_fix`。
- M10.10 已完成 visual Wave B gate：`M10-PA-003/008/009/011` 进入 Wave B，`M10-PA-013` 作为既有 Wave B 候选并入；`M10-PA-004/007/010` 暂不进入自动回测。
- M10.11 已完成 Wave B capital backtest：`M10-PA-013/003/008/009/011` 已输出 baseline trade ledger、三档成本 metrics、strategy scorecard、client report 和 equity curve CSV/SVG。
- M10.12 已完成 all-strategy scorecard：16 条 `M10-PA-*` 汇总为最终状态矩阵，当前为 `8` 条完成资金测试、`3` 条需要定义修正、`1` 条图形复核保留、`2` 条 supporting-only、`2` 条 research-only；portfolio proxy 只纳入已完成资金测试策略，排除仍需定义修正的 `M10-PA-005`，final equity 为 `105728.18 USD`，但不是可执行组合回测。
- M10.13 已完成 read-only observation runbook：主观察队列为 `M10-PA-001/002/012/008/009`，覆盖 `13` 个策略周期；`M10-PA-005` 因定义未闭合排除，`M10-PA-003/011/013` 进入 watchlist/deferred。
- M11 已完成 paper gate report：候选池仍来自 M10.13 主观察队列，`M10-PA-001/002/012` 为 Tier A 核心观察候选，`M10-PA-008/009` 为 Tier B 视觉条件候选；当前 gate decision 为 `not_approved`，没有任何候选可作为 paper trading approval evidence。
- M12.0 已完成 Longbridge read-only auth preflight：本地 Longbridge CLI 与当前 token 的 quote/K 线只读探针可用，且 artifact 明确保持 `broker_connection=false / real_orders=false / live_execution=false / paper_trading_approval=false`。
- M12.1 已完成 Longbridge read-only feed：生成 `16` 条 `SPY/QQQ/NVDA/TSLA x 1d/1h/15m/5m` 只读 bar-close feed ledger；该阶段只生成输入，不运行策略、不生成交易/账户字段、不输出盈亏结论。
- M12.2 已完成 core strategy daily observation：生成 `32` 条 Tier A 只读观察记录；由于 M12.1 feed 只有单根 latest bar，当前全部记录为 `skip_no_trade`，不伪造策略触发、不批准 paper trading。
- M12.3 已完成 visual review precheck：复用 M10.2/M10.10 现有图例与 gate 产物，生成 `7` 条 strategy rows 与 `30` 条 case rows；本阶段只做 agent 预审和人工复核包，不替代人工图形判断。
- M12.4 已完成 definition fix and retest：`M10-PA-005` 有复测 before/after 数字但仍未解除 `needs_definition_fix`；`M10-PA-004/007` 仅登记定义字段缺口和图例证据，不伪造交易结果。
- M12.5 已完成 liquid universe scanner：股票/ETF seed 共 `147` 只，当前本地 cache 实际扫描 `4` 只，输出 `12` 条 Tier A 候选；缺数据的 `143` 只 seed 全部 deferred。M12.8 已把这 `147` 只 seed 的只读 K 线 coverage / deferred / fetch-plan 入账；在真实补齐前不得把 scanner 结果描述为 full universe 可用。
- M12.6 已完成 weekly client scorecard：输出 `16` 条策略 dashboard，周报汇总历史资金测试、每日只读观察、scanner 候选、图形复核和定义修正；当前交易状态仍为 `closed_not_authorized`。
- M11.5 已完成 paper gate recheck：复查 `M10-PA-001/002/012/008/009` 后仍为 `not_approved`；当前必须先补齐真实只读观察窗口、completed candidate events、`M10-PA-008/009` 人工图形复核、`M10-PA-005/004/007` definition blocker 关闭或正式降级、scanner cache 覆盖计划和人工业务审批。
- M12.7 已完成早期日线截图策略复用：`M12-BENCH-001` 只作为 `signal_bar_entry_placeholder` 的日线 trend benchmark；长窗口结果为 `scanner_factor_candidate`，但不得作为准入证据或 M10 clean-room 策略来源。
- M12.8 已完成 universe cache coverage / deferred / fetch-plan：`147` 只 seed 全部入账，当前有任一 native cache 的标的是 `4` 只，完整覆盖目标窗口标的是 `0` 只，`588` 个缺口全部 deferred，`294` 个 native cache 请求进入只读 fetch plan；在真实补齐前不得宣称 full universe scanner 可用。
- M12.9 已完成 visual review closure overlay：覆盖 `M10-PA-008/009/003/011/004/007` 共 `6` 条策略与 `30` 个 case；`M10-PA-008/009` 已完成 agent-side closure 但仍需用户确认后才可讨论 gate evidence，`M10-PA-004/007` 仍只作为 definition evidence support。
- M12.10 已完成 definition fix/retest：`M10-PA-005` 已补齐 `34651` 条 range geometry event ledger，但复测后仍为 `reject_for_now_after_geometry_review`；`M10-PA-004/007` 正式降级为 visual-only / manual-labeling，不再进入自动回测队列。
- M12.11 已完成 read-only trading dashboard：本地 HTML 看板汇总 `12` 条 scanner 候选、`32` 条只读观察事件、`4` 个只读标的 latest bar close、`10` 个模拟资金曲线引用、M12.10 definition 决策和 M11.5 gate 状态；看板只使用 readonly / hypothetical / simulated 语义。
- M12.12 已完成 daily observation loop 第一版：第一批 `50` 只股票/ETF 的 `1d` 长窗口与当前交易日 `5m` 只读 K 线已补齐，生成 `141` 条每日只读候选、中文看板、全策略状态总表、`M10-PA-008/009` 图形确认包和 M11.6 模拟准入复查；长历史 `5m` 全窗口仍未补齐。
- 下一步是连续运行 M12.12 日常更新，累计 `10` 个交易日看板记录，并同步关闭 `M10-PA-008/009` 用户图形确认；达到条件后再进入 M11.6 模拟交易试运行批准。
- `M10-PA-014/015` 只能作为 supporting rules，`M10-PA-006/016` 保持 research-only。
- 自 `M9G.0` 起，旧 `PA-SC-*` strategy cards、测试计划与回测报告都只作为 legacy / historical baseline 保留。
- M9 Strategy Factory 的 `SF-*` catalog/spec/triage 现在也只作为 legacy comparison，不再作为 M10 clean-room 提炼输入。
- 如需查看 M9 历史，应阅读：
  - `docs/strategy-factory.md`
  - `reports/strategy_lab/strategy_factory_plan.md`
  - `reports/strategy_lab/strategy_factory/final_summary.md`

## 先看哪个分支

- 当前 M12.12 阶段分支在：`feature/m12-12-daily-observation-loop`
- 当前 M10/M12 稳定基线在：`main`
- 长期稳定基线仍是：`main`

如果你的目标是判断“项目现在做到哪里了，以及下一步最该提炼/测试什么策略”，应优先查看 M10 目录，不要把 M9 `PA-SC-*` 或 `SF-*` 当作当前策略先验。

## 当前阶段

- `M9A`~`M9F` 首轮已完成，但当前全部视为 legacy / historical baseline：
  - 已建立 strategy cards 目录与模板
  - 已盘点 transcript / Brooks PPT / notes
  - 已产出首批 `10` 张策略卡
  - 已为优先策略写测试计划
  - 已输出普通人可读的 strategy lab 总结
- `M9G.0` 已完成：
  - 已冻结 Strategy Factory 的 legacy boundary、provider contract、`SF-*` 命名空间与 ledger/run_state 模板

## 当前最重要的阅读顺序

1. 项目整体状态：
   - `docs/status.md`
   - `plans/active-plan.md`
2. Strategy Factory 契约：
   - `docs/strategy-factory.md`
   - `reports/strategy_lab/strategy_factory_plan.md`
   - `knowledge/wiki/strategy_factory/index.md`
3. Legacy 对照基线：
   - `reports/strategy_lab/m9_strategy_lab_summary.md`
   - `knowledge/wiki/strategy_cards/index.md`
4. `PA-SC-002` 历史 benchmark：
   - `knowledge/wiki/strategy_cards/combined/pa-sc-002-breakout-follow-through.md`
   - `knowledge/wiki/strategy_cards/combined/PA-SC-002-executable-v0.1.md`
5. `PA-SC-002` 第一轮实验：
   - `reports/strategy_lab/pa_sc_002_minimum_experiment_v0.1.md`
   - `reports/strategy_lab/pa_sc_002_first_backtest_report.md`
6. `PA-SC-002` 深入诊断：
   - `reports/strategy_lab/pa_sc_002_diagnostic_analysis.md`
   - `reports/strategy_lab/pa_sc_002_variant_suite.md`

## 当前最重要的业务结论

- 当前没有任何策略可以被表述为“已稳定盈利”。
- `PA-SC-002 v0.1` 已经可以被客观化并完成最小回测，但当前成本后仍为亏损。
- 当前更像是“全天候版本过宽”，不是“breakout follow-through 这个策略族必然无效”。
- 目前最值得继续正式重测的方向是：
  - `Midday Block`
- 但这仍然只是“下一轮候选假设”，不是已经确认的正式升级版。
- `Late Only` 只可视为 diagnostic upper bound，不能直接当作正式方案。

## 如果要让 ChatGPT 网页版继续给策略建议

最值得让它重点分析的是这几份文件：

- `reports/strategy_lab/m9_strategy_lab_summary.md`
- `knowledge/wiki/strategy_cards/index.md`
- `knowledge/wiki/strategy_cards/combined/pa-sc-002-breakout-follow-through.md`
- `knowledge/wiki/strategy_cards/combined/PA-SC-002-executable-v0.1.md`
- `reports/strategy_lab/pa_sc_002_first_backtest_report.md`
- `reports/strategy_lab/pa_sc_002_diagnostic_analysis.md`
- `reports/strategy_lab/pa_sc_002_variant_suite.md`

建议让它重点回答：

- `PA-SC-002` 当前亏损更像是规则太宽、时段不对，还是过滤器不够强？
- `Midday Block` 是否值得作为 `v0.2` 的唯一正式重测版本？
- 在不扩成大规模调参项目的前提下，`PA-SC-002` 下一轮最小改动应该是什么？
- 在 `PA-SC-002` 还未收敛前，是否应该暂缓 `PA-SC-003 / PA-SC-005`？

## 关于原始资料

- `knowledge/raw/` 仍保持只读。
- 本仓库的 GitHub 分支主要展示“策略提炼方案、策略卡、测试计划、回测与诊断报告”。
- 部分超大 raw PDF 不适合直接推送到普通 GitHub 仓库；即使不在远端，当前 strategy lab 的提炼进度和研究结论也已经完整体现在上述 Markdown 与实验产物中。
