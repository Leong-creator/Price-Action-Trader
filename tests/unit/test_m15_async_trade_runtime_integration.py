"""Offline runtime trade integration and crash-window evidence; no SDK network."""

import ast
from contextlib import ExitStack
import inspect
from pathlib import Path
import socket
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import run_m15_longbridge_sdk_runtime as runtime
from scripts.m15_official_async_trade_lib import AsyncTradeBridgeError, BoundedTradeRequestGate, OfficialAsyncTradeBridge
from scripts.m15_submission_journal_lib import SubmissionJournal
from scripts.m15_longbridge_realtime_execution_lib import run_realtime_execution
from tests.unit import test_m15_longbridge_realtime_execution as executor_tests
from tests.unit import test_m15_boot_runtime_integration as boot_fixtures


class AsyncTradeRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_sdk_contract_requires_async_trade_without_sync_fallback(self):
        sdk = SimpleNamespace(QuoteContext=object(), TradeContext=Mock(), PortfolioContext=object())
        with patch.dict(sys.modules, {"longbridge": SimpleNamespace(openapi=sdk), "longbridge.openapi": sdk}):
            with self.assertRaisesRegex(RuntimeError, "sdk_contract_missing:AsyncTradeContext"):
                runtime.require_sdk_contract()
            sdk.TradeContext.assert_not_called()
            sdk.AsyncTradeContext = object()
            self.assertIs(runtime.require_sdk_contract(), sdk)

    def build(self, dispatch=True):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        sdk = SimpleNamespace(OAuthBuilder=Mock(), TradeContext=Mock(side_effect=AssertionError("sync forbidden")))
        bridge = Mock()
        gate = BoundedTradeRequestGate()
        note = Mock()
        with patch.object(runtime, "read_client_id", return_value="offline-id"), \
                patch.object(runtime, "sdk_config_from_oauth", return_value="paper-config"), \
                patch.object(runtime, "OfficialAsyncTradeBridge", return_value=bridge) as factory:
            result = runtime.build_sdk_trade_clients(SimpleNamespace(trade_region="unchanged", output_dir=Path(directory.name)), sdk,
                                                     gate, note, dispatch_enabled=dispatch)
        factory.assert_called_once_with("paper-config", sdk=sdk, request_timeout=2.0)
        sdk.TradeContext.assert_not_called()
        return result, gate, note

    def test_build_two_second_bridge_and_shared_entry_exit_latch(self):
        (bridge, client, flatten), gate, note = self.build()
        self.assertIs(client, flatten)
        self.assertIs(client.trade_context, bridge)
        self.assertIs(client.request_gate, gate)
        self.assertIs(client.on_submission, note)

    def test_readonly_build_does_not_arm_paper_dispatch(self):
        (bridge, client, flatten), _, _ = self.build(dispatch=False)
        self.assertIsNone(client)
        self.assertIs(flatten.trade_context, bridge)
        bridge.submit_order.assert_not_called()

    def test_constructor_failure_closes_created_bridge(self):
        sdk = SimpleNamespace(OAuthBuilder=Mock())
        bridge = Mock()
        with patch.object(runtime, "read_client_id", return_value="offline"), \
                patch.object(runtime, "sdk_config_from_oauth", return_value=None), \
                patch.object(runtime, "OfficialAsyncTradeBridge", return_value=bridge), \
                patch.object(runtime, "SdkRealtimePaperClient", side_effect=ValueError("bad adapter")):
            with self.assertRaises(ValueError):
                runtime.build_sdk_trade_clients(SimpleNamespace(trade_region="unchanged", output_dir=Path("/unused")), sdk,
                                                BoundedTradeRequestGate(), None, dispatch_enabled=True)
        bridge.close.assert_called_once()

    def test_startup_stack_closes_trade_and_does_not_skip_other_cleanup(self):
        bridge = Mock()
        bridge.close.side_effect = AsyncTradeBridgeError("cleanup timeout")
        other_cleanup = Mock()
        with patch.object(runtime.sys, "stderr"):
            with ExitStack() as stack:
                stack.callback(other_cleanup)
                stack.callback(runtime.close_sdk_trade_client, bridge)
        bridge.close.assert_called_once()
        other_cleanup.assert_called_once()

    def test_local_fault_never_probes_or_rebuilds(self):
        bridge = Mock()
        bridge.check_health.side_effect = AsyncTradeBridgeError("submit_order timeout; outcome unknown")
        client = Mock()
        with patch.object(runtime, "build_sdk_trade_clients", side_effect=AssertionError("no rebuild")):
            for _ in range(3):
                health = runtime.runtime_trade_health(bridge, client, probe=True)
                self.assertFalse(health["ok"])
                self.assertTrue(health["fault_halted"])
                self.assertTrue(health["requires_manual_reconciliation"])
                self.assertFalse(health["trade_context_refresh_required"])
        client.healthcheck.assert_not_called()

    def test_swallowed_sdk_exception_is_detected_after_health_probe(self):
        bridge = Mock()
        bridge.check_health.side_effect = [None, AsyncTradeBridgeError("today_orders timeout")]
        client = SimpleNamespace(healthcheck=Mock(return_value={"ok": False}),
                                 submission_journal_health=lambda: {"ok": True},
                                 trade_context_refresh_required=False)
        health = runtime.runtime_trade_health(bridge, client, probe=True)
        self.assertTrue(health["fault_halted"])
        client.healthcheck.assert_called_once()

    def test_admission_failure_does_not_poison_healthy_bridge(self):
        bridge = Mock()
        client = SimpleNamespace(healthcheck=Mock(return_value={"ok": False, "error": "rate budget"}),
                                 submission_journal_health=lambda: {"ok": True},
                                 trade_context_refresh_required=False)
        health = runtime.runtime_trade_health(bridge, client, probe=True)
        self.assertFalse(health["ok"])
        self.assertFalse(health.get("fault_halted", False))

    def test_hot_runtime_has_one_build_no_sync_context_and_both_cleanup_paths(self):
        source = inspect.getsource(runtime._run_watch_after_boot_check)
        tree = ast.parse(source)
        builds = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == "build_sdk_trade_clients"]
        self.assertEqual(len(builds), 1)
        self.assertNotIn("sdk.TradeContext(", source)
        self.assertNotIn("execution_request_gate = SdkTradeRequestGate()", source)
        self.assertIn("execution_request_gate = BoundedTradeRequestGate()", source)
        self.assertIn("execution_request_gate.begin_cycle(time.monotonic() + 5, reserve_seconds=2.0)", source)
        cycles = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == "begin_cycle"]
        self.assertEqual(len(cycles), 1)
        parent_loop = next(node for node in ast.walk(tree) if isinstance(node, ast.While)
                           and ast.unparse(node.test) == "not shutdown_requested")
        self.assertIs(parent_loop.body[0].value, cycles[0])
        self.assertIn("startup_cleanup.callback(close_sdk_trade_client, execution_trade)", source)
        self.assertTrue(any(isinstance(node, ast.Try) and any(
            isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
            and item.func.id == "cleanup_runtime_resources"
            for part in node.finalbody for item in ast.walk(part)) for node in ast.walk(tree)))
        self.assertIn("close_sdk_trade_client(execution_trade)", inspect.getsource(runtime.cleanup_runtime_resources))

    def test_final_cleanup_reaches_trade_even_when_quote_cleanup_fails(self):
        bridge, account = Mock(), Mock()
        with patch.object(runtime, "stop_spawned_process", side_effect=RuntimeError("quote cleanup failed")), \
                patch.object(runtime, "close_spawn_queue"), patch.object(runtime.signal, "signal"), \
                patch.object(runtime.sys, "stderr"):
            with self.assertRaisesRegex(RuntimeError, "quote cleanup failed"):
                runtime.cleanup_runtime_resources(stop_event=Mock(), worker=Mock(), message_queue=Mock(),
                                                  execution_trade=bridge, account=account, previous_sigterm_handler=None)
        bridge.close.assert_called_once()
        account.stop.assert_called_once()

    def test_reconcile_requires_ready_paper_snapshot(self):
        tree = ast.parse(inspect.getsource(runtime._run_watch_after_boot_check))
        guarded = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                       and any(isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
                               and item.func.attr == "reconcile_submissions"
                               for statement in node.body for item in ast.walk(statement))
                       and "account_snapshot_ready" in ast.unparse(node.test))
        code = compile(ast.fix_missing_locations(ast.Module(body=[guarded], type_ignores=[])), "guard", "exec")
        for ready, channel, expected in ((False, "lb_papertrading", 0), (True, "live", 0),
                                         (True, "lb_papertrading", 1)):
            client = Mock()
            exec(code, {"account_snapshot_ready": ready, "snapshot": {"account_channel": channel},
                        "flatten_client": client})
            self.assertEqual(client.reconcile_submissions.call_count, expected)

    def test_trade_status_reports_actual_async_api_deadlines_and_journal_evidence(self):
        sdk = SimpleNamespace(AsyncTradeContext=SimpleNamespace(create=Mock(return_value=object())))
        bridge = OfficialAsyncTradeBridge(None, sdk=sdk, request_timeout=2.0)
        self.addCleanup(bridge.close)
        for journal in ({"ok": True, "unresolved_submission_count": 0},
                        {"ok": False, "pending_reconciliation": True, "unresolved_submission_count": 1},
                        {"ok": False, "fault_halted": True, "error": "storage_failed"}):
            client = SimpleNamespace(submission_journal_health=lambda: journal)
            result = runtime.runtime_trade_observability(bridge, client)
            self.assertEqual(result["api"], "AsyncTradeContext")
            self.assertEqual(result["adapter"], "OfficialAsyncTradeBridge")
            self.assertEqual(result["request_deadline_seconds"], 2.0)
            self.assertEqual(result["cycle_budget_seconds"], 5.0)
            self.assertEqual(result["submission_journal"], journal)
        sdk.AsyncTradeContext.create.assert_called_once()

    def test_startup_not_sent_journal_does_not_latch_or_invoke_sdk(self):
        fixture = boot_fixtures.BootRuntimeIntegrationTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.save(fixture.previous())
        journal = SubmissionJournal(fixture.config.output_dir / "m15_sdk_submission_journal.jsonl")
        journal.begin({"client_request_id": "admission-denied", "signal_id": "signal"},
                      "PAT-RT signal admission-denied")
        journal.finish("admission-denied", outcome="not_sent")
        result = runtime.checked_runtime_boot_startup(fixture.config)
        self.assertTrue(result["allow_reinitialize"])
        self.assertEqual(result["startup_submission_journal"]["unresolved_submission_count"], 0)
        fixture.sdk.assert_not_called()

    def test_startup_without_journal_does_not_create_one_or_invoke_sdk(self):
        fixture = boot_fixtures.BootRuntimeIntegrationTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.save(fixture.previous())
        result = runtime.checked_runtime_boot_startup(fixture.config)
        self.assertTrue(result["allow_reinitialize"])
        self.assertFalse((fixture.config.output_dir / "m15_sdk_submission_journal.jsonl").exists())
        fixture.sdk.assert_not_called()

    def test_evidence_crash_before_batch_ledger_can_repeat_request_without_wal(self):
        helper = executor_tests.M15LongbridgeRealtimeExecutionTest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = helper.make_config(root, execute_orders=True, paper_trading_approval=True)
            helper.write_jsonl(root / "signals.jsonl", [helper.signal(signal_id="crash-window")])
            client = SimpleNamespace(submit_order=Mock(return_value={
                "submitted": False, "status": "submit_unconfirmed_missing_order_id", "order_id": ""}))
            with patch("scripts.m15_longbridge_realtime_execution_lib.append_jsonl",
                       side_effect=OSError("crash before batch ledger")):
                with self.assertRaises(OSError):
                    run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z", broker_client=client)
            self.assertEqual(client.submit_order.call_count, 1)
            run_realtime_execution(config, generated_at="2026-06-04T14:00:01Z", broker_client=client)
            self.assertEqual(client.submit_order.call_count, 2)


if __name__ == "__main__":
    unittest.main()
