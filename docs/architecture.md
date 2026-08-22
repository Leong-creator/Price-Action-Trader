# 架构边界

## 2026-08-21 M15行情临时生产覆盖（当前权威）

- 147只原生推送在官方未修改版和项目版 `longbridge 4.5.0` 上均出现订阅后停止前进时，纸面账户合同允许显式使用 `sdk_snapshot_poll`。当前每3秒由可回收子进程创建一个全新SDK行情上下文并执行一次全量报价请求；不使用CLI、本地模拟或历史账本。
- 单轮报价超过2.5秒即撤销该轮行情的开仓资格；工作进程连续5秒无进展才终止并重建。正常轮询间隔必须持续报告进度，交易性能门槛与进程存活门槛不得混用。任一轮覆盖不完整、超时或账户快照过期都停止新开仓。快照最后成交时间只做审计，完整五分钟批次按边界后形成耗时判断是否及时；同一交易日已退出标的的可信报价行继续保留给账户盈亏对账。
- 快照只按接收时刻构造秒级采样K线。只有同一五分钟边界147只交易标的全部到齐且在边界后5秒内形成，才可进入纸面账户新开仓；残缺或迟到批次只允许已有持仓退出。该证据不得称为逐笔成交等价K线、原生推送稳定日或300只扩展验收。
- 正常网络路径完整继承用户代理。项目只能清除自身遗留的DNS覆盖和长桥代理绕过项，不得修改Windows/WSL代理、系统DNS或hosts。运行状态使用原子文件替换。
- 本节覆盖下方2026-08-20“快照只能诊断”的旧生产结论，直至147只原生推送稳定性问题另行解决；策略合同、仓位、止损、目标和质量门槛保持不变。

## 2026-08-20 M15行情上下文生命周期（权威）

- M15生产行情固定使用补丁版 `longbridge 4.5.0` 和一个长生命周期 `QuoteContext`。同一连接先准备147只标的的SDK K线状态，再一次订阅 `Quote + Trade` 并核验覆盖；生产配置只允许一个行情连接。
- 美股五分钟K线由SDK内部按逐笔成交聚合真实OHLCV，Python只接收确认完成的K线。`Quote`只服务最新状态和SDK协议，不在Python侧采样拼K线。SDK回调禁止执行文件I/O、账户查询或策略计算。
- 快照轮询仅保留为显式诊断工具，生产交易配置禁止自动回退。推送不完整、连接静默、订阅失败或工作进程异常时必须停止新开仓并重建唯一连接，不得用轮询采样K线继续交易或冒充实时完整会话。
- SDK版本不得低于 `longbridge 4.5.0`。该版本修复上下文销毁后的后台重连任务并共享进程级HTTP连接池；旧版和短生命周期行情上下文组合会积累连接、线程和内存，不得恢复。
- 正常网络路径是否可用必须在原样保留用户代理和代理绕过配置时通过真实SDK行情请求判断。固定地址只作为当前M15进程的回退环境，不能修改用户代理、系统DNS或hosts；未启用回退时不得擅自把长桥域名加入 `NO_PROXY`。
- M15历史日线和盘后五分钟补录分别使用单标的一次性SDK上下文，严格串行且互不重叠；本地研究批处理独立运行且不能改变M15状态。历史数据不具备实时下单资格。
- 日线加载状态和实时订阅状态使用独立超时域：只有实时行情工作进程存在时才适用订阅启动期限，防止日线串行加载被错误判成行情进程死亡。

## M15 正式测试证据边界

- M15 盘中交易系统只使用冻结147只生产池、当前合同哈希和长桥模拟账户事实；本地模拟、M12/M13/M14结果和300只扩展池不得进入订单热路径。
- M15 行情只允许一个持久 SDK 推送工作进程。只有 `sdk_subscription`、交易池订阅完整、日线上下文完整且账户快照新鲜时才具备订单资格；任何 `sdk_snapshot_poll` 状态都必须停止新开仓。慢统计、看板、验收和本地研究不得建立额外盘中行情连接；禁止回退 CLI，也不能把历史补录或快照采样计作实时推送证据。
- 盘后证据系统分开生成行情会话、策略运行、券商执行和盈利样本四层状态。四层互不替代，且证据系统只能报告，不能改变策略权限。
- 视觉策略历史回放使用冻结300只数据，实时影子使用147只生产行情。人工图形复核通过候选指纹绑定，规则变化后必须重新复核；视觉草案永远不能因机器回放自动进入订单通道。

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
- M10.9 definition tightening 只对 `M10-PA-005` 做结构性去重与触发密度复测；它不得按收益调参，也不能在缺少 range geometry 字段时解除 `needs_definition_fix`。
- M10.10 visual Wave B gate 只判断强图形策略是否具备进入后续模拟规格/回测的条件；它不运行回测、不证明策略有效，也不把 visual pack ready 解释为自动可交易。
- M10.11 Wave B capital backtest 只对 M10.10 queue 中的策略做 OHLCV 近似 historical simulation；视觉策略结果必须保留 proxy/review 边界，不得解释为策略批准或 paper trading 准入。
- M10.12 all-strategy scorecard 只汇总既有 Wave A/Wave B 资金测试、definition-fix、supporting 和 research-only 状态；portfolio proxy 不是按真实时间戳合并订单的可执行组合回测，也不进入 broker、risk 或 execution。
- M10.13 read-only observation runbook 只定义未来观察队列、周报模板、暂停条件和人工复核节奏；它不启动 observation runner，不接实时行情，不接 broker，不下单，也不批准 paper trading。
- M11 paper gate 只把 M10.12/M10.13 的结果整理成候选分级、准入阻塞项和风险暂停规则；当前 gate decision 固定为 `not_approved`，`M10-PA-001/002/012` 只是 Tier A 核心观察候选，`M10-PA-008/009` 只是 Tier B 视觉条件候选，二者都不是 paper trading approval evidence。
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
