# Video 3D: Forex Charts Are Approximate, Scalps and Swing Trades

来源范围：`part1 p232-p247`。本章对应 Al Brooks “Price Action Fundamentals” 课程的 `Video 3D (#4 of 5)`，主题是外汇图表只是近似，以及外汇中的刮头皮交易和波段交易。正文依据渲染后的幻灯片逐页视觉校对后重写，保留 Bid、Ask、midpoint、inside bid/ask、订单成交与图表不一致、scalp 的 K 线数量和 pip 数、swing 的 K 线数量和 leg 规则；标题页、目录页、纯文字重复页、回顾页和结束页不进入正文图像。

## 本单元范围：图表仅近似，刮头皮和波段交易

`source: part1 p232-p233, p243, p246-p247`

本视频有两个主题：外汇图表仅近似，`Charts only approximate`；刮头皮和波段交易，`Scalps and swing trades`。由于外汇没有集中交易所和统一最后成交价，同一货币对在不同经纪商图表上可以略有差异，交易者必须理解订单实际以 Bid 或 Ask 成交，而图表可能只显示其中一种报价或中点。

## 外汇图表只是近似，没有真正统一的 Last

`source: part1 p234`

外汇没有实际集中市场，因此 “Last” 永远无法被统一知道，`No actual market, so "Last" is never known`。不同经纪商使用不同银行，`Different brokers use different banks`；有些经纪商使用多家银行，`Some brokers use many banks`。每个经纪商的图表都略有不同，因为他的图表只显示来自其银行的交易，`Chart slightly different for each broker, since his charts only shows the trades from his bank`。课程提醒，不要担心接下来几张幻灯片中的细节，`Don't worry about details in next few slides`。

![外汇图表只是近似](../assets/evidence/video_003D/part1_p0234.webp)

源图举例，Interactive Brokers 图表上的 “Last” trade 是 1.11350，而 FXCM 图表上的 “Last” trade 是 1.11340。这个差异不是交易者策略错误，而是外汇市场结构导致的报价来源差异。

## 外汇图表不显示实际交易，可以基于 Bid、Ask、Bid/Ask 或中点

`source: part1 p235`

外汇图表不显示实际交易，`Forex Charts: Do Not Show Actual Trades`。图表可以基于 Bid，可以基于 Ask，可以基于 Bid 和 Ask，也可以基于 Bid 与 Ask 的中点，`Midpoint of Bid and Ask`。如果图表基于 Bid 和 Ask，课程写出每根 K 线低点可能是该低点处最大 Ask，而 K 线高点可能是该高点处最小 Bid，`low of each bar is maximum Ask at the low, and high of bar is minimum Bid at the high`。这说明外汇 K 线的高低点不是像交易所市场那样简单来自统一成交序列。

## 经纪商可以选择 inside Bid、inside Ask、midpoint 或 min Bid/max Ask

`source: part1 p236-p237`

经纪商有几种图表选择。图表可以只基于 `inside Bid`，也就是最接近上次交易的 Bid，`Inside means the closest Bid to the last trade`。也可以只基于 `inside Ask`，即最接近上次交易的 Ask。源页示例中，EURUSD 基于 inside Bid 的高点是 1.13190，这是 FXCM 默认；而 EURUSD.A 基于 inside Ask，给符号加 `.A`，高点是 1.13205，比 Bid 高 1.5 pips，因为 Ask 总是更高，`Ask is always higher`。

![inside Bid 与 inside Ask 图表差异](../assets/evidence/video_003D/part1_p0236.webp)

Interactive Brokers 图表可以基于 Bid 和 Ask 的中点。示例中基于中点的 EURUSD 高点是 1.131450，低点是 1.131375，使用 6 位小数。另一种图表基于最小 inside Bid 和最大 inside Ask，K 线会更大，因为没有使用中点，`bar is bigger since not using midpoint`；示例高点是 1.13165，即 max Ask，低点是 1.13125，即 min Bid。

