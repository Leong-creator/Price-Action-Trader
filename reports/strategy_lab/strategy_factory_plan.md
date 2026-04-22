# Strategy Factory Plan

## 当前口径

- 本文件当前对应 `M9 Strategy Factory Full Extraction Completeness Audit v4` 的仓库落地结果。
- 新 factory 始终从 `knowledge/indices/source_manifest.json` 覆盖的全部来源重新开始，不以 legacy `PA-SC-*` 为 seed。
- 旧 `PA-SC-*` 与 `PA-SC-002` 继续只作为 legacy / historical comparison / benchmark 资料。
- 新 catalog 的编号空间固定为 `SF-*`。

## 已落地内容

- provider contract 已冻结：
  - `config/strategy_factory/active_provider_config.json`
  - `reports/strategy_lab/strategy_factory/run_state.json`
- 已落地 v4 审计产物：
  - `reports/strategy_lab/strategy_catalog.json`
  - `reports/strategy_lab/strategy_dedup_map.json`
  - `reports/strategy_lab/chunk_adjudication.jsonl`
  - `reports/strategy_lab/source_family_completeness_report.json`
  - `reports/strategy_lab/source_theme_coverage.json`
  - `reports/strategy_lab/cross_chunk_synthesis.json`
  - `reports/strategy_lab/cross_source_corroboration.json`
  - `reports/strategy_lab/cross_source_corroboration_final.json`
  - `reports/strategy_lab/overmerge_review.json`
  - `reports/strategy_lab/saturation_report.json`
  - `reports/strategy_lab/unresolved_strategy_extraction_gaps.json`
  - `reports/strategy_lab/full_extraction_audit.json`
  - `reports/strategy_lab/factory_summary.md`
  - `reports/strategy_lab/cards/SF-001.md` ~ `SF-005.md`
  - `reports/strategy_lab/specs/SF-001.yaml` ~ `SF-005.yaml`
- 已冻结的 catalog：
  - `SF-001 Trend Pullback Second Entry`
  - `SF-002 Breakout Follow-Through Continuation`
  - `SF-003 Failed Breakout Range-Edge Reversal`
  - `SF-004 Tight Channel Trend Continuation`
  - `SF-005 Gap Continuation Versus Exhaustion`

## 当前 closure 结论

- `text_extractable_closure=true`
- `full_source_closure=false`
- 原因：visual-heavy / partial source gaps 仍存在，当前已逐条写入 `unresolved_strategy_extraction_gaps.json`。
- `saturation_report.json` 已满足双轮连续零增量 closure。
- `cross_source_corroboration_final.json` 已在 catalog freeze 后重算。

## M9H Wave2 扩样本回测结果

- 已完成 `Controlled Batch Backtest + Strategy Triage` 的 wave2 扩样本回测。
- 本轮只推进：
  - `SF-001`
  - `SF-002`
  - `SF-003`
  - `SF-004`
- 本轮保持 deferred：
  - `SF-005`，原因：`single_source_risk` 与 family 边界偏粗
- wave2 数据范围：
  - `SPY / QQQ / NVDA / TSLA`
  - `5m`
  - `2025-04-01 ~ 2026-04-21`
  - `primary provider = longbridge`
- 已落盘：
  - `reports/strategy_lab/backtest_eligibility_matrix.json`
  - `reports/strategy_lab/backtest_dataset_inventory.json`
  - `reports/strategy_lab/executable_spec_queue.json`
  - `reports/strategy_lab/backtest_queue.json`
  - `reports/strategy_lab/backtest_batch_summary.json`
  - `reports/strategy_lab/strategy_triage_matrix.json`
  - `reports/strategy_lab/final_strategy_factory_report.md`
  - `reports/strategy_lab/final_strategy_factory_trade_report.md`
  - `reports/strategy_lab/final_strategy_factory_cash_report.md`
- 当前 wave2 triage 结论：
  - `SF-001 = modify_and_retest`
  - `SF-002 = modify_and_retest`
  - `SF-003 = modify_and_retest`
  - `SF-004 = modify_and_retest`
  - `SF-005 = deferred_single_source_risk`
