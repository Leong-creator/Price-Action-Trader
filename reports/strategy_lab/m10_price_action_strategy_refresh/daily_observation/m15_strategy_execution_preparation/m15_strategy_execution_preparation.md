# M15 Strategy Execution Preparation

- Generated at: `2026-05-31T02:39:00Z`
- First batch / second batch / repair / auxiliary: `4/5/9/7`
- First paper order candidate: `M10-PA-004-long-1d`
- Boundary: no credentials, no broker connection, no order submission, no live execution.

## First Batch

| Runtime | Action | Size | Status | Paper scope |
|---|---|---:|---|---|
| M10-PA-004-long-1d | advance_internal_sim | 1.0 | 主推进策略，正常仓位进入下一轮内部模拟 | first_order_candidate_after_user_approval |
| M10-PA-005-1d | risk_limited_advance | 0.25 | 风险受限推进，日线单独判断，不和 5 分钟混合 | excluded_from_first_order |
| M10-PA-005-5m | risk_limited_advance | 0.25 | 风险受限推进，5 分钟单独判断 | excluded_until_broker_blockers_clear |
| M10-PA-008-1d | risk_limited_advance | 0.25 | 风险受限推进，单笔风险上限先固定 | excluded_until_broker_blockers_clear |

## Second Batch

| Runtime | Action | Size | Status |
|---|---|---:|---|
| M10-PA-013-1d | risk_limited_advance | 0.50 | 表现较好，先补新行情账本，不进第一笔长桥模拟账户 |
| M10-PA-013-5m | risk_limited_advance | 0.50 | 过滤弱支撑/阻力失败信号后继续内部模拟 |
| M10-PA-012-5m | risk_limited_advance | 0.50 | 修目标价和止损几何，先跑 1 倍风险目标价影子账本 |
| M10-PA-002-1d | risk_limited_advance | 0.25 | 加强突破质量和回撤控制后继续内部模拟 |
| M10-PA-004-MBF-1d | risk_limited_advance | 0.50 | 作为 PA004 并行变体对照，不覆盖主线 PA004 |

## Repair Queue

| Runtime | Size | Repair plan |
|---|---:|---|
| M10-PA-001-1d | 0.10 | 修入场质量、止损距离、连续亏损控制；账本转正前只做 0.1 倍修复试验 |
| M10-PA-001-5m | 0.10 | 修入场质量、止损距离、连续亏损控制；账本转正前只做 0.1 倍修复试验 |
| M10-PA-002-5m | 0.10 | 修假突破过滤、突破确认、失败后冷却；未修完不进模拟账户 |
| M10-PA-004-MBF-QC-1d | 0.10 | 修确认条件和入场质量；只作为 PA004 质量确认变体 |
| M10-PA-007-1d | 0.10 | 修第二腿图形识别器；没有稳定图形证据前不交易 |
| M10-PA-009-1d | 0.10 | 修弱信号过滤和图形证据；账本转正前低仓位修复 |
| M10-PA-011-5m | 0.10 | 修开盘区间反转高回撤；只允许小仓位试验 |
| M12-FTD-001-baseline-1d | 0.00 | 修趋势过滤和连续亏损保护；先作为对照基准 |
| M12-FTD-001-loss-streak-guard-1d | 0.00 | 修连续亏损保护；不进第一批长桥模拟账户 |

## Auxiliary Modules

| Strategy | Purpose | Standalone trading |
|---|---|---|
| M10-PA-003 | 质量评分和排序模块，给主策略打分 | False |
| M10-PA-006 | 限价入场过滤模块，过滤差入场 | False |
| M10-PA-010 | 图形识别资料模块，帮助视觉策略补证据 | False |
| M10-PA-014 | 目标价计算模块，服务止盈目标 | False |
| M10-PA-015 | 止损和仓位模块，服务风控和数量计算 | False |
| M10-PA-016 | 区间加仓辅助模块，服务已有主策略 | False |
| AI-TRADER-EXTERNAL | 外部参考信号，只做对照，不复制交易，不覆盖本项目判断 | False |

## Monday Acceptance

- `m12_47_alive`: M12.47 守护器存活
- `regular_us_session`: 当前市场窗口为美股常规交易时段
- `m12_37_owned_by_supervisor`: M12.37 只能由 M12.47 自动拉起
- `quote_source`: 行情来源必须为 longbridge_quote_readonly
- `daily_and_5m_complete`: 第一批 50 只日线和当日 5 分钟数据完整
- `m13_current_day_ledger`: M13 生成当天策略账本
- `m14_recompute`: M14 重算内部模拟、修复队列、影子参数和长桥预演
- `no_fallback_or_old_snapshot`: 备用行情或旧快照当天不允许进入长桥模拟账户

## Longbridge Paper Entry Conditions

- 至少 1 次周一正常交易窗口完整刷新通过
- M10-PA-004 的限价单预演通过
- M10-PA-005 和 M10-PA-008 的风控阻断已修复，或明确排除在第一笔模拟订单之外
- 用户单独批准模拟账户令牌注入
- 用户单独批准首次模拟订单
- 未经批准不连接账户、不下单
