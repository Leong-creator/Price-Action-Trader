# Video 4: My Setup

来源范围：`part1 p267-p280`。本章对应 Al Brooks “Price Action Fundamentals” 课程的 `Video 4`，主题是交易环境和图表设置。正文依据渲染后的幻灯片逐页视觉校对后重写，保留专注环境、5 分钟 ES Emini 设置、RTH/ETH 与 continuation contracts 差异、15/60 分钟 EMA 在 5 分钟图上的近似参数、日周月图均线设置；标题页和结束页不进入正文图像。

## 交易环境：减少干扰并保持专注

`source: part1 p268`

Al Brooks 的家庭办公室设置很简单。他使用笔记本电脑，第二台电脑用于聊天室，`Laptop (2nd computer is for chat room)`。交易时窗帘拉上，不接电话，不看电视，`Blinds closed, don't take calls, don't watch TV`。他忽略新闻和评论人士，`Ignore the news and pundits`。他不希望有任何干扰或意见，`I don't want any distractions, or opinions`，并且非常专注，`I am very focused`。

这页不是一般生活建议，而是交易流程的一部分。价格行为交易要求连续读取 context、momentum、突破、回调和失败信号；外部意见和新闻解释会干扰交易者对图表本身的判断。

## 交易工作的零和性质

`source: part1 p269`

Al Brooks 把自己的工作定义为通过做喜欢的事赚钱，`Make Money Doing Something I Love`。他说自己的工作是把钱从你的账户拿出来放进他的账户，`Take money from your account, and put it into mine`；你的工作是把钱从他的账户拿走，`Your job is to take money from mine`。这就是市场游戏，`That is the game we are playing`。

这段话把交易从“预测故事”拉回到对手盘现实。每笔交易都有另一方，交易者需要在概率、风险和管理上比对手更好，而不是只追求解释。

## 主要设置：5 分钟 S&P500 ES Emini，叠加 20 EMA 和较高周期 EMA

`source: part1 p270`

Al Brooks 的核心设置是 5 分钟 S&P500 ES Emini 图，`My Setup: 5 Minute S&P500 ES Emini`。图上显示 5 分钟图自身的 20 bar EMA，同时叠加 15 分钟 20 bar EMA 和 60 分钟 20 bar EMA。图中标注 `20 bar EMA (the 5 minute)`、`15 minute 20 bar EMA`、`60 minute 20 bar EMA`。

![5 分钟 S&P500 ES Emini 设置](../assets/evidence/video_004/part1_p0270.webp)

这说明 Brooks 的交易视角虽然以 5 分钟图为主，但并不忽略较高周期均线。15 分钟和 60 分钟 EMA 给 5 分钟走势提供更大背景，尤其在趋势、回调、均线测试和价格距离均线过远时有参考意义。

## 为什么你的 Emini 图表可能与他的不同

`source: part1 p271-p272`

Emini 图表可能因为数据源设置不同而与 Brooks 图表不同。你的图表可能在移动平均线上方，因为你使用 24 小时数据，也就是 ETH，`Extended Trading Hours`。你的价格也可能不同，因为你使用季度合约，而不是 continuation contracts。Brooks 的图表有很多 K 线低于移动平均线，是因为他使用日盘数据，也就是 RTH，`Regular Trading Hours`，以及 continuation contracts。

![Emini 图表差异：ETH/RTH 与合约类型](../assets/evidence/video_004/part1_p0271.webp)

因此，比较图表时不能只问同一根 K 线是否在均线上方或下方，还要确认数据时段、合约连续性、平台和均线计算方式。否则同一市场会因为输入数据不同而给出不同视觉结论。

## 5 分钟 EURUSD 上的 20 EMA、15 分钟 EMA 和 60 分钟 EMA

`source: part1 p273`

5 分钟 EURUSD 图同样展示三条 EMA：5 分钟图自身的 20 bar EMA，15 分钟 20 bar EMA，以及 60 分钟 20 bar EMA。源图中 60 分钟 EMA 处在更高位置，15 分钟 EMA 与 5 分钟 EMA 更接近。

![5 分钟 EURUSD 上的多周期 EMA](../assets/evidence/video_004/part1_p0273.webp)

这个设置与 ES Emini 一致，说明 Brooks 不把多周期 EMA 限定在某一个市场。外汇和期货都可以用同一逻辑近似较高周期均线。

## 交易室多图布局：5 分钟、15 分钟、60 分钟、日线、周线、月线

`source: part1 p274`

交易室布局展示了多个时间周期。主图是 5 分钟图，旁边有 60 分钟、15 分钟、月线、周线和日线图。较高周期图不是为了替代 5 分钟入场，而是用于提供更大支撑阻力、趋势位置和均线背景。

![多周期交易室布局](../assets/evidence/video_004/part1_p0274.webp)

这与前面“context 是当前 K 线左侧所有 K 线”和“所有市场周期具有相同价格行为”相一致。较高周期能显示更大的趋势、交易区间和均线测试，帮助避免只被 5 分钟局部形态牵引。

