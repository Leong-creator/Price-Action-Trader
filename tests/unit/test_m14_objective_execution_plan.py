from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_objective_execution_plan_lib import load_config, run_m14_objective_execution_plan


class M14ObjectiveExecutionPlanTest(unittest.TestCase):
    def test_builds_execution_queue_from_current_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_objective_execution_plan(
                load_config(config_path),
                generated_at="2026-05-26T23:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.objective-execution-plan.v1")
            self.assertFalse(result["summary"]["objective_complete"])
            self.assertEqual(result["summary"]["execution_action_count"], 7)
            self.assertEqual(result["summary"]["p0_action_count"], 5)
            self.assertEqual(result["summary"]["waiting_for_fresh_refresh_action_count"], 5)
            self.assertEqual(result["summary"]["manual_execution_allowed_count"], 0)
            self.assertEqual(result["summary"]["approved_internal_sim_strategy_count"], 2)
            self.assertTrue(result["summary"]["can_run_next_internal_sim_session"])
            self.assertEqual(result["summary"]["rescue_runtime_strategy_count"], 2)
            self.assertEqual(result["summary"]["rescue_rows_collecting_count"], 1)
            self.assertEqual(result["summary"]["rescue_rows_first_ledger_wait_count"], 1)
            self.assertEqual(result["summary"]["parameter_gate_row_count"], 3)
            self.assertEqual(result["summary"]["parameter_digest_waiting_count"], 2)
            self.assertEqual(result["summary"]["parameter_continue_ab_collection_count"], 1)
            self.assertEqual(result["summary"]["strategy_evidence_open_gap_row_count"], 6)
            self.assertEqual(result["summary"]["strategy_evidence_requires_fresh_refresh_count"], 4)
            self.assertEqual(result["summary"]["strategy_evidence_wait_first_ledger_gap_count"], 1)
            self.assertEqual(result["summary"]["strategy_evidence_rescue_10_day_ab_gap_count"], 3)
            self.assertEqual(result["summary"]["strategy_evidence_shadow_review_gap_count"], 2)
            self.assertFalse(result["summary"]["broker_or_live_enabled"])
            self.assertFalse(result["summary"]["manual_m12_37_once_allowed"])

            actions = {row["action_id"]: row for row in result["execution_actions"]}
            self.assertEqual(
                actions["approved_internal_sim_next_refresh"]["action_state"],
                "ready_for_m12_47_supervisor_window",
            )
            self.assertEqual(
                actions["rescue_first_ledger_watch"]["action_state"],
                "waiting_for_m12_47_fresh_refresh",
            )
            self.assertEqual(
                actions["parameter_shadow_review_after_fresh_evidence"]["action_state"],
                "waiting_for_m12_47_fresh_refresh_no_candidates",
            )
            self.assertEqual(actions["broker_dry_run_watch_only"]["action_state"], "guardrail_watch_only")
            self.assertIn("open evidence gaps=6", actions["objective_completion_recheck"]["evidence"])
            for action in result["execution_actions"]:
                self.assertFalse(action["manual_execution_allowed"])
                self.assertFalse(action["broker_connection"])
                self.assertFalse(action["real_order"])
                self.assertFalse(action["live_execution"])
                self.assertFalse(action["manual_m12_37_once"])
                self.assertIn("manual_m12_37_once", action["forbidden_operations"])

            rescue_rows = {row["strategy_id"]: row for row in result["rescue_strategy_rows"]}
            self.assertEqual(
                rescue_rows["M10-PA-008-broker-risk-cap-shadow"]["execution_state"],
                "wait_first_m13_rescue_ledger",
            )
            self.assertEqual(
                rescue_rows["M10-PA-001-m14-modify-20260522"]["execution_state"],
                "collect_rescue_ab_evidence",
            )
            parameter_states = [row["execution_state"] for row in result["parameter_gate_digest_rows"]]
            self.assertEqual(parameter_states.count("wait_fresh_refresh"), 2)
            self.assertEqual(parameter_states.count("continue_ab_collection_only"), 1)

            persisted = json.loads((root / "execution_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "execution_plan.md").read_text(encoding="utf-8")
            self.assertIn("M14 Objective Execution Plan", md)
            self.assertIn("approved_internal_sim_next_refresh", md)
            self.assertIn("Strategy evidence open/fresh/first-ledger/10-day/shadow gaps: `6/4/1/3/2`", md)
            self.assertIn("Manual M12.37 once-mode", result["plain_language_result"])

    def test_rejects_manual_once_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["manual_m12_37_once"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "manual_m12_37_once"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        objective_path = root / "objective.json"
        next_session_path = root / "next_session.json"
        rescue_path = root / "rescue.json"
        activation_path = root / "activation.json"
        external_path = root / "external.json"
        broker_path = root / "broker.json"
        config_path = root / "config.json"

        objective_path.write_text(
            json.dumps(
                {
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "manual_m12_37_once": False,
                    "summary": {
                        "objective_complete": False,
                        "objective_blockers": [
                            "rescue_evidence_sufficient_for_promotion",
                            "fresh_refresh_required_before_parameter_activation",
                        ],
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "approved_internal_sim_strategy_count": 2,
                        "approved_internal_sim_strategy_ids": ["M10-PA-004", "M10-PA-005"],
                        "strategy_evidence_open_gap_row_count": 6,
                        "strategy_evidence_requires_fresh_refresh_count": 4,
                        "strategy_evidence_wait_first_ledger_gap_count": 1,
                        "strategy_evidence_rescue_10_day_ab_gap_count": 3,
                        "strategy_evidence_shadow_review_gap_count": 2,
                    },
                    "objective_completion_assessment": {"completion_state": "not_complete"},
                }
            ),
            encoding="utf-8",
        )
        next_session_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "can_run_next_internal_sim_session": True,
                        "next_session_mode": "m12_47_supervised_fresh_refresh_only",
                        "approved_runtime_input_connected_count": 3,
                        "approved_runtime_input_count": 3,
                        "broker_watch_strategy_count": 1,
                        "broker_watch_strategy_ids": ["M10-PA-005"],
                        "manual_m12_37_once_allowed": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        rescue_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "rescue_runtime_strategy_count": 2,
                        "pending_evidence_strategy_ids": [
                            "M10-PA-001-m14-modify-20260522",
                            "M10-PA-008-broker-risk-cap-shadow",
                        ],
                        "m13_ledger_observed_strategy_count": 1,
                        "no_m13_ledger_evidence_count": 1,
                        "no_m13_ledger_evidence_strategy_ids": ["M10-PA-008-broker-risk-cap-shadow"],
                        "promotion_allowed_count": 0,
                        "evidence_ready_for_manual_review_count": 0,
                    },
                    "rows": [
                        {
                            "strategy_id": "M10-PA-001-m14-modify-20260522",
                            "parent_strategy_id": "M10-PA-001",
                            "evidence_status": "collecting_ab_evidence",
                            "promotion_blocked_reason": "needs_10_trading_days_ab_evidence",
                            "observed_trading_days_count": 1,
                            "remaining_ab_trading_days": 9,
                            "required_ab_trading_days": 10,
                            "latest_trading_date": "2026-05-22",
                            "m13_account_ledger_row_count": 1,
                            "m13_signal_ledger_row_count": 1,
                            "signal_count": 0,
                            "open_count": 0,
                            "risk_blocked_count": 0,
                            "runtime_ids": ["M10-PA-001-m14-modify-20260522-1d"],
                        },
                        {
                            "strategy_id": "M10-PA-008-broker-risk-cap-shadow",
                            "parent_strategy_id": "M10-PA-008",
                            "evidence_status": "no_m13_rescue_ledger_evidence_yet",
                            "promotion_blocked_reason": "no_m13_rescue_ledger_rows_yet",
                            "observed_trading_days_count": 0,
                            "remaining_ab_trading_days": 10,
                            "required_ab_trading_days": 10,
                            "latest_trading_date": "",
                            "m13_account_ledger_row_count": 0,
                            "m13_signal_ledger_row_count": 0,
                            "signal_count": 0,
                            "open_count": 0,
                            "risk_blocked_count": 0,
                            "runtime_ids": ["M10-PA-008-broker-risk-cap-shadow-1d"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        activation_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "gate_row_count": 3,
                        "waiting_for_fresh_refresh_count": 2,
                        "continue_ab_collection_count": 1,
                        "shadow_review_candidate_count": 0,
                        "implementation_mutation_allowed_count": 0,
                        "parameter_mutation_allowed_count": 0,
                        "fresh_refresh_observed": False,
                        "source_quote": "fallback_quotes_only",
                        "manual_m12_37_once_allowed": False,
                        "gate_state_counts": {
                            "waiting_for_m12_47_fresh_refresh": 2,
                            "continue_ab_collection_only": 1,
                        },
                    },
                    "gate_rows": [
                        self._gate_row(
                            "m14-param-gate-1",
                            "M10-PA-001-m14-modify-20260522",
                            "fresh_quote_gate_recheck",
                            "waiting_for_m12_47_fresh_refresh",
                            "blocked_until_fresh_refresh",
                        ),
                        self._gate_row(
                            "m14-param-gate-2",
                            "M10-PA-008-broker-risk-cap-shadow",
                            "ledger_path_mapping_audit",
                            "waiting_for_m12_47_fresh_refresh",
                            "shadow_runtime_wait_first_ledger",
                        ),
                        self._gate_row(
                            "m14-param-gate-3",
                            "M10-PA-011-ORB-R1",
                            "continue_ab_evidence_collection",
                            "continue_ab_collection_only",
                            "collect_more_ab_evidence",
                        ),
                    ],
                }
            ),
            encoding="utf-8",
        )
        external_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "external_reference_project_count": 2,
                        "mapped_rescue_row_count": 2,
                        "broker_blocker_reference_row_count": 1,
                        "copy_trading_allowed": False,
                    }
                }
            ),
            encoding="utf-8",
        )
        broker_path.write_text(
            json.dumps(
                {
                    "dry_run_ready_count": 1,
                    "blocked_count": 1,
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
                    "schema_version": "m14.objective-execution-plan.config.v1",
                    "stage": "M14.objective_execution_plan",
                    "project_stage_label": "fixture objective execution plan",
                    "inputs": {
                        "m14_objective_completion_audit": str(objective_path),
                        "m14_internal_sim_next_session_plan": str(next_session_path),
                        "m14_rescue_ab_evidence_tracker": str(rescue_path),
                        "m14_rescue_parameter_activation_gate": str(activation_path),
                        "m14_rescue_external_reference_map": str(external_path),
                        "m14_2_broker_readiness_plan": str(broker_path),
                    },
                    "outputs": {
                        "execution_plan_json": str(root / "execution_plan.json"),
                        "execution_plan_md": str(root / "execution_plan.md"),
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
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _gate_row(
        self,
        gate_row_id: str,
        strategy_id: str,
        experiment_family: str,
        gate_state: str,
        source_status: str,
    ) -> dict[str, object]:
        return {
            "gate_row_id": gate_row_id,
            "strategy_id": strategy_id,
            "parent_strategy_id": strategy_id.split("-m14")[0],
            "priority": "P0",
            "issue_type": "fixture",
            "experiment_family": experiment_family,
            "candidate_parameter_family": experiment_family,
            "required_readiness_family": "fresh_quote_recheck",
            "source_experiment_status": source_status,
            "gate_state": gate_state,
            "shadow_review_candidate": False,
            "implementation_mutation_allowed": False,
            "parameter_mutation_allowed": False,
            "next_action": "fixture next action",
            "runtime_ids": [f"{strategy_id}-runtime"],
        }


if __name__ == "__main__":
    unittest.main()
