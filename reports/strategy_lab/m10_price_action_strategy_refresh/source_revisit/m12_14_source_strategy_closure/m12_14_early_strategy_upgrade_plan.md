# M12.14 早期日线策略多来源升级计划

## 直接结论

- 早期日线策略不能再只叫 benchmark；它已经升级为 `M12-FTD-001` 的重点正式候选。
- 当前历史模拟：收益 `745.13%`，盈利 `745131.37`，胜率 `36.74%`，最大回撤 `49.04%`，交易 `41030` 笔。
- 现在要做的不是盲目调参数，而是按来源补强定义，再做 A/B 重测，重点看最大回撤能否下降。

## 要补强的定义

### 行情背景

- 当前问题：旧版只说日线明显上涨或下跌，太粗，容易把震荡里的强K线也当成机会。
- 新定义：先把行情分成突破、紧密通道、宽通道、震荡区间、过渡期；只有趋势背景足够清楚时才允许顺势信号K进入测试。
- 测试看点：预期减少震荡里的误触发，重点观察回撤是否下降。
- 来源：
  - `wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md`
  - `wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md`
  - `raw:knowledge/raw/youtube/fangfangtu/transcripts/Price_Action方方土.pdf`
  - `raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_012A_market_cycle_four_parts_pullback_channel_trading_range.md`
  - `raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_014E_trends_tight_channel_small_pullback.md`

### 信号K质量

- 当前问题：旧版只要求顺势强K线，没有拆实体、收盘位置、影线和背景是否配合。
- 新定义：拆成实体强度、收盘位置、影线比例、是否与背景同向、下一根是否跟进；弱信号K只能观察，不能作为正式触发。
- 测试看点：预期过滤差K线，候选数会下降，胜率和回撤要重新看。
- 来源：
  - `wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md`
  - `raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf`
  - `raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_008A_candles_setups_signal_bars_trend_tr_entry_bad_signal.md`
  - `raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_015D_breakouts_second_leg_traps_strong_breakouts.md`

### 更高周期一致性

- 当前问题：旧版没有判断更高周期，可能在日线看起来强，但周线其实处于区间上沿。
- 新定义：日线信号优先要求更高周期不处于明显阻力边缘；若更高周期是震荡区间边缘，则信号降级为观察。
- 测试看点：预期减少高位追涨和低位追空。
- 来源：
  - `wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md`
  - `raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_009C_pullbacks_endless_higher_lower_timeframes_countertrend_exit.md`
  - `raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_012A_market_cycle_four_parts_pullback_channel_trading_range.md`

### 长回调保护

- 当前问题：旧版把趋势中的所有顺势信号都近似看待，没有区分普通回调和已经拖太久的回调。
- 新定义：如果回调已经持续约20根K线以上，不再按普通趋势恢复处理，必须重新评估是否已经进入区间或反转。
- 测试看点：这是降低大回撤的第一优先过滤器。
- 来源：
  - `raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_009C_pullbacks_endless_higher_lower_timeframes_countertrend_exit.md`
  - `raw:knowledge/raw/notes/方方土视频笔记 - 回调&数K线.pdf`
  - `wiki:knowledge/wiki/sources/fangfangtu-pullback-counting-bars-note.md`

### 入场确认

- 当前问题：旧版只看突破信号K高低点，容易把第二天无跟进的假信号也纳入。
- 新定义：区分突破信号K入场和下一根K线收盘确认；若突破后1-2根K线没有跟进，取消或降级。
- 测试看点：这是把高收益策略变得更稳的第二优先过滤器。
- 来源：
  - `wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md`
  - `raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_015B_breakouts_follow_through_reversal_small_start.md`
  - `raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_015D_breakouts_second_leg_traps_strong_breakouts.md`

### 止损和目标

- 当前问题：旧版固定信号K另一端止损、2R目标，解释力不够。
- 新定义：保留信号K止损，同时记录波段止损、实际风险止损、前高前低、测量目标，回测输出多目标对比。
- 测试看点：不是为了调参，而是为了知道收益来自哪里、回撤由什么造成。
- 来源：
  - `raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_020A_measured_moves_leg1_equals_leg2_prior_leg.md`
  - `raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_034A_actual_risk_traders_equation_profit_targets.md`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/source_ledgers/M10-PA-014.json`
  - `reports/strategy_lab/m10_price_action_strategy_refresh/source_ledgers/M10-PA-015.json`

## 下一次测试怎么跑

- 对照组：M12.12 简化版。
- 测试组 1：只加长回调保护。
- 测试组 2：只加 1-2 根K线跟进确认。
- 测试组 3：加行情背景分类 + 信号K质量。
- 测试组 4：完整多来源增强版。
- 成功标准：不是收益更高就算赢，而是收益、最大回撤、连续亏损、分标的稳定性一起看。
