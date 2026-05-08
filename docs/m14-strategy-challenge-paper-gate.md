# M14 Strategy Challenge And Internal Paper Gate

## Goal

M14 的目标是在 M13 每日账本之上建立稳定挑战层：每个策略按纽约交易日进入 append-only challenge ledger，满 `10` 个真实交易日后才允许输出 `promote / modify / reject / continue_testing`，并且只有通过 gate 的策略能进入内部模拟账户。

## Source Of Truth

- Runner config: `config/examples/m14_strategy_challenge_gate.json`
- Runner: `scripts/run_m14_strategy_challenge_gate.py`
- Challenge ledger: `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m14_strategy_challenge/m14_challenge_day_ledger.jsonl`
- Decision ledger: `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m14_strategy_challenge/m14_strategy_decision_ledger.jsonl`
- Paper trial gate: `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m14_strategy_challenge/m14_paper_trial_gate.json`
- Dashboard: `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m14_strategy_challenge/m14_strategy_challenge_dashboard.html`

## Policy

- 默认挑战窗口是 `10` 个纽约交易日。
- 亏损策略不允许静默改定义；先冻结 baseline，再生成新 variant ID 做 A/B。
- 提前处理只允许在 circuit breaker 下触发：至少 `3` 个 signal days 后，`net_pnl_r < -2R`、最大回撤 `>3%`、风险拦截占比过高，或重复数据缺口。
- `paper_trial_gate=approved_internal_sim_only` 只表示内部模拟账户准入，不表示 broker paper、真实账户或实盘批准。
- `fallback_quotes_only`、`--no-fetch`、`--no-refresh-quotes` 或 `current_day_runtime_ready=false` 会阻止 gate 批准，并在 M14 dashboard 顶部显示告警。

## Internal Paper Bridge

M14 只对 gate 已批准的策略转换 M13/M12 ledger signal：

1. Ledger open event -> `ExecutionRequest`
2. `src.risk.evaluate_order_request(...)`
3. `src.execution.PaperBrokerAdapter.submit(...)`
4. 写入 `m14_internal_paper_execution_ledger.jsonl`

该桥接仍强制：

- `simulated=true`
- `broker_paper_connection=false`
- `real_money_actions=false`
- `live_execution=false`
- `paper_trading_approval=false`

当前 `2026-05-08` 样本因为 M12 看板是 fallback/no-fetch 口径，M14 已写入 challenge/decision/gate，但没有任何策略获准进入内部模拟成交。

## Run Command

```bash
python3 scripts/run_m14_strategy_challenge_gate.py --generated-at 2026-05-08T17:10:00Z --trading-date 2026-05-08
```
