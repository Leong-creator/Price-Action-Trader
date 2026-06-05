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
- Longbridge paper 当前优先走 OAuth 授权路径，使用 `longbridge auth login` / `Config.from_oauth()`，不再把旧式 `App Key / Secret / Access Token` 三件套作为唯一入口。OAuth 连接审计必须仍保持 paper-only 语义：用户确认模拟账户授权、live token 禁用、真实资金和真实订单禁用；读取资产/持仓、进入订单提交链路和首次 paper 下单仍必须等用户单独批准。当前模拟账户预演按 `10000 USD` 共享资金池执行，非修复、非辅助、非暂停 runtime 都可进入模拟账户测试名单；碎股、融券做空和期权全部禁用。订单类型允许普通限价单和突破触发限价单，必须在美股常规交易时段、一键停止开启、单日订单数、单笔风险、单策略敞口、单标的敞口和总敞口上限生效后才可进入提交链路。
- 长桥模拟账户必须按独立新账户处理，不得把 M12/M13 旧本地模拟持仓、历史开仓、历史平仓、旧订单草稿或本地平仓信号迁移过去，也不得用它们阻断长桥开仓。长桥账户只看自己的现金、持仓、挂单、成交、订单编号和止损/止盈计划。
- M15 必须拆成两条完全隔离的链路：本地完整链路由 M12.47/M12.37/M13/M14 生成完整行情、账本、评分和全策略复盘，允许分钟级延迟；长桥实时执行链路只消费长桥实时行情/新 K 线事件生成的实时信号、长桥模拟账户自身状态和实时风控结果。长桥实时链路不得读取 `m12_46_account_trade_ledger.jsonl`、不得把 M13/M14 完整重算作为下单前置条件、不得用本地平仓决定长桥是否开仓。
- M15 长桥实时行情入口为 `scripts/run_m15_longbridge_realtime_market_event_ingestor.py`，配置为 `config/examples/m15_longbridge_realtime_market_event_ingestor.json`。第一版只调用 Longbridge CLI 只读 `kline` 命令生成 `m15_realtime_market_events.jsonl`；不得读取账户、资产、持仓、订单、旧快速队列或本地模拟账本。`147` 只种子池必须保留为总覆盖范围，但实时轮询使用热名单优先和游标分批，避免每轮全量请求拖慢热路径。该入口后续可替换为 SDK 行情订阅，但输出事件契约不得改变。
- M15 长桥实时信号入口为 `scripts/run_m15_longbridge_realtime_signal_router.py`，配置为 `config/examples/m15_longbridge_realtime_signal_router.json`。它只消费长桥实时行情/新 K 线事件，输出 `m15_realtime_signal_events.jsonl` 给实时执行链路；不得读取本地模拟账本、旧快速队列或本地平仓。第一版支持行情事件内嵌策略意图、`M10-PA-004-long-1d` 日线强势跟进检测器，以及 `price_action_realtime_v1` 通用实时价格行为检测器；后者已覆盖 `M10-PA-001-1d/5m`、`M10-PA-002-1d`、`M10-PA-005-1d/5m`、`M10-PA-008-1d`、`M10-PA-012-5m`、`M10-PA-013-1d/5m`、`M12-FTD-001-baseline-1d` 的白名单信号生成。修复策略、辅助模块和影子变体仍不得生成长桥实时信号。同一交易日、同一标的、同一方向、多个不同运行单元共振时，只生成一条主信号，其余写入合并审计；共振只提高主信号仓位上限，不重复下单。
- M15 长桥实时账户状态入口为 `scripts/run_m15_longbridge_realtime_account_state.py`，配置为 `config/examples/m15_longbridge_realtime_account_state.json`。它只读取长桥模拟账户自身的通道、现金、购买力、持仓和未完成挂单；不得提交、撤单、改单，不得读取本地模拟账户状态。实时执行链路必须使用该账户状态作为持仓、挂单、现金和敞口来源。
- M15 长桥实时持仓退出入口为 `scripts/run_m15_longbridge_realtime_position_manager.py`，配置为 `config/examples/m15_longbridge_realtime_position_manager.json`。它只用长桥账户持仓、长桥实时行情和长桥实时执行记录里的止损/目标价生成平仓信号；本地模拟平仓不得触发长桥平仓。卖出只允许作为已有多头的止损/止盈/平仓，不得变成融券做空。长桥账户已有但没有本轮 M15 开仓元数据的持仓必须标记为非系统管理持仓，只展示、不自动平仓。
- M15 长桥实时执行入口为 `scripts/run_m15_longbridge_realtime_execution.py`，配置为 `config/examples/m15_longbridge_realtime_execution.json`。实时信号事件必须包含 `signal_id`、生成时间、运行单元、标的、周期、方向、订单类型、触发价/限价、止损、目标价、建议数量、风险金额、行情事件编号和有效期；信号只代表当前可执行意图，不是本地模拟账本行。执行链路必须检查长桥账户自身已有持仓、未完成挂单、现金、单标的敞口、总敞口和单笔风险；新买入不得无视已有持仓或挂单，卖出只能平已有多头。信号生成到本地发起长桥模拟账户下单请求的处理时间目标为 `<= 1` 秒，第一版 `<= 5` 秒仍可接受；超过 `5` 秒必须记录延迟异常并重新检查当前价格、风险、止损、目标和扣费后利润，超过 `max_delayed_signal_age_seconds` 或信号自身有效期的旧信号必须阻断，不允许停机后补交几分钟或几小时前的信号。默认配置仍关闭真实提交，只有 `execute_orders=true` 且 `paper_trading_approval=true` 才允许调用模拟账户下单命令。
- M15 长桥实时执行只处理未处理过的实时信号事件；同一个 `signal_id` 一旦已有执行流水，不论当时是提交、阻断还是只读演练，都不会在后续循环里反复重算或补交。若价格行为条件后来仍然成立，必须由新的长桥行情事件重新触发新的 `signal_id`。
- 长桥实时执行必须把本交易日已提交但账户状态尚未刷新出的模拟买单计入待成交敞口；如果同一标的已有长桥持仓、未完成挂单或实时提交账本里的待成交买单，新买入必须阻断，防止账户状态延迟导致重复开仓。
- M15 长桥实时会话守护器入口为 `scripts/run_m15_longbridge_realtime_session_supervisor.py`，配置为 `config/examples/m15_longbridge_realtime_session_supervisor.json`。它只在配置允许的美股常规交易时段按顺序拉起实时行情采集、实时信号路由、实时账户状态、实时持仓退出和实时执行链路；非交易窗口只写“等待交易窗口”状态。该守护器不得手动运行 M12.37 once-mode，不得读取旧快速队列作为下单来源，不得读取本地模拟账本，也不得启用实盘或真实资金。
- 模拟订单启用必须使用单独配置：`config/examples/m15_longbridge_realtime_execution.paper_orders_enabled.json` 与 `config/examples/m15_longbridge_realtime_session_supervisor.paper_orders_enabled.json`。开盘前必须运行 `scripts/run_m15_opening_trade_readiness.py`，只有 M12.47 守护器存活、M15 实时守护器存活、账户确认为 `lb_papertrading`、`execute_orders=true`、`paper_trading_approval=true`、实盘/真实资金/碎股/做空/期权全部禁用、修复策略和辅助模块隔离时，才允许等待常规交易时段自动提交长桥模拟账户订单。
- `m15_longbridge_fast_signal_queue` 从长桥提交来源降级为本地审计/历史兼容产物；`scripts/run_m15_all_strategy_order_preview.py` 也只保留为本地复盘和稳定性审计，不得作为长桥实时下单热路径。旧快速队列仍可用于研究重复信号、共振和费用门槛，但不能再给长桥提交器提供待提交订单。
- 长桥实时白名单只包含非修复、非辅助、非影子救援的正式运行单元。修复策略、救援变体、影子参数策略只跑本地模拟，不创建长桥实时信号、不进入长桥实时风控、不占长桥实时资源；辅助模块只服务本地策略评分、止损、仓位、目标价和图形证据，不独立下单。
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
