# Golden Cases

`tests/golden_cases/` 用于放置 M8B 的知识库对齐 golden cases。

当前目录已落盘实际 golden cases，并由 reliability 回归直接消费，不再只是 `M8A` skeleton。

约束：

- 仅使用本地静态样本或用户导出的离线文件。
- 不依赖外部网络。
- 不接真实 broker、真实账户或 live execution。
- 保持 `paper / simulated` 边界。

当前用途：

- `cases/`：知识对齐、缺失 refs、`not_applicable`、conflict、insufficient evidence 等代表性样本
- reliability 测试基于这些 case 验证 “不伪造知识引用、不越过适用性边界、资料不足时允许 no-trade / wait”
