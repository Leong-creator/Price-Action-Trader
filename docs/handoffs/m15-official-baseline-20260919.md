# 官方独立基线与行情候选改动交接

```yaml
task_id: m15-official-baseline-20260919
role: root_integrator
branch_or_worktree: codex/fix-official-example-baseline-20260919
objective: 按官方文档验证接入并移除旧行情接入逻辑
status: partial
interfaces_changed:
  - 候选行情使用官方OAuthBuilder.build、Config.from_oauth默认配置、QuoteContext
  - 一次订阅整个目标集合的Quote和Trade；删除分批参数和异步行情桥接
  - 超过官方500只上限拒绝，当前生产目标仍为147只
  - Config构造前后拒绝端点及地区环境覆盖，覆盖值不写入错误
  - 阶段ACK及绝对期限由父进程监督，卡死子进程必须回收并确认退出
  - 行情锁继承及父进程死亡保护；普通import不能重新执行正式入口
tests_run:
  - 全集798项中795通过、1过时源码字符串断言失败、2跳过
  - 删除冗余源码断言并增强行为断言后，相关147项全部通过
  - 最终797项为组合覆盖，未宣称重新完整执行797项
  - 离线147乘78等于11466根K线逐条OHLCV与时间断言通过
  - 独立复核包含父死子退出、忽略TERM后的强杀、锁继承、阶段ACK和导入安全
assumptions:
  - 2026-09-19为休市日，首推与初始化查询不证明盘中连续性
risks:
  - 最终项目探针及开启官方日志的独立官方示例仍在订阅请求完成前超时
  - SDK内部、网络和远端服务的最终因果尚未区分
  - 候选改动未部署，pipeline未执行，整场真实验收为0天
  - 独立审查发现并修复导入误启动；真实影响见单独事件记录
qa_focus:
  - 不能以离线测试、一次订阅成功或无订单宣称行情修复
  - 原故障及订单防重保留，不自动恢复或切换数据源
rollback_notes:
  - 不保留旧异步或分批运行选项；历史Git与离线档案只保存成果及证据
next_recommended_action: 用官方日志和最小复现继续核对SDK请求完成链路；证据明确后才恢复项目验证
needs_user_decision: false
```

改动涉及行情生命周期和运行入口，**标记需人工复核后部署**。实现代理、QA和独立审查已完成本轮离线复核；这不替代真实行情验收，也不构成当前部署许可。

证据入口：[完整实验与现状](../20260919-official-example-baseline.md)、[独立示例记录](../evidence/20260919-official-baseline-results.json)、[误启动事件](../decisions/20260919-runtime-import-start-incident.md)。本轮真实结果包含成功与失败，失败反证不得删除。

原始SDK日志可能含鉴权资料，仅留在项目外私有档案。对外材料只使用白名单提取的事件时序、公开接口、版本和文件校验信息。
