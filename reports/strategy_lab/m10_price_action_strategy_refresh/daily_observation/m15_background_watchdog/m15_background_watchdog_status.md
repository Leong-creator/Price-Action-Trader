# M15 后台看护状态

- 状态: `healthy`
- 生成时间: `2026-07-01T12:29:34Z`
- 结果: 后台看护已完成：M12.47 与 M15 长桥实时守护器已按 daemon/status/readiness 顺序检查；没有手动运行 M12.37 once。
- 下一次检查间隔: `60` 秒

| 步骤 | 状态 | 耗时(ms) | 摘要 |
|---|---:|---:|---|
| M12.47 守护器自愈拉起 | 0 | 163 | supervisor_already_running pid=9028 |
| M15 长桥实时守护器自愈拉起 | 0 | 57 | 长桥实时链路守护器已在运行，PID=80258 |
| M12.47 守护器状态 | 0 | 3129 | son": "",
  "failure_state": "",
  "failure_reason": "",
  "next_session_start_new_york": "2026-07-01 09:25:00 EDT",
  " |
| M15 长桥实时守护器状态 | 0 | 58 | /home/hgl/projects/Price-Action-Trader/reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m15_long |
| M15 开盘值守验收 | 0 | 60 | "2026-07-01 09:30:00 EDT",
    "seconds_until_next_session": 3622,
    "session_should_run": false,
    "session_started |

## 边界

- 只维护 M12.47 / M15 守护器。
- 不手动运行 M12.37 once。
- 不提交、撤销或修改订单。
- 仍只限长桥模拟账户。
