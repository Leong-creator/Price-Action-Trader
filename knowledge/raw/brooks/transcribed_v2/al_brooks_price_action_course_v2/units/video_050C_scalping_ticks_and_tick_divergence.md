# Video 50C: Scalping - Ticks, Tick Extremes, Tick Divergence, Support, and Resistance

来源范围：`advanced p1225-p1244`。本章对应 Al Brooks “How to Trade Price Action” 课程的 `Video 50C (#3 of 5)`，主题为 `Scalping` 中使用 ticks 寻找信号，以及 `Tick Divergence`。正文依据渲染后的幻灯片逐页视觉校对后重写，保留 NYSE tick 值定义、`700-1,000` 阈值、`1 point scalp`、`3-4 points` 风险、通常需要 `5 ticks` 才能赚 `4 ticks/1 point`、极端 tick 不一定是趋势结束、第一次极端值最重要、买入/卖出高潮中的 tick 背离、高手在支撑阻力汇合处反向剥头皮、`1-2 points` 目标、tick 支撑阻力和 tick 大部分时间高于 `0` 时多头突破概率增加等细节。标题页、目录页、回顾页和结束页不进入正文图像。

## NYSE ticks 衡量上一笔交易中上涨股与下跌股的净差

`source: advanced p1227`

NYSE 大约有 `3,000 stocks`。如果某只股票当前交易价高于上一笔交易价，它给 ticks 增加 `+1`；如果当前交易价等于上一笔交易价，增加 `0`；如果当前交易价低于上一笔交易价，增加 `-1`。当前 tick 值是 NYSE 全部股票的合计。如果 `Ticks = 1,000`，表示上一笔交易中上涨股票比下跌股票多 `1,000` 只。例如 `600` 只股票不变、`2,200` 只上涨、`1,200` 只下跌，则计算为 `0 + 2,200 - 1,200 = 1,000`。

本单元使用的核心阈值是 `Ticks 1,000`、`Ticks 700`、`Ticks -700`、`Ticks -1,000`。剥头皮交易者关注的是这些极端值是否出现在趋势早期、弱反弹末期、支撑阻力汇合处、或与价格新高新低发生背离时。tick 极端值本身不是信号，必须和 Emini 的价格行为一起判断。

![Ticks definition 700 to 1000：NYSE 约 3,000 stocks；当前交易价高于/等于/低于上一笔分别 +1/0/-1；Ticks=1000 表示上涨股比下跌股多 1000，只例 0+2200-1200=1000](../assets/evidence/video_050C/advanced_p1227.webp)

## 趋势早期的第一组 tick 极端通常不是趋势结束，而是剥头皮顺势信号

`source: advanced p1228-p1232`

若 Emini 横向到上行后出现空头突破，交易者寻找第一次 tick 读数低于 `-700` 或 `-1,000`。这种 tick 极端通常不是趋势结束，而是可顺势做空的信号。空头可以卖空头 K 收盘，并在更高位置加仓；也可以卖 `1 point PB`。管理上，第一次卖出打平退出，第二次卖出获得 `1 point` 利润。示例中虽然 tick 接近 `-700` 已到交易日结束，但方法重点是：第一次极端读数配合空头突破时，通常支持继续顺势剥头皮。

其他做空剥头皮方法也围绕 `1 point scalp`。空头可以在前一根 K 线上方卖出，可以卖空头旗形下方突破，可以在 `1 min MA` 处卖，也就是 `20 Gap Bar Sell`。这类交易的风险常为 `3-4 points`，目标是 `1 point`。由于 Emini 要赚 `4 ticks` 才等于 `1 point`，实际通常需要下跌 `5 ticks` 才能净赚 `4 ticks/1 point`，这说明小目标交易对入场位置和滑点很敏感。

反向逻辑用于横向到下行后的多头突破。如果 Emini 横向到下行并出现多头突破，交易者寻找第一次 tick 读数高于 `700` 或 `1,000`。多头可以买多头 K 收盘并在更低位置加仓，也可以买 `1 point PB`。第一次买入打平退出，第二次买入获得 `1 point` 利润。其他做多方法包括在前一根 K 线下方买、在多头旗形上方突破买、在从高点回调 `1 point` 处买、在均线处买，即 `20 Gap Bar Buy`。风险同样是 `3-4 points`，目标是 `1 point`，通常需要上涨 `5 ticks` 才能实现 `4 ticks/1 point` 盈利。当 ticks 更强并触及 `1,000` 时，重复同一流程。

![Tick extreme not end of trend：Emini sideways/up 后 bear BO，寻找第一次 ticks 低于 -700 或 -1000；卖 bear closes、scale in higher、卖 1 point PB；第一次卖打平，第二次卖赚 1 point](../assets/evidence/video_050C/advanced_p1228.webp)

