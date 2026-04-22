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

- 下一步不是自动扩大 batch backtest，而是等待更窄范围的下一波重测决策。
- 若进入下一阶段，只允许基于已冻结的 `SF-*` catalog、`cross_source_corroboration_final.json`、`strategy_triage_matrix.json` 与 `unresolved_strategy_extraction_gaps.json` 选择候选。
- wave2 已证明单纯继续扩样本不足以直接把 family 升为 retain/promoted；下一步重点应转向按 `quality_filter` 收紧 executable spec，再决定是否进入更正式的 retest。
