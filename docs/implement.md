# 主 Agent 执行手册

## 1. 执行主线

`plans/active-plan.md` 是当前唯一执行主线。

开始任何任务前，必须读取：

- `plans/active-plan.md`
- `docs/status.md`
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/acceptance.md`
- 当前模块最近的 `AGENTS.md` 或 `AGENTS.override.md`

## 2. 每个 milestone 的流程

1. 确认当前 milestone。
2. 按 `docs/branching.md` 创建分支。
3. 判断是否需要 subagent。
4. 派发 researcher / data_engineer / kb_curator / implementer / reviewer / qa。
5. 等待 subagent 结果。
6. 读取 handoff。
7. 主 agent 集成。
8. reviewer 审查。
9. qa 验证。
10. 更新 `docs/status.md`、必要时更新 `docs/decisions.md` 和 `plans/active-plan.md`。
11. 未触发阻塞时继续下一个 milestone。

## 3. 何时必须创建 subagent

满足任一条件即必须显式创建：

- 2 个以上独立子任务。
- 同时涉及探索、实现、审查、测试。
- 同时涉及知识库和代码。
- 涉及多个模块边界。
- 涉及高风险模块。

## 4. 防死循环

- 同一子任务失败 3 次，熔断。
- reviewer 连续打回 3 次，熔断。
- 熔断后输出 Failure Dossier。
- 禁止盲目继续尝试。

## 5. 何时问用户

只在以下情况问用户：

- 需要真实账户、凭证、付费服务或外部权限。
- 需要决定是否进入下一阶段。
- 需要决定高影响架构取舍。
- 需要业务验收或实盘审批。
- 熔断后需要用户选择继续方向。

其他情况下，主 agent 自主推进。

## 6. 完成前检查

任务完成前必须确认：

- 在正确分支上完成。
- 测试或验证已运行。
- 文档已同步。
- status 已更新。
- handoff 已归档或摘要写入 status。
- reviewer 通过。
- qa 通过。
