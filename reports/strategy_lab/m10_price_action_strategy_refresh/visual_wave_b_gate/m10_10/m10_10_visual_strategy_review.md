# M10.10 Visual Wave B Gate Review

## 摘要

- 本阶段只复核 `M10-PA-003/004/007/008/009/010/011` 这 7 条强图形策略。
- `ready_for_wave_b_backtest` 只表示可进入后续模拟规格冻结和历史回测，不代表策略有效或盈利。
- M10.10 不启动回测、不接 broker、不批准 paper trading。

## Gate 结果

| Strategy | Decision | OHLCV Proxy | Timeframes | Note |
|---|---|---|---|---|
| M10-PA-003 | `ready_for_wave_b_backtest` | medium | 1h / 15m / 5m | 可进入 Wave B，但只能作为紧密通道的近似回测。 |
| M10-PA-004 | `needs_definition_fix` | low | - | 先补通道边界定义，不进入本轮 Wave B。 |
| M10-PA-007 | `needs_definition_fix` | low | - | 与失败突破类问题相似，需要先补结构字段。 |
| M10-PA-008 | `ready_for_wave_b_backtest` | medium | 1d / 1h / 15m / 5m | 可进入 Wave B，但必须保留趋势反转近似风险。 |
| M10-PA-009 | `ready_for_wave_b_backtest` | medium_low | 1d / 1h / 15m / 5m | 可进入 Wave B，结果必须标注 wedge 画线风险。 |
| M10-PA-010 | `visual_only_not_backtestable` | low | - | 先保留为 visual-only，不进入本轮自动回测。 |
| M10-PA-011 | `ready_for_wave_b_backtest` | medium | 15m / 5m | 可进入 Wave B，只跑 `15m / 5m`。 |

## Wave B Queue

- ready visual strategies: `M10-PA-003, M10-PA-008, M10-PA-009, M10-PA-011`
- plus existing Wave B candidate: `M10-PA-013`

## 后续规格要求

### M10-PA-003
- decision: `ready_for_wave_b_backtest`
- reason: tight channel can be approximated with consecutive directional closes, small pullbacks, and channel-break disqualifiers.
- spec requirements:
  - minimum consecutive channel bars
  - pullback depth cap
  - opposite follow-through disqualifier

### M10-PA-004
- decision: `needs_definition_fix`
- reason: broad channel boundary depends on drawn channel line quality and boundary tests that are not yet encoded.
- spec requirements:
  - channel boundary anchor persistence
  - boundary touch tolerance
  - strong breakout disqualifier

### M10-PA-007
- decision: `needs_definition_fix`
- reason: second-leg trap needs range edge, first leg, second leg, and trap confirmation fields before reliable backtest.
- spec requirements:
  - first-leg and second-leg labels
  - range edge or breakout edge
  - trap confirmation bar

### M10-PA-008
- decision: `ready_for_wave_b_backtest`
- reason: major trend reversal can be approximated with prior trend, trend break, test, and reversal confirmation.
- spec requirements:
  - prior trend strength
  - trend break confirmation
  - test or higher-low/lower-high structure

### M10-PA-009
- decision: `ready_for_wave_b_backtest`
- reason: wedge can be approximated by three pushes using swing pivots, but drawn wedge quality remains a review risk.
- spec requirements:
  - three-push pivot detector
  - push spacing bounds
  - failed wedge disqualifier

### M10-PA-010
- decision: `visual_only_not_backtestable`
- reason: final flag, climax, and TBTL combine multiple visual/context labels that cannot be safely reduced to one Wave B trigger yet.
- spec requirements:
  - separate final flag from climax
  - define exhaustion versus continuation
  - define TBTL measurement window

### M10-PA-011
- decision: `ready_for_wave_b_backtest`
- reason: opening reversal can be approximated with session open anchors, gap/opening context, and early reversal confirmation.
- spec requirements:
  - regular-session opening anchor
  - first 30-60 minute reversal window
  - trend-from-open disqualifier
