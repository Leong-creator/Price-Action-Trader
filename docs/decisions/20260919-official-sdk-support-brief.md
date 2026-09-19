# 长桥官方SDK订阅初始化超时：脱敏支持说明（2026-09-19）

本材料供长桥核对订阅请求/响应时序，尚未对外发送。当前行情问题未解决，正式程序未部署、未解锁、未恢复自动启动；真实完整交易日通过0天。本文不包含OAuth、账号资料、trace_id或原始SDK日志。原始材料私有保存，仅可按支持所需范围另行脱敏提供。

## 环境与执行边界

- Linux、CPython3.12、官方 `longbridge==4.5.0`；wheel为 `longbridge-4.5.0-cp312-cp312-manylinux_2_39_x86_64.whl`。
- wheel SHA256：`5387db07db2d29dd52ff6abcd5e888f1442cd0581ad38dc5e51182a0a9cd8daa`；实际加载native模块SHA256：`4af34d03b87402e680630e2e0f5e11612d84ce22ac12a8dcd3a18886d094d185`。环境核验通过，未沿用本地修改包。
- 独立样例执行命令形态为 `<verified-python> -I source.py`，外部排他锁与60秒总期限，逐次确认子进程退出；SDK单请求保留默认，不加项目重试。示例进程不导入项目scripts，不访问账户、订单、日线、K线或策略。
- 采用官方 `Config.from_oauth(oauth)` 默认，未显式覆盖region或endpoint。最后日志显示SDK默认选择 `openapi-quote.longbridge.cn`。这不表示项目账户/历史工具所有helper也零手工端点。
- 官方示例只替换认证占位（标准库读取，私密内容不公开）及symbols；Quote+Trade、初始化后查询为官方公开接口扩展，明确不是原示例全文。
- 全程串行使用同一147只生产集合，不扩容。2026-09-19为周六，Quote首推不能证明交易时段连续性；Trade 0不作休市故障证据。

