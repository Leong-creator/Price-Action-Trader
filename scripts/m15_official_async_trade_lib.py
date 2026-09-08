"""Bounded facade over one official AsyncTradeContext, without quote contexts.

The caller must supply a paper-only SDK Config and verify lb_papertrading before
dispatch. Request deadlines bound local waits, not remote execution: a timed-out
write may have executed. Never retry it, even after constructing another bridge.
No public native close acknowledgement exists; close only joins our loop thread.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import math
import threading
import time
from collections import deque
from typing import Any


class AsyncTradeBridgeError(RuntimeError):
    """Closed or irreversibly failed bridge; no automatic rebuild or retry."""


class AsyncTradeBridgeTimeout(AsyncTradeBridgeError):
    """Local deadline expired; a remote write's outcome is unknown."""


class TradeRequestNotSent(AsyncTradeBridgeError):
    """Admission refused before calling the SDK, so there is no remote write."""


class BoundedTradeRequestGate:
    """Preserve the 30/30s budget without sleeping on the runtime thread.

    Share one gate across both paper and flatten clients. A refused request is
    not automatically retried; only a later fresh decision can be admitted.
    """

    def __init__(self, *, max_calls: int = 30, window_seconds: float = 30.0,
                 monotonic_clock: Any = time.monotonic) -> None:
        if max_calls <= 0 or not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("trade admission limits must be positive")
        self._max_calls = max_calls
        self._window = window_seconds
        self._clock = monotonic_clock
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def call(self, callback: Any) -> Any:
        if not self._lock.acquire(blocking=False):
            raise TradeRequestNotSent("trade admission busy; request not sent")
        try:
            now = self._clock()
            while self._calls and now - self._calls[0] >= self._window:
                self._calls.popleft()
            if len(self._calls) >= self._max_calls:
                raise TradeRequestNotSent("trade rate budget exhausted; request not sent")
            self._calls.append(now)
        finally:
            self._lock.release()
        return callback()


class OfficialAsyncTradeBridge:
    """Invoke and await all SDK I/O on one owned background loop.

    create() is the official synchronous *factory*, not a synchronous network
    operation. Blocking TradeContext methods and asyncio.to_thread are not used.
    SDK errors poison the instance. close() is explicit and idempotent.
    """

    def __init__(self, config: Any, *, sdk: Any = None, init_timeout: float = 3.0,
                 request_timeout: float = 0.5, close_timeout: float = 1.0) -> None:
        for value in (init_timeout, request_timeout, close_timeout):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("timeouts must be finite and positive")
        if sdk is None:
            from longbridge import openapi as sdk
        self._request_timeout = request_timeout
        self._close_timeout = close_timeout
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._ready: concurrent.futures.Future = concurrent.futures.Future()
        self._pending: set[concurrent.futures.Future] = set()
        self._loop = None
        self._shutdown = None
        self._context = None
        self._failure = ""
        self._cleanup_error = ""
        self._thread = threading.Thread(target=self._run, args=(sdk, config),
                                        name="m15-official-async-trade", daemon=True)
        self._thread.start()
        try:
            self._ready.result(timeout=init_timeout)
            self.check_health()
        except Exception as exc:
            self._stop(f"initialization failed: {exc}")
            self._thread.join(timeout=close_timeout)
            error = AsyncTradeBridgeTimeout if isinstance(exc, TimeoutError) else AsyncTradeBridgeError
            raise error(self._failure) from exc

    def _run(self, sdk: Any, config: Any) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve(sdk, config))
        except BaseException as exc:
            self._stop(f"trade loop failed: {exc}")
            if not self._ready.done():
                self._ready.set_exception(AsyncTradeBridgeError(str(exc)))
        finally:
            self._stop()
            loop.close()
            asyncio.set_event_loop(None)

    async def _serve(self, sdk: Any, config: Any) -> None:
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._shutdown = asyncio.Event()
        try:
            if self._stopping.is_set():
                raise AsyncTradeBridgeError("closed before initialization")
            self._context = sdk.AsyncTradeContext.create(config)
            self._ready.set_result(None)
            if not self._stopping.is_set():
                await self._shutdown.wait()
        finally:
            self._stop()
            tasks = asyncio.all_tasks() - {asyncio.current_task()}
            for task in tasks:
                task.cancel()
            if tasks:
                _, pending = await asyncio.wait(tasks, timeout=self._close_timeout)
                if pending:
                    self._cleanup_error = "SDK awaitables did not finish cancellation"
            self._context = None

    def _stop(self, failure: str = "") -> None:
        with self._lock:
            if failure and not self._failure:
                self._failure = failure
            self._stopping.set()
            for future in tuple(self._pending):
                future.cancel()
            if self._loop is not None and not self._loop.is_closed():
                try:
                    self._loop.call_soon_threadsafe(self._shutdown.set)
                except RuntimeError:
                    pass

    def check_health(self) -> None:
        """Local loop health only, without a network request."""
        with self._lock:
            if (self._stopping.is_set() or not self._thread.is_alive()
                    or self._loop is None or not self._loop.is_running()):
                raise AsyncTradeBridgeError(self._failure or "trade bridge closed")

    async def _dispatch(self, method: str, args: tuple, kwargs: dict) -> Any:
        self.check_health()
        return await getattr(self._context, method)(*args, **kwargs)

    def _discard(self, future: concurrent.futures.Future) -> None:
        with self._lock:
            self._pending.discard(future)

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if threading.current_thread() is self._thread:
            raise AsyncTradeBridgeError("blocking bridge call from owned loop")
        with self._lock:
            self.check_health()
            # Reject contention instead of building an unbounded queue of writes.
            if self._pending:
                raise AsyncTradeBridgeError("trade request already in flight")
            coroutine = self._dispatch(method, args, kwargs)
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
            except Exception:
                coroutine.close()
                self._stop("failed to schedule trade request")
                raise
            self._pending.add(future)
            future.add_done_callback(self._discard)
        try:
            result = future.result(timeout=self._request_timeout)
        except concurrent.futures.TimeoutError as exc:
            self._stop(f"{method} timed out; remote outcome unknown")
            raise AsyncTradeBridgeTimeout(self._failure) from exc
        except Exception as exc:
            self._stop(f"{method} failed: {exc}")
            raise AsyncTradeBridgeError(self._failure) from exc
        self.check_health()
        return result

    def today_orders(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("today_orders", *args, **kwargs)

    def account_balance(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("account_balance", *args, **kwargs)

    def submit_order(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("submit_order", *args, **kwargs)

    def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("cancel_order", *args, **kwargs)

    def replace_order(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("replace_order", *args, **kwargs)

    def order_detail(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("order_detail", *args, **kwargs)

    def estimate_max_purchase_quantity(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("estimate_max_purchase_quantity", *args, **kwargs)

    def close(self) -> None:
        if threading.current_thread() is self._thread:
            raise AsyncTradeBridgeError("cannot join own loop thread")
        self._stop()
        self._thread.join(timeout=self._close_timeout)
        if self._thread.is_alive():
            raise AsyncTradeBridgeTimeout("trade loop cleanup timed out")
        if self._cleanup_error:
            raise AsyncTradeBridgeError(self._cleanup_error)

    def __enter__(self) -> OfficialAsyncTradeBridge:
        self.check_health()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