![Other ways to sell scalp：1 point scalp 做空可卖 prior bar 上方、bear flag 下方 BO、1 min MA/20 Gap Bar Sell；risk 3-4 points，目标 1 point，通常需跌 5 ticks 才赚 4 ticks](../assets/evidence/video_050C/advanced_p1229.webp)

![Ticks above 700 or 1000 bull BO：Emini sideways/down 后 bull BO，寻找第一次 ticks 高于 700 或 1000；买 bull closes、scale in lower、买 1 point PB；第一次买打平，第二次买赚 1 point](../assets/evidence/video_050C/advanced_p1230.webp)

![Other ways to buy scalp：1 point scalp 做多可买 prior bar 下方、bull flag 上方 BO、从高点 1 point PB、MA/20 Gap Bar Buy；risk 3-4 points，目标 1 point，通常需涨 5 ticks 才赚 4 ticks](../assets/evidence/video_050C/advanced_p1231.webp)

## 弱反弹后的极端 tick 可能是高潮；第三或第四次极端更可能结束趋势

`source: advanced p1233-p1234`

当 ticks 在经过 `20 or more bars` 的疲弱反弹后达到 `1,000`，它可能是反弹的高潮结束，而不是会产生第二段上涨的突破。示例中价格阶梯式上涨到交易区间高位，因此很快出现反转的可能性增加。交易者不应立即买入；需要观察空头是否形成强反转，或者是否形成紧密空头通道。这里的重点是：同样的 `1,000`，若出现在趋势早期可能支持顺势剥头皮，若出现在二十多根 K 的弱反弹末期，则可能是买入高潮。

极端 ticks 中通常只有第一次极端最重要。当 ticks 达到 `-1,000`，但这是 tick 新低中的第三或第四次新低，它可能是卖出高潮，也是空头趋势结束。此时不应立即卖出；交易者要等待多头是否能形成强反转，或形成紧密多头通道。第一次极端值往往反映趋势爆发，后面的第三次、第四次极端值则可能反映趋势过度和衰竭。

![Extreme ticks possible climax：弱反弹 20+ bars 后 ticks 达 1000，可能是反弹高潮结束而非有第二段上涨的 BO；阶梯式上到 TR 高位，等待 bears 强反转或 tight bear channel，不立即买](../assets/evidence/video_050C/advanced_p1233.webp)

![Extreme ticks only first important：ticks 达 -1000 但已是 tick 新低的第三或第四次，可能是 sell climax 和 bear trend 结束；不立即卖，等待 bulls 强反转或 tight bull channel](../assets/evidence/video_050C/advanced_p1234.webp)

## 买入高潮和卖出高潮中的 tick 背离，必须结合新高新低与支撑阻力

`source: advanced p1236-p1239`

高潮阶段要寻找 tick 背离，但一个 tick 极端值 `1,000` 或 `-1,000` 通常不是走势结束。买入高潮中，若第一次 ticks 达到 `1,000`，或者随后出现下跌反转、或多头旗形突破，多头会买入；Emini 通常会创出新高，只要至少有 `1 point` 盈利，就在旧高处获利。这个做法不是在第一次强 tick 处做空，而是利用第一次强 tick 后通常还有新高的倾向。

在支撑阻力汇合处，高手有时会反向剥头皮。若 Emini 处在多个阻力位汇合处，并且新高处出现 tick 背离，而第一次 tick 极端值高于 `1,000`，高手剥头皮交易者有时会在新高处卖出。由于在强多头突破中做空很危险，这只适用于高手。执行方式包括在前高或高出 `1-2 points` 处卖出，在反转下跌处卖出，取 `1-2 point scalp`，并且常可保留一部分做波段。

卖出高潮后的逻辑对称。高潮中寻找 tick 背离，tick 极端 `1,000` 或 `-1,000` 通常不是走势结束。空头会在第一次 ticks 达到 `-1,000`、反转上行或空头旗形突破时做空；Emini 通常会创出新低，只要至少有 `1 point` 盈利，就在旧低处获利。若 Emini 处在多个支撑位汇合处，并且新低处出现 tick 背离，而第一次 tick 极端低于 `-1,000`，高手剥头皮交易者有时会在新低买入。由于在强空头突破中买入很危险，这也只适用于高手；买点包括前低或低出 `1-2 points`，以及反转上行处，目标为 `1-2 point scalp`，并常可保留部分仓位做波段。

![Tick divergence buy climax：高潮寻找 tick divergence；tick extreme 通常不是走势结束；多头买第一次 ticks 1000、reversal down 或 bull flag BO，Emini 通常新高，旧高至少 1 point 获利](../assets/evidence/video_050C/advanced_p1236.webp)

