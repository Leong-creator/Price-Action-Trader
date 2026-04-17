# 可靠性验证总纲

## 1. 阶段定位

`M8` 定义为 `Reliability Validation`。

本阶段不是功能扩展阶段，不是 broker 延续阶段，也不是收益最大化阶段。  
本阶段只验证 M0-M7 既有交付物是否可靠、可复现、可追溯、可保守运行。

## 2. 固定边界

- 默认运行边界仍为 `paper / simulated`
- 不接真实资金
- 不启用实盘自动下单
- 不重开真实 broker、真实账户、live execution
- 不把付费 API 前置化
- 不把浏览器自动化写成生产执行链路
- `M8` 完成前，不重新评估 broker / live

## 3. 目标

`M8` 需要证明：

1. 系统严格受知识库约束，引用可追溯，资料不足时保持保守
2. 同一输入下研究链可复现、deterministic、无 future leakage
3. paper / simulated 执行链安全，风控阻断稳定生效
4. 在真实历史数据与实时只读输入下，系统仍然只输出 shadow / paper 结果，不误入真实 broker / live

## 4. 子阶段主线

### M8A：测试基线、文档与门禁落盘

- 目标：冻结 `active-plan / acceptance / status / roadmap / decisions`
- 交付物：门禁文档、评分文档、阶段 runbook 总纲
- 本阶段不创建测试实现代码、脚本、目录骨架

### M8B：知识库对齐测试

- 目标：验证输出是否真正遵守知识库，而不是“看起来像遵守”
- 核心门禁：真实 `source_refs`、适用性约束、冲突显式化、资料不足时保守 `no-trade / wait`

### M8C：离线端到端可靠性测试

- 目标：验证现有最小闭环的 determinism 与安全红线
- 核心门禁：无 future leakage、同输入 deterministic、risk-before-fill、audit / review traceability、forbidden paths

### M8D：真实历史数据稳健性 + 实时 shadow / paper 验证框架

- 目标：在真实输入下验证系统仍然保守、稳定、可解释
- 核心门禁：真实输入只进入 shadow / paper，不进入真实 broker / live

## 5. 输入边界

按当前数据源策略，M8 可接受的输入顺序为：

1. P0：静态测试样本
2. P1：用户导出的真实历史 CSV/JSON
3. P2：免费公共数据源的本地快照
4. 实时只读输入：shadow / paper 观察路径

明确不进入：

- P4 正式 broker / live execution
- 真实账户联通
- 付费 API 前置化

## 6. 报告产物要求

M8 各子阶段都应要求输出：

- 当前阶段结论
- 硬门禁是否全部通过
- 失败样本类型
- 人工抽检重点
- 是否仍保持 `paper / simulated`

## 7. 完成定义

- `M8` 的通过标准首先是行为可靠性，而不是收益指标。
- 任一硬门禁失败，都不得宣称 M8 通过。
- 在 `M8` 完成前，任何 broker / live 的重新评估都不进入执行主线。
