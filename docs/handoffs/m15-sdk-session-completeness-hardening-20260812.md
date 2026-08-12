# M15 SDK 五分钟会话完整性修复交接

## 目标

- 消除连续交易日五分钟边界缺失的系统性原因。
- 保持长桥模拟账户、策略合同、仓位和门槛不变。
- 盘后允许补齐审计数据，但绝不冒充实时会话或触发历史订单。

## 已完成

- quote 回调在 SDK `subscribe()` 前启用，首批回调不再被主动丢弃。
- finalized 五分钟K线写入使用 `flush + fsync` 后才进入策略路由。
- `dispatch_completed_rows` 明确拒绝 `context_only` 和 `strategy_dispatch_eligible=false` 行。
- 纽约收盘后先回收实时行情子进程，再由单一 SDK 历史连接做有界补齐；补录记录为 `longbridge_sdk_intraday_recovery`。
- `five_minute_session_coverage` 分开输出真实实时完整度与盘后补齐完整度。
- 收盘后 daily context 刷新保留当日五分钟上下文。
- 健康主进程在纽约 `09:25-16:05` 遇到代码/配置漂移时延迟到盘后重载。
- 视觉影子失败流水和长桥看板已展示精确缺口与双重完整度口径。

## 安全边界

- 仅 `lb_papertrading`。
- 未修改策略门槛、仓位、订单类型或正式测试编号。
- 盘后补录不调用 router/execution，不计为实时影子证据。
- 真实故障恢复不受部署冻结影响。

## 验证

- `python -m py_compile`：通过。
- `tests.unit.test_m15_longbridge_sdk_runtime`、`tests.unit.test_m15_visual_strategy_shadow_session`、`tests.unit.test_m15_longbridge_dashboard`：`184/184` 通过。
- 账户快照、开盘验收、后台看护、实时路由、执行与持仓管理外围回归：`180/180` 通过。
- `git diff --check`：通过。

## 非交易时段实机复核

- SDK 主进程和后台看护均为单实例，实际配置指纹一致，无待重载标记。
- 长桥账户确认为 `lb_papertrading`，账户、持仓、订单、成交和做空容量只读端点全部通过。
- 交易池行情快照 `300/300`、日线 `18000/18000`、账户快照低于 `45s`、正式测试编号 active、模拟订单派发已武装。
- 开盘验收 `14` 项通过、`0` 项失败，仅等待常规交易时段；综合验收 `11` 项通过、`0` 项失败，仅等待常规交易时段。
- 非交易时段没有实时推送，当前快照轮询不作为完整会话证据；下一完整交易日仍需验证 `23400` 根真实五分钟K线。

## 仍需真实市场验收

- 下一完整美股交易日必须达到 `300 × 78 = 23400` 根真实 SDK 五分钟K线。
- `session_complete=true`，不能只依赖 `data_complete_after_recovery=true`。
- 主进程整场不得因源码/配置漂移重启；若行情子进程恢复，必须保留明确原因和缺口边界。

## 回退

- 回退本交接对应提交即可恢复旧行为。
- 不删除现有行情、订单、成交、归因或审计产物。