![Tick divergence buy climax bears sell：阻力汇合且新高 tick divergence，第一次 tick extreme 高于 1000 时，高手有时卖新高；仅高手，卖 prior high 或高 1-2 points、卖 reversal down，取 1-2 point scalp，可 swing part](../assets/evidence/video_050C/advanced_p1237.webp)

![Tick divergence after sell climax：卖出高潮后 tick divergence；空头卖第一次 ticks -1000、reversal up 或 bear flag BO，Emini 通常新低，旧低至少 1 point 获利](../assets/evidence/video_050C/advanced_p1238.webp)

![Tick divergence sell climax bulls buy：支撑汇合且新低 tick divergence，第一次 tick extreme 低于 -1000 时，高手有时买新低；仅高手，买 prior low 或低 1-2 points、买 reversal up，取 1-2 point scalp，可 swing part](../assets/evidence/video_050C/advanced_p1239.webp)

## tick 支撑和阻力可作为交易区间与趋势中的短线触发

`source: advanced p1240-p1242`

在空头趋势或交易区间中，当 ticks 回到前高位置时，交易者可以用市价单或收盘价卖出，目标为 `1-2 point scalp`，并且常可保留一部分仓位做波段。这是 `Tick Resistance: Sell`。在多头趋势或交易区间中，当 ticks 回到前低位置时，交易者可以用市价单或收盘价买入；若低位还有 tick 背离和楔形底部，则可能形成交易区间中的支撑。这个 `Tick Support: Buy` 不是孤立指标，而是要和价格是否在趋势、交易区间、楔形底部或支撑阻力汇合处一起判断。

当 ticks 大部分时间高于 `0` 时，多头突破概率增加。示例中市场是空头趋势中的交易区间，常规预期是趋势向下恢复，或者趋势反转向上。若 ticks 大部分时间高于 `0`，且多次读数达到 `700 or more`，说明市场内部广度偏强，多头突破机会增加。tick 支撑不是保证突破，而是对交易区间内方向概率的补充证据。

![Tick resistance sell：空头趋势或 TR 中，ticks 在前高时以 market 或 close 卖，取 1-2 point scalp，常可 swing part](../assets/evidence/video_050C/advanced_p1240.webp)

![Tick support buy：低位 tick divergence 与 wedge bottom，可能 TR；bull trend 或 TR 中，ticks 在前低时以 market 或 close 买；bear trend/TR 中前高 ticks 可卖](../assets/evidence/video_050C/advanced_p1241.webp)

![Tick support mostly above zero：空头趋势中的 TR，预期趋势恢复向下或趋势反转向上；ticks 大多高于 0 且多次 700+，多头突破概率增加](../assets/evidence/video_050C/advanced_p1242.webp)

## 本单元的可执行知识点索引

- `source: advanced p1227`：NYSE 约 `3,000 stocks`，当前交易高于/等于/低于上一笔分别给 tick `+1/0/-1`；`Ticks = 1,000` 表示上涨股比下跌股多 `1,000`，示例为 `600` 不变、`2,200` 上涨、`1,200` 下跌，计算 `0 + 2,200 - 1,200 = 1,000`。
- `source: advanced p1228-p1232`：横向到上行后空头突破，第一次 ticks 低于 `-700` 或 `-1,000` 通常不是趋势结束，可卖空头收盘、在更高位置加仓、卖 `1 point PB`；横向到下行后多头突破，第一次 ticks 高于 `700` 或 `1,000` 可买多头收盘、在更低位置加仓、买 `1 point PB`；做多做空的 1 点剥头皮风险常为 `3-4 points`，通常需移动 `5 ticks` 才能净赚 `4 ticks/1 point`。
- `source: advanced p1233-p1234`：若 ticks 在 `20 or more bars` 弱反弹后达到 `1,000`，可能是反弹高潮而非带第二段上涨的突破，需等待空头强反转或紧密空头通道；若 ticks 到 `-1,000` 已是第三或第四次 tick 新低，可能是卖出高潮和空头趋势结束，需等待多头强反转或紧密多头通道。
- `source: advanced p1236-p1239`：买入高潮中第一次 `1,000` 或后续多头旗形突破后，Emini 通常会新高；阻力汇合处新高 tick 背离且首次极端高于 `1,000` 时，高手可卖前高或高 `1-2 points`，取 `1-2 point scalp`，可留部分波段；卖出高潮对称，首次 `-1,000` 后通常仍会新低，支撑汇合处新低 tick 背离且首次极端低于 `-1,000` 时，高手可买前低或低 `1-2 points`。
- `source: advanced p1240-p1242`：空头趋势或交易区间中，ticks 到前高可用市价或收盘卖，目标 `1-2 points`，可留部分波段；多头趋势或交易区间中，ticks 到前低可用市价或收盘买；空头趋势中的交易区间若 ticks 大多高于 `0` 且多次读数 `700 or more`，多头突破概率增加。