官方用法依据：[快速开始](https://open.longbridge.com/docs/getting-started)、[行情概览](https://open.longbridge.com/docs/quote/overview)、[订阅](https://open.longbridge.com/zh-CN/docs/quote/subscribe/subscribe)。订阅文档上限500，当前147只一次足够；不凭经验额外分批，也不把500称为已实测容量。

## 8项独立样例时间线

时间均为2026-09-19 UTC，北京时间加8小时；成功样例保留官方sleep(10)，下列总时间不是订阅操作耗时。前7项只有外部时点/回调/异常栈，未额外植入阶段计时。

| 序号及目录简称 | UTC开始—结束 | 总耗时 | 结果 |
|---|---|---|---|
| 1 default-two-quote | 09:30:19.366—09:30:30.422 | 11.056秒 | SPY/QQQ异步Quote，各1首推，exit0 |
| 2 default-147-quote | 09:31:18.399—09:31:49.029 | 30.630秒 | 仅扩大symbols至147，await ctx.subscribe超时，0回调 |
| 3 default-147-quote-sync | 09:34:05.545—09:34:16.349 | 10.804秒 | 官方同步Quote，147只各1首推，exit0 |
| 4 default-147-quote-async-control | 09:35:33.460—09:36:04.189 | 30.730秒 | 与2字节相同源码，订阅超时，0回调 |
| 5 default-147-quote-trade-sync | 09:37:22.951—09:37:33.856 | 10.904秒 | 相对3仅增加Trade类型/回调，147Quote、0Trade，exit0 |
| 6 default-147-quote-async-sync-callback | 09:38:05.790—09:38:36.422 | 30.632秒 | 相对2仅async回调改普通def，订阅超时，0回调 |
| 7 default-147-sync-initialization-queries | 09:42:18.055—09:42:29.060 | 11.005秒 | 相对5加subscriptions与quote(147)，订阅147条均含Quote/Trade，快照147，exit0 |
| 8 default-147-sync-official-logging-008 | 10:05:46.198—10:06:17.029 | 30.831秒 | 与5同源，仅外部启用官方LOG_PATH，订阅超时，0回调 |

所有样例子进程均已退出；超时由SDK订阅调用返回，不是外部60秒期限强杀。第7项stdout多参数输出与回调交错，Quote对象repr计数147，不按行归属证券；订阅记录及集合覆盖单独核验。

## 3项项目接回探针（与独立示例分开）

| 目录 | UTC开始—结束 | 实测 |
|---|---|---|
| project-raw-sync-147-001 | 09:51:48.180—09:52:19.083 | 保留旧50只分批，首请求30.865秒超时，总30.978秒，0回调 |
| project-raw-sync-single147-002 | 09:54:17.840—09:54:47.891 | 仅私有配置50→147，单次订阅0.731秒完成，总30.124秒，147/147；raw/normalized/enqueued/dequeued Quote各147 |
| project-final-raw147-003 | 10:01:32.608—10:02:03.310 | 删除分批循环后的候选，单次147请求30.659秒超时，总30.774秒，0回调 |

三个worker均已退出，无账户/订单访问；第三次失败是对“同步默认＋单次147已修复”的反证，pipeline因此未运行。没有把失败隐藏在成功样例后，也不能仅凭上述对照认定API或分批是唯一原因。

## 官方日志提供的进一步定位

| UTC时点 | 白名单事件 |
|---|---|
| 10:05:46.246759 | creating quote context |
| 10:05:46.247561 | quote context created |
| 10:05:46.568761 | connecting to quote server |
| 10:05:46.722493 | AuthRequest日志 |
| 10:05:46.935078 | 认证响应成功 |
| 10:05:46.935113 | UserQuoteProfileRequest日志 |
| 10:05:46.979768 | UserQuoteProfileResponse成功，subscribe_limit=500 |
| 10:05:46.979897 | SubscribeRequest日志，此后没有成功订阅响应或推送记录 |

核对官方v4.5源码，Subscribe命令6的本地限流为limit10/burst5，每秒补10、初始及最大5，一次请求消耗1，与请求中147只标的数量无关。该RequestTimeout来自request_raw在限流acquire_one完成、内部command_tx.send成功后，等待reply_rx约30秒超时。因此可以收窄为“已过本地限流并入SDK内部发送队列，等待请求完成超时”。**这不是请求已发上网络的证明，也不是服务端没有响应的证明。** 参考 [client.rs请求路径](https://github.com/longbridge/openapi/blob/v4.5.0/rust/crates/wsclient/src/client.rs#L357)、[error.rs错误定义](https://github.com/longbridge/openapi/blob/v4.5.0/rust/crates/wsclient/src/error.rs#L38)。

## 请协助核对

1. 按上述UTC窗口核对订阅请求是否抵达、服务器处理及响应时点；如已响应，协助定位SDK接收、分派与reply完成环节。现有应用层日志不能区分这些位置。
2. 核对同一默认配置/147只集合的成功与失败窗口差异，以及SDK在休市订阅时的预期响应行为；所需额外观测请明确能够区分哪两个原因。
3. 确认官方建议的最小复现及日志字段。当前先停止连接，不继续同条件重试，不变更策略或端点，不部署未经验证的候选。

已排除项目策略/K线作为本次独立样例初始化失败的前置起因，也不是完全无法认证或读取行情档案。尚未排除SDK内部调度/接收、网络、服务端或其他权限细节；不宣称长桥服务全面故障。9月8日故障发生在初始化完成后开盘断流，今天发生在订阅初始化，**尚不能证明两者同根因**。独立import误启动涉及模拟账户只读访问，另见 [事件记录](20260919-runtime-import-start-incident.md)，不计入上述11项授权探针或验收。

## 可复现证据索引

私有归档根名 `20260919-official-baseline/`，每个独立目录保存source.py、run_result.json、私有stdout/stderr和适用的safe_summary.json；有序证券列表固定在源码及inputs.json。公开资料只有脱敏结果，原始日志不得随报告直接转发。官方原始async示例SHA256为 `4ba4ac4b0be05e8ffc1c1a5d7997af95ee03e552f2f95a9d979d84d11690d062`，来源 [v4.5.0官方示例](https://github.com/longbridge/openapi/blob/v4.5.0/examples/python/subscribe_quote_async.py)。实际运行源文件校验如下：

| 独立实验目录 | source.py SHA256 |
|---|---|
| `default-two-quote` | `3dba1f8d797d9307090474ba480ec80f142e7db88247979788e72de5731c34ae` |
| `default-147-quote` | `065d5ff0fe9d6b9e228b56d8a6277701a184eb70a57413d7d2fa51dfeb6c2bb1` |
| `default-147-quote-sync` | `2d1bbf45496b3f876b3d608ff2c0f3f4bfad9500333541154d1bd92bc0605694` |
| `default-147-quote-async-control` | `065d5ff0fe9d6b9e228b56d8a6277701a184eb70a57413d7d2fa51dfeb6c2bb1` |
| `default-147-quote-trade-sync` | `22b624aafead9302158d16dcfa5cb31cde32b081a44de9b5a7eb9639382243e5` |
| `default-147-quote-async-sync-callback` | `83fb42115b57951440f05581a817730a54a77249753e678308f0fc5e516cf07d` |
| `default-147-sync-initialization-queries` | `3b5ba295cf9570b0f4f4a1482ba7f43003f9962fbf50c011ffc29e174357aa5f` |
| `default-147-sync-official-logging-008` | `22b624aafead9302158d16dcfa5cb31cde32b081a44de9b5a7eb9639382243e5` |

项目探针summary.json校验：

| 目录 | SHA256 |
|---|---|
| `project-raw-sync-147-001` | `2651940b6e455bc765109c5e27814314f9c364dbd098026d8fcdcdb287b869ff` |
| `project-raw-sync-single147-002` | `a517516bc5614a55641a0fb75ed465a4569558b0a567dcc750e0d686b21678d1` |
| `project-final-raw147-003` | `a5211364f9adb098eb5f23e6814b7a0d4316af253275a21202dcde2b33bc63d6` |

环境记录为environment-verification.json及source-provenance.json；项目候选源码以candidate-runtime-source-hashes.json和candidate-runtime.patch冻结。聚合脱敏索引见 [官方基线证据](../evidence/20260919-official-baseline-results.json)。没有将离线测试、周末首推或一次查询成功算作真实整场通过。
