from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.m15_opening_trade_readiness_lib import load_config, run_m15_opening_trade_readiness
from scripts.m15_longbridge_realtime_session_supervisor_lib import (
    build_window_state,
    config_digest,
    load_config as load_realtime_supervisor_config,
    runtime_identity_payload,
)


class M15OpeningTradeReadinessTest(unittest.TestCase):
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
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertIn("process=alive", checks["m15_realtime_daemon_alive"]["actual"])

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
