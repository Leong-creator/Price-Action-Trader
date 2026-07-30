import json
import os
import signal
import tempfile
import time
import unittest
from functools import partial
from pathlib import Path

from scripts.m15_longbridge_sdk_account_worker_lib import (
    AccountWorkerConfig,
    SpawnAccountSnapshotWorker,
)


class ScriptedProvider:
    def __init__(self, plan_index, behavior, state_dir):
        self.plan_index = plan_index
        self.behavior = behavior
        self.state_dir = Path(state_dir)
        self.refresh_calls = 0

    def refresh(self):
        self.refresh_calls += 1
        action = self._action("refresh", self.refresh_calls - 1)
        log_event(
            self.state_dir,
            {
                "event": "refresh",
                "plan_index": self.plan_index,
                "call_index": self.refresh_calls,
                "pid": os.getpid(),
                "action": action["kind"],
            },
        )
        if action["kind"] == "hang":
            while True:
                time.sleep(1.0)
        return dict(action["snapshot"])

    def stop(self):
        action = self.behavior.get("stop", {"kind": "return"})
        log_event(
            self.state_dir,
            {
                "event": "stop",
                "plan_index": self.plan_index,
                "pid": os.getpid(),
                "action": action["kind"],
            },
        )
        if action["kind"] == "hang_ignore_sigterm":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            while True:
                time.sleep(1.0)

    def _action(self, key, index):
        configured = self.behavior.get(key, [])
        if not configured:
            return {"kind": "snapshot", "snapshot": {"trusted": True}}
        if index >= len(configured):
            return configured[-1]
        return configured[index]


def next_plan_index(state_dir):
    counter_path = Path(state_dir) / "generation_counter.txt"
    if not counter_path.exists():
        counter_path.write_text("0\n", encoding="utf-8")
    with counter_path.open("r+", encoding="utf-8") as handle:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        raw = handle.read().strip() or "0"
        plan_index = int(raw)
        handle.seek(0)
        handle.truncate()
        handle.write(f"{plan_index + 1}\n")
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return plan_index


