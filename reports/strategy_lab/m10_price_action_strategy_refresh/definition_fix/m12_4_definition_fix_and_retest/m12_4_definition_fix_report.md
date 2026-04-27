# M12.4 定义修正与复测报告

## 摘要

- 范围只覆盖 `M10-PA-005`、`M10-PA-004`、`M10-PA-007`。
- `M10-PA-005` 复用 M10.9 的结构性清理复测结果：移除重复确认，并对日内同方向触发加入 20-bar 冷却。
- `M10-PA-004/007` 本阶段只沉淀可执行字段缺口，不生成交易结果。
- 本阶段没有根据资金曲线、收益率、胜率或回撤调参。
- 仍然不接 broker、不接真实账户、不下单，也不批准 paper trading。

## M10-PA-005 Baseline 复测结果

| Timeframe | Trades Before | Trades After | Net Profit Before | Net Profit After | Return Before | Return After | Win Rate Before | Win Rate After | Max DD Before | Max DD After | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1d | 1481 | 1188 | -34130.96 | -22855.77 | -8.5327 | -5.7139 | 0.3201 | 0.3232 | 85559.02 | 65578.87 | completed_capital_test |
| 1h | 1469 | 950 | -613.09 | 4527.65 | -0.1533 | 1.1319 | 0.3302 | 0.3305 | 60231.57 | 36366.79 | needs_definition_fix |
| 15m | 7511 | 2966 | 50820.21 | 14707.57 | 12.7051 | 3.6769 | 0.3474 | 0.3422 | 113914.37 | 73311.91 | needs_definition_fix |
| 5m | 23881 | 8007 | -163742.05 | -107134.41 | -40.9355 | -26.7836 | 0.3397 | 0.3318 | 257549.22 | 134862.81 | needs_definition_fix |

结论：`M10-PA-005` 的噪音明显下降，但 `range_high/range_low/range_midpoint/breakout_extreme/reentry_confirmation_index` 仍未在上游 detector 中持久化，所以继续保持 `needs_definition_fix`。

## M10-PA-004/007 定义字段缺口

| Strategy | Visual Cases | Required Fields | Retest Status | Notes |
|---|---:|---|---|---|
| M10-PA-004 | 5 | channel boundary anchor persistence; boundary touch tolerance; strong breakout disqualifier | not_rerun_no_executable_definition_change | broad channel boundary depends on drawn channel line quality and boundary tests that are not yet encoded. |
| M10-PA-007 | 5 | first-leg and second-leg labels; range edge or breakout edge; trap confirmation bar | not_rerun_no_executable_definition_change | second-leg trap needs range edge, first leg, second leg, and trap confirmation fields before reliable backtest. |

## 后续处理

- `M10-PA-005`：下一轮要在 detector 层持久化交易区间几何字段，然后再复跑，不再只从交易行反推。
- `M10-PA-004`：先补通道边界 anchor、边界触碰容差、强突破排除字段，再判断是否能进入复测。
- `M10-PA-007`：先补第一腿、第二腿、陷阱确认 bar、区间或突破边界标签，再判断是否能进入复测。
