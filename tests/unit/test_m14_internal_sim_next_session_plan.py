from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_internal_sim_next_session_plan_lib import load_config, run_m14_internal_sim_next_session_plan


class M14InternalSimNextSessionPlanTest(unittest.TestCase):
    def test_builds_next_session_plan_without_broker_or_manual_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_internal_sim_next_session_plan(
                load_config(config_path),
                generated_at="2026-05-26T15:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.internal-sim-next-session-plan.v1")
            self.assertEqual(result["summary"]["next_session_mode"], "m12_47_supervised_fresh_refresh_only")
            self.assertTrue(result["summary"]["can_run_next_internal_sim_session"])
            self.assertEqual(result["summary"]["approved_internal_sim_strategy_count"], 2)
            self.assertEqual(result["summary"]["launch_ready_strategy_count"], 2)
            self.assertEqual(result["summary"]["approved_runtime_input_connected_count"], 3)
            self.assertEqual(result["summary"]["approved_runtime_input_count"], 3)
            self.assertEqual(result["summary"]["broker_watch_strategy_count"], 1)
            self.assertEqual(result["summary"]["global_watch_row_count"], 5)
            self.assertEqual(result["summary"]["rescue_next_refresh_watch_rows"], 3)
            self.assertEqual(result["summary"]["first_ledger_watch_count"], 1)
            self.assertEqual(result["summary"]["broker_rule_shadow_watch_count"], 2)
            self.assertEqual(result["summary"]["parameter_change_allowed_now_count"], 0)
            self.assertFalse(result["summary"]["manual_m12_37_once_allowed"])
            self.assertEqual(result["summary"]["legacy_historical_profit_planning_input_count"], 0)
            self.assertFalse(result["summary"]["can_start_broker_paper"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["legacy_historical_profit_planning_input"])
            self.assertIn(
                "legacy_history_metric_boundary_check",
                {row["watch_id"] for row in result["global_watch_rows"]},
            )

            rows = {row["strategy_id"]: row for row in result["strategy_session_rows"]}
            self.assertEqual(rows["M10-PA-004"]["session_action"], "continue_internal_simulated_account_testing")
            self.assertFalse(rows["M10-PA-004"]["legacy_historical_profit_planning_input"])
            self.assertIn(
                "legacy_history_metrics_display_only_not_planning_input",
                rows["M10-PA-004"]["acceptance_checks"],
            )
            self.assertEqual(
                rows["M10-PA-005"]["session_action"],
                "continue_internal_sim_and_watch_broker_dry_run_blockers",
            )
            self.assertIn("pa005_rule_shadow_recheck_after_fresh_refresh", rows["M10-PA-005"]["acceptance_checks"])
            self.assertEqual(rows["M10-PA-005"]["linked_next_refresh_family_counts"], {"broker_rule_shadow_recheck": 2})

            md = (root / "plan.md").read_text(encoding="utf-8")
            self.assertIn("M14 Internal Sim Next Session Plan", md)
            self.assertIn("Manual M12.37 once-mode allowed: `False`", md)
            self.assertIn("Broker paper start allowed: `False`", md)
            self.assertIn("Legacy history metric planning inputs: `0`", md)
            self.assertIn("display-only and cannot affect strategy planning", md)

    def test_rejects_manual_m12_37_or_live_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["manual_m12_37_once"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "manual_m12_37_once"):
                load_config(config_path)

    def test_rejects_legacy_historical_profit_planning_input_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["legacy_historical_profit_planning_input"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "legacy_historical_profit_planning_input"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        launch_path = root / "launch.json"
        goal_path = root / "goal.json"
        next_refresh_path = root / "next_refresh.json"
        rescue_ab_path = root / "rescue_ab.json"
        config_path = root / "config.json"

        launch_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "approved_internal_sim_strategy_count": 2,
                        "launch_ready_strategy_count": 2,
                        "m12_account_input_connected_runtime_count": 3,
                        "m12_account_input_runtime_count": 3,
                        "broker_watch_strategy_count": 1,
                        "broker_watch_strategy_ids": ["M10-PA-005"],
                        "hard_boundary_violation_count": 0,
                    },
                    "strategy_rows": [
                        {
                            "strategy_id": "M10-PA-004",
                            "display_name": "PA004",
                            "gate_runtime_ids": ["M10-PA-004-long-1d"],
                            "internal_sim_launch_status": "ready_internal_sim_continue",
                            "can_continue_internal_simulated_account": True,
                            "m12_account_input_connected_runtime_count": 1,
                            "m12_account_input_runtime_count": 1,
                            "m12_account_input_status_counts": {"connected_zero_signal_today": 1},
                            "m13_signal_count": 0,
                            "m13_open_count": 0,
                            "m13_close_count": 0,
                            "m13_test_states": "zero_signal",
                            "broker_dry_run_ready_count": 0,
                            "broker_dry_run_blocked_count": 0,
                            "broker_blocker_reason_counts": {},
                        },
                        {
                            "strategy_id": "M10-PA-005",
                            "display_name": "PA005",
                            "gate_runtime_ids": ["M10-PA-005-1d", "M10-PA-005-5m"],
                            "internal_sim_launch_status": "ready_internal_sim_continue_with_broker_dry_run_watch",
                            "can_continue_internal_simulated_account": True,
                            "m12_account_input_connected_runtime_count": 2,
                            "m12_account_input_runtime_count": 2,
                            "m12_account_input_status_counts": {"connected_with_signal_today": 1, "connected_zero_signal_today": 1},
                            "m13_signal_count": 8,
                            "m13_open_count": 2,
                            "m13_close_count": 2,
                            "m13_test_states": "signal_generated,zero_signal",
                            "broker_dry_run_ready_count": 1,
                            "broker_dry_run_blocked_count": 1,
                            "broker_blocker_reason_counts": {"max_total_exposure_exceeded": 1},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        goal_path.write_text(
            json.dumps({"m14_trading_date": "2026-05-22"}),
            encoding="utf-8",
        )
        next_refresh_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "watch_rows": 3,
                        "first_ledger_watch_count": 1,
                        "broker_rule_shadow_watch_count": 2,
                        "target_stop_shadow_compare_count": 0,
                        "parameter_change_allowed_now_count": 0,
                    },
                    "rows": [
                        self._watch_row("M10-PA-005", "M10-PA-005", "broker_rule_shadow_recheck"),
                        self._watch_row("M10-PA-005", "M10-PA-005", "broker_rule_shadow_recheck"),
                        self._watch_row(
                            "M10-PA-008-broker-risk-cap-shadow",
                            "M10-PA-008",
                            "first_rescue_ledger_watch",
                        ),
                    ],
                }
            ),
            encoding="utf-8",
        )
        rescue_ab_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "no_m13_ledger_evidence_count": 1,
                        "promotion_allowed_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "stage": "M14.internal_sim_next_session_plan",
                    "project_stage_label": "fixture next session",
                    "inputs": {
                        "m14_internal_sim_launch_readiness": str(launch_path),
                        "m14_goal_readiness_report": str(goal_path),
                        "m14_rescue_next_refresh_readiness": str(next_refresh_path),
                        "m14_rescue_ab_evidence_tracker": str(rescue_ab_path),
                    },
                    "outputs": {
                        "plan_json": str(root / "plan.json"),
                        "plan_md": str(root / "plan.md"),
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "internal_simulated_account": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                        "manual_m12_37_once": False,
                        "legacy_historical_profit_planning_input": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _watch_row(self, strategy_id: str, parent_strategy_id: str, family: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "parent_strategy_id": parent_strategy_id,
            "runtime_id": f"{strategy_id}-runtime",
            "readiness_family": family,
        }


if __name__ == "__main__":
    unittest.main()
