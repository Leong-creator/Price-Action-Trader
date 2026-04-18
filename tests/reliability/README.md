# Reliability Tests

`tests/reliability/` 用于放置 `M8` 的可靠性验证测试，包括知识库对齐、离线 determinism / leakage 守卫、shadow/paper baseline 约束，以及 `M8D` 一致性修复回归。

当前目录已包含实际测试实现，不再是 `M8A` skeleton-only 目录。

约束：

- 真实历史数据只能以本地 CSV/JSON 形式接入。
- 实时输入只允许 shadow / paper 观察路径。
- 不得接入真实 broker、真实账户或 live execution。
- 不依赖外部网络。

当前代表性测试：

- `test_kb_alignment.py`、`test_no_hallucinated_kb_refs.py`
- `test_replay_determinism.py`、`test_no_future_leakage.py`
- `test_long_horizon_daily_validation.py`、`test_intraday_pilot_validation.py`
- `test_shadow_paper_consistency.py`、`test_dataset_manifest_contract.py`
- `test_curated_promotion_minimal_set.py`、`test_strategy_atom_trace.py`