![midpoint 与 min Bid/max Ask 图表差异](../assets/evidence/video_003D/part1_p0237.webp)

## Bid 图表上，买入交易可能不会显示在图表上

`source: part1 p238-p239`

如果图表基于 Bid，买入交易可能不会出现在图表上，`Chart Based on Bid: Buy Trade Might Not Be on Chart!`。FXCM 默认图表只显示 Bid，不显示实际交易或 Ask，`The default FXCM charts show only Bids, not actual trades or Ask`。买入限价单可能看起来应该在某处成交，但实际上不会成交，`Limit order to buy might not get filled here`。原因是买单以 Ask 成交，而 Ask 高于 Bid，因此也高于 K 线低点，`Buy orders filled at Ask, which is above Bid, and therefore above low of bar`。只有当 Ask 跌到买入订单下方时，买单才会成交，`Only get filled if Ask falls below buy order`。

![Bid 图表上买入交易可能不显示](../assets/evidence/video_003D/part1_p0238.webp)

买入也可能在 K 线高点上方成交，`Buys get filled at Ask, which can be above high of bar`；交易者可能在高于 K 线高点的位置买入成交，`Might get filled on buy order, above high of bar`。因此你的交易可能不会显示在图表上，`Your trade might not be on chart!`。

## Ask 图表上，卖出交易可能不会显示在图表上

`source: part1 p240-p241`

如果图表基于 Ask，卖出交易也可能不会出现在图表上，`Chart Based on Ask: Sell Trade Might Not Be on Chart!`。FXCM 可以创建只显示 Ask 的图表，`FXCM has the option of creating charts showing only Asks`。卖出限价单可能看起来应在某处成交，但实际不会成交，`Limit order to sell might not get filled here`。原因是卖单以 Bid 成交，而 Bid 低于 Ask，因此也低于 K 线高点，`Sell orders filled at Bid, which is below Ask and therefore below high of bar`。只有当 Bid 高于卖出订单时，卖单才会成交，`Only get filled if Bid goes above sell order`。

![Ask 图表上卖出交易可能不显示](../assets/evidence/video_003D/part1_p0240.webp)

卖出订单也可能在低于 K 线低点的位置成交，`Sells get filled at BID, which can be below low of bar`；交易者可能在低于 K 线低点的位置做空成交，`Can get filled on short below low of bar`。因此卖出交易也可能不显示在图表上。

## 外汇图表近似且永远不会完美

`source: part1 p242`

外汇图表近似且永远不会完美，`Forex Charts: Approximate and Never Perfect`。如果看起来订单应该成交但没有成交，不要担心，`Do not worry if looks like order should be filled but is not`。如果仍然担心，可以给经纪商打电话询问解释，`If worried, call your broker, and ask for explanation`。

![外汇图表近似且永远不会完美](../assets/evidence/video_003D/part1_p0242.webp)

这个执行层面的结论很重要：外汇图表的高低点与交易者订单成交之间可能存在 Bid/Ask 基础差异。交易复盘时，不应把每个看似未成交的订单都当作经纪商错误，也不能把图表上的单个价格点视为所有订单都会成交的绝对事实。

## 外汇 scalp：1-5 根 K 线、只有很小回调，常见 10-50 pips

`source: part1 p244`

外汇中的 “scalp” 通常指 1 到 5 根 K 线、只有很小回调的交易，`Forex "Scalp": 1 - 5 Bars, Only Small PB`。多数外汇交易者并不使用这个词，`Most Forex traders don't use that term`，而是把所有交易都称为 “trade”。那些提到 scalps 的交易者通常交易 60 分钟图及更小周期，`are trading 60 min charts and smaller`。在这种语境中，scalp 是 10 到 50 pips，`Scalp is 10 - 50 pips`。其他交易都只是 “trades”。

![外汇 scalp：1-5 根 K 线和 10-50 pips](../assets/evidence/video_003D/part1_p0244.webp)

