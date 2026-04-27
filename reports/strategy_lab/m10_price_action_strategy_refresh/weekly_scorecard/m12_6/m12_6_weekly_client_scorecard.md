# M12.6 Weekly Client Scorecard

## 本周总览

- 策略总数：16 条。
- 历史资金测试状态：{"completed_capital_test": 8, "needs_definition_fix": 3, "research_only": 2, "supporting_rule": 2, "visual_only_not_backtestable": 1}。
- 每日只读观察：32 条记录，0 条完整候选，32 条 skip/no-trade。
- 选股扫描：股票池 147 只，本地缓存实际扫描 4 只，候选 12 条，deferred 143 只。
- 图形预审：30 个 Brooks v2 图例 case，仍待人工复核。
- 当前交易状态：`closed_not_authorized`。

## 策略 Dashboard

| Strategy | 状态 | 历史收益 | 胜率 | 最大回撤 | 本周观察 | Scanner | 下周动作 |
|---|---|---:|---:|---:|---:|---:|---|
| M10-PA-001 | continue_read_only_observation | 24.73% | 35.84% | 34.18% | 12 | 6 | carry_scanner_candidates_into_weekly_review |
| M10-PA-002 | continue_read_only_observation | 3.28% | 34.92% | 23.56% | 12 | 0 | keep_bar_close_observation_running |
| M10-PA-003 | watchlist_after_priority_cases | -4.54% | 33.91% | 16.08% | 0 | 0 | review_after_tier_a_and_priority_visual_cases |
| M10-PA-004 | definition_fix_required | - | - | - | 0 | 0 | finish_definition_fields_before_retest |
| M10-PA-005 | definition_fix_required | -6.92% | 33.33% | - | 0 | 0 | finish_definition_fields_before_retest |
| M10-PA-006 | not_independent_trigger | - | - | - | 0 | 0 | keep_as_supporting_or_research |
| M10-PA-007 | definition_fix_required | - | - | - | 0 | 0 | finish_definition_fields_before_retest |
| M10-PA-008 | manual_visual_review_required | 4.00% | 35.41% | 9.28% | 0 | 0 | user_review_priority_visual_cases |
| M10-PA-009 | manual_visual_review_required | 1.02% | 33.95% | 9.16% | 0 | 0 | user_review_priority_visual_cases |
| M10-PA-010 | not_current_week_focus | - | - | - | 0 | 0 | keep_in_backlog |
| M10-PA-011 | watchlist_after_priority_cases | -1.63% | 28.81% | 3.81% | 0 | 0 | review_after_tier_a_and_priority_visual_cases |
| M10-PA-012 | continue_read_only_observation | 26.89% | 38.15% | 12.74% | 8 | 6 | carry_scanner_candidates_into_weekly_review |
| M10-PA-013 | not_current_week_focus | -7.94% | 32.55% | 12.81% | 0 | 0 | keep_in_backlog |
| M10-PA-014 | not_independent_trigger | - | - | - | 0 | 0 | keep_as_supporting_or_research |
| M10-PA-015 | not_independent_trigger | - | - | - | 0 | 0 | keep_as_supporting_or_research |
| M10-PA-016 | not_independent_trigger | - | - | - | 0 | 0 | keep_as_supporting_or_research |

## Scanner 候选

| Symbol | Strategy | Timeframe | Status | Direction | Entry | Stop | Target | Risk |
|---|---|---|---|---|---:|---:|---:|---|
| NVDA | M10-PA-012 | 15m | trigger_candidate | short | 200.7200 | 202.7500 | 198.8100 | medium |
| NVDA | M10-PA-012 | 5m | trigger_candidate | short | 200.7200 | 202.7500 | 198.8100 | medium |
| QQQ | M10-PA-001 | 1d | watch_candidate | short | 642.2100 | 650.0000 | 626.6300 | medium |
| QQQ | M10-PA-012 | 5m | trigger_candidate | long | 651.1400 | 648.5200 | 653.0200 | low |
| SPY | M10-PA-001 | 15m | watch_candidate | short | 709.2900 | 710.7000 | 706.4700 | low |
| SPY | M10-PA-001 | 1d | watch_candidate | short | 702.6400 | 712.3900 | 683.1400 | medium |
| SPY | M10-PA-001 | 5m | watch_candidate | long | 710.2200 | 709.2900 | 712.0800 | low |
| SPY | M10-PA-012 | 5m | trigger_candidate | long | 709.5100 | 708.2200 | 710.7700 | low |
| TSLA | M10-PA-001 | 15m | watch_candidate | short | 385.8200 | 390.6000 | 376.2600 | medium |
| TSLA | M10-PA-001 | 1d | watch_candidate | short | 385.2200 | 409.2800 | 337.1000 | high |
| TSLA | M10-PA-012 | 15m | trigger_candidate | short | 388.3690 | 393.3800 | 384.0690 | medium |
| TSLA | M10-PA-012 | 5m | trigger_candidate | short | 388.6300 | 393.3800 | 384.3300 | medium |

## 甲方结论

- Tier A 可以继续做每日只读观察和 scanner 候选跟踪。
- `M10-PA-008/009` 仍需人工图形复核，不进入自动 scanner。
- `M10-PA-004/005/007` 仍在定义修正队列。
- 当前周报只用于模拟观察和测试管理，不作为交易批准。
