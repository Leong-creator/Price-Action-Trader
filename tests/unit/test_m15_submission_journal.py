"""Fake SDK crash/durability tests; all files are temporary and network denied."""

import json
import os
from pathlib import Path
import socket
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.m15_longbridge_sdk_runtime_lib import SdkRealtimePaperClient
from scripts.m15_official_async_trade_lib import BoundedTradeRequestGate, TradeRequestNotSent
from scripts.m15_submission_journal_lib import SubmissionJournal, SubmissionJournalError
from scripts.m15_longbridge_realtime_execution_lib import run_realtime_execution
from scripts.m15_longbridge_realtime_execution_lib import build_order_payload
from scripts.m15_longbridge_realtime_signal_router_lib import deterministic_signal_id
from scripts.m15_longbridge_realtime_position_manager_lib import deterministic_exit_signal_id
from scripts.m15_pa004_overcap_cleanup_lib import stable_cleanup_id
from scripts import run_m15_longbridge_sdk_runtime as runtime
from tests.unit import test_m15_longbridge_realtime_execution as executor_tests


ENUM = SimpleNamespace(Buy="Buy", Sell="Sell", LO="LO", MO="MO", LIT="LIT", Day="Day", RTHOnly="RTHOnly")
SDK = SimpleNamespace(OrderSide=ENUM, OrderType=ENUM, TimeInForceType=ENUM, OutsideRTH=ENUM)
PAYLOAD = {"client_request_id": "request-1", "signal_id": "signal-1", "symbol": "AAPL",
           "side": "buy", "order_type": "limit", "quantity": "1", "limit_price": "100"}
REMARK = "PAT-RT signal-1 request-1"


class SubmissionJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "journal.jsonl"
        guard = patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        self.trade = SimpleNamespace(submit_order=Mock(return_value=SimpleNamespace(order_id="mock-1")),
                                     cancel_order=Mock(), replace_order=Mock())

    def client(self, **kwargs):
        return SdkRealtimePaperClient(self.trade, SDK, submission_journal_path=self.path, **kwargs)

    def test_modern_entry_exit_and_cleanup_id_generators_can_begin(self):
        entry_id = deterministic_signal_id("M10-PA-001-1d", "AAPL", "live-event", "2026-09-08T14:00:00Z")
        exit_id = deterministic_exit_signal_id(symbol="AAPL", runtime_id="M10-PA-001-1d",
                                               exit_reason="stop_loss", source_open_order_id="mock-open")
        cleanup_id = stable_cleanup_id(batch_id="mock-batch", cleanup_epoch_id="20260908")
        self.assertEqual(len(entry_id), 22)
        for signal_id, side in ((entry_id, "buy"), (exit_id, "sell"), (cleanup_id, "sell")):
            with self.subTest(signal_id=signal_id):
                payload = build_order_payload({"signal_id": signal_id, "runtime_id": "M10-PA-001-1d"},
                                              side, "market", "AAPL", Decimal(1), Decimal(100), Decimal(0))
                if signal_id == cleanup_id:
                    payload["client_request_id"] = cleanup_id
                self.assertTrue(self.client().submit_order(payload)["submitted"])
                entry = SubmissionJournal(self.path).snapshot()[payload["client_request_id"]]
                self.assertTrue(entry["remark"].startswith(f"PAT-RT {signal_id} "))
                self.assertEqual(entry["remark"], self.trade.submit_order.call_args.kwargs["remark"])

    def test_actual_authorized_cleanup_generates_reconcilable_id(self):
        root = Path(self.tmp.name)
        (root / runtime.AUTHORIZED_ACCOUNT_EXIT_FILE).write_text(json.dumps({
            "authorized": True, "paper_simulated_only": True, "status": "authorized",
            "symbol": "LCID", "maximum_quantity": "1",
        }))
        config = replace(runtime.load_config(), output_dir=root, formal_test_epoch_id="formal-main")
        account = SimpleNamespace(snapshot=lambda: {
            "generated_at": "2026-09-08T14:00:00Z", "paper_account_verified": True,
            "positions_ok": True, "orders_ok": True, "open_orders": [],
            "positions": [{"symbol": "LCID.US", "quantity": "1", "available": "1"}],
        })
        result = runtime.run_authorized_account_exit_cycle(config, account, self.client(),
                                                           now=datetime(2026, 9, 8, 14, tzinfo=UTC))
        self.assertEqual(result["order_id"], "mock-1")
        entry = next(iter(SubmissionJournal(self.path).snapshot().values()))
        self.assertTrue(entry["key"].startswith("account-cleanup-LCID-"))
        self.assertTrue(entry["remark"].startswith(f"PAT-RT {entry['payload']['signal_id']} "))

    def test_legacy_sixty_character_signal_is_fail_closed_without_protocol_change(self):
        result = self.client().submit_order({**PAYLOAD, "signal_id": "s" * 60})
        self.assertEqual(result["status"], "submit_blocked_submission_journal_failed")
        self.trade.submit_order.assert_not_called()

    def test_intent_is_fsynced_before_sdk_and_result_afterwards_without_secrets(self):
        events = []
        real_fsync = os.fsync
        def sync(fd):
            events.append("fsync")
            return real_fsync(fd)
        def submit(**kwargs):
            events.append("SDK")
            self.assertEqual(events[:2], ["fsync", "fsync"])
            self.assertEqual(kwargs["remark"], REMARK)
            self.assertEqual(SubmissionJournal(self.path).snapshot()["request-1"]["outcome"], "intent")
            return SimpleNamespace(order_id="mock-1")
        self.trade.submit_order.side_effect = submit
        client = self.client()
        with patch("scripts.m15_submission_journal_lib.os.fsync", side_effect=sync):
            result = client.submit_order({**PAYLOAD, "access_token": "NEVER-PERSIST-ME", "sdk_config": {"token": "secret"}})
        self.assertEqual(events, ["fsync", "fsync", "SDK", "fsync", "fsync"])
        self.assertEqual(result["status"], "submitted")
        state = SubmissionJournal(self.path).snapshot()["request-1"]
        self.assertEqual(state["outcome"], "acknowledged")
        self.assertNotIn("NEVER-PERSIST-ME", self.path.read_text())
        self.assertNotIn("access_token", self.path.read_text())
        self.assertNotIn("Filled", self.path.read_text())

    def test_crash_after_acceptance_restarts_blocked_until_exact_unique_order(self):
        self.trade.submit_order.side_effect = SystemExit("process lost before receipt")
        with self.assertRaises(SystemExit):
            self.client().submit_order(PAYLOAD)
        restarted = self.client()
        self.assertEqual(restarted.submit_order(PAYLOAD)["status"], "submit_unconfirmed_missing_order_id")
        fresh = {**PAYLOAD, "signal_id": "signal-2", "client_request_id": "request-2"}
        self.assertEqual(restarted.submit_order(fresh)["status"], "submit_blocked_pending_reconciliation")
        self.assertFalse(restarted.reconcile_submissions({"orders": []}))
        self.assertFalse(restarted.reconcile_submissions({"orders": [
            {"remark": REMARK + "-not-exact", "order_id": "mock-1"}]}))
        self.assertFalse(restarted.reconcile_submissions({"orders": [
            {"remark": REMARK, "order_id": "mock-1"}, {"remark": REMARK, "order_id": "mock-2"}]}))
        self.assertFalse(restarted.reconcile_submissions({"orders": [{"remark": REMARK}]}))
        self.assertEqual(self.trade.submit_order.call_count, 1)
        self.assertTrue(restarted.reconcile_submissions({"orders": [
            {"remark": REMARK, "order_id": "mock-1", "status": "Filled"}]}))
        self.assertTrue(restarted.submission_journal_health()["ok"])
        self.assertEqual(restarted.submit_order(PAYLOAD)["order_id"], "mock-1")
        self.assertEqual(self.trade.submit_order.call_count, 1)
        self.trade.submit_order.side_effect = None
        self.trade.submit_order.return_value = SimpleNamespace(order_id="mock-2")
        self.assertEqual(restarted.submit_order(fresh)["order_id"], "mock-2")
        self.assertNotIn("Filled", self.path.read_text())

    def test_acknowledged_result_survives_restart_before_executor_ledger(self):
        original = self.client().submit_order(PAYLOAD)
        self.assertTrue(original["sdk_request_sent"])
        self.assertFalse(original["submission_journal_reused"])
        response = self.client().submit_order(PAYLOAD)
        self.assertTrue(response["submitted"])
        self.assertEqual(response["order_id"], "mock-1")
        self.assertFalse(response["sdk_request_sent"])
        self.assertTrue(response["submission_journal_reused"])
        self.assertTrue(response["recovered_order"])
        self.assertEqual(response["submission_confirmation_source"], "durable_journal")
        self.trade.submit_order.assert_called_once()

    def test_unknown_result_survives_restart_and_blocks_other_write_methods(self):
        self.trade.submit_order.side_effect = TimeoutError("lost reply")
        self.client().submit_order(PAYLOAD)
        restarted = self.client()
        self.assertFalse(restarted.submission_journal_health()["ok"])
        with self.assertRaises(SubmissionJournalError):
            restarted.cancel_order("existing-order")
        with self.assertRaises(SubmissionJournalError):
            restarted.replace_order("existing-order", 1, 100)
        self.trade.cancel_order.assert_not_called()
        self.trade.replace_order.assert_not_called()
        restarted.submit_order(PAYLOAD)
        self.trade.submit_order.assert_called_once()

    def test_not_sent_admission_is_durable_and_releases_for_fresh_key(self):
        gate = BoundedTradeRequestGate(max_calls=1)
        gate.call(lambda: None)
        first = self.client(request_gate=gate).submit_order(PAYLOAD)
        self.assertEqual(first["status"], "submit_blocked_trade_admission")
        self.assertFalse(first["confirmation_required"])
        self.trade.submit_order.assert_not_called()
        self.assertEqual(SubmissionJournal(self.path).snapshot()["request-1"]["outcome"], "not_sent")
        restarted = self.client()
        self.assertTrue(restarted.submission_journal_health()["ok"])
        self.assertEqual(restarted.submit_order(PAYLOAD)["status"], "submit_blocked_trade_admission")
        self.assertTrue(restarted.submit_order({**PAYLOAD, "client_request_id": "request-2", "signal_id": "signal-2"})["submitted"])
        self.trade.submit_order.assert_called_once()

    def test_cycle_budget_not_sent_is_durable_and_next_fresh_cycle_can_submit(self):
        now = [0.0]
        gate = BoundedTradeRequestGate(monotonic_clock=lambda: now[0])
        gate.begin_cycle(5.0, reserve_seconds=2.0)
        now[0] = 3.001
        client = self.client(request_gate=gate)
        result = client.submit_order(PAYLOAD)
        self.assertEqual(result["status"], "submit_blocked_trade_admission")
        self.trade.submit_order.assert_not_called()
        self.assertEqual(SubmissionJournal(self.path).snapshot()["request-1"]["outcome"], "not_sent")
        self.assertTrue(client.submission_journal_health()["ok"])
        gate.begin_cycle(now[0] + 5, reserve_seconds=2.0)
        self.assertTrue(client.submit_order({**PAYLOAD, "client_request_id": "fresh", "signal_id": "fresh-signal"})["submitted"])
        self.trade.submit_order.assert_called_once()

    def test_not_sent_exception_inside_sdk_is_not_admission_proof(self):
        self.trade.submit_order.side_effect = TradeRequestNotSent("not an admission exception")
        result = self.client().submit_order(PAYLOAD)
        self.assertEqual(result["status"], "submit_unconfirmed_missing_order_id")
        self.assertEqual(SubmissionJournal(self.path).snapshot()["request-1"]["outcome"], "unknown")

    def test_missing_or_unstable_keys_never_reach_sdk(self):
        for bad in ({"client_request_id": ""}, {"client_request_id": None},
                    {"client_request_id": "contains space"}, {"signal_id": ""}):
            with self.subTest(bad=bad):
                result = self.client().submit_order({**PAYLOAD, **bad})
                self.assertEqual(result["status"], "submit_blocked_submission_journal_failed")
        self.trade.submit_order.assert_not_called()

    def test_key_reuse_with_changed_payload_is_rejected(self):
        self.client().submit_order(PAYLOAD)
        result = self.client().submit_order({**PAYLOAD, "quantity": "2"})
        self.assertEqual(result["status"], "submit_blocked_submission_journal_failed")
        self.trade.submit_order.assert_called_once()

    def test_truncated_remark_collision_is_rejected_before_second_submit(self):
        payload = {**PAYLOAD, "signal_id": "s" * 52, "client_request_id": "same-prefix-key-1"}
        self.assertTrue(self.client().submit_order(payload)["submitted"])
        result = self.client().submit_order({**payload, "client_request_id": "same-prefix-key-2"})
        self.assertEqual(result["status"], "submit_blocked_submission_journal_failed")
        self.trade.submit_order.assert_called_once()

    def test_torn_or_corrupted_record_fails_closed_without_truncation(self):
        journal = SubmissionJournal(self.path)
        journal.begin(PAYLOAD, REMARK)
        valid = self.path.read_bytes()
        for corrupt in (valid + b'{"record":', valid[:-1], valid.replace(b'"intent"', b'"Intent"')):
            with self.subTest(corrupt=corrupt[-20:]):
                self.path.write_bytes(corrupt)
                with self.assertRaises(SubmissionJournalError):
                    self.client()
                self.assertEqual(self.path.read_bytes(), corrupt)
        self.trade.submit_order.assert_not_called()

    def test_before_intent_fsync_failure_never_calls_sdk_and_stops_instance(self):
        client = self.client()
        with patch("scripts.m15_submission_journal_lib.os.fsync", side_effect=OSError("disk failed")):
            result = client.submit_order(PAYLOAD)
        self.assertEqual(result["status"], "submit_blocked_submission_journal_failed")
        self.assertTrue(client.submission_journal_health()["fault_halted"])
        client.submit_order({**PAYLOAD, "client_request_id": "another"})
        self.trade.submit_order.assert_not_called()
        # A fully buffered intent might have reached disk; it must remain pending.
        restarted = self.client()
        self.assertEqual(restarted.submit_order(PAYLOAD)["status"], "submit_unconfirmed_missing_order_id")

    def test_after_receipt_append_failure_returns_unknown_and_restart_blocks(self):
        client = self.client()
        original = client._submission_journal._append
        def append(handle, row):
            if row["outcome"] != "intent":
                raise OSError("cannot record acknowledgement")
            return original(handle, row)
        with patch.object(client._submission_journal, "_append", side_effect=append):
            result = client.submit_order(PAYLOAD)
        self.assertEqual(result["status"], "submit_unconfirmed_missing_order_id")
        self.assertFalse(result["submitted"])
        self.assertEqual(result["order_id"], "")
        self.assertEqual(result["response"]["order_id"], "")
        self.assertEqual(result["observed_broker_order_id"], "mock-1")
        self.assertTrue(client.submission_journal_health()["fault_halted"])
        client.submit_order(PAYLOAD)
        self.client().submit_order(PAYLOAD)
        self.trade.submit_order.assert_called_once()

    def test_after_receipt_fsync_failure_stops_current_instance(self):
        client = self.client()
        real_fsync = os.fsync
        count = [0]
        def fsync(fd):
            count[0] += 1
            if count[0] == 3:
                raise OSError("result fsync failed")
            return real_fsync(fd)
        with patch("scripts.m15_submission_journal_lib.os.fsync", side_effect=fsync):
            result = client.submit_order(PAYLOAD)
        self.assertEqual(result["status"], "submit_unconfirmed_missing_order_id")
        self.assertTrue(result["submission_journal_failed"])
        self.assertEqual(result["observed_broker_order_id"], "mock-1")
        self.assertFalse(result["submitted"])
        self.assertTrue(client.submission_journal_health()["fault_halted"])
        client.submit_order(PAYLOAD)
        self.trade.submit_order.assert_called_once()

    def test_reconciliation_write_failure_does_not_unlock(self):
        self.trade.submit_order.side_effect = TimeoutError("unknown")
        self.client().submit_order(PAYLOAD)
        restarted = self.client()
        with patch.object(restarted._submission_journal, "_append", side_effect=OSError("disk full")):
            self.assertFalse(restarted.reconcile_submissions({"orders": [{"remark": REMARK, "order_id": "mock-1"}]}))
        self.assertTrue(restarted.submission_journal_health()["fault_halted"])
        self.client().submit_order({**PAYLOAD, "client_request_id": "new-request"})
        self.trade.submit_order.assert_called_once()

    def test_reconciliation_note_failure_remains_stopped(self):
        self.trade.submit_order.side_effect = TimeoutError("unknown")
        self.client().submit_order(PAYLOAD)
        client = self.client(on_submission=Mock(side_effect=OSError("account note failed")))
        self.assertFalse(client.reconcile_submissions({"orders": [{"remark": REMARK, "order_id": "mock-1"}]}))
        self.assertTrue(client.submission_journal_health()["fault_halted"])
        client.submit_order({**PAYLOAD, "client_request_id": "new"})
        self.trade.submit_order.assert_called_once()

    def test_two_preexisting_clients_reread_journal_before_writing(self):
        first, second = self.client(), self.client()
        self.trade.submit_order.side_effect = TimeoutError("unknown")
        first.submit_order(PAYLOAD)
        response = second.submit_order({**PAYLOAD, "client_request_id": "new-key"})
        self.assertEqual(response["status"], "submit_blocked_pending_reconciliation")
        self.trade.submit_order.assert_called_once()

    def test_executor_batch_crash_no_longer_resends_with_journal_after_restart(self):
        helper = executor_tests.M15LongbridgeRealtimeExecutionTest()
        root = Path(self.tmp.name)
        config = helper.make_config(root, execute_orders=True, paper_trading_approval=True)
        helper.write_jsonl(root / "signals.jsonl", [helper.signal(signal_id="crash-window")])
        self.trade.submit_order.side_effect = TimeoutError("accepted but response lost")
        with patch("scripts.m15_longbridge_realtime_execution_lib.append_jsonl", side_effect=OSError("batch crash")):
            with self.assertRaises(OSError):
                run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z", broker_client=self.client())
        result = run_realtime_execution(config, generated_at="2026-06-04T14:00:01Z", broker_client=self.client())
        self.assertEqual(result["submitted_count"], 0)
        self.assertEqual(result["unconfirmed_submission_count"], 1)
        self.trade.submit_order.assert_called_once()


if __name__ == "__main__":
    unittest.main()
