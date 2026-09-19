# M15 行情接收诊断

本说明实现 2026-09-19 用户批准的收敛计划。诊断只提供故障定位证据，不证明长桥服务故障，也不授予订单资格。策略、K 线语义、账户新鲜度和风险限制保持不变。需独立复核后部署。

当前同步候选修复尚未成立且未部署：最终项目raw单次147只再次在SDK订阅超时，pipeline尚未运行并暂停；随后独立同步示例仅启用官方LOG_PATH仍30.831秒超时；现停止连接，整理官方支持材料，不重复变更写法。独立官方示例中同步147只Quote及Quote+Trade完成订阅，异步147只三次超时已熔断；详见 [官方示例基线](20260919-official-example-baseline.md)。这些周末首推不是盘中连续行情证据，也不能证明9月8日断流同根因。

候选 worker 在原始回调入口、规范化、入队、出队及 K 线形成处累计计数，按标的和事件类型分开，保存 UTC 与单调时钟时间。原始回调计数不依赖出队，因此可以区别“没有收到”和“收到但没有处理”。回调内不做文件 I/O；样本只保留最近 64 项元信息，不保存凭证或完整推送。心跳每秒携带快照，生产输出 `m15_quote_pipeline_diagnostics.jsonl` 每 30 秒及退出时保存一份快照。计数进程内累积，进程编号及时间必须一起解读，不能把心跳次数当行情进展。

原生 SDK reader 和内部重连状态明确为 `unknown`。`transport_reader_errors=null` 不表示已经证明无错误，空数组仅用于可观测错误来源。故障状态保存上一份状态快照与其生成时间；快照仅是上次观测，不保证当时全部门禁通过。进程退出后的 `--status` 保留原始故障与细节，另报进程已停止。

## 独立只读探针

以下为探针接口说明，不是当前继续连接指令；当前连接实验及pipeline均已暂停。满足后续有依据实验与独立复核门槛后，使用已核验 `.venv-m15/bin/python` 运行 `scripts/run_m15_longbridge_quote_diagnostic.py`：

```bash
.venv-m15/bin/python scripts/run_m15_longbridge_quote_diagnostic.py \
  --config config/m15_longbridge_marketdata.production.json \
  --symbols SPY.US,QQQ.US --duration-seconds 600 \
  --output-dir /tmp/pat-quote-diagnostic-unique
```

默认 `--mode raw-sdk` 直接观察 SDK 回调。全生产池使用 `--production-universe` 替换 `--symbols`。原始小池、原始147只、处理链路三次探针串行运行；输出目录必须新建或为空，位于工作区和生产输出目录之外。采样时限为 1 至 86400 秒，包含初始化时间。父进程按墙钟监督，即使子进程 SDK/OAuth 同步函数阻塞也会在采样时限加5秒后停止；清理自己的子进程另有有界等待。`phase.json` 保存卡住的阶段，不泄露SDK敏感异常。候选raw-sdk使用同步官方接口，保留SDK默认单请求超时，批次记录 `request_timeout_seconds=null`、`native_request_timeout=sdk_default`；raw父进程只监督采样总时限加5秒，不另施加45秒订阅阶段期限。SDK内部请求不能靠async取消保证终止，超期须终止自己的子进程并确认退出。候选仅一次提交整个行情集合，删除分批配置/循环；请求数量不得超过500，生产池147不变。`phases.jsonl` 和summary保留该次请求的offset/size、等待限时、成功/失败及耗时，历史结果的多批记录只属旧实验，错误保留数值供应商 code、固定 kind、类型、分类和最多8层安全因果链，不输出SDK异常正文或 trace_id；code未知而按关键词归类时明确标为启发式，不能据此断言根因。请求记录同时保存本次公开证券代码列表。先完成环境来源校验，再持有原有跨工作区唯一行情锁并检查旧运行进程；发现占用或孤儿子进程立即拒绝，不杀死他人连接。正式 runtime 同样拒绝遗留孤儿，自己的子进程仍在原 finally 流程回收。

候选raw-sdk探针与生产行情worker统一直接创建一个官方同步 `QuoteContext`，使用官方行情Config默认，只订阅Quote/Trade和检查覆盖；不再使用旧异步行情桥接或自定行情端点。账户/历史工具的helper保持原边界，不声称全项目没有手工端点。所有模式均不访问账户、订单或生产故障文件，不重试。

`--mode pipeline --production-universe --duration-seconds 1800` 仅运行既有行情 worker 和五分钟聚合器。日线缓存只读，同一连接按现有规则初始化，所有诊断写入独立输出目录。父进程消费 heartbeat/bar，复用生产阶段绝对期限（初始化/订阅等使用配置 `subscription_deadline_seconds`，当前45秒，日线上下文使用自身配置时限）、边界5秒期限、源标记和参考行情新鲜度检查；记录真实K线数量和完整边界，不创建策略、账户或交易客户端，不调用正式 run_watch，也不写完整日验收通过文件。

父子进程共享同一个行情锁的 open description，父进程异常退出不会释放仍由子进程持有的锁。Linux 父死亡保护及启动竞态复核进一步保证父进程被强杀时子进程退出。自己的子进程超期可被终止，不杀他人连接。官方无 native close 确认接口，因此只有子进程实际退出后才可运行下一探针，summary 显式记录 worker_process_exited 和 forced cleanup。

`duration_completed` 仅表示完成指定采样窗口，不代表有数据或行情稳定。raw-sdk 不形成 K 线；pipeline 的短时边界证据也不是完整日验收，更不是策略验收。休市无推送不能判成行情故障。

## 证据判读

- 原始回调不增长：继续区分 SDK、连接、网络或权限，不能归因于本地队列。
- 原始回调增长但规范化/入队不增长：检查转换错误或溢出。
- 入队增长而出队停滞：检查处理阻塞与队列深度。
- 出队增长而预期边界无 K 线：检查聚合和交易时段；不自行补造真实实时数据。

官方内部重连不可观测不是额外行情合格证明要求；按连续性、及时性、完整性验收。项目仍不自动重试、切换来源或恢复交易。

错误分类依据：[官方订阅错误码](https://open.longbridge.com/docs/quote/subscribe/subscribe)中的301606限频、301605订阅数量限制，以及[报价错误码](https://open.longbridge.com/docs/quote/pull/candlestick)中的301604无权限。保留未知数值code供支持人员核对，不猜测其含义。
