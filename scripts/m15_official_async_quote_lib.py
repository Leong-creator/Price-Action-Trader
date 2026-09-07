"""Synchronous facade over one official AsyncQuoteContext and one loop thread.

No SDK context is created at import time. SDK I/O is invoked and awaited only
on the owned loop. Callbacks must only enqueue; never call this bridge in one.
See docs/m15-official-async-quote-bridge.md for lifecycle limitations.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import math
import threading
import weakref
from typing import Any, Callable


class AsyncQuoteBridgeError(RuntimeError):
    """The bridge is closed or irreversibly failed; no retry is performed."""


class AsyncQuoteBridgeTimeout(AsyncQuoteBridgeError):
    """A local wait expired; the remote operation's outcome is unknown."""


class OfficialAsyncQuoteBridge:
    """Own exactly one SDK context; close explicitly or use a context manager.

    Initialization readiness means local context creation, not authenticated
    connection/subscription readiness. All timeout values are in seconds.
    ``sdk`` is an injection point for offline tests; production omits it.
    """

    def __init__(
        self,
        config: Any,
        *,
        init_timeout: float = 10.0,
        request_timeout: float = 10.0,
        close_timeout: float = 5.0,
        sdk: Any = None,
    ) -> None:
        for name, value in (
            ("init_timeout", init_timeout),
            ("request_timeout", request_timeout),
            ("close_timeout", close_timeout),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if sdk is None:
            from longbridge import openapi as sdk

        self._request_timeout = request_timeout
        self._close_timeout = close_timeout
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._callback_local = threading.local()
        self._ready: concurrent.futures.Future[None] = concurrent.futures.Future()
        self._pending: set[concurrent.futures.Future[Any]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown: asyncio.Event | None = None
        self._context: Any = None
        self._callbacks: dict[str, Callable] = {}
        self._failure: str | None = None
        self._cleanup_error: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            args=(sdk, config),
            name="m15-official-async-quote",
            daemon=True,
        )
        self._thread.start()
        try:
            self._ready.result(timeout=init_timeout)
            self._check_open()
        except Exception as exc:
            self._stop(f"initialization failed: {type(exc).__name__}: {exc}")
            self._thread.join(timeout=close_timeout)
            cleanup = "" if not self._thread.is_alive() else "; loop thread cleanup timed out"
            error = (
                AsyncQuoteBridgeTimeout
                if isinstance(exc, concurrent.futures.TimeoutError)
                else AsyncQuoteBridgeError
            )
            raise error(f"{self._failure}{cleanup}") from exc

    def _run(self, sdk: Any, config: Any) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        service = loop.create_task(self._serve(sdk, config))
        try:
            loop.run_until_complete(service)
        except BaseException as exc:
            self._stop(f"loop failed: {type(exc).__name__}: {exc}")
            self._cleanup_error = f"loop failed: {type(exc).__name__}: {exc}"
            if not self._ready.done():
                self._ready.set_exception(AsyncQuoteBridgeError(str(exc)))
        finally:
            self._stop()
            # An unexpected loop.stop must still let the service's shutdown
            # finally block release context/callback references on this thread.
            if not service.done():
                try:
                    loop.run_until_complete(service)
                except BaseException as exc:
                    self._cleanup_error = f"loop cleanup failed: {type(exc).__name__}: {exc}"
            loop.close()
            asyncio.set_event_loop(None)

    async def _serve(self, sdk: Any, config: Any) -> None:
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._shutdown = asyncio.Event()
        try:
            if self._stopping.is_set():
                raise AsyncQuoteBridgeError("closed before initialization")
            # The official factory is synchronous, but must run inside the loop.
            self._context = sdk.AsyncQuoteContext.create(config)
            self._context.set_on_quote(self._callback("set_on_quote"))
            self._context.set_on_trades(self._callback("set_on_trades"))
            self._ready.set_result(None)
            if not self._stopping.is_set():
                await self._shutdown.wait()
        finally:
            self._stop()
            # Keep native callback registration immutable while pushes may be
            # running. Weak forwarders suppress late pushes without SDK setters
            # during shutdown or undocumented None callback arguments.
            self._callbacks.clear()
            tasks = asyncio.all_tasks() - {asyncio.current_task()}
            for task in tasks:
                task.cancel()
            if tasks:
                _, pending = await asyncio.wait(tasks, timeout=self._close_timeout)
                if pending:
                    self._cleanup_error = "SDK awaitables did not finish cancellation"
            # No public SDK close/aclose exists. Dropping this reference is not
            # an acknowledgement that the native transport has finished closing.
            self._context = None

    def _stop(self, failure: str | None = None) -> None:
        with self._lock:
            if failure is not None and self._failure is None:
                self._failure = failure
            self._stopping.set()
            for future in tuple(self._pending):
                future.cancel()
            if self._loop is not None and not self._loop.is_closed():
                try:
                    self._loop.call_soon_threadsafe(self._shutdown.set)
                except RuntimeError:
                    pass

    def _check_caller(self) -> None:
        if threading.current_thread() is self._thread or getattr(
            self._callback_local, "active", False
        ):
            raise AsyncQuoteBridgeError("blocking bridge calls are forbidden in loop/callback")

    def _check_open(self) -> None:
        if self._stopping.is_set():
            raise AsyncQuoteBridgeError(self._failure or "bridge is closed")

    def _discard(self, future: concurrent.futures.Future[Any]) -> None:
        with self._lock:
            self._pending.discard(future)

    async def _dispatch(self, method: str, args: tuple, kwargs: dict) -> Any:
        self._check_open()
        if method in ("set_on_quote", "set_on_trades"):
            self._callbacks[method] = args[0]
            return None
        # Calling the SDK method on the caller thread would bind its Python
        # awaitable to the wrong/no loop. Invocation belongs here too.
        return await getattr(self._context, method)(*args, **kwargs)

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self._check_caller()
        with self._lock:
            self._check_open()
            coroutine = self._dispatch(method, args, kwargs)
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
            except Exception:
                coroutine.close()
                self._stop("failed to schedule SDK request")
                raise
            self._pending.add(future)
            future.add_done_callback(self._discard)
        try:
            result = future.result(timeout=self._request_timeout)
        except concurrent.futures.TimeoutError as exc:
            self._stop(f"{method} timed out; remote outcome unknown")
            raise AsyncQuoteBridgeTimeout(self._failure) from exc
        except Exception as exc:
            self._stop(f"{method} failed: {type(exc).__name__}: {exc}")
            raise AsyncQuoteBridgeError(self._failure) from exc
        self._check_open()
        return result

    def _callback(self, method: str) -> Callable:
        owner = weakref.ref(self)

        def enqueue(symbol: str, event: Any) -> None:
            bridge = owner()
            if bridge is None or bridge._stopping.is_set():
                return
            callback = bridge._callbacks.get(method)
            if callback is None:
                return
            bridge._callback_local.active = True
            try:
                result = callback(symbol, event)
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise TypeError("callback must not return an awaitable")
            except Exception as exc:
                bridge._stop(f"callback failed: {type(exc).__name__}: {exc}")
            finally:
                bridge._callback_local.active = False

        return enqueue

    def set_on_quote(self, callback: Callable[[str, Any], None]) -> None:
        self._register("set_on_quote", callback)

    def set_on_trades(self, callback: Callable[[str, Any], None]) -> None:
        self._register("set_on_trades", callback)

    def _register(self, method: str, callback: Callable) -> None:
        if not callable(callback) or inspect.iscoroutinefunction(callback):
            raise TypeError("callback must be a synchronous enqueue function")
        self._call(method, callback)

    def candlesticks(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("candlesticks", *args, **kwargs)

    def subscribe(self, symbols: Any, sub_types: Any) -> None:
        self._call("subscribe", symbols, sub_types)

    def subscriptions(self) -> Any:
        return self._call("subscriptions")

    def quote(self, symbols: Any) -> Any:
        return self._call("quote", symbols)

    def check_health(self) -> None:
        """Raise on local failure/closed/stopped loop; perform no SDK I/O.

        This is not a connection, subscription or reconnect health probe.
        """
        with self._lock:
            self._check_open()
            if (
                not self._thread.is_alive()
                or self._loop is None
                or not self._loop.is_running()
                or self._loop.is_closed()
            ):
                self._stop("quote loop/thread is not running")
                raise AsyncQuoteBridgeError(self._failure)

    def close(self) -> None:
        """Reject requests, cancel awaitables, drop context and join our thread.

        This does not prove native WebSocket closure or disable SDK reconnects.
        A timeout/error is reported, never hidden as successful cleanup.
        """
        self._check_caller()
        self._stop()
        self._thread.join(timeout=self._close_timeout)
        if self._thread.is_alive():
            raise AsyncQuoteBridgeTimeout("loop thread cleanup timed out")
        if self._cleanup_error is not None:
            raise AsyncQuoteBridgeError(self._cleanup_error)

    def __enter__(self) -> OfficialAsyncQuoteBridge:
        self._check_open()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
