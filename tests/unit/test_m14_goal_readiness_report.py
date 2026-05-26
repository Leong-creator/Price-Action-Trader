from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_goal_readiness_report_lib import load_config, run_m14_goal_readiness_report


class M14GoalReadinessReportTest(unittest.TestCase):
    def test_report_synthesizes_stage_gate_rescue_and_broker_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_goal_readiness_report(
                load_config(config_path),
                generated_at="2026-05-26T13:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.goal-readiness-report.v1")
            self.assertTrue(result["challenge"]["ten_day_challenge_complete"])
            self.assertTrue(result["internal_simulation_gate"]["can_enter_internal_simulation_for_approved_strategies"])
            self.assertEqual(result["internal_simulation_gate"]["approved_internal_sim_strategy_ids"], ["M10-PA-004"])
            self.assertEqual(result["rescue_status"]["rescue_runtime_connected_strategy_count"], 2)
            self.assertTrue(result["rescue_status"]["rescue_ready_for_ab_evidence_collection"])
            self.assertEqual(result["rescue_ab_evidence"]["m13_ledger_observed_strategy_count"], 2)
            self.assertEqual(result["rescue_ab_evidence"]["rescue_runtime_strategy_count"], 2)
            self.assertEqual(result["rescue_ab_evidence"]["evidence_ready_for_manual_review_count"], 0)
            self.assertEqual(result["rescue_ab_evidence"]["promotion_allowed_count"], 0)
            self.assertEqual(result["broker_readiness"]["mode"], "paper_dry_run_only")
            self.assertEqual(result["broker_readiness"]["dry_run_ready_count"], 1)
            self.assertEqual(result["broker_readiness"]["blocked_count"], 1)
            self.assertTrue(all(result["execution_boundaries"].values()))
            self.assertFalse(result["goal_completion_assessment"]["goal_complete"])
            self.assertIn("no broker/live/real order approval", result["plain_language_result"])

            matrix = {row["strategy_id"]: row for row in result["strategy_action_matrix"]}
            self.assertEqual(matrix["M10-PA-004"]["next_action_category"], "continue_internal_simulation")
            self.assertTrue(matrix["M10-PA-004"]["can_enter_internal_simulation"])
            self.assertEqual(matrix["M10-PA-001"]["next_action_category"], "collect_rescue_ab_evidence")
            self.assertEqual(matrix["M10-PA-011"]["next_action_category"], "rebuild_detector_ab_evidence")
            for row in matrix.values():
                self.assertFalse(row["broker_connection"])
                self.assertFalse(row["real_order"])
                self.assertFalse(row["live_execution"])
                self.assertFalse(row["paper_trading_approval"])

            persisted = json.loads((root / "readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["project_stage_label"], result["project_stage_label"])
            md = (root / "readiness.md").read_text(encoding="utf-8")
            self.assertIn("Internal simulated-account ready strategies", md)
            self.assertIn("Rescue A/B Evidence", md)
            self.assertIn("Completion Assessment", md)

    def test_unsafe_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["live_execution"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        summary_path = root / "summary.json"
        gate_path = root / "gate.json"
        rescue_plan_path = root / "rescue_plan.json"
        rescue_coverage_path = root / "rescue_coverage.json"
        rescue_ab_path = root / "rescue_ab.json"
        broker_path = root / "broker.json"
        config_path = root / "config.json"
        summary_path.write_text(
            json.dumps(
                {
                    "stage": "M14.strategy_challenge_paper_gate",
                    "trading_date": "2026-05-22",
                    "challenge_progress_label": "10/10",
                    "effective_challenge_trading_days": 10,
                    "required_challenge_trading_days": 10,
                    "data_quality_state": "history_recompute_from_existing_challenge",
                    "recompute_only": True,
                    "m12_current_day_runtime_ready": False,
                    "paper_simulated_only": True,
                    "internal_simulated_account": True,
                    "broker_paper_connection": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                }
            ),
            encoding="utf-8",
        )
        gate_path.write_text(
            json.dumps(
                {
                    "gate_scope": "internal_simulated_account_only",
                    "approved_internal_sim_strategy_ids": ["M10-PA-004"],
                    "paper_simulated_only": True,
                    "internal_simulated_account": True,
                    "broker_paper_connection": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "rows": [
                        self._gate_row("M10-PA-004", "approved_internal_sim_only", "promote"),
                        self._gate_row("M10-PA-001", "not_approved_modify_candidate", "modify"),
                        self._gate_row("M10-PA-011", "not_approved_rejected", "reject"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        rescue_plan_path.write_text(
            json.dumps(
                {
                    "external_references": [
                        {
                            "project": "example",
                            "url": "https://example.test/project",
                            "usable_pattern": "shadow diagnostics",
                            "boundary": "local gates only",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        rescue_coverage_path.write_text(
            json.dumps(
                {
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "connected_rescue_strategy_count": 2,
                    "registered_rescue_strategy_count": 2,
                    "registered_rescue_account_count": 2,
                    "planned_action_covered_count": 2,
                    "planned_action_row_count": 2,
                    "all_registered_rescue_inputs_connected": True,
                    "all_planned_rescue_actions_have_runtime_coverage": True,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "pending_rescue_strategy_ids": [],
                    "pending_planned_action_strategy_ids": [],
                    "next_required_evidence": "10 trading-day A/B ledger evidence",
                    "planned_action_rows": [
                        {
                            "strategy_id": "M10-PA-001",
                            "coverage_status": "covered_by_rescue_runtime",
                            "coverage_strategy_ids": ["M10-PA-001-m14-modify-20260522"],
                        },
                        {
                            "strategy_id": "M10-PA-011",
                            "coverage_status": "covered_by_rescue_runtime",
                            "coverage_strategy_ids": ["M10-PA-011-ORB-R1"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        rescue_ab_path.write_text(
            json.dumps(
                {
                    "min_ab_trading_days": 10,
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "summary": {
                        "rescue_runtime_strategy_count": 2,
                        "m13_ledger_observed_strategy_count": 2,
                        "collecting_evidence_count": 2,
                        "evidence_ready_for_manual_review_count": 0,
                        "no_m13_ledger_evidence_count": 0,
                        "promotion_allowed_count": 0,
                        "pending_evidence_strategy_ids": [
                            "M10-PA-001-m14-modify-20260522",
                            "M10-PA-011-ORB-R1",
                        ],
                        "no_m13_ledger_evidence_strategy_ids": [],
                        "evidence_ready_for_manual_review_strategy_ids": [],
                    },
                    "plain_language_result": "fixture rescue A/B evidence summary",
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
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.goal-readiness-report.config.v1",
                    "stage": "M14.goal_readiness_report",
                    "project_stage_label": "M14 test",
                    "inputs": {
                        "m14_summary": str(summary_path),
                        "m14_paper_trial_gate": str(gate_path),
                        "m14_strategy_rescue_plan": str(rescue_plan_path),
                        "m14_rescue_runtime_coverage": str(rescue_coverage_path),
                        "m14_rescue_ab_evidence_tracker": str(rescue_ab_path),
                        "m14_2_broker_readiness_plan": str(broker_path),
                    },
                    "outputs": {
                        "readiness_json": str(root / "readiness.json"),
                        "readiness_md": str(root / "readiness.md"),
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

    def _gate_row(self, strategy_id: str, gate: str, decision: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "display_name": strategy_id,
            "completed_trading_days": 10,
            "decision": decision,
            "decision_reason": "fixture",
            "paper_trial_gate": gate,
            "runtime_ids": [f"{strategy_id}-1d"],
            "broker_paper_connection": False,
            "real_money_actions": False,
            "live_execution": False,
            "paper_trading_approval": False,
        }


if __name__ == "__main__":
    unittest.main()
