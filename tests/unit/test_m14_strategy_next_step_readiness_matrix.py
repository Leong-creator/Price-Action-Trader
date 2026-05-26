from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_next_step_readiness_matrix_lib import (
    load_config,
    run_m14_strategy_next_step_readiness_matrix,
)


class M14StrategyNextStepReadinessMatrixTest(unittest.TestCase):
    def test_builds_readiness_matrix_and_blocks_legacy_history_metric_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_next_step_readiness_matrix(
                load_config(config_path),
                generated_at="2026-05-27T05:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.strategy-next-step-readiness-matrix.v1")
            self.assertEqual(result["summary"]["strategy_next_step_row_count"], 4)
            self.assertEqual(result["summary"]["approved_internal_sim_continue_count"], 1)
            self.assertEqual(result["summary"]["can_continue_internal_sim_now_count"], 1)
            self.assertEqual(result["summary"]["promotion_allowed_count"], 0)
            self.assertEqual(result["summary"]["final_discard_allowed_count"], 0)
            self.assertEqual(result["summary"]["parameter_activation_allowed_count"], 0)
            self.assertEqual(result["summary"]["broker_paper_start_allowed_count"], 0)
            self.assertEqual(result["summary"]["future_source_reextract_spec_prep_row_count"], 1)
            self.assertEqual(result["summary"]["future_source_reextract_spec_unblocked_count"], 0)
            self.assertEqual(result["summary"]["future_source_reextract_spec_pending_confirmation_count"], 8)
            self.assertEqual(result["summary"]["legacy_historical_profit_planning_input_count"], 0)
            self.assertTrue(result["summary"]["legacy_historical_profit_ignored"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["parameter_mutation"])
            self.assertFalse(result["legacy_historical_profit_planning_input"])

            rows = {row["strategy_id"]: row for row in result["matrix_rows"]}
            self.assertEqual(rows["M10-PA-004"]["current_bucket"], "approved_internal_sim_continue")
            self.assertEqual(rows["M10-PA-004"]["next_step_type"], "continue_next_internal_sim_refresh")
            self.assertTrue(rows["M10-PA-004"]["can_continue_internal_sim_now"])
            self.assertIn("m12_47_fresh_refresh", rows["M10-PA-004"]["required_next_evidence"])
            self.assertEqual(rows["M10-PA-011"]["next_step_type"], "collect_first_rescue_ledger")
            self.assertIn("first_m13_rescue_ledger", rows["M10-PA-011"]["required_next_evidence"])
            self.assertEqual(rows["M10-PA-001"]["next_step_type"], "complete_shadow_parameter_review")
            self.assertTrue(rows["M10-PA-001"]["parameter_shadow_spec_present"])
            self.assertTrue(rows["M10-PA-001"]["parameter_activation_waiting_for_fresh_refresh"])
            self.assertEqual(rows["M10-PA-003"]["current_bucket"], "source_review_or_plugin_research")
            self.assertEqual(rows["M10-PA-003"]["visual_question_pending_count"], 3)
            self.assertEqual(rows["M10-PA-003"]["visual_case_pending_count"], 5)
            self.assertEqual(rows["M10-PA-003"]["future_source_reextract_spec_prep_count"], 1)
            self.assertEqual(rows["M10-PA-003"]["future_source_reextract_spec_pending_confirmation_count"], 8)
            self.assertIn(
                "future_source_reextract_spec_manual_visual_confirmation",
                rows["M10-PA-003"]["required_next_evidence"],
            )
            for row in result["matrix_rows"]:
                self.assertFalse(row["promotion_allowed"])
                self.assertFalse(row["final_discard_allowed"])
                self.assertFalse(row["parameter_activation_allowed_now"])
                self.assertFalse(row["broker_paper_start_allowed"])
                self.assertFalse(row["legacy_historical_profit_planning_input"])

            policy = result["legacy_history_metric_exclusion"]
            self.assertFalse(policy["planning_input_allowed"])
            self.assertIn("historical_net_profit", policy["excluded_metrics"])
            persisted = json.loads((root / "matrix.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "matrix.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Next-Step Readiness Matrix", md)
            self.assertIn("Future source-reextract spec prep rows/drafts/unblocked/blocked/pending: `1/1/0/1/8`", md)
            self.assertIn("Legacy history metric planning inputs: `0`", md)
            self.assertIn("M10-PA-004", md)

    def test_rejects_legacy_history_metric_planning_input_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["legacy_historical_profit_planning_input"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "legacy_historical_profit_planning_input"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        decision_path = root / "decision.json"
        gap_path = root / "gap.json"
        burndown_path = root / "burndown.json"
        blocker_path = root / "blocker.json"
        visual_path = root / "visual.json"
        future_spec_path = root / "future_spec.json"
        rescue_path = root / "rescue.json"
        shadow_path = root / "shadow.json"
        config_path = root / "config.json"
        decision_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                        "ten_day_challenge_complete": True,
                    },
                    "ladder_rows": [
                        self._decision_row("M10-PA-004", "approved_internal_sim_continue", True),
                        self._decision_row("M10-PA-001", "rescue_ab_collect", False),
                        self._decision_row("M10-PA-011", "rebuild_detector_then_ab", False),
                        self._decision_row("M10-PA-003", "shadow_or_plugin_hold", False),
                    ],
                }
            ),
            encoding="utf-8",
        )
        gap_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "open_evidence_gap_row_count": 4,
                        "requires_m12_47_fresh_refresh_count": 3,
                    },
                    "gap_rows": [
                        self._gap_row("M10-PA-004", "approved_internal_sim_continue", "approved_wait_next_refresh", ["m12_47_fresh_refresh", "manual_m14_review"], True),
                        self._gap_row("M10-PA-001", "rescue_ab_collect", "wait_shadow_parameter_review", ["m12_47_fresh_refresh", "rescue_10_day_ab_window", "shadow_parameter_review"], False),
                        self._gap_row("M10-PA-011", "rebuild_detector_then_ab", "wait_first_rescue_ledger", ["first_m13_rescue_ledger", "rescue_10_day_ab_window"], False),
                        self._gap_row("M10-PA-003", "shadow_or_plugin_hold", "shadow_or_plugin_hold", ["independent_strategy_evidence_missing"], False),
                    ],
                }
            ),
            encoding="utf-8",
        )
        burndown_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "burndown_row_count": 4,
                        "open_evidence_gap_row_count": 4,
                        "requires_m12_47_fresh_refresh_count": 3,
                    },
                    "burndown_rows": [
                        self._burndown_row("M10-PA-004", "approved_internal_sim_continue", "approved_internal_sim_refresh", ["m12_47_fresh_refresh"], True, 1),
                        self._burndown_row("M10-PA-001", "rescue_ab_collect", "rescue_shadow_parameter_review", ["shadow_parameter_review"], False, 2),
                        self._burndown_row("M10-PA-011", "rebuild_detector_then_ab", "first_rescue_ledger", ["first_m13_rescue_ledger"], False, 3),
                        self._burndown_row("M10-PA-003", "shadow_or_plugin_hold", "shadow_plugin_research", ["source_visual_confirmation"], False, 4),
                    ],
                }
            ),
            encoding="utf-8",
        )
        blocker_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                        "ten_day_challenge_complete": True,
                        "parameter_activation_allowed_count": 0,
                        "broker_paper_start_allowed_count": 0,
                        "legacy_historical_profit_ignored": True,
                        "can_run_next_internal_sim_session": True,
                        "can_start_broker_paper": False,
                        "post_refresh_fresh_refresh_observed": False,
                        "post_refresh_source_quote": "fallback_quotes_only",
                        "post_refresh_waiting_count": 3,
                    },
                    "legacy_history_metric_exclusion": {
                        "excluded_metrics": ["historical_net_profit", "historical_return_percent"],
                        "excluded_from_decisions": ["strategy_promotion", "parameter_activation"],
                    },
                }
            ),
            encoding="utf-8",
        )
        visual_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_visual_confirmation_response_gate_row_count": 1,
                        "question_response_pending_count": 3,
                        "case_response_pending_count": 5,
                        "future_spec_unblocked_count": 0,
                    },
                    "response_gate_rows": [
                        {
                            "strategy_id": "M10-PA-003",
                            "question_response_pending_count": 3,
                            "case_response_pending_count": 5,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        future_spec_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "future_source_reextract_spec_prep_row_count": 1,
                        "conditional_spec_draft_count": 1,
                        "future_spec_unblocked_count": 0,
                        "blocked_until_manual_visual_confirmation_count": 1,
                        "manual_confirmation_pending_count": 8,
                        "legacy_historical_profit_planning_input_count": 0,
                    },
                    "future_source_reextract_spec_prep_rows": [
                        {
                            "strategy_id": "M10-PA-003",
                            "draft_state": "blocked_until_manual_visual_confirmation",
                            "manual_visual_confirmation_complete": False,
                            "manual_confirmation_pending_count": 8,
                            "legacy_historical_profit_planning_input": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        rescue_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "rescue_runtime_strategy_count": 2,
                        "m13_ledger_observed_strategy_count": 1,
                        "no_m13_ledger_evidence_count": 1,
                        "promotion_allowed_count": 0,
                    },
                    "rows": [
                        {
                            "strategy_id": "M10-PA-001-m14-modify",
                            "parent_strategy_id": "M10-PA-001",
                            "remaining_ab_trading_days": 7,
                            "observed_trading_days_count": 3,
                        },
                        {
                            "strategy_id": "M10-PA-011-ORB-R1",
                            "parent_strategy_id": "M10-PA-011",
                            "evidence_status": "no_m13_ledger_evidence",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        shadow_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "spec_row_count": 1,
                        "candidate_variant_count": 1,
                        "waiting_for_fresh_refresh_count": 1,
                    },
                    "spec_rows": [
                        {
                            "strategy_id": "M10-PA-001-m14-modify",
                            "parent_strategy_id": "M10-PA-001",
                            "spec_state": "waiting_for_fresh_refresh",
                            "activation_gate_state": "waiting_for_m12_47_fresh_refresh",
                            "variant_count": 1,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-next-step-readiness-matrix.config.v1",
                    "stage": "M14.strategy_next_step_readiness_matrix",
                    "inputs": {
                        "m14_strategy_decision_ladder": str(decision_path),
                        "m14_strategy_evidence_gap_matrix": str(gap_path),
                        "m14_strategy_evidence_gap_burndown": str(burndown_path),
                        "m14_objective_blocker_burndown": str(blocker_path),
                        "m14_strategy_source_visual_confirmation_response_gate": str(visual_path),
                        "m14_strategy_future_source_reextract_spec_prep": str(future_spec_path),
                        "m14_rescue_ab_evidence_tracker": str(rescue_path),
                        "m14_rescue_parameter_shadow_spec": str(shadow_path),
                    },
                    "outputs": {
                        "next_step_matrix_json": str(root / "matrix.json"),
                        "next_step_matrix_md": str(root / "matrix.md"),
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

    def _decision_row(self, strategy_id: str, route_category: str, can_advance: bool) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "display_name": f"{strategy_id} fixture",
            "route_rank": 1 if can_advance else 2,
            "route_category": route_category,
            "decision": "promote" if can_advance else "rescue",
            "ladder_state": "approved_continue_internal_sim" if can_advance else "continue_rescue_with_shadow_specs",
            "completed_trading_days": 10 if can_advance else 3,
            "can_advance_next_step": can_advance,
            "can_promote_now": False,
            "continue_rescue": not can_advance,
            "final_discard_allowed": False,
        }

    def _gap_row(
        self,
        strategy_id: str,
        route_category: str,
        gap_state: str,
        missing: list[str],
        can_continue: bool,
    ) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "display_name": f"{strategy_id} fixture",
            "route_rank": 1 if can_continue else 2,
            "route_category": route_category,
            "gap_state": gap_state,
            "missing_evidence_categories": missing,
            "required_artifacts": [f"{strategy_id}.json"],
            "can_continue_internal_sim_now": can_continue,
            "can_promote_now": False,
            "continue_rescue": not can_continue,
            "final_discard_allowed": False,
        }

    def _burndown_row(
        self,
        strategy_id: str,
        route_category: str,
        burn_down_lane: str,
        next_evidence: list[str],
        can_continue: bool,
        sequence_rank: int,
    ) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "display_name": f"{strategy_id} fixture",
            "sequence_rank": sequence_rank,
            "route_category": route_category,
            "burn_down_lane": burn_down_lane,
            "next_evidence_to_collect": next_evidence,
            "blocked_by": next_evidence,
            "allowed_operations": ["artifact_review", "m12_47_supervised_refresh_review"],
            "can_continue_internal_sim_now": can_continue,
            "can_promote_now": False,
            "continue_rescue": not can_continue,
            "final_discard_allowed": False,
            "activation_gate_row_count": 1 if strategy_id == "M10-PA-001" else 0,
            "activation_waiting_for_fresh_refresh_count": 1 if strategy_id == "M10-PA-001" else 0,
        }


if __name__ == "__main__":
    unittest.main()
