# M15 SDK 时间字段归一修复

```yaml
task_id: m15-sdk-timestamp-normalization-20260921
role: constrained implementation and offline verification
branch_or_worktree: codex/fix-linux-official-runtime-20260921
objective: Normalize official SDK local-naive datetimes to aware UTC before IPC so existing parent quote validation can accept valid callbacks
status: success
files_changed:
  - scripts/m15_longbridge_sdk_runtime_lib.py
  - tests/unit/test_m15_sdk_timestamp_normalization.py
  - docs/handoffs/m15-sdk-timestamp-20260921.md
interfaces_changed:
  - sdk_plain_value returns aware UTC for SDK datetime values
  - General strict_event_datetime and quote-state validity checks remain unchanged
commands_run:
  - .venv-m15/bin/python -m unittest tests.unit.test_m15_sdk_timestamp_normalization tests.unit.test_m15_preopen_bar_integrity tests.unit.test_m15_daily_inputs -q
tests_run:
  - 35 tests passed in 0.523 seconds, including 7 dedicated normalization cases
  - Spawn child with TZ=Asia/Shanghai or UTC, actual SDK adapter functions, actual multiprocessing Pipe, actual parent quote-state function
assumptions:
  - SDK datetime input follows official local-naive datetime.fromtimestamp conversion
  - Normalization happens on SDK callback host before payload crosses processes
risks:
  - This fix concerns callbacks already received; it does not explain historical subscription timeout with zero callbacks
  - SDK boundary helper is shared; independent review is required before runtime deployment
qa_focus:
  - Manual review marker: inspect source-boundary scope and parent validation behavior before deployment
  - Future and malformed timestamps must still fail parent checks
  - General naive-input rejection must not be relaxed
rollback_notes:
  - No SDK, system timezone, credentials, strategy, risk threshold or production state changed
next_recommended_action: Parent integrates with official-runtime repairs, independently reviews and performs authorized runtime validation
needs_user_decision: false
user_decision_needed: null
```

## 问题与实际修复

官方 Python SDK 将事件 epoch 转为不带时区的本机时间，使用的是 `PyDateTime::from_timestamp(..., None)`。[官方 5.0.0 时间绑定源码](https://raw.githubusercontent.com/longbridge/openapi/v5.0.0/python/src/time.rs)

现有 `sdk_plain_value` 原样保留这个 datetime，经行情进程消息传给父进程后，`update_live_quote_session_state` 调用通用 `strict_event_datetime`，后者正确拒绝没有时区的输入。因此真实到达的 SDK 回调也可能无法更新父进程报价状态。

修复限定在 **SDK 专用归一边界**：datetime 调用 `astimezone(UTC)`，把 SDK 的本机 naive 时间转换为带时区 UTC；已带时区的 datetime 同样保留其实际时刻并统一为 UTC。没有用 `replace(tzinfo=UTC)` 错贴标签，没有将任何普通字符串默认解释为 UTC，也没有修改父进程严格校验。Decimal 保留原对象，date 仍按原逻辑转为字符串，其他字段和嵌套结构语义不变。

## 验证证据与限制

专用测试在独立 spawn 子进程内设置 `TZ` 并调用 `tzset`，分别模拟 Asia/Shanghai 和 UTC 主机，构造官方 SDK 相同形状的本机 naive 时间字段，通过真实 `sdk_object_to_dict`、真实 multiprocessing Pipe 和真实父进程 `update_live_quote_session_state` 验证：同一 UTC 事件可以更新报价、交易日和五分钟报价快照。父进程与系统时区没有修改。

同一条管道还验证 aware 时间、未来时间和畸形时间。未来/畸形输入仍被父进程拒绝；异常时区转换向外传播失败，不伪造有效时间。通用 strict 校验继续拒绝未经 SDK 边界转换的 naive 输入。所有测试禁止 socket 连接，未导入/实例化官方 SDK、未访问账户或订单、未启动运行主循环。

首次专用测试中两条断言将仓库的 UTC `Z` 表示误写成 `+00:00` 字符串比较；已改为比较解析后的真实时刻，生产代码没有为测试改日期输出格式。定稿的专用、盘前K线及日线输入相关验证共35项通过。

**这不是历史订阅超时的根因结论。** 该错误发生在回调收到之后；此前官方独立示例在订阅完成前超时、回调为0，不能由此解释。修复本身也不代表实机连续行情、K线或策略验收已经通过。高风险运行路径已标记人工复核，仍需独立审查后按本轮授权验证。
