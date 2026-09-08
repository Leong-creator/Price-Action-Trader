"""Offline reproductions for the three boot review findings; no SDK I/O."""
from contextlib import ExitStack
import unittest
from unittest.mock import MagicMock, patch

from scripts import m15_runtime_boot_identity_lib as boot
from scripts import run_m15_longbridge_sdk_runtime as runtime
from scripts.m15_submission_journal_lib import SubmissionJournal
from tests.unit import test_m15_boot_runtime_integration as fixtures


class BootReviewRegressionsTest(unittest.TestCase):
    def setUp(self):
        self.shutdown_impl = runtime.request_runtime_shutdown
        self.fx = fixtures.BootRuntimeIntegrationTest()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)

    def test_goodall_nested_trade_fault_is_manual_across_boot(self):
        f = self.fx
        old = f.previous(trade_context_health={
            "status": "trade_context_fault_halted", "fault_halted": True,
            "requires_manual_reconciliation": True,
        })
        f.save(old)
        with self.assertRaisesRegex(RuntimeError, "explicit_fault_latched"):
            runtime.start_runtime_daemon(f.args, f.config)
        decision = f.audit()[-1]["decision"]
        self.assertEqual(decision["action"], "manual_required")
        self.assertIn("trade_context_health.fault_halted", decision["fault_markers"])
        self.assertEqual(f.read_status(), old)
        f.popen.assert_not_called()
        f.shutdown.assert_not_called()

    def test_nested_manual_or_unknown_submission_markers_latch(self):
        f = self.fx
        for extra in (
            {"trade_context_health": {"requires_manual_reconciliation": True}},
            {"trade_context_health": {"pending_reconciliation": True, "unresolved_submission_count": 1}},
            {"last_hot_pipeline": {"execution": {"results": [{"confirmation_required": True}]}}},
            {"last_hot_pipeline": {"execution": {"status": "submit_unconfirmed_missing_order_id"}}},
            {"last_hot_pipeline": {"execution": {"submission_journal_outcome": "unknown"}}},
        ):
            with self.subTest(extra=extra):
                self.assertTrue(boot.runtime_fault_markers(f.previous(**extra)))
                f.save(f.previous(**extra))
                with self.assertRaisesRegex(RuntimeError, "explicit_fault_latched"):
                    runtime.checked_runtime_boot_startup(f.config)

    def test_false_flags_normal_gate_blocks_and_old_boot_audit_do_not_latch(self):
        state = self.fx.previous(
            trade_context_health={"fault_halted": False, "requires_manual_reconciliation": False,
                                  "unresolved_submission_count": 0, "pending_reconciliation": False},
            last_hot_pipeline={"execution": {"status": "blocked_outside_regular_session",
                                             "confirmation_required": False}},
            runtime_boot_recovery={"trade_context_health": {"fault_halted": True}},
        )
        self.assertEqual(boot.runtime_fault_markers(state), [])

    def test_unresolved_disk_journal_latches_even_if_status_heartbeat_is_old(self):
        f = self.fx
        f.save(f.previous())
        journal = SubmissionJournal(f.config.output_dir / "m15_sdk_submission_journal.jsonl")
        journal.begin({"client_request_id": "req-1", "signal_id": "sig-1"}, "PAT-RT sig-1 req-1")
        for outcome in ("intent", "unknown"):
            with self.subTest(outcome=outcome):
                if outcome == "unknown":
                    journal.finish("req-1", outcome="unknown")
                with self.assertRaisesRegex(RuntimeError, "explicit_fault_latched"):
                    runtime.checked_runtime_boot_startup(f.config)
                self.assertEqual(f.audit()[-1]["decision"]["startup_submission_journal"]["unresolved_submission_count"], 1)
        f.sdk.assert_not_called()

    def test_acknowledged_disk_journal_does_not_prevent_normal_boot(self):
        f = self.fx
        f.save(f.previous())
        journal = SubmissionJournal(f.config.output_dir / "m15_sdk_submission_journal.jsonl")
        journal.begin({"client_request_id": "req-1", "signal_id": "sig-1"}, "PAT-RT sig-1 req-1")
        journal.finish("req-1", outcome="acknowledged", order_id="offline-order-id")
        self.assertTrue(runtime.checked_runtime_boot_startup(f.config)["allow_reinitialize"])

    def test_corrupt_disk_journal_is_manual_without_repair(self):
        f = self.fx
        f.save(f.previous())
        path = f.config.output_dir / "m15_sdk_submission_journal.jsonl"
        path.write_text("torn_record")
        with self.assertRaisesRegex(RuntimeError, "explicit_fault_latched"):
            runtime.checked_runtime_boot_startup(f.config)
        self.assertEqual(path.read_text(), "torn_record")

    def test_goodall_operator_stopped_reused_pid_is_not_signalled_or_replaced(self):
        f = self.fx
        f.save(f.previous(status="operator_stopped", runtime_boot_id=fixtures.NEW_BOOT,
                          config_fingerprint=runtime.config_fingerprint(f.config)))
        runtime.pid_path(f.config).write_text("321\n")
        f.proc_entry(321, [b"python", boot.RUNTIME_SCRIPT.encode(), b"--watch"])
        with patch.object(runtime, "process_alive", return_value=True), \
             patch.object(runtime, "is_expected_sdk_runtime_process", return_value=True), \
             patch.object(runtime, "process_start_ticks", return_value="99999"):
            with self.assertRaisesRegex(RuntimeError, "identity_mismatch_no_signal_sent"):
                runtime.start_runtime_daemon(f.args, f.config)
        f.shutdown.assert_not_called()
        f.popen.assert_not_called()
        self.assertEqual(runtime.pid_path(f.config).read_text(), "321\n")

    def test_missing_boot_ticks_or_wrong_config_never_permits_shutdown(self):
        f = self.fx
        for changes in ({"runtime_boot_id": ""}, {"runtime_process_start_ticks": ""},
                        {"runtime_process_start_ticks": "99999"}, {"config_fingerprint": "another-config"}):
            with self.subTest(changes=changes):
                state = f.previous(status="operator_stopped", runtime_boot_id=fixtures.NEW_BOOT,
                                   config_fingerprint=runtime.config_fingerprint(f.config))
                state.update(changes)
                f.save(state)
                runtime.pid_path(f.config).write_text("321\n")
                with patch.object(runtime, "process_alive", return_value=True), \
                     patch.object(runtime, "is_expected_sdk_runtime_process", return_value=True), \
                     patch.object(runtime, "process_start_ticks", return_value="12345"):
                    with self.assertRaisesRegex(RuntimeError, "identity_mismatch_no_signal_sent"):
                        runtime.start_runtime_daemon(f.args, f.config)
        f.shutdown.assert_not_called()
        f.popen.assert_not_called()

    def test_shutdown_identity_mismatch_prevents_initial_signal(self):
        with patch.object(runtime, "process_alive", return_value=True), \
             patch.object(runtime, "runtime_status_process_matches", return_value=False), \
             patch.object(runtime.os, "kill") as kill, patch.object(runtime.os, "killpg") as killpg:
            self.assertFalse(self.shutdown_impl(321, expected_status=self.fx.previous()))
        kill.assert_not_called()
        killpg.assert_not_called()

    def test_shutdown_rechecks_identity_before_group_escalation(self):
        with patch.object(runtime, "process_alive", return_value=True), \
             patch.object(runtime, "is_expected_sdk_runtime_process", return_value=True), \
             patch.object(runtime, "runtime_status_process_matches", side_effect=[True, False]), \
             patch.object(runtime.os, "kill") as kill, patch.object(runtime.os, "killpg") as killpg:
            self.assertFalse(self.shutdown_impl(321, timeout_seconds=0, expected_status=self.fx.previous()))
        kill.assert_called_once_with(321, runtime.signal.SIGTERM)
        killpg.assert_not_called()

    def test_unstarted_multiprocessing_worker_is_not_joined(self):
        worker = runtime.mp.get_context("spawn").Process()
        with patch.object(worker, "join", wraps=worker.join) as join:
            runtime.stop_spawned_process(worker, graceful=True)
            runtime.stop_spawned_process(worker, graceful=False)
        join.assert_not_called()
        self.assertIsNone(worker.pid)

    def test_cleanup_worker_error_cannot_skip_queue_or_replace_original_error(self):
        event, worker, queue, trade, account = (MagicMock() for _ in range(5))
        with patch.object(runtime, "stop_spawned_process", side_effect=AssertionError("can only join a started process")), \
             patch.object(runtime.signal, "signal"):
            with self.assertRaisesRegex(RuntimeError, "original_start_error"):
                try:
                    raise RuntimeError("original_start_error")
                finally:
                    runtime.cleanup_runtime_resources(
                        stop_event=event, worker=worker, message_queue=queue,
                        execution_trade=trade, account=account, previous_sigterm_handler=None,
                    )
        queue.close.assert_called_once()
        queue.join_thread.assert_called_once()
        trade.close.assert_called_once()
        account.stop.assert_called_once()

    def test_cleanup_event_error_still_attempts_every_resource(self):
        event, queue, trade, account = (MagicMock() for _ in range(4))
        event.set.side_effect = RuntimeError("event_cleanup_error")
        with patch.object(runtime.signal, "signal") as restore:
            with self.assertRaisesRegex(RuntimeError, "event_cleanup_error"):
                runtime.cleanup_runtime_resources(
                    stop_event=event, worker=None, message_queue=queue,
                    execution_trade=trade, account=account, previous_sigterm_handler=None,
                )
        queue.close.assert_called_once()
        queue.join_thread.assert_called_once()
        trade.close.assert_called_once()
        account.stop.assert_called_once()
        restore.assert_called_once()

    def test_goodall_real_watch_worker_start_failure_keeps_original_and_closes_queue(self):
        f = self.fx
        f.save(f.previous())
        f.sdk.side_effect = None
        f.sdk.return_value = object()
        account, trade, queue = MagicMock(), MagicMock(), MagicMock()
        account.snapshot.return_value = {}
        f.account.return_value = account
        f.clients.return_value = (trade, None, MagicMock())
        worker = runtime.mp.get_context("spawn").Process()
        context = MagicMock()
        context.Process.return_value = worker
        context.Queue.return_value = queue
        with ExitStack() as stack:
            for name, result in (
                ("readonly_gate_passed", (False, 0, 1)), ("verify_manifest", {"verified": False}),
                ("read_jsonl_tail_rows", []), ("held_position_monitoring_symbols", ()),
                ("load_current_sdk_intraday_context", []),
                ("restore_pipeline_observability", ([], {}, "")),
            ):
                stack.enter_context(patch.object(runtime, name, return_value=result))
            stack.enter_context(patch.object(runtime.mp, "get_context", return_value=context))
            stack.enter_context(patch.object(runtime.signal, "signal"))
            stack.enter_context(patch.object(worker, "start", side_effect=RuntimeError("original_worker_start_error")))
            join = stack.enter_context(patch.object(worker, "join", wraps=worker.join))
            with self.assertRaisesRegex(RuntimeError, "original_worker_start_error"):
                runtime.run_watch(f.config, dispatch_requested=False)
        join.assert_not_called()
        queue.close.assert_called_once()
        queue.join_thread.assert_called_once()
        account.stop.assert_called_once()
        trade.close.assert_called_once()
        self.assertIn("original_worker_start_error", f.read_status()["reason"])
        f.assert_lock_released()


if __name__ == "__main__":
    unittest.main()
