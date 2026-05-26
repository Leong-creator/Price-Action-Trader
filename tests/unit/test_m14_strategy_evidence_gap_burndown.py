from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_evidence_gap_burndown_lib import (
    load_config,
    run_m14_strategy_evidence_gap_burndown,
)


class M14StrategyEvidenceGapBurndownTest(unittest.TestCase):
    def test_builds_ordered_burndown_without_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_evidence_gap_burndown(
                load_config(config_path),
                generated_at="2026-05-27T04:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.strategy-evidence-gap-burndown.v1")
            self.assertEqual(result["summary"]["burndown_row_count"], 5)
            self.assertEqual(result["summary"]["p0_row_count"], 3)
            self.assertEqual(result["summary"]["p1_row_count"], 1)
            self.assertEqual(result["summary"]["p2_row_count"], 1)
            self.assertEqual(result["summary"]["ready_for_internal_sim_refresh_count"], 1)
            self.assertEqual(result["summary"]["first_ledger_watch_row_count"], 1)
            self.assertEqual(result["summary"]["rescue_ab_collection_row_count"], 3)
            self.assertEqual(result["summary"]["shadow_review_wait_row_count"], 1)
            self.assertEqual(result["summary"]["pre_refresh_review_available_count"], 4)
            self.assertEqual(result["summary"]["promotion_candidate_count"], 0)
            self.assertEqual(result["summary"]["final_discard_allowed_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["parameter_mutation"])

            rows = {row["strategy_id"]: row for row in result["burndown_rows"]}
            self.assertEqual(rows["M10-PA-004"]["burn_down_lane"], "approved_internal_sim_refresh")
            self.assertEqual(rows["M10-PA-004"]["priority"], "P0")
            self.assertEqual(rows["M10-PA-011"]["burn_down_lane"], "first_rescue_ledger")
            self.assertIn("first_rescue_specific_ledger_missing", rows["M10-PA-011"]["blocked_by"])
            self.assertEqual(rows["M10-PA-004-MBF"]["priority"], "P1")
            self.assertEqual(rows["M10-PA-003"]["priority"], "P2")
            self.assertIn("shadow_parameter_review_not_open", rows["M10-PA-001"]["blocked_by"])
            for row in result["burndown_rows"]:
                self.assertFalse(row["final_discard_allowed"])
                self.assertFalse(row["parameter_mutation"])
                self.assertFalse(row["manual_m12_37_once"])

            persisted = json.loads((root / "burndown.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "burndown.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Evidence Gap Burndown", md)
            self.assertIn("Priority P0/P1/P2: `3/1/1`", md)
            self.assertIn("first_rescue_ledger", md)

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
        gap_path = root / "gap_matrix.json"
        execution_path = root / "execution.json"
        experiment_path = root / "experiment.json"
        activation_path = root / "activation.json"
        external_path = root / "external.json"
        config_path = root / "config.json"
        gap_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                        "open_evidence_gap_row_count": 5,
                    },
                    "gap_rows": [
                        self._gap_row("M10-PA-004", "approved_internal_sim_continue", "approved_wait_next_refresh", ["m12_47_fresh_refresh", "manual_m14_review"], True),
                        self._gap_row("M10-PA-001", "rescue_ab_collect", "wait_shadow_parameter_review", ["m12_47_fresh_refresh", "rescue_10_day_ab_window", "shadow_parameter_review", "manual_m14_review"], False),
                        self._gap_row("M10-PA-011", "rebuild_detector_then_ab", "wait_first_rescue_ledger", ["m12_47_fresh_refresh", "first_m13_rescue_ledger", "rescue_10_day_ab_window", "manual_m14_review"], False),
                        self._gap_row("M10-PA-004-MBF", "parallel_ab_collect", "collect_rescue_ab_evidence", ["rescue_10_day_ab_window", "manual_m14_review"], False),
                        self._gap_row("M10-PA-003", "shadow_or_plugin_hold", "shadow_or_plugin_hold", ["independent_strategy_evidence_missing", "manual_m14_review"], False),
                    ],
                }
            ),
            encoding="utf-8",
        )
        execution_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "execution_action_count": 7,
                        "p0_action_count": 5,
                        "waiting_for_fresh_refresh_action_count": 5,
                    },
                    "execution_actions": [
                        {
                            "action_id": "approved_internal_sim_next_refresh",
                            "strategy_ids": ["M10-PA-004"],
                        },
                        {
                            "action_id": "rescue_first_ledger_watch",
                            "strategy_ids": ["M10-PA-011-ORB-R1"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        experiment_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "experiment_row_count": 2,
                        "allowed_now_count": 0,
                    },
                    "experiment_rows": [
                        {
                            "strategy_id": "M10-PA-001-m14-modify-20260522",
                            "parent_strategy_id": "M10-PA-001",
                            "experiment_family": "fresh_quote_gate_recheck",
                        },
                        {
                            "strategy_id": "M10-PA-011-ORB-R1",
                            "parent_strategy_id": "M10-PA-011",
                            "experiment_family": "ledger_path_mapping_audit",
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
                        "gate_row_count": 2,
                        "shadow_review_candidate_count": 0,
                        "waiting_for_fresh_refresh_count": 2,
                    },
                    "gate_rows": [
                        {
                            "strategy_id": "M10-PA-001-m14-modify-20260522",
                            "parent_strategy_id": "M10-PA-001",
                            "gate_state": "waiting_for_m12_47_fresh_refresh",
                            "shadow_review_candidate": False,
                        },
                        {
                            "strategy_id": "M10-PA-011-ORB-R1",
                            "parent_strategy_id": "M10-PA-011",
                            "gate_state": "waiting_for_m12_47_fresh_refresh",
                            "shadow_review_candidate": False,
                        },
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
                    }
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-evidence-gap-burndown.config.v1",
                    "stage": "M14.strategy_evidence_gap_burndown",
                    "inputs": {
                        "m14_strategy_evidence_gap_matrix": str(gap_path),
                        "m14_objective_execution_plan": str(execution_path),
                        "m14_rescue_parameter_experiment_queue": str(experiment_path),
                        "m14_rescue_parameter_activation_gate": str(activation_path),
                        "m14_rescue_external_reference_map": str(external_path),
                    },
                    "outputs": {
                        "burndown_json": str(root / "burndown.json"),
                        "burndown_md": str(root / "burndown.md"),
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
            "display_name": strategy_id,
            "route_rank": 1,
            "route_category": route_category,
            "gap_state": gap_state,
            "missing_evidence_categories": missing,
            "open_evidence_gap_count": len(missing),
            "requires_m12_47_fresh_refresh": "m12_47_fresh_refresh" in missing,
            "can_continue_internal_sim_now": can_continue,
            "continue_rescue": route_category in {"rescue_ab_collect", "parallel_ab_collect", "rebuild_detector_then_ab"},
            "manual_review_ready": False,
            "broker_watch": False,
            "rescue_ab_observed_days_max": 1 if route_category != "approved_internal_sim_continue" else 0,
            "rescue_ab_remaining_days_min": 9 if route_category != "approved_internal_sim_continue" else 0,
            "candidate_variant_count": 1 if "shadow_parameter_review" in missing else 0,
            "rescue_runtime_strategy_ids": [f"{strategy_id}-m14-modify-20260522"]
            if route_category != "approved_internal_sim_continue"
            else [],
        }
