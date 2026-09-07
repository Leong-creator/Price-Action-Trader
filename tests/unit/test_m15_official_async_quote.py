from __future__ import annotations

import asyncio
import gc
import queue
import threading
import time
import unittest
import weakref
from types import SimpleNamespace

from scripts.m15_official_async_quote_lib import (
    AsyncQuoteBridgeError,
    AsyncQuoteBridgeTimeout,
    OfficialAsyncQuoteBridge,
)


class FakeAsyncSDK:
    """Offline SDK: like PyO3, methods need a loop at invocation, not just await."""

    def __init__(self):
        self.created = 0
        self.context = None
        self.calls = []
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.delay = 0
        self.error = None
        self.create_error = None
        self.create_gate = None
        self.create_started = threading.Event()
        self.AsyncQuoteContext = SimpleNamespace(create=self.create)

    def QuoteContext(self, *_args):
        raise AssertionError("sync context forbidden")

    def create(self, config):
        self.created += 1
        self.loop = asyncio.get_running_loop()
        self.thread = threading.get_ident()
        self.config = config
        self.create_started.set()
        if self.create_gate is not None:
            self.create_gate.wait(2)
        if self.create_error is not None:
            raise self.create_error
        self.context = FakeContext(self)
        return self.context


class FakeContext:
    def __init__(self, sdk):
        self.sdk = sdk
        self.callbacks = {}

    def check_loop(self):
        assert asyncio.get_running_loop() is self.sdk.loop
        assert threading.get_ident() == self.sdk.thread

    def set_on_quote(self, callback):
        self.check_loop()
        self.callbacks["quote"] = callback

    def set_on_trades(self, callback):
        self.check_loop()
        self.callbacks["trades"] = callback

    def request(self, name, *args, **kwargs):
        self.check_loop()
        self.sdk.calls.append((name, args, kwargs))

        async def response():
            self.sdk.started.set()
            try:
                await asyncio.sleep(self.sdk.delay)
            except asyncio.CancelledError:
                self.sdk.cancelled.set()
                raise
            if self.sdk.error is not None:
                raise self.sdk.error
            return (name, args, kwargs)

        return response()

    def candlesticks(self, *args, **kwargs):
        return self.request("candlesticks", *args, **kwargs)

    def subscribe(self, *args, **kwargs):
        return self.request("subscribe", *args, **kwargs)

    def subscriptions(self):
        return self.request("subscriptions")

    def quote(self, *args, **kwargs):
        return self.request("quote", *args, **kwargs)


