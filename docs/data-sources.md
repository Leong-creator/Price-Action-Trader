# 数据源策略

<!-- strategy_factory_provider_contract={"active_provider_config_path":"config/strategy_factory/active_provider_config.json","primary_provider_runtime_source":"source_order[0]"} -->

## 1. 总原则

当前阶段优先轻资产验证，不把付费 API、真实账户、实盘能力作为前置条件。

## 2. 数据源优先级

1. P0：静态 CSV/JSON 历史数据回放。
2. P1：用户手动导出的 CSV/JSON。
3. P2：无需复杂认证的免费公共数据源。
4. P3：浏览器 DOM/截图/图表识别临时验证。
5. P4：正式券商 API。

补充说明：

- `P4` 只允许在用户明确批准、且仍保持 `paper / simulated` 边界时接入。
- 当前仓库允许的券商 API 数据用途仅限“只读历史行情下载 -> 本地 CSV 缓存 -> Codex 内回测”。
- 即使使用券商 API，也不得在当前阶段接入真实下单、持仓管理、资产查询或自动化交易路径。
- 当前 Strategy Factory 的 `primary_provider` 只允许由 `config/strategy_factory/active_provider_config.json`
  的 `source_order[0]` 推导。
- 计划、状态和验收文档只描述这个 contract，不把具体 provider 写成长期固定口径。
- 其他 provider 仍可作为显式指定时的兼容或历史对照路径，但不属于 contract 自身。

## 3. 浏览器方案边界

浏览器方案只允许用于：

- 只读观察。
- 截图辅助分析。
- 页面导出文件。
- 临时验证数据可用性。

禁止用于：

- 真实下单。
- 长期生产数据源。
- 绕过 API 权限。
- 绕过风控。

## 4. Adapter 原则

所有数据源必须通过 adapter 进入系统。策略、风控、回测不得直接依赖某个浏览器页面、某个 API SDK 或某个导出格式。

当前已落盘的 provider-specific adapter 与历史 run 仍保留为仓库历史事实，但不构成
Strategy Factory 的长期默认 provider 口径。