源图给出几个具体交易。一个 scalp 在 10 pips 利润处退出，`Exit with 10 pips profit for scalp`。另一个交易是在失败空头突破处买入，`Buy failed bear BO`。还有一个是在双底看涨旗形处买入，`Buy DB bull flag`。波段交易者在时段结束退出，分别获得 18 pips 和 26 pips 利润，`Swing traders exit at end of session with 18 pips profit`、`with 26 pips profit`。

## Swing：5 根或更多 K 线，经常两条或更多腿，允许回调

`source: part1 p245`

波段交易是 5 根或更多 K 线，经常两条或更多 leg，并允许回调，`Swing: 5 or More Bars, Often 2 or More Legs, Allow PB`。在 5 到 15 分钟图上，scalp 是 10 到 40 pips，`On 5 - 15 minute chart, scalp is 10 - 40 pips`。在 60 分钟图上，scalp 是 20 到 50 pips，`on 60 minute chart, scalp is 20 - 50 pips`。任何更多的交易都称为 swing 或 trade，`Anything more is "swing" or "trade"`。

![外汇 swing：5 根或更多 K 线、两条或更多腿](../assets/evidence/video_003D/part1_p0245.webp)

波段交易通常至少 10 根 K 线、两条腿，`Swing usually at least 10 bars, 2 legs`。源图中，刮头皮交易者以 20 pips 利润退出，`Scalper exits with 20 pips profit`；波段交易者以 49 pips 利润退出，`Swing trader exits with 49 pips profit`。图上还标出在强空头跟进 K 线收盘处做空，`Sell close of strong bear follow-through bar`。

这一页把 scalp 与 swing 的区别从时间、K 线数量、leg 数量、是否允许回调和 pip 目标多个角度划分。scalp 更短、更依赖小回调和快速退出；swing 更长，允许回调，并通常包含至少两条腿。

## 本单元的可执行知识点索引

- `source: part1 p234-p235`：外汇没有集中实际市场，所以 Last 永远无法统一知道；不同经纪商用不同银行，图表略有不同；外汇图表不显示实际交易，可基于 Bid、Ask、Bid/Ask 或 Bid/Ask 中点。
- `source: part1 p236-p237`：图表可基于 inside Bid、inside Ask、midpoint 或 min Bid/max Ask；Ask 总高于 Bid，基于 Ask 的高点可能比 Bid 高点高 1.5 pips；不用 midpoint 时 K 线更大。
- `source: part1 p238-p239`：Bid 图表上买入订单以 Ask 成交，Ask 高于 Bid 和 K 线低点；只有 Ask 跌破买入限价单才成交，买入可能在 K 线高点上方成交，交易可能不显示在图表上。
- `source: part1 p240-p241`：Ask 图表上卖出订单以 Bid 成交，Bid 低于 Ask 和 K 线高点；只有 Bid 高于卖出限价单才成交，卖出可能在 K 线低点下方成交，交易可能不显示在图表上。
- `source: part1 p242`：外汇图表近似且永远不会完美；看起来该成交却没有成交时不要担心，必要时询问经纪商。
- `source: part1 p244`：外汇 scalp 通常是 1-5 根 K 线、很小 PB；多数外汇交易者不用 scalp 这个词；使用该词的人多交易 60 分钟及以下周期；scalp 通常是 10-50 pips。
- `source: part1 p244`：示例包括失败空头突破买入、DB bull flag 买入、scalp 10 pips 退出、波段交易者时段结束分别以 18 pips 和 26 pips 利润退出。
- `source: part1 p245`：Swing 是 5 根或更多 K 线，经常两条或更多腿并允许 PB；5-15 分钟图 scalp 为 10-40 pips，60 分钟图 scalp 为 20-50 pips；swing 通常至少 10 根 K 线、2 条腿，示例 scalp 20 pips 退出，swing 49 pips 退出。
