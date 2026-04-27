# 架构边界

## 1. 当前阶段定位

当前处于轻资产验证阶段，基础设施优先，正式券商 API、自动下单、真实资金账户都不作为前置条件。

## 2. 分层原则

- `knowledge/`：原始资料、wiki 知识页与 schema。
- `knowledge/wiki/strategy_cards/`：面向策略提炼与测试计划的知识页层，继续受 wiki frontmatter 与 `source_refs` 约束。
- `src/data/`：数据导入、清洗、schema、回放。
- `src/strategy/`：PA context、bar-by-bar、setup、信号生成。
- `src/backtest/`：历史回测与结果统计。
- `src/review/`：复盘与报告整理。
- `src/risk/`：风控、熔断、暂停与恢复条件。
- `src/execution/`：模拟执行与后续 adapter 抽象。
- `src/broker/`：broker adapters 与浏览器只读验证路径。
- `src/news/`：新闻、事件、财报等辅助过滤信息。
- `src/shared/`：跨模块共享结构。
- `reports/strategy_lab/`：策略提炼支线的快照、来源盘点、提炼日志、测试计划、comparison 与用户摘要；当前 M10 产物位于 `reports/strategy_lab/m10_price_action_strategy_refresh/`。

## 3. 数据源优先级

1. P0：静态 CSV/JSON 历史数据回放。
2. P1：用户手动导出的 CSV/JSON。
3. P2：无需复杂认证的免费公共行情源或交易所公开接口。
4. P3：浏览器 DOM / 截图 / 图表识别。
5. P4：正式券商 API。

## 4. Adapter 边界

所有数据源和后续执行能力都必须通过 adapter 接入。策略、风控、回测不得直接依赖某个浏览器页面、某个 API SDK 或某个导出格式。

## 5. M10 Strategy Refresh 边界

- M10 clean-room catalog 使用 `M10-PA-*` namespace，不复用旧 `PA-SC-*` 或 `SF-*` 作为提炼先验。
- Brooks v2 manual transcript、方方土 YouTube transcript、方方土 notes 是 M10 策略证据来源；ChatGPT share 与 Codex thread 只作为 reference-only comparison。
- M10 catalog、source ledger、visual gap ledger、visual golden case pack 和 backtest eligibility 不直接等于 executable strategy rule。
- M10.3 backtest specs 只冻结 Wave A historical pilot 的事件识别、entry/stop/target、skip 规则、成本敏感性和样本门槛；它们不代表已回测结论、盈利结论、promoted strategy 或 live execution 能力。
- M10.5 read-only observation plan 只定义观察候选、事件 schema、质量复核和 paper gate handoff；它不启动实时观察 runner，不接真实 broker，不写入真实订单路径。
- M10.6 read-only observation replay 只用本地 cached OHLCV 生成 recorded replay ledger；它不是实时行情订阅，不生成执行、仓位、现金或盈亏结论，也不进入 `src/risk/`、`src/execution/`、`src/broker/` 的 live 行为。
- M10.8 Wave A capital backtest 只把 M10.4 candidate events 按 M10.7 capital model 转成 historical simulation 成绩单；它可以输出模拟本金、权益、净利润、胜率、回撤和交易明细，但不代表策略升级、paper trading 批准、broker 接入或真实订单能力。
- M10.2 visual pack 只记录 Brooks v2 evidence image logical path 与 checksum；图片资产继续 local-only，不进入普通 Git 跟踪。
- 本层仍属于 `paper / simulated` 研究能力，不进入 `src/risk/`、`src/execution/`、`src/broker/`。

## 6. 高风险边界

以下内容属于高风险边界，必须走独立分支、独立测试、独立复核：

- 真实下单
- 账户连接
- 实盘开关
- 风控阈值
- 仓位与杠杆
- 止损止盈
- 凭证与密钥
