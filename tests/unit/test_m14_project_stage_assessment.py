from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_project_stage_assessment_lib import load_config, run_m14_project_stage_assessment


class M14ProjectStageAssessmentTest(unittest.TestCase):
    def test_builds_stage_assessment_and_strategy_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_project_stage_assessment(
                load_config(config_path),
                generated_at="2026-05-26T16:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.project-stage-assessment.v1")
            self.assertEqual(result["summary"]["challenge_progress_label"], "10/10")
            self.assertTrue(result["summary"]["ten_day_challenge_complete"])
            self.assertEqual(result["summary"]["approved_internal_sim_strategy_count"], 2)
            self.assertEqual(result["summary"]["approved_internal_sim_strategy_ids"], ["M10-PA-004", "M10-PA-005"])
            self.assertTrue(result["summary"]["can_run_next_internal_sim_session"])
            self.assertEqual(result["summary"]["approved_runtime_input_connected_count"], 3)
            self.assertEqual(result["summary"]["approved_runtime_input_count"], 3)
            self.assertEqual(result["summary"]["rescue_runtime_strategy_count"], 2)
            self.assertEqual(result["summary"]["rescue_m13_ledger_observed_strategy_count"], 1)
            self.assertEqual(result["summary"]["rescue_no_m13_ledger_evidence_count"], 1)
            self.assertEqual(result["summary"]["rescue_promotion_allowed_count"], 0)
            self.assertEqual(result["summary"]["broker_dry_run_ready_count"], 1)
            self.assertEqual(result["summary"]["broker_dry_run_blocked_count"], 1)
            self.assertFalse(result["summary"]["can_start_broker_paper"])
            self.assertFalse(result["summary"]["manual_m12_37_once_allowed"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])

            self.assertEqual(
                result["summary"]["route_counts"],
                {
                    "approved_internal_sim_continue": 2,
                    "rebuild_detector_then_ab": 1,
                    "rescue_ab_collect": 1,
                    "shadow_or_plugin_review": 1,
                },
            )
            rows = {row["strategy_id"]: row for row in result["strategy_routes"]}
            self.assertEqual(rows["M10-PA-004"]["route_category"], "approved_internal_sim_continue")
            self.assertFalse(rows["M10-PA-004"]["broker_watch"])
            self.assertEqual(rows["M10-PA-005"]["route_category"], "approved_internal_sim_continue")
            self.assertTrue(rows["M10-PA-005"]["broker_watch"])
            self.assertEqual(rows["M10-PA-001"]["route_category"], "rescue_ab_collect")
            self.assertTrue(rows["M10-PA-001"]["requires_10_day_ab_evidence"])
            self.assertEqual(rows["M10-PA-011"]["route_category"], "rebuild_detector_then_ab")

            self.assertEqual(
                result["stage_assessment"]["stage_decision"],
                "continue_approved_internal_sim_and_collect_rescue_ab_evidence",
            )
            self.assertFalse(result["goal_completion_assessment"]["goal_complete"])
            self.assertEqual(
                result["rescue_policy"]["policy"],
                "do_not_discard_before_rescue_route_exhausted",
            )
            self.assertFalse(result["next_fresh_refresh_acceptance"]["manual_m12_37_once_allowed"])

            persisted = json.loads((root / "assessment.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "assessment.md").read_text(encoding="utf-8")
            self.assertIn("M14 Project Stage Assessment", md)
            self.assertIn("Manual M12.37 once-mode allowed: `False`", md)
            self.assertIn("approved_internal_sim_continue", md)

    def test_rejects_live_or_manual_once_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["manual_m12_37_once"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "manual_m12_37_once"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        goal_path = root / "goal.json"
        next_session_path = root / "next_session.json"
        rescue_plan_path = root / "rescue_plan.json"
        backlog_path = root / "backlog.json"
        config_path = root / "config.json"

        goal_path.write_text(
            json.dumps(
                {
                    "project_stage_label": "M14 test stage",
                    "m14_trading_date": "2026-05-22",
                    "challenge": {
                        "challenge_progress_label": "10/10",
                        "ten_day_challenge_complete": True,
                        "effective_challenge_trading_days": 10,
                        "required_challenge_trading_days": 10,
                        "data_quality_state": "history_recompute_from_existing_challenge",
                    },
                    "internal_simulation_gate": {
                        "approved_internal_sim_strategy_count": 2,
                        "approved_internal_sim_strategy_ids": ["M10-PA-004", "M10-PA-005"],
                    },
                    "internal_sim_launch_readiness": {
                        "launch_ready_strategy_count": 2,
                    },
                    "rescue_ab_evidence": {
                        "rescue_runtime_strategy_count": 2,
                        "m13_ledger_observed_strategy_count": 1,
                        "no_m13_ledger_evidence_count": 1,
                        "no_m13_ledger_evidence_strategy_ids": ["M10-PA-012-shadow"],
                        "promotion_allowed_count": 0,
                    },
                    "rescue_next_refresh_readiness": {
                        "watch_rows": 4,
                        "parameter_change_allowed_now_count": 0,
                    },
                    "broker_readiness": {
                        "dry_run_ready_count": 1,
                        "blocked_count": 1,
                    },
                    "strategy_action_matrix": [
                        self._matrix_row("M10-PA-004", "continue_internal_simulation", "promote", False),
                        self._matrix_row("M10-PA-005", "continue_internal_simulation", "promote", False),
                        self._matrix_row("M10-PA-001", "collect_rescue_ab_evidence", "modify", True),
                        self._matrix_row("M10-PA-011", "rebuild_detector_ab_evidence", "reject", True),
                        self._matrix_row("M10-PA-003", "continue_shadow_or_plugin_review", "continue_testing", False),
                    ],
                    "next_actions": [
                        {"priority": "P0", "action": "Run approved strategies", "boundary": "No broker/live"}
                    ],
                    "external_reference_policy": {
                        "allowed_use": "architecture inspiration only",
                        "forbidden_use": "copy-trading",
                        "references": [],
                    },
                    "plain_language_result": "Goal fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        next_session_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "next_session_mode": "m12_47_supervised_fresh_refresh_only",
                        "can_run_next_internal_sim_session": True,
                        "approved_runtime_input_connected_count": 3,
                        "approved_runtime_input_count": 3,
                        "broker_watch_strategy_count": 1,
                        "broker_watch_strategy_ids": ["M10-PA-005"],
                    },
                    "strategy_session_rows": [
                        {
                            "strategy_id": "M10-PA-004",
                            "session_action": "continue_internal_simulated_account_testing",
                            "broker_dry_run_blocked_count": 0,
                            "linked_next_refresh_watch_count": 0,
                            "linked_next_refresh_family_counts": {},
                        },
                        {
                            "strategy_id": "M10-PA-005",
                            "session_action": "continue_internal_sim_and_watch_broker_dry_run_blockers",
                            "broker_dry_run_blocked_count": 1,
                            "linked_next_refresh_watch_count": 2,
                            "linked_next_refresh_family_counts": {"broker_rule_shadow_recheck": 2},
                        },
                    ],
                    "global_watch_rows": [
                        {
                            "priority": "P0",
                            "watch_id": "broker_live_boundary_check",
                            "expected_after_refresh": "broker/live stays disabled",
                        }
                    ],
                    "execution_protocol": [
                        {
                            "step": "wait_for_m12_47_supervisor_window",
                            "owner": "M12.47 supervisor",
                            "rule": "Do not run M12.37 once-mode manually.",
                        }
                    ],
                    "plain_language_result": "Next-session fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        rescue_plan_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {"strategy_id": "M10-PA-001", "next_action": "Create rescue variant and collect A/B evidence."},
                        {"strategy_id": "M10-PA-011", "next_action": "Rebuild detector before final rejection."},
                    ],
                    "external_references": [],
                }
            ),
            encoding="utf-8",
        )
        backlog_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "actionable_before_10d_count": 2,
                        "zero_signal_after_connection_count": 1,
                        "missing_rescue_ledger_count": 1,
                        "broker_blocker_reason_counts": {"max_total_exposure_exceeded": 1},
                    },
                    "plain_language_result": "Backlog fixture plain result.",
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.project-stage-assessment.config.v1",
                    "stage": "M14.project_stage_assessment",
                    "project_stage_label": "fixture project stage assessment",
                    "inputs": {
                        "m14_goal_readiness_report": str(goal_path),
                        "m14_internal_sim_next_session_plan": str(next_session_path),
                        "m14_strategy_rescue_plan": str(rescue_plan_path),
                        "m14_rescue_optimization_backlog": str(backlog_path),
                    },
                    "outputs": {
                        "assessment_json": str(root / "assessment.json"),
                        "assessment_md": str(root / "assessment.md"),
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "internal_simulated_account": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                        "manual_m12_37_once": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _matrix_row(
        self,
        strategy_id: str,
        next_action_category: str,
        decision: str,
        requires_ab: bool,
    ) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "display_name": strategy_id,
            "paper_trial_gate": "approved_internal_sim_only"
            if next_action_category == "continue_internal_simulation"
            else "not_approved_modify_candidate",
            "decision": decision,
            "decision_reason": "fixture",
            "completed_trading_days": 10,
            "runtime_ids": [f"{strategy_id}-runtime"],
            "rescue_runtime_strategy_ids": [f"{strategy_id}-rescue"] if requires_ab else [],
            "requires_10_day_ab_evidence": requires_ab,
            "can_enter_internal_simulation": next_action_category == "continue_internal_simulation",
            "next_action_category": next_action_category,
            "rescue_coverage_status": "covered_by_rescue_runtime" if requires_ab else "",
        }


if __name__ == "__main__":
    unittest.main()
