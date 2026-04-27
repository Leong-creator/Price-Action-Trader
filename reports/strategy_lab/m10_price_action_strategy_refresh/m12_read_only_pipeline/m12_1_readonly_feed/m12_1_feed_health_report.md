# M12.1 Longbridge Read-only Feed Health Report

## 结论

- auth status: `valid_readonly_market_data`
- ledger rows: `16`
- deferred inputs: `0`
- 本阶段只生成只读 bar-close 输入，不运行策略、不生成执行字段、不输出盈亏结论。

## 范围

- symbols: `SPY / QQQ / NVDA / TSLA`
- timeframes: `1d / 1h / 15m / 5m`
- strategy scope: `M10-PA-001 / M10-PA-002 / M10-PA-012`
- `1d` 只用于收盘后观察；`1h / 15m / 5m` 只用于 regular-session bar close 后观察。

## 数据角色

- K 线轮询是主输入。
- Quote snapshot 只做健康检查。
- Subscriptions 只做诊断，不作为当前依赖。
