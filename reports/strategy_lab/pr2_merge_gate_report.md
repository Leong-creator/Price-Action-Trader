# PR #2 Merge Gate & Result Integrity Audit

- `pr_number`: `2`
- `head_ref`: `feature/m9-strategy-factory-batch-backtest-wave2`
- `base_ref`: `main`
- `mergeable`: `MERGEABLE`
- `audit_baseline`: `main...feature/m9-strategy-factory-batch-backtest-wave2`
- `merge_recommendation`: `merge_ready`
- `next_step_recommendation`: `enter_v0.2_spec_freeze`

## Validation

- `python scripts/validate_strategy_factory_contract.py`: passed
- `python scripts/validate_kb.py`: passed
- `git diff --check`: passed
- `python -m unittest tests/unit/test_strategy_factory_backtest_eligibility.py tests/unit/test_strategy_factory_dataset_inventory.py tests/unit/test_strategy_factory_queue.py tests/unit/test_strategy_triage.py tests/unit/test_strategy_factory_backtest_logic.py tests/reliability/test_strategy_factory_pipeline.py -v`: passed

## Merge Gate Decision

1. PR #2 是否可合并：
   - `是`。当前 GitHub 状态为 `MERGEABLE`，且在补足结果解释后，本轮未发现阻止合并的剩余 blocker。
2. 是否存在 blocker：
   - `否`。本轮原始 blocker 是 `SF-003` 与 `SF-004` 的 R/cash 异号缺少解释；现已在现金报告、总报告和本审计报告中补足说明。
3. R/cash 是否一致或已解释：
   - `已解释`。`SF-001` 与 `SF-002` 保持同号；`SF-003 baseline`、`SF-003 quality_filter`、`SF-004 quality_filter` 为异号案例，但它们来自独立 cash sizing layer 对多标的聚合结果的重新加权，不应被解读成 “R 的美元等价物”。
4. 当前四个已测策略为什么仍是 `modify_and_retest`：
   - `SF-001`、`SF-002`：`quality_filter` 相对 baseline 改善明显，但它只是 `diagnostic_selected_variant`，下一步应先冻结更窄的 `v0.2 spec`，不能直接升格为正式规则。
   - `SF-003`、`SF-004`：`quality_filter` 虽相对 baseline 改善，但 best variant 在 R 口径仍未转正，因此继续保持 `modify_and_retest` 是必要的。
5. `SF-005` 为什么 deferred：
   - `SF-005` 仍然只有 `single-source corroboration`，且 family 边界偏粗，当前必须继续保持 `deferred_single_source_risk`，不能与 `SF-001 ~ SF-004` 一起推进。
6. 合并后下一步是否进入 `v0.2 spec freeze`：
   - `是`。PR #2 合并后，默认下一步应进入更窄范围的 `v0.2 spec freeze`；本轮不建议自动开启新的 batch backtest。

## Integrity Notes

- `quality_filter` 在本 PR 中统一解释为 `diagnostic_selected_variant`，不是正式冻结策略、不是 validated rule、不是默认生产版本。
- `robust_candidate` 只表示样本覆盖更充分，不代表稳定盈利、实盘 readiness 或自动交易能力。
- cash report 是独立解释层。它保留对 `$25,000 / $100 risk per trade` 的研究型 sizing 映射，但不能覆盖 trade report 的 R 口径结论。
