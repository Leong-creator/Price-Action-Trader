# Price Action Trader 需求文档

## 1. 项目目标

本项目目标是构建一个以 Price Action 知识库为核心的交易研究与自动化辅助系统，优先服务美股和港股。

系统最终希望具备：

1. 从 Brooks、方方土视频转录文档、用户笔记等资料中整理 PA 知识库。
2. 基于 OHLCV 数据识别市场 context、bar-by-bar 变化、setup、信号 K、入场触发、止损与目标。
3. 输出可解释的交易建议和选股结果。
4. 支持历史回测、模拟验证、复盘报告。
5. 在长期验证稳定后，再接入正式券商 API 和自动下单。

## 2. 当前阶段

当前处于轻资产验证阶段。

当前要做：

- 仓库规范与 agent 工作机制。
- 知识库结构与资料投放目录。
- PA 知识整理 schema。
- 静态测试数据与数据 schema。
- 策略信号原型。
- 回测与模拟验证基础。

当前不做：

- 不接入真实资金账户。
- 不启用实盘自动下单。
- 不把付费券商 API 作为前置条件。
- 不把浏览器自动化作为生产级执行链路。
- 不做未经验证的激进交易策略。

## 3. 用户角色与 agent 角色

用户是甲方，负责提出目标、提供资料、做关键业务审批和最终验收。

主 agent 负责：

- 维护 active plan。
- 拆解 milestone。
- 创建和管理 subagent。
- 推进开发、测试、文档同步。
- 汇总审核结果。
- 只在必要决策点请求用户介入。

## 4. 核心功能需求

### 4.1 知识库 ingestion

系统必须允许用户把资料直接放入对应目录：

- Brooks PPT 或导出 PDF：`knowledge/raw/brooks/ppt/`
- Brooks 提取文字：`knowledge/raw/brooks/extracted_text/`
- 方方土视频转录文档：`knowledge/raw/youtube/fangfangtu/transcripts/`
- 方方土视频 metadata：`knowledge/raw/youtube/fangfangtu/metadata/`
- 视频图表截图、补充标注：`knowledge/raw/youtube/fangfangtu/supplements/`
- 用户笔记：`knowledge/raw/notes/`

要求：

- raw 层不可改写。
- wiki 层负责整理。
- 缺图不阻塞入库，但必须标记 `missing_visuals`。
- 每条规则必须保留 source_refs。

### 4.2 PA 知识结构化

系统必须支持以下 wiki 页面类型：

- concepts
- setups
- rules
- indicators
- market-regimes
- risk
- sources
- glossary
- case-studies

setup 页面必须尽量记录：

- pa_context
- market_cycle
- higher_timeframe_context
- bar_by_bar_notes
- signal_bar
- entry_trigger
- entry_bar
- stop_rule
- target_rule
- trade_management
- measured_move
- invalidation
- risk_reward_min

### 4.3 数据导入与回放

系统必须优先支持：

- 本地静态 OHLCV CSV。
- 本地 JSON 新闻样本。
- 用户导出的行情数据。

OHLCV 最小字段：

- symbol
- market
- timeframe
- timestamp
- timezone
- open
- high
- low
- close
- volume

系统必须校验：

- timestamp 可解析。
- high >= open/close/low。
- low <= open/close/high。
- price/volume 非法值。
- 同一 symbol/timeframe/timestamp 重复。

### 4.4 PA 信号生成

系统必须输出结构化交易信号，而不是简单字符串。

最小字段：

- signal_id
- symbol
- market
- timeframe
- direction
- setup_type
- pa_context
- entry_trigger
- stop_rule
- target_rule
- invalidation
- confidence
- source_refs
- explanation
- risk_notes

早期信号只能作为研究建议或回测输入，不得直接实盘执行。

### 4.5 技术指标辅助

技术指标只能作为辅助，不得替代 PA context。

早期可支持：

- EMA / MA
- ATR
- volume average
- RSI / MACD 作为可选辅助

每个指标必须有公式说明、参数配置和测试。

### 4.6 新闻与事件过滤

新闻模块早期只用于：

- 标记重大事件。
- 解释波动。
- 对交易建议做过滤或风险提示。

禁止早期把新闻情绪直接转为实盘订单。

### 4.7 选股/筛选

系统应支持基于以下条件筛选候选标的：

- 市场：US / HK
- 流动性
- 波动率
- 当前 market regime
- 是否接近 PA setup
- 是否有重大新闻/财报风险

早期选股结果必须包含解释和风险提示。

### 4.8 回测

回测必须支持：

- 使用静态 OHLCV 数据。
- 使用策略信号。
- 计算交易记录。
- 统计胜率、盈亏比、期望值、最大回撤、交易频率、滑点敏感性。

回测结果不得伪造。若数据不足，必须明确标注。

### 4.9 模拟盘/纸面交易

模拟盘阶段必须验证：

- 信号生成。
- 风控拦截。
- 建议订单创建。
- 模拟成交。
- 持仓状态。
- 日志与复盘。

模拟盘通过前禁止实盘。

### 4.10 风控

风控必须至少支持：

- 单笔最大风险。
- 总仓位限制。
- 标的集中度。
- 日内最大亏损。
- 连续亏损暂停。

### 4.11 Strategy Lab

系统必须支持把原始知识来源整理成独立的 Markdown strategy cards 和 test plans，而不是每次运行前临时检索大文件。

最小要求：

- 策略卡必须保留真实 `source_refs`，并显式区分 transcript、Brooks PPT、用户 notes 的证据优先级。
- 每张策略卡都必须包含可测试的入场、止损、出场、失效条件与禁止交易条件；证据不足时必须明确写出。
- 系统必须支持记录策略当前结论：`draft / candidate / tested / promoted / rejected`。
- 系统必须支持为策略写独立测试计划，包括标的、周期、历史窗口、成本/滑点、样本切分、最低交易数、通过/淘汰标准。
- strategy lab 产物只服务 research / backtest / paper / simulated，不代表 broker/live/real-money 能力。
- 止损规则。
- 熔断与紧急停止。

风控失败必须阻断执行。

### 4.11 执行适配器

早期只做抽象，不接真实账户。

后续执行层应通过 adapter 抽象：

- PaperBrokerAdapter
- BrowserReadOnlyAdapter
- FormalBrokerAdapter

正式 Broker API 只能在回测、模拟验证稳定后接入。

### 4.12 复盘报告

系统必须支持生成复盘信息：

- 信号来源。
- 知识库规则引用。
- 价格行为解释。
- 新闻/事件影响。
- 入场、止损、目标。
- 结果统计。
- 错误原因。
- 待改进项。

## 5. 阶段路线

1. 阶段 0：仓库、规则、知识库结构、测试数据初始化。
2. 阶段 1：知识库 ingestion、schema、wiki index、KB 校验。
3. 阶段 2：数据 schema、CSV 回放、PA 信号原型。
4. 阶段 3：回测与报告。
5. 阶段 4：模拟盘/纸面交易与风控闭环。
6. 阶段 5：正式 API 接入评估。
7. 阶段 6：小规模实盘灰度，仅人工批准后进入。

## 6. 非功能要求

- 可追溯。
- 可回退。
- 可验证。
- 可解释。
- 可维护。
- 高风险变更需人工复核。
