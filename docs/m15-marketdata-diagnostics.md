# M15 行情接收诊断

本说明实现 2026-09-19 用户批准的收敛计划。诊断只提供故障定位证据，不证明长桥服务故障，也不授予订单资格。策略、K 线语义、账户新鲜度和风险限制保持不变。需独立复核后部署。

正式 worker 在原始回调入口、规范化、入队、出队及 K 线形成处累计计数，按标的和事件类型分开，保存 UTC 与单调时钟时间。原始回调计数不依赖出队，因此可以区别“没有收到”和“收到但没有处理”。回调内不做文件 I/O；样本只保留最近 64 项元信息，不保存凭证或完整推送。心跳每秒携带快照，生产输出 `m15_quote_pipeline_diagnostics.jsonl` 每 30 秒及退出时保存一份快照。计数进程内累积，进程编号及时间必须一起解读，不能把心跳次数当行情进展。

原生 SDK reader 和内部重连状态明确为 `unknown`。`transport_reader_errors=null` 不表示已经证明无错误，空数组仅用于可观测错误来源。故障状态保存上一份状态快照与其生成时间；快照仅是上次观测，不保证当时全部门禁通过。进程退出后的 `--status` 保留原始故障与细节，另报进程已停止。

## 独立只读探针

使用正式 `.venv-m15/bin/python` 运行 `scripts/run_m15_longbridge_quote_diagnostic.py`：

```bash
.venv-m15/bin/python scripts/run_m15_longbridge_quote_diagnostic.py \
  --config config/m15_longbridge_marketdata.production.json \
  --symbols SPY.US,QQQ.US --duration-seconds 600 \
  --output-dir /tmp/pat-quote-diagnostic-unique
```

全生产池使用 `--production-universe` 替换 `--symbols`。两种探针串行运行；输出目录必须新建或为空，位于工作区和生产输出目录之外。总时限为 1 至 86400 秒，包含初始化时间。先完成环境来源校验，再持有原有跨工作区唯一行情锁并检查旧运行进程；发现占用或孤儿子进程立即拒绝，不杀死他人连接。正式 runtime 同样拒绝遗留孤儿，自己的子进程仍在原 finally 流程回收。

探针直接创建一个官方 `AsyncQuoteContext`，只订阅 Quote/Trade 和检查覆盖，不访问账户、订单或生产故障文件，不重试。每秒在回调外保存诊断，退出保存 summary/environment。官方无 native close 确认接口，因此只有进程实际退出后才可运行下一探针；调用者须确认 PID 消失。`duration_completed` 仅表示完成指定采样窗口，不代表有数据或行情稳定。此探针不形成 K 线；整场 K 线和策略验收仍由正式运行链路提供，休市无推送不能判成行情故障。

## 证据判读

- 原始回调不增长：继续区分 SDK、连接、网络或权限，不能归因于本地队列。
- 原始回调增长但规范化/入队不增长：检查转换错误或溢出。
- 入队增长而出队停滞：检查处理阻塞与队列深度。
- 出队增长而预期边界无 K 线：检查聚合和交易时段；不自行补造真实实时数据。

官方内部重连不可观测不是额外行情合格证明要求；按连续性、及时性、完整性验收。项目仍不自动重试、切换来源或恢复交易。
