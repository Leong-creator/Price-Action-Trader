from __future__ import annotations

import asyncio
import contextlib
import io
import json
import queue
import os
import multiprocessing as mp
from multiprocessing.reduction import DupFd
import time
from datetime import timedelta
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from scripts.m15_marketdata_diagnostics_lib import (
    PipelineDiagnostics, acquire_quote_owner_lock, assert_no_legacy_quote_processes,
)
from scripts import run_m15_longbridge_quote_diagnostic as diagnostic
from scripts import run_m15_longbridge_sdk_runtime as runtime


def blocking_sdk_factory_probe(config_path, symbols, duration, output_dir):
    class Quote:
        @classmethod
        def create(cls, config):
            time.sleep(60)  # Simulates a native synchronous factory blocking its event loop.
    sdk = SimpleNamespace(AsyncQuoteContext=Quote,
        OAuthBuilder=lambda _: SimpleNamespace(build=lambda _: object()))
    config = SimpleNamespace(quote_region="cn")
    with patch.object(diagnostic, "read_client_id", return_value="test"), \
         patch.object(diagnostic, "sdk_config_from_oauth", return_value=object()):
        asyncio.run(diagnostic.collect(config, symbols, duration, Path(output_dir), sdk, asyncio.Event()))


def hold_shared_lock(stop, ready):
    ready.set()
    stop.wait(15)


def parent_with_blocked_probe(output_dir, lock_path):
    with acquire_quote_owner_lock(Path(lock_path)) as owner:
        asyncio.run(diagnostic.supervise_raw("unused", ["SPY.US"], 60,
            Path(output_dir), asyncio.Event(), worker_target=blocking_sdk_factory_probe,
            owner_fd=owner.fileno()))


