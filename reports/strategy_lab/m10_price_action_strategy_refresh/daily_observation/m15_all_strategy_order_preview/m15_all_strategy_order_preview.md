# 全策略长桥模拟账户订单预演

- 状态：`local_preview_created_for_all_strategy_orders`
- 看板日期：`2026-06-01`
- 行情来源：`longbridge_quote_readonly`
- 人话结论：已为 30 个交易运行单元做长桥模拟账户格式的本地订单预演，生成 275 条订单草稿，其中开仓 152 条、平仓 123 条；7 个辅助模块不单独生成订单。 按 6000 美元共享资金、整股、只做多规则筛选后，5 条草稿可在用户批准后进入模拟账户提交链路。 当前只写本地账本，不连接账户、不下单。

## 边界

- 只写本地订单草稿：是
- 连接长桥账户：否
- 读取凭证：否
- 提交订单：否
- 实盘执行：否
- 手动运行 M12.37：否
- 账户口径：6000 美元共享模拟资金
- 碎股：不做，数量向下取整，低于 1 股只保留草稿
- 做空/期权：不做，看空开仓只记录不提交
- 订单类型：允许普通限价单和突破触发限价单

## 汇总

- 交易运行单元：`30`
- 辅助模块：`7`
- 订单草稿：`275`
- 开仓草稿：`152`
- 平仓草稿：`123`
- 用户批准后可进入提交链路的草稿：`5`
- 这些草稿名义金额：`920.79`
- M13 对比一致：`275`
- M13 对比缺失或不一致：`0`

## 运行单元

| 运行单元 | 策略 | 状态 | 草稿数 | 开仓 | 平仓 | 本地记录状态 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| M10-PA-001-1d | M10-PA-001 | repair_now | 3 | 2 | 1 | 已生成本地订单草稿 |
| M10-PA-001-5m | M10-PA-001 | repair_now | 23 | 16 | 7 | 已生成本地订单草稿 |
| M10-PA-001-m14-modify-20260522-1d | M10-PA-001-m14-modify-20260522 | repair_now | 0 | 0 | 0 | 修复运行单元本次没有本地新订单 |
| M10-PA-002-1d | M10-PA-002 | risk_limited_advance | 2 | 0 | 2 | 已生成本地订单草稿 |
| M10-PA-002-5m | M10-PA-002 | repair_now | 53 | 28 | 25 | 已生成本地订单草稿 |
| M10-PA-002-m14-modify-20260522-1d | M10-PA-002-m14-modify-20260522 | repair_now | 0 | 0 | 0 | 修复运行单元本次没有本地新订单 |
| M10-PA-004-MBF-1d | M10-PA-004-MBF | risk_limited_advance | 12 | 5 | 7 | 已生成本地订单草稿 |
| M10-PA-004-MBF-QC-1d | M10-PA-004-MBF-QC | repair_now | 4 | 2 | 2 | 已生成本地订单草稿 |
| M10-PA-004-MBF-QC-m14-modify-20260522-1d | M10-PA-004-MBF-QC-m14-modify-20260522 | risk_limited_advance | 4 | 2 | 2 | 已生成本地订单草稿 |
| M10-PA-004-long-1d | M10-PA-004 | advance_internal_sim | 1 | 0 | 1 | 已生成本地订单草稿 |
| M10-PA-005-1d | M10-PA-005 | risk_limited_advance | 0 | 0 | 0 | 推进运行单元本次没有本地新订单 |
| M10-PA-005-5m | M10-PA-005 | risk_limited_advance | 55 | 30 | 25 | 已生成本地订单草稿 |
| M10-PA-007-1d | M10-PA-007 | repair_now | 3 | 2 | 1 | 已生成本地订单草稿 |
| M10-PA-007-m14-modify-20260522-1d | M10-PA-007-m14-modify-20260522 | repair_now | 1 | 1 | 0 | 已生成本地订单草稿 |
| M10-PA-008-1d | M10-PA-008 | risk_limited_advance | 1 | 0 | 1 | 已生成本地订单草稿 |
| M10-PA-008-broker-risk-cap-shadow-1d | M10-PA-008-broker-risk-cap-shadow | repair_now | 0 | 0 | 0 | 修复运行单元本次没有本地新订单 |
| M10-PA-009-1d | M10-PA-009 | repair_now | 0 | 0 | 0 | 修复运行单元本次没有本地新订单 |
| M10-PA-009-m14-modify-20260522-1d | M10-PA-009-m14-modify-20260522 | repair_now | 0 | 0 | 0 | 修复运行单元本次没有本地新订单 |
| M10-PA-011-5m | M10-PA-011 | repair_now | 7 | 4 | 3 | 已生成本地订单草稿 |
| M10-PA-011-ORB-R1-5m | M10-PA-011-ORB-R1 | repair_now | 7 | 4 | 3 | 已生成本地订单草稿 |
| M10-PA-012-5m | M10-PA-012 | risk_limited_advance | 0 | 0 | 0 | 推进运行单元本次没有本地新订单 |
| M10-PA-012-m14-modify-20260522-5m | M10-PA-012-m14-modify-20260522 | repair_now | 0 | 0 | 0 | 修复运行单元本次没有本地新订单 |
| M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow-5m | M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow | risk_limited_advance | 4 | 2 | 2 | 已生成本地订单草稿 |
| M10-PA-013-1d | M10-PA-013 | advance_internal_sim | 2 | 2 | 0 | 已生成本地订单草稿 |
| M10-PA-013-5m | M10-PA-013 | risk_limited_advance | 28 | 15 | 13 | 已生成本地订单草稿 |
| M10-PA-013-m14-modify-20260522-1d | M10-PA-013-m14-modify-20260522 | repair_now | 0 | 0 | 0 | 修复运行单元本次没有本地新订单 |
| M10-PA-013-m14-modify-20260522-5m | M10-PA-013-m14-modify-20260522 | repair_now | 45 | 24 | 21 | 已生成本地订单草稿 |
| M12-FTD-001-baseline-1d | M12-FTD-001 | repair_now | 7 | 5 | 2 | 已生成本地订单草稿 |
| M12-FTD-001-loss-streak-guard-1d | M12-FTD-001 | repair_now | 13 | 8 | 5 | 已生成本地订单草稿 |
| M12-FTD-001-m14-modify-20260522-1d | M12-FTD-001-m14-modify-20260522 | repair_now | 0 | 0 | 0 | 修复运行单元本次没有本地新订单 |

