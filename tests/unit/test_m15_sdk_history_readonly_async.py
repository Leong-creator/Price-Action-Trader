from __future__ import annotations

import asyncio
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
import inspect
import math
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import m15_longbridge_sdk_analytics_lib as analytics


NOW = datetime(2026, 9, 8, 10, tzinfo=UTC)


class FakeSdk:
    def __init__(self):
        self.calls = []
        self.loops = []
        self.behaviors = {}
        self.channels = [{"account_channel": "lb_papertrading"}]
        self.trade_count = self.portfolio_count = 0
        self.cancelled = False
        self.OAuthBuilder = lambda _client: SimpleNamespace(build_async=self.oauth)
        self.AsyncTradeContext = SimpleNamespace(create=self.create_trade)
        self.PortfolioContext = self.create_portfolio
        self.Config = SimpleNamespace(from_oauth=lambda *_a, **_k: object())

    def record(self, method, kwargs=None):
        self.loops.append(asyncio.get_running_loop())
        self.calls.append((method, kwargs or {}))

    async def oauth(self, _callback):
        return await self.invoke("oauth")

    def create_trade(self, _config):
        self.record("create_trade")
        self.trade_count += 1
        return SimpleNamespace(
            stock_positions=lambda: self.invoke("stock_positions"),
            history_orders=lambda **kw: self.invoke("history_orders", kw),
            history_executions=lambda **kw: self.invoke("history_executions", kw),
        )

    def create_portfolio(self, _config):
        self.calls.append(("create_portfolio", {}))
        self.portfolio_count += 1
        return SimpleNamespace(profit_analysis_by_market=self.profit)

    def profit(self, **kwargs):
        self.calls.append(("profit", kwargs))
        if "profit" in self.behaviors:
            raise RuntimeError("request timeout")
        return {"profit": "1.23"}

    async def invoke(self, name, kwargs=None):
        self.record(name, kwargs)
        if name in self.behaviors:
            return await self.behaviors[name]()
        if name == "stock_positions":
            return {"channels": self.channels}
        if name == "history_orders":
            return [{"order_id": "fresh", "status": "Filled", "side": "Buy"}]
        if name == "history_executions":
            return [{"trade_id": "fill", "order_id": "fresh"}]
        return {"profit": "1.23"}

    async def stall(self):
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled = True


class AsyncHistoryReadonlyTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("socket.socket.connect", side_effect=AssertionError("no network")))
        self.stack.enter_context(patch.object(analytics, "read_client_id", return_value="offline-client"))
        self.sdk = FakeSdk()
        self.config = SimpleNamespace(trade_region="global")
        self.reader = None

    def make_reader(self, **kwargs):
        self.reader = analytics.OfficialAsyncAnalyticsReader(self.sdk, self.config, **kwargs)
        self.addCleanup(self.reader.close)
        return self.reader

    def read_orders(self, reader):
        return reader.history_orders(start_at=NOW - timedelta(days=2), end_at=NOW)

    def test_all_factories_and_io_share_one_loop_without_worker_threads(self):
        threads = set(threading.enumerate())
        reader = self.make_reader()
        self.assertEqual(self.sdk.calls, [])
        self.assertEqual(self.read_orders(reader)[0]["order_id"], "fresh")
        reader.history_executions(start_at=NOW-timedelta(days=2), end_at=NOW)
        self.assertEqual(len(set(self.sdk.loops)), 1)
        self.assertEqual(self.sdk.trade_count, 1)
        self.assertEqual(self.sdk.portfolio_count, 0)
        reader.close()
        self.assertTrue(reader._loop.is_closed())
        self.assertIsNone(reader._trade)
        self.assertEqual(set(threading.enumerate()), threads)

    def test_official_keyword_arguments_preserved(self):
        self.read_orders(self.make_reader())
        kwargs = next(kwargs for method, kwargs in self.sdk.calls if method == "history_orders")
        self.assertEqual(kwargs, {"start_at": NOW-timedelta(days=2), "end_at": NOW})

    def test_saturated_history_response_cannot_publish(self):
        for method in ("history_orders", "history_executions"):
            with self.subTest(method=method):
                async def saturated():
                    return [{}] * 1000
                self.sdk = FakeSdk()
                self.sdk.behaviors[method] = saturated
                with self.assertRaisesRegex(RuntimeError, "possibly_truncated"):
                    self.run_with_fake_sdk()
                self.writer.assert_not_called()

    def test_malformed_history_is_not_treated_as_empty_success(self):
        for response in (None, {}, (), ""):
            with self.subTest(response=response):
                async def malformed():
                    return response
                self.sdk = FakeSdk()
                self.sdk.behaviors["history_orders"] = malformed
                with self.assertRaisesRegex(RuntimeError, "invalid_response"):
                    self.run_with_fake_sdk()
                self.writer.assert_not_called()

    def test_timeout_is_bounded_cancels_and_permanently_rejects_later_calls(self):
        self.sdk.behaviors["history_orders"] = self.sdk.stall
        reader = self.make_reader(request_timeout=0.02)
        started = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, "history_orders_timeout"):
            self.read_orders(reader)
        with self.assertRaisesRegex(RuntimeError, "history_orders_failed"):
            self.read_orders(reader)
        reader.close()
        self.assertLess(time.monotonic()-started, 0.5)
        self.assertTrue(self.sdk.cancelled)
        self.assertEqual(self.sdk.trade_count, 1)
        self.assertEqual(sum(name == "history_orders" for name, _ in self.sdk.calls), 1)

    def test_oauth_timeout_cannot_create_trade_or_history(self):
        self.sdk.behaviors["oauth"] = self.sdk.stall
        with self.assertRaises(TimeoutError):
            self.read_orders(self.make_reader(request_timeout=0.02))
        self.reader.close()
        self.assertEqual(self.sdk.trade_count, 0)

    def test_total_deadline_does_not_reset_for_each_request(self):
        reader = self.make_reader(total_timeout=0.03, request_timeout=1)
        self.read_orders(reader)
        time.sleep(0.04)
        with self.assertRaisesRegex(TimeoutError, "total_deadline"):
            reader.history_executions(start_at=NOW, end_at=NOW)
        self.assertFalse(any(name == "history_executions" for name, _ in self.sdk.calls))

    def test_late_success_after_cancellation_is_not_accepted(self):
        async def late():
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                return [{"order_id": "late"}]
        self.sdk.behaviors["history_orders"] = late
        reader = self.make_reader(request_timeout=0.02)
        with self.assertRaises(TimeoutError):
            self.read_orders(reader)
        reader.close()

    def test_return_after_blocking_sdk_call_deadline_is_rejected(self):
        async def delayed():
            time.sleep(0.04)
            return []
        self.sdk.behaviors["history_orders"] = delayed
        with self.assertRaisesRegex(TimeoutError, "late_result"):
            self.read_orders(self.make_reader(request_timeout=0.02))

    def test_sdk_timeout_error_is_not_retried(self):
        async def fail():
            raise RuntimeError("request timeout")
        self.sdk.behaviors["history_orders"] = fail
        with self.assertRaisesRegex(RuntimeError, "request timeout"):
            self.read_orders(self.make_reader())
        with self.assertRaises(RuntimeError):
            self.read_orders(self.reader)
        self.assertEqual(self.sdk.trade_count, 1)

    def test_only_unambiguous_paper_channel_is_allowed(self):
        for channels in ([], [{}], [{"account_channel": "live"}],
                         [{"account_channel": "lb_papertrading"}, {"account_channel": "live"}]):
            with self.subTest(channels=channels):
                self.sdk = FakeSdk()
                self.sdk.channels = channels
                reader = self.make_reader()
                with self.assertRaisesRegex(RuntimeError, "verified_paper_account"):
                    self.read_orders(reader)
                reader.close()
                self.assertFalse(any(name == "history_orders" for name, _ in self.sdk.calls))

    def test_write_and_quote_methods_are_not_exposed_or_dispatchable(self):
        reader = self.make_reader()
        for name in ("submit_order", "cancel_order", "replace_order", "subscribe", "quote", "today_orders"):
            self.assertFalse(hasattr(reader, name))
            with self.assertRaises(ValueError):
                reader._read(name)
        self.assertEqual(self.sdk.calls, [])

    def test_closed_reader_never_connects(self):
        reader = self.make_reader()
        reader.close()
        reader.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.read_orders(reader)
        self.assertEqual(self.sdk.calls, [])

    def test_invalid_timeouts_do_not_create_loop_or_connect(self):
        for name in ("request_timeout", "total_timeout", "close_timeout"):
            for value in (0, -1, math.inf, math.nan):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.make_reader(**{name: value})
        self.assertEqual(self.sdk.calls, [])

    def test_sync_entry_rejects_nested_running_loop_without_io(self):
        async def call():
            with self.assertRaisesRegex(RuntimeError, "synchronous_caller"):
                self.make_reader()
        asyncio.run(call())
        self.assertEqual(self.sdk.calls, [])

    def test_other_async_tasks_can_progress_during_history_wait(self):
        ticks = []
        async def delayed():
            async def heartbeat():
                for _ in range(4):
                    await asyncio.sleep(0.001)
                    ticks.append(time.monotonic())
            task = asyncio.create_task(heartbeat())
            await asyncio.sleep(0.02)
            await task
            return []
        self.sdk.behaviors["history_orders"] = delayed
        self.read_orders(self.make_reader())
        self.assertEqual(len(ticks), 4)

    def run_with_fake_sdk(self, cache=None, snapshot_age=0, reader_factory=None):
        state = {"paper_account_verified": True, "account_channel": "lb_papertrading",
                 "generated_at": (NOW-timedelta(seconds=snapshot_age)).isoformat()}
        config = SimpleNamespace(account_state_path=Path("account.json"), output_dir=Path("output"),
                                 historical_order_start_date="2026-06-01")
        self.writer = Mock(return_value={"ok": True})
        self.runtime_gate = Mock()
        self.stack.enter_context(patch.dict(sys.modules, {
            "longbridge": SimpleNamespace(openapi=self.sdk), "longbridge.openapi": self.sdk,
        }))
        self.stack.enter_context(patch.object(analytics, "load_sdk_config", return_value=self.config))
        self.stack.enter_context(patch.object(analytics, "load_account_config", return_value=config))
        self.stack.enter_context(patch.object(analytics, "require_live_sdk_runtime", self.runtime_gate))
        self.stack.enter_context(patch.object(analytics, "read_json", side_effect=[state, cache or {}]))
        self.stack.enter_context(patch.object(analytics, "write_sdk_analytics_outputs", self.writer))
        if reader_factory:
            self.stack.enter_context(patch.object(analytics, "OfficialAsyncAnalyticsReader", reader_factory))
        return analytics.run_sdk_analytics("runtime", "account", generated_at=NOW)

    def test_full_refresh_uses_async_history_and_unchanged_profit_ranges(self):
        self.assertEqual(self.run_with_fake_sdk(), {"ok": True})
        args = self.writer.call_args.kwargs
        self.assertEqual(args["history_refresh_mode"], "sdk_history_bootstrap")
        self.assertEqual(args["historical_orders"][0]["order_id"], "fresh")
        self.assertEqual(args["profit_analysis"], {"profit": "1.23"})
        self.assertEqual(args["app_display_metrics"]["status"], "incomplete")
        self.assertEqual(self.runtime_gate.call_count, 2)
        queries = [kw for name, kw in self.sdk.calls if name == "profit"]
        self.assertEqual(queries[0]["start"], "2026-06-01")
        self.assertEqual(queries[0]["end"], "2026-09-09")
        self.assertEqual(queries[1]["start"], queries[1]["end"])

    def test_each_failed_stage_leaves_cache_and_outputs_untouched(self):
        for stage in ("oauth", "stock_positions", "history_orders", "history_executions", "profit"):
            with self.subTest(stage=stage):
                async def fail():
                    raise RuntimeError("request timeout")
                self.sdk = FakeSdk()
                self.sdk.behaviors[stage] = fail
                cache = {"historical_orders": [{"order_id": "cached", "status": "New"}]}
                with self.assertRaisesRegex(RuntimeError, "request timeout"):
                    self.run_with_fake_sdk(cache)
                self.writer.assert_not_called()
                self.assertEqual(cache["historical_orders"], [{"order_id": "cached", "status": "New"}])
                self.assertLessEqual(self.sdk.trade_count, 1)

    def test_expired_snapshot_after_successful_io_cannot_publish(self):
        async def slow():
            await asyncio.sleep(0.025)
            return []
        self.sdk.behaviors["history_orders"] = slow
        with self.assertRaisesRegex(RuntimeError, "fresh_account_snapshot"):
            self.run_with_fake_sdk(snapshot_age=44.99)
        self.writer.assert_not_called()

    def test_local_timeout_in_run_does_not_publish_cache_and_closes_loop(self):
        self.sdk.behaviors["history_executions"] = self.sdk.stall
        reader = self.make_reader(request_timeout=0.02)
        with self.assertRaises(TimeoutError):
            self.run_with_fake_sdk(
                {"historical_orders": [{"order_id": "cached"}]},
                reader_factory=lambda *_: reader,
            )
        self.writer.assert_not_called()
        self.assertTrue(reader._loop.is_closed())
        self.assertEqual(self.sdk.portfolio_count, 0)

    def test_incremental_empty_success_is_explicit_and_preserves_old_history(self):
        async def empty():
            return []
        self.sdk.behaviors["history_orders"] = empty
        self.sdk.behaviors["history_executions"] = empty
        self.run_with_fake_sdk({"historical_orders": [{"order_id": "cached"}]})
        args = self.writer.call_args.kwargs
        self.assertEqual(args["historical_orders"], [{"order_id": "cached"}])
        self.assertEqual(args["history_refresh_mode"], "trusted_cache_plus_two_day_sdk_incremental_and_fresh_snapshot")
        kwargs = next(kw for name, kw in self.sdk.calls if name == "history_orders")
        self.assertEqual(kwargs["start_at"], NOW-timedelta(days=2))

    def test_production_path_does_not_use_legacy_retry_helper(self):
        with patch.object(analytics, "read_with_timeout_recovery", side_effect=AssertionError("retry forbidden")):
            self.run_with_fake_sdk()
        source = inspect.getsource(analytics.run_sdk_analytics)
        self.assertNotIn("sdk.TradeContext(", source)


class InstalledSdkContractTest(unittest.TestCase):
    def test_450_bound_methods_used_by_production_exist_without_connecting(self):
        try:
            import longbridge.openapi as sdk
        except ImportError:
            self.skipTest("official SDK not installed")
        self.assertTrue(callable(sdk.OAuthBuilder.build_async))
        self.assertTrue(callable(sdk.AsyncTradeContext.create))
        for name in ("history_orders", "history_executions"):
            signature = inspect.signature(getattr(sdk.AsyncTradeContext, name))
            self.assertIn("start_at", signature.parameters)
            self.assertIn("end_at", signature.parameters)
        self.assertTrue(callable(sdk.AsyncTradeContext.stock_positions))
        self.assertTrue(callable(sdk.PortfolioContext.profit_analysis_by_market))


if __name__ == "__main__":
    unittest.main()
