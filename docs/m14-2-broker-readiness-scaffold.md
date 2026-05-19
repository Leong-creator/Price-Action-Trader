# M14.2 Broker Readiness Scaffold

## Purpose

本阶段只做工程准备，让后续策略通过 M14 gate 后，可以较快进入 broker paper / live 的人工审批流程。

当前交付不是 broker 接入，不连接真实账户，不提交订单。

## Current Boundary

- `mode=paper_dry_run_only`
- `broker_connection_enabled=false`
- `real_order_enabled=false`
- `live_execution_enabled=false`
- `paper_trading_approval=false`
- `kill_switch_enabled=true`
- 凭证不得写入仓库、配置、测试或默认值。

## Flow

1. M13/M14 先生成每日策略账本和 `paper_trial_gate`。
2. 只有策略进入 `approved_internal_sim_only` 后，才允许进入 broker readiness dry-run。
3. `ExecutionRequest` 必须已经通过 `src.risk.evaluate_order_request`。
4. `build_broker_readiness_plan` 只生成 `BrokerOrderPreview`。
5. `BrokerOrderPreview` 不是订单，不含 `submit/connect/login` 行为。
6. 真实 broker paper 或 live 必须另开高风险分支、补凭证隔离、人工审批和回退方案。

## Block Conditions

以下任一条件触发时必须阻断：

- `risk_decision.outcome != allow`
- 策略未进入 `approved_internal_sim_only`
- `broker_connection_enabled=true`
- `real_order_enabled=true`
- `live_execution_enabled=true`
- `paper_trading_approval=true`
- `kill_switch_enabled=false`
- 配置或代码包含默认凭证值

## Acceptance

- 只能输出 dry-run order preview。
- 不引入真实 broker SDK、HTTP client、WebSocket client。
- 不读取真实凭证。
- 不新增真实下单方法。
- 测试必须覆盖风险拦截、未批准策略、unsafe config 和 happy-path preview。
