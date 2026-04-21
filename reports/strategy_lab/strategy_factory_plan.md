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

## 当前仍未做

- 未启动任何 batch backtest。
- 未改 trigger。
- 未碰 broker / live / real-money。
- 未修改 `knowledge/raw/`。

## 下一步

- 下一步不是自动进入回测，而是等待单独的 batch backtest 决策。
- 若进入下一阶段，只允许基于已冻结的 `SF-*` catalog、`cross_source_corroboration_final.json` 与 `unresolved_strategy_extraction_gaps.json` 选择候选。
