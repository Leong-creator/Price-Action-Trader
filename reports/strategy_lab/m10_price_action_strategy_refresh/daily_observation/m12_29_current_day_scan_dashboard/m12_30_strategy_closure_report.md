# M12.30 策略全量收口表

| 策略 | 最终状态 | 收益% | 胜率% | 最大回撤% | 说明 |
|---|---:|---:|---:|---:|---|
| M10-PA-001 Trend Pullback Second-Entry Continuation | 进入每日实时只读测试 | 24.7327 | 35.84 | 34.1783 | 核心顺势策略，历史资金测试完成，继续扫描 50 只。 |
| M10-PA-002 Breakout Follow-Through Continuation | 进入每日实时只读测试 | 3.2810 | 34.92 | 23.5592 | 突破后跟进策略，历史资金测试完成，也可作为 FTD 确认过滤器。 |
| M10-PA-003 Tight Channel Trend Continuation | 过滤器/排名因子 | -4.5359 | 33.91 | 16.0795 | 紧密通道更适合作为强趋势股票加分项，暂不作为独立买卖触发。 |
| M10-PA-004 Broad Channel Boundary Reversal | 观察队列：只做多版 | 0.5530 | 40.24 | 2.0479 | 整体混合版本弱，但做多分支转正；只做多观察，做空版暂不进入主线。 |
| M10-PA-005 Trading Range Failed Breakout Reversal | 研究项：定义仍弱 | -6.9222 | 33.33 |  | 交易区间失败突破复测仍弱，几何定义不能稳定改善，不拖主线。 |
| M10-PA-006 Trading Range BLSHS Limit-Order Framework | 研究项 |  |  |  | BLSHS 限价框架不是独立触发。 |
| M10-PA-007 Second-Leg Trap Reversal | 观察队列 | 0.6473 | 41.15 | 3.8796 | 第二腿陷阱小范围测试为正，先观察但不进模拟买卖准入。 |
| M10-PA-008 Major Trend Reversal | 观察队列 | 4.0036 | 35.41 | 9.2807 | 主要趋势反转有历史资金测试，但图形语境强，先严格观察。 |
| M10-PA-009 Wedge Reversal and Wedge Flag | 观察队列 | 1.0173 | 33.95 | 9.1580 | 楔形反转历史测试略正，先严格观察。 |
| M10-PA-010 Final Flag or Climax TBTL Reversal | 研究项 |  |  |  | Final Flag/Climax/TBTL 过于复合，不作为单独触发。 |
| M10-PA-011 Opening Reversal | 暂不进入主线 | -1.6268 | 28.81 | 3.8072 | 开盘反转历史资金测试偏弱，保留复核。 |
| M10-PA-012 Opening Range Breakout | 进入每日实时只读测试 | 26.8927 | 38.15 | 12.7415 | 开盘区间突破历史资金测试表现较好，继续 15m/5m。 |
| M10-PA-013 Support and Resistance Failed Test | 暂不进入主线 | -7.9392 | 32.55 | 12.8117 | 支撑阻力失败测试历史资金测试偏弱，暂不加入实时主线。 |
| M10-PA-014 Measured Move Target Engine | 辅助规则 |  |  |  | Measured Move 只作为目标/止盈模块。 |
| M10-PA-015 Protective Stops and Position Sizing | 辅助规则 |  |  |  | 止损与仓位模块，不是入场触发。 |
| M10-PA-016 Trading Range Scaling-In Research | 研究项 |  |  |  | 交易区间加仓研究不作为独立触发。 |
| M12-FTD-001 方方土日线趋势顺势信号K | 进入每日实时只读测试 | 610.44 | 37.36 | 48.38 | 早期强策略已改为 pullback_guard 版本，进入每日只读测试观察回撤。 |
| M12-SRC-001 日线趋势顺势信号K增强版 | 已合并到 M12-FTD-001 |  |  |  | 这是早期强策略的增强版，先放进每日观察，不直接批准模拟买卖。 |
| M12-SRC-002 趋势回调二次入场 | 已合并到 M10-PA-001 |  |  |  | 这是已通过历史资金测试的核心顺势策略。 |
| M12-SRC-003 突破后1-2根K线跟进 | 已合并到 M10-PA-002 |  |  |  | 它本身是核心策略，也能帮助判断强K线后有没有真实延续。 |
| M12-SRC-004 紧密通道/小回调顺势 | 已合并到 M10-PA-003 |  |  |  | 它更像帮我们从50只里挑更强的股票，不先单独统计盈利。 |
| M12-SRC-005 长回调保护 | 已合并到 M12-FTD-001-filter |  |  |  | 它的作用是减少长回调里的差机会，不是独立策略。 |
| M12-SRC-006 主要趋势反转观察 | 已合并到 M10-PA-008 |  |  |  | 反转机会更依赖图形语境，先观察典型机会，不和主线策略混测。 |
