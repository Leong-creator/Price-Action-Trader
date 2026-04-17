# Integration Tests

`tests/integration/` 用于放置 M8C 的离线端到端可靠性测试。

当前阶段仅完成 M8A 测试骨架，不落真实测试实现。

约束：

- 只允许离线运行。
- 输入必须可复现、可回放。
- 不接入外部网络。
- 不得出现真实 broker、真实账户或 live execution 路径。

后续建议内容：

- `test_offline_e2e_*.py`：离线闭环测试
- `fixtures/`：端到端回放样本
- `snapshots/`：审计与复盘基线
