# PR #3 Merge Gate Report

- `pr_number`: `3`
- `pr_title`: `[codex] Add M9I.2 Wave3 robustness validation artifacts`
- `base_ref`: `main`
- `head_ref`: `feature/m9-wave3-robustness-validation`
- `merge_gate_status`: `merge_ready`
- `blocker_count`: `0`

## 1. 审核范围

本次只审核 PR #3 当前内容是否自洽、是否适合合并到 `main`，以及是否可作为后续历史扩样回测的干净基线。

已核对：

- `reports/strategy_lab/wave3_robustness_summary.md`
- `reports/strategy_lab/wave3_robustness_summary.json`
- `reports/strategy_lab/strategy_triage_matrix.json`
- `reports/strategy_lab/backtest_dataset_inventory.json`
- `reports/strategy_lab/v0_2_spec_freeze_summary.md`
- `plans/active-plan.md`
- `docs/status.md`
- `docs/acceptance.md`
- `docs/strategy-factory.md`
- `config/examples/public_history_backtest_long_horizon_longbridge.json`
- `docs/user-backtest-guide.md`
- PR #3 compare diff 与已落盘 `Wave3` 子目录产物

## 2. 结果一致性结论

### 2.1 Wave3 triage 一致性

- `wave3_robustness_summary.json` 与 `wave3_robustness_summary.md` 一致：
  - `SF-001 = modify_and_retest`
  - `SF-002 = modify_and_retest`
  - `SF-003 = modify_and_retest`
  - `SF-004 = insufficient_sample`
- `strategy_triage_matrix.json` 当前快照与上述结论一致，并保留 `history[]`：
  - `SF-001 ~ SF-003` 当前为 `modify_and_retest`
  - `SF-004` 当前为 `insufficient_sample`
  - `SF-005` 保持 `deferred_single_source_risk`

### 2.2 retain_candidate / ready_for_backtest 语义

- `retain_candidate_count = 0` 在 `wave3_robustness_summary.json` 与 Markdown summary 中一致。
- 文档口径一致写明：由于当前没有 `strict post-freeze holdout`，本轮不允许输出 `retain_candidate`。
- `ready_for_backtest = true` 仅存在于更早的 extraction-stage artifact（`full_extraction_audit.json`），代表“catalog 在当时具备进入下一阶段的资格”，不代表 `Wave3` 当前已产生可晋级结论；与当前 `Wave3` triage 不冲突。

### 2.3 spec freeze 与 Wave3 输入一致性

- `v0_2_spec_freeze_summary.md` 明确：
  - `SF-001 ~ SF-004` 是 frozen `v0.2-candidate`
  - `SF-005` 未纳入 freeze
- `Wave3` 只加载：
  - `SF-001-v0.2-candidate.yaml`
  - `SF-002-v0.2-candidate.yaml`
  - `SF-003-v0.2-candidate.yaml`
  - `SF-004-v0.2-candidate.yaml`
- 未发现 `SF-005-v0.2-candidate` 被错误纳入。

## 3. 数据源与 dataset inventory 结论

- provider contract 通过：`primary_provider = longbridge`
- `backtest_dataset_inventory.json` 与当前仓库状态一致：
  - `phase = M9I.2`
  - `provider = longbridge`
  - `common_start = 2025-04-01`
  - `common_end = 2026-04-21`
  - 4 个 symbol 都来自 `local_cache_fallback`
- `config/examples/public_history_backtest_long_horizon_longbridge.json` 与 `docs/user-backtest-guide.md` 的只读历史路径一致，未发现旧 provider 默认值残留。

## 4. 文档同步结论

以下文档已同步到 `M9I.2 Wave3` 口径：

- `plans/active-plan.md`
- `docs/status.md`
- `docs/acceptance.md`
- `docs/strategy-factory.md`
- `reports/strategy_lab/strategy_factory_plan.md`

文档当前一致表达：

- `Wave3` 只验证 frozen `v0.2-candidate`
- `SF-005` 不在本轮
- 没有 `strict post-freeze holdout` 时，不能给 `retain_candidate`
- 当前下一步是三选一：
  - `paper shadow`
  - `再修改`
  - `继续补 SF-005 evidence`

## 5. 验证记录

本次 merge gate 已执行并通过：

- `python scripts/validate_strategy_factory_contract.py`
- `python scripts/validate_kb.py`
- `python -m unittest tests/unit/test_strategy_factory_docs_sync.py tests/unit/test_strategy_triage.py tests/unit/test_strategy_factory_dataset_inventory.py tests/unit/test_strategy_factory_queue.py tests/unit/test_wave3_spec_loading.py tests/unit/test_wave3_split_integrity.py tests/unit/test_wave3_cost_stress.py tests/unit/test_wave3_triage.py tests/reliability/test_strategy_factory_pipeline.py -v`
- `git diff --check`

## 6. Merge Gate 结论

1. PR #3 是否可合并：
   - `yes`
2. 是否存在 blocker：
   - `no`
3. 是否适合作为后续历史扩样回测的干净基线：
   - `yes`
4. 建议基线：
   - 优先以“PR #3 合并后的 `main`”作为下一阶段唯一基线
   - 若必须在合并前引用具体提交，则以当前 head commit 为准

