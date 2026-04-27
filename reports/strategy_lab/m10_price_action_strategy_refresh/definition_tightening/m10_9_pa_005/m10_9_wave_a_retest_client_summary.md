# M10.9 Wave A 复测客户摘要

## 本次改了什么

`M10-PA-005` 在日内数据上触发过密。本次复测移除重复触发，并限制同一个 20-bar 窗口内反复出现的同方向失败突破触发。

## 给甲方看的结果

| Timeframe | Trades Before | Trades After | Net Profit Before | Net Profit After | Win Rate Before | Win Rate After | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| 1d | 1481 | 1188 | -34130.96 | -22855.77 | 0.3201 | 0.3232 | daily_reference_only |
| 1h | 1469 | 950 | -613.09 | 4527.65 | 0.3302 | 0.3305 | keep_in_definition_review |
| 15m | 7511 | 2966 | 50820.21 | 14707.57 | 0.3474 | 0.3422 | keep_in_definition_review |
| 5m | 23881 | 8007 | -163742.05 | -107134.41 | 0.3397 | 0.3318 | keep_in_definition_review |

## 结论

本次清理让测试噪音下降，尤其是 `5m` 和 `15m`。但这个策略还不能解除定义复核。下一步真正要修的是让 detector 记录实际交易区间边界、中点、突破极值和重新回到区间内的确认 bar，这样才能从策略结构本身审计，而不是只从交易结果行反推。
