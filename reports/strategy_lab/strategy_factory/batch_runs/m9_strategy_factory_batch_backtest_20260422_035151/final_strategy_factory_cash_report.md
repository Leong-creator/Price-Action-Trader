# M9 Cash-Equity Batch Report

- `run_id`: `m9_strategy_factory_batch_backtest_20260422_035151`
- `provider`: `longbridge`
- `symbols`: SPY, QQQ, NVDA, TSLA
- `coverage_window`: `2025-04-01 ~ 2026-04-21`
- `timeframe`: `5m`
- `starting_capital`: `$25000.0000`
- `risk_per_trade`: `$100.0000`
- `sizing_rule`: `position_size = min(floor(risk_per_trade / risk_per_share), floor(current_equity / entry_price))`
- `boundary`: `paper/simulated`

| Strategy | Variant | Trades | Win Rate | Net PnL | Ending Equity | Return | Max DD | Avg Trade | Triage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| SF-001 | quality_filter | 8037 | 0.3371 | $8683.7310 | $33683.7310 | 34.7349% | $7616.7830 | $1.0805 | modify_and_retest |
| SF-002 | quality_filter | 988 | 0.3451 | $920.8710 | $25920.8710 | 3.6835% | $4110.6050 | $0.9321 | modify_and_retest |
| SF-003 | quality_filter | 1119 | 0.3262 | $1118.6740 | $26118.6740 | 4.4747% | $1694.5250 | $0.9997 | modify_and_retest |
| SF-004 | quality_filter | 301 | 0.3289 | $517.0960 | $25517.0960 | 2.0684% | $2066.0500 | $1.7179 | modify_and_retest |
| SF-005 | - | 0 | - | - | - | - | - | - | deferred_single_source_risk |

## Notes
- 现金口径为研究用途的固定 sizing layer，不改变现有 trigger、risk、execution 或 broker 语义。
- 本报告按每个策略独立账户计算，默认从 `$25,000` 起始、单笔风险预算 `$100`，不模拟策略间资金共享。
- 该层仅用于把 R 倍数结果映射为更直观的美元盈亏/回撤/权益变化，不代表实盘能力。
