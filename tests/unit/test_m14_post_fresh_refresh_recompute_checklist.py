from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_post_fresh_refresh_recompute_checklist_lib import (
    load_config,
    run_m14_post_fresh_refresh_recompute_checklist,
)


class M14PostFreshRefreshRecomputeChecklistTest(unittest.TestCase):
    def test_builds_safe_recompute_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_post_fresh_refresh_recompute_checklist(
                load_config(config_path),
                generated_at="2026-05-27T00:10:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.post-fresh-refresh-recompute-checklist.v1")
            self.assertFalse(result["summary"]["fresh_refresh_observed"])
            self.assertEqual(result["summary"]["source_quote"], "fallback_quotes_only")
            self.assertEqual(result["summary"]["recompute_step_count"], 23)
            self.assertEqual(result["summary"]["m14_script_step_count"], 22)
            self.assertEqual(result["summary"]["acceptance_gate_count"], 7)
            self.assertTrue(result["summary"]["two_pass_stabilization_required"])
            self.assertEqual(result["summary"]["rescue_no_m13_ledger_evidence_count"], 2)
            self.assertEqual(result["summary"]["parameter_shadow_spec_candidate_variant_count"], 4)
            self.assertEqual(result["summary"]["strategy_decision_final_discard_allowed_count"], 0)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_count"], 0)
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["live_execution"])

            steps = {row["step_id"]: row for row in result["recompute_steps"]}
            self.assertEqual(
                steps["wait_for_m12_47_supervisor_refresh"]["step_type"],
                "wait",
            )
            self.assertEqual(
                steps["review_post_refresh_outcomes"]["command"],
                "python scripts/run_m14_rescue_post_refresh_outcome_review.py",
            )
            self.assertEqual(
                steps["objective_audit_after_ladder"]["command"],
                "python scripts/run_m14_objective_completion_audit.py",
            )
            self.assertEqual(
                steps["strategy_evidence_gap_matrix_refresh"]["command"],
                "python scripts/run_m14_strategy_evidence_gap_matrix.py",
            )
            self.assertEqual(
                steps["strategy_evidence_gap_burndown_refresh"]["command"],
                "python scripts/run_m14_strategy_evidence_gap_burndown.py",
            )
            self.assertEqual(
                steps["strategy_pre_refresh_review_packet_refresh"]["command"],
                "python scripts/run_m14_strategy_pre_refresh_review_packet.py",
            )
            for row in result["recompute_steps"]:
                self.assertNotIn("run_m12_37_intraday_auto_loop.py", row["command"])
                self.assertFalse(row["manual_m12_37_once_allowed"])
                self.assertFalse(row["broker_connection"])
                self.assertFalse(row["real_order"])
                self.assertFalse(row["live_execution"])
                self.assertFalse(row["parameter_mutation"])

            gates = {row["gate_id"]: row for row in result["acceptance_gates"]}
            self.assertEqual(gates["fresh_refresh_source_gate"]["state"], "waiting")
            self.assertEqual(gates["no_final_discard_without_rescue_exhaustion_gate"]["state"], "passed")
            self.assertEqual(gates["broker_live_boundary_gate"]["state"], "passed")

            persisted = json.loads((root / "checklist.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "checklist.md").read_text(encoding="utf-8")
            self.assertIn("M14 Post-Fresh-Refresh Recompute Checklist", md)
            self.assertIn("M14 read-only script steps: `22`", md)
            self.assertIn("Final discard allowed: `0`", md)

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
        next_session_path = root / "next_session.json"
        post_refresh_path = root / "post_refresh.json"
        rescue_ab_path = root / "rescue_ab.json"
        next_refresh_path = root / "next_refresh.json"
        parameter_queue_path = root / "parameter_queue.json"
        activation_gate_path = root / "activation_gate.json"
        shadow_spec_path = root / "shadow_spec.json"
        decision_ladder_path = root / "decision_ladder.json"
        objective_audit_path = root / "objective_audit.json"
        objective_execution_path = root / "objective_execution.json"
        config_path = root / "config.json"

        next_session_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "can_run_next_internal_sim_session": True,
                        "next_session_mode": "m12_47_supervised_fresh_refresh_only",
                        "approved_runtime_input_connected_count": 4,
                        "approved_runtime_input_count": 4,
                    },
                }
            ),
            encoding="utf-8",
        )
        post_refresh_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "fresh_refresh_observed": False,
                        "source_quote": "fallback_quotes_only",
                        "waiting_count": 13,
                        "passed_count": 0,
                        "failed_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        rescue_ab_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "rescue_runtime_strategy_count": 11,
                        "m13_ledger_observed_strategy_count": 9,
                        "no_m13_ledger_evidence_count": 2,
                        "promotion_allowed_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        next_refresh_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "watch_rows": 13,
                        "parameter_change_allowed_now_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        parameter_queue_path.write_text(
            json.dumps({"summary": {"experiment_row_count": 4}}),
            encoding="utf-8",
        )
        activation_gate_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "gate_row_count": 4,
                        "waiting_for_fresh_refresh_count": 3,
                        "shadow_review_candidate_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        shadow_spec_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "spec_row_count": 4,
                        "candidate_variant_count": 4,
                    }
                }
            ),
            encoding="utf-8",
        )
        decision_ladder_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "m14_trading_date": "2026-05-22",
                        "strategy_ladder_row_count": 5,
                        "final_discard_allowed_count": 0,
                        "promotion_candidate_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        objective_audit_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "objective_complete": False,
                        "blocked_count": 3,
                        "in_progress_count": 2,
                    },
                }
            ),
            encoding="utf-8",
        )
        objective_execution_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "execution_action_count": 7,
                        "waiting_for_fresh_refresh_action_count": 5,
                    }
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.post-fresh-refresh-recompute-checklist.config.v1",
                    "stage": "M14.post_fresh_refresh_recompute_checklist",
                    "project_stage_label": "fixture post-refresh checklist",
                    "inputs": {
                        "m14_internal_sim_next_session_plan": str(next_session_path),
                        "m14_rescue_post_refresh_outcome_review": str(post_refresh_path),
                        "m14_rescue_ab_evidence_tracker": str(rescue_ab_path),
                        "m14_rescue_next_refresh_readiness": str(next_refresh_path),
                        "m14_rescue_parameter_experiment_queue": str(parameter_queue_path),
                        "m14_rescue_parameter_activation_gate": str(activation_gate_path),
                        "m14_rescue_parameter_shadow_spec": str(shadow_spec_path),
                        "m14_strategy_decision_ladder": str(decision_ladder_path),
                        "m14_objective_completion_audit": str(objective_audit_path),
                        "m14_objective_execution_plan": str(objective_execution_path),
                    },
                    "outputs": {
                        "checklist_json": str(root / "checklist.json"),
                        "checklist_md": str(root / "checklist.md"),
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


if __name__ == "__main__":
    unittest.main()
