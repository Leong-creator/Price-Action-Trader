# 测试数据集整理规范

## 1. 目标

本文件定义 M8 可靠性验证阶段允许使用的数据集类型、整理要求与门禁。

本文件只覆盖测试数据整理与使用边界，不定义测试实现细节。

## 2. 允许的数据来源

按当前项目边界，M8 允许以下输入顺序：

1. `tests/test_data/` 中的静态样本
2. 用户手动导出的本地历史 CSV/JSON
3. 免费公共数据源的本地快照
4. 实时只读输入的本地缓存或快照

当前不允许：

- 真实 broker 数据直连
- 真实账户联通
- live execution 输入链
- 付费 API 作为前置条件

## 3. 数据集分层

### 3.1 Golden Cases

用于 M8B 的知识库对齐测试。

要求：

- 输入可复现
- 期望输出可人工审查
- `source_refs` 可核对
- 允许 `no-trade / wait`

### 3.2 Integration Cases

用于 M8C 的离线端到端可靠性测试。

要求：

- 覆盖 deterministic 重放
- 覆盖 future leakage 防线
- 覆盖 risk-before-fill
- 覆盖审计与复盘链完整性

### 3.3 Reliability Cases

用于 M8D 的真实历史数据稳健性与 shadow / paper 框架验证。

要求：

- 只使用本地真实历史 CSV/JSON 或只读快照
- 保持 `paper / simulated`
- 不进入 broker / live

## 4. 最小元数据要求

每份后续新增测试数据都应至少记录：

- `dataset_name`
- `source_type`
- `market`
- `symbol`
- `timeframe`
- `time_range`
- `timezone`
- `origin`
- `limitations`
- `approved_for`

## 5. 样本整理原则

- 原始资料仍放在 `knowledge/raw/`，不得为测试方便而改写。
- 测试样本应复制或导出到测试目录，保持与 raw 解耦。
- 缺样本时允许先保留目录与说明，不伪造真实数据。
- 样本不足时，测试结论必须明确为样本不足，而不是伪造通过。

## 6. 审查门禁

任何新引入测试数据，至少检查：

- 是否来自允许的数据源层级
- 是否能本地离线运行
- 是否包含最小元数据
- 是否会诱导越界到真实 broker / live
- 是否需要人工脱敏

## 7. 报告要求

M8 相关报告至少注明：

- 使用的数据集名称
- 数据来源层级
- 是否为静态样本、真实历史导出或只读快照
- 已知缺口与局限
- 是否仍保持 `paper / simulated`
