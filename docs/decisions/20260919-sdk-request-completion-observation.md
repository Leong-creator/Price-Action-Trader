# 官方SDK请求完成链路排查（2026-09-19）

## 本轮范围

用户在收到“官方样例仍订阅超时”的结果后要求继续。维持官方 `longbridge==4.5.0`、默认Config、147只一次订阅、原有股票列表及Quote/Trade类型；不改策略，不升级SDK，不分批，不切端点或代理。此前8项独立样例与3项项目探针全部作为历史证据保留，本轮不是恢复同条件重试。

## 官方用法与发布核对

1. 已保存8个实际执行样例的同步/异步调用关系均正确。异步样例使用 `await build_async`、普通 `AsyncQuoteContext.create` 和 `await subscribe`；官方原始async样例与v4.5.0逐字节一致。没有发现需要以重新试跑纠正的 `await create` 错误。
2. 官方5.0.0已于2026-09-14发布，但发布说明没有本次订阅超时的定向修复。v4.5.0至v5.0.0的Python quote同步/异步绑定、push/async_callback及Rust quote Core、WS client、blocking runtime七个文件逐字节相同。未穷尽构建依赖差异，不能宣称两个版本的二进制行为完全一致；目前没有据此升级的证据。
3. 旧版本的其他死锁/销毁后重连问题与当前进入subscribe后、零回调的失败条件不同，不能借用为本案根因。