## 辅助模块

| 模块 | 用途 | 独立交易 |
| --- | --- | --- |
| AI-TRADER-EXTERNAL | 外部参考信号，只做对照，不复制交易，不覆盖本项目判断 | 否 |
| M10-PA-003 | 质量评分和排序模块，给主策略打分 | 否 |
| M10-PA-006 | 限价入场过滤模块，过滤差入场 | 否 |
| M10-PA-010 | 图形识别资料模块，帮助视觉策略补证据 | 否 |
| M10-PA-014 | 目标价计算模块，服务止盈目标 | 否 |
| M10-PA-015 | 止损和仓位模块，服务风控和数量计算 | 否 |
| M10-PA-016 | 区间加仓辅助模块，服务已有主策略 | 否 |

## 订单草稿样例

| 意图 | 运行单元 | 标的 | 方向 | 动作 | 档位 | 本地数量 | 整股数量 | 限价 | 风险 | 状态 |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 平仓 | M10-PA-001-1d | QQQ | 看涨 | sell | repair | 0.0031 | 0 | 739.1 | 0.00 | blocked_missing_order_fields |
| 开仓 | M10-PA-001-1d | TLT | 看跌 | sell_short | repair | 9.1152 | 9 | 84.88 | 9.72 | repair_runtime_order_preview_created_submit_blocked |
| 开仓 | M10-PA-001-1d | LQD | 看跌 | sell_short | repair | 7.1737 | 7 | 108.49 | 7.77 | repair_runtime_order_preview_created_submit_blocked |
| 平仓 | M10-PA-002-1d | XLV | 看涨 | sell | risk_limited | 98.4244 | 98 | 149.02 | 0.00 | local_order_preview_created_close_position_unmapped |
| 平仓 | M10-PA-004-long-1d | NOW | 看涨 | sell | primary | 5.8079 | 5 | 133.41 | 0.00 | local_order_preview_created_close_position_unmapped |
| 开仓 | M12-FTD-001-baseline-1d | XLU | 看跌 | sell_short | repair | 487.1356 | 487 | 43.81 | 73.05 | repair_runtime_order_preview_created_submit_blocked |
| 开仓 | M12-FTD-001-loss-streak-guard-1d | XLU | 看跌 | sell_short | repair | 461.0395 | 461 | 43.81 | 69.15 | repair_runtime_order_preview_created_submit_blocked |
| 平仓 | M10-PA-005-5m | XLU | 看涨 | sell | risk_limited | 45.0586 | 45 | 43.77 | 0.00 | local_order_preview_created_close_position_unmapped |
| 平仓 | M10-PA-005-5m | TSLA | 看跌 | buy_to_cover | risk_limited | 8.422 | 8 | 423.1 | 0.00 | local_order_preview_created_close_position_unmapped |
| 平仓 | M10-PA-007-1d | SLV | 看涨 | sell | repair | 6.9076 | 6 | 67.53 | 0.00 | repair_runtime_order_preview_created_submit_blocked |
| 开仓 | M10-PA-007-1d | TSLA | 看跌 | sell_short | repair | 0.7636 | 0 | 435.79 | 0.00 | blocked_missing_order_fields |
| 开仓 | M10-PA-007-1d | DIA | 看涨 | buy | repair | 0.5582 | 0 | 510.78 | 0.00 | blocked_missing_order_fields |
| 平仓 | M10-PA-004-MBF-1d | SNOW | 看涨 | sell | risk_limited | 6.1273 | 6 | 262.58 | 0.00 | local_order_preview_created_close_position_unmapped |
| 平仓 | M10-PA-004-MBF-1d | QCOM | 看涨 | sell | risk_limited | 7.4889 | 7 | 245.77 | 0.00 | local_order_preview_created_close_position_unmapped |
| 平仓 | M10-PA-004-MBF-1d | MU | 看涨 | sell | risk_limited | 1.9552 | 1 | 1013.6 | 0.00 | local_order_preview_created_close_position_unmapped |
| 开仓 | M10-PA-004-MBF-1d | SNOW | 看涨 | buy | risk_limited | 8.3247 | 0 | 263.72 | 0.00 | blocked_missing_order_fields |
| 开仓 | M10-PA-004-MBF-1d | NVDA | 看涨 | buy | risk_limited | 10.0293 | 1 | 218.84 | 5.47 | local_order_preview_created_ready_after_user_approval |
| 开仓 | M10-PA-004-MBF-1d | NOW | 看涨 | buy | risk_limited | 16.3761 | 1 | 134.18 | 3.35 | local_order_preview_created_ready_after_user_approval |
| 开仓 | M10-PA-004-MBF-1d | MU | 看涨 | buy | risk_limited | 2.1488 | 0 | 1021.22 | 0.00 | blocked_missing_order_fields |
| 开仓 | M10-PA-004-MBF-1d | CRM | 看涨 | buy | risk_limited | 5.1198 | 1 | 200.56 | 5.01 | local_order_preview_created_6000_account_size_blocked |
| 平仓 | M10-PA-004-MBF-QC-1d | MSFT | 看涨 | sell | repair | 0.837 | 0 | 461.04 | 0.00 | blocked_missing_order_fields |
| 开仓 | M10-PA-004-MBF-QC-1d | NOW | 看涨 | buy | repair | 3.206 | 3 | 134.18 | 10.05 | repair_runtime_order_preview_created_submit_blocked |
| 开仓 | M10-PA-004-MBF-QC-1d | CRM | 看涨 | buy | repair | 2.1437 | 2 | 200.56 | 10.02 | repair_runtime_order_preview_created_submit_blocked |
| 开仓 | M10-PA-013-1d | LQD | 看跌 | sell_short | standard | 47.9905 | 5 | 108.55 | 5.25 | local_order_preview_created_short_disabled |
| 开仓 | M10-PA-013-1d | EFA | 看跌 | sell_short | standard | 32.9346 | 5 | 103.99 | 7.65 | local_order_preview_created_short_disabled |
| 平仓 | M10-PA-013-5m | XLU | 看涨 | sell | risk_limited | 466.5703 | 466 | 43.77 | 0.00 | local_order_preview_created_close_position_unmapped |
| 平仓 | M10-PA-004-MBF-QC-m14-modify-20260522-1d | MSFT | 看涨 | sell | risk_limited | 8.7184 | 8 | 461.04 | 0.00 | local_order_preview_created_close_position_unmapped |
| 开仓 | M10-PA-004-MBF-QC-m14-modify-20260522-1d | NOW | 看涨 | buy | risk_limited | 29.9343 | 1 | 134.18 | 3.35 | local_order_preview_created_ready_after_user_approval |
| 开仓 | M10-PA-004-MBF-QC-m14-modify-20260522-1d | CRM | 看涨 | buy | risk_limited | 20.016 | 1 | 200.56 | 5.01 | local_order_preview_created_ready_after_user_approval |
| 开仓 | M10-PA-007-m14-modify-20260522-1d | DIA | 看涨 | buy | repair | 5.4675 | 5 | 510.78 | 91.45 | repair_runtime_order_preview_created_submit_blocked |
| 平仓 | M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow-5m | DIA | 看涨 | sell | risk_limited | 39.2599 | 39 | 509.43 | 0.00 | local_order_preview_created_close_position_unmapped |
| 平仓 | M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow-5m | XLF | 看涨 | sell | risk_limited | 0.0006 | 0 | 51.25 | 0.00 | blocked_missing_order_fields |
| 平仓 | M10-PA-013-m14-modify-20260522-5m | XLU | 看涨 | sell | repair | 450.8566 | 450 | 43.77 | 0.00 | repair_runtime_order_preview_created_submit_blocked |
| 平仓 | M10-PA-004-MBF-1d | AMD | 看涨 | sell | risk_limited | 3.6917 | 3 | 498.55 | 0.00 | local_order_preview_created_close_position_unmapped |
| 平仓 | M10-PA-008-1d | ADBE | 看跌 | buy_to_cover | risk_limited | 5.2469 | 5 | 265.09 | 0.00 | local_order_preview_created_close_position_unmapped |
| 平仓 | M10-PA-004-MBF-1d | SNOW | 看涨 | sell | risk_limited | 8.3247 | 8 | 276.91 | 0.00 | local_order_preview_created_close_position_unmapped |
| 平仓 | M10-PA-004-MBF-QC-1d | CRM | 看涨 | sell | repair | 2.1437 | 2 | 208.08 | 0.00 | repair_runtime_order_preview_created_submit_blocked |
| 平仓 | M10-PA-004-MBF-QC-m14-modify-20260522-1d | CRM | 看涨 | sell | risk_limited | 20.016 | 20 | 208.08 | 0.00 | local_order_preview_created_close_position_unmapped |
| 开仓 | M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow-5m | DIA | 看涨 | buy | risk_limited | 39.183 | 0 | 510.44 | 0.00 | blocked_missing_order_fields |
| 开仓 | M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow-5m | XLK | 看涨 | buy | risk_limited | 0.0001 | 0 | 194.08 | 0.00 | blocked_missing_order_fields |
| 平仓 | M10-PA-004-MBF-1d | CRM | 看涨 | sell | risk_limited | 5.1198 | 5 | 210.59 | 0.00 | local_order_preview_created_close_position_unmapped |
| 开仓 | M10-PA-002-5m | QQQ | 看涨 | buy | repair | 26.657 | 26 | 740.4 | 7.28 | repair_runtime_order_preview_created_submit_blocked |
| 开仓 | M10-PA-002-5m | TQQQ | 看涨 | buy | repair | 0.0002 | 0 | 85.27 | 0.00 | blocked_missing_order_fields |
| 平仓 | M12-FTD-001-baseline-1d | XLU | 看跌 | buy_to_cover | repair | 487.1356 | 487 | 43.5 | 0.00 | repair_runtime_order_preview_created_submit_blocked |
| 开仓 | M12-FTD-001-baseline-1d | IWM | 看跌 | sell_short | repair | 74.6628 | 74 | 287.86 | 39.96 | repair_runtime_order_preview_created_submit_blocked |
| 平仓 | M12-FTD-001-loss-streak-guard-1d | XLU | 看跌 | buy_to_cover | repair | 461.0395 | 461 | 43.5 | 0.00 | repair_runtime_order_preview_created_submit_blocked |
| 开仓 | M12-FTD-001-loss-streak-guard-1d | IWM | 看跌 | sell_short | repair | 70.663 | 70 | 287.86 | 37.80 | repair_runtime_order_preview_created_submit_blocked |
| 开仓 | M12-FTD-001-loss-streak-guard-1d | XLY | 看跌 | sell_short | repair | 0.0001 | 0 | 119.02 | 0.00 | blocked_missing_order_fields |
| 平仓 | M10-PA-002-5m | QQQ | 看涨 | sell | repair | 26.657 | 26 | 740.98 | 0.00 | repair_runtime_order_preview_created_submit_blocked |
| 平仓 | M10-PA-002-5m | TQQQ | 看涨 | sell | repair | 0.0002 | 0 | 85.47 | 0.00 | blocked_missing_order_fields |
