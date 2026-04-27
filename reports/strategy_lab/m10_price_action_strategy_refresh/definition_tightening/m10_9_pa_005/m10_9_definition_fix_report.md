# M10.9 定义修正报告

## 摘要

- 范围：只处理 `M10-PA-005`。
- 规则：先移除重复确认事件，再对 `1h / 15m / 5m` 的同标的同方向触发施加 20-bar 冷却。
- 依据：只做结构性清理；没有任何过滤条件使用 PnL、资金曲线、胜率或 profit factor。
- 结果：触发密度下降，但定义尚未解除复核，因为 M10.4 没有持久化 range geometry 字段。

## 过滤账本

| Timeframe | Before | After Dedupe | After Tightening | Removed | Cooldown Removed | Status |
|---|---:|---:|---:|---:|---:|---|
| 1d | 1481 | 1188 | 1188 | 293 | 0 | daily_duplicate_cleanup_only |
| 1h | 1469 | 1233 | 950 | 519 | 283 | definition_breadth_reduced_not_cleared |
| 15m | 7511 | 6289 | 2966 | 4545 | 3323 | definition_breadth_reduced_not_cleared |
| 5m | 23881 | 19740 | 8007 | 15874 | 11733 | definition_breadth_reduced_not_cleared |

## Baseline 复测指标

| Timeframe | Before Trades | After Trades | Before Net Profit | After Net Profit | Before Win Rate | After Win Rate | Before Max DD | After Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1d | 1481 | 1188 | -34130.96 | -22855.77 | 0.3201 | 0.3232 | 85559.02 | 65578.87 |
| 1h | 1469 | 950 | -613.09 | 4527.65 | 0.3302 | 0.3305 | 60231.57 | 36366.79 |
| 15m | 7511 | 2966 | 50820.21 | 14707.57 | 0.3474 | 0.3422 | 113914.37 | 73311.91 |
| 5m | 23881 | 8007 | -163742.05 | -107134.41 | 0.3397 | 0.3318 | 257549.22 | 134862.81 |

## 上游缺口

- 当前 candidate events 不包含 `range_high`、`range_low`、`range_midpoint`、`breakout_extreme` 或 `reentry_confirmation_index`。
- 因为这些字段缺失，本阶段不能诚实地声称 Brooks 交易区间定义已经完全修好。
- `M10-PA-005` 继续保持 `needs_definition_fix`；本次复测只作为清理后的对照，不作为升级决策。

## 边界

本阶段只是历史模拟复测。不接 broker，不接真实账户，不启用自动执行，不批准 paper trading，也不开放真实订单路径。
