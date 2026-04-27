# Video 3E: Forex Margins, Rollover, Carry Trade, and Profit/Loss

来源范围：`part1 p248-p266`。本章对应 Al Brooks “Price Action Fundamentals” 课程的 `Video 3E (#5 of 5)`，主题是保证金、盈亏、rollover、carry trade 和外汇盈亏公式。正文依据渲染后的幻灯片逐页视觉校对后重写，保留保证金比例、货币基础、roll rates、隔夜三倍利息、long/short 盈亏公式、conversion factor 和所有示例数字；标题页、目录页、重复页和结束页不进入正文图像。

## 本单元范围：保证金与盈亏

`source: part1 p248-p249, p254, p266`

本视频是 `Forex Basics` 的第五部分，主题只有两个：保证金，`Margins`；盈亏，`Profit and loss`。这一章从“开仓需要多少保证金”转向“交易结束后盈亏如何按照报价货币和账户货币结算”。

## 保证金是开仓的善意押金，不是费用或佣金

`source: part1 p250`

保证金是为了开仓而放入的善意押金，`Good faith deposit to open a position`。它不是费用，也不是佣金，`Not a fee or commission`。保证金根据基础货币计算，`Calculated on base currency`。如果交易 EURUSD，保证金是 EUR 的 2%，`If EURUSD, margin is 2% of EUR`。源页用图示说明，每 10 欧元保证金控制 500 欧元头寸，`Every 10 Euros in margin controls a 500 Euro position`。

![保证金是开仓押金，不是费用](../assets/evidence/video_003E/part1_p0250.webp)

## USDJPY 与 EURUSD 的保证金示例

`source: part1 p251-p252`

如果以 104.041 的价格买入 100,000 单位 USDJPY，保证金是基础货币 USD 的 2%，`Margin is 2% of base currency (USD)`。100,000 美元的 2% 等于 2,000 美元，`2% of $100,000 = $2,000`。

![100,000 USDJPY 的保证金示例](../assets/evidence/video_003E/part1_p0251.webp)

如果以 1.31275 买入 100,000 EURUSD，保证金是基础货币 EUR 的 2%。100,000 × 1.31275 美元/欧元 = 131,275 美元，2% 保证金约为 2,626 美元，`2% margin is about $2,626`。

![100,000 EURUSD 的保证金示例](../assets/evidence/video_003E/part1_p0252.webp)

这两个例子说明，保证金按基础货币计算，但账户显示和风险常以美元换算。USDJPY 的基础货币是 USD，所以计算直接；EURUSD 的基础货币是 EUR，需要先把 100,000 欧元换算为美元名义价值。

## 外汇保证金通常小于非外汇市场，常见 20:1 到 50:1

`source: part1 p253`

外汇保证金通常小于非外汇市场，`Margins are smaller than for non-Forex markets`，因为外汇市场通常按百分比计算的波动较小，`Forex markets usually move less on % basis`。50:1 杠杆只需要 2% 保证金，`50:1 leverage is only 2% margin`。每交易 10,000 美元需要 200 美元保证金，`$200 for every $10,000 traded`。保证金通常是 20:1 到 50:1，`Margin often 20:1 to 50:1`。

![外汇保证金通常 20:1 到 50:1](../assets/evidence/video_003E/part1_p0253.webp)

这页给出的是风险约束而不是收益承诺。保证金小意味着交易者可以控制更大名义金额，但价格反向移动时账户损益也会放大。

## 交易盈亏基于报价货币，并在日终转换为账户货币

`source: part1 p255-p256`

一笔交易的盈亏基于报价货币，`Profit or Loss on a Trade: Based on Quote Currency`。以 EURUSD 为例，报价货币是 USD，所以盈亏以美元为基础，`Based on the quote currency (here, USD)`。如果账户本币也是美元，那么时段结束后不需要转换，`Since USD is account currency, no conversion`。如果账户本币不是报价货币，盈亏会在时段结束时转换为账户本币，`Converted into your native account currency, at end of session`。

