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
- Longbridge paper 当前优先走 OAuth 授权路径，使用 `longbridge auth login` / `Config.from_oauth()`，不再把旧式 `App Key / Secret / Access Token` 三件套作为唯一入口。OAuth 连接审计必须仍保持 paper-only 语义：用户确认模拟账户授权、live token 禁用、真实资金和真实订单禁用。当前长桥仍只有一个 `lb_papertrading` 模拟账户，但本地默认按“单策略单仓”归因和控仓：每条合格策略独立一个 `10000 USD` 虚拟仓，统一 `1.0` 测试，不再用 `0.5 / 0.25 / 0.10` 倍率打折；每仓总敞口 `6000 USD`、单标的 `1500 USD`、单笔风险 `20 USD`、现金保留 `4000 USD`，不设置所有单策略仓合计敞口上限。同一标的允许不同单策略仓分别持有，必须按资金池、运行单元、订单号和成交批次分开归因。第一批单策略仓为 `M10-PA-004-long-1d`、`M10-PA-002-5m`、`M12-FTD-001-baseline-1d`、`M12-FTD-001-loss-streak-guard-1d`、`M10-PA-004-MBF-1d`、`M10-PA-004-MBF-QC-1d`、`M10-PA-013-5m`、`M10-PA-011-ORB-R1-5m`。统一实验仓继续低倍率筛选 `M10-PA-002-1d`、`M10-PA-013-1d`、`M10-PA-008-1d`、`M10-PA-005-1d/5m`、`M10-PA-012-5m`、`M10-PA-001-1d`。真正碎股订单、融券做空和期权全部禁用；但建议数量大于等于 `1` 股的小数数量必须先向下取整为整股并重新检查风险和利润，只有不足 `1` 股才阻断。订单类型允许普通限价单和突破触发限价单，必须在美股常规交易时段、一键停止开启、单笔风险、单仓单标的敞口和单仓总敞口上限生效后才可进入提交链路。
- 长桥模拟账户必须按独立新账户处理，不得把 M12/M13 旧本地模拟持仓、历史开仓、历史平仓、旧订单草稿或本地平仓信号迁移过去，也不得用它们阻断长桥开仓。长桥账户只看自己的现金、持仓、挂单、成交、订单编号和止损/止盈计划。
- M15 必须拆成两条完全隔离的链路：本地完整链路由 M12.47/M12.37/M13/M14 生成完整行情、账本、评分和全策略复盘，允许分钟级延迟；长桥实时执行链路只消费长桥实时行情/新 K 线事件生成的实时信号、长桥模拟账户自身状态和实时风控结果。长桥实时链路不得读取 `m12_46_account_trade_ledger.jsonl`、不得把 M13/M14 完整重算作为下单前置条件、不得用本地平仓决定长桥是否开仓。
- M15 长桥实时行情入口为 `scripts/run_m15_longbridge_realtime_market_event_ingestor.py`，配置为 `config/examples/m15_longbridge_realtime_market_event_ingestor.json`。第一版只调用 Longbridge CLI 只读 `kline` 命令生成 `m15_realtime_market_events.jsonl`；不得读取账户、资产、持仓、订单、旧快速队列或本地模拟账本。`147` 只种子池必须保留为总覆盖范围，但实时轮询使用热名单优先和游标分批，避免每轮全量请求拖慢热路径。长桥 CLI 单次 K 线请求必须有硬超时，超时后必须连同子进程组一起终止并把该标的记为 deferred，不能让单个行情请求卡死整条实时执行链路。当前热路径每轮默认扫描 `6` 个热名单标的加 `2` 个轮询标的；行情事件文件超过上限时只归档旧行情事件并保留最近事件，避免长期运行后每轮解析百 MB 旧行情。后续 SDK 行情订阅接入前不得恢复全量同步阻塞扫描。该入口后续可替换为 SDK 行情订阅，但输出事件契约不得改变。
- M15 长桥实时信号入口为 `scripts/run_m15_longbridge_realtime_signal_router.py`，配置为 `config/examples/m15_longbridge_realtime_signal_router.json`。它只消费长桥实时行情/新 K 线事件，输出 `m15_realtime_signal_events.jsonl` 给实时执行链路；不得读取本地模拟账本、旧快速队列或本地平仓。第一版支持行情事件内嵌策略意图、`M10-PA-004-long-1d` 日线强势跟进检测器，以及 `price_action_realtime_v1` 通用实时价格行为检测器；后者已覆盖单策略仓和统一实验仓白名单运行单元。FTD 原版、FTD 连亏保护、PA004-MBF、PA004-MBF-QC、PA013-5m、PA011-ORB-R1 和 PA002-5m 必须分别进入自己的单策略仓，独立信号、独立风控、独立统计。`M10-PA-002-1d` 只保留在统一实验仓，不再通过 `additional_runtime_bucket_routes` 镜像到 002 专项仓。修复策略、辅助模块和未列入单仓白名单的影子/救援变体仍不得生成长桥实时信号。同一交易日、同一标的、同一方向、同一资金池内多个不同运行单元共振时，只生成一条主信号，其余写入合并审计；跨资金池同标的信号不合并，各资金池独立下单和归因。
- M15 长桥实时信号路由器不得每轮全量重扫历史行情事件。热路径只处理当前交易会话收到的行情事件、同标的/周期必要的少量历史 K 线上下文，以及旧嵌入信号的阻断审计行；无关旧行情只保留审计价值，不得参与当前实时信号生成，避免长时间运行后拖慢下单链路。
- M15 长桥实时账户状态入口为 `scripts/run_m15_longbridge_realtime_account_state.py`，配置为 `config/examples/m15_longbridge_realtime_account_state.json`。它只读取长桥模拟账户自身的通道、现金、购买力、持仓、未完成挂单、历史订单和历史成交；不得提交、撤单、改单，不得读取本地模拟账户状态。实时执行链路必须只使用当前持仓、挂单、现金和敞口做下单风控；历史订单/历史成交只用于看板胜率、成交数和对账统计，不参与实时开仓判断。账户状态刷新必须同时生成长桥盈亏对账 JSON 和 Markdown，避免 JSON 已更新但人工报告/看板引用仍停在旧日期。
- M15 长桥旧挂单清理入口为 `scripts/run_m15_longbridge_realtime_stale_order_cleanup.py`，配置为 `config/examples/m15_longbridge_realtime_stale_order_cleanup.json`。它只允许在 `lb_papertrading` 模拟账户通道下处理上一交易窗口遗留的买入挂单；不得撤卖出保护单，不得接触实盘、真实资金或本地模拟账本。清理后必须重新读取长桥模拟账户状态，再进入持仓退出和新信号执行。
- M15 长桥实时持仓退出入口为 `scripts/run_m15_longbridge_realtime_position_manager.py`，配置为 `config/examples/m15_longbridge_realtime_position_manager.json`。它只用长桥账户持仓、长桥实时行情和长桥实时执行记录里的止损/目标价生成平仓信号；本地模拟平仓不得触发长桥平仓。卖出只允许作为已有多头的止损/止盈/平仓，不得变成融券做空。长桥账户已有但没有本轮 M15 开仓元数据的持仓必须标记为“只接管退出”：不迁移成本地策略、不参与新开仓或加仓，但可以按长桥账户自身成本价和实时价格生成止损/止盈退出计划。
- M15 长桥实时执行入口为 `scripts/run_m15_longbridge_realtime_execution.py`，配置为 `config/examples/m15_longbridge_realtime_execution.json`。实时信号事件必须包含 `signal_id`、生成时间、运行单元、标的、周期、方向、订单类型、触发价/限价、止损、目标价、建议数量、风险金额、行情事件编号和有效期；信号只代表当前可执行意图，不是本地模拟账本行。执行链路必须检查长桥账户自身现金、卖出可用数量、已有卖出挂单，以及本地虚拟资金池内的已提交买单、同标的敞口、总敞口和单笔风险；同一标的允许不同资金池分别持有，但同一资金池内仍去重和控仓。卖出只能平长桥账户已有多头；新测试基线清仓卖出必须使用可成交保护限价，优先用当前价略低的限价，若券商持仓只给成本价则使用折扣成本价兜底，避免清仓卡在成本价上。实时执行必须和路由器使用同一套整股化数量规则：`raw_quantity >= 1` 时向下取整为 `submitted_quantity` 并重算单笔风险、敞口、扣费后利润和收益风险比；`raw_quantity < 1` 时阻断为 `blocked_quantity_below_one_share`；不得再用 `blocked_fractional_disabled` 阻断 `24.0964 -> 24` 这类大于 1 股的小数数量。扣费后预计净利润低于当前运行单元门槛的实时信号只记录不提交：全局最低 `5 USD`，普通可交易信号最低 `8 USD`，`M10-PA-001` 等弱策略最低 `12 USD`；目标利润/止损风险普通信号必须 `>= 1.5`，弱策略必须 `>= 2.0`，不足时直接阻断，不强行拉高目标价。信号生成到本地发起长桥模拟账户下单请求的处理时间目标为 `<= 1` 秒，第一版 `<= 5` 秒仍可接受；超过 `5` 秒不得直接提交旧信号，必须由当前行情重建新的实时信号意图，重建后仍通过当前价格、风险、止损、目标和扣费后利润检查才可提交；超过 `max_delayed_signal_age_seconds` 或信号自身有效期的旧信号必须阻断，不允许停机后补交几分钟或几小时前的信号。默认配置仍关闭真实提交，只有 `execute_orders=true` 且 `paper_trading_approval=true` 才允许调用模拟账户下单命令。
- M15 长桥实时执行只处理未处理过的实时信号事件；同一个 `signal_id` 一旦已有执行流水，不论当时是提交、阻断还是只读演练，都不会在后续循环里反复重算或补交。若价格行为条件后来仍然成立，必须由新的长桥行情事件重新触发新的 `signal_id`。
- M15 长桥实时信号路由必须感知当前新测试基线：如果信号在清仓窗口内生成，但 `test_epoch` 激活后同一行情事件/价格行为条件仍被当前路由器识别为有效机会，路由器必须重建一条带当前 `test_epoch_id` 的新实时信号，并把原始信号时间写入审计字段；这不是读取本地模拟或补旧单，而是用当前基线重新确认仍成立的长桥实时意图。
- 长桥实时执行必须把本交易日当前测试基线内已提交但账户状态尚未刷新出的模拟买单计入对应资金池的待成交敞口；如果同一资金池内同一标的已有实时提交账本里的待成交买单或本轮已选择买单，新买入必须阻断，防止账户状态延迟导致重复开仓。
- 长桥虚拟资金池占用必须用长桥账户最新订单状态校正，并且必须按当前测试基线全量持仓/挂单计算，不能只看本交易日开盘后的提交记录：已取消、拒绝或过期且未成交的买单不得继续占用资金池；已成交且长桥仍有持仓的买单必须占用对应资金池；卖出成交按数量释放本地虚拟敞口。看板里的单策略仓和统一实验仓 `used_exposure` 与实时风控必须共用同一套账户感知口径，不能继续用旧提交账本裸累计值或日内裸累计值。
- 长桥实时执行必须执行同资金池同标的冷却：同一资金池内同一标的当天亏损卖出后，不再重复开仓；每个策略每日新开仓次数可配置上限，统一实验仓内的 `M10-PA-001` 当前最多 `1` 个新标的。单策略仓不使用低倍率，但仍受每仓总敞口、单标的和单笔风险硬上限约束。卖出请求必须写入稳定状态机，只有长桥账户当前可卖数量大于 `0` 且没有同标的卖出挂单时才允许提交；本地已提交卖单记录只用于短时间防止账户状态延迟造成重复提交，不得永久阻断券商侧已成交、已撤销或已拒绝后的新卖出评估。
- 长桥看板、日报和分仓盈亏口径固定为长桥账户自身数据，字段名必须避免混用：`长桥账户当日盈亏` 优先使用同日 `longbridge profit-analysis --start today --end today` 的 `sum_profit`；`长桥接口持仓今日浮动` 只表示 `portfolio.total_today_pl`；`长桥当前持仓总盈亏` 只表示当前持仓按长桥成本价、数量和当前价计算的浮动盈亏；`长桥交易累计盈亏` 只表示 `profit-analysis by-market US` 的股票交易累计盈亏。不得再输出模糊的 `长桥今日盈亏`、`长桥总盈亏`、`长桥账户总盈亏` 或 `长桥交易总盈亏` 作为活跃看板字段。长桥完整最大回撤必须来自 `m15_longbridge_realtime_equity_curve.jsonl` 的账户权益时间序列，不能用单标的亏损率或本地模拟曲线替代；样本不足时必须显示“样本不足”。长桥接口缺数据时只能显示“无法计算/等待长桥数据”，不得用 `100000`、旧本地模拟账本或旧 `historical_net_profit` 硬算。
- 长桥分仓口径必须和账户口径一致：每个单策略仓和统一实验仓分别输出 `分仓当日盈亏`、`分仓持仓今日浮动`、`分仓当前持仓总盈亏`、`分仓已实现盈亏` 和 `分仓交易累计盈亏`；这些字段只由长桥实际成交、当前长桥持仓和本地归因映射计算。本地 `submitted` 但长桥未成交的请求只能进入未成交诊断，不得进入分仓盈亏、胜率、回撤、已用敞口或策略表现。
- 长桥 App 顶部“当日盈亏”只有在 CLI/API 字段已验证能和 App 页面一致时才可使用对应字段；当前已验证的同日 `profit-analysis` 是 CLI 里最接近账户当日盈亏的候选口径，必须保留源字段名和刷新时间。`portfolio.total_today_pl` 不得冒充 App 顶部当日盈亏，只能标为“接口持仓今日浮动”。总资产和持仓市值优先使用 `portfolio.total_cash + portfolio.market_accounts.US.market_value`，因为该口径与 App 资产页展示更接近；同时保留原始 `overview.total_asset / overview.market_cap` 作为审计字段。
- 长桥订单、分仓、策略表现和胜率必须以长桥真实订单/成交为最终事实源：只有 `Filled` 或可确认部分成交数量的订单进入单策略仓、统一实验仓、策略盈亏、胜率、盈亏比和回撤；本地 `submitted` 流水只作为归因线索和请求审计。`Rejected / Canceled / Expired / 本地未确认订单号` 必须进入 `m15_longbridge_unfilled_order_diagnostics`，不得计入成绩、持仓占用或策略表现。`m15_longbridge_order_reconciliation` 是当前长桥订单对账主产物，必须保留长桥订单号、状态、成交数量、成交价、资金池、运行单元、归因状态和是否计入成绩。
- M12 主看板里的长桥模拟账户板块必须显示长桥面板自己的刷新时间、账户状态刷新时间和盈亏对账刷新时间；本地模拟大看板的 `generated_at` 不得被误用为长桥账户状态时间。非交易窗口如果 M15 已只读刷新账户状态，文案必须说明“账户状态已只读刷新，交易循环等待下一交易日自动运行”，不能把它描述成数据源降级或旧快照。
- M15 长桥实时会话守护器入口为 `scripts/run_m15_longbridge_realtime_session_supervisor.py`，配置为 `config/examples/m15_longbridge_realtime_session_supervisor.json`。它只在配置允许的美股常规交易时段按顺序拉起实时行情采集、实时信号路由、实时账户状态、旧买入挂单清理、清理后账户状态复读、实时持仓退出和实时执行链路；非交易窗口只写“等待交易窗口”状态。该守护器不得手动运行 M12.37 once-mode，不得读取旧快速队列作为下单来源，不得读取本地模拟账本，也不得启用实盘或真实资金。
- M15 长桥实时会话守护器流水是运行审计，不参与下单去重、持仓归因或风控状态恢复；该流水超过保留上限时可自动归档旧行并保留最近状态，避免长期守护导致看板和巡检变慢。执行流水、信号事件和账户状态仍按各自业务语义保留，不能用同一规则随意截断。
- M15 长桥实时会话守护器文本日志只用于人工排查，不参与风控、去重、持仓归因或状态恢复；启动前若日志超过保留上限必须归档旧日志，非交易窗口等待状态不得每轮重复刷同一句日志，避免长期常驻后巡检和看板排查被大日志拖慢。
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
