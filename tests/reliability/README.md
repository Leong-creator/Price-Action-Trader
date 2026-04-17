# Reliability Tests

`tests/reliability/` 用于放置 M8D 的稳健性与 shadow / paper 验证框架测试。

当前阶段仅完成 M8A 测试骨架，不落真实测试实现。

约束：

- 真实历史数据只能以本地 CSV/JSON 形式接入。
- 实时输入只允许 shadow / paper 观察路径。
- 不得接入真实 broker、真实账户或 live execution。
- 不依赖外部网络。

后续建议内容：

- `test_historical_robustness_*.py`
- `test_shadow_paper_guardrails_*.py`
- `fixtures/` 与 `reports/` 的本地快照说明
