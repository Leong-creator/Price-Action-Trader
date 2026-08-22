# M15 market-data observability

- Realtime completeness and post-close research repair are separate facts. A repaired final dataset never changes realtime order eligibility.
- The production acceptance gate is versioned as `m15_marketdata_integrity_gate_v1.json`; old readonly evidence cannot satisfy it.
- One complete regular session requires 78 on-time boundaries, 147 rows per boundary (11,466 rows), zero incomplete or late boundaries, one quote-worker generation, an account snapshot age below 45 seconds and pipeline p95 at or below one second.
- The dashboard exposes the deployment commit and manifest, transport, subscription hash, connection generation, SPY/QQQ heartbeat, boundary results and process resources.
- One accepted complete session permits the next trading day to resume paper entries. Three consecutive accepted sessions are required before the transport is called stable or the 300-symbol rollout starts.
