# Broker Approval Checklist

## Purpose

- 本清单只用于 M7 readiness assessment 的人工审批与核对。
- 当前阶段不允许把本清单视为真实接入授权。

## Checklist

- 已确认当前运行模式仍为 paper / simulated。
- 已确认不存在真实账户、真实资金或 live execution 默认开关。
- 已确认 `FormalBrokerAdapter` 仍是 interface-only contract draft。
- 已确认没有引入真实 broker SDK、HTTP client、WebSocket client 或外部网络依赖。
- 已确认没有引入真实凭证、默认凭证值、仓库落盘凭证或测试中的伪真实凭证。
- 已确认 credential isolation 规则覆盖注入、最小权限、轮换、吊销与审计。
- 已确认 risk gate 与 execution gate 顺序未被修改，broker draft 无法绕过现有风控。
- 已确认 no-go 时系统默认停留在 paper / simulated。
- 已确认存在清晰回退方案，可整体撤回 M7 assessment 改动。
- 已确认 reviewer 已完成高风险边界审查。
- 已确认 qa 已完成 readiness 清单核对。
- 已确认任何下一阶段外部权限、真实账户、付费服务或 live execution 仍需用户单独批准。

## Required Evidence

- `python -m unittest discover -s tests/unit -v`
- `python -m py_compile src/broker/__init__.py src/broker/contracts.py tests/unit/test_broker_contract_assessment.py`
- reviewer handoff
- qa handoff
- 当前 milestone 状态同步到 `docs/status.md` 与 `plans/active-plan.md`

## Disallowed Outcomes

- 将 contract draft 当作真实接入实现继续扩展。
- 在未获批准时新增真实账户、真实资金、付费服务或 live execution 路径。
- 将 credential isolation 简化为文档口头说明而无明确 gate。
