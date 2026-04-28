# M12.11 Read-only Trading Dashboard Snapshot

## 摘要

- Scanner candidates: `12`
- Read-only observation events: `32`
- Skip/no-trade events: `32`
- Cache present symbols: `4` / `147`
- Target-complete cache symbols: `0`
- Paper gate decision: `not_approved`
- PA005 decision: `reject_for_now_after_geometry_review`
- Simulated equity curve refs: `10`

## 边界

- 看板只消费既有只读 / 模拟 artifacts。
- 看板只显示 readonly、hypothetical、simulated 字段。
- 当前不批准 paper trading，也不产生真实资金行为。
