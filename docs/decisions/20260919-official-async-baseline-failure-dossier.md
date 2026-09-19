# 官方异步147只最小示例失败记录与熔断

官方4.5.0原包、Config默认、零项目scripts导入下，147只Quote异步路径三次订阅超时。停止该异步路径探针，不继续同条件连接。此次用户授权的官方基线与前一轮项目封装实验分别留证，旧Failure Dossier不覆盖。

## 已完成对照

以下为UTC 2026-09-19（北京时间加8小时）；进程总耗时包含官方示例成功订阅后sleep(10)，没有注入阶段日志，不能把总耗时当订阅耗时。

| 实验 | 时间与结果 |
|---|---|
| 异步SPY/QQQ Quote | 09:30:19.366—09:30:30.422；11.056秒exit0，各1条首推 |
| 异步147只Quote A | 09:31:18.399—09:31:49.029；30.630秒OpenApiException/request timeout，栈在await ctx.subscribe，回调0 |
| 同步147只Quote B | 09:34:05.545—09:34:16.349；10.804秒exit0，147只各1条首推，stderr 0 |
| 异步147只Quote A复核 | 09:35:33.460—09:36:04.189；30.730秒同阶段失败，回调0；与A源码逐字节相同 |
| 同步147只Quote+Trade扩展 | 09:37:22.951—09:37:33.856；10.904秒exit0，147 Quote首推、Trade 0、stderr 0；周末无Trade不判失败，亦不证明逐笔可持续 |
| 异步context仅改同步回调 | 09:38:05.790—09:38:36.422；30.632秒同阶段失败，回调0；相对A仅async def on_quote改def |

三次异步失败均由SDK订阅调用返回/抛错，不是60秒外部总期限终止。各子进程已退出，实验串行；未访问账户、日线、策略、订单或生产故障锁。

## 结论与未证明事项

- 147只Quote官方同步路径当次可行，异步路径在两次相同源码及一次同步回调对照中失败，支持实现路径相关的诊断方向；不证明SDK内部缺陷、供应商或网络唯一根因。
- 失败无需项目策略、K线或桥接即可复现；仅将回调改为普通def未解决。不能单独归责策略、旧封装或async回调写法。
- 周六首推不能证明盘中连续行情、实时Trade、完整五分钟K线或策略消费；真实完整日仍0天。9月8日初始化后的开盘断流与今天的订阅初始化超时尚未证明同根因。
- 基于同步Quote与Quote+Trade完成的证据，实施单一同步官方QuoteContext候选修复；不保留异步自动回退。账户异步不动，正式部署/解锁/交易恢复仍未发生。

## 证据冻结

私有根目录 `20260919-official-baseline/`，每例保留source.py、run_result.json及私有原始输出；安全摘要另存safe_summary.json。原始异步源码哈希为 `065d5ff0fe9d6b9e228b56d8a6277701a184eb70a57413d7d2fa51dfeb6c2bb1`，同步回调对照源码为 `83fb42115b57951440f05581a817730a54a77249753e678308f0fc5e516cf07d`。

| 失败结果文件 | SHA256 |
|---|---|
| `default-147-quote/run_result.json` | `a18963670bd4e267fc98e57fe1928d1d4c5b6482517c9615d0e6196526fb9283` |
| `default-147-quote-async-control/run_result.json` | `ab89666beeac5f8309cd8d6fed00433b9b094c28ee226f966b2ebcf7c8ccc188` |
| `default-147-quote-async-sync-callback/run_result.json` | `ee193bca6d81fcd92a497775b3bed2d4b4605e0173a73050707db168e668ba48` |

```yaml
failure_dossier:
  task_id: official_async_147_baseline_20260919
  branch_or_worktree: codex/fix-official-example-baseline-20260919
  attempt_count: 3
  failed_commands: [default-147-quote, default-147-quote-async-control, default-147-quote-async-sync-callback]
  failed_tests: [官方异步147只Quote订阅三次超时]
  changed_files: [隔离示例仅认证占位与symbols, 第三次仅回调async改def]
  attempted_fixes: [官方默认配置独立基线, 同步成功后的A-B-A复核, 同步回调单变量对照]
  suspected_causes: [异步SDK调用路径或其与服务端和网络的交互, 内部根因未确认]
  rollback_plan: 不恢复旧异步行情退路，不解除原故障锁
  safest_degraded_option: 保持正式运行与订单停止，实施并复核唯一同步行情候选路径
  decision_needed: 同步候选完成离线测试和隔离实测后独立审查，不再试异步连接
```

## 后续反证（不覆盖上述三次冻结记录）

后续同步单次147只项目候选再次超时；独立同步示例仅打开官方LOG_PATH也在30.831秒订阅超时。因此同步路径曾成功不能证明异步SDK是唯一根因，也不能视同步候选已解决。全部连接实验现已停止，pipeline及部署暂停；最新证据见 [官方支持说明](20260919-official-sdk-support-brief.md)。上述Dossier的同步候选下一步是当时判断，当前以本段及现行计划为准。
