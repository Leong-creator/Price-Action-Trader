# Integration Tests

`tests/integration/` 用于放置 M8C 的离线端到端可靠性测试。

当前目录已包含实际离线端到端测试，不再只是 `M8A` skeleton。

约束：

- 只允许离线运行。
- 输入必须可复现、可回放。
- 不接入外部网络。
- 不得出现真实 broker、真实账户或 live execution 路径。

当前代表性测试：

- `test_offline_e2e_pipeline.py`：覆盖 `src/data -> src/strategy -> src/backtest -> src/risk -> src/execution -> src/news -> src/review` 的离线闭环
