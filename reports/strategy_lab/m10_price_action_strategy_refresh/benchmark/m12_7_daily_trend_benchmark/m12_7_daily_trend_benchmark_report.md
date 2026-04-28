# M12.7 Daily Trend Momentum Benchmark

## 结论

- Benchmark：`M12-BENCH-001 Daily Trend Momentum Baseline`
- 决策：`scanner_factor_candidate`
- 原因：长窗口样本、profit factor 与收益集中度满足 scanner 因子候选门槛。
- 边界：只作为早期日线趋势动量 benchmark / scanner factor 候选；不作为准入证据，不代表 Brooks clean-room 策略。

## 核心成绩

- 模拟初始资金：`$100000.00`
- 模拟最终权益：`$149786.19`
- 模拟净结果：`$49786.19`
- 模拟收益率：`49.7862%`
- benchmark 事件数：`1165`
- 胜率：`36.2232%`
- Profit factor：`1.1357`
- 模拟峰谷回落：`$15239.14` / `12.1939%`
- 被模拟预算规则压制的信号：`330`

## 分标的

- `SPY`：模拟事件 `183` 条，模拟净结果 `$18310.93`，胜率 `39.8907%`，benchmark 信号 `380` 个，缓存 `local_data/longbridge_history/us_SPY_1d_2010-06-29_2026-04-21_longbridge.csv`。
- `QQQ`：模拟事件 `286` 条，模拟净结果 `$19417.11`，胜率 `38.1119%`，benchmark 信号 `395` 个，缓存 `local_data/longbridge_history/us_QQQ_1d_1990-01-01_2026-04-21_longbridge.csv`。
- `NVDA`：模拟事件 `354` 条，模拟净结果 `$23986.46`，胜率 `37.8531%`，benchmark 信号 `382` 个，缓存 `local_data/longbridge_history/us_NVDA_1d_2010-06-29_2026-04-21_longbridge.csv`。
- `TSLA`：模拟事件 `342` 条，模拟净结果 `$-11928.31`，胜率 `30.9942%`，benchmark 信号 `379` 个，缓存 `local_data/longbridge_history/us_TSLA_1d_2010-06-29_2026-04-21_longbridge.csv`。

## 与 M10 Tier A 对比

| ID | 来源族 | 模拟收益率 | 胜率 | 模拟峰谷回落 | 事件数 | 状态 |
|---|---:|---:|---:|---:|---:|---|
| M12-BENCH-001 | early_daily_placeholder_benchmark | 49.7862% | 0.3622 | 12.1939% | 1165 | scanner_factor_candidate |
| M10-PA-001 | m10_clean_room_strategy | 24.7327% | 0.3584 | 34.1783% | 19312 | completed_capital_test |
| M10-PA-002 | m10_clean_room_strategy | 3.2810% | 0.3492 | 23.5592% | 16303 | completed_capital_test |
| M10-PA-012 | m10_clean_room_strategy | 26.8927% | 0.3815 | 12.7415% | 3662 | completed_capital_test |

## 交付边界

- 本阶段复用的是早期截图里的 `signal_bar_entry_placeholder`，不是 M10 clean-room catalog。
- 它只能作为 benchmark 或 scanner 排名因子候选，不能单独作为准入证据。
- 所有结果都是 historical simulation，不包含任何执行链路。