class MarketdataDiagnosticsTest(unittest.TestCase):
    def test_raw_callback_can_progress_without_normalization_or_dequeue(self):
        stats = PipelineDiagnostics(sample_limit=2)
        for _ in range(3):
            stats.record("raw_callback", "SPY.US", "quote")
        snapshot = stats.snapshot(drain_samples=True)
        self.assertEqual(snapshot["stages"]["raw_callback:SPY.US:quote"]["count"], 3)
        self.assertNotIn("dequeued:SPY.US:quote", snapshot["stages"])
        self.assertEqual(snapshot["native_reader_state"], "unknown")
        self.assertEqual(snapshot["sdk_internal_reconnect_state"], "unknown")
        self.assertEqual(len(snapshot["samples"]), 2)
        self.assertEqual(snapshot["sample_overwritten_count"], 1)
        self.assertEqual(stats.snapshot()["samples"], [])
        self.assertGreaterEqual(stats.snapshot()["observed_monotonic"], snapshot["observed_monotonic"])

    def test_lock_is_exclusive_but_file_remaining_is_not_a_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owner.lock"
            with acquire_quote_owner_lock(path):
                with self.assertRaisesRegex(RuntimeError, "another_quote_owner"):
                    acquire_quote_owner_lock(path)
            with acquire_quote_owner_lock(path):
                pass

    def test_output_cannot_overwrite_production_or_prior_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaises(ValueError):
                diagnostic.validate_output_dir(output / "child", output)
            (output / "existing").write_text("evidence")
            with self.assertRaises(ValueError):
                diagnostic.validate_output_dir(output, output / "production")

    def test_legacy_quote_owner_blocks_without_killing(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            runtime_process = proc / "99999999"
            runtime_process.mkdir()
            (runtime_process / "cmdline").write_bytes(b"python\0/old/run_m15_longbridge_sdk_runtime.py\0--watch\0")
            with patch("os.kill") as kill:
                with self.assertRaisesRegex(RuntimeError, "99999999"):
                    assert_no_legacy_quote_processes(proc)
                kill.assert_not_called()
            (runtime_process / "cmdline").write_bytes(b"python\0/old/run_m15_longbridge_sdk_runtime.py\0--status\0")
            assert_no_legacy_quote_processes(proc)

    def test_orphaned_spawn_worker_blocks_without_killing(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            child = proc / "99999998"
            (child / "fd").mkdir(parents=True)
            (child / "cmdline").write_bytes(b"python\0-c\0from multiprocessing.spawn import spawn_main\0")
            (child / "fd/1").symlink_to("/old/m15_longbridge_sdk_runtime.log")
            with patch("os.kill") as kill:
                with self.assertRaisesRegex(RuntimeError, "99999998"):
                    assert_no_legacy_quote_processes(proc)
                kill.assert_not_called()

    def test_probe_has_one_context_and_no_account_or_bar_acceptance(self):
        calls = []
        class Quote:
            @classmethod
            def create(cls, config):
                calls.append("create")
                return cls()
            def set_on_quote(self, handler):
                self.callback = handler
            def set_on_trades(self, handler):
                pass
            async def subscribe(self, symbols, types):
                calls.append("subscribe")
                self.callback("SPY.US", {"last_done": "500"})
            async def subscriptions(self):
                return [{"symbol": "SPY.US", "sub_types": ["quote", "trade"]}]
        sdk = SimpleNamespace(AsyncQuoteContext=Quote,
            OAuthBuilder=lambda _: SimpleNamespace(build=lambda _: object()),
            SubType=SimpleNamespace(Quote="quote", Trade="trade"))
        config = SimpleNamespace(quote_region="cn", sdk_subscribe_batch_size=50)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(diagnostic, "read_client_id", return_value="not-a-secret"), \
             patch.object(diagnostic, "sdk_config_from_oauth", return_value=object()):
            result = asyncio.run(diagnostic.collect(config, ["SPY.US"], 0.02,
                Path(directory), sdk, asyncio.Event()))
            self.assertEqual(calls, ["create", "subscribe"])
            self.assertFalse(result["production_acceptance"])
            self.assertEqual(result["status"], "duration_completed")
            self.assertEqual(result["diagnostics"]["stages"]["dequeued:SPY.US:quote"]["count"], 1)
            self.assertFalse(result["account_access"])
            self.assertTrue((Path(directory) / "summary.json").exists())

    def test_child_keeps_same_lock_when_parent_descriptor_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owner.lock"
            owner = acquire_quote_owner_lock(path)
            context = mp.get_context("spawn")
            stop, ready = context.Event(), context.Event()
            child = context.Process(target=diagnostic._supervised_entry,
                args=(hold_shared_lock, (stop, ready), DupFd(owner.fileno()), os.getpid()))
            child.start()
            try:
                self.assertTrue(ready.wait(5))
                owner.close()
                with self.assertRaisesRegex(RuntimeError, "another_quote_owner"):
                    acquire_quote_owner_lock(path)
            finally:
                stop.set()
                child.join(5)
                if child.is_alive():
                    child.kill()
                    child.join(5)
                owner.close()
            with acquire_quote_owner_lock(path):
                pass

    def test_parent_sigkill_kills_blocked_sdk_child_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            lock_path = output / "owner.lock"
            context = mp.get_context("spawn")
            parent = context.Process(target=parent_with_blocked_probe, args=(directory, str(lock_path)))
            parent.start()
            try:
                deadline = time.monotonic() + 8
                phase = {}
                while time.monotonic() < deadline:
                    try:
                        phase = json.loads((output / "phase.json").read_text())
                        if phase.get("stage") == "context_create":
                            break
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.05)
                self.assertEqual(phase.get("stage"), "context_create")
                child_pid = phase["process_id"]
                parent.kill()
                parent.join(5)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        state = Path(f"/proc/{child_pid}/stat").read_text().split(") ", 1)[1].split()[0]
                    except FileNotFoundError:
                        break
                    if state == "Z":
                        break
                    time.sleep(0.05)
                else:
                    self.fail("native child survived parent SIGKILL")
                with acquire_quote_owner_lock(lock_path):
                    pass
            finally:
                if parent.is_alive():
                    parent.kill()
                parent.join(5)

    def test_parent_deadline_stops_blocked_native_factory(self):
        with tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            result = asyncio.run(diagnostic.supervise_raw("unused", ["SPY.US"], 0.05,
                Path(directory), asyncio.Event(), worker_target=blocking_sdk_factory_probe))
            self.assertLess(time.monotonic() - started, 12)
            self.assertEqual(result["reason"], "diagnostic_wall_clock_deadline_exceeded")
            self.assertEqual(result["last_phase"]["stage"], "context_create")
            self.assertTrue(result["worker_process_exited"])
            self.assertTrue(result["worker_forced_cleanup"])
            self.assertFalse(result["production_acceptance"])

    def test_pipeline_uses_existing_boundaries_and_rejects_late_missing_or_duplicate(self):
        from tests.unit.test_m15_session_evidence import at, bars
        config = runtime.load_config()
        symbols = ("SPY.US", "QQQ.US")
        with patch.object(runtime, "configured_trading_symbols", return_value=symbols):
            evidence = diagnostic.PipelineProbeEvidence(config)
            evidence.consume({"kind": "ready", "partial_bar_suppressed_until": at(8, 9, 30).isoformat()}, at(8, 9, 30))
            close = at(8, 9, 35)
            evidence.consume({"kind": "heartbeat", "raw_reference_activity": [{
                "kind": "market_activity", "symbol": "SPY.US", "received_at": close.isoformat(),
                "source_mode": "official_sdk_raw_quote_callback"}]}, close)
            evidence.consume({"kind": "bars", "rows": bars(close, symbols)}, close + timedelta(seconds=1))
            self.assertEqual(evidence.bar_count, 2)
            self.assertEqual(evidence.session.complete_boundary_count, 1)
            with self.assertRaisesRegex(RuntimeError, "duplicate_boundary"):
                evidence.consume({"kind": "bars", "rows": bars(close, symbols)}, close + timedelta(seconds=2))
            with self.assertRaisesRegex(RuntimeError, "boundary_deadline"):
                evidence.check_deadlines(close + timedelta(minutes=5, seconds=6))

    def test_pipeline_spawns_only_quote_worker_and_redirects_all_writes(self):
        from scripts.m15_longbridge_sdk_quote_transport_lib import official_sdk_quote_worker
        config = runtime.load_config()
        messages = queue.Queue()
        messages.cancel_join_thread = lambda: None
        messages.close = lambda: None
        child_stop = __import__("threading").Event()
        child = MagicMock(pid=123, exitcode=0)
        child.is_alive.side_effect = lambda: not child_stop.is_set()
        context = MagicMock()
        context.Queue.return_value = messages
        context.Event.return_value = child_stop
        context.Process.return_value = child
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(diagnostic.mp, "get_context", return_value=context), \
             patch.object(runtime, "SdkAccountProcessCoordinator") as account, \
             patch.object(runtime, "build_sdk_trade_clients") as orders:
            result = asyncio.run(diagnostic.collect_pipeline(config, "config.json", 0.01,
                Path(directory), asyncio.Event()))
            call = context.Process.call_args.kwargs
            self.assertIs(call["target"], diagnostic._supervised_entry)
            self.assertIs(call["args"][0], official_sdk_quote_worker)
            self.assertEqual(call["args"][1][-1], directory)
            self.assertFalse(result["production_acceptance"])
            account.assert_not_called()
            orders.assert_not_called()
            self.assertTrue(result["worker_process_exited"])

    def test_status_preserves_original_fault_after_process_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            status = output / "status.json"
            status.write_text(json.dumps({"status": "fault_halted", "reason": "reference_market_data_stalled",
                "fault_details": {"raw": 9}, "market_data_fault_halted": True}))
            config = SimpleNamespace(runtime_status_path=status, output_dir=output)
            args = SimpleNamespace(status=True, config="unused")
            buffer = io.StringIO()
            with patch.object(runtime, "parse_args", return_value=args), \
                 patch.object(runtime, "load_config", return_value=config), \
                 patch.object(runtime, "config_fingerprint", return_value="fingerprint"), \
                 contextlib.redirect_stdout(buffer):
                self.assertEqual(runtime.main(), 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["status"], "fault_halted")
            self.assertEqual(payload["reason"], "reference_market_data_stalled")
            self.assertEqual(payload["fault_details"], {"raw": 9})
            self.assertFalse(payload["runtime_process_alive"])
            self.assertEqual(json.loads(status.read_text())["reason"], "reference_market_data_stalled")
