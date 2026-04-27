# Video 3C: Pip Value, Forex Workspaces, and Futures vs Forex

来源范围：`part1 p204-p231`。本章对应 Al Brooks “Price Action Fundamentals” 课程的 `Video 3C (#3 of 5)`，主题是 pip 价值、外汇工作区、以及期货和外汇的比较。正文依据渲染后的幻灯片逐页视觉校对后重写，保留 pip 价值计算、bid/ask 报价、spread、经纪商利润、Forex 与 EC futures 成本对比、较冷门货币对大点差等全部数字和条件；标题页、目录页、平台截图页、回顾页和结束页不进入正文图像。

## 本单元范围：pip 价值、外汇工作区、期货还是外汇

`source: part1 p204-p205, p211, p222, p230-p231`

本视频有三个主题：pip 的价值，`Value of a pip`；外汇工作区，`Forex workspaces`；期货还是外汇，`Futures or Forex?`。本章把前一节的 pip 定义进一步量化，说明不同货币对中 1 pip 对账户货币的价值如何计算，并把外汇现货与欧元期货在保证金、点差、佣金和交易成本上进行比较。

## 10,000 单位约每 pip 1 美元，100,000 单位约每 pip 10 美元

`source: part1 p206`

对于 10,000 单位交易，1 pip 大约等于 1 美元，`For a 10,000 unit trade 1 pip = about $1`。课程提到有许多免费的在线 pip 计算器，`many free online Pip calculators`。标准交易规模是 100,000 单位，`Standard size trade = 100,000 units`，此时 1 pip 大约等于 10 美元，`1 pip is about $10`。

![pip 价值和在线 pip 计算器](../assets/evidence/video_003C/part1_p0206.webp)

这条近似规则适用于大多数以美元计价、标准规模的直观估算，但具体货币对和报价货币会改变实际美元价值。

## EURUSD 的 pip 价值：100,000 单位时 1 pip = 10 美元

`source: part1 p207`

在 EURUSD 中，1 pip 报价为 0.0001 美元，`1 pip in EURUSD is quoted as 0.0001 US dollars`。如果交易 100,000 单位，一 pip 等于 10 美元，`one pip = $10 US dollars`，计算为 100,000 × 0.0001 = $10。EURUSD 的盈亏以美元表示，`Profit or loss is in dollars`。

![EURUSD 中 100,000 单位的 1 pip = 10 美元](../assets/evidence/video_003C/part1_p0207.webp)

## USDJPY 的 pip 价值：先以日元计，再换算成美元

`source: part1 p208-p210`

在 USDJPY 中，1 pip 报价为 0.01 日元，`1 pip in USDJPY is quoted as .01 Japanese yen`。如果交易 100,000 单位，一 pip 等于 1,000 日元，`one pip = 1,000 Japanese yen`，计算为 100,000 × 0.01 = 1,000 yen。

已实现盈亏以日元计，`Realized profit or loss is in yen`，并在交易时段结束后自动换算成美元，`Automatically converted to US dollars at end of session`。如果 USDJPY = 104.32，那么 1,000 日元 = 9.59 美元 = 1 pip。

更完整的计算是：若 USDJPY = 104.32，那么每美元 104.32 日元，`104.32 yen per dollar`。2 是 pip digit，所以每美元有 10,432 pips，`2 is the pip digit, so 10,432 pips per dollar`。1 pip = 1 / 10,432 美元 = 0.0000959 美元每单位，`0.0000959 dollars per unit`。标准交易规模 100,000 单位时，1 pip = 100,000 × 0.0000959 = 9.59 美元。因此，交易 100,000 单位时，1 pip 大约等于 10 美元。

![USDJPY 标准交易中 1 pip 约为 9.59 美元](../assets/evidence/video_003C/part1_p0210.webp)

## 外汇工作区和价格梯

`source: part1 p212-p214`

源页展示了常见外汇工作区，包括 TradeStation RadarScreen、Forex TradeStation Chart Analysis、EURJPY 5 分钟图、Interactive Brokers 的 FX Trader，以及 Interactive Brokers 的价格梯和 5 分钟图。这些页面主要展示交易软件界面，不提供新的交易规则。它们说明外汇交易者通常会同时看报价、订单输入区域、价格梯和图表。

