# M12.0 Longbridge Read-only Auth Check

## 结论

- auth status: `valid_readonly_market_data`
- next action: `ready_for_m12_1_readonly_feed`
- 本阶段只验证 Longbridge 行情/K 线只读能力，不接交易账户、不下单、不批准 paper/live。

## 运行边界

- paper_simulated_only: `true`
- paper_trading_approval: `false`
- broker_connection: `false`
- real_orders: `false`
- live_execution: `false`
- allowed CLI commands: `check / kline / quote / subscriptions`
- 禁止调用交易、资产、持仓、现金、融资、订单相关命令。

## 探针结果

| Probe | Status | Summary |
|---|---|---|
| auth_check | `ok` | `{"active_region": "CN", "connectivity_ok": true, "token": "valid"}` |
| quote_snapshot | `ok` | `{"first_keys": ["high", "last", "low", "open", "overnight_quote", "post_market_quote", "pre_market_quote", "prev_close", "status", "symbol", "turnover", "volume"], "first_symbol": "SPY.US", "row_count": 1}` |
| latest_kline | `ok` | `{"first_keys": ["close", "high", "low", "open", "time", "turnover", "volume"], "first_symbol": null, "row_count": 1}` |
| subscription_snapshot | `ok` | `{"first_keys": [], "first_symbol": null, "row_count": 0}` |

## M12.1 Handoff

- 若 auth status 为 `valid_readonly_market_data`，下一阶段可以实现只读 bar-close feed。
- 若 auth status 不是 valid，先执行 `longbridge auth login`，只授权 quote / K-line / market data。
- 不允许为了通过预检而调用任何账户、资产、持仓或订单命令。
