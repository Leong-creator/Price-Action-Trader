"""Real parent-loop replay: read-only means no broker writes, including exits."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from tests.unit import test_m15_session_evidence as session


class ReadonlyDispatchGuardsTest(unittest.TestCase):
    def test_real_dispatch_with_exit_signal_and_no_client_never_calls_executor(self):
        runtime = session.runtime
        with TemporaryDirectory() as temporary:
            config = replace(runtime.load_config(), market_events_path=Path(temporary) / "events.jsonl")
            rows = session.bars(session.at(8, 10, 0), runtime.configured_trading_symbols(config))
            account = MagicMock()
            account.snapshot.return_value = {"positions": [{"symbol": "SPY.US", "quantity": "10"}]}
            exit_signal = {"signal_id": "existing-position-exit", "symbol": "SPY", "action": "exit_long"}
            cache = []
            with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
                 patch.object(runtime, "fresh_market_events", side_effect=lambda values, *a, **kw: values), \
                 patch.object(runtime, "load_formal_test_marker", return_value={}), \
                 patch("scripts.m15_longbridge_realtime_signal_router_lib.run_realtime_signal_router", return_value={}), \
                 patch("scripts.m15_longbridge_realtime_position_manager_lib.run_realtime_position_manager",
                       return_value={"emitted_exit_signal_events": [exit_signal]}) as manager, \
                 patch("scripts.m15_longbridge_realtime_execution_lib.run_realtime_execution",
                       side_effect=AssertionError("read-only executor mutation")) as executor:
                runtime.dispatch_completed_rows(config, rows, runtime.MarketEventContext(), account, None,
                    signal_event_cache=cache, signal_id_cache=set(), execution_ledger_cache=[],
                    new_entry_submission_enabled=False)
            manager.assert_called_once()
            self.assertIn(exit_signal, cache)
            executor.assert_not_called()

    def test_full_session_existing_orders_and_pending_flatten_never_mutate_broker(self):
        for gate_passed in (False, True):
            with self.subTest(gate_already_passed=gate_passed):
                captured = {}
                write_client = []

                class TrackingPatch:
                    def __call__(self, target, *args, **kwargs):
                        if target.endswith("advance_cleanup_state"):
                            kwargs["side_effect"] = AssertionError("read-only capital cleanup")
                        return patch(target, *args, **kwargs)

                    @contextmanager
                    def object(self, target, name, *args, **kwargs):
                        if name in {"run_pending_flatten_cycle", "run_authorized_account_exit_cycle",
                                    "run_sdk_order_maintenance"}:
                            kwargs["side_effect"] = AssertionError("read-only entered " + name)
                        if name == "load_formal_test_marker":
                            kwargs["return_value"] = {"status": "pending_flatten", "test_epoch_id": "test",
                                "short_test_epoch_id": "test-short", "test_started_at": "2026-09-08T13:00:00Z"}
                        if name == "SdkAccountProcessCoordinator":
                            account = kwargs["return_value"]
                            snapshot = account.snapshot.side_effect
                            account.snapshot.side_effect = lambda: {
                                **snapshot(), "account_channel": "lb_papertrading",
                                "positions": [{"symbol": "SPY.US", "quantity": "10"}],
                                "orders": [{"order_id": "existing-order", "symbol": "SPY.US",
                                            "status": "New", "side": "Sell", "quantity": "10"}]}
                        if name == "build_sdk_trade_clients":
                            build = kwargs["side_effect"]
                            def checked_build(*a, **kw):
                                result = build(*a, **kw)
                                client = result[2]
                                for method in ("submit_order", "cancel_order", "replace_order"):
                                    getattr(client, method).side_effect = AssertionError("broker mutation: " + method)
                                write_client.append(client)
                                return result
                            kwargs["side_effect"] = checked_build
                        with patch.object(target, name, *args, **kwargs) as mocked:
                            if target is session.runtime:
                                captured[name] = mocked
                            yield mocked

                harness = session.WatchLoopTest()
                with patch.object(session, "patch", TrackingPatch()), \
                     patch.object(session.runtime, "assert_no_legacy_quote_processes", create=True), \
                     patch("socket.socket", side_effect=AssertionError("network forbidden")):
                    result, statuses, gates, dispatched = harness.watch(
                        session.at(8, 9, 29), harness.day_events(8), dispatch=False,
                        gate_passed=gate_passed, validation_approved=True, flatten_blocks_new_entries=False)
                self.assertEqual(result, 0)
                self.assertEqual(len(dispatched), 78)
                self.assertTrue(gates, "must exercise full-session gate transition")
                self.assertTrue(all(not enabled and client is None for _, _, enabled, client in dispatched))
                self.assertTrue(all(not row.get("extra", {}).get("dispatch_enabled") for row in statuses))
                for name in ("run_pending_flatten_cycle", "run_authorized_account_exit_cycle",
                             "run_sdk_order_maintenance"):
                    captured[name].assert_not_called()
                self.assertEqual(len(write_client), 1)
                for method in ("submit_order", "cancel_order", "replace_order"):
                    getattr(write_client[0], method).assert_not_called()


if __name__ == "__main__":
    unittest.main()
