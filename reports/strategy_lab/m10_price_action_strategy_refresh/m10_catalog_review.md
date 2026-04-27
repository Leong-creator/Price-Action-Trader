# M10.1 Catalog Review and Test Queue

## 摘要

- 当前 clean-room catalog 冻结为 `16` 条 `M10-PA-*` 策略/规则条目。
- M10.1 不启动大规模回测；本阶段只完成目录复审、来源复核、测试分流和后续阶段承接。
- Visual golden case 不是所有策略的统一前置门槛，只适用于强图形依赖策略。
- Brooks-only / YouTube-only 不因缺少交叉验证而自动拒绝；notes-only 必须降级。
- 旧 `PA-SC-*` / `SF-*` 仅用于 comparison artifact，不作为 M10 clean-room catalog 来源。

## 策略复审表

| ID | 策略 | 来源 | M10.1 分流 | source refs | 复审结论 |
|---|---|---|---|---:|---|
| M10-PA-001 | Trend Pullback Second-Entry Continuation | Brooks v2 + YouTube + notes | Backtest Wave A | 7 | freeze_for_wave_a_spec_work |
| M10-PA-002 | Breakout Follow-Through Continuation | Brooks v2 + YouTube + notes | Backtest Wave A | 7 | freeze_for_wave_a_spec_work |
| M10-PA-003 | Tight Channel Trend Continuation | Brooks v2 + YouTube + notes | Visual golden case first | 7 | freeze_with_visual_golden_case_gate |
| M10-PA-004 | Broad Channel Boundary Reversal | Brooks v2 + YouTube + notes | Visual golden case first | 7 | freeze_with_visual_golden_case_gate |
| M10-PA-005 | Trading Range Failed Breakout Reversal | Brooks v2 + notes | Backtest Wave A | 5 | freeze_for_wave_a_spec_work |
| M10-PA-006 | Trading Range BLSHS Limit-Order Framework | Brooks v2 + YouTube + notes | Research only | 7 | freeze_as_research_only |
| M10-PA-007 | Second-Leg Trap Reversal | Brooks v2 + YouTube + notes | Visual golden case first | 7 | freeze_with_visual_golden_case_gate |
| M10-PA-008 | Major Trend Reversal | Brooks v2 + YouTube + notes | Visual golden case first | 7 | freeze_with_visual_golden_case_gate |
| M10-PA-009 | Wedge Reversal and Wedge Flag | Brooks v2 + YouTube + notes | Visual golden case first | 7 | freeze_with_visual_golden_case_gate |
| M10-PA-010 | Final Flag or Climax TBTL Reversal | Brooks v2 + YouTube + notes | Visual golden case first | 6 | freeze_with_visual_golden_case_gate |
| M10-PA-011 | Opening Reversal | Brooks v2 + YouTube + notes | Visual golden case first | 6 | freeze_with_visual_golden_case_gate |
| M10-PA-012 | Opening Range Breakout | Brooks v2 | Backtest Wave A | 3 | freeze_for_wave_a_spec_work |
| M10-PA-013 | Support and Resistance Failed Test | Brooks v2 | Backtest Wave B candidate | 3 | freeze_as_wave_b_candidate |
| M10-PA-014 | Measured Move Target Engine | Brooks v2 | Supporting rule | 3 | freeze_as_attached_supporting_rule_no_standalone_trigger |
| M10-PA-015 | Protective Stops and Position Sizing | Brooks v2 + YouTube + notes | Supporting rule | 7 | freeze_as_attached_supporting_rule_no_standalone_trigger |
| M10-PA-016 | Trading Range Scaling-In Research | Brooks v2 + YouTube + notes | Research only | 7 | freeze_as_research_only |

## 测试分流

- `backtest_wave_a`: M10-PA-001, M10-PA-002, M10-PA-005, M10-PA-012
- `backtest_wave_b_candidate`: M10-PA-013
- `visual_golden_case_first`: M10-PA-003, M10-PA-004, M10-PA-007, M10-PA-008, M10-PA-009, M10-PA-010, M10-PA-011
- `supporting_rule`: M10-PA-014, M10-PA-015
- `research_only`: M10-PA-006, M10-PA-016

## Visual Golden Case 规则

- Visual golden case 是图例审查，不是所有策略的前置门槛。
- 需要先过 visual golden case 的策略必须准备 `3` 个 Brooks v2 正例、`1` 个反例、`1` 个边界例。
- 每个案例必须包含 evidence image/source ref、图形判定要点和 OHLCV 近似风险说明。
- 未通过 visual review 的策略不得把历史回测结果解释为有效策略，只能保留为 research / visual-review-only。

## Historical Backtest Wave A

- `M10-PA-001`: `1d / 1h / 15m / 5m`
- `M10-PA-002`: `1d / 1h / 15m / 5m`
- `M10-PA-005`: `1d / 1h / 15m / 5m`
- `M10-PA-012`: `15m / 5m`
- 每条必须输出 candidate events、skip/no-trade ledger、source ledger、成本/滑点敏感性、per-symbol、per-regime、failure-mode notes。
- 本阶段不输出 `retain/promote`；只允许 `needs_definition_fix / needs_visual_review / continue_testing / reject_for_now`。

## Supporting Rules

- `M10-PA-014` 只作为目标/止盈模块。
- `M10-PA-015` 只作为止损/仓位/实际风险模块。
- 两者不得生成独立 entry trigger。

## 后续阶段铺垫

- `M10.2` Visual Golden Case Pack: 为高视觉策略建立 Brooks v2 正例、反例、边界例和人工复核记录。
- `M10.3` Backtest Spec Freeze: 为 Wave A 策略冻结事件识别、skip 规则、成本、样本门槛和失败标准。
- `M10.4` Historical Backtest Pilot: 只跑 Wave A 小范围 pilot，验证事件识别、ledger 和成本敏感性，不证明盈利。
- `M10.5` Read-only Observation Plan: pilot 合格后才设计实时只读观察；仍不接 broker、不下单。
- `M11` Paper Trading Candidate Gate: historical pilot、visual review、实时只读观察达标后才讨论 paper trading。

## 边界

- M10 继续保持 `paper / simulated`。
- 不接真实 broker，不接真实账户，不进入 live execution，不自动下单。
