# M9I.2 Wave3 Holdout / Walk-forward Robustness Validation

- `run_id`: `m9_wave3_robustness_validation_20260422_081119`
- `provider`: `longbridge`
- `data_window`: `2025-04-01 ~ 2026-04-21`
- `common_session_count`: 265
- `strict_holdout_available`: false
- `tested_strategies`: SF-001, SF-002, SF-003, SF-004

## Triage Counts
- `insufficient_sample`: 1
- `modify_and_retest`: 3

## Strategy Snapshot

| Strategy | Triage | WF Windows | Proxy Trades | Strict Trades | Robustness Score | Reason |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| SF-001 | modify_and_retest | 4 | 1183 | 0 | 58 | strict post-freeze holdout is unavailable, so this frozen candidate cannot be promoted beyond modify_and_retest. |
| SF-002 | modify_and_retest | 4 | 156 | 0 | 27 | strict post-freeze holdout is unavailable, so this frozen candidate cannot be promoted beyond modify_and_retest. |
| SF-003 | modify_and_retest | 4 | 157 | 0 | 15 | strict post-freeze holdout is unavailable, so this frozen candidate cannot be promoted beyond modify_and_retest. |
| SF-004 | insufficient_sample | 4 | 22 | 0 | 44 | aggregate OOS closed trades stayed below 100, so Wave3 cannot support a stronger conclusion. |

## Notes
- 本轮只验证冻结后的 `v0.2-candidate`，未修改 specs，也未新增过滤器。
- 没有严格 post-freeze holdout 时，不允许输出 `retain_candidate`。
- `cash` 只是仓位 sizing 解释层，不能单独覆盖 `R` 口径的硬门槛结论。

