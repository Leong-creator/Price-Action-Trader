# M12.4 复测客户摘要

## 这一步解决了什么

本阶段把不能继续推进的几条策略拆清楚：哪一条已经有复测数字，哪几条还缺可执行定义。没有为了凑结果补假交易。

## 已有数字的策略

| 策略 | 周期 | 修正前交易数 | 修正后交易数 | 修正后净利润 | 修正后胜率 | 当前状态 |
|---|---|---:|---:|---:|---:|---|
| M10-PA-005 | 1d | 1481 | 1188 | -22855.77 | 0.3232 | completed_capital_test |
| M10-PA-005 | 1h | 1469 | 950 | 4527.65 | 0.3305 | needs_definition_fix |
| M10-PA-005 | 15m | 7511 | 2966 | 14707.57 | 0.3422 | needs_definition_fix |
| M10-PA-005 | 5m | 23881 | 8007 | -107134.41 | 0.3318 | needs_definition_fix |

## 暂不能给交易数字的策略

| 策略 | 已有图例数 | 为什么先不复测 | 下一步要补什么 |
|---|---:|---|---|
| M10-PA-004 | 5 | broad channel boundary depends on drawn channel line quality and boundary tests that are not yet encoded. | channel boundary anchor persistence; boundary touch tolerance; strong breakout disqualifier |
| M10-PA-007 | 5 | second-leg trap needs range edge, first leg, second leg, and trap confirmation fields before reliable backtest. | first-leg and second-leg labels; range edge or breakout edge; trap confirmation bar |

## 甲方视角结论

`M10-PA-005` 有复测数字，但仍不够干净，暂不进入自动观察或选股扫描。`M10-PA-004/007` 有图例证据，但还没有可执行定义，不能硬跑历史回测。下一阶段应进入 M12.5 选股扫描，第一版只接 Tier A 主线，同时把这些策略留在定义修正队列。
