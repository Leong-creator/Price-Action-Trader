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
- 若存在 `reports/conversation_goal/current_goal.md`，读取当前对话目标；它只约束本轮意图，不覆盖上面的 source of truth。

当 Codex 客户端没有 `/goal` slash command 时，使用以下仓库内入口设置当前对话目标：

```bash
python scripts/set_conversation_goal.py "目标描述"
```

## 1.1 当前 M14/M15 策略推进规则

- M14 gate 和 readiness 的判断主键是 `runtime_id`，不是 `strategy_id`；`1d`、`5m` 和 rescue/shadow runtime 必须独立给结论、仓位倍率和下一步动作。
- 当前交易运行单元动作状态只允许 `advance_internal_sim`、`risk_limited_advance`、`repair_now`、`pause_runtime`、`paper_candidate`；辅助条目使用 `auxiliary_module`，明确写成“辅助模块：启用为某某用途，不作为独立交易策略”。不得再输出泛化 `continue_testing`、`waiting_for_review` 或“继续观察”作为下一步。
- 盈利但高回撤、低胜率或风险偏高的 runtime 默认走 `risk_limited_advance` 并降低仓位，不得仅因这些风险自动否掉进入内部模拟。
- 明显亏损、零信号或执行链断裂的 runtime 必须给出具体 `repair_now` / `pause_runtime` 原因，不能用观察替代修复。
- M15 修复队列不能只停在报告层；已经批准修复的 runtime 必须进入 M12 账户化运行规则，至少明确仓位倍率、收益风险比、止损距离、假突破确认、图形上下文或连续亏损暂停中的适用规则。周一 fresh refresh 后，用 M13/M14 账本验收这些规则是否真的减少亏损或错误入场。
- `historical_net_profit`、历史净利润、历史收益和历史盈利因子属于旧版错误产物，不得出现在当前 M12/M13/M14/M15 dashboard、CSV、JSON、HTML、Markdown 输出，也不得作为规划或 gate 输入。以后如需历史表现，必须用 M13 account operation ledger 重新按每日价格 mark-to-market，并换新字段名。
- Longbridge paper 当前优先走 OAuth 授权路径，使用 `longbridge auth login` / `Config.from_oauth()`，不再把旧式 `App Key / Secret / Access Token` 三件套作为唯一入口。OAuth 连接审计必须仍保持 paper-only 语义：用户确认模拟账户授权、live token 禁用、真实资金和真实订单禁用；读取资产/持仓、进入订单提交链路和首次 paper 下单仍必须等用户单独批准。当前模拟账户预演按 `6000 USD` 共享资金池执行，非修复、非辅助、非暂停 runtime 都可进入模拟账户测试名单；碎股、融券做空和期权全部禁用。订单类型允许普通限价单和突破触发限价单，必须在美股常规交易时段、一键停止开启、单日订单数、单笔风险、单策略敞口、单标的敞口和总敞口上限生效后才可进入提交链路。
- 长桥模拟账户必须按全新账户处理，不得把 M12/M13 旧本地模拟持仓、历史开仓、历史平仓或旧订单草稿迁移过去。M15 提交器只能提交 `paper_account_start_at` 之后产生的新开仓信号；旧本地模拟订单只允许继续作为本地对比和稳定性审计。
- M15 必须拆成两条链路：本地完整链路由 M12.47/M12.37/M13/M14 生成完整行情、账本、评分和全策略订单预演，允许分钟级延迟；长桥模拟账户快速链路只消费当天已确认策略名单、`paper_account_start_at` 之后的新开仓信号和长桥模拟账户自身状态。每个交易日第一次提交前必须确认 M14 当天策略名单，之后每笔订单不得再等待完整 M13/M14 重算，只做快速风控。
- M15 提交器默认只能先运行 `scripts/run_m15_longbridge_fast_signal_queue.py` 生成当天新信号队列；`scripts/run_m15_all_strategy_order_preview.py` 只保留为后台审计和本地模拟对账，不得作为每笔订单的前置阻塞。提交器默认 `15` 秒检查一次，长桥认证、资产、持仓或挂单读取失败时退避到 `60` 秒。提交器必须写入独立的长桥模拟账户状态 artifact，且该状态只能来自长桥模拟账户自身，不能继承本地模拟仓位。
- M15 快速队列必须合并同一交易日、同一标的、同一方向的重复开仓候选：只保留一条主订单，其余作为共振支持行审计，不得重复提交。多策略共振只提高整股数量，倍率固定为基础 `1.0`、独立策略家族 `+0.50`、同家族变体 `+0.25`、最高 `1.75`，并继续受 `6000 USD` 资金模型、单标的 `600 USD`、总敞口 `3600 USD` 和单笔风险上限约束。
- M15 快速队列必须把非当前纽约交易日的 `scan_date` 标成 `stale_snapshot_waiting_for_current_refresh`，所有行都加 `stale_snapshot_submit_blocked`，提交资格强制为 `0`。盘前异动只允许降权、阻断或等待确认：看涨信号遇到盘前反向跌幅 `<= -3%` 阻断，同向涨幅 `> 8%` 等开盘首个 5 分钟确认，同向 `3% ~ 8%` 只做上下文标记，不额外加仓。
- 周一前只能准备 M15 预演、白名单、仓位、熔断和验收清单；周一交易时段必须等 M12.47 自动拉起 M12.37 fresh refresh，行情来源为 `longbridge_quote_readonly` 后才能重算 M13/M14 和继续长桥模拟账户预演。
- M12.37 盘中自动刷新配置必须允许 `postmarket_or_runtime_ready`：只要 M12 当天行情和账户化运行数据已准备好，就可以在美股常规交易时段重算 M14，避免 M15 模拟账户提交器因为“当天策略复核只等盘后”而无法提交当日新信号。仍禁止手动运行 M12.37 once-mode。

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
