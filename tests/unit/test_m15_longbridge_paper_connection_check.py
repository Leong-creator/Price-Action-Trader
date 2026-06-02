from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m15_longbridge_paper_connection_check_lib import (
    CommandResult,
    load_config,
    run_m15_longbridge_paper_connection_check,
)


class M15LongbridgePaperConnectionCheckTest(unittest.TestCase):
    def test_valid_token_without_paper_marker_blocks_before_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(
                load_config(),
                output_dir=Path(tmp),
                cli_name="python3",
                require_paper_account_marker=True,
                user_confirmed_paper_account=False,
                paper_account_assertion_source="",
            )
            payload = run_m15_longbridge_paper_connection_check(
                config,
                generated_at="2026-06-02T00:00:00Z",
                command_runner=self._runner(
                    check={"session": {"token": "valid"}, "connectivity": {"cn": {"ok": True, "ms": 12}}, "region": {"active": "CN"}},
                    auth={"token": {"status": "valid", "path": "/redacted"}, "account": {"account_type": None, "account_channel": None, "member_id": 1}},
                ),
            )

        self.assertEqual(payload["connection_check_status"], "blocked_paper_account_not_verified")
        self.assertFalse(payload["paper_account_assertion_accepted"])
        self.assertFalse(payload["paper_account_verified"])
        self.assertFalse(payload["asset_read_attempted"])
        self.assertFalse(payload["position_read_attempted"])
        self.assertFalse(payload["order_submitted"])
        self.assertFalse(payload["real_money_actions"])
        self.assertIn("member_id_present", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn('"member_id": 1', json.dumps(payload, ensure_ascii=False))

    def test_paper_marker_connects_but_still_does_not_read_assets_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(
                load_config(),
                output_dir=Path(tmp),
                cli_name="python3",
                require_paper_account_marker=True,
                user_confirmed_paper_account=False,
                paper_account_assertion_source="",
            )
            payload = run_m15_longbridge_paper_connection_check(
                config,
                generated_at="2026-06-02T00:00:00Z",
                command_runner=self._runner(
                    check={"session": {"token": "valid"}, "connectivity": {"global": {"ok": True, "ms": 111}}, "region": {"active": "HK"}},
                    auth={"token": {"status": "valid", "path": "/redacted"}, "account": {"account_type": "paper", "account_channel": "paper"}},
                ),
            )

        self.assertEqual(payload["connection_check_status"], "connected_verified_paper_account")
        self.assertTrue(payload["paper_account_verified"])
        self.assertFalse(payload["asset_read_allowed_now"])
        self.assertFalse(payload["asset_read_attempted"])
        self.assertFalse(payload["order_submitted"])

    def test_oauth_user_confirmed_paper_account_connects_without_marker_but_stays_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(
                load_config(),
                output_dir=Path(tmp),
                cli_name="python3",
                require_paper_account_marker=False,
                user_confirmed_paper_account=True,
                paper_account_assertion_source="user_confirmed_oauth_authorization",
            )
            payload = run_m15_longbridge_paper_connection_check(
                config,
                generated_at="2026-06-02T00:00:00Z",
                command_runner=self._runner(
                    check={"session": {"token": "valid"}, "connectivity": {"cn": {"ok": True, "ms": 12}}, "region": {"active": "CN"}},
                    auth={"token": {"status": "valid", "path": "/redacted"}, "account": {"account_type": None, "account_channel": None, "member_id": 1}},
                ),
            )

        self.assertEqual(payload["connection_check_status"], "connected_oauth_user_confirmed_paper_account")
        self.assertFalse(payload["paper_account_marker_verified"])
        self.assertTrue(payload["paper_account_assertion_accepted"])
        self.assertTrue(payload["paper_account_verified"])
        self.assertFalse(payload["asset_read_attempted"])
        self.assertFalse(payload["position_read_attempted"])
        self.assertFalse(payload["order_submitted"])

    def test_live_token_policy_blocks_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(load_config(), output_dir=Path(tmp), cli_name="python3", live_token_allowed=True)
            payload = run_m15_longbridge_paper_connection_check(
                config,
                generated_at="2026-06-02T00:00:00Z",
                command_runner=self._runner(check={}, auth={}),
            )

        self.assertEqual(payload["connection_check_status"], "blocked_connection_policy")
        self.assertIn("live_token_forbidden", payload["policy_blockers"])
        self.assertFalse(payload["order_submitted"])

    @staticmethod
    def _runner(*, check: dict, auth: dict):
        def run(args: list[str]) -> CommandResult:
            if args[1:3] == ["check", "--format"]:
                return CommandResult(0, json.dumps(check), "")
            if args[1:4] == ["auth", "status", "--format"]:
                return CommandResult(0, json.dumps(auth), "")
            return CommandResult(1, "", "unexpected")

        return run


if __name__ == "__main__":
    unittest.main()
