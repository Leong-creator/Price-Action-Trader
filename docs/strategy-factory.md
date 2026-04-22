<!-- strategy_factory_provider_contract={"active_provider_config_path":"config/strategy_factory/active_provider_config.json","primary_provider_runtime_source":"source_order[0]"} -->

# Strategy Factory Contract

## 1. 目标

`M9G Strategy Factory` 的目标是把 `knowledge/indices/source_manifest.json` 覆盖的全部知识来源重新进入统一的 extraction / queue / catalog / triage 流程，并把旧 `PA-SC-*` 产物降级为 historical baseline。

## 2. Legacy 边界

- `knowledge/wiki/strategy_cards/` 继续保留，但只作为 legacy / historical baseline。
- 旧 `PA-SC-*` 编号、命名、聚类、结论与 triage 结果不得作为新 catalog 的 seed、family prior、默认 merge target 或 queue baseline。
- `PA-SC-002` 只允许作为 `historical_benchmark_refs` 或 regression reference，不得主导新 catalog 结构。
- 新 catalog 的唯一编号空间是 `SF-*`。

## 3. Provider Contract

- `primary_provider` 的唯一运行时来源是 `reports/strategy_lab/strategy_factory/run_state.json` 中的 `active_provider_config_path` 指向的 repo 配置文件。
- 当前固定配置文件为 `config/strategy_factory/active_provider_config.json`。
- `primary_provider` 必须等于该配置文件中 `source_order[0]` 的值。
- 计划、状态、验收与数据源文档只允许描述这个 contract，不得把具体 provider 名称写成长期固定口径。
- 任何 provider 切换都必须先更新配置，再通过 `python scripts/validate_strategy_factory_contract.py`。

## 4. 目录与台账

### Wiki 根目录

- `knowledge/wiki/strategy_factory/index.md`
- `knowledge/wiki/strategy_factory/strategies/`
- `knowledge/wiki/strategy_factory/specs/`
- `knowledge/wiki/strategy_factory/test_plans/`

### 运行台账

- `reports/strategy_lab/strategy_factory/coverage_ledger.json`
- `reports/strategy_lab/strategy_factory/extraction_queue.json`
- `reports/strategy_lab/strategy_factory/catalog_ledger.json`
- `reports/strategy_lab/strategy_factory/backtest_queue.json`
- `reports/strategy_lab/strategy_factory/triage_ledger.json`
- `reports/strategy_lab/strategy_factory/run_state.json`
- `reports/strategy_lab/strategy_factory/final_summary.md`

## 5. 关键字段

### Strategy Factory frontmatter / ledger 字段

- `factory_stage`
- `readiness_gate`
- `factory_decision`
- `decision_reason`
- `legacy_overlap_refs`
- `historical_comparison_refs`
- `historical_benchmark_refs`

### `readiness_gate`

- `ready`
- `needs_visual_review`
- `needs_event_labels`
- `needs_definition_freeze`
- `blocked_source`
- `blocked_provider`

### `factory_decision`

- `retain`
- `modify_and_retest`
- `insufficient_sample`
- `parked`
- `rejected_variant`

### `coverage_ledger` source 状态

- `pending`
- `mapped`
- `partial`
- `blocked`
- `parked`

## 6. Resume Contract

- heartbeat 或后续自动推进只允许依赖 `coverage_ledger.json`、`extraction_queue.json`、`catalog_ledger.json`、`backtest_queue.json`、`triage_ledger.json` 与 `run_state.json`。
- `resume_cursor` 是唯一恢复游标。
- 不得依赖隐含聊天上下文、线程记忆或“之前在别的聊天说过”的状态。

## 7. 当前阶段

- 当前已完成 `M9 Strategy Factory Full Extraction Completeness Audit v4`。
- 已完成：
  - `Full-Pass Chunk Adjudication`
  - `Cross-Chunk Synthesis Pass`
  - `Discovery Closure`
  - `Overmerge Review`
  - `Notes Per-Source Findings`
  - `Source Section / Unit / Theme Coverage Matrix`
  - `Cross-Source Corroboration Report`
  - `Saturation / Convergence Pass`
  - `Strategy Closure 与 Catalog Freeze`
- 当前已冻结 `5` 张 `SF-*` strategy cards，并落盘到 `reports/strategy_lab/cards/` 与 `reports/strategy_lab/specs/`。
- 当前闭环结论必须区分：
  - `text_extractable_closure`
  - `full_source_closure`
- 当前结论为：
  - `text_extractable_closure=true`
  - `full_source_closure=false`
  - 仍存在 visual / partial gaps，已写入 `reports/strategy_lab/unresolved_strategy_extraction_gaps.json`
- 当前已完成 `M9H Controlled Batch Backtest + Strategy Triage` 的 wave2 扩样本回测：
  - `SF-001 ~ SF-004` 已进入 `SPY / QQQ / NVDA / TSLA`、`5m`、`2025-04-01 ~ 2026-04-21` 的多标的聚合 baseline + limited diagnostics。
  - `SF-005` 保持 `deferred_single_source_risk`。
  - 当前 triage 结论冻结为：
    - `SF-001 = modify_and_retest`
    - `SF-002 = modify_and_retest`
    - `SF-003 = modify_and_retest`
    - `SF-004 = modify_and_retest`
    - `SF-005 = deferred_single_source_risk`
- 当前样本覆盖结论为：
  - `SF-001 ~ SF-004 = robust_candidate`
  - `SF-005 = not_run`
- `quality_filter` 若被选为 best variant，只能解释为 `diagnostic_selected_variant`，不能被写成正式冻结策略。
- `ready_for_backtest` 仍然只是结论字段；wave2 已完成，但下一波不得自动启动，必须先完成 merge gate，并在通过后进入更窄范围的 `v0.2 spec freeze`。
- 当前已完成 `M9I.1 Freeze v0.2 Candidate Specs`：
  - 已新增 `SF-001 ~ SF-004` 的 `v0.2-candidate` 文件到 `reports/strategy_lab/specs/`。
  - 这些文件只作为候选包装层，保留 `SF-001.yaml ~ SF-004.yaml` 作为 `v0.1` 基线，不回写 `strategy_catalog.json`。
  - `v0.2-candidate` 只能来自 wave2 已观察到的 `quality_filter`，不得新增未测试过滤器。
  - 每个 `v0.2-candidate` 都必须绑定 wave2 证据路径、记录 `v0.1 -> v0.2-candidate` 的具体变更、预期改善和残余风险。
  - `SF-005` 在 `M9I.1` 继续保持 `deferred_single_source_risk`，不纳入 `v0.2-candidate` freeze。
  - `M9I.1` 完成后，仓库状态应解释为 `v0.2-candidate specs frozen; eligible to plan Wave3 robustness validation`，而不是自动进入新的 batch backtest。
