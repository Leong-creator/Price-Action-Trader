# M10.3 Backtest Spec Freeze Summary

## 摘要

- 本阶段只冻结 Wave A 可执行回测规格，不运行 historical backtest。
- 覆盖 `M10-PA-001/002/005/012`；不把 visual-first、supporting、research-only 条目放入 Wave A spec。
- 所有 spec 保持 `paper / simulated`，不接 broker、不接真实账户、不下单。
- 本阶段不得输出 `retain/promote`、收益判断或实盘能力结论。

## Wave A Spec Index

| ID | timeframes | spec | allowed outcomes |
|---|---|---|---|
| M10-PA-001 | `1d / 1h / 15m / 5m` | `backtest_specs/M10-PA-001.md` | `needs_definition_fix, needs_visual_review, continue_testing, reject_for_now` |
| M10-PA-002 | `1d / 1h / 15m / 5m` | `backtest_specs/M10-PA-002.md` | `needs_definition_fix, needs_visual_review, continue_testing, reject_for_now` |
| M10-PA-005 | `1d / 1h / 15m / 5m` | `backtest_specs/M10-PA-005.md` | `needs_definition_fix, needs_visual_review, continue_testing, reject_for_now` |
| M10-PA-012 | `15m / 5m` | `backtest_specs/M10-PA-012.md` | `needs_definition_fix, needs_visual_review, continue_testing, reject_for_now` |

## Cost Sensitivity Policy

- `baseline`: slippage `1 bps`, fee_per_order `0`
- `stress_low`: slippage `2 bps`, fee_per_order `0`
- `stress_high`: slippage `5 bps`, fee_per_order `0`

## Sample Gate

- 每个 strategy/timeframe 至少 `30` 个 candidate events。
- skip 后至少 `10` 个 executed trades。
- 低于样本门槛只能标记 `continue_testing` 或 `needs_definition_fix`。
- 样本门槛只允许解释测试质量，不允许宣称盈利稳定性。

## M10.4 Handoff

- 下一阶段只允许做 Historical Backtest Pilot。
- Pilot 必须输出 candidate events、skip/no-trade ledger、source ledger、成本/滑点敏感性、per-symbol、per-regime 与 failure-mode notes。
- Pilot 结果仍只能进入 `needs_definition_fix / needs_visual_review / continue_testing / reject_for_now`。
