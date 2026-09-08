"""Offline only: no SDK constructors, sockets, account access or quote contexts."""

import asyncio
import socket
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.m15_official_async_trade_lib import (
    AsyncTradeBridgeError, AsyncTradeBridgeTimeout, BoundedTradeRequestGate,
    OfficialAsyncTradeBridge, TradeRequestNotSent,
)
from scripts.m15_longbridge_sdk_runtime_lib import SdkRealtimePaperClient
from scripts.m15_longbridge_realtime_execution_lib import (
    hydrate_unconfirmed_execution_rows, run_realtime_execution,
    should_retry_market_exit_as_marketable_limit,
)
from tests.unit import test_m15_longbridge_realtime_execution as execution_tests


ENUM = SimpleNamespace(Buy="Buy", Sell="Sell", LO="LO", MO="MO", LIT="LIT",
                       Day="Day", RTHOnly="RTHOnly")
SDK = SimpleNamespace(OrderSide=ENUM, OrderType=ENUM, TimeInForceType=ENUM, OutsideRTH=ENUM)
PAYLOAD = dict(side="sell", symbol="AAPL", order_type="market", quantity="1",
               signal_id="timeout-signal", client_request_id="timeout-request",
               current_price="100", fallback_quote_age_ms=0)


class PaperOrderTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_all_ambiguous_exceptions_latch_notify_and_never_fallback(self):
        for error in (TimeoutError("request timeout"), ConnectionError("reset"),
                      RuntimeError("HTTP 502"), RuntimeError("unknown error")):
            with self.subTest(error=error):
                trade = SimpleNamespace(submit_order=Mock(side_effect=error))
                note = Mock()
                client = SdkRealtimePaperClient(trade, SDK, on_submission=note)
                first = client.submit_order(PAYLOAD)
                self.assertEqual(first["status"], "submit_unconfirmed_missing_order_id")
                self.assertFalse(first["explicit_reject"])
                self.assertTrue(first["confirmation_required"])
                self.assertEqual(first["order_id"], "")
                self.assertEqual(client.submit_order(PAYLOAD), first)
                blocked = client.submit_order({**PAYLOAD, "client_request_id": "new-request"})
                self.assertEqual(blocked["status"], "submit_blocked_pending_reconciliation")
                trade.submit_order.assert_called_once()
                note.assert_called_once_with(PAYLOAD, first)
                self.assertFalse(should_retry_market_exit_as_marketable_limit(
                    {"exit_only_position_signal": True}, first, PAYLOAD))

    def test_missing_id_notifies_and_success_is_deduplicated(self):
        for order_id in ("", "mock-order"):
            with self.subTest(order_id=order_id):
                note = Mock()
                trade = SimpleNamespace(submit_order=Mock(return_value=SimpleNamespace(order_id=order_id)))
                client = SdkRealtimePaperClient(trade, SDK, on_submission=note)
                first = client.submit_order(PAYLOAD)
                self.assertEqual(client.submit_order(PAYLOAD), first)
                self.assertEqual(first["submitted"], bool(order_id))
                note.assert_called_once()
                trade.submit_order.assert_called_once()

    def test_rate_budget_refuses_without_sleep_or_ambiguous_placeholder(self):
        now = [0.0]
        gate = BoundedTradeRequestGate(max_calls=1, window_seconds=30, monotonic_clock=lambda: now[0])
        gate.call(lambda: None)
        trade = SimpleNamespace(submit_order=Mock(return_value=SimpleNamespace(order_id="mock-order")))
        note = Mock()
        client = SdkRealtimePaperClient(trade, SDK, request_gate=gate, on_submission=note)
        with patch("time.sleep", side_effect=AssertionError("must not sleep")):
            result = client.submit_order(PAYLOAD)
        self.assertEqual(result["status"], "submit_blocked_trade_admission")
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(client._unconfirmed_submission)
        trade.submit_order.assert_not_called()
        note.assert_not_called()
        now[0] = 30.0
        self.assertTrue(client.submit_order({**PAYLOAD, "client_request_id": "fresh-request"})["submitted"])

    def test_busy_gate_never_waits(self):
        gate = BoundedTradeRequestGate()
        gate._lock.acquire()
        try:
            with self.assertRaises(TradeRequestNotSent):
                gate.call(lambda: self.fail("SDK must not run"))
        finally:
            gate._lock.release()

    def test_cycle_budget_is_shared_for_reads_writes_and_cpu_delay(self):
        now = [0.0]
        gate = BoundedTradeRequestGate(max_calls=2, monotonic_clock=lambda: now[0])
        calls = []
        gate.begin_cycle(5.0)
        gate.call(lambda: calls.append("health"))
        now[0] = 3.0
        gate.call(lambda: calls.append("capacity"))
        now[0] = 3.001
        with patch("time.sleep", side_effect=AssertionError("must not sleep")):
            with self.assertRaisesRegex(TradeRequestNotSent, "cycle budget"):
                gate.call(lambda: calls.append("submit"))
        self.assertEqual(calls, ["health", "capacity"])
        gate.begin_cycle(8.001)
        with self.assertRaisesRegex(TradeRequestNotSent, "rate budget"):
            gate.call(lambda: calls.append("maintenance"))

    def test_invalid_cycle_budget_rejected(self):
        gate = BoundedTradeRequestGate()
        for deadline, reserve in ((float("inf"), 2), (5, -1), (5, float("nan"))):
            with self.subTest(deadline=deadline, reserve=reserve), self.assertRaises(ValueError):
                gate.begin_cycle(deadline, reserve)

    def test_note_failure_preserves_ack_and_blocks_new_writes(self):
        trade = SimpleNamespace(submit_order=Mock(return_value=SimpleNamespace(order_id="mock-order")))
        client = SdkRealtimePaperClient(trade, SDK, on_submission=Mock(side_effect=OSError("disk full")))
        result = client.submit_order(PAYLOAD)
        self.assertTrue(result["submitted"])
        self.assertEqual(result["order_id"], "mock-order")
        self.assertIn("disk full", result["submission_note_error"])
        self.assertEqual(client.submit_order({**PAYLOAD, "client_request_id": "other"})["status"],
                         "submit_blocked_pending_reconciliation")
        trade.submit_order.assert_called_once()

    def test_executor_persists_unknown_and_wont_replay_after_client_recreation(self):
        helper = execution_tests.M15LongbridgeRealtimeExecutionTest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = helper.make_config(root, execute_orders=True, paper_trading_approval=True)
            helper.write_jsonl(root / "signals.jsonl", [helper.signal(signal_id="sig-timeout")])
            trade = SimpleNamespace(submit_order=Mock(side_effect=TimeoutError("accepted then response lost")))
            client = SdkRealtimePaperClient(trade, SDK, on_submission=Mock())
            first = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z", broker_client=client)
            self.assertEqual(first["unconfirmed_submission_count"], 1)
            self.assertEqual(first["submitted_count"], 0)
            second = run_realtime_execution(config, generated_at="2026-06-04T14:00:02Z",
                                           broker_client=SdkRealtimePaperClient(trade, SDK))
            self.assertEqual(second["attempted_order_count"], 0)
            trade.submit_order.assert_called_once()

    def test_existing_remark_hydration_releases_latch_only_on_unique_broker_id(self):
        trade = SimpleNamespace(submit_order=Mock(side_effect=TimeoutError("lost reply")))
        note = Mock()
        client = SdkRealtimePaperClient(trade, SDK, on_submission=note)
        result = client.submit_order(PAYLOAD)
        self.assertFalse(client.reconcile_submissions({"orders": []}))
        order = {"order_id": "mock-broker-id", "status": "Filled",
                 "remark": "PAT-RT timeout-signal timeout-request"}
        self.assertFalse(client.reconcile_submissions({"orders": [order, {**order, "order_id": "ambiguous"}]}))
        account = {"orders": [order]}
        rows = hydrate_unconfirmed_execution_rows([
            {"signal_id": PAYLOAD["signal_id"], "submission_status": result["status"]}
        ], account, {})
        self.assertEqual(rows[0]["submission_status"], "submitted")
        self.assertEqual(rows[0]["submission_confirmation_state"], "broker_reconciled_terminal")
        self.assertTrue(client.reconcile_submissions(account))
        self.assertIsNone(client._unconfirmed_submission)
        self.assertEqual(client.submit_order(PAYLOAD)["order_id"], "mock-broker-id")
        trade.submit_order.assert_called_once()
        self.assertEqual(note.call_count, 2)
        self.assertEqual(note.call_args.args[1]["order_id"], "mock-broker-id")


class AsyncTradeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def bridge(self, context, **kwargs):
        factory = Mock(side_effect=lambda _config: context)
        sdk = SimpleNamespace(AsyncTradeContext=SimpleNamespace(create=factory))
        bridge = OfficialAsyncTradeBridge(object(), sdk=sdk, request_timeout=0.05, **kwargs)
        self.addCleanup(bridge.close)
        factory.assert_called_once()
        return bridge

    def test_mock_complete_client_workflow_uses_owned_loop_and_one_factory(self):
        calls = []
        class Context:
            def __getattr__(self, name):
                async def operation(*args, **kwargs):
                    calls.append((name, args, kwargs, threading.current_thread().name))
                    return SimpleNamespace(order_id="mock-order", cash_max_qty=2, margin_max_qty=3)
                return operation
        bridge = self.bridge(Context())
        self.assertEqual(bridge.maximum_request_wait_seconds, 0.05)
        client = SdkRealtimePaperClient(bridge, SDK)
        self.assertTrue(client.healthcheck()["ok"])
        self.assertTrue(client.submit_order(PAYLOAD)["submitted"])
        self.assertTrue(client.cancel_order("mock-order")["canceled"])
        self.assertTrue(client.replace_order("mock-order", Decimal(1), Decimal(100))["replaced"])
        self.assertEqual(client.order_detail("mock-order").order_id, "mock-order")
        self.assertEqual(client.max_short_quantity("AAPL", Decimal(100))["max_quantity"], Decimal(3))
        self.assertEqual([call[0] for call in calls], ["today_orders", "submit_order", "cancel_order",
                         "replace_order", "order_detail", "estimate_max_purchase_quantity"])
        self.assertTrue(all(call[3] == "m15-official-async-trade" for call in calls))
        bridge.check_health()
        bridge.close()
        bridge.close()
        self.assertFalse(bridge._thread.is_alive())

    def test_every_io_deadline_is_bounded_and_poisoned_without_retry(self):
        for method in ("today_orders", "account_balance", "submit_order", "cancel_order",
                       "replace_order", "order_detail", "estimate_max_purchase_quantity"):
            with self.subTest(method=method):
                calls = []
                class Context:
                    def __getattr__(self, name):
                        async def operation(*args, **kwargs):
                            calls.append(name)
                            await asyncio.sleep(30)
                        return operation
                bridge = self.bridge(Context())
                started = time.monotonic()
                with self.assertRaises(AsyncTradeBridgeTimeout):
                    getattr(bridge, method)()
                self.assertLess(time.monotonic() - started, 0.5)
                with self.assertRaises(AsyncTradeBridgeError):
                    getattr(bridge, method)()
                self.assertEqual(calls, [method])
                bridge.close()
                self.assertFalse(bridge._thread.is_alive())

    def test_accepted_then_timeout_keeps_parent_heartbeat_and_unknown_latch(self):
        accepted = []
        class Context:
            async def submit_order(self, **kwargs):
                accepted.append(kwargs)
                await asyncio.sleep(30)
        bridge = self.bridge(Context())
        heartbeat = threading.Event()
        timer = threading.Timer(0.01, heartbeat.set)
        timer.start()
        note = Mock()
        client = SdkRealtimePaperClient(bridge, SDK, on_submission=note)
        result = client.submit_order(PAYLOAD)
        timer.join(timeout=1)
        self.assertTrue(heartbeat.is_set())
        self.assertEqual(result["status"], "submit_unconfirmed_missing_order_id")
        self.assertEqual(client.submit_order(PAYLOAD), result)
        self.assertEqual(len(accepted), 1)
        note.assert_called_once()

    def test_factory_error_reclaims_thread_and_never_uses_sync_sdk(self):
        before = {t.ident for t in threading.enumerate()}
        sdk = SimpleNamespace(AsyncTradeContext=SimpleNamespace(create=Mock(side_effect=ValueError("bad config"))),
                              TradeContext=Mock(side_effect=AssertionError("sync forbidden")))
        with self.assertRaises(AsyncTradeBridgeError):
            OfficialAsyncTradeBridge(None, sdk=sdk)
        sdk.TradeContext.assert_not_called()
        self.assertEqual({t.ident for t in threading.enumerate()}, before)

    def test_budget_admission_does_not_poison_or_rebuild_bridge(self):
        calls = []
        class Context:
            async def today_orders(self):
                calls.append("health")
                return []
        sdk = SimpleNamespace(AsyncTradeContext=SimpleNamespace(create=Mock(return_value=Context())))
        bridge = OfficialAsyncTradeBridge(None, sdk=sdk, request_timeout=2.0)
        self.addCleanup(bridge.close)
        self.assertEqual(bridge.maximum_request_wait_seconds, 2.0)
        now = [4.0]
        gate = BoundedTradeRequestGate(monotonic_clock=lambda: now[0])
        gate.begin_cycle(5.0, reserve_seconds=2.0)
        client = SdkRealtimePaperClient(bridge, SDK, request_gate=gate)
        self.assertFalse(client.healthcheck()["ok"])
        bridge.check_health()
        self.assertEqual(calls, [])
        gate.begin_cycle(9.0)
        self.assertTrue(client.healthcheck()["ok"])
        self.assertEqual(calls, ["health"])
        sdk.AsyncTradeContext.create.assert_called_once()

    def test_invalid_timeouts_fail_before_factory(self):
        for value in (0, -1, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                OfficialAsyncTradeBridge(None, sdk=object(), request_timeout=value)


if __name__ == "__main__":
    unittest.main()
