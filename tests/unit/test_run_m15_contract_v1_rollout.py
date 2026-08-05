from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from scripts.run_m15_contract_v1_rollout import (
    activate_validation_session,
    prepare_rollout,
    rollout_check,
)


class ContractV1RolloutTest(unittest.TestCase):
    def test_check_rejects_unverified_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, account_path = self.fixture(root)
            self.write(account_path, {"account_channel": "lb_papertrading", "paper_account_verified": False})
            with patch("scripts.run_m15_contract_v1_rollout.ROOT", root):
                result = rollout_check(config_path, now=datetime(2026, 8, 5, tzinfo=UTC))
            self.assertFalse(result["ready_to_prepare"])
            self.assertIn("paper_account_snapshot_not_verified_or_stale", result["blockers"])

    def test_prepare_writes_pending_marker_without_activating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, account_path = self.fixture(root)
            self.write(account_path, {
                "generated_at": "2026-08-05T00:00:00Z",
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions_ok": True,
                "orders_ok": True,
                "positions": [{"symbol": "AAPL.US"}],
                "open_orders": [],
            })
            with patch("scripts.run_m15_contract_v1_rollout.ROOT", root):
                result = prepare_rollout(config_path, now=datetime(2026, 8, 5, tzinfo=UTC))
            self.assertEqual(result["status"], "prepared_pending_flatten")
            marker = json.loads((root / "marker.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "pending_flatten")
            self.assertTrue(marker["blocks_new_entries"])
            self.assertEqual(marker["test_started_at"], "")

    def test_validation_session_requires_flat_account_and_records_automatic_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, account_path = self.fixture(root)
            self.write(account_path, {
                "generated_at": "2026-08-05T14:00:00Z",
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions_ok": True,
                "orders_ok": True,
                "positions": [],
                "open_orders": [],
            })
            with patch("scripts.run_m15_contract_v1_rollout.ROOT", root):
                result = activate_validation_session(
                    config_path,
                    validation_end_at="2026-08-05T19:45:00Z",
                    now=datetime(2026, 8, 5, 14, 0, tzinfo=UTC),
                )

            self.assertEqual(result["status"], "validation_active")
            marker = json.loads((root / "marker.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "active")
            self.assertTrue(marker["validation_session"])
            self.assertEqual(marker["validation_end_at"], "2026-08-05T19:45:00Z")
            self.assertFalse(marker["blocks_new_entries"])

    def fixture(self, root: Path) -> tuple[Path, Path]:
        contracts = root / "contracts"
        contracts.mkdir()
        self.write(contracts / "R1.json", {
            "schema_version": "m15-strategy-contract-v1",
            "runtime_id": "R1",
            "strategy_id": "S1",
            "display_name_zh": "测试",
            "stage": "paper-v1",
            "direction": "long",
            "timeframe": "5m",
            "setup": {"rule": "test"},
            "entry_rules": {"entry": "test"},
            "exit_rules": {"exit": "test"},
            "risk_controls": {"risk": "test"},
            "data_requirements": {"source": "sdk"},
            "visual_acceptance": {"required": False, "status": "not-required"},
            "execution_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_signal_source": False,
            },
            "source_refs": ["test"],
        })
        self.write(root / "execution.json", {
            "strategy_contracts": {"directory": str(contracts)},
            "longbridge_realtime": {"allowed_runtime_ids": ["R1"]},
            "virtual_capital_buckets": {"r1": {"runtime_ids": ["R1"]}},
            "test_epoch": {"test_epoch_id": "long-epoch"},
            "paper_short_testing": {"test_epoch_id": "short-epoch"},
        })
        self.write(root / "router.json", {"paper_short_testing": {"test_epoch_id": "short-epoch"}})
        account_path = root / "account.json"
        self.write(root / "account-config.json", {"outputs": {"account_state": str(account_path)}})
        self.write(root / "position.json", {"stage": "placeholder"})
        self.write(root / "cleanup.json", {"stage": "placeholder"})
        self.write(root / "universe.json", {"symbols": ["AAPL"]})
        config = {
            "outputs": {"output_dir": str(root), "market_events": str(root / "events.jsonl"), "runtime_status": str(root / "status.json")},
            "oauth": {"client_id_file": str(root / "client-id"), "quote_region": "global", "trade_region": "global"},
            "market_data": {"market": "US", "use_seed_universe": False, "universe_path": str(root / "universe.json"), "symbol_limit": 1, "trading_symbol_limit": 1, "bar_minutes": 5, "daily_context_bars": 60},
            "runtime": {"heartbeat_interval_seconds": 5, "reconnect_backoff_seconds": 5, "subscription_batch_size": 1, "subscription_deadline_seconds": 20, "maximum_consecutive_subscription_failures": 3, "snapshot_poll_interval_seconds": 1, "subscription_failures_before_snapshot_fallback": 1, "snapshot_poll_dispatch_max_elapsed_ms": 1000, "snapshot_poll_min_successful_cycles": 1, "market_data_heartbeat_deadline_seconds": 5, "account_snapshot_interval_seconds": 15, "account_snapshot_refresh_deadline_seconds": 8, "account_snapshot_circuit_retry_seconds": 15, "maximum_account_snapshot_age_seconds": 45, "paper_trading_only": True, "live_execution": False, "real_money_actions": False},
            "routing": {"router_config": str(root / "router.json"), "execution_config": str(root / "execution.json"), "account_state_config": str(root / "account-config.json"), "position_manager_config": str(root / "position.json"), "stale_order_cleanup_config": str(root / "cleanup.json"), "paper_order_dispatch_enabled": True},
            "formal_test_transition": {"enabled": True, "test_epoch_id": "long-epoch", "short_test_epoch_id": "short-epoch", "marker_path": str(root / "marker.json"), "epoch_state_path": str(root / "epoch.json")},
        }
        config_path = root / "runtime.json"
        self.write(config_path, config)
        return config_path, account_path

    @staticmethod
    def write(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