来源：[官方5.0.0发布](https://github.com/longbridge/openapi/releases/tag/v5.0.0)、[固定版本CHANGELOG](https://github.com/longbridge/openapi/blob/v5.0.0/CHANGELOG.md)、[版本比较](https://github.com/longbridge/openapi/compare/v4.5.0...v5.0.0)、[PyPI发布元数据](https://pypi.org/pypi/longbridge/json)、[官方async示例](https://github.com/longbridge/openapi/blob/v4.5.0/examples/python/subscribe_quote_async.py)。搜索缓存可能早于直接发布元数据，本轮使用固定tag及直接元数据判定。

## 新识别的日志盲区

- [Python同步subscribe](https://github.com/longbridge/openapi/blob/v4.5.0/python/src/quote/context.rs#L131)未显式释放GIL，但Rust请求处理有[独立多线程runtime](https://github.com/longbridge/openapi/blob/v4.5.0/rust/src/runtime.rs#L7)，Python回调在[独立线程](https://github.com/longbridge/openapi/blob/v4.5.0/rust/src/blocking/runtime.rs#L32)。不能把Python等待直接解释为此次网络请求死锁。
- [quote Core的订阅处理](https://github.com/longbridge/openapi/blob/v4.5.0/rust/src/quote/core.rs#L478)会等待订阅响应，期间不消费自己的推送队列。因此“没有Core parsed push日志”不等于“WS或网络没有收到首推”。
- [底层WS响应处理](https://github.com/longbridge/openapi/blob/v4.5.0/rust/crates/wsclient/src/client.rs#L199)直接按request_id完成请求，不经过Python回调或Core推送处理。推送进入无界队列，不会因Core暂未消费而反压此响应路径。
- [内部入队及30秒等待](https://github.com/longbridge/openapi/blob/v4.5.0/rust/crates/wsclient/src/client.rs#L357)与[真正socket发送](https://github.com/longbridge/openapi/blob/v4.5.0/rust/crates/wsclient/src/client.rs#L167)是不同边界。此前RequestTimeout只证明已经入内部队列并等待完成超时。

以上是源码边界核对，不是现场根因证明。线程处于futex等待不能自动称为GIL死锁；TLS/TCP字节计数也不能识别某条订阅请求或响应。

## 新增观测设计

保留此前成功与失败的相同同步Quote+Trade源文件，SHA256 `22b624aafead9302158d16dcfa5cb31cde32b081a44de9b5a7eb9639382243e5`。示例不导入项目代码。旧集成工作区已归档，改用当前候选的已核验官方环境，native模块仍为相同哈希；这项解释器路径变化明确登记，不能称所有环境条件逐字节未变。

外部观察器只为本次子进程记录匿名连接标识、TCP收发/确认/重传计数、收发队列和线程等待分类。它不抓包、不解密、不读取鉴权载荷、不保存其他进程连接，不修改系统代理；原始SDK日志和标准输出/错误只保存在项目外私有目录。单连接锁、父进程死亡保护、60秒外部期限和实际子进程退出检查均在外层；不改变SDK请求逻辑。

源码、输入、环境核验及观测产物放在私有 `/home/hgl/project-archives/Price-Action-Trader/20260919-request-observation/`。观察器必须先经纯本地TCP离线测试及独立审查，才可由主代理执行一次真实只读样例。

## 结果

观察器的7项纯本地测试及独立复核通过，覆盖目标PID过滤、载荷不落盘、阻塞采样绝对期限、TERM/KILL回收、父进程死亡后子进程退出及锁释放。主代理随后只运行一次case009：UTC **11:20:26.813383—11:20:57.847208**，总31.034秒，SDK在subscribe返回request timeout，Quote/Trade回调均0；不是60秒外部强杀。原样源码校验不变，子进程exit1且实际退出，行情锁可取得，主线5份保护状态哈希不变。

官方日志显示认证于11:20:27.624094完成，行情档案于27.674697完成，SubscribeRequest于27.674889记录；之后没有成功订阅响应日志。系统侧155次采样均成功，记录两个匿名连接，不能只凭端口把它们一一认领为具体SDK请求。

| 唯一持续443连接的采样开始时点（UTC） | 已发送字节 | TCP确认字节 | 已接收字节 |
|---|---:|---:|---:|
| 11:20:27.415766 | 575 | 576 | 5505 |
| 11:20:27.616032 | 689 | 690 | 5786 |
| 11:20:27.816247 | 1985 | 1986 | 6637 |
| 11:20:57.646507 | 1985 | 1986 | 6637 |

443连接共152个样本，状态均ESTAB、收发队列均0；末段150个样本跨29.830260秒，字节及段计数不增长。**27.616032至27.816247这一采样间隔同时覆盖认证响应、行情档案请求/响应和订阅请求，因此其增量不能全部归属订阅。** TCP ACK仅表示对端TCP确认，不能证明长桥应用服务收到或处理了command6，也不能证明没有中间节点。

另一个端口10808连接在76次样本中出现，收发计数于11:20:27.215468后不增长，最后出现为11:20:42.030900；不据此判断具体请求归属。未提供retrans、bytes_retrans、unacked、lost字段，不能补成实测0。线程末态为21条futex等待和2条事件等待，CPU计数很低，不支持持续CPU忙等；不能把futex直接认定为GIL或SDK死锁。

现在能够排除“整个过程完全没有TCP进展”的解释，也没有观察到持续内核收发队列积压。仍无法区分订阅未实际发送、只到中间节点、服务端未处理/未响应、以及SDK已读到数据但未完成正确响应匹配。原始观测与白名单结果均私存，聚合结果见 [系统观测证据](../evidence/20260919-request-observation-result.json)。

本次结束后没有继续SDK连接。累计为9项独立样例及3项项目探针，仍未修复、未部署、真实完整交易日0天。pipeline、故障解锁、自动启动保持暂停。

## 下一步所需证据

优先请长桥核对上述UTC窗口中command6的request_id、服务端接收时点、处理结果及响应发送时点。已有本地代理/路由记录若能对应该连接，可作为补充；不凭代理存在认定其为根因，不改变代理配置或再试端点。

本轮补充的只读检查确认域名解析为公网地址，未见本次DNS查询返回保留测试网段；这不能证明当时连接路径完全相同。现有10808监听进程为sing-box，父进程为v2rayN，但当前Windows查询权限不能读取其命令行/可执行路径，无法定位正在使用的配置和日志文件。没有扫描其他用户目录、启用新日志或修改代理。现有日志是否开启、是否包含该窗口记录均为未知，不能写成“没有错误日志”或认定代理为原因。

若官方确认未收到请求，再定位发送/中间网络；若确认已回复，再定位回程及SDK响应匹配；若官方处理未完成，则由官方定位服务端条件。取得这项区分证据前，没有理由继续改策略、分批、盲升版本或重跑直至成功。新的脱敏支持包在私有归档 `sanitized-support-with-case009.zip`，尚未外发；不把本地准备材料等同已提交供应商或已修复。
