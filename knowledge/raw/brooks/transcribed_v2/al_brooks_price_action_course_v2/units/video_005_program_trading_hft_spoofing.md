# Video 5: Program Trading, HFT, Spoofing, and Front Running

来源范围：`part1 p281-p316`。本章对应 Al Brooks “Price Action Fundamentals” 课程的 `Video 5`，主题是程序化交易、高频交易、spoofing、front running 与 HFT。正文依据渲染后的幻灯片逐页视觉校对后重写，保留所有百分比、交易数量、闪崩数据、法律/作弊类型、spoofing 流程、front running 计算和 HFT 盈利示例；标题页、目录页、回顾页和结束页不进入正文图像。

## 本单元范围：程序化交易、高频交易、spoofing、front running

`source: part1 p281-p282, p291, p299, p305, p315-p316`

本视频的四个主题是：什么是程序化交易，`What is program trading?`；高频交易，`High frequency trading`；欺骗性挂单，`Spoofing`；抢跑订单与 HFT，`Front running & HFTs`。课程的核心立场是：程序化交易和 HFT 真实存在，并且创造大量市场成交，但它们的交易也会在图表上留下价格行为；散户不能用它们作为拒绝学习交易的借口。

## 程序化交易：算法基于所有可想象概念，控制所有走势

`source: part1 p283-p284`

程序化交易中的算法基于每一种可以想象的概念，`Algorithms are based on every imaginable concept`。即使在平静的交易区间中，成交量也很大，`Even in quiet Trading Ranges, volume is huge`。无数公司持续买入，`Countless firms are continuing to buy`；无数其他公司也持续卖出，`Countless others are continuing to sell`。

程序化交易控制所有走势，`Program Trading: Controls All Moves`。空头程序努力制造向下突破，`Bearish programs fight to create downside breakout`；多头程序努力制造向上突破，`Bullish programs fight to create upside breakout`。最终一方获胜，另一方回补或退出，市场发生突破，`Eventually one side wins, other side covers, and market breaks out`。

![程序化交易控制所有走势](../assets/evidence/video_005/part1_p0284.webp)

图中向下突破示例写出多头放弃，空头继续卖出，`Bulls give up`、`Bears keep selling`。向上突破示例写出空头放弃，多头继续买入，`Bears give up`、`Bulls keep buying`。这把突破理解为大量程序之间的竞争结果，而不是单一交易者意愿。

## 套利交易占 30%，维持相关市场接近公平价值

`source: part1 p285`

程序化交易中的一个重要部分是套利交易，`Arbitrage Trading`。课程写出 30% 的交易是套利交易，`30% of trading is Arbitrage Trading`。机构在紧密相关的市场中采取相反头寸，利用微小差异赚取小额利润，`Firm takes opposite positions, in closely related markets, to make small profit on tiny discrepancies`。这种活动保持相关市场接近公平价值，`Keeps related markets close to fair value`。HFT 公司监控相关市场之间的差异，并寻找快速小利润，`HFT firms monitor related markets for discrepancies, and look to make quick, small profit`。

![程序化套利交易](../assets/evidence/video_005/part1_p0285.webp)

源图并列 SPY 和 Emini，说明相关市场的价格行为非常接近。套利者通过买便宜、卖昂贵来缩小差异。

## 程序无法隐藏它们正在做什么：交易会创造价格行为

`source: part1 p286`

程序不能隐藏它们正在做什么，`Programs: Cannot Hide What They Are Doing`。它们的交易创造价格行为，每个人都能看到，`Their trades create price action, which everyone can see`。如果交易者能学会读图，就可以搭上它们交易的顺风车，`If you can learn to read charts, you can piggy-back onto their trades`。但必须正确管理，`Must manage correctly`。

![程序交易无法隐藏价格行为](../assets/evidence/video_005/part1_p0286.webp)

源图示例中，市场先反弹，多头在收盘价附近买入，`Rally, so bulls buy closes`。随后多头因后续走势失望，`Bulls disappointed by follow-through`；多头在他们最后买入的收盘价处不断卖出多头仓位，`Bulls keep selling out of longs, at last close that they bought`；多头最终放弃，`Bulls finally give up`；空头看到这一点并卖出，`Bears see this and sell`。这说明程序化交易虽然复杂，但最终仍以 K 线、突破、失败、回补和放弃的形式出现在图表上。

## 你不能移动市场：价格到达你的订单，说明机构也在同价交易

`source: part1 p287-p288`