- 当前 wave2 sample status：
  - `SF-001 ~ SF-004 = robust_candidate`
  - `SF-005 = not_run`
- 当前仍未做：
  - 未进入 broker / live / real-money。
  - 未改 trigger。
  - 未修改 `knowledge/raw/`。

## 下一步

- 下一步不是自动扩大 batch backtest，而是先完成 PR #2 merge gate；若通过，则进入更窄范围的 `v0.2 spec freeze`。
- 若进入下一阶段，只允许基于已冻结的 `SF-*` catalog、`cross_source_corroboration_final.json`、`strategy_triage_matrix.json` 与 `unresolved_strategy_extraction_gaps.json` 选择候选。
- wave2 已证明单纯继续扩样本不足以直接把 family 升为 retain/promoted；`quality_filter` 只能被解释为 `diagnostic_selected_variant`，下一步重点应转向 `v0.2 spec freeze`，再决定是否进入更正式的 retest。

## M9I.1 v0.2 Candidate Spec Freeze

- 已基于 wave2 已测试的 `quality_filter` 观察结果，冻结以下 `v0.2-candidate` spec：
  - `reports/strategy_lab/specs/SF-001-v0.2-candidate.yaml`
  - `reports/strategy_lab/specs/SF-002-v0.2-candidate.yaml`
  - `reports/strategy_lab/specs/SF-003-v0.2-candidate.yaml`
  - `reports/strategy_lab/specs/SF-004-v0.2-candidate.yaml`
- 这些 `v0.2-candidate` 只允许作为下一轮验证输入，不得解释成已验证正式策略。
- `SF-005` 继续保持 `deferred_single_source_risk`，未纳入 `v0.2-candidate` freeze。
- 本阶段已落盘：
  - `reports/strategy_lab/v0_2_spec_freeze_summary.md`
- 本阶段不做：
  - 新 batch backtest
  - 新策略提炼
  - visual gap closure

## M9I.2 Wave3 Holdout / Walk-forward Robustness Validation

- 已完成对 4 份 frozen `v0.2-candidate` spec 的 `Wave3` robustness validation。
- 本轮验证对象固定为：
  - `SF-001`
  - `SF-002`
  - `SF-003`
  - `SF-004`
- `SF-005` 不在本轮验证范围内。
- 本轮数据窗口与切分：
  - `SPY / QQQ / NVDA / TSLA`
  - `5m`
  - 目标窗口：`2024-04-01 ~ 2026-04-22`
  - 实际公共窗口：`2025-04-01 ~ 2026-04-21`
  - `core_history = 225 sessions`
  - `proxy_holdout = 40 sessions`
  - `strict_post_freeze_holdout = 0 sessions`
  - `walk-forward = 4 windows`
- 本轮已落盘：
  - `reports/strategy_lab/wave3_robustness_summary.md`
  - `reports/strategy_lab/wave3_robustness_summary.json`
  - `reports/strategy_lab/SF-001/wave3/`
  - `reports/strategy_lab/SF-002/wave3/`
  - `reports/strategy_lab/SF-003/wave3/`
  - `reports/strategy_lab/SF-004/wave3/`
- 当前 `Wave3` triage 结论：
  - `SF-001 = modify_and_retest`
  - `SF-002 = modify_and_retest`
  - `SF-003 = modify_and_retest`
  - `SF-004 = insufficient_sample`
- 当前没有 `retain_candidate`，原因不是策略已被否定，而是：
  - 没有严格意义上的 post-freeze holdout
  - `retain_candidate` gate 被锁定依赖 strict holdout
- 当前仓库状态应解释为：
  - `v0.2-candidate specs frozen`
  - `Wave3 completed`
  - `eligible to decide among paper shadow / 再修改 / 继续补 SF-005 evidence`
- 当前默认下一步不是自动继续扩大回测，而是三选一：
  - `paper shadow`
  - `再修改`
  - `继续补 SF-005 evidence`
