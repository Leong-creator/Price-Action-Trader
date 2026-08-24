from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.m15_monday_refresh_acceptance_lib import (
    MondayRefreshAcceptanceConfig,
    run_m15_monday_refresh_acceptance,
)


class M15MondayRefreshAcceptanceTest(unittest.TestCase):
    def test_sdk_chain_is_armed_while_waiting_for_regular_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=False)

            payload = run_m15_monday_refresh_acceptance(config, generated_at="2026-07-18T09:00:00Z")

            self.assertEqual(payload["acceptance_status"], "armed_waiting_regular_session")
            self.assertEqual(payload["fail_count"], 0)
            self.assertEqual(payload["waiting_count"], 1)
            self.assertEqual(payload["runtime_whitelist_count"], 18)
            self.assertTrue(payload["paper_account_verified"])
            self.assertTrue(payload["local_simulation_isolated"])

    def test_sdk_chain_is_ready_during_regular_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=True)

            payload = run_m15_monday_refresh_acceptance(config, generated_at="2026-07-20T13:31:00Z")

            self.assertEqual(payload["acceptance_status"], "ready_regular_session")
            self.assertEqual(payload["fail_count"], 0)
            self.assertEqual(payload["waiting_count"], 0)

    def test_sdk_chain_accepts_canonical_paper_order_ready_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=True)
            readiness = json.loads(config.opening_readiness_path.read_text(encoding="utf-8"))
            readiness["readiness_status"] = "ready_for_longbridge_paper_orders"
            config.opening_readiness_path.write_text(json.dumps(readiness), encoding="utf-8")

            payload = run_m15_monday_refresh_acceptance(config, generated_at="2026-07-20T13:31:00Z")

            self.assertEqual(payload["acceptance_status"], "ready_regular_session")
            self.assertEqual(payload["fail_count"], 0)

    def test_canonical_ready_status_cannot_hide_disabled_new_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=True)
            readiness = json.loads(config.opening_readiness_path.read_text(encoding="utf-8"))
            readiness.update(
                {
                    "readiness_status": "waiting_for_marketdata_acceptance",
                    "new_position_submission_enabled": False,
                }
            )
            config.opening_readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
            runtime = json.loads(config.sdk_runtime_status_path.read_text(encoding="utf-8"))
            runtime.update(
                {
                    "dispatch_enabled": False,
                    "dispatch_block_reason": "two_day_readonly_gate",
                    "readonly_sessions_passed": 0,
                    "readonly_sessions_required": 1,
                }
            )
            config.sdk_runtime_status_path.write_text(json.dumps(runtime), encoding="utf-8")

            payload = run_m15_monday_refresh_acceptance(
                config,
                generated_at="2026-08-24T14:00:00Z",
            )

            self.assertEqual(payload["acceptance_status"], "armed_waiting_marketdata_acceptance")
            self.assertFalse(payload["new_position_submission_enabled"])
            self.assertEqual(payload["fail_count"], 0)

    def test_inconsistent_ready_status_is_blocked_when_new_positions_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=True)
            readiness = json.loads(config.opening_readiness_path.read_text(encoding="utf-8"))
            readiness.update(
                {
                    "readiness_status": "ready_for_longbridge_paper_orders",
                    "new_position_submission_enabled": False,
                }
            )
            config.opening_readiness_path.write_text(json.dumps(readiness), encoding="utf-8")

            payload = run_m15_monday_refresh_acceptance(
                config,
                generated_at="2026-08-24T14:00:00Z",
            )

            self.assertEqual(payload["acceptance_status"], "blocked_monday_acceptance")
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["opening_readiness"]["status"], "fail")

    def test_pending_flatten_is_safe_waiting_not_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=False)
            runtime = json.loads(config.sdk_runtime_status_path.read_text(encoding="utf-8"))
            runtime["dispatch_enabled"] = False
            config.sdk_runtime_status_path.write_text(json.dumps(runtime), encoding="utf-8")
            readiness = json.loads(config.opening_readiness_path.read_text(encoding="utf-8"))
            readiness["readiness_status"] = "armed_waiting_flatten_session"
            config.opening_readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
            formal = json.loads(config.formal_epoch_path.read_text(encoding="utf-8"))
            formal.update({"status": "pending_flatten", "blocks_new_entries": True})
            config.formal_epoch_path.write_text(json.dumps(formal), encoding="utf-8")

            payload = run_m15_monday_refresh_acceptance(config, generated_at="2026-08-05T10:00:00Z")

            self.assertEqual(payload["acceptance_status"], "armed_waiting_flatten_session")
            self.assertEqual(payload["fail_count"], 0)
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["paper_dispatch_armed"]["status"], "waiting_for_flatten")
            self.assertEqual(checks["formal_epoch_active"]["status"], "waiting_for_flatten")

    def test_marketdata_readonly_gate_is_safe_waiting_not_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=False)
            runtime = json.loads(config.sdk_runtime_status_path.read_text(encoding="utf-8"))
            runtime.update(
                {
                    "dispatch_enabled": False,
                    "dispatch_block_reason": "two_day_readonly_gate",
                    "readonly_sessions_passed": 0,
                    "readonly_sessions_required": 1,
                }
            )
            config.sdk_runtime_status_path.write_text(json.dumps(runtime), encoding="utf-8")

            payload = run_m15_monday_refresh_acceptance(
                config,
                generated_at="2026-08-22T03:41:39Z",
            )

            self.assertEqual(
                payload["acceptance_status"],
                "armed_waiting_marketdata_acceptance",
            )
            self.assertEqual(payload["fail_count"], 0)
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(
                checks["paper_dispatch_armed"]["status"],
                "waiting_for_marketdata_acceptance",
            )

    def test_watchdog_previous_result_does_not_create_acceptance_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=True)
            config.watchdog_status_path.write_text(
                json.dumps({"watchdog_status": "needs_attention"}),
                encoding="utf-8",
            )

            payload = run_m15_monday_refresh_acceptance(
                config,
                generated_at="2026-07-20T13:31:00Z",
            )

            self.assertEqual(payload["acceptance_status"], "ready_regular_session")
            self.assertNotIn(
                "watchdog_single_healthy",
                {row["check"] for row in payload["checks"]},
            )

    def test_stale_account_snapshot_blocks_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=False, account_snapshot_healthy=False)

            payload = run_m15_monday_refresh_acceptance(config, generated_at="2026-07-18T09:00:00Z")

            self.assertEqual(payload["acceptance_status"], "blocked_monday_acceptance")
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["account_snapshot_fresh"]["status"], "fail")

    def test_zero_second_account_snapshot_is_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=False)
            runtime = json.loads(config.sdk_runtime_status_path.read_text(encoding="utf-8"))
            runtime["account_snapshot_age_seconds"] = 0
            config.sdk_runtime_status_path.write_text(json.dumps(runtime), encoding="utf-8")

            payload = run_m15_monday_refresh_acceptance(config, generated_at="2026-07-22T13:20:00Z")

            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["account_snapshot_fresh"]["status"], "pass")
            self.assertEqual(payload["fail_count"], 0)

    def test_temporarily_unavailable_dashboard_statistics_do_not_block_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=False)
            config.dashboard_path.write_text(
                json.dumps(
                    {
                        "source_of_truth": "longbridge_sdk_paper_account",
                        "data_status": "temporarily_unavailable",
                    }
                ),
                encoding="utf-8",
            )

            payload = run_m15_monday_refresh_acceptance(
                config,
                generated_at="2026-08-22T03:45:00Z",
            )

            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["dashboard_sdk_source"]["status"], "pass")
            self.assertEqual(payload["fail_count"], 0)

    def test_negative_account_snapshot_age_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(Path(tmp), session_should_run=False)
            runtime = json.loads(config.sdk_runtime_status_path.read_text(encoding="utf-8"))
            runtime["account_snapshot_age_seconds"] = -1
            config.sdk_runtime_status_path.write_text(json.dumps(runtime), encoding="utf-8")

            payload = run_m15_monday_refresh_acceptance(config, generated_at="2026-07-22T13:20:00Z")

            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["account_snapshot_fresh"]["status"], "fail")

    def test_unverified_account_blocks_and_clears_broker_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_fixture(
                Path(tmp),
                session_should_run=False,
                paper_account_verified=False,
            )

            payload = run_m15_monday_refresh_acceptance(config, generated_at="2026-07-18T09:00:00Z")

            self.assertEqual(payload["acceptance_status"], "blocked_monday_acceptance")
            self.assertFalse(payload["paper_account_verified"])
            self.assertFalse(payload["broker_connection"])
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["paper_account_verified"]["status"], "fail")

    def make_fixture(
        self,
        root: Path,
        *,
        session_should_run: bool,
        account_snapshot_healthy: bool = True,
        paper_account_verified: bool = True,
    ) -> MondayRefreshAcceptanceConfig:
        runtime = root / "runtime.json"
        readiness = root / "readiness.json"
        watchdog = root / "watchdog.json"
        account = root / "account.json"
        dashboard = root / "dashboard.json"
        formal = root / "formal.json"
        epoch = "m15-sdk-formal-single-strategy-20260716"
        runtime.write_text(
            json.dumps(
                {
                    "runtime_pid": os.getpid(),
                    "runtime_process_alive": True,
                    "status": "running",
                    "runtime_engine": "sdk",
                    "sdk_connected": True,
                    "configured_symbol_count": 147,
                    "subscription_coverage": "147/147",
                    "daily_context_row_count": 8820,
                    "daily_context_state": "complete",
                    "account_snapshot_healthy": account_snapshot_healthy,
                    "account_snapshot_age_seconds": 1 if account_snapshot_healthy else 90,
                    "dispatch_enabled": True,
                    "dispatch_requested": True,
                }
            ),
            encoding="utf-8",
        )
        readiness.write_text(
            json.dumps(
                {
                    "fail_count": 0,
                    "readiness_status": "ready_for_regular_session" if session_should_run else "armed_waiting_regular_session",
                    "paper_order_submission_enabled": True,
                    "new_position_submission_enabled": True,
                    "runtime_whitelist": [f"R{index}" for index in range(18)],
                    "formal_test_transition": {"test_epoch_id": epoch},
                    "market_window": {
                        "session_should_run": session_should_run,
                        "market_status": "regular_session" if session_should_run else "非交易日等待",
                    },
                    "boundaries": {
                        "paper_simulated_only": True,
                        "live_execution": False,
                        "real_money_actions": False,
                        "local_simulation_as_order_source": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        watchdog.write_text(json.dumps({"watchdog_status": "healthy"}), encoding="utf-8")
        account.write_text(
            json.dumps(
                {
                    "paper_account_verified": paper_account_verified,
                    "account_channel": "lb_papertrading" if paper_account_verified else "unverified",
                }
            ),
            encoding="utf-8",
        )
        dashboard.write_text(
            json.dumps({"source_of_truth": "longbridge_sdk_paper_account", "data_status": "trustworthy"}),
            encoding="utf-8",
        )
        formal.write_text(json.dumps({"status": "active", "test_epoch_id": epoch}), encoding="utf-8")
        return MondayRefreshAcceptanceConfig(
            stage="M15.monday_refresh_acceptance",
            sdk_runtime_status_path=runtime,
            opening_readiness_path=readiness,
            watchdog_status_path=watchdog,
            account_state_path=account,
            dashboard_path=dashboard,
            formal_epoch_path=formal,
            output_dir=root / "out",
        )


if __name__ == "__main__":
    unittest.main()
