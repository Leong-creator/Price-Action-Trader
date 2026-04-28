# M12.19 图形检测器原型报告

## 用人话结论

- `M10-PA-004/007` 不再拖在“等图例确认”状态。
- 当前处理方式是：先做机器检测器原型，明确机器要识别什么图形，再决定以后是否值得回测。
- 本轮整理出 `10` 个检测器候选图例：`M10-PA-004` 5 个，`M10-PA-007` 5 个。
- 这些不是交易信号，也不输出盈利、胜率或回撤。

## 检测器规则

### M10-PA-004 宽通道边界反转检测器原型
- 机器要识别：宽通道、通道边界、触边、触边后反转确认、强突破失效条件
- 最少字段：swing_high_low_sequence、channel_width_proxy、boundary_touch_count、reversal_bar、breakout_follow_through
- 当前结论：detector_prototype_ready_not_backtest_ready
- 原因：Brooks 图例足够说明要检测什么，但仅靠当前 OHLCV 近似还不能稳定判断通道画线质量。

### M10-PA-007 第二腿陷阱反转检测器原型
- 机器要识别：第一腿、第二腿、陷阱点、反向失败点、反转确认K线
- 最少字段：leg1_extreme、leg2_extreme、trap_break_level、failure_close、reversal_bar
- 当前结论：detector_prototype_ready_not_backtest_ready
- 原因：Brooks 图例足够说明腿部和陷阱结构，但当前还缺稳定的腿部计数器和陷阱确认器。

