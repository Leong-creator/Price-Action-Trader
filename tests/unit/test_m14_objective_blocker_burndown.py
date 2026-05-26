from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_objective_blocker_burndown_lib import (
    load_config,
    run_m14_objective_blocker_burndown,
)


class M14ObjectiveBlockerBurndownTest(unittest.TestCase):
    def test_builds_objective_burndown_and_excludes_legacy_profit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_objective_blocker_burndown(
                load_config(config_path),
                generated_at="2026-05-27T04:30:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.objective-blocker-burndown.v1")
            self.assertEqual(result["summary"]["blocker_burndown_row_count"], 7)
            self.assertEqual(result["summary"]["p0_blocker_count"], 4)
            self.assertEqual(result["summary"]["p1_blocker_count"], 3)
            self.assertEqual(result["summary"]["future_source_reextract_spec_prep_row_count"], 2)
            self.assertEqual(result["summary"]["future_source_reextract_spec_prep_unblocked_count"], 0)
            self.assertEqual(result["summary"]["future_source_reextract_spec_prep_pending_confirmation_count"], 16)
            self.assertEqual(result["summary"]["legacy_historical_profit_planning_input_count"], 0)
            self.assertTrue(result["summary"]["legacy_historical_profit_ignored"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["parameter_mutation"])
            self.assertFalse(result["legacy_historical_profit_planning_input"])

            rows = {row["blocker_id"]: row for row in result["blocker_rows"]}
            self.assertEqual(
                rows["legacy_historical_profit_contamination_guardrail"]["state"],
                "active_guardrail",
            )
            self.assertIn(
                "historical_net_profit",
                rows["legacy_historical_profit_contamination_guardrail"]["excluded_metrics"],
            )
            self.assertEqual(
                rows["fresh_refresh_required_before_parameter_activation"]["state"],
                "waiting_for_m12_47_fresh_refresh",
            )
            self.assertEqual(rows["rescue_first_ledger_gap"]["priority"], "P0")
            self.assertEqual(rows["source_visual_manual_confirmation_gap"]["priority"], "P1")
            for row in result["blocker_rows"]:
                self.assertFalse(row["can_promote_strategy_now"])
                self.assertFalse(row["can_discard_strategy_now"])
                self.assertFalse(row["can_activate_parameter_now"])
                self.assertFalse(row["can_start_broker_paper"])
                self.assertFalse(row["legacy_historical_profit_planning_input"])

            metric_policy = result["legacy_history_metric_exclusion"]
            self.assertIn("strategy_promotion", metric_policy["excluded_from_decisions"])
            self.assertIn("m13_account_operation_ledger", metric_policy["replacement_evidence_sources"])

            persisted = json.loads((root / "blocker.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "blocker.md").read_text(encoding="utf-8")
            self.assertIn("M14 Objective Blocker Burndown", md)
            self.assertIn("Future source-reextract spec prep rows/drafts/unblocked/blocked/pending: `2/2/0/2/16`", md)
            self.assertIn("Legacy history metric planning inputs: `0`", md)
            self.assertIn("historical_net_profit", md)

    def test_rejects_legacy_history_metric_planning_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["legacy_historical_profit_planning_input"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "legacy_historical_profit_planning_input"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        objective_path = root / "objective.json"
        stage_path = root / "stage.json"
        evidence_path = root / "evidence.json"
        visual_path = root / "visual.json"
        future_spec_path = root / "future_spec.json"
        config_path = root / "config.json"
        objective_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "objective_complete": False,
                        "objective_blockers": [
                            "rescue_evidence_sufficient_for_promotion",
                            "fresh_refresh_required_before_parameter_activation",
                        ],
                        "requirement_count": 13,
                        "proven_count": 4,
                        "blocked_count": 3,
                        "in_progress_count": 3,
                        "guardrail_count": 3,
                        "ten_day_challenge_complete": True,
                        "challenge_progress_label": "10/10",
                        "approved_internal_sim_strategy_count": 3,
                        "approved_internal_sim_strategy_ids": ["M10-PA-004", "M10-PA-005", "M10-PA-008"],
                        "approved_runtime_input_connected_count": 4,
                        "approved_runtime_input_count": 4,
                        "rescue_runtime_strategy_count": 11,
                        "rescue_m13_ledger_observed_strategy_count": 9,
                        "rescue_no_m13_ledger_evidence_count": 2,
                        "rescue_promotion_allowed_count": 0,
                        "strategy_evidence_open_gap_row_count": 20,
                        "strategy_evidence_requires_fresh_refresh_count": 12,
                        "strategy_evidence_wait_first_ledger_gap_count": 2,
                        "strategy_evidence_rescue_10_day_ab_gap_count": 10,
                        "strategy_evidence_shadow_review_gap_count": 11,
                        "parameter_experiment_row_count": 14,
                        "parameter_activation_waiting_for_fresh_refresh_count": 13,
                        "parameter_activation_shadow_review_candidate_count": 0,
                        "parameter_activation_parameter_mutation_allowed_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        stage_path.write_text(
            json.dumps(
                {
                    "m14_trading_date": "2026-05-22",
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "can_run_next_internal_sim_session": True,
                        "next_session_mode": "m12_47_supervised_fresh_refresh_only",
                        "post_refresh_fresh_refresh_observed": False,
                        "post_refresh_source_quote": "fallback_quotes_only",
                        "post_refresh_waiting_count": 13,
                        "broker_dry_run_ready_count": 5,
                        "broker_dry_run_blocked_count": 3,
                    },
                }
            ),
            encoding="utf-8",
        )
        evidence_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "burndown_row_count": 20,
                        "p0_row_count": 12,
                        "p1_row_count": 1,
                        "p2_row_count": 7,
                        "pre_refresh_review_available_count": 19,
                    }
                }
            ),
            encoding="utf-8",
        )
        visual_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_visual_confirmation_response_gate_row_count": 2,
                        "manual_visual_confirmation_review_pack_ready": True,
                        "review_pack_question_count": 6,
                        "review_pack_case_asset_exists_count": 10,
                        "review_pack_case_asset_count": 10,
                        "question_response_pending_count": 6,
                        "case_response_pending_count": 10,
                        "future_spec_unblocked_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        future_spec_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "future_source_reextract_spec_prep_row_count": 2,
                        "conditional_spec_draft_count": 2,
                        "future_spec_unblocked_count": 0,
                        "blocked_until_manual_visual_confirmation_count": 2,
                        "manual_confirmation_pending_count": 16,
                        "legacy_historical_profit_planning_input_count": 0,
                    }
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.objective-blocker-burndown.config.v1",
                    "stage": "M14.objective_blocker_burndown",
                    "inputs": {
                        "m14_objective_completion_audit": str(objective_path),
                        "m14_project_stage_assessment": str(stage_path),
                        "m14_strategy_evidence_gap_burndown": str(evidence_path),
                        "m14_strategy_source_visual_confirmation_response_gate": str(visual_path),
                        "m14_strategy_future_source_reextract_spec_prep": str(future_spec_path),
                    },
                    "outputs": {
                        "blocker_burndown_json": str(root / "blocker.json"),
                        "blocker_burndown_md": str(root / "blocker.md"),
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


if __name__ == "__main__":
    unittest.main()