## 下单需要市场：经纪商创造市场并收取价差

`source: part1 p215`

市场允许交易者在任何时候买入或卖出，`Market: allows you to buy or sell at any time`。但每笔交易都需要有人站在另一边，`Need someone to take opposite side`。经纪商的工作是为你创造市场，`Broker's job to create market for you`。他总是愿意站在另一边，但要以某个价格为条件，`He is always willing to take other side, but at a price`。

这句话解释了为什么看似“无佣金”的外汇交易仍然有成本：经纪商通过 bid/ask spread 让交易者随时可以成交，但 spread 就是交易成本和经纪商利润来源。

## 交易日内用 bid/ask 进出，收盘后用 last 调整

`source: part1 p216`

交易日内，买价和卖价用于进入和退出交易，`Bid and Ask prices are used to enter and exit trades`。交易时段结束后，`Last` 价格用于时段结束后的调整，`After session closes, Last price is used to make adjustments after session ends`。源页示例中 EURUSD 的 Last、Bid、Ask 都在报价表中显示。

## Ask、Bid 和 spread

`source: part1 p217-p220`

`Ask` 是较高价格，是经纪商在你想买入时愿意卖给你的价格，`Ask (higher price) where he is willing to sell if you want to buy`。`Bid` 是较低价格，是经纪商在你想卖出时愿意从你那里买入的价格，`Bid (lower price) where he is willing to buy if you want to sell`。二者差额是 spread，`Difference is the spread`。

![bid、ask 和 spread](../assets/evidence/video_003C/part1_p0217.webp)

在示例报价中，EURUSD Last 为 1.11347，Bid 为 1.11347，Ask 为 1.11361，Bid-Ask 为 0.00014。这个 spread 是 1.4 pips。通常每次买入和每次卖出至少亏 1 pip，`You usually lose at least 1 pip on every buy and every sell`。经纪商保留这些 pips 作为利润，`Broker keeps those pips as broker's profit`。这就是经纪商总是愿意在你想卖时买、在你想买时卖的激励。

经纪商报价表示他愿意以 1.11347 从你那里买入，`Buy from you for 1.11347`，并以 1.11361 卖给你，`Sell to you for 1.11361`。他每笔交易赚 1 pip，通常更多；在这里他赚了 1.4 pips。

100,000 EURUSD 报价例子中，Bid = 1.11347，是你卖出时付出的价格；Ask = 1.11361，是你买入时付出的价格。经纪商利润是 bid/ask spread：1.11361 - 1.11347 = 0.00014 = 1.4 pips = 14 美元，因为 100,000 units × 0.00014 = 14 美元。

![100,000 EURUSD 报价例子：1.4 pips = 14 美元](../assets/evidence/video_003C/part1_p0220.webp)

如果买入后立刻想卖出，就至少亏 1 pip，通常更多，`You will lose at least 1 pip (usually more)`。如果是 100,000 单位 EURUSD，通常至少亏 10 美元，`you usually lose at least $10`。

## Forex 与期货：外汇可以极小仓位，期货显示实际成交

`source: part1 p223-p224`

外汇可以在低于 2,000 美元的账户中交易极小仓位，`With Forex, can trade tiny positions in accounts less than $2,000`。机构交易外汇远多于期货，因为外汇有灵活性、摆脱交易所约束和低成本，`Institutions trade Forex far more than futures, because of flexibility, freedom from exchanges, and low cost`。

期货图表几乎与外汇图表相同，`Chart is almost identical to Forex`，但期货显示实际成交，`Shows actual trades`。期货需要更大账户，因为保证金至少 2,000 美元，`Need bigger account, since margin is at least $2,000`。源页示例中 EC futures 有 37,000 份合约，所以交易活跃，`37,000 contracts, so actively traded`。

![Forex 与 EC futures 图表对比](../assets/evidence/video_003C/part1_p0223.webp)

## 100,000 EURUSD 与 1 份 EC futures 合约的名义价值和成本

`source: part1 p225-p226`

