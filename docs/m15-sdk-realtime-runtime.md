# M15 长桥 SDK 实时运行层

## 目的

M15 的长桥模拟账户实时链路需要由长桥 SDK 的行情推送驱动：实时行情或成交推送 -> 五分钟 K 线完成 -> 实时信号 -> 快速风控 -> 长桥模拟订单请求。它不读取本地模拟账本，也不使用旧快速队列作为下单来源。

SDK 行情运行层的入口是 `scripts/run_m15_longbridge_sdk_runtime.py`，配置为 `config/examples/m15_longbridge_sdk_runtime.json`。它将最终 K 线写入现有 `m15_realtime_market_events.jsonl` 契约，因此路由、执行、看板与审计产物不需要改变字段协议。

## 运行边界

- 仅允许 `lb_papertrading` 模拟账户；实盘、真实资金、期权和融资保持关闭。
- 行情使用长桥 SDK 订阅；下单复用持久 SDK 交易客户端，不允许每笔订单启动 CLI 子进程。
- 历史订单、成交对账、盈亏统计与日报继续在慢路径执行，不能阻塞实时订单处理。
- 实时事件文件在热路径只追加写入；每分钟心跳压缩为最近 20,000 条。实时路由只读取最近 4,096 条事件，不扫描整个历史文件。
- `1` 秒是信号产生到发起模拟订单请求的优化目标，`5` 秒内仍可接受；超过后必须用当前行情重新确认，不能补交旧信号。

## 启用前置条件

1. 在项目虚拟环境安装 `requirements-runtime.txt` 中锁定的 SDK 版本。
2. 将 OAuth SDK `client_id` 写入 `~/.config/price-action-trader/longbridge_sdk_client_id`，并在浏览器完成该客户端的授权。
3. 先运行 `python scripts/run_m15_longbridge_sdk_runtime.py --check`。它必须显示 SDK 和 OAuth 前置条件可用。
4. 通过模拟客户端集成验证后，才能把实际 M15 守护器从 CLI K 线轮询切换到 SDK 常驻运行层。切换时必须停止旧行情采集器，禁止两个来源同时写入同一事件文件。

当前仓库已完成事件契约、SDK 客户端适配、订单号解析和离线测试；SDK 包下载与 OAuth 客户端授权未完成前，生产模拟下单链路不得切换。
