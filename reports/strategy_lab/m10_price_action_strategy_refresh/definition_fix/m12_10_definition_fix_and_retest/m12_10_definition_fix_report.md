# M12.10 Definition Fix and Retest Report

## 摘要

- 范围只覆盖 `M10-PA-005 / M10-PA-004 / M10-PA-007`。
- `M10-PA-005` 已重新从本地 OHLCV 计算并落盘交易区间几何字段：range high/low/height、breakout edge、re-entry close、failed breakout extreme。
- `M10-PA-005` geometry ledger 现在按 distinct failed-breakout geometry candidate 生成唯一 `event_id`，不会把同一 signal 下的不同 breakout geometry 混成同一记录。
- `M10-PA-004 / M10-PA-007` 仍无法在无人工通道/腿部标签的情况下稳定量化，本阶段正式降级为 visual-only / manual-labeling，不生成假回测。
- `M10-PA-008 / M10-PA-009` 的图例仍未被用户确认，继续不得计入 paper gate evidence。
- 本阶段不接 broker、不接账户、不下单，也不批准 paper trading。

- `M10-PA-005` geometry event count: `34651`
- `M10-PA-005` geometry deferred count: `0`

## M10-PA-005 复测口径

| Timeframe | Before Trades | After Trades | After Net Profit | After Return % | After Win Rate | After Max DD | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| 1d | 1481 | 1188 | -22855.77 | -5.7139 | 0.3232 | 65578.87 | `reject_for_now_after_geometry_review` |
| 1h | 1469 | 950 | 4527.65 | 1.1319 | 0.3305 | 36366.79 | `reject_for_now_after_geometry_review` |
| 15m | 7511 | 2966 | 14707.57 | 3.6769 | 0.3422 | 73311.91 | `reject_for_now_after_geometry_review` |
| 5m | 23881 | 8007 | -107134.41 | -26.7836 | 0.3318 | 134862.81 | `reject_for_now_after_geometry_review` |

## M10-PA-004 / M10-PA-007 降级结论

| Strategy | Decision | Reason |
|---|---|---|
| M10-PA-004 | `visual_only_not_backtestable_without_manual_labels` | Visual case evidence exists, but required geometry labels are not executable from OHLCV without a new detector or manual labeling. |
| M10-PA-007 | `visual_only_not_backtestable_without_manual_labels` | Visual case evidence exists, but required geometry labels are not executable from OHLCV without a new detector or manual labeling. |

## 甲方可读结论

`M10-PA-005` 已补齐结构字段，但历史复测仍不足以进入自动观察或 paper gate；当前结论是 `reject_for_now_after_geometry_review`。`M10-PA-004/007` 不再悬空等待自动回测，正式降级为需要人工标签或新检测器后再讨论。
