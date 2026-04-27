# M12.5 Liquid Universe Scanner Report

## 摘要

- 股票池：147 只 US-listed 股票/ETF seed。
- 实际有本地数据并完成扫描的标的：4 只。
- 输出候选：12 条。
- 本阶段只用本地 OHLCV cache；缺数据的标的全部 deferred，不补假机会。
- 自动 scanner 只接 Tier A：`M10-PA-001/002/012`。
- 不接 broker、不接账户、不下单、不批准 paper trading。

## 候选明细

| Symbol | Strategy | Timeframe | Status | Direction | Entry | Stop | Target | Risk | Queue |
|---|---|---|---|---|---:|---:|---:|---|---|
| NVDA | M10-PA-012 | 15m | trigger_candidate | short | 200.7200 | 202.7500 | 198.8100 | medium | eligible_for_read_only_observation |
| NVDA | M10-PA-012 | 5m | trigger_candidate | short | 200.7200 | 202.7500 | 198.8100 | medium | eligible_for_read_only_observation |
| QQQ | M10-PA-001 | 1d | watch_candidate | short | 642.2100 | 650.0000 | 626.6300 | medium | eligible_for_read_only_observation |
| QQQ | M10-PA-012 | 5m | trigger_candidate | long | 651.1400 | 648.5200 | 653.0200 | low | eligible_for_read_only_observation |
| SPY | M10-PA-001 | 15m | watch_candidate | short | 709.2900 | 710.7000 | 706.4700 | low | eligible_for_read_only_observation |
| SPY | M10-PA-001 | 1d | watch_candidate | short | 702.6400 | 712.3900 | 683.1400 | medium | eligible_for_read_only_observation |
| SPY | M10-PA-001 | 5m | watch_candidate | long | 710.2200 | 709.2900 | 712.0800 | low | eligible_for_read_only_observation |
| SPY | M10-PA-012 | 5m | trigger_candidate | long | 709.5100 | 708.2200 | 710.7700 | low | eligible_for_read_only_observation |
| TSLA | M10-PA-001 | 15m | watch_candidate | short | 385.8200 | 390.6000 | 376.2600 | medium | eligible_for_read_only_observation |
| TSLA | M10-PA-001 | 1d | watch_candidate | short | 385.2200 | 409.2800 | 337.1000 | high | eligible_for_read_only_observation |
| TSLA | M10-PA-012 | 15m | trigger_candidate | short | 388.3690 | 393.3800 | 384.0690 | medium | eligible_for_read_only_observation |
| TSLA | M10-PA-012 | 5m | trigger_candidate | short | 388.6300 | 393.3800 | 384.3300 | medium | eligible_for_read_only_observation |

## 下一步

下一阶段可以把 scanner 输出接到每周成绩单。扩大覆盖前，应先补齐更多 universe 标的的只读 K 线缓存或受控 Longbridge 读取计划。