如果想在某个价格卖出，无论是发起做空，还是退出糟糕多头交易，市场无法到达你的价格，除非一个或更多机构也想在同一价格卖出，`Market cannot get to your price, unless one, or more institutions wants to sell at same price`。源图中，一个多头被套在多头仓位中，和其他被套多头一起最终放弃。他在空头突破中退出，`Bull exited during bear BO`。多头最终决定以盈亏平衡卖出，但价格没有到达他的卖出限价单上方，因为机构想以更低价格卖出，`Did not get above his sell limit order, because institutions wanted to sell lower`。

![你不能移动市场：卖出价格必须有机构同向交易](../assets/evidence/video_005/part1_p0287.webp)

同样，如果想在某个价格买入，无论是发起多头，还是退出糟糕空头交易，市场不能到达你的价格，除非一个或更多机构想在同一价格买入。源图中 5 根 K 线反弹后，多头押注至少还会再涨一点，`5 bar rally`、`Bulls bet on at least a little more up`。多头在前一根 K 线高点放置买入止损单，`Bulls place buy stop order at high of prior bar`。订单被成交，说明机构也想在同一价格买入，`Order got filled, so institutions wanted to buy at same price`。

![你不能移动市场：买入成交说明机构也在买](../assets/evidence/video_005/part1_p0288.webp)

这两页把个人订单的意义限定清楚：个体交易者不能单独推动市场，自己的订单成交只是因为更大机构流动性也在同一价格行动。

## 公司能作弊吗：非法方式存在，但在美国和欧洲很难

`source: part1 p289-p290`

课程问公司能否作弊。回答是：这不是一个需要担心的问题，`Not a problem, don't worry`，在美国和欧洲非常困难，`Very difficult in US and Europe`。常见非法方式包括内幕交易，`Insider trading`；抢跑订单，`Front-running orders`；spoofing；与其他人串通以控制市场，`Collusion with others to corner market`；操纵伦敦下午 4 点定盘，`Rigging the 4 pm London Fix`。

源页引用最大美国内幕交易案判决新闻，强调这些行为会被执法追究。交易者应知道这些非法行为存在，但不能把它们当成不学习图表和风险管理的理由。

## 高频交易：程序化交易的一种，贡献多数成交量，但对方向影响最小

`source: part1 p292-p295`

高频交易是程序化交易的一种，`Type of program trading`。它创造一天中大多数成交量，`Creates most of day's volume`。HFT 公司通过刮头皮获取微小利润，`HFT firms scalp for tiny profits`，对市场方向影响最小，`Minimal effect on market's direction`。

![高频交易创造大量成交量但方向影响小](../assets/evidence/video_005/part1_p0292.webp)

课程强调 HFT 与普通交易者无关，`Nothing to do with traders`。普通交易者以分钟为单位操作，不是以毫秒为单位，`We operate in minutes, not milliseconds`。典型 HFT 公司每天交易 10 到 50 million 笔，`10 - 50 million trades a day`；每笔交易 100 到 300 股，`100 - 300 shares per trade`；交易 4,000 只股票的篮子，`Basket of 4,000 stocks`；只有 55% 的时间正确，`Right only 55% of the time`；每笔交易赚一分钱，`Making a penny per trade`。

![典型 HFT 公司交易数量和胜率](../assets/evidence/video_005/part1_p0294.webp)

市场成交量构成中，其他机构贡献 25%，`Other institutions contribute 25%`；你和我占最后 5%，`You and I make up the final 5%`。源页图表写出 HFT 公司创造 70% 的成交量，`HFT Firms Create 70% of Volume`。这说明散户在总成交量中只是极小部分。

![HFT 公司创造 70% 成交量，其他机构 25%，散户 5%](../assets/evidence/video_005/part1_p0295.webp)

## 2010 年 5 月 6 日 Emini 闪崩与 HFT 成交量

`source: part1 p296-p298`

2010 年 5 月 6 日 Emini 发生闪崩，`Flash Crash of May 6, 2010`。当天 Emini 下跌 99 点，约 10%，`Fell 99 points, about 10%`；在 10 分钟内下跌 6%，即 60 点，`Fell 6% (60 points) in 10 minutes`；随后反弹 66 点，`Then rallied 66 points`。

![2010 年 5 月 6 日 Emini 闪崩](../assets/evidence/video_005/part1_p0296.webp)