class OfficialAsyncQuoteBridgeTests(unittest.TestCase):
    def bridge(self, sdk=None, **kwargs):
        sdk = sdk or FakeAsyncSDK()
        bridge = OfficialAsyncQuoteBridge(object(), sdk=sdk, **kwargs)
        self.addCleanup(bridge.close)
        return sdk, bridge

    def test_single_context_forwarding_and_thread_cleanup(self):
        sdk, bridge = self.bridge()
        bars = bridge.candlesticks("700.HK", "Day", 30, "NoAdjust", "Intraday")
        self.assertEqual(bars[1], ("700.HK", "Day", 30, "NoAdjust", "Intraday"))
        bridge.candlesticks("700.HK", period="Day", count=2)
        self.assertEqual(sdk.calls[-1][2], {"period": "Day", "count": 2})
        bridge.subscribe(["700.HK"], ["Quote", "Trade"])
        bridge.subscriptions()
        bridge.quote(["700.HK"])
        self.assertEqual(sdk.created, 1)
        self.assertNotEqual(sdk.thread, threading.get_ident())
        bridge.close()
        bridge.close()
        self.assertFalse(bridge._thread.is_alive())
        self.assertIsNone(bridge._context)
        self.assertEqual(bridge._callbacks, {})
        self.assertTrue(sdk.loop.is_closed())
        with self.assertRaises(AsyncQuoteBridgeError):
            bridge.quote(["700.HK"])
        self.assertEqual(sdk.created, 1)

    def test_slow_async_request_allows_python_and_loop_heartbeats(self):
        sdk = FakeAsyncSDK()
        sdk.delay = 0.25
        _, bridge = self.bridge(sdk)
        ticks = []

        async def heartbeat():
            for _ in range(20):
                ticks.append("loop")
                await asyncio.sleep(0.005)

        loop_future = asyncio.run_coroutine_threadsafe(heartbeat(), sdk.loop)
        outcome = queue.Queue()

        def request():
            try:
                outcome.put(bridge.candlesticks("700.HK", "Day", 30, "NoAdjust"))
            except Exception as exc:
                outcome.put(exc)

        caller = threading.Thread(target=request)
        caller.start()
        self.assertTrue(sdk.started.wait(1))
        started = time.monotonic()
        for _ in range(30):
            time.sleep(0.002)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.20)
        self.assertTrue(caller.is_alive())
        loop_future.result(1)
        caller.join(1)
        self.assertFalse(caller.is_alive())
        self.assertEqual(len(ticks), 20)
        self.assertEqual(outcome.get_nowait()[0], "candlesticks")

    def test_timeout_fails_closed_cancels_request_and_never_recreates(self):
        sdk = FakeAsyncSDK()
        sdk.delay = 2
        _, bridge = self.bridge(sdk, request_timeout=0.03)
        with self.assertRaises(AsyncQuoteBridgeTimeout):
            bridge.candlesticks("700.HK")
        with self.assertRaises(AsyncQuoteBridgeError):
            bridge.quote(["700.HK"])
        bridge.close()
        self.assertTrue(sdk.cancelled.is_set())
        self.assertFalse(bridge._thread.is_alive())
        self.assertEqual(sdk.created, 1)
        self.assertEqual(len(sdk.calls), 1)

    def test_close_cancels_waiting_caller(self):
        sdk = FakeAsyncSDK()
        sdk.delay = 2
        _, bridge = self.bridge(sdk)
        errors = queue.Queue()

        def request():
            try:
                bridge.quote(["700.HK"])
            except AsyncQuoteBridgeError as exc:
                errors.put(exc)

        caller = threading.Thread(target=request)
        caller.start()
        self.assertTrue(sdk.started.wait(1))
        bridge.close()
        caller.join(1)
        self.assertFalse(caller.is_alive())
        self.assertIsInstance(errors.get_nowait(), AsyncQuoteBridgeError)
        self.assertTrue(sdk.cancelled.is_set())

    def test_close_timeout_is_reported_and_later_join_reclaims_thread(self):
        sdk, bridge = self.bridge(close_timeout=0.02)
        entered = threading.Event()
        release = threading.Event()

        async def blocked_loop():
            entered.set()
            release.wait(2)

        asyncio.run_coroutine_threadsafe(blocked_loop(), sdk.loop)
        try:
            self.assertTrue(entered.wait(1))
            with self.assertRaisesRegex(AsyncQuoteBridgeTimeout, "cleanup timed out"):
                bridge.close()
            with self.assertRaises(AsyncQuoteBridgeError):
                bridge.subscriptions()
        finally:
            release.set()
            bridge._thread.join(1)
        bridge.close()
        self.assertFalse(bridge._thread.is_alive())

    def test_concurrent_callers_share_one_context(self):
        sdk = FakeAsyncSDK()
        sdk.delay = 0.03
        _, bridge = self.bridge(sdk)
        results = queue.Queue()

        def request(symbol):
            try:
                results.put(bridge.quote([symbol]))
            except Exception as exc:
                results.put(exc)

        callers = [threading.Thread(target=request, args=(str(i),)) for i in range(6)]
        for caller in callers:
            caller.start()
        for caller in callers:
            caller.join(1)
            self.assertFalse(caller.is_alive())
        self.assertEqual(results.qsize(), 6)
        self.assertEqual({results.get_nowait()[1][0][0] for _ in callers}, set("012345"))
        self.assertEqual(sdk.created, 1)

    def test_callback_replacement_and_native_forwarder_do_not_retain_closed_bridge(self):
        sdk = FakeAsyncSDK()
        bridge = OfficialAsyncQuoteBridge(object(), sdk=sdk)
        owner = weakref.ref(bridge)
        events = []
        try:
            native_callback = sdk.context.callbacks["quote"]
            bridge.set_on_quote(lambda *_: events.append("old"))
            bridge.set_on_quote(lambda *_: events.append("new"))
            self.assertIs(sdk.context.callbacks["quote"], native_callback)
            native_callback("700.HK", object())
            self.assertEqual(events, ["new"])
        finally:
            bridge.close()
        del bridge
        gc.collect()
        self.assertIsNone(owner())
        native_callback("700.HK", object())
        self.assertEqual(events, ["new"])

    def test_sdk_error_fails_closed(self):
        sdk = FakeAsyncSDK()
        sdk.error = ValueError("fake sdk failure")
        _, bridge = self.bridge(sdk)
        with self.assertRaisesRegex(AsyncQuoteBridgeError, "fake sdk failure"):
            bridge.subscriptions()
        with self.assertRaises(AsyncQuoteBridgeError):
            bridge.subscribe([], [])
        self.assertEqual(len(sdk.calls), 1)

    def test_health_is_local_and_immediately_reports_callback_fault(self):
        sdk, bridge = self.bridge()
        bridge.check_health()
        self.assertEqual(sdk.calls, [])

        def callback(_symbol, _event):
            raise queue.Full("enqueue failed")

        bridge.set_on_quote(callback)
        sdk.context.callbacks["quote"]("700.HK", object())
        with self.assertRaisesRegex(AsyncQuoteBridgeError, "callback failed"):
            bridge.check_health()
        self.assertEqual(sdk.calls, [])
        bridge.close()
        with self.assertRaises(AsyncQuoteBridgeError):
            bridge.check_health()

    def test_health_reports_actual_loop_exit_and_releases_context(self):
        sdk = FakeAsyncSDK()
        bridge = OfficialAsyncQuoteBridge(object(), sdk=sdk)
        try:
            sdk.loop.call_soon_threadsafe(sdk.loop.stop)
            bridge._thread.join(1)
            self.assertFalse(bridge._thread.is_alive())
            self.assertIsNone(bridge._context)
            self.assertEqual(bridge._callbacks, {})
            with self.assertRaisesRegex(AsyncQuoteBridgeError, "loop failed"):
                bridge.check_health()
            self.assertEqual(sdk.calls, [])
        finally:
            with self.assertRaisesRegex(AsyncQuoteBridgeError, "loop failed"):
                bridge.close()

    def test_health_reports_normal_close(self):
        _, bridge = self.bridge()
        bridge.check_health()
        bridge.close()
        with self.assertRaisesRegex(AsyncQuoteBridgeError, "closed"):
            bridge.check_health()

    def test_callbacks_enqueue_unmodified_and_late_callbacks_ignored(self):
        sdk, bridge = self.bridge()
        events = queue.Queue()
        bridge.set_on_quote(lambda symbol, event: events.put_nowait((symbol, event)))
        bridge.set_on_trades(lambda symbol, event: events.put_nowait((symbol, event)))
        quote_callback = sdk.context.callbacks["quote"]
        trade_callback = sdk.context.callbacks["trades"]
        event = object()
        quote_callback("700.HK", event)
        trade_callback("700.HK", event)
        self.assertIs(events.get_nowait()[1], event)
        self.assertIs(events.get_nowait()[1], event)
        bridge.close()
        quote_callback("700.HK", event)
        self.assertTrue(events.empty())

    def test_callback_error_and_reentry_fail_closed_without_deadlock(self):
        for action in ("quote", "close", "raise"):
            with self.subTest(action=action):
                sdk, bridge = self.bridge()

                def callback(_symbol, _event):
                    if action == "quote":
                        bridge.quote([])
                    elif action == "close":
                        bridge.close()
                    else:
                        raise queue.Full

                bridge.set_on_quote(callback)
                sdk.context.callbacks["quote"]("700.HK", object())
                with self.assertRaisesRegex(AsyncQuoteBridgeError, "callback failed"):
                    bridge.subscriptions()
                bridge.close()
                self.assertEqual(sdk.calls, [])

    def test_loop_thread_reentry_rejected(self):
        sdk, bridge = self.bridge()

        async def reentry():
            with self.assertRaisesRegex(AsyncQuoteBridgeError, "forbidden"):
                bridge.subscriptions()

        asyncio.run_coroutine_threadsafe(reentry(), sdk.loop).result(1)

    def test_async_callback_rejected(self):
        _, bridge = self.bridge()

        async def callback(_symbol, _event):
            pass

        with self.assertRaises(TypeError):
            bridge.set_on_quote(callback)

    def test_initialization_failure_reclaims_thread(self):
        sdk = FakeAsyncSDK()
        sdk.create_error = ValueError("fake create failure")
        before = set(threading.enumerate())
        with self.assertRaisesRegex(AsyncQuoteBridgeError, "fake create failure"):
            OfficialAsyncQuoteBridge(object(), sdk=sdk)
        self.assertEqual(set(threading.enumerate()), before)
        self.assertEqual(sdk.created, 1)

    def test_initialization_timeout_drops_late_context_without_retry(self):
        sdk = FakeAsyncSDK()
        sdk.create_gate = threading.Event()
        errors = queue.Queue()

        def create():
            try:
                OfficialAsyncQuoteBridge(
                    object(), sdk=sdk, init_timeout=0.02, close_timeout=0.5
                )
            except AsyncQuoteBridgeTimeout as exc:
                errors.put(exc)

        caller = threading.Thread(target=create)
        caller.start()
        self.assertTrue(sdk.create_started.wait(1))
        time.sleep(0.06)
        sdk.create_gate.set()
        caller.join(1)
        self.assertFalse(caller.is_alive())
        self.assertIsInstance(errors.get_nowait(), AsyncQuoteBridgeTimeout)
        self.assertEqual(sdk.created, 1)
        self.assertTrue(sdk.loop.is_closed())
        # Installed forwarders hold only weak references to the expired bridge.
        sdk.context.callbacks["quote"]("700.HK", object())

    def test_invalid_timeouts_do_not_create_context(self):
        sdk = FakeAsyncSDK()
        for name in ("init_timeout", "request_timeout", "close_timeout"):
            for value in (0, -1, float("inf"), float("nan")):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    OfficialAsyncQuoteBridge(object(), sdk=sdk, **{name: value})
        self.assertEqual(sdk.created, 0)


if __name__ == "__main__":
    unittest.main()
