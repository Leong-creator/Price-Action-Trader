from __future__ import annotations

import fcntl
import multiprocessing as mp
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import run_m15_longbridge_sdk_runtime as runtime


def ignore_term_and_block(ready):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    ready.set()
    while True:
        time.sleep(0.1)


def parent_with_blocked_quote(path, child_pid, ready):
    context = mp.get_context("spawn")
    with open(path, "a+") as owner:
        fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        worker = context.Process(target=runtime.quote_worker_with_owned_lock,
            args=(ignore_term_and_block, (ready,), runtime.QuoteWorkerLock(owner.fileno()), os.getpid()))
        worker.start()
        if not ready.wait(10):
            raise RuntimeError("child_start_failed")
        child_pid.value = worker.pid
        while True:
            time.sleep(0.1)


class StageDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.stage = runtime.QuoteWorkerStageDeadline(SimpleNamespace(
            subscription_deadline_seconds=45, daily_context_deadline_seconds=600), 10)

    def stage_at(self, phase, started, received=None):
        self.stage.consume({"kind": "sdk_stage", "phase": phase,
                            "started_monotonic": started}, started if received is None else received)

    def test_progress_and_duplicate_messages_do_not_extend_initialization(self):
        self.stage_at("initializing", 40)
        self.stage.consume({"kind": "subscription_progress", "completed": 50}, 54)
        self.assertIsNone(self.stage.overdue(55))
        self.assertEqual(self.stage.overdue(56)["phase"], "initializing")

    def test_delayed_notifications_use_child_start_not_receipt_time(self):
        self.stage_at("daily_context", 12, 100)
        self.stage_at("subscribing", 20, 100)
        self.assertEqual(self.stage.overdue(100), {
            "phase": "subscribing", "deadline_seconds": 45, "elapsed_seconds": 80})

    def test_late_transition_cannot_erase_previous_expiry(self):
        self.stage_at("daily_context", 56)
        self.stage_at("subscribing", 57)
        self.assertEqual(self.stage.overdue(60)["phase"], "initializing")

    def test_all_startup_and_refresh_phases_have_absolute_limits(self):
        self.stage_at("daily_context", 12)
        self.assertIsNone(self.stage.overdue(612))
        self.stage_at("subscribing", 100)
        self.stage_at("initial_snapshot", 120)
        self.assertEqual(self.stage.overdue(166)["phase"], "initial_snapshot")
        self.stage_at("streaming", 130)
        self.assertIsNone(self.stage.overdue(10000))
        self.stage_at("daily_refresh", 10000)
        self.stage.consume({"kind": "daily_context_progress", "completed": 100}, 10599)
        self.stage_at("daily_refresh", 10599)
        self.assertEqual(self.stage.overdue(10601)["phase"], "daily_refresh")

    def test_invalid_phase_and_timestamps_fail_closed(self):
        for phase, started in [("streaming", 12), ("daily_context", float("nan")),
                               ("daily_context", 9), ("daily_context", 21)]:
            with self.subTest(phase=phase, started=started), self.assertRaises(ValueError):
                self.stage_at(phase, started, 20)

    def test_ready_received_after_streaming_cannot_reset_child_clock(self):
        self.stage_at("daily_context", 12)
        self.stage_at("subscribing", 15)
        self.stage_at("initial_snapshot", 20)
        self.stage_at("streaming", 25)
        self.stage.acknowledge_ready(40)
        self.stage_at("daily_refresh", 30, 45)
        self.stage.acknowledge_ready(50)
        self.assertEqual(self.stage.started, 30)
        self.assertEqual(self.stage.phase, "daily_refresh")

    def test_refresh_cannot_pause_opening_heartbeat_or_its_own_deadline(self):
        config = SimpleNamespace(market_timezone="America/New_York", market_holidays=(),
                                 regular_session_start_time="09:30", regular_session_end_time="16:00")
        self.stage.phase = "daily_refresh"
        self.assertFalse(runtime.quote_worker_heartbeat_required(self.stage, config,
                         datetime.fromisoformat("2026-09-18T16:10:00-04:00")))
        self.assertTrue(runtime.quote_worker_heartbeat_required(self.stage, config,
                        datetime.fromisoformat("2026-09-21T09:30:00-04:00")))
        self.assertEqual(self.stage.overdue(611)["phase"], "daily_refresh")
        self.stage.phase = "streaming"
        self.assertTrue(runtime.quote_worker_heartbeat_required(self.stage, config,
                        datetime.fromisoformat("2026-09-18T16:10:00-04:00")))


