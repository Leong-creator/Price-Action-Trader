from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_internal_sim_launch_readiness_lib import load_config, run_m14_internal_sim_launch_readiness


class M14InternalSimLaunchReadinessTest(unittest.TestCase):
    def test_launch_readiness_keeps_approved_strategies_internal_sim_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_internal_sim_launch_readiness(
                load_config(config_path),
                generated_at="2026-05-26T14:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.internal-sim-launch-readiness.v1")
            self.assertTrue(result["challenge"]["ten_day_challenge_complete"])
            self.assertEqual(result["summary"]["approved_internal_sim_strategy_count"], 2)
            self.assertEqual(result["summary"]["launch_ready_strategy_count"], 2)
            self.assertEqual(result["summary"]["broker_watch_strategy_count"], 1)
            self.assertEqual(result["summary"]["m12_account_input_connected_runtime_count"], 3)
            self.assertEqual(result["summary"]["m12_account_input_runtime_count"], 3)
            self.assertEqual(result["summary"]["broker_dry_run_ready_count"], 1)
            self.assertEqual(result["summary"]["broker_dry_run_blocked_count"], 1)
            self.assertEqual(result["summary"]["hard_boundary_violation_count"], 0)
            self.assertTrue(result["summary"]["can_continue_internal_simulated_account"])
            self.assertFalse(result["summary"]["can_start_broker_paper"])
            self.assertTrue(all(result["execution_boundaries"].values()))
            self.assertIn("broker paper/live stays disabled", result["plain_language_result"])

            rows = {row["strategy_id"]: row for row in result["strategy_rows"]}
            self.assertEqual(rows["M10-PA-004"]["internal_sim_launch_status"], "ready_internal_sim_continue")
            self.assertEqual(
                rows["M10-PA-005"]["internal_sim_launch_status"],
                "ready_internal_sim_continue_with_broker_dry_run_watch",
            )
            self.assertEqual(rows["M10-PA-005"]["broker_blocker_reason_counts"], {"max_total_exposure_exceeded": 1, "risk_decision_not_allow": 1})
            for row in rows.values():
                self.assertTrue(row["can_continue_internal_simulated_account"])
                self.assertFalse(row["broker_connection"])
                self.assertFalse(row["real_order"])
                self.assertFalse(row["live_execution"])
                self.assertFalse(row["paper_trading_approval"])

            persisted = json.loads((root / "launch.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "launch.md").read_text(encoding="utf-8")
            self.assertIn("M14 Internal Sim Launch Readiness", md)
            self.assertIn("Approved Strategy Rows", md)
            self.assertIn("Boundary Check", md)

    def test_unsafe_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["broker_connection"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        summary_path = root / "summary.json"
        gate_path = root / "gate.json"
        registry_path = root / "registry.json"
        audit_path = root / "audit.json"
        scorecard_path = root / "scorecard.json"
        broker_path = root / "broker.json"
        config_path = root / "config.json"

        summary_path.write_text(
            json.dumps(
                {
                    "trading_date": "2026-05-22",
                    "challenge_progress_label": "10/10",
                    "effective_challenge_trading_days": 10,
                    "required_challenge_trading_days": 10,
                    "data_quality_state": "history_recompute_from_existing_challenge",
                    "m12_current_day_runtime_ready": False,
                    "paper_simulated_only": True,
                    "internal_simulated_account": True,
                    "broker_paper_connection": False,
                    "real_money_actions": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                }
            ),
            encoding="utf-8",
        )
        gate_path.write_text(
            json.dumps(
                {
                    "approved_internal_sim_strategy_ids": ["M10-PA-004", "M10-PA-005"],
                    "gate_scope": "internal_simulated_account_only",
                    "paper_simulated_only": True,
                    "internal_simulated_account": True,
                    "broker_paper_connection": False,
                    "trading_connection": False,
                    "real_money_actions": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "rows": [
                        self._gate_row("M10-PA-004", ["M10-PA-004-long-1d"]),
                        self._gate_row("M10-PA-005", ["M10-PA-005-1d", "M10-PA-005-5m"]),
                    ],
                }
            ),
            encoding="utf-8",
        )
        registry_path.write_text(
            json.dumps(
                {
                    "strategies": [
                        {
                            "strategy_id": "M10-PA-004",
                            "display_name": "PA004",
                            "runtime_accounts": [
                                {"runtime_id": "M10-PA-004-long-1d", "timeframe": "1d", "lane": "mainline"}
                            ],
                        },
                        {
                            "strategy_id": "M10-PA-005",
                            "display_name": "PA005",
                            "runtime_accounts": [
                                {"runtime_id": "M10-PA-005-1d", "timeframe": "1d", "lane": "experimental"},
                                {"runtime_id": "M10-PA-005-5m", "timeframe": "5m", "lane": "experimental"},
                            ],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        audit_path.write_text(
            json.dumps(
                {
                    "rows": [
                        self._audit_row("M10-PA-004", "M10-PA-004-long-1d", "connected_zero_signal_today", 0),
                        self._audit_row("M10-PA-005", "M10-PA-005-1d", "connected_zero_signal_today", 0),
                        self._audit_row("M10-PA-005", "M10-PA-005-5m", "connected_with_signal_today", 8),
                    ]
                }
            ),
            encoding="utf-8",
        )
        scorecard_path.write_text(
            json.dumps(
                {
                    "rows": [
                        self._scorecard_row("M10-PA-004", 0, 0, 0, "zero_signal"),
                        self._scorecard_row("M10-PA-005", 8, 2, 2, "signal_generated,zero_signal"),
                    ]
                }
            ),
            encoding="utf-8",
        )
        broker_path.write_text(
            json.dumps(
                {
                    "mode": "paper_dry_run_only",
                    "dry_run_ready_count": 1,
                    "blocked_count": 1,
                    "source_risk_check_count": 2,
                    "broker_connection_enabled": False,
                    "real_order_enabled": False,
                    "live_execution_enabled": False,
                    "paper_trading_approval": False,
                    "rows": [
                        {
                            "strategy_id": "M10-PA-005",
                            "runtime_id": "M10-PA-005-5m",
                            "readiness_status": "dry_run_ready",
                            "reason_codes": ["paper_dry_run_only"],
                            "source_risk_reason_codes": ["allow"],
                        },
                        {
                            "strategy_id": "M10-PA-005",
                            "runtime_id": "M10-PA-005-5m",
                            "readiness_status": "blocked",
                            "reason_codes": ["risk_decision_not_allow"],
                            "source_risk_reason_codes": ["max_total_exposure_exceeded"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.internal-sim-launch-readiness.config.v1",
                    "stage": "M14.internal_sim_launch_readiness",
                    "project_stage_label": "M14 launch fixture",
                    "inputs": {
                        "m14_summary": str(summary_path),
                        "m14_paper_trial_gate": str(gate_path),
                        "m13_strategy_runtime_registry": str(registry_path),
                        "m12_account_input_audit": str(audit_path),
                        "m13_daily_strategy_scorecard": str(scorecard_path),
                        "m14_2_broker_readiness_plan": str(broker_path),
                    },
                    "outputs": {
                        "readiness_json": str(root / "launch.json"),
                        "readiness_md": str(root / "launch.md"),
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "internal_simulated_account": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _gate_row(self, strategy_id: str, runtime_ids: list[str]) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "display_name": strategy_id,
            "completed_trading_days": 10,
            "required_trading_days": 10,
            "decision": "promote",
            "paper_trial_gate": "approved_internal_sim_only",
            "runtime_ids": runtime_ids,
        }

    def _audit_row(self, strategy_id: str, runtime_id: str, status: str, signal_count: int) -> dict[str, str]:
        return {
            "strategy_id": strategy_id,
            "runtime_id": runtime_id,
            "input_status": status,
            "formal_input_stream": "true",
            "source_row_count": str(signal_count),
            "today_formal_signal_count": str(signal_count),
        }

    def _scorecard_row(self, strategy_id: str, signal_count: int, open_count: int, close_count: int, states: str) -> dict[str, str]:
        return {
            "strategy_id": strategy_id,
            "signal_count": str(signal_count),
            "open_count": str(open_count),
            "close_count": str(close_count),
            "test_states": states,
        }


if __name__ == "__main__":
    unittest.main()
