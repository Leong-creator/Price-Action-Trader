# Golden Cases

`tests/golden_cases/` 用于放置 M8B 的知识库对齐 golden cases。

当前阶段仅完成 M8A 测试骨架，不落真实测试实现。

约束：

- 仅使用本地静态样本或用户导出的离线文件。
- 不依赖外部网络。
- 不接真实 broker、真实账户或 live execution。
- 保持 `paper / simulated` 边界。

后续建议内容：

- `fixtures/`：golden 输入样本
- `expected/`：期望输出快照
- `test_*.py`：基于 unittest 的对齐测试
