# M13 Real Daily Strategy Testing

## Goal

M13 的目标是把策略测试从看板观察升级为每日可审计账本。每个策略或模块在纽约交易日内必须写入一个明确状态；没有账本事件就不能宣称“今天已测试”。

## Daily States

M13 固定使用以下状态：

- `not_connected`
- `detector_missing`
- `missing_data`
- `zero_signal`
- `signal_generated`
- `open`
- `close`
- `risk_blocked`
- `plugin_ab_attached`

## Source Of Truth

- Registry: `config/examples/m13_strategy_runtime_registry.json`
- Runner config: `config/examples/m13_daily_strategy_test_runner.json`
- Signal ledger: `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m13_real_daily_strategy_testing/m13_strategy_signal_ledger.jsonl`
- Account ledger: `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m13_real_daily_strategy_testing/m13_account_operation_ledger.jsonl`
- Scorecard: `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m13_real_daily_strategy_testing/m13_daily_strategy_scorecard.csv`
- Goal status: `reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m13_real_daily_strategy_testing/m13_goal_status.json`

## Current Policy

独立开仓策略进入 runtime account；filter、目标、止损、仓位和加仓规则进入 plugin A/B ledger，不伪装成独立开仓策略。`M10-PA-010` 保持 research-only，直到有最小 detector contract。

AI-Trader 只能作为外部候选信号源研究。允许读取公开或用户授权的只读信号，写入外部研究账本并做本地影子测试；禁止 copy-trading、直接执行或把外部 agent 的信号当成本项目自有策略。

## Experimental Adapters

M13 已把原先空挂的实验账户接入最小可测输入流：

- `M10-PA-005`: failed-breakout range adapter，仍是高风险实验账户，不因接线而升级。
- `M10-PA-007`: M12.23 tightened second-leg detector adapter。
- `M10-PA-008/009/013`: M10.11 Wave B proxy detector adapter。
- `M10-PA-011`: 只保留 `5m` opening-reversal adapter；日线不是有效开盘反转测试口径。

最新 `2026-05-08` 纽约交易日样本已写入 `23` 条 strategy/account signal ledger rows 与 `25` 条 account operation ledger rows，`blocked_strategy_ids=[]`，`goal_complete=true`。这只表示每日测试闭环已跑通；是否推广策略必须等待 10 个真实交易日 challenge。

## Run Command

```bash
python3 scripts/run_m13_daily_strategy_test_runner.py --generated-at 2026-05-08T00:30:00Z
```

不传 `--trading-date` 时，runner 会优先使用 M12.29 看板里的 `scan_date`。