闪崩中很少几家公司交易了巨大成交量。15 家 HFT 公司交易了 34% 的成交量、33% 的交易，每天 3,200 笔交易，平均规模 6 份合约。个人交易者只交易 1% 的成交量、2% 的交易，每天 1 笔交易，平均规模 1 份合约。

![闪崩中 HFT 与个人交易者成交量对比](../assets/evidence/video_005/part1_p0298.webp)

这些数字说明 HFT 在极端事件中参与度很高，但也说明散户不是市场主要目标。

## Spoofing：虚假订单使成交量无用

`source: part1 p300`

机构并不愚蠢，`Firms are not stupid`。它们知道一些公司使用成交量来决定交易，`Know some firms use volume to decide on trades`，因此出现 spoofing 机会：创造虚假订单欺骗其他公司，`Create fake orders to trick other firms`。这种行为根据 2010 年 Dodd-Frank Act 非法，`Illegal under Dodd-Frank Act, 2010`。

![spoofing 如何工作](../assets/evidence/video_005/part1_p0300.webp)

源图解释了 spoofing 的一般过程：spoofing 交易者先放出一个人为价格的大卖单，引诱其他卖家跟随，随后取消卖单并同时买入；之后反向放出大买单，引诱买家跟随，再取消买单并卖出。通过大量重复大订单，spoofing 者可以在短时间内积累利润。

## Spoofing 示例：放置、取消虚假 Emini 卖单，再反向获利

`source: part1 p301-p304`

spoofing 有很多变化。示例中，spoofing 公司想以更低价格买入 Emini，`Spoofing firm wants to buy Emini lower`。它在当前价格上方放置巨大卖单，offer，但意图是在成交前取消，`Places huge sell orders just above, but with intention to cancel before filled`。源图中，spoofing 者在当前 bid 上方 5 ticks 处放置卖出 500 份 Emini 的订单。

![spoofing：放置虚假卖单](../assets/evidence/video_005/part1_p0301.webp)

其他公司看到巨大卖单后开始卖出，`Other firms see huge sell order`、`Start selling`。随着市场下跌，spoofing 者取消巨大挂起卖单，`As market falls, spoofer cancels huge resting sell order`，并同时买入，`Spoofer buys at same time`。图中写出卖单消失，价格下跌，spoofing 者买入 Emini。

![spoofing：取消虚假卖单并买入](../assets/evidence/video_005/part1_p0302.webp)

其他公司注意到卖单被取消，停止卖出并买回空头，`They stop selling and buy back shorts`。据说 Paul Rotter，即 “The Flipper”，在德国债券中使用过这种方式。随后市场上涨，spoofing 者获利退出，`Market goes up`、`Spoofer exits with profit`。

![spoofing：其他公司回补，spoofing 者获利](../assets/evidence/video_005/part1_p0304.webp)

这里的交易含义是：仅靠盘口挂单量判断方向会被欺骗。价格行为最终会显示假单取消、价格下跌、回补和反向移动。

## Front running：抢跑订单也是非法的

`source: part1 p305-p307`

`Front running` 是抢跑交易，指交易者通过内部信息或其他方式提前在客户订单之前交易以获利。课程明确写出 front running 也是非法的，`Front running is also illegal`。公司拿到你的买入订单，`Firms takes your order to buy`；如果看到信号 K 线上方有很多止损单，它就在你之前买入，`If sees a lot of stop orders just above, it buys just before you`；当你买入时，它卖给你，`It sells to you when you buy`。它通过卖给你来填补你的订单并获利，`It takes profits by selling to you to fill your order`。

![front running：机构在客户买单前先买](../assets/evidence/video_005/part1_p0306.webp)

front running 可以从极小盗窃中获得巨大利润，`Huge Profits from Tiny Thefts`。如果 100 股赚半美分，则每笔交易赚 50 cents，`If makes 1/2 penny on 100 shares, then 50 cents per trade`。如果每天做 10,000 次，那么每年额外利润为 100 万美元，`If do it 10,000 times a day, then $1 million a year in extra profit`。

![front running：微小优势累积成巨大利润](../assets/evidence/video_005/part1_p0307.webp)

## HFT 最大化所有优势，但不是散户亏损的主要原因

`source: part1 p308-p314`

HFT 公司最大化所有优势，`Maximizes Every Advantage`。它们使用极快计算机，`very fast computers`；位于交易所附近以最小化延迟，`Located close to the exchanges to minimize latency`；持仓从微秒到数小时不等，`Hold trades for micro-seconds to hours`；经常为一个 tick 做刮头皮，`Often scalp for one tick`。

