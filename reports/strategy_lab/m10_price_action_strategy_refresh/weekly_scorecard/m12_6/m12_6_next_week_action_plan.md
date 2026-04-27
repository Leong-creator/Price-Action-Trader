# M12.6 Next Week Action Plan

## 1. 每日只读观察

- 继续跟踪 Tier A：`M10-PA-001 / M10-PA-002 / M10-PA-012`。
- 当前 M12.2 观察记录为 32 条，完整候选为 0 条；下一周重点是积累真实 bar-close 观察窗口。

## 2. Scanner 覆盖扩展

- 当前股票池 147 只，只有 4 只有本地缓存。
- 下一步优先补齐 universe seed 的只读 K 线缓存或受控读取计划，再扩大日扫覆盖。

## 3. 图形复核

- 优先复核：M10-PA-008, M10-PA-009。
- 复核目标是确认 Brooks v2 图例语境是否能转成可执行定义，不替代人工判断。

## 4. 定义修正

- 继续处理：M10-PA-004, M10-PA-005, M10-PA-007。
- `M10-PA-005` 需要 range geometry 字段；`M10-PA-004/007` 需要边界、腿部和陷阱确认字段。

## 5. M11.5 承接

- 只有在周报输入完整、图形复核和定义 blocker 有明确状态后，才进入 M11.5 gate recheck。
- M11.5 仍只做 gate 复查，不批准交易。

## Tier A 本周状态

| Strategy | Observation | Scanner | Next |
|---|---:|---:|---|
| M10-PA-001 | 12 | 6 | carry_scanner_candidates_into_weekly_review |
| M10-PA-002 | 12 | 0 | keep_bar_close_observation_running |
| M10-PA-012 | 8 | 6 | carry_scanner_candidates_into_weekly_review |