## TradeStation 中 60 分钟与 15 分钟 20 EMA 的计算

`source: part1 p275-p276`

源页给出 TradeStation 代码，用于在 5 分钟图上近似 60 分钟 20 bar EMA 和 15 分钟 20 bar EMA。60 分钟 EMA 指标使用 `_length(20)`，并以 `SessionEndTime(1315 {PST US Session})` 作为输入。代码中先用 `Xaverage(C, 240)` 初始化，因为 60 分钟相当于 12 根 5 分钟 K 线，20 根 60 分钟 K 线约等于 240 根 5 分钟 K 线。页面备注提醒，`1315` 应按自己的时区调整为对应交易时段结束时间，1315 是太平洋标准时间。

15 分钟 EMA 指标同样使用 `_length(20)`，并用 `Xaverage(C, 60)` 初始化，因为 15 分钟相当于 3 根 5 分钟 K 线，20 根 15 分钟 K 线约等于 60 根 5 分钟 K 线。代码按 15 分钟边界更新 EMA，其余时间用当前 5 分钟收盘近似当前较高周期 EMA 值。

这些代码页不需要逐行成为交易规则，但它们说明 Brooks 的较高周期 EMA 不是随意画线，而是用可编程方式在 5 分钟图上近似较高周期 20 EMA。

## 任意平台上的近似参数：15 分钟 EMA 用 60 或 50，60 分钟 EMA 用 240 或 220

`source: part1 p277`

任何平台都可以近似 Al Brooks 编程的 EMA，`A close approximation to Al Brooks' programmed EMAs, can be achieved for any platform`。方法是调整平台指标中的 EMA 周期，`Adjust period of EMA within platform indicators`。

在 5 分钟图上显示 15 分钟 EMA 时，因为 15min / 5min = 3，应把 EMA 指标周期设为 3 × 20 = 60；源页还写出 50 更准确，`50 is more accurate`。在 5 分钟图上显示 60 分钟 EMA 时，因为 60min / 5min = 12，应把 EMA 指标周期设为 12 × 20 = 240；源页写出 220 更好，`220 is better`。

![5 分钟图上近似 15 分钟与 60 分钟 EMA](../assets/evidence/video_004/part1_p0277.webp)

这给后续复盘提供了可执行参数：如果平台不能按 Brooks 代码计算较高周期 EMA，可以先用 50 近似 15 分钟 20 EMA，用 220 近似 60 分钟 20 EMA。

## 日线、周线、月线背景：50、100、150、200 bar simple MA

`source: part1 p278-p279`

较高周期背景中，Brooks 展示了 S&P500 cash index 日线上的 50 bar simple MA、100 bar simple MA、150 bar simple MA 和 200 bar simple MA。图中这些均线用于观察日线长期趋势和回调位置。

![S&P500 日线 50/100/150/200 bar simple MA](../assets/evidence/video_004/part1_p0278.webp)

EURUSD 日线图同样显示 50、100、150、200 bar simple MA。这个设置说明大周期均线用于市场背景，而不是只用于某一种资产。

![EURUSD 日线 50/100/150/200 bar simple MA](../assets/evidence/video_004/part1_p0279.webp)

## 本单元的可执行知识点索引

- `source: part1 p268`：交易环境使用笔记本，第二台电脑用于聊天室；窗帘拉上，不接电话，不看电视；忽略新闻和评论人士；避免干扰和意见，保持高度专注。
- `source: part1 p269`：交易是对手盘游戏，目标是从对方账户拿钱，对方也试图从你的账户拿钱。
- `source: part1 p270`：主要设置是 5 分钟 S&P500 ES Emini，显示 5 分钟 20 bar EMA，并叠加 15 分钟 20 bar EMA 和 60 分钟 20 bar EMA。
- `source: part1 p271-p272`：你的 Emini 图表可能因使用 24 小时 ETH 数据而在均线上方；Brooks 使用 RTH 日盘数据和 continuation contracts，所以图上很多 K 线可能低于 MA；季度合约与连续合约也会造成价格差异。
- `source: part1 p273-p274`：5 分钟 EURUSD 同样显示 5、15、60 分钟 20 EMA；交易室布局同时看 5 分钟、15 分钟、60 分钟、日线、周线、月线。
- `source: part1 p275-p276`：TradeStation 中 60 分钟 20 EMA 用 240 根 5 分钟 K 线近似，15 分钟 20 EMA 用 60 根 5 分钟 K 线近似；交易时段结束时间要按时区调整。
- `source: part1 p277`：任意平台近似参数为：5 分钟图上的 15 分钟 20 EMA 设置为 3 × 20 = 60，50 更准确；5 分钟图上的 60 分钟 20 EMA 设置为 12 × 20 = 240，220 更好。
- `source: part1 p278-p279`：日线背景图可使用 50、100、150、200 bar simple MA，示例包括 S&P500 cash index 和 EURUSD。