def log_event(state_dir, payload):
    event_path = Path(state_dir) / "events.jsonl"
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_events(state_dir):
    event_path = Path(state_dir) / "events.jsonl"
    if not event_path.exists():
        return []
    return [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def scripted_provider_factory(plan, state_dir):
    plan_index = next_plan_index(state_dir)
    behavior = plan[plan_index] if plan_index < len(plan) else plan[-1]
    log_event(
        state_dir,
        {
            "event": "provider_created",
            "plan_index": plan_index,
            "pid": os.getpid(),
        }
    )
    return ScriptedProvider(plan_index, behavior, state_dir)


def delayed_scripted_provider_factory(plan, state_dir, delay_seconds):
    time.sleep(delay_seconds)
    return scripted_provider_factory(plan, state_dir)


def trusted_snapshot(timestamp, marker):
    return {
        "generated_at": timestamp,
        "account_channel": "lb_papertrading",
        "paper_account_verified": True,
        "critical_errors": [],
        "orders": [],
        "open_orders": [],
        "trusted": True,
        "marker": marker,
    }


class M15LongbridgeSdkAccountWorkerTest(unittest.TestCase):
    def test_startup_grace_is_separate_from_regular_refresh_deadline(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        state_dir = Path(temp_dir.name)
        plan = [{"refresh": [{"kind": "snapshot", "snapshot": trusted_snapshot("2026-07-21T01:06:00Z", "startup-ok")}]}]
        worker = SpawnAccountSnapshotWorker(
            partial(delayed_scripted_provider_factory, plan, str(state_dir), 0.15),
            config=AccountWorkerConfig(
                refresh_total_deadline_seconds=0.05,
                startup_total_deadline_seconds=0.5,
            ),
        )
        try:
            snapshot = worker.refresh()
        finally:
            worker.stop()

        self.assertEqual(snapshot["marker"], "startup-ok")
        self.assertEqual(snapshot["worker_refresh_status"], "healthy")
        self.assertFalse(snapshot["worker_last_refresh_timed_out"])

    def make_worker(self, plan, *, config):
        temp_dir = tempfile.TemporaryDirectory()
        state_dir = Path(temp_dir.name)
        self.addCleanup(temp_dir.cleanup)
        worker = SpawnAccountSnapshotWorker(
            partial(scripted_provider_factory, plan, str(state_dir)),
            config=config,
        )
        return worker, temp_dir, state_dir

    def test_refresh_timeout_preserves_last_trusted_snapshot_and_opens_circuit(self) -> None:
        config = AccountWorkerConfig(
            refresh_total_deadline_seconds=0.2,
            circuit_breaker_consecutive_timeouts=1,
            circuit_recovery_consecutive_successes=2,
        )
        plan = [
            {
                "refresh": [
                    {"kind": "snapshot", "snapshot": trusted_snapshot("2026-07-21T01:00:00Z", "healthy-1")},
                    {"kind": "hang"},
                ]
            },
        ]
        worker, temp_dir, state_dir = self.make_worker(plan, config=config)
        try:
            healthy = worker.refresh()
            timed_out = worker.refresh()
        finally:
            worker.stop()

        self.assertEqual(healthy["generated_at"], "2026-07-21T01:00:00Z")
        self.assertEqual(timed_out["generated_at"], "2026-07-21T01:00:00Z")
        self.assertEqual(timed_out["last_trusted_generated_at"], "2026-07-21T01:00:00Z")
        self.assertTrue(timed_out["worker_last_refresh_timed_out"])
        self.assertTrue(timed_out["worker_circuit_open"])
        self.assertEqual(timed_out["worker_refresh_status"], "timeout_circuit_open")
        self.assertIn("refresh_timeout_circuit_open_after_1_consecutive_timeouts", timed_out["worker_circuit_reason"])
        refresh_events = [row for row in read_events(state_dir) if row.get("event") == "refresh"]
        self.assertEqual(len(refresh_events), 2)

    def test_timeout_restart_rebuilds_worker_and_publishes_new_generation(self) -> None:
        config = AccountWorkerConfig(
            refresh_total_deadline_seconds=0.2,
            circuit_breaker_consecutive_timeouts=3,
        )
        plan = [
            {"refresh": [{"kind": "hang"}]},
            {"refresh": [{"kind": "snapshot", "snapshot": trusted_snapshot("2026-07-21T01:01:00Z", "healthy-2")}]},
        ]
        worker, temp_dir, state_dir = self.make_worker(plan, config=config)
        try:
            first = worker.refresh()
        finally:
            worker.stop()

        self.assertEqual(first["worker_refresh_status"], "healthy")
        self.assertTrue(first["worker_retried_after_restart"])
        self.assertEqual(first["worker_restart_count"], 1)
        self.assertEqual(first["generated_at"], "2026-07-21T01:01:00Z")
        self.assertGreaterEqual(first["worker_generation"], 2)
        created = [row for row in read_events(state_dir) if row.get("event") == "provider_created"]
        self.assertEqual(len(created), 2)

    def test_untrusted_sdk_result_preserves_last_trusted_snapshot_and_restarts_worker(self) -> None:
        config = AccountWorkerConfig(
            refresh_total_deadline_seconds=0.2,
            startup_total_deadline_seconds=0.5,
            circuit_breaker_consecutive_timeouts=2,
        )
        untrusted = {
            **trusted_snapshot("2026-07-21T01:01:30Z", "untrusted"),
            "trusted": False,
            "paper_account_verified": False,
            "critical_errors": ["positions_sdk_failed"],
        }
        plan = [
            {
                "refresh": [
                    {"kind": "snapshot", "snapshot": trusted_snapshot("2026-07-21T01:01:00Z", "healthy")},
                    {"kind": "snapshot", "snapshot": untrusted},
                ]
            },
            {
                "refresh": [
                    {"kind": "snapshot", "snapshot": trusted_snapshot("2026-07-21T01:02:00Z", "recovered")},
                ]
            },
        ]
        worker, _temp_dir, _state_dir = self.make_worker(plan, config=config)
        try:
            healthy = worker.refresh()
            preserved = worker.refresh()
            recovered = worker.refresh()
        finally:
            worker.stop()

        self.assertEqual(healthy["generated_at"], "2026-07-21T01:01:00Z")
        self.assertEqual(preserved["generated_at"], "2026-07-21T01:01:00Z")
        self.assertEqual(preserved["last_trusted_generated_at"], "2026-07-21T01:01:00Z")
        self.assertEqual(
            preserved["worker_refresh_status"],
            "untrusted_snapshot_preserved_last_good",
        )
        self.assertEqual(preserved["rejected_snapshot_critical_errors"], ["positions_sdk_failed"])
        self.assertEqual(preserved["worker_consecutive_untrusted_results"], 1)
        self.assertEqual(recovered["generated_at"], "2026-07-21T01:02:00Z")
        self.assertEqual(recovered["worker_refresh_status"], "healthy")
        self.assertEqual(recovered["worker_consecutive_untrusted_results"], 0)

    def test_stop_escalates_to_kill_when_provider_stop_hangs(self) -> None:
        config = AccountWorkerConfig(
            refresh_total_deadline_seconds=0.2,
            stop_timeout_seconds=0.1,
            terminate_timeout_seconds=0.1,
            kill_timeout_seconds=0.3,
        )
        plan = [
            {
                "refresh": [{"kind": "snapshot", "snapshot": trusted_snapshot("2026-07-21T01:02:00Z", "healthy-3")}],
                "stop": {"kind": "hang_ignore_sigterm"},
            }
        ]
        worker, temp_dir, _state_dir = self.make_worker(plan, config=config)
        try:
            worker.refresh()
            summary = worker.stop()
        finally:
            pass

        self.assertTrue(summary["terminate_sent"])
        self.assertTrue(summary["kill_sent"])
        self.assertTrue(summary["stopped"])

    def test_circuit_blocks_immediate_retry_then_recovers_after_consecutive_successes(self) -> None:
        config = AccountWorkerConfig(
            refresh_total_deadline_seconds=0.2,
            circuit_breaker_consecutive_timeouts=1,
            circuit_recovery_consecutive_successes=2,
            circuit_retry_cooldown_seconds=0.25,
        )
        plan = [
            {
                "refresh": [
                    {"kind": "snapshot", "snapshot": trusted_snapshot("2026-07-21T01:03:00Z", "healthy-4")},
                    {"kind": "hang"},
                ]
            },
            {
                "refresh": [
                    {"kind": "snapshot", "snapshot": trusted_snapshot("2026-07-21T01:03:30Z", "recover-1")},
                    {"kind": "snapshot", "snapshot": trusted_snapshot("2026-07-21T01:04:00Z", "recover-2")},
                ]
            },
        ]
        worker, temp_dir, _state_dir = self.make_worker(plan, config=config)
        try:
            worker.refresh()
            opened = worker.refresh()
            skipped = worker.refresh()
            time.sleep(0.30)
            probe = worker.refresh()
            recovered = worker.refresh()
        finally:
            worker.stop()

        self.assertTrue(opened["worker_circuit_open"])
        self.assertEqual(skipped["worker_refresh_status"], "circuit_open_skip")
        self.assertEqual(probe["worker_refresh_status"], "healthy_circuit_probe")
        self.assertTrue(probe["worker_circuit_open"])
        self.assertEqual(probe["worker_consecutive_successes"], 1)
        self.assertEqual(recovered["worker_refresh_status"], "healthy_circuit_recovered")
        self.assertFalse(recovered["worker_circuit_open"])
        self.assertEqual(recovered["worker_consecutive_successes"], 2)
        self.assertEqual(recovered["generated_at"], "2026-07-21T01:04:00Z")

    def test_request_snapshot_returns_latest_published_state(self) -> None:
        config = AccountWorkerConfig(refresh_total_deadline_seconds=0.2)
        plan = [
            {"refresh": [{"kind": "snapshot", "snapshot": trusted_snapshot("2026-07-21T01:05:00Z", "healthy-5")}]}
        ]
        worker, temp_dir, _state_dir = self.make_worker(plan, config=config)
        try:
            worker.start()
            refreshed = worker.refresh()
            latest = worker.request_snapshot()
        finally:
            worker.stop()

        self.assertEqual(latest["generated_at"], refreshed["generated_at"])
        self.assertEqual(latest["marker"], "healthy-5")
        self.assertTrue(latest["worker_running"])


if __name__ == "__main__":
    unittest.main()
