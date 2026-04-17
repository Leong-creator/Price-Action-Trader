# Reliability Reports

`reports/reliability/` 用于存放 M8 可靠性验证阶段生成的本地报告。

当前阶段仅完成 M8A 目录落盘，不生成真实报告结果。

约束：

- 只保留本地可回溯输出。
- 不写入伪造的真实历史结果。
- 不包含真实账户、真实 broker 或 live execution 数据。
- 保持 `paper / simulated` 边界。

建议后续子目录：

- `golden_cases/`
- `integration/`
- `reliability/`