如果交易 EURJPY，但本地账户货币是美元，则在一天结束时自动转换回美元。若盈利，利润以日元计，因此日元以 Bid 卖出换成美元，`If profit, it is in yen, so yen sold at Bid into dollars`。若亏损，则用美元按 Ask 买入日元以弥补亏损，`If loss, buy yen at Ask in dollars to cover loss`。

![日终盈亏转换回账户货币](../assets/evidence/video_003E/part1_p0256.webp)

## Rollover：每 24 小时交易日结束时平仓并自动重新开仓

`source: part1 p257`

Rollover 发生在每个 24 小时交易时段结束时，即美国东部时间下午 5 点，`At End of Each 24 Hour Session (5 pm ET)`。所有仓位会被关闭，`All positions are closed`，然后为下一个交易日自动重新开仓或滚动，`Reopened automatically (rolled over) for next trading day`。下一交易日通常几分钟后开始，周五除外，`begins just few minutes later, except on Friday`。

![每 24 小时时段结束的 rollover](../assets/evidence/video_003E/part1_p0257.webp)

## Carry trade：买高利率货币，卖低利率货币

`source: part1 p258-p259`

Carry trade 是购买利率较高的货币或债券，`Buy currency (or bond) with higher interest rate`，同时卖出利率较低的货币或债券，`Sell currency (or bond) with lower interest rate`。交易者支付较低利率，收取较高利率，`Pay the lower interest rate, and collect the higher one`。利润来自利率差，`Profit is difference in interest rates`。

![Carry trade：买高利率货币、卖低利率货币](../assets/evidence/video_003E/part1_p0258.webp)

源图例子中，日本央行基准借款利率低于 0.1%，投资者以低利率借入日元，然后兑换成墨西哥比索或购买墨西哥债券。墨西哥比索计价的 2023 年 12 月债券收益率为 6.5%，投资者收取较高利率，并在比索相对日元上涨时获益。

Carry trade 是长期策略，用于创造收入和利润，`Long-term strategy, to generate income and profits`。它适合机构，不适合个人，`For institutions, not individuals`。只有在汇率稳定，或外汇价格朝交易者方向移动时才有效，`Only works, if either exchange rate is stable, or Forex price moves in your direction`。

![Carry trade 适合机构且要求汇率稳定或价格顺向](../assets/evidence/video_003E/part1_p0259.webp)

## Carry trade 影响 rollover 价格

`source: part1 p260`

Carry trade 会影响 roll price。示例是做多 100,000 AUDCHF。如果多头 roll rate 是 3.20 美元，空头 roll rate 是 -6.10 美元，那么在下一交易时段开盘时，3.20 美元会加到账户，`$3.20 added to your account on open of next session`。如果是周五，会得到 3 天利息，因此是 9.60 美元，`If Friday, get 3 days worth of interest, so $9.60`。如果做空 100,000 AUDCHF，则 6.10 × 3 = 18.30 美元会被扣除，`would be debited`。

![Carry trade 影响 rollover 价格](../assets/evidence/video_003E/part1_p0260.webp)

这页把 carry trade 从理论利差连接到实际账户变动：持仓跨越结算时间时，账户会按 roll rate 得到利息或被扣利息。

## 盈亏公式：long、short 与 conversion factor

`source: part1 p261`

做多交易的盈亏公式是：`(exit price - entry price) × conversion factor × trade size`。做空交易的盈亏公式是：`(entry price - exit price) × conversion factor × trade size`。`Conversion factor` 是把盈亏转换成美元所需的汇率，`exchange rate to convert into US dollars`。

![外汇盈亏公式](../assets/evidence/video_003E/part1_p0261.webp)

做多公式和做空公式的差别只在于价格差方向。若报价货币已经是美元，conversion factor 可以是 1；若盈亏以日元等其他货币计，需要用转换因子换算成美元。

## 示例：做空 100,000 EURUSD，10 pips 约 100 美元

`source: part1 p262`

如果在 1.31811 卖出，并在 1.31711 买回，做空交易盈亏为 `(1.31811 - 1.31711) × conversion factor × 100,000`。计算为 0.00100 × 1 × 100,000 = 100 美元。由于该头寸盈亏已经以美元计，不需要转换，`no conversion since position already in dollars`。快速计算是：10 pips 利润约等于 100 美元，`10 pips profits = about $100`。

