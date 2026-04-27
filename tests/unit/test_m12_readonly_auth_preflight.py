from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import m12_readonly_auth_preflight_lib as MODULE


class M12ReadonlyAuthPreflightTests(unittest.TestCase):
    def test_preflight_writes_readonly_boundary_and_uses_only_allowed_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/longbridge"),
                mock.patch.object(MODULE.subprocess, "run", side_effect=_probe_responses()) as run_mock,
            ):
                artifact = MODULE.run_m12_readonly_auth_preflight(
                    Path(tmpdir),
                    probe_symbol="SPY.US",
                    generated_at="2026-04-27T00:00:00Z",
                )

            self.assertEqual(artifact["auth_status"], "valid_readonly_market_data")
            self.assertEqual(artifact["next_action"], "ready_for_m12_1_readonly_feed")
            boundary = artifact["runtime_boundary"]
            self.assertTrue(boundary["paper_simulated_only"])
            self.assertFalse(boundary["paper_trading_approval"])
            self.assertFalse(boundary["broker_connection"])
            self.assertFalse(boundary["real_orders"])
            self.assertFalse(boundary["live_execution"])
            called_commands = [call.args[0] for call in run_mock.call_args_list]
            for command in called_commands:
                self.assertIn(command[1], MODULE.READONLY_COMMAND_ALLOWLIST)
                self.assertNotIn(command[1], MODULE.FORBIDDEN_COMMANDS)

            runtime_path = Path(tmpdir) / "m12_0_runtime_boundary.json"
            report_path = Path(tmpdir) / "m12_0_longbridge_readonly_auth_check.md"
            self.assertTrue(runtime_path.exists())
            self.assertTrue(report_path.exists())
            persisted = json.loads(runtime_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["auth_status"], "valid_readonly_market_data")

    def test_missing_cli_is_deferred_without_market_data_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                mock.patch.object(MODULE.shutil, "which", return_value=None),
                mock.patch.object(MODULE.subprocess, "run") as run_mock,
            ):
                artifact = MODULE.run_m12_readonly_auth_preflight(
                    Path(tmpdir),
                    generated_at="2026-04-27T00:00:00Z",
                )
        self.assertEqual(artifact["auth_status"], "missing_cli")
        self.assertEqual(artifact["probes"][0]["status"], "missing_cli")
        run_mock.assert_not_called()

    def test_forbidden_command_is_rejected_before_subprocess(self) -> None:
        with self.assertRaisesRegex(ValueError, "not allowed"):
            MODULE._assert_readonly_command(["order", "list", "--format", "json"])
        with self.assertRaisesRegex(ValueError, "forbidden"):
            MODULE._assert_readonly_command(["quote", "order", "--format", "json"])

    def test_artifact_validation_blocks_enabled_live_flags(self) -> None:
        artifact = {
            "runtime_boundary": MODULE.build_runtime_boundary() | {"real_orders": True},
            "probes": [],
        }
        with self.assertRaisesRegex(ValueError, "real_orders"):
            MODULE.validate_preflight_artifact(artifact)

    def test_report_does_not_claim_trading_approval(self) -> None:
        artifact = {
            "auth_status": "valid_readonly_market_data",
            "next_action": "ready_for_m12_1_readonly_feed",
            "runtime_boundary": MODULE.build_runtime_boundary(),
            "probes": [],
        }
        report = MODULE.build_report(artifact)
        lowered = report.lower()
        self.assertIn("broker_connection: `false`", lowered)
        self.assertIn("real_orders: `false`", lowered)
        self.assertNotIn("real_orders=true", lowered)
        self.assertNotIn("broker_connection=true", lowered)
        self.assertNotIn("live-ready", lowered)

    def test_cli_text_sanitizer_removes_ansi_sequences(self) -> None:
        self.assertEqual(MODULE.clean_cli_text("run `\x1b[32mlongbridge update\x1b[0m`"), "run `longbridge update`")


def _probe_responses() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "connectivity": {"cn": {"ok": True}, "global": {"ok": True}},
                    "region": {"active": "CN"},
                    "session": {"token": "valid"},
                }
            ),
            stderr="",
        ),
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"symbol": "SPY.US", "last_done": "500.00"}]),
            stderr="",
        ),
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"time": "2026-04-21 00:00:00", "open": "500.00", "close": "501.00"}]),
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout=json.dumps([]), stderr=""),
    ]


if __name__ == "__main__":
    unittest.main()
