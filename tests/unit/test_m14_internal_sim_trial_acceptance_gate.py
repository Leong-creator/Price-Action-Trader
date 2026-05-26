from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_internal_sim_trial_acceptance_gate_lib import (
    load_config,
    run_m14_internal_sim_trial_acceptance_gate,
)


class M14InternalSimTrialAcceptanceGateTest(unittest.TestCase):
    def test_builds_trial_acceptance_gate_without_broker_or_legacy_profit_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_internal_sim_trial_acceptance_gate(
                load_config(config_path),
                generated_at="2026-05-26T16:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.internal-sim-trial-acceptance-gate.v1")
            self.assertEqual(result["summary"]["approved_trial_strategy_count"], 2)
            self.assertEqual(result["summary"]["trial_start_ready_count"], 2)
            self.assertTrue(result["summary"]["can_start_internal_sim_trial_now"])
            self.assertEqual(result["summary"]["fresh_refresh_required_count"], 2)
            self.assertEqual(result["summary"]["post_refresh_waiting_count"], 13)
            self.assertFalse(result["summary"]["post_refresh_fresh_refresh_observed"])
            self.assertEqual(result["summary"]["post_refresh_source_quote"], "fallback_quotes_only")
            self.assertEqual(result["summary"]["legacy_historical_profit_planning_input_count"], 0)
            self.assertFalse(result["summary"]["manual_m12_37_once_allowed"])
            self.assertFalse(result["summary"]["can_start_broker_paper"])
            self.assertFalse(result["summary"]["broker_or_live_enabled"])
            self.assertEqual(result["summary"]["global_gate_state_counts"], {"pass": 3, "waiting": 2})
            self.assertEqual(
                [row["step_id"] for row in result["post_trial_recompute_protocol"]],
                [
                    "review_post_refresh_outcomes",
                    "refresh_internal_sim_next_session_plan",
                    "strategy_next_step_readiness_matrix_refresh",
                    "project_stage_assessment_refresh",
                ],
            )
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["legacy_historical_profit_planning_input"])

            gates = {row["gate_id"]: row for row in result["global_acceptance_gates"]}
            self.assertEqual(gates["legacy_history_metric_exclusion_gate"]["state"], "pass")
            self.assertEqual(gates["m12_47_fresh_refresh_gate"]["state"], "waiting")

            rows = {row["strategy_id"]: row for row in result["trial_acceptance_rows"]}
            self.assertEqual(rows["M10-PA-004"]["trial_start_status"], "ready_internal_sim_trial")
            self.assertEqual(
                rows["M10-PA-008"]["trial_start_status"],
                "ready_internal_sim_trial_with_broker_watch_only",
            )
            self.assertIn("broker_dry_run_blockers_remain_watch_only", rows["M10-PA-008"]["required_trial_evidence"])
            self.assertIn(
                "first_rescue_specific_m13_ledger_watch",
                rows["M10-PA-008"]["post_refresh_acceptance_checks"],
            )
            self.assertFalse(rows["M10-PA-008"]["legacy_historical_profit_planning_input"])

            md = (root / "gate.md").read_text(encoding="utf-8")
            self.assertIn("M14 Internal Sim Trial Acceptance Gate", md)
            self.assertIn("Legacy history metric planning inputs: `0`", md)
            self.assertIn("Broker paper/live/manual M12.37/parameter mutation", md)

    def test_rejects_legacy_profit_or_broker_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["legacy_historical_profit_planning_input"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "legacy_historical_profit_planning_input"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        next_session_path = root / "next_session.json"
        next_step_path = root / "next_step.json"
        project_stage_path = root / "project_stage.json"
        checklist_path = root / "checklist.json"
        objective_blocker_path = root / "objective_blocker.json"
        post_refresh_path = root / "post_refresh.json"
        config_path = root / "config.json"

        next_session_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "approved_internal_sim_strategy_count": 2,
                        "launch_ready_strategy_count": 2,
                        "approved_runtime_input_connected_count": 3,
                        "approved_runtime_input_count": 3,
                        "broker_watch_strategy_count": 1,
                        "broker_watch_strategy_ids": ["M10-PA-008"],
                        "can_run_next_internal_sim_session": True,
                        "next_session_mode": "m12_47_supervised_fresh_refresh_only",
                        "legacy_historical_profit_planning_input_count": 0,
                    },
                    "strategy_session_rows": [
                        {
                            "strategy_id": "M10-PA-004",
                            "display_name": "PA004",
                            "runtime_ids": ["M10-PA-004-long-1d"],
                            "session_action": "continue_internal_simulated_account_testing",
                            "can_continue_internal_simulated_account": True,
                            "m12_account_input_connected_runtime_count": 1,
                            "m12_account_input_runtime_count": 1,
                            "m13_signal_count": 0,
                            "m13_open_count": 0,
                            "m13_close_count": 0,
                            "broker_dry_run_ready_count": 0,
                            "broker_dry_run_blocked_count": 0,
                            "linked_next_refresh_watch_count": 0,
                            "linked_next_refresh_family_counts": {},
                        },
                        {
                            "strategy_id": "M10-PA-008",
                            "display_name": "PA008",
                            "runtime_ids": ["M10-PA-008-1d", "M10-PA-008-shadow-1d"],
                            "session_action": "continue_internal_sim_and_watch_broker_dry_run_blockers",
                            "can_continue_internal_simulated_account": True,
                            "m12_account_input_connected_runtime_count": 2,
                            "m12_account_input_runtime_count": 2,
                            "m13_signal_count": 1,
                            "m13_open_count": 1,
                            "m13_close_count": 0,
                            "broker_dry_run_ready_count": 0,
                            "broker_dry_run_blocked_count": 1,
                            "broker_blocker_reason_counts": {"max_risk_per_order_exceeded": 1},
                            "linked_next_refresh_watch_count": 1,
                            "linked_next_refresh_family_counts": {"first_rescue_ledger_watch": 1},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        next_step_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "legacy_historical_profit_planning_input_count": 0,
                        "approved_internal_sim_continue_count": 2,
                    },
                    "matrix_rows": [
                        self._matrix_row("M10-PA-004", "PA004", []),
                        self._matrix_row(
                            "M10-PA-008",
                            "PA008",
                            ["first_m13_rescue_ledger", "shadow_parameter_review"],
                        ),
                    ],
                }
            ),
            encoding="utf-8",
        )
        project_stage_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "current_project_stage": "M14 stable strategy testing + M14.2 broker readiness dry-run scaffold",
                        "challenge_progress_label": "10/10",
                        "can_start_broker_paper": False,
                        "broker_or_live_enabled": False,
                        "manual_m12_37_once_allowed": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        checklist_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "recompute_step_count": 26,
                        "acceptance_gate_count": 8,
                        "two_pass_stabilization_required": True,
                    },
                    "recompute_steps": [
                        self._recompute_step("review_post_refresh_outcomes", 2),
                        self._recompute_step("refresh_internal_sim_next_session_plan", 14),
                        self._recompute_step("strategy_next_step_readiness_matrix_refresh", 21),
                        self._recompute_step("project_stage_assessment_refresh", 26),
                    ],
                }
            ),
            encoding="utf-8",
        )
        objective_blocker_path.write_text(
            json.dumps({"summary": {"legacy_historical_profit_planning_input_count": 0}}),
            encoding="utf-8",
        )
        post_refresh_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "fresh_refresh_observed": False,
                        "source_quote": "fallback_quotes_only",
                        "waiting_count": 13,
                    }
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "stage": "M14.internal_sim_trial_acceptance_gate",
                    "project_stage_label": "fixture trial gate",
                    "inputs": {
                        "m14_internal_sim_next_session_plan": str(next_session_path),
                        "m14_strategy_next_step_readiness_matrix": str(next_step_path),
                        "m14_project_stage_assessment": str(project_stage_path),
                        "m14_post_fresh_refresh_recompute_checklist": str(checklist_path),
                        "m14_objective_blocker_burndown": str(objective_blocker_path),
                        "m14_rescue_post_refresh_outcome_review": str(post_refresh_path),
                    },
                    "outputs": {
                        "acceptance_gate_json": str(root / "gate.json"),
                        "acceptance_gate_md": str(root / "gate.md"),
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "internal_simulated_account": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                        "manual_m12_37_once": False,
                        "m13_registry_mutation": False,
                        "m12_account_specs_mutation": False,
                        "broker_readiness_status_mutation": False,
                        "parameter_mutation": False,
                        "legacy_historical_profit_planning_input": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _matrix_row(self, strategy_id: str, display_name: str, extra_evidence: list[str]) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "display_name": display_name,
            "current_bucket": "approved_internal_sim_continue",
            "next_step_type": "continue_next_internal_sim_refresh",
            "can_continue_internal_sim_now": True,
            "completed_trading_days": 10,
            "required_next_evidence": [
                "m12_47_fresh_refresh",
                "post_refresh_m13_m14_recompute",
                *extra_evidence,
            ],
            "blocked_by": ["m12_47_fresh_refresh_not_observed"],
            "legacy_historical_profit_planning_input": False,
        }

    def _recompute_step(self, step_id: str, order: int) -> dict[str, object]:
        return {
            "step_id": step_id,
            "order": order,
            "command": f"python scripts/run_{step_id}.py",
            "required_timing": "after_m12_47_fresh_refresh",
            "acceptance_hint": "fixture acceptance hint",
        }


if __name__ == "__main__":
    unittest.main()
