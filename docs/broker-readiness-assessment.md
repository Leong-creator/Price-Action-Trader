# Broker Readiness Assessment

## Scope

- 本文档只服务于 M7 readiness assessment。
- 当前产物只允许包含 `FormalBrokerAdapter` 接口草案、能力矩阵、门禁条件、go/no-go 模板与风险说明。
- 本文档不授权真实 broker 接入实现、不授权真实账户联通、不授权真实下单、不授权 live execution。

## Assessment Boundary

- 运行基线仍是 M5 冻结的 paper/simulated execution 与 risk contracts。
- 复盘与证据链仍消费 M6 冻结的 review/report contracts。
- 任何 FormalBrokerAdapter 草案都必须位于 risk gate 与 execution gate 之后。
- FormalBrokerAdapter 草案只定义 future integration boundary，不提供网络调用、SDK 封装、登录、下单、改单、撤单、订阅或账户同步实现。

## Capability Matrix

| Capability | Assessment Status | Notes |
| --- | --- | --- |
| Account session metadata | Draft only | 仅允许定义 session / account reference 占位结构，不允许真实登录。 |
| Credential isolation | Required | 必须定义注入、轮换、最小权限、审计和禁止仓库落盘规则。 |
| Pre-trade gate dependency | Required | 必须显式依赖既有 risk / execution gate，不得绕过。 |
| Order submission | Disallowed in M7 | 只能列为未来阶段能力，不得实现。 |
| Cancel / replace | Disallowed in M7 | 只能列为未来阶段能力，不得实现。 |
| Position sync | Disallowed in M7 | 只能列为未来阶段能力，不得实现。 |
| Market data / quote routing | Disallowed in M7 | 不是当前 readiness assessment 的交付物。 |
| Dry-run / probe | Draft only | 只允许定义未来只读探针需求，不允许联通外部系统。 |
| Audit trail | Required | 必须说明审批、凭证使用、回退和人工复核的审计要求。 |

## Prerequisites

- `python -m unittest discover -s tests/unit -v` 持续通过。
- M5 paper execution / risk loop 持续稳定，无未关闭高风险缺陷。
- M6 news / review integration 持续稳定，无越界到 signal / order / execution 的回归。
- 明确当前阶段仍停留在 simulated / paper 研究闭环。
- 未获得用户对真实账户、真实资金、付费服务或 live execution 的批准前，不得越级推进。

## Credential Isolation Requirements

- 凭证不得写入仓库、测试样本、默认配置、源码常量或文档示例中的真实值。
- 凭证注入必须是外部运行时行为，且默认缺省。
- 凭证必须区分 read-only probe 与 future trading scope，不得复用单一高权限 key。
- 凭证轮换、吊销、过期和审计要求必须先于任何真实联通实现。
- 任何未来真实凭证使用都必须可追溯到人工审批记录。

## Approval Gates

- Gate 1：paper-only 基线稳定，M5 与 M6 回归继续通过。
- Gate 2：FormalBrokerAdapter contract draft 完成 reviewer 审查，确认无真实调用实现。
- Gate 3：credential isolation 与 approval checklist 完整，qa 核对通过。
- Gate 4：存在清晰回退方案，且 no-go 时系统继续停留在 paper/simulated。
- Gate 5：获得用户对下一阶段外部权限、真实账户或付费服务的明确批准。

## Go / No-Go Template

## Current Assessment Result

- 当前结论：`no-go`
- 原因：
  - 当前阶段只完成 readiness assessment artifact，没有真实 broker 联通批准。
  - 当前不存在真实账户、真实资金、付费服务或 live execution 审批。
  - 当前 `FormalBrokerAdapter` 仍是 interface-only contract draft，未到可接入阶段。
  - 默认策略必须继续停留在 paper / simulated。

### Go

- 仅在以下条件同时满足时才可讨论下一阶段：
  - readiness 文档完整
  - contract draft 无越界实现
  - reviewer / qa 通过
  - 凭证隔离与审批清单完整
  - 用户明确批准后续外部权限或真实账户联通

### No-Go

- 任一条件不满足时，结论必须是 no-go。
- no-go 的默认动作：
  - 继续停留在 paper / simulated
  - 不接真实 broker
  - 不接真实账户
  - 不启用 live execution
  - 只允许继续完善 research / review / documentation

## Rollback Boundary

- M7 只允许新增 assessment 文档与 contract draft。
- 若出现真实 broker SDK、HTTP client、登录、下单、改单、撤单、账户同步或外部网络依赖，实现即视为越界，整段 M7 改动必须回退。
