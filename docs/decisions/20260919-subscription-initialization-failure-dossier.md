# 147只订阅初始化失败：熔断与证据记录

## 结论与边界

同一147只行情接入任务已连续三次失败，**触发熔断，停止同条件连接尝试**。故障范围已收窄到订阅初始化，尚未进入实时K线或策略阶段；不把缺少K线和策略信号另列为独立根因。

两只股票实时推送可工作、147只历史日线读取成功，说明长桥不是完全不可达；仍不能排除订阅权限、SDK请求处理、网络、上游首推与批量订阅交互。没有确证根因，不称已修复，不称长桥服务全面故障。

## 三次尝试

时间为UTC 2026-09-18，北京时间为次日加8小时。全部为只读诊断，未访问账户或订单，不产生生产验收记录。

| 证据目录 | 时间/耗时 | 结果 |
|---|---|---|
| `raw-147-001` | 16:41:47—16:42:17，30.034秒 | TimeoutError；原始回调记录0，未记录阶段，不能单凭本次定位 |
| `raw-147-phased-002` | 16:43:21—16:43:51，30.134秒 | 记录停在subscribe，TimeoutError，原始回调0；worker已退出、无需强制清理 |
| `pipeline-147-001` | 16:44:24—16:45:24，60.062秒 | 先真实读取147只/8820条日线，无失败、非缓存；随后首批50只订阅报AsyncQuoteBridgeError。订阅进度通知0、回调0、K线0、完整边界0；worker已退出、无需强制清理 |

第三次摘要的外层异常为RuntimeError/quote_worker_reported_failure，worker错误消息保存 `official_sdk_quote_worker_failed` 与 `AsyncQuoteBridgeError`。不能只根据异常类别宣称已找到底层网络或供应商错误。

官方[订阅行情说明](https://open.longbridge.com/zh-CN/docs/quote/subscribe/subscribe)列明订阅标的上限500只；147只未超过该数量上限。该上限不证明具体账户权限、批量请求或每只标的均正常，不能以“147必然超额”结案。

## 证据冻结

以下文件保存在私有归档根目录 `20260919-cleanup/live-diagnostics/`，内容不复制进仓库；本提交冻结其SHA256。任何后续实验使用新目录，不覆盖这三次现场记录。与归档值不一致时不得再将其视为原现场。

| 相对证据文件 | SHA256 |
|---|---|
| `raw-147-001/summary.json` | `e9fc054a0db2989bd3292f605aaf030752f11849244b2f919761aa6a86caf754` |
| `raw-147-phased-002/summary.json` | `d0f21412c9d13b18809e329a2a967ee9313717b49a1450c6b301a831101fb1f0` |
| `raw-147-phased-002/phase.json` | `ff38b32d3c545e3b6a06ea818cd0301d35485d6d93715d8e6840df58eec3cd2f` |
| `pipeline-147-001/summary.json` | `3bd3716e02919e3fce8498f10f7959bd87de9d20c4b1eee4b863a593e0ed836a` |
| `pipeline-147-001/worker_messages.jsonl` | `4f4a83d167a826f460ebdec4d7718feb183230f7abe7998764ad25bf305c3644` |

## 下一项区分实验（尚未执行）

先在隔离代码中补足每个SDK阶段的开始/结束时间、批次标的数量、异常原始信息与当时回调数，并通过禁网测试。独立复核后，仅改变订阅批次大小：固定同一官方环境、端点、147只列表及Quote/Trade类型，从每批2只逐步订阅，最终目标仍是147只；单一连接，不自动重试，首次异常即退出并保存累计覆盖和首个失败批次。

- 小批次能完成全部147只，则问题偏向原首批50只的请求/首推处理，应再由一次有明确对照的实验验证，不能直接称生产已稳定。
- 小批次在固定累计数量或标的处失败，则定位该批次、账户权限或总订阅状态，带时间线交长桥核对；不改策略。
- 即使最小首批也失败，则对照此前两只成功的环境、连接占用及供应商返回证据，不继续重复同条件连接。

本实验须作为新假设、有判据的独立任务经复核后执行；三次失败的原任务保持熔断。未完成诊断和正式复核前，不部署生产、不解除原故障锁、不恢复自动启动或交易。

## Failure Dossier交接

```yaml
failure_dossier:
  task_id: official_sdk_147_subscription_initialization_20260919
  branch_or_worktree: isolated_integration_diagnostics
  attempt_count: 3
  failed_commands:
    - isolated raw SDK diagnostic, 147 symbols, raw-147-001
    - isolated phased raw SDK diagnostic, 147 symbols, raw-147-phased-002
    - isolated pipeline diagnostic, 147 symbols, pipeline-147-001
  failed_tests: [真实147只订阅初始化三次未完成, 无真实完整日通过证据]
  changed_files: [隔离诊断阶段记录, 本文档及本轮状态记录]
  attempted_fixes: [清理旧环境并核验官方SDK, 添加阶段记录, 用真实日线加生产管道对照]
  suspected_causes: [批量订阅或首推处理, SDK请求处理, 订阅权限, 网络或上游订阅服务]
  rollback_plan: 不启用旧行情退路；保存归档证据和原故障锁，程序不部署
  safest_degraded_option: 保持正式行情与订单停止，不使用旧值继续开仓
  decision_needed: 主代理独立复核新的区分实验，禁止同条件重复连接
```