class WorkerTerminationTests(unittest.TestCase):
    def test_import_from_noncanonical_prefix_cannot_exec_or_connect(self):
        # Keep installed dependencies available while simulating a different
        # interpreter prefix. Old module-level reexec fails at the sentinel.
        script = '''
import os, socket, sys
sys.prefix = "/definitely-not-the-project-venv"
def forbidden(*args, **kwargs):
    raise AssertionError("import attempted exec or network")
os.execve = forbidden
socket.socket.connect = forbidden
socket.create_connection = forbidden
from scripts import run_m15_longbridge_sdk_runtime
assert "longbridge.openapi" not in sys.modules
print("import-only-ok")
'''
        result = subprocess.run([sys.executable, "-c", script], cwd=runtime.ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "import-only-ok")

    def test_real_spawned_worker_ignoring_term_is_killed_and_reaped(self):
        context = mp.get_context("spawn")
        ready = context.Event()
        worker = context.Process(target=ignore_term_and_block, args=(ready,))
        worker.start()
        try:
            self.assertTrue(ready.wait(10))
            started = time.monotonic()
            runtime.stop_spawned_process(worker, graceful=False)
            self.assertFalse(worker.is_alive())
            self.assertEqual(worker.exitcode, -signal.SIGKILL)
            self.assertLess(time.monotonic() - started, 7)
        finally:
            if worker.is_alive():
                worker.kill()
            worker.join(5)
            worker.close()

    def test_real_spawned_quote_keeps_flock_after_parent_copy_closes(self):
        context = mp.get_context("spawn")
        ready = context.Event()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quote.lock"
            owner = path.open("a+")
            fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            worker = context.Process(target=runtime.quote_worker_with_owned_lock,
                args=(ignore_term_and_block, (ready,), runtime.QuoteWorkerLock(owner.fileno()), os.getpid()))
            worker.start()
            try:
                self.assertTrue(ready.wait(10))
                owner.close()
                with path.open("a+") as contender:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                runtime.stop_spawned_process(worker, graceful=False)
                with path.open("a+") as contender:
                    fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                owner.close()
                if worker.is_alive():
                    worker.kill()
                worker.join(5)
                worker.close()

    def test_parent_sigkill_stops_native_child_and_releases_connection_lock(self):
        context = mp.get_context("spawn")
        child_pid = context.Value("i", 0)
        ready = context.Event()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quote.lock"
            parent = context.Process(target=parent_with_blocked_quote, args=(str(path), child_pid, ready))
            parent.start()
            try:
                deadline = time.monotonic() + 15
                while not child_pid.value and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertGreater(child_pid.value, 0)
                parent.kill()
                parent.join(5)
                self.assertFalse(parent.is_alive())
                # Orphans may briefly be zombies until their new parent reaps
                # them; flock release proves the SDK process owns no live fd.
                deadline = time.monotonic() + 5
                with path.open("a+") as contender:
                    while True:
                        try:
                            fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            if time.monotonic() >= deadline:
                                self.fail("quote child retained lock after parent SIGKILL")
                            time.sleep(0.02)
                stat = Path(f"/proc/{child_pid.value}/stat")
                if stat.exists():
                    self.assertEqual(stat.read_text().split(")", 1)[1].split()[0], "Z")
            finally:
                if parent.is_alive():
                    parent.kill()
                parent.join(5)
                if child_pid.value:
                    try:
                        os.kill(child_pid.value, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                parent.close()

    def test_unreapable_worker_preserves_queue_and_other_cleanup_runs(self):
        worker = Mock(pid=123)
        worker.is_alive.return_value = True
        worker.terminate.side_effect = PermissionError("denied")
        worker.kill.side_effect = PermissionError("denied")
        messages, account, trade, state = Mock(), Mock(), Mock(), {}
        retained = []
        with patch.object(runtime, "_UNREAPED_WORKER_RESOURCES", retained), \
             patch.object(runtime.signal, "signal"), patch.object(runtime.sys, "stderr"):
            with self.assertRaises(runtime.WorkerTerminationError):
                runtime.cleanup_runtime_resources(stop_event=Mock(), worker=worker,
                    message_queue=messages, execution_trade=trade, account=account,
                    previous_sigterm_handler=None, resource_state=state)
        worker.kill.assert_called_once()
        messages.close.assert_not_called()
        messages.join_thread.assert_not_called()
        trade.close.assert_called_once()
        account.stop.assert_called_once()
        self.assertEqual(retained, [(worker, messages)])
        self.assertEqual(state["unreaped_quote_worker_pid"], 123)

    def test_cleanup_failure_does_not_replace_original_exception(self):
        worker = Mock(pid=123)
        state = {}
        with patch.object(runtime, "stop_spawned_process", side_effect=runtime.WorkerTerminationError("unreaped")), \
             patch.object(runtime, "_UNREAPED_WORKER_RESOURCES", []), \
             patch.object(runtime.signal, "signal"), patch.object(runtime.sys, "stderr"):
            with self.assertRaisesRegex(ValueError, "original"):
                try:
                    raise ValueError("original")
                finally:
                    runtime.cleanup_runtime_resources(stop_event=Mock(), worker=worker,
                        message_queue=Mock(), execution_trade=Mock(), account=Mock(),
                        previous_sigterm_handler=None, resource_state=state)
        self.assertTrue(state["quote_worker_cleanup_failed"])


if __name__ == "__main__":
    unittest.main()
