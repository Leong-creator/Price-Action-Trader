# 架构边界

## 1. 当前阶段定位

当前处于轻资产验证阶段，基础设施优先，正式券商 API、自动下单、真实资金账户都不作为前置条件。

## 2. 分层原则

- `knowledge/`：原始资料、wiki 知识页与 schema。
- `src/data/`：数据导入、清洗、schema、回放。
- `src/strategy/`：PA context、bar-by-bar、setup、信号生成。
- `src/backtest/`：历史回测与结果统计。
- `src/review/`：复盘与报告整理。
- `src/risk/`：风控、熔断、暂停与恢复条件。
- `src/execution/`：模拟执行与后续 adapter 抽象。
- `src/broker/`：broker adapters 与浏览器只读验证路径。
- `src/news/`：新闻、事件、财报等辅助过滤信息。
- `src/shared/`：跨模块共享结构。

## 3. 数据源优先级

1. P0：静态 CSV/JSON 历史数据回放。
2. P1：用户手动导出的 CSV/JSON。
3. P2：无需复杂认证的免费公共行情源或交易所公开接口。
4. P3：浏览器 DOM / 截图 / 图表识别。
5. P4：正式券商 API。

## 4. Adapter 边界

所有数据源和后续执行能力都必须通过 adapter 接入。策略、风控、回测不得直接依赖某个浏览器页面、某个 API SDK 或某个导出格式。

## 5. 高风险边界

以下内容属于高风险边界，必须走独立分支、独立测试、独立复核：

- 真实下单
- 账户连接
- 实盘开关
- 风控阈值
- 仓位与杠杆
- 止损止盈
- 凭证与密钥
