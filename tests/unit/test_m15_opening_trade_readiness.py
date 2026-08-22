from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts.m15_opening_trade_readiness_lib import (
    DEFAULT_CONFIG_PATH,
    load_config,
    run_m15_opening_trade_readiness,
    sdk_runtime_health_issues,
)
from scripts.m15_longbridge_sdk_runtime_lib import config_fingerprint as sdk_config_fingerprint
from scripts.m15_longbridge_sdk_runtime_lib import configured_symbols as sdk_configured_symbols
from scripts.m15_longbridge_sdk_runtime_lib import configured_trading_symbols as sdk_configured_trading_symbols
from scripts.m15_longbridge_sdk_runtime_lib import load_config as load_sdk_runtime_config
from scripts.m15_longbridge_sdk_runtime_lib import trading_universe_fingerprint
from scripts.m15_longbridge_realtime_session_supervisor_lib import (
    build_window_state,
    config_digest,
    load_config as load_realtime_supervisor_config,
    runtime_identity_payload,
)


class M15OpeningTradeReadinessTest(unittest.TestCase):
    def test_explicit_missing_config_fails_without_falling_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-readiness.json"

            with self.assertRaisesRegex(FileNotFoundError, "config not found"):
                load_config(missing)

    def test_default_readiness_config_targets_active_sdk_paper_runtime(self) -> None:
        config = load_config()

        self.assertEqual(DEFAULT_CONFIG_PATH.name, "m15_opening_trade_readiness.paper_orders_enabled.json")
        self.assertEqual(config.realtime_runtime_engine, "sdk")
        self.assertEqual(
            config.execution_config_path.name,
            "m15_longbridge_realtime_execution.paper_contract_v1.json",
        )

    def test_sdk_run_overwrites_legacy_readiness_with_canonical_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(self.write_fixture(root, paper_enabled=True, live_execution=False))
            canonical_dir = root / "canonical"
            legacy_dir = root / "legacy"
            legacy_dir.mkdir(parents=True, exist_ok=True)
            config = replace(config, realtime_runtime_engine="sdk", output_dir=canonical_dir)

            with (
                patch("scripts.m15_opening_trade_readiness_lib.DEFAULT_OUTPUT_DIR", canonical_dir),
                patch("scripts.m15_opening_trade_readiness_lib.DEFAULT_M15_REALTIME_DIR", legacy_dir),
            ):
                run_m15_opening_trade_readiness(config, generated_at="2026-06-04T12:20:00Z")

            pointer = json.loads((legacy_dir / "m15_opening_trade_readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(pointer["readiness_status"], "superseded_use_canonical_sdk_readiness")
            self.assertFalse(pointer["trading_decision_allowed"])
            self.assertEqual(pointer["canonical_path"], str(canonical_dir / "m15_opening_trade_readiness.json"))

    def test_armed_waiting_regular_session_when_paper_enabled_and_daemons_alive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_fixture(root, paper_enabled=True, live_execution=False)
            config = load_config(config_path)

            payload = run_m15_opening_trade_readiness(config, generated_at="2026-06-04T12:20:00Z")

            self.assertEqual(payload["readiness_status"], "armed_waiting_regular_session")
            self.assertTrue(payload["paper_order_submission_enabled"])
            self.assertTrue(payload["m12_47_daemon_alive"])
            self.assertTrue(payload["m15_realtime_daemon_alive"])
            self.assertTrue(payload["paper_account_verified"])
            self.assertEqual(payload["fail_count"], 0)
            self.assertEqual(payload["waiting_count"], 1)
            self.assertEqual(payload["informational_count"], 1)
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["m12_47_daemon_alive"]["status"], "informational")
            self.assertTrue(checks["m12_47_daemon_alive"]["non_blocking"])
            self.assertIn("process=alive", checks["m15_realtime_daemon_alive"]["actual"])

    def test_pending_flatten_disables_new_positions_without_disabling_exits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_fixture(root, paper_enabled=True, live_execution=False)
            status_path = root / "realtime" / "m15_longbridge_realtime_session_supervisor.json"
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            status_payload["formal_test_transition"] = {
                "status": "pending_flatten",
                "activation_blocker": "validation_flatten_incomplete:connect_timeout",
            }
            status_path.write_text(json.dumps(status_payload), encoding="utf-8")

            payload = run_m15_opening_trade_readiness(
                load_config(config_path),
                generated_at="2026-06-04T12:20:00Z",
            )

            self.assertEqual(payload["readiness_status"], "armed_waiting_flatten_session")
            self.assertTrue(payload["paper_order_submission_enabled"])
            self.assertFalse(payload["new_position_submission_enabled"])
            self.assertEqual(payload["actual_runtime_ids_seen"], [])
            self.assertEqual(payload["recent_execution_inputs"], [])
            self.assertEqual(payload["execution_runtime_identity"], {})
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["formal_test_flatten_transition"]["status"], "waiting")

    def test_active_formal_epoch_blocks_when_execution_start_time_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_fixture(root, paper_enabled=True, live_execution=False)
            status_path = root / "realtime" / "m15_longbridge_realtime_session_supervisor.json"
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            status_payload["formal_test_transition"] = {
                "status": "active",
                "test_epoch_id": "formal-epoch",
                "test_started_at": "2026-06-04T13:30:00Z",
            }
            status_path.write_text(json.dumps(status_payload), encoding="utf-8")
            epoch_state_path = root / "realtime" / "m15_longbridge_virtual_account_epoch.json"
            epoch_state_path.write_text(
                json.dumps(
                    {
                        "status": "activated",
                        "test_epoch_id": "formal-epoch",
                        "test_started_at": "",
                    }
                ),
                encoding="utf-8",
            )

            payload = run_m15_opening_trade_readiness(
                load_config(config_path),
                generated_at="2026-06-04T14:00:00Z",
            )

            self.assertEqual(payload["readiness_status"], "blocked_opening_trade_watch")
            self.assertFalse(payload["new_position_submission_enabled"])
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["formal_test_execution_epoch"]["status"], "fail")

    def test_blocks_when_execution_config_enables_live_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_fixture(root, paper_enabled=True, live_execution=True)
            config = load_config(config_path)

            payload = run_m15_opening_trade_readiness(config, generated_at="2026-06-04T14:00:00Z")

            self.assertEqual(payload["readiness_status"], "blocked_opening_trade_watch")
            self.assertGreater(payload["fail_count"], 0)
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["paper_only_boundaries"]["status"], "fail")

    def test_reports_dead_m15_pid_and_stale_status_age(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_fixture(root, paper_enabled=True, live_execution=False)
            (root / "realtime" / "m15_longbridge_realtime_session_supervisor.pid").write_text("99999999", encoding="utf-8")
            (root / "realtime" / "m15_longbridge_realtime_session_supervisor.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-04T13:00:00Z",
                        "local_simulation_isolated": True,
                        "local_ledger_input_ref": "",
                        "legacy_fast_queue_used": False,
                        "manual_m12_37_once_used": False,
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(config_path)

            payload = run_m15_opening_trade_readiness(config, generated_at="2026-06-04T14:00:00Z")

            self.assertFalse(payload["m15_realtime_daemon_alive"])
            self.assertEqual(payload["m15_realtime_daemon_pid"], 99999999)
            self.assertEqual(payload["m15_realtime_status_age_seconds"], 3600)
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["m15_realtime_daemon_alive"]["status"], "fail")
            self.assertIn("process=dead", checks["m15_realtime_daemon_alive"]["actual"])
            self.assertIn("status_age_seconds=3600", checks["m15_realtime_daemon_alive"]["actual"])

    def test_sdk_readiness_requires_complete_daily_context(self) -> None:
        sdk_config = load_sdk_runtime_config()
        trading_count = len(sdk_configured_trading_symbols(sdk_config))
        expected_rows = trading_count * sdk_config.daily_context_bars
        status = {
            "status": "running",
            "sdk_connected": True,
            "deployment_manifest_verified": True,
            "deployment_worktree_clean": True,
            "market_data_transport": "official_sdk_persistent_websocket",
            "market_data_mode": "sdk_subscription",
            "market_data_circuit_open": False,
            "runtime_engine": "sdk",
            "config_fingerprint": sdk_config_fingerprint(sdk_config),
            "trading_universe_fingerprint": trading_universe_fingerprint(
                sdk_config
            ),
            "subscription_coverage": f"{len(sdk_configured_symbols(sdk_config))}/{len(sdk_configured_symbols(sdk_config))}",
            "trading_subscription_coverage": f"{trading_count}/{trading_count}",
            "daily_context_state": "complete",
            "daily_context_row_count": len(sdk_configured_symbols(sdk_config)) * sdk_config.daily_context_bars,
            "trading_daily_context_ready": True,
            "trading_daily_context_row_count": expected_rows,
            "daily_context_failed_symbols": [],
            "account_snapshot_healthy": True,
        }
        self.assertEqual(sdk_runtime_health_issues(status, sdk_config, True), [])
        status["trading_market_data_coverage"] = f"{trading_count}/{trading_count}"
        status["trading_subscription_coverage"] = f"0/{trading_count}"
        self.assertEqual(sdk_runtime_health_issues(status, sdk_config, True), [])
        status["daily_context_state"] = "loading"
        status["trading_daily_context_ready"] = False
        self.assertIn("sdk_daily_context_incomplete", sdk_runtime_health_issues(status, sdk_config, True))
        status["daily_context_state"] = "complete"
        status["trading_daily_context_ready"] = True
        status["account_snapshot_circuit_open"] = True
        status["account_snapshot_worker_status"] = "timeout_circuit_open"
        issues = sdk_runtime_health_issues(status, sdk_config, True)
        self.assertIn("sdk_account_snapshot_circuit_open", issues)
        self.assertIn("sdk_account_worker_status=timeout_circuit_open", issues)
        status["account_snapshot_circuit_open"] = False
        status["account_snapshot_worker_status"] = "healthy"
        status["trading_universe_fingerprint"] = "drift"
        self.assertIn(
            "sdk_trading_universe_fingerprint_drift",
            sdk_runtime_health_issues(status, sdk_config, True),
        )

    def test_m12_47_status_is_informational_only_when_daemon_is_down(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_fixture(root, paper_enabled=True, live_execution=False)
            m12_status = root / "m12_47_status.json"
            m12_status.write_text(json.dumps({"supervisor_process_alive": False}), encoding="utf-8")

            payload = run_m15_opening_trade_readiness(
                load_config(config_path),
                generated_at="2026-06-04T12:20:00Z",
            )

            self.assertEqual(payload["readiness_status"], "armed_waiting_regular_session")
            self.assertFalse(payload["m12_47_daemon_alive"])
            self.assertEqual(payload["fail_count"], 0)
            self.assertEqual(payload["informational_count"], 1)
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["m12_47_daemon_alive"]["status"], "informational")

    def test_m12_47_stale_alive_flag_does_not_override_a_dead_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_fixture(root, paper_enabled=True, live_execution=False)
            m12_status = root / "m12_47_status.json"
            m12_status.write_text(
                json.dumps({"supervisor_process_alive": True, "supervisor_pid": 99999999}),
                encoding="utf-8",
            )

            payload = run_m15_opening_trade_readiness(
                load_config(config_path),
                generated_at="2026-06-04T12:20:00Z",
            )

            self.assertFalse(payload["m12_47_daemon_alive"])
            self.assertEqual(payload["fail_count"], 0)

    def write_fixture(self, root: Path, *, paper_enabled: bool, live_execution: bool) -> Path:
        output_dir = root / "realtime"
        output_dir.mkdir(parents=True)
        m12_status = root / "m12_47_status.json"
        account_state = output_dir / "m15_longbridge_realtime_account_state.json"
        realtime_status = output_dir / "m15_longbridge_realtime_session_supervisor.json"
        execution_config = root / "execution.json"
        supervisor_config = root / "supervisor.json"
        readiness_config = root / "readiness.json"
        m12_status.write_text(json.dumps({"supervisor_process_alive": True}), encoding="utf-8")
        account_state.write_text(
            json.dumps(
                {
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "live_execution": False,
                    "real_money_actions": False,
                }
            ),
            encoding="utf-8",
        )
        realtime_status.write_text(
            json.dumps(
                {
                    "local_simulation_isolated": True,
                    "local_ledger_input_ref": "",
                    "legacy_fast_queue_used": False,
                    "manual_m12_37_once_used": False,
                }
            ),
            encoding="utf-8",
        )
        execution_payload = {
            "stage": "M15.longbridge_realtime_execution",
            "title": "长桥模拟账户实时执行链路（测试）",
            "inputs": {"realtime_signal_events": str(root / "signals.jsonl"), "paper_account_state": str(account_state)},
            "outputs": {"output_dir": str(output_dir)},
            "longbridge_realtime": {
                "required_account_channel": "lb_papertrading",
                "cli_name": "longbridge",
                "cli_timeout_seconds": 6,
                "time_in_force": "day",
                "outside_rth": "RTH_ONLY",
                "execute_orders": paper_enabled,
                "paper_trading_approval": paper_enabled,
                "session_started_at": "auto",
                "allow_replay": False,
                "watch_interval_seconds": 1,
                "latency_target_ms": 1000,
                "latency_acceptable_ms": 5000,
                "allowed_runtime_ids": ["M10-PA-004-long-1d"],
            },
            "paper_account_model": {
                "equity": "10000",
                "max_total_exposure": "6000",
                "max_symbol_exposure": "1500",
                "max_risk_per_order": "20",
                "min_cash_reserve": "4000",
                "allow_fractional_shares": False,
                "allow_short_selling": False,
                "allow_options": False,
                "allow_margin_financing": False,
                "minimum_net_profit_after_fees": "0",
            },
            "runtime_layering": {
                "longbridge_realtime_candidates": ["M10-PA-004-long-1d"],
                "local_repair_or_shadow_only": ["M10-PA-007-1d"],
                "auxiliary_modules_local_only": ["M10-PA-003"],
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": live_execution,
                "real_money_actions": False,
                "local_simulation_as_order_source": False,
                "manual_m12_37_once": False,
                "fractional_shares": False,
                "short_selling": False,
                "options": False,
                "margin_financing": False,
            },
        }
        execution_config.write_text(json.dumps(execution_payload), encoding="utf-8")
        supervisor_payload = {
            "stage": "M15.longbridge_realtime_session_supervisor",
            "title": "长桥实时链路守护器（测试）",
            "inputs": {
                "ingestor_config": str(root / "ingestor.json"),
                "router_config": str(root / "router.json"),
                "account_state_config": str(root / "account_state.json"),
                "position_manager_config": str(root / "position_manager.json"),
                "execution_config": str(execution_config),
            },
            "outputs": {"output_dir": str(output_dir)},
            "realtime_session_supervisor": {
                "check_interval_seconds": 5,
                "market_timezone": "America/New_York",
                "regular_session_start_time": "09:30",
                "regular_session_end_time": "16:00",
                "active_market_phases": ["regular_session"],
                "market_holidays": [],
                "max_consecutive_failures": 3,
                "run_ingestor": True,
                "run_router": True,
                "run_account_state": True,
                "run_position_manager": True,
                "run_execution": True,
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_signal_source": False,
                "manual_m12_37_once": False,
                "margin_financing": False,
            },
        }
        supervisor_config.write_text(json.dumps(supervisor_payload), encoding="utf-8")
        supervisor_runtime_config = load_realtime_supervisor_config(supervisor_config)
        window = build_window_state(supervisor_runtime_config, generated_at="2026-06-04T12:20:00Z")
        runtime_identity = runtime_identity_payload(supervisor_runtime_config, window)
        realtime_status.write_text(
            json.dumps(
                {
                    "generated_at": "2026-06-04T12:20:00Z",
                    "runtime_identity": runtime_identity,
                    "input_config_digests": {
                        "supervisor_config": supervisor_runtime_config.config_digest,
                        "ingestor_config": config_digest(supervisor_runtime_config.ingestor_config_path),
                        "router_config": config_digest(supervisor_runtime_config.router_config_path),
                        "account_state_config": config_digest(supervisor_runtime_config.account_state_config_path),
                        "stale_order_cleanup_config": config_digest(supervisor_runtime_config.stale_order_cleanup_config_path),
                        "position_manager_config": config_digest(supervisor_runtime_config.position_manager_config_path),
                        "execution_config": config_digest(supervisor_runtime_config.execution_config_path),
                    },
                    "local_simulation_isolated": True,
                    "local_ledger_input_ref": "",
                    "legacy_fast_queue_used": False,
                    "manual_m12_37_once_used": False,
                }
            ),
            encoding="utf-8",
        )
        (output_dir / "m15_longbridge_realtime_execution.json").write_text(
            json.dumps(
                {
                    "runtime_ids_seen_this_cycle": ["M10-PA-004-long-1d"],
                    "recent_execution_inputs": [
                        {
                            "signal_id": "fixture-signal",
                            "runtime_id": "M10-PA-004-long-1d",
                            "symbol": "AAPL",
                            "created_at": "2026-06-04T12:19:59Z",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (output_dir / "m15_longbridge_realtime_session_supervisor.pid").write_text(str(os.getpid()), encoding="utf-8")
        readiness_config.write_text(
            json.dumps(
                {
                    "stage": "M15.opening_trade_readiness",
                    "inputs": {
                        "m12_47_status": str(m12_status),
                        "realtime_runtime_engine": "cli",
                        "realtime_supervisor_config": str(supervisor_config),
                        "execution_config": str(execution_config),
                        "realtime_account_state": str(account_state),
                        "realtime_supervisor_status": str(realtime_status),
                    },
                    "outputs": {"output_dir": str(root / "readiness")},
                }
            ),
            encoding="utf-8",
        )
        return readiness_config


if __name__ == "__main__":
    unittest.main()
