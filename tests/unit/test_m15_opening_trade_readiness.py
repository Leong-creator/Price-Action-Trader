from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.m15_longbridge_sdk_runtime_lib import (
    config_fingerprint,
    configured_trading_symbols,
    load_config as load_sdk_config,
    trading_universe_fingerprint,
)
from scripts.m15_opening_trade_readiness_lib import (
    DEFAULT_CONFIG_PATH,
    load_config,
    plain_result,
    resolve_readiness_status,
    sdk_runtime_health_issues,
)


class M15OpeningTradeReadinessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sdk_config = load_sdk_config(
            "config/m15_longbridge_marketdata.production.json"
        )

    def healthy_status(self, generated_at: str = "2026-08-28T14:00:00Z") -> dict:
        expected_count = len(configured_trading_symbols(self.sdk_config))
        return {
            "status": "running",
            "generated_at": generated_at,
            "runtime_started_at": "2026-08-28T13:00:00Z",
            "sdk_connected": True,
            "deployment_manifest_verified": True,
            "deployment_worktree_clean": True,
            "market_data_transport": "official_sdk_persistent_websocket",
            "market_data_mode": "official_sdk_subscription",
            "account_order_transport": "official_sdk_persistent_context",
            "quote_worker_generation": 1,
            "runtime_engine": "sdk",
            "config_fingerprint": config_fingerprint(self.sdk_config),
            "trading_universe_fingerprint": trading_universe_fingerprint(
                self.sdk_config
            ),
            "trading_subscription_coverage": f"{expected_count}/{expected_count}",
            "trading_daily_context_ready": True,
            "account_snapshot_healthy": True,
            "account_snapshot_circuit_open": False,
            "account_snapshot_worker_status": "healthy",
        }

    def test_default_config_is_the_only_production_readiness_config(self) -> None:
        config = load_config()
        self.assertEqual(
            DEFAULT_CONFIG_PATH.name, "m15_opening_trade_readiness.production.json"
        )
        self.assertEqual(config.realtime_runtime_engine, "sdk")
        self.assertEqual(
            config.sdk_runtime_config_path.name,
            "m15_longbridge_marketdata.production.json",
        )

    def test_explicit_missing_config_does_not_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "config not found"):
                load_config(Path(directory) / "missing.json")

    def test_healthy_single_connection_runtime_has_no_health_issues(self) -> None:
        issues = sdk_runtime_health_issues(
            self.healthy_status(),
            self.sdk_config,
            True,
            generated_at="2026-08-28T14:00:00Z",
        )
        self.assertEqual(issues, [])

    def test_fault_halted_runtime_is_blocked_without_recovery_assumption(self) -> None:
        status = self.healthy_status()
        status.update(
            {
                "status": "fault_halted",
                "sdk_connected": False,
                "account_snapshot_healthy": False,
            }
        )
        issues = sdk_runtime_health_issues(
            status,
            self.sdk_config,
            False,
            generated_at="2026-08-28T14:00:00Z",
        )
        self.assertIn("process_not_alive", issues)
        self.assertIn("runtime_status=fault_halted", issues)
        self.assertIn("sdk_not_connected", issues)
        self.assertIn("sdk_account_snapshot_stale", issues)

    def test_stale_status_and_configuration_drift_are_explicit_failures(self) -> None:
        status = self.healthy_status("2026-08-28T13:58:00Z")
        status["market_data_transport"] = "removed_transport"
        status["config_fingerprint"] = "stale"
        issues = sdk_runtime_health_issues(
            status,
            self.sdk_config,
            True,
            generated_at="2026-08-28T14:00:00Z",
        )
        self.assertIn("sdk_runtime_status_stale", issues)
        self.assertIn("market_data_transport_config_drift", issues)
        self.assertIn("sdk_config_fingerprint_drift", issues)

    def test_second_market_data_connection_generation_is_rejected(self) -> None:
        status = self.healthy_status()
        status["quote_worker_generation"] = 2
        issues = sdk_runtime_health_issues(
            status,
            self.sdk_config,
            True,
            generated_at="2026-08-28T14:00:00Z",
        )
        self.assertIn("official_market_data_connection_generation_not_one", issues)

    def test_live_push_gate_rejects_initial_snapshot_only(self) -> None:
        status = self.healthy_status()
        status["reference_market_activity"] = {
            "SPY.US": {
                "source": "official_sdk_initial_snapshot",
                "at": "2026-08-28T13:59:59Z",
            }
        }
        issues = sdk_runtime_health_issues(
            status,
            self.sdk_config,
            True,
            generated_at="2026-08-28T14:00:00Z",
            require_live_push=True,
        )
        self.assertIn("sdk_reference_market_push_stale", issues)

    def test_readiness_status_never_claims_orders_during_acceptance_wait(self) -> None:
        status = resolve_readiness_status(
            fail_count=0,
            pending_formal_flatten=False,
            market_phase="regular_session",
            new_position_submission_enabled=False,
            readonly_gate_waiting=True,
        )
        result = plain_result(
            status,
            0,
            1,
            {"market_status": "美股常规交易时段"},
        )
        self.assertEqual(status, "waiting_for_marketdata_acceptance")
        self.assertIn("新开仓仍被禁止", result)
        self.assertNotIn("订单提交已启用", result)


if __name__ == "__main__":
    unittest.main()
