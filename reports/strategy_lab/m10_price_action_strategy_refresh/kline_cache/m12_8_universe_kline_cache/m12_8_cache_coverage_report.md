# M12.8 Universe Kline Cache Completion

## 摘要

- 股票池：`147` 只 M12.5 US liquid seed。
- 当前有任一 native cache 的标的：`4` 只。
- 完整覆盖目标窗口或已从首根可用 bar 覆盖到目标终点的标的：`0` 只。
- deferred/error ledger 条目：`588` 条。
- fetch plan 请求：`294` 条，估算 Longbridge chunk `23373` 个。

## 结论

M12.8 当前没有伪造 K 线，也没有把 `SPY/QQQ/NVDA/TSLA` 的局部缓存描述为全 universe 可用。
在 fetch plan 真正执行并重新生成 coverage 之前，scanner 只能把 `cache_present_symbols` 当作局部诊断输入，不能宣称 `147` 只股票全量可扫描。

## 可用集合

- cache present symbols：`NVDA, QQQ, SPY, TSLA`
- target complete symbols：`-`

## 边界

- `local_data/` 继续不进入 Git；tracked artifact 只记录 logical path、checksum、row count、date span 和 lineage。
- `15m / 1h` 只从 `5m` 聚合，必须保留 `derived_from_5m`。
- 缺失、过期、限流或供应商异常只能进入 deferred/error ledger，不补假数据、不补假候选。
