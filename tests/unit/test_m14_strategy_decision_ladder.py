from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_decision_ladder_lib import load_config, run_m14_strategy_decision_ladder


class M14StrategyDecisionLadderTest(unittest.TestCase):
    def test_builds_strategy_ladder_without_discarding_rescue_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_decision_ladder(
                load_config(config_path),
                generated_at="2026-05-27T02:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.strategy-decision-ladder.v1")
            self.assertEqual(result["summary"]["strategy_ladder_row_count"], 4)
            self.assertEqual(result["summary"]["approved_next_step_count"], 1)
            self.assertEqual(result["summary"]["rescue_continue_count"], 2)
            self.assertEqual(result["summary"]["shadow_or_plugin_hold_count"], 1)
            self.assertEqual(result["summary"]["promotion_candidate_count"], 0)
            self.assertEqual(result["summary"]["final_discard_allowed_count"], 0)
            self.assertEqual(result["summary"]["shadow_spec_strategy_count"], 2)
            self.assertEqual(result["summary"]["candidate_variant_count"], 3)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["m13_registry_mutation"])
            self.assertFalse(result["m12_account_specs_mutation"])
            self.assertFalse(result["broker_readiness_status_mutation"])
            self.assertFalse(result["parameter_mutation"])

            rows = {row["strategy_id"]: row for row in result["ladder_rows"]}
            self.assertTrue(rows["M10-PA-004"]["can_advance_next_step"])
            self.assertEqual(rows["M10-PA-004"]["ladder_state"], "approved_continue_internal_sim")
            self.assertEqual(rows["M10-PA-001"]["ladder_state"], "continue_rescue_with_shadow_specs")
            self.assertIn("rescue_10_day_ab_window_incomplete", rows["M10-PA-001"]["final_discard_blockers"])
            self.assertEqual(rows["M10-PA-011"]["ladder_state"], "wait_first_rescue_ledger")
            self.assertIn("first_m13_rescue_ledger_missing", rows["M10-PA-011"]["final_discard_blockers"])
            self.assertEqual(rows["M10-PA-003"]["ladder_state"], "shadow_or_plugin_hold")
            for row in result["ladder_rows"]:
                self.assertFalse(row["final_discard_allowed"])
                self.assertFalse(row["broker_connection"])
                self.assertFalse(row["manual_m12_37_once"])

            persisted = json.loads((root / "ladder.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "ladder.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Decision Ladder", md)
            self.assertIn("Final discard allowed: `0`", md)
            self.assertIn("approved_continue_internal_sim", md)

    def test_rejects_unsafe_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["broker_connection"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "broker_connection"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        goal_path = root / "goal.json"
        next_session_path = root / "next_session.json"
        rescue_path = root / "rescue.json"
        shadow_path = root / "shadow.json"
        external_path = root / "external.json"
        objective_path = root / "objective.json"
        config_path = root / "config.json"

        goal_path.write_text(
            json.dumps(
                {
                    "project_stage_label": "M14 fixture stage",
                    "m14_trading_date": "2026-05-22",
                    "challenge": {
                        "ten_day_challenge_complete": True,
                        "challenge_progress_label": "10/10",
                    },
                    "strategy_action_matrix": [
                        self._strategy_row("M10-PA-004", "continue_internal_simulation", "promote", False),
                        self._strategy_row("M10-PA-001", "collect_rescue_ab_evidence", "modify", True),
                        self._strategy_row("M10-PA-011", "rebuild_detector_ab_evidence", "reject", True),
                        self._strategy_row("M10-PA-003", "continue_shadow_or_plugin_review", "continue_testing", False),
                    ],
                }
            ),
            encoding="utf-8",
        )
        next_session_path.write_text(
            json.dumps(
                {
                    "strategy_session_rows": [
                        {
                            "strategy_id": "M10-PA-004",
                            "session_action": "continue_internal_simulated_account_testing",
                            "broker_dry_run_blocked_count": 0,
                            "linked_next_refresh_watch_count": 0,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        rescue_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "rescue_runtime_strategy_count": 2,
                        "promotion_allowed_count": 0,
                    },
                    "rows": [
                        {
                            "strategy_id": "M10-PA-001-m14-modify-20260522",
                            "parent_strategy_id": "M10-PA-001",
                            "evidence_status": "collecting_ab_evidence",
                            "can_promote": False,
                            "ready_for_manual_review": False,
                            "meets_min_ab_trading_days": False,
                            "observed_trading_days_count": 1,
                            "remaining_ab_trading_days": 9,
                        },
                        {
                            "strategy_id": "M10-PA-011-ORB-R1",
                            "parent_strategy_id": "M10-PA-011",
                            "evidence_status": "no_m13_rescue_ledger_evidence_yet",
                            "can_promote": False,
                            "ready_for_manual_review": False,
                            "meets_min_ab_trading_days": False,
                            "observed_trading_days_count": 0,
                            "remaining_ab_trading_days": 10,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        shadow_path.write_text(
            json.dumps(
                {
                    "spec_rows": [
                        {
                            "strategy_id": "M10-PA-001-m14-modify-20260522",
                            "parent_strategy_id": "M10-PA-001",
                            "spec_state": "fresh_recheck_spec_ready_wait_refresh",
                            "variant_count": 1,
                        },
                        {
                            "strategy_id": "M10-PA-001-extra-shadow",
                            "parent_strategy_id": "M10-PA-001",
                            "spec_state": "target_stop_shadow",
                            "variant_count": 1,
                        },
                        {
                            "strategy_id": "M10-PA-011-ORB-R1",
                            "parent_strategy_id": "M10-PA-011",
                            "spec_state": "wait_first_ledger_before_parameter_decision",
                            "variant_count": 1,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        external_path.write_text(
            json.dumps(
                {
                    "rescue_reference_rows": [
                        {
                            "strategy_id": "M10-PA-001",
                            "external_reference_pattern_ids": ["ai_trader_shadow_signal_scoreboard"],
                            "local_review_lanes": ["shadow_signal_scoreboard", "decision_log_audit"],
                        }
                    ],
                    "broker_blocker_reference_rows": [],
                }
            ),
            encoding="utf-8",
        )
        objective_path.write_text(
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
                    "schema_version": "m14.strategy-decision-ladder.config.v1",
                    "stage": "M14.strategy_decision_ladder",
                    "inputs": {
                        "m14_goal_readiness_report": str(goal_path),
                        "m14_internal_sim_next_session_plan": str(next_session_path),
                        "m14_rescue_ab_evidence_tracker": str(rescue_path),
                        "m14_rescue_parameter_shadow_spec": str(shadow_path),
                        "m14_rescue_external_reference_map": str(external_path),
                        "m14_objective_execution_plan": str(objective_path),
                    },
                    "outputs": {
                        "decision_ladder_json": str(root / "ladder.json"),
                        "decision_ladder_md": str(root / "ladder.md"),
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

    def _strategy_row(
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
        }


if __name__ == "__main__":
    unittest.main()
