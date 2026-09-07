# Official Async Quote Bridge

## Scope

This isolated, unintegrated adapter owns one background Python asyncio loop and
calls `AsyncQuoteContext.create(config)` exactly once. It does not adopt an
already-created synchronous context. Replace the worker's construction site;
never construct both contexts. No worker/runtime or order behavior is changed
by this patch. Integration requires manual review and read-only validation.

## Official SDK 4.5.0 Evidence

- [Python synchronous quote binding](https://github.com/longbridge/openapi/blob/v4.5.0/python/src/quote/context.rs):
  `candlesticks` calls the blocking Rust context without `detach/allow_threads`.
- [Blocking quote implementation](https://github.com/longbridge/openapi/blob/v4.5.0/rust/src/blocking/quote.rs)
  and [blocking runtime](https://github.com/longbridge/openapi/blob/v4.5.0/rust/src/blocking/runtime.rs):
  `BlockingRuntime::call` waits on `reply_rx.recv()`.
- [Python asynchronous binding](https://github.com/longbridge/openapi/blob/v4.5.0/python/src/quote/context_async.rs):
  `create` is a synchronous factory; I/O uses `future_into_py` with awaited Rust
  requests. Callback setters are synchronous.
- [PyO3 threading](https://pyo3.rs/main/parallelism): explicit detachment permits
  other Python threads during blocking native work. A Python daemon thread does
  not fix a native method that retains the GIL.

The installed 4.5.0 `openapi.pyi` agrees with the public async factory and method
signatures. No public sync-to-async view/clone or explicit close/aclose exists.
The bridge invokes SDK methods inside a running loop, then awaits their results.
Its caller waits on a concurrent Future using a threading condition, allowing
other Python threads to run. The calling thread itself remains blocked: use a
background refresh caller when the worker's main loop must keep progressing.

## Integration Sketch

```python
from longbridge import openapi as sdk
from scripts.m15_official_async_quote_lib import OfficialAsyncQuoteBridge

# config is the existing authorized SDK Config. Do not create QuoteContext.
with OfficialAsyncQuoteBridge(
    config, init_timeout=10.0, request_timeout=5.0, close_timeout=5.0
) as quote:
    quote.set_on_quote(lambda symbol, event: quote_queue.put_nowait((symbol, event)))
    quote.set_on_trades(lambda symbol, event: trade_queue.put_nowait((symbol, event)))
    quote.subscribe(symbols, [sdk.SubType.Quote, sdk.SubType.Trade])
    subscriptions = quote.subscriptions()
    snapshot = quote.quote(symbols)
    bars = quote.candlesticks(
        symbols[0], sdk.Period.Day, 30, sdk.AdjustType.NoAdjust,
        sdk.TradeSessions.Intraday,
    )
    # Existing worker processing and subscription-type verification stay here.
    # Call once on EVERY worker loop iteration, even without incoming pushes.
    quote.check_health()
```

This is documentation only, not an executed connection check. `subscribe` has
the official two-argument signature; the bridge invents no `is_first_push` knob.
Callback payloads are passed unchanged, with no trade filtering or deduplication.

## Failure and Lifecycle Contract

- Initialization timeout covers local factory completion, not authentication or
  a healthy connection. Subscription/snapshot validation remains the caller's
  responsibility. Timeouts must be finite and positive.
- Every request timeout or SDK error permanently fails the instance, rejects
  subsequent calls, cancels outstanding waits and starts cleanup. There is no
  retry/recreation. Late results cannot reopen the instance or be published as a
  successful response after failure is observed. The remote outcome is unknown.
- Callback errors (including a full enqueue queue) fail the instance. Sync calls
  from either the owned loop or callback are forbidden to avoid deadlock.
  Callbacks must be fast, synchronous enqueue functions. A callback already
  running at shutdown cannot be preempted. Future callbacks are ignored.
- `check_health()` performs no SDK I/O: it raises immediately for an observed
  callback/request fault, a closed bridge, a stopped loop or a dead loop thread.
  Call it on every worker loop iteration. It does not detect a hung-but-running
  loop, native transport close/reconnect or remote subscription health.
- Native callback forwarders are registered once during initialization, before
  subscription. Public callback registration updates local targets on the loop.
  Weak references avoid retaining the bridge; shutdown suppresses forwards and
  clears application callback targets without calling native setters during an
  in-flight push or relying on undocumented `None` setter arguments.
- `close()` is idempotent, rejects requests, cancels Python awaitables,
  clears callback targets, drops the owned context reference and joins the loop
  thread. Cleanup failures/timeouts raise; they are not silently treated as
  success. Always close in `finally` or a context manager.
- Python cannot forcibly kill a blocked thread or preempt native code retaining
  the GIL. A stuck constructor/cleanup or noncooperative awaitable can exceed a
  cleanup deadline; a daemon thread is not evidence of successful reclamation.
- Official SDK 4.5.0 exposes no explicit close/aclose or native-transport join.
  Dropping references and canceling awaitables does not acknowledge cancellation
  of remote I/O or immediate WebSocket closure. Internal SDK automatic reconnect
  is unchanged and cannot be disabled/proven absent via this adapter. This is
  one context, not a guarantee of zero reconnects.
- Deadlines, stale-data blocking, subscription validation and parent watchdogs
  remain required. This adapter neither arms orders nor makes readiness claims.

## Offline Verification

```bash
/home/hgl/projects/Price-Action-Trader/.venv/bin/python -B -m unittest \
  tests.unit.test_m15_official_async_quote -v
```

Tests inject a FakeAsyncSDK and never import or construct an actual SDK context.
They require a running loop at SDK method invocation, check one factory call,
slow async I/O with concurrent Python/loop heartbeats, timeout/error fail-closed,
callback behavior, pending-call cancellation, startup failure/timeout and thread
cleanup. Passing fake tests does not establish live connectivity or native
transport closure. Rollback is to omit/revert this standalone adapter patch;
do not restore a known GIL-blocking refresh as a fallback.

Verified on 2026-09-07: 18 adapter tests plus 132 existing quote/runtime tests
passed (150 total). The adapter suite also passed 20 consecutive rounds (360
executions) with `socket.socket.connect/connect_ex` patched to reject network
access and thread counts returning to baseline after every round. No real SDK
context was created. Worker integration and read-only machine validation are
pending with the main agent; no user decision or additional permission is
needed for this isolated component.
