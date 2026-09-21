# 2026-09-21 晚间定时测试结果

结论：Windows、WSL两项定时均实际启动，但都未通过窗口验收。Windows已收到真实行情，测试因本地监控读取健康文件异常而中止；WSL在日线请求阶段超时，尚未到实时订阅。不能合并成“两边行情断流”或把策略没运行单列为新根因。复查时没有启动新SDK连接、重试或修改运行程序。

## Windows：接收成功，监控提前终止测试

- 定时外壳21:25:01开始，原生控制器21:25:03启动；21:25:04.117已完成147只Quote/Trade订阅，订阅阶段约0.823秒。
- 原始events共7,170条：2,097条Quote覆盖147只，5,073条Trade覆盖107只。最后事件接收于21:26:16.161798，距控制器终止0.200455秒，不能据此声称长桥已断流。
- 控制器21:26:16.362结束，运行73.258秒，`watchdog_fault / invalid_health_record`。该原因由监控读取或解析health.json的OSError/ValueError路径产生，不是静默判定；本次没有保存具体异常类型，不能进一步断言是权限/文件占用/JSON竞态中的哪一种。
- 最后health仍是合法JSON，status=observing、reason=null、queue_depth=0，最大队列延迟195.985ms。该最后文件不代表此前那一次读取必然成功，不能用它抹去实际监控错误。
- 另有2,258条源时间领先接收时间（Quote637、Trade1,621），最多领先438.832ms；4,791条时间差在0—2000ms，另121条超过2000ms且均为首次Quote。后续1,950条Quote及全部5,073条Trade没有超过2000ms的正时间差。这些是盘前记录的描述性分组，不是regular fresh验收；源时间差也不是独立的网络延迟测量。领先原因仍未证实，不能直接说本机再次偏慢，且它不是invalid_health_record的直接停止原因。既有future容差保持，不修改或追溯改写分类。
- 测试在21:30开盘前已中止，没有完成21:25—21:45窗口。regular_event_count及参考流regular fresh为0属于当时仍盘前的分类，不能说完全没行情，也不能签发正常开盘/整场通过。源码、helper与输入清单均保持，之前的修改未被撤回。

优先修复本地监控状态文件读取的异常处理与证据记录：明确短暂读取失败和持续状态丢失，复现异常路径后做有限容错及最终失败保护；保持真实行情静默、队列和时间阈值。修复和复核后另行安排覆盖真实开盘的Windows测试，不擅自当晚补跑或修改既有失败证据。

## WSL：日线请求超时，未到实时订阅

任务21:50:00启动，主项目诊断21:50:01.315开始，21:50:36.531结束，约35.216秒。worker阶段只有initializing和daily_context，之后OpenApiException被分类request_timeout，外层reason=quote_worker_reported_failure。当前代码先调用官方candlesticks获取日线上下文，再订阅实时Quote/Trade；本次没有daily_context_progress/完成记录或subscribing阶段。

因此日线、报价状态、实时K线、策略判断均0；它们是初始化请求未完成后的结果，不是四个独立故障。不能把盘前case017的subscribe超时阶段直接套到晚间case014。WSL官方环境核验通过、405项固定文件保持；具体网络/SDK/服务端原因仍未证实，后续聚焦初始化请求完成问题，不改策略条件。

## 定时与收尾

定时触发本身有效，Windows→WSL串行执行。两边子进程退出已验证，Windows Job活动进程0、WSL进程组为空；本轮复查也确认没有目标行情进程、锁占用或隔离标记。临时Windows认证已清理，原认证及5份正式保护状态哈希不变，正式生产与订单未恢复。

复查时Windows一次任务已不在任务列表，符合原EndBoundary后1小时删除设置，执行证明仍由已归档started/result记录保留；不以任务消失推断未运行。WSL任务last_run=21:50、last_result=4、NextRun为空，界面的Ready不代表已安排下一次。两项一次机会均已使用，未自动重新安排。

原始证据在项目外20260921-windows-continuity与20260921-linux-runtime-test；Windows原始证据已由外壳归档，Windows端重复副本仍保留待按清单去重。本轮安全汇总、独立Windows复核及收尾核验位于`/home/hgl/project-archives/Price-Action-Trader/20260921-evening-results/`。详细安全字段见[晚间结果](../evidence/20260921-evening-results.json)。真实完整日通过仍0，不能将准备时的文件一致/任务Ready解释成真实运行已经通过。