![HFT 公司最大化所有优势](../assets/evidence/video_005/part1_p0308.webp)

但散户只占市场的 5%，是很小的一块，`You and I make up only 5%`。机构不能主要从散户身上赚钱，因为散户资金不够，`Firms cannot make money from us. We don't have enough`。课程把 blaming HFT 视为没有学习交易的借口，`Excuse for failing to learn how to trade`。机构必须从其他机构赚钱，因为其他机构占市场 95%，`Firms have to make money from other firms, which are 95% of market`。

HFT 利润示例：一家公司今天做 10 million 笔交易，每笔 100 股；在 5.5 million 笔交易中赚 1 penny，胜率 55%；在 4.5 million 笔交易中亏 1 penny。5.5 million 个盈利 pennies = 5.5 million 美元；4.5 million 个亏损 pennies = 4.5 million 美元；当天净利润 = 1 million 美元；每年净利润 = 200 million 美元。

![HFT 公司微利交易的利润计算](../assets/evidence/video_005/part1_p0312.webp)

HFT 公司追逐财富，但许多会亏损，`HFT Firms Chase Riches: Many Lose`。巨大利润潜力创造了许多公司，`Huge profit potential creates lots of firms`；只有最好的 HFT 公司能做得那么好，`Only best HFT firms do that well`；许多公司亏钱，`Many lose money`。

![HFT 公司利润分布：许多亏损](../assets/evidence/video_005/part1_p0313.webp)

课程最后明确说，HFT 公司不是交易者交易问题的根源，`HFT Firms: Not the Problem With Your Trading`。每个人都想把自己的亏损归咎于别人，`Everyone wants to blame their losses on others`。如果你亏损，是因为你还不够好，`If you lose, it is because you are not yet good enough`。市场中有钱可以赚，`The dollars are there for the taking`，但你必须学会如何交易，`You have to learn how to trade`。

## 本单元的可执行知识点索引

- `source: part1 p283-p284`：程序化交易算法基于所有可想象概念；即使平静 TR 中成交量也巨大；多头和空头程序争夺上下突破，最终一方获胜，另一方回补，市场突破。
- `source: part1 p285`：30% 交易是套利交易；机构在相关市场持相反头寸，利用微小差异获利，并使相关市场接近公平价值。
- `source: part1 p286-p288`：程序交易不能隐藏，因为交易创造每个人都能看到的价格行为；个体交易者不能移动市场，自己的买卖价格能成交，说明机构也在相同价格买卖。
- `source: part1 p289-p290`：非法作弊方式包括 insider trading、front-running orders、spoofing、collusion to corner market、rigging the 4 pm London Fix；在美国和欧洲这些行为很难且会被追究。
- `source: part1 p292-p295`：HFT 是程序化交易的一种，创造当天大部分成交量但对方向影响最小；典型 HFT 每天 10-50 million trades、每笔 100-300 shares、4,000 股票篮子、55% 正确、每笔赚 1 penny；HFT 占 70% 成交量，其他机构 25%，散户 5%。
- `source: part1 p296-p298`：2010-05-06 Emini 闪崩中，Emini 跌 99 点约 10%，10 分钟跌 6% 即 60 点，随后反弹 66 点；15 家 HFT 公司占 34% 成交量和 33% 交易，平均 6 合约；个人交易者占 1% 成交量和 2% 交易，平均 1 合约。
- `source: part1 p300-p304`：spoofing 通过虚假大订单欺骗使用成交量/盘口量的机构，Dodd-Frank Act 2010 下非法；示例为在当前 bid 上方 5 ticks 放置 500 Emini 大卖单，诱使其他公司卖出，取消卖单后买入，随后其他公司回补，spoofing 者获利退出。
- `source: part1 p306-p307`：front running 非法；机构看到信号 K 线上方大量买入止损单后先买入，再卖给客户完成订单；100 股赚 1/2 penny 等于每笔 50 cents，每天 10,000 次可产生每年 $1 million 额外利润。
- `source: part1 p308-p314`：HFT 使用极快电脑、靠近交易所、持仓微秒到数小时、常为 1 tick 刮头皮；散户只占市场 5%，机构必须从占 95% 的其他机构赚钱；10 million 笔交易、55% 每笔赚 1 penny、45% 每笔亏 1 penny，可净赚当天 $1 million、每年 $200 million，但许多 HFT 公司亏损。
