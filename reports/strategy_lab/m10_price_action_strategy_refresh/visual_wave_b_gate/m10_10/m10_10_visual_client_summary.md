# M10.10 Visual Strategy Client Summary

## 给甲方看的结论

- 可进入 Wave B 模拟测试的视觉策略：`M10-PA-003, M10-PA-008, M10-PA-009, M10-PA-011`。
- 暂不进入 Wave B 的视觉策略：`M10-PA-004, M10-PA-007, M10-PA-010`。
- Wave B 还会带上低视觉候选：`M10-PA-013`。
- 这一步只是决定能不能继续做模拟测试，不是策略批准。

## 策略状态

| Strategy | Status | Client Note |
|---|---|---|
| M10-PA-003 | `ready_for_wave_b_backtest` | 可进入 Wave B，但只能作为紧密通道的近似回测。 |
| M10-PA-004 | `needs_definition_fix` | 先补通道边界定义，不进入本轮 Wave B。 |
| M10-PA-007 | `needs_definition_fix` | 与失败突破类问题相似，需要先补结构字段。 |
| M10-PA-008 | `ready_for_wave_b_backtest` | 可进入 Wave B，但必须保留趋势反转近似风险。 |
| M10-PA-009 | `ready_for_wave_b_backtest` | 可进入 Wave B，结果必须标注 wedge 画线风险。 |
| M10-PA-010 | `visual_only_not_backtestable` | 先保留为 visual-only，不进入本轮自动回测。 |
| M10-PA-011 | `ready_for_wave_b_backtest` | 可进入 Wave B，只跑 `15m / 5m`。 |

## 下一步

进入 M10.11 后，只对本 queue 中的策略生成资金曲线测试；暂不进入 queue 的策略先补定义或保留为图形复核材料。