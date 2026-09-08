# Live execution time boundary

The SDK caller supplies an aware live clock to the executor. Signal timestamps
remain unchanged. Each candidate is evaluated using the current time; just
before submission the executor recomputes signal age and checks account snapshot
age, signal expiry and the caller's regular-session condition again. Routing and
position-management delays can no longer disappear behind the bar receipt time.
Expired or unreconfirmed delayed short signals are rejected before capacity I/O.

Offline/replay callers keep their explicit historical clock and cannot thereby
grant the production SDK caller permission to replay historical signals.

The integration branch also limits the shared SDK request gate to a five-second
cycle, reserving its two-second per-request deadline before every network call.
That separate guard bounds cumulative I/O; this change alone does not bound
arbitrary CPU work or prove one-second live P95 latency. Pending writes are never
retried to meet a timing target. Strategy thresholds and position limits do not
change. High-risk execution changes require integration review before deployment.

Verification: five new live-clock tests plus seventy existing executor tests pass
offline. They cover a fresh accepted order, routing delay, snapshot expiry,
session closure and signal expiry before the request. No broker call was made.
