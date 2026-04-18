# Reliability Reports

`reports/reliability/` 用于存放 M8 可靠性验证阶段生成的本地报告。

本目录不再只是 `M8A` 占位目录；它用于存放 repo-safe、可回溯的 reliability / shadow-session 本地报告与说明。

约束：

- 只保留本地可回溯输出。
- 不写入伪造的真实历史结果。
- 不包含真实账户、真实 broker 或 live execution 数据。
- 保持 `paper / simulated` 边界。
- 不得伪装为真实盈利证明。

建议后续子目录：

- `golden_cases/`
- `integration/`
- `reliability/`
- `shadow_sessions/`

`M8 shadow/paper baseline` 报告最小字段建议：

- `dataset.dataset_name`
- `dataset.source_type`
- `dataset.market`
- `dataset.timeframe`
- `dataset.timezone`
- `dataset.regime_tags`
- `session.requested_mode`
- `session.read_only_input`
- `session.simulated_output`
- `summary.bar_count`
- `summary.signal_count`
- `summary.trade_count`
- `summary.warnings`
- `review_traceability.source_refs`
- `review_traceability.items[].kb_source_refs`
- `review_traceability.items[].pa_explanation`
- `review_traceability.items[].risk_notes`
- `review_traceability.items[].news_source_refs`
- `review_traceability.items[].trade_outcome`
