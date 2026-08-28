# M15 长桥 SDK 实时运行层

## 入口

- 运行脚本：`scripts/run_m15_longbridge_sdk_runtime.py`
- 正式配置：`config/m15_longbridge_marketdata.production.json`
- 开盘验收：`config/m15_opening_trade_readiness.production.json`
- 后台看护：`config/m15_background_watchdog.production.json`
- SDK版本：`longbridge==4.5.0`

实时数据流为：

`官方SDK报价/逐笔成交推送 -> 五分钟K线 -> 实时策略 -> 快速风控 -> 长桥模拟账户订单`

本地模拟账本、旧快速队列、行情CLI、`longbridge serve` 和M12盘中任务均不是上游。

## 启动顺序

1. 校验项目虚拟环境和官方 SDK 接口。
2. 校验配置只允许官方 SDK 单长连接，且不存在回退、重试或重连参数。
3. 读取并确认 `lb_papertrading` 账户、持仓、订单和成交端点。
4. 创建唯一 `QuoteContext`，先注册报价和逐笔成交回调。
5. 读取147只标的最近60根日线，必须达到8820/8820。
6. 在同一连接中分批订阅147只标的的 `Quote` 和 `Trade`。
7. 查询服务器订阅列表，必须达到147/147。
8. 读取一次147只初始快照，仅建立初始状态。
9. 进入长期推送消费；只有完整实时五分钟K线可以触发策略。

## 运行边界

- 仅允许长桥模拟账户；实盘、真实资金、期权和融资关闭。
- 行情回调只入有界队列。队列溢出视为数据完整性故障，立即停止。
- 五分钟成交量只累计逐笔成交数量，不使用快照累计量。
- 无成交延续K线不得触发开仓。
- 账户快照每15秒由独立SDK上下文刷新；超过45秒关闭新开仓。
- 延迟目标为信号产生到发起SDK订单请求95分位不超过1秒，5秒以内暂可接受；超过5秒必须放弃旧意图，不得补交。
- 订单必须取得长桥订单号；缺订单号只记待确认，不得重发。
- 看板和审计只读取运行状态和实际长桥账户数据，不创建第二行情连接。

## 故障规则

- 订阅调用失败、订阅不足147只、日线不足8820条、初始快照缺失、回调队列溢出、行情静默、边界不完整或子进程退出，均进入 `fault_halted`。
- `fault_halted` 关闭新开仓；看护器只报告，不自动重启。
- 禁止自动重试订阅、自动重连、自动切换端点、快照轮询、CLI回退或旧值继续开仓。
- 修复明确原因后，由人工使用同一正式配置重新启动；故障期间旧信号不得重放。

## 清仓规则

`scripts/run_m15_sdk_validation_flatten.py` 只用于用户明确授权的单次模拟账户清仓：

- 仅在指定纽约交易日和美股常规交易时段执行。
- 单次确认模拟账户、持仓、挂单和官方 SDK 当前行情。
- 任一标的行情缺失、账户不明或持仓方向不明时整批停止。
- 每个持仓只提交一次市价退出请求；失败后不改挂限价、不按成本价代替行情、不重复请求。
- 只有长桥确认持仓、挂单和待确认订单全部为0，才能激活新测试编号。

## 命令

```bash
./.venv/bin/python scripts/run_m15_longbridge_sdk_runtime.py --check \
  --config config/m15_longbridge_marketdata.production.json

./.venv/bin/python scripts/run_m15_longbridge_sdk_runtime.py --daemon --dispatch \
  --config config/m15_longbridge_marketdata.production.json

./.venv/bin/python scripts/run_m15_opening_trade_readiness.py \
  --config config/m15_opening_trade_readiness.production.json

./.venv/bin/python scripts/run_m15_background_watchdog.py --status \
  --config config/m15_background_watchdog.production.json
```

自动启动只调用 `scripts/start_m15_trading_stack_after_boot.sh` 一次，不创建周期性Windows终端任务。

## 验收

非交易时段只验证SDK接口、147/147订阅、8820/8820日线、初始快照、模拟账户和进程稳定性。最终行情验收必须等待一个完整美股交易日达到78/78边界和11466/11466根实时K线，非交易时段探针不能替代该证据。