![做空 100,000 EURUSD 盈利示例](../assets/evidence/video_003E/part1_p0262.webp)

## 示例：做多 100,000 USDJPY，31 pips 约 300 美元

`source: part1 p263`

如果在 103.801 买入，并在 104.112 卖出，做多交易盈亏为 `(104.112 - 103.801) × conversion factor × 100,000`。价格差为 0.311，需要把日元换算成美元，所以使用 conversion factor 0.0096。计算为 0.311 × 0.0096 × 100,000 = 298 美元。快速计算是：1 pip 略低于 10 美元，所以 31 pips 利润约 300 美元。

![做多 100,000 USDJPY 盈利示例](../assets/evidence/video_003E/part1_p0263.webp)

## 示例：做多 100,000 EURJPY，110 pips 约 1,000 美元

`source: part1 p264-p265`

如果在 136.801 买入，并在 137.902 卖出，做多交易盈亏为 `(137.902 - 136.801) × conversion factor × 100,000`。价格差是 1.101，conversion factor 是 0.0096。计算为 1.101 × 0.0096 × 100,000 = 1,057 美元。快速计算是：1 pip 略低于 10 美元，所以 110 pips 利润约 1,000 美元。

![做多 100,000 EURJPY 盈利示例](../assets/evidence/video_003E/part1_p0264.webp)

`part1 p265` 是同一 EURJPY 计算页的重复页，正文以 `part1 p264-p265` 合并处理。

## 本单元的可执行知识点索引

- `source: part1 p250`：保证金是开仓善意押金，不是费用或佣金；保证金按基础货币计算；EURUSD 保证金是 EUR 的 2%；每 10 欧元保证金控制 500 欧元头寸。
- `source: part1 p251-p252`：买入 100,000 USDJPY 时，基础货币 USD 的 2% 保证金为 2,000 美元；买入 100,000 EURUSD at 1.31275 时，100,000 × 1.31275 = 131,275 美元，2% 保证金约 2,626 美元。
- `source: part1 p253`：外汇保证金通常小于非外汇市场，因为外汇按百分比波动通常较小；50:1 杠杆只需 2% 保证金；每 10,000 美元交易需要 200 美元保证金；保证金通常 20:1 到 50:1。
- `source: part1 p255-p256`：交易盈亏基于报价货币；EURUSD 盈亏基于 USD，若账户也是 USD 不需转换；EURJPY 盈利以日元计时，日终按 Bid 卖日元换美元，亏损时按 Ask 买日元覆盖亏损。
- `source: part1 p257`：Rollover 在每个 24 小时交易时段结束时，即 5 pm ET，所有仓位关闭并自动为下一交易日重新开仓，周五除外。
- `source: part1 p258-p259`：Carry trade 是买高利率货币或债券、卖低利率货币或债券，利润来自利率差；它是机构长期策略，只有在汇率稳定或价格顺向时有效。
- `source: part1 p260`：做多 100,000 AUDCHF 若多头 roll rate 为 $3.20，下一时段账户增加 $3.20；周五得 3 天利息为 $9.60；若做空则 $6.10 × 3 = $18.30 扣除。
- `source: part1 p261`：Long P/L = `(exit price - entry price) × conversion factor × trade size`；Short P/L = `(entry price - exit price) × conversion factor × trade size`；conversion factor 是转换成美元的汇率。
- `source: part1 p262`：做空 100,000 EURUSD，1.31811 卖出、1.31711 买回，0.00100 × 1 × 100,000 = $100，10 pips 约 $100。
- `source: part1 p263`：做多 100,000 USDJPY，103.801 买入、104.112 卖出，0.311 × 0.0096 × 100,000 = $298，31 pips 约 $300。
- `source: part1 p264-p265`：做多 100,000 EURJPY，136.801 买入、137.902 卖出，1.101 × 0.0096 × 100,000 = $1,057，110 pips 约 $1,000。
