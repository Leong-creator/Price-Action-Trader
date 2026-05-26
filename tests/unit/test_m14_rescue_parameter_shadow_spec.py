from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_parameter_shadow_spec_lib import (
    load_config,
    run_m14_rescue_parameter_shadow_spec,
)


class M14RescueParameterShadowSpecTest(unittest.TestCase):
    def test_builds_shadow_specs_without_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_rescue_parameter_shadow_spec(
                load_config(config_path),
                generated_at="2026-05-27T01:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-parameter-shadow-spec.v1")
            self.assertEqual(result["summary"]["spec_row_count"], 6)
            self.assertEqual(result["summary"]["candidate_variant_count"], 6)
            self.assertEqual(result["summary"]["waiting_for_fresh_refresh_count"], 5)
            self.assertEqual(result["summary"]["wait_first_ledger_count"], 1)
            self.assertEqual(result["summary"]["continue_ab_only_count"], 1)
            self.assertEqual(result["summary"]["target_stop_shadow_variant_count"], 1)
            self.assertEqual(result["summary"]["broker_quantity_cap_variant_count"], 1)
            self.assertEqual(result["summary"]["broker_rule_shadow_variant_count"], 1)
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

            rows = {row["experiment_family"]: row for row in result["spec_rows"]}
            target_variant = rows["target_stop_reward_geometry_shadow"]["candidate_variants"][0]
            self.assertEqual(target_variant["variant_id"], "risk_normalized_1_0r")
            self.assertEqual(target_variant["parameter_values"]["target_rule"], "entry_plus_1_0r")
            self.assertEqual(target_variant["parameter_values"]["best_variant_candidate_count"], 12)
            quantity_variant = rows["quantity_cap_shadow"]["candidate_variants"][0]
            self.assertEqual(quantity_variant["parameter_values"]["proposed_quantity"], "5.2083")
            self.assertEqual(quantity_variant["parameter_values"]["proposed_risk_amount"], "100")
            cooldown_variant = rows["cooldown_quality_veto_shadow"]["candidate_variants"][0]
            self.assertEqual(cooldown_variant["parameter_values"]["rule_family"], "cooldown_quality_veto")
            self.assertEqual(
                rows["ledger_path_mapping_audit"]["spec_state"],
                "wait_first_ledger_before_parameter_decision",
            )
            self.assertEqual(
                rows["continue_ab_evidence_collection"]["spec_state"],
                "continue_ab_collection_no_new_parameter_spec",
            )
            for row in result["spec_rows"]:
                self.assertFalse(row["implementation_mutation_allowed"])
                self.assertFalse(row["parameter_mutation_allowed"])

            persisted = json.loads((root / "shadow_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "shadow_spec.md").read_text(encoding="utf-8")
            self.assertIn("M14 Rescue Parameter Shadow Spec", md)
            self.assertIn("Parameter mutation allowed: `0`", md)
            self.assertIn("risk_normalized_1_0r", md)

    def test_rejects_unsafe_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["parameter_mutation"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "parameter_mutation"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        queue_path = root / "queue.json"
        gate_path = root / "gate.json"
        target_path = root / "target.json"
        broker_prep_path = root / "broker_prep.json"
        rule_evidence_path = root / "rule_evidence.json"
        external_path = root / "external.json"
        config_path = root / "config.json"

        rows = [
            self._experiment_row(
                "m14-param-exp-stale",
                "M10-PA-001-shadow",
                "M10-PA-001",
                "fresh_quote_gate_recheck",
                "quote_source_freshness_gate",
                "blocked_until_fresh_refresh",
                "zero_signal_after_connection",
                "stale_quote_source_blocks_candidate",
            ),
            self._experiment_row(
                "m14-param-exp-target",
                "M10-PA-012-m14-modify-20260522",
                "M10-PA-012",
                "target_stop_reward_geometry_shadow",
                "target_stop_geometry_normalization_not_lowering_frozen_min_r",
                "blocked_until_fresh_refresh",
                "zero_signal_after_connection",
                "reward_filter_blocks_all",
            ),
            self._experiment_row(
                "m14-param-exp-quantity",
                "M10-PA-008",
                "M10-PA-008",
                "quantity_cap_shadow",
                "position_size_quantity_cap",
                "blocked_until_fresh_refresh",
                "broker_dry_run_blocker",
                "max_risk_per_order_exceeded",
            ),
            self._experiment_row(
                "m14-param-exp-cooldown",
                "M10-PA-005",
                "M10-PA-005",
                "cooldown_quality_veto_shadow",
                "cooldown_quality_veto",
                "blocked_until_fresh_refresh",
                "broker_dry_run_blocker",
                "consecutive_losses_limit",
            ),
            self._experiment_row(
                "m14-param-exp-ledger",
                "M10-PA-008-broker-risk-cap-shadow",
                "M10-PA-008",
                "ledger_path_mapping_audit",
                "registry_input_signal_account_ledger_mapping",
                "shadow_runtime_wait_first_ledger",
                "missing_rescue_ledger",
                "",
            ),
            self._experiment_row(
                "m14-param-exp-collect",
                "M10-PA-011-ORB-R1",
                "M10-PA-011",
                "continue_ab_evidence_collection",
                "none_ab_evidence_only",
                "collect_more_ab_evidence",
                "collect_more_ab_evidence",
                "",
            ),
        ]
        queue_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "project_stage": "M14 fixture stage",
                        "experiment_row_count": len(rows),
                    },
                    "experiment_rows": rows,
                }
            ),
            encoding="utf-8",
        )
        gate_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "fresh_refresh_observed": False,
                        "source_quote": "fallback_quotes_only",
                        "gate_row_count": len(rows),
                    },
                    "gate_rows": [
                        {
                            "experiment_row_id": row["experiment_row_id"],
                            "gate_row_id": f"gate-{row['experiment_row_id']}",
                            "gate_state": "continue_ab_collection_only"
                            if row["experiment_family"] == "continue_ab_evidence_collection"
                            else "waiting_for_m12_47_fresh_refresh",
                            "gate_reason": "fixture",
                            "shadow_review_candidate": False,
                        }
                        for row in rows
                    ],
                }
            ),
            encoding="utf-8",
        )
        target_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "strategy_id": "M10-PA-012-m14-modify-20260522",
                            "best_variant_id": "risk_normalized_1_0r",
                            "best_variant_candidate_runtime_id": "M10-PA-012-target-stop-shadow-5m",
                            "eligible_source_row_count": 12,
                            "best_variant_candidate_count": 12,
                            "current_reward_r_min": "0.7159",
                            "current_reward_r_max": "0.9819",
                            "current_reward_ge_1_0_count": 0,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        broker_prep_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "strategy_id": "M10-PA-008",
                            "source_reason_codes": ["max_risk_per_order_exceeded"],
                            "proposed_variant_id": "broker_risk_cap_shadow",
                            "source_quantity": "5.2469",
                            "proposed_quantity": "5.2083",
                            "source_risk_amount": "100.74",
                            "proposed_risk_amount": "100",
                            "proposed_shadow_runtime_id": "M10-PA-008-broker-risk-cap-shadow-1d",
                            "symbol": "ADBE",
                            "timeframe": "1d",
                        },
                        {
                            "strategy_id": "M10-PA-005",
                            "source_reason_codes": ["consecutive_losses_limit"],
                            "proposed_variant_id": "broker_cooldown_quality_shadow",
                            "prep_action": "prepare_cooldown_quality_veto_shadow_rule",
                            "ab_test_hypothesis": "preserve halt and veto lower quality later entries",
                            "symbol": "XLV",
                            "timeframe": "5m",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        rule_evidence_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "strategy_id": "M10-PA-005",
                            "rule_family": "cooldown_quality_veto",
                            "proposed_variant_id": "broker_cooldown_quality_shadow",
                            "proposed_shadow_strategy_id": "M10-PA-005-broker-cooldown-quality-shadow",
                            "shadow_rule_decision": "preserve_loss_streak_halt_and_veto_lower_quality_later_entries",
                            "source_reason_codes": ["consecutive_losses_limit"],
                            "comparison_contract": "Preserve the halt and compare later entries.",
                            "symbol": "XLV",
                            "timeframe": "5m",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        external_path.write_text(
            json.dumps(
                {
                    "rescue_reference_rows": [
                        {
                            "strategy_id": "M10-PA-001-shadow",
                            "external_reference_pattern_ids": ["ai_trader_shadow_signal_scoreboard"],
                            "local_review_lanes": ["shadow_signal_scoreboard", "decision_log_audit"],
                        }
                    ],
                    "broker_blocker_reference_rows": [],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.rescue-parameter-shadow-spec.config.v1",
                    "stage": "M14.rescue_parameter_shadow_spec",
                    "inputs": {
                        "m14_rescue_parameter_experiment_queue": str(queue_path),
                        "m14_rescue_parameter_activation_gate": str(gate_path),
                        "m14_rescue_target_stop_shadow_normalization": str(target_path),
                        "m14_2_broker_blocker_shadow_ab_prep": str(broker_prep_path),
                        "m14_2_broker_blocker_rule_shadow_evidence": str(rule_evidence_path),
                        "m14_rescue_external_reference_map": str(external_path),
                    },
                    "outputs": {
                        "shadow_spec_json": str(root / "shadow_spec.json"),
                        "shadow_spec_md": str(root / "shadow_spec.md"),
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
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

    def _experiment_row(
        self,
        experiment_row_id: str,
        strategy_id: str,
        parent_strategy_id: str,
        experiment_family: str,
        candidate_parameter_family: str,
        status: str,
        issue_type: str,
        dominant_issue: str,
    ) -> dict[str, object]:
        return {
            "experiment_row_id": experiment_row_id,
            "strategy_id": strategy_id,
            "parent_strategy_id": parent_strategy_id,
            "runtime_ids": [f"{strategy_id}-runtime"],
            "priority": "P0",
            "issue_type": issue_type,
            "dominant_issue": dominant_issue,
            "experiment_family": experiment_family,
            "candidate_parameter_family": candidate_parameter_family,
            "candidate_change_scope": "fixture",
            "status": status,
            "external_review_lanes": ["decision_log_audit"],
            "required_evidence": ["fixture evidence"],
            "source_metrics": {
                "eligible_if_fresh_quote_count": 3,
                "observed_trading_days_count": 1,
                "remaining_ab_trading_days": 9,
            },
        }


if __name__ == "__main__":
    unittest.main()
