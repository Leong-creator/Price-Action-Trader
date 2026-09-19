# 行情替代源核对与单源迁移条件

核对日期：2026-09-19。依据为供应商官方文档、产品说明和定价；公开能力尚未经过本项目真实连接验证。

用户已允许在长桥官方接入方法仍无法解决时更换行情来源，并要求优先免费。此次授权不包含开户、入金、购买订阅或恢复订单。当前应解决行情访问与接入问题，不据此重写策略。

## 保持原要求，不新增全市场门槛

保持147只股票、实时Quote/Trade输入、60根日线上下文、五分钟聚合及完整日78个边界的验收要求。原计划没有要求SIP全市场数据，不能擅自增加这一门槛。

长桥官方快速开始将免费美股行情列为Nasdaq Basic（仅OpenAPI）；Nasdaq说明Basic报价来自Nasdaq市场，成交来自Nasdaq及FINRA/Nasdaq TRF。覆盖所有美股上市标的，不等于覆盖所有成交场所。当前账户的完整套餐权益尚未确认，不把产品说明当作账户实测结果。IEX与现长桥输入的场所覆盖、成交量和价格差异需要核对，不能预设二者等价，也不能仅凭不是SIP便排除。

## 已核实的选择

下表各来源获取日期均为2026-09-19；价格和权益以正式开通时的供应商说明为准。

| 来源 | 官方能力与限制 | 对当前147只要求的结论 | 官方来源 |
| --- | --- | --- | --- |
| 长桥免费美股 | 文档列Nasdaq Basic；现有官方接入仍有订阅超时，根因未确定 | 本阶段官方地域及当前版本对照已失败并停止；不能把换源当作证明旧故障原因 | [长桥快速开始](https://open.longbridge.cn/zh-CN/docs/getting-started)、[Nasdaq Basic](https://www.nasdaq.com/products/data/equities/nasdaq-basic) |
| Alpaca Basic | 免费实时IEX，WebSocket订阅上限30只 | 数量不满足147，不能通过轮换订阅冒充整场覆盖；覆盖和成交量语义另需比较 | [官方套餐](https://docs.alpaca.markets/us/docs/about-market-data-api)、[数据差异](https://docs.alpaca.markets/us/docs/market-data-faq) |
| Alpaca Algo Trader Plus | 当前标价99美元/月，实时全美交易所数据、订阅数量不限 | 能力上可作为候选；尚无本项目数据权益验证，未授权购买 | [官方套餐](https://docs.alpaca.markets/us/docs/about-market-data-api) |
| Tradier Lite | 0美元/月且含API；正式券商账户可取实时汇总行情；官方称市场流支持数百标的，限一条市场流；sandbox延迟15分钟 | 优先核对的低成本条件候选，不能称免开户即用。需正式账户、开户资格及Production Token；每年少于2笔交易有50美元不活跃费，未入金超过60天在线体验受限。不得为行情擅自交易或入金 | [定价与费用](https://tradier.com/pricing)、[行情权益](https://docs.tradier.com/docs/market-data)、[流限制](https://docs.tradier.com/docs/streaming-data) |
| TradingView | 官方没有供用户向外取行情/指标的数据API；条款限制算法决策等非展示数据使用 | 不作为正式替代源，不采用网页抓取或逆向接口 | [API说明](https://www.tradingview.com/support/solutions/43000474413-i-need-access-to-your-api-in-order-to-get-data-or-indicator-values/)、[条款](https://www.tradingview.com/policies/) |
| Yahoo / yfinance | yfinance是非Yahoo官方研究工具，已有WebSocket能力；Yahoo不同市场有不同延迟 | 可供适当的个人研究；没有证据证明满足147只实时逐笔完整性和当前成交处理要求，不能直接替换 | [yfinance说明](https://github.com/ranaroussi/yfinance/blob/main/README.md?plain=1)、[Yahoo数据说明](https://help.yahoo.com/kb/SLN2310.html) |
| Twelve Data Basic | 8 API credits/min、800/day，8个试用WebSocket credits且限指定试用标的；WebSocket不提供OHLC或bid/ask | 免费方案不满足当前数量与输入要求 | [试用限制](https://support.twelvedata.com/en/articles/5335783-trial)、[WebSocket FAQ](https://support.twelvedata.com/en/articles/5194610-websocket-faq) |
| Massive / Alpha Vantage免费方案 | Massive免费为日终数据、5次调用/分钟；Alpha Vantage普通免费25次/日，实时及15分钟延迟美股属付费权益 | 可用于有限历史研究，不能直接恢复当前实时链路 | [Massive定价](https://massive.com/pricing)、[Alpha Vantage说明](https://www.alphavantage.co/support/) |

本轮仅在已检查的`config/`、`scripts/`、`src/`、`docs/`、环境变量名称及已知配置文件名称范围内，未找到替代源凭证设置。这不是对整台机器的穷尽搜索，也不证明用户没有其他供应商账户。未读取或公开替代源凭证值，未创建账户或连接新源。

## 确定替代源后的执行顺序

1. **确认访问资格。** 优先核实现有Tradier正式账户及实时权益是否可用；否则再确定其他供应商。开户、凭证配置和付费是独立前提，不能从“允许换源”推导为已授权。无需在对话中公开凭证。
2. **只实现所选一个源的输入映射。** 核对标的名称、报价字段、逐笔条件码、撤销与更正、重复及乱序、成交量范围、时区、交易时段、日线复权和缺失值。不得机械套用长桥条件码。Tradier的`trade`与`timesale`语义不同，需按逐笔聚合所需信息选择并验证；历史日线可能未按股息复权，不能忽略差异。[流字段](https://docs.tradier.com/docs/streaming)、[历史说明](https://docs.tradier.com/docs/historical-data)
3. **独立验证147只。** 按该供应商官方接口、实际权益及官方限额接收原股票池，保存订阅结果、数据时间、错误及实际覆盖。数量或权限不足则停止，不缩池、不轮换伪造连续覆盖。
4. **接回原处理链路。** 验证数据收到、进入处理、形成K线、策略完成判断；策略、股票池和风险参数保持不变。只有证据证明某一映射必须改变，才记录差异并单独验证。
5. **真实整场验收。** 正常交易日147只、78边界、11,466条分类明确的K线记录；盘后补录不算实时通过，无成交延续K线不触发开仓。一个完整日提供恢复资格依据，连续三个完整日才称稳定；不自动恢复交易、不补旧信号。

迁移采用明确的一次单源切换，不建设长桥与新源的自动回退或并行拼接。新源尚未验证前，不把旧故障解锁，也不把候选供应商能力写成项目已恢复。

## 当前结论

免费公开方案尚没有已核实、可立即接入并满足147只原要求的选项；Tradier是有正式账户与费用条件的低成本候选，Alpaca Plus是需付费授权的候选。现阶段换源前缺少的是**已确认可用的数据访问资格及对应输入验证**，不是需要增加策略框架。本阶段长桥官方地域和当前发布版对照已失败并停止，详见[实测结果](20260919-official-route-result.md)；确认访问资格后按上述顺序更换唯一行情来源。