当欧元价格为 1.24 美元时，100,000 单位价值 124,000 美元，`$1.24 per Euro 100,000 units is $124,000`。这与 1 份 EC futures 合约价值 155,000 美元大致相同，`About same as 1 EC futures contract ($155,000)`。

期货 bid/ask spread 通常是 1 tick，欧元期货中 1 tick 等于 12.50 美元，`Futures bid/ask spread usually 1 tick, which is $12.50 for euro futures`。佣金约为 round turn 5 美元，`Commission is about $5 round turn`。1.2400 是 12,400 ticks，12.50 美元每 tick × 12,400 ticks = 155,000 美元，即 1 份期货合约价值。

![Forex 与期货名义价值和成本比较](../assets/evidence/video_003C/part1_p0225.webp)

## 立即进出没有免费交易

`source: part1 p227-p228`

如果立即进入并退出，没有任何东西是免费的，`If Enter and Exit Immediately: Nothing Is Free`。如果交易 100,000 EURUSD Forex，每笔交易最低成本是 bid-ask spread，EURUSD 大约为 1 pip，所以约 10 美元，通常更多。若交易 1 份 Euro futures 合约，每笔交易最低成本是 1 tick 加佣金，等于 15 美元，`1 tick plus commission = $15`。

![立即进出时 Forex 与 futures 的最低成本](../assets/evidence/video_003C/part1_p0227.webp)

这页把无佣金外汇和低成本期货放在同一标准下比较：交易者不能只看“佣金”，必须把点差、tick 和 round turn 佣金一起看。

## 冷门货币对点差可以很大

`source: part1 p229`

交易较少的货币对可能有很大 spread，`Less traded pairs can have big spreads`。GBPNZD 可以有 10 pips 或更多，`GBPNZD can be 10 pips or more`。源图示例 spread 为 11 pips。若交易 100,000 单位，有效“佣金”仍然大约只有每边 7 美元，`effective commission is still only about $7 each way`。这句话的含义是，尽管点差以 pip 计很大，不同货币对每 pip 的美元价值会不同，所以实际美元成本需要换算。

![GBPNZD spread 可达 11 pips](../assets/evidence/video_003C/part1_p0229.webp)

## 本单元的可执行知识点索引

- `source: part1 p206-p207`：10,000 单位交易中 1 pip 约等于 1 美元；标准 100,000 单位交易中 1 pip 约等于 10 美元；EURUSD 中 1 pip = 0.0001 美元，100,000 × 0.0001 = 10 美元。
- `source: part1 p208-p210`：USDJPY 中 1 pip = 0.01 日元；100,000 单位时 1 pip = 1,000 日元；若 USDJPY = 104.32，1,000 日元 = 9.59 美元，100,000 × 0.0000959 = 9.59 美元。
- `source: part1 p215-p221`：市场允许随时买卖，但需要对手方；经纪商创造市场，总愿意站在另一边但要收价格；Ask 是较高买入价，Bid 是较低卖出价，差额是 spread；EURUSD 1.11347/1.11361 spread 为 0.00014 = 1.4 pips = 14 美元。
- `source: part1 p221`：买入后立刻卖出，通常至少亏 1 pip；100,000 EURUSD 通常至少亏 10 美元。
- `source: part1 p223-p224`：Forex 可在低于 2,000 美元账户中交易微小仓位；机构外汇交易多于期货，因为灵活、摆脱交易所约束、成本低；期货显示实际成交，但需要更大保证金。
- `source: part1 p225-p226`：EUR 1.24 时，100,000 units = 124,000 美元，接近 1 份 EC futures 合约 155,000 美元；欧元期货 spread 通常 1 tick = 12.50 美元，round turn 佣金约 5 美元。
- `source: part1 p227-p228`：100,000 EURUSD Forex 立即进出最低成本约 1 pip = 10 美元且常更多；1 份 Euro futures 合约最低成本是 1 tick 加佣金 = 15 美元。
- `source: part1 p229`：冷门货币对 spread 可很大，GBPNZD 可以 10 pips 或更多，示例为 11 pips；100,000 单位时有效“佣金”仍可能约每边 7 美元。
