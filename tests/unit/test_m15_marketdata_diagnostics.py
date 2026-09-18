from __future__ import annotations

import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.m15_marketdata_diagnostics_lib import (
    PipelineDiagnostics, acquire_quote_owner_lock, assert_no_legacy_quote_processes,
)
from scripts import run_m15_longbridge_quote_diagnostic as diagnostic
from scripts import run_m15_longbridge_sdk_runtime as runtime


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
