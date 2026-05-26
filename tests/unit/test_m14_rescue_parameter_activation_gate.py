from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_parameter_activation_gate_lib import (
    load_config,
    run_m14_rescue_parameter_activation_gate,
)


class M14RescueParameterActivationGateTest(unittest.TestCase):
    def test_waits_without_fresh_refresh_and_keeps_mutations_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root, fresh=False)

            result = run_m14_rescue_parameter_activation_gate(
                load_config(config_path),
                generated_at="2026-05-26T21:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-parameter-activation-gate.v1")
            self.assertFalse(result["summary"]["fresh_refresh_observed"])
            self.assertEqual(result["summary"]["gate_row_count"], 5)
            self.assertEqual(result["summary"]["waiting_for_fresh_refresh_count"], 4)
            self.assertEqual(result["summary"]["continue_ab_collection_count"], 1)
            self.assertEqual(result["summary"]["shadow_review_candidate_count"], 0)
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

            states = {row["experiment_family"]: row["gate_state"] for row in result["gate_rows"]}
            self.assertEqual(states["fresh_quote_gate_recheck"], "waiting_for_m12_47_fresh_refresh")
            self.assertEqual(states["target_stop_reward_geometry_shadow"], "waiting_for_m12_47_fresh_refresh")
            self.assertEqual(states["continue_ab_evidence_collection"], "continue_ab_collection_only")
            for row in result["gate_rows"]:
                self.assertFalse(row["implementation_mutation_allowed"])
                self.assertFalse(row["parameter_mutation_allowed"])

            md = (root / "gate.md").read_text(encoding="utf-8")
            self.assertIn("M14 Rescue Parameter Activation Gate", md)
            self.assertIn("Parameter mutation allowed: `0`", md)

    def test_passed_evidence_opens_shadow_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root, fresh=True)

            result = run_m14_rescue_parameter_activation_gate(
                load_config(config_path),
                generated_at="2026-05-26T21:10:00Z",
            )

            self.assertTrue(result["summary"]["fresh_refresh_observed"])
            self.assertEqual(result["summary"]["shadow_review_candidate_count"], 3)
            self.assertEqual(result["summary"]["first_ledger_ready_count"], 1)
            self.assertEqual(result["summary"]["manual_review_required_count"], 3)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_count"], 0)

            rows = {row["experiment_family"]: row for row in result["gate_rows"]}
            self.assertEqual(rows["fresh_quote_gate_recheck"]["gate_state"], "ready_for_shadow_parameter_review")
            self.assertEqual(
                rows["target_stop_reward_geometry_shadow"]["gate_state"],
                "ready_for_shadow_parameter_review",
            )
            self.assertEqual(rows["cooldown_quality_veto_shadow"]["gate_state"], "ready_for_shadow_parameter_review")
            self.assertEqual(
                rows["ledger_path_mapping_audit"]["gate_state"],
                "first_ledger_observed_start_ab_evidence_count",
            )
            self.assertFalse(rows["fresh_quote_gate_recheck"]["implementation_mutation_allowed"])
            self.assertFalse(rows["fresh_quote_gate_recheck"]["parameter_mutation_allowed"])

    def test_rejects_unsafe_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root, fresh=True)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["parameter_mutation"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "parameter_mutation"):
                load_config(config_path)

    def _write_fixture(self, root: Path, *, fresh: bool) -> Path:
        queue_path = root / "queue.json"
        post_path = root / "post.json"
        config_path = root / "config.json"
        queue_path.write_text(
            json.dumps(
                {
                    "experiment_rows": [
                        self._experiment_row(
                            "m14-param-exp-stale",
                            "M10-PA-001-shadow",
                            "M10-PA-001",
                            "fresh_quote_gate_recheck",
                            "fresh_quote_recheck",
                        ),
                        self._experiment_row(
                            "m14-param-exp-target",
                            "M10-PA-012-shadow",
                            "M10-PA-012",
                            "target_stop_reward_geometry_shadow",
                            "target_stop_shadow_compare",
                        ),
                        self._experiment_row(
                            "m14-param-exp-ledger",
                            "M10-PA-008-broker-risk-cap-shadow",
                            "M10-PA-008",
                            "ledger_path_mapping_audit",
                            "first_rescue_ledger_watch",
                        ),
                        self._experiment_row(
                            "m14-param-exp-cooldown",
                            "M10-PA-005",
                            "M10-PA-005",
                            "cooldown_quality_veto_shadow",
                            "broker_rule_shadow_recheck",
                            dominant_issue="consecutive_losses_limit",
                        ),
                        self._experiment_row(
                            "m14-param-exp-collect",
                            "M10-PA-011-ORB-R1",
                            "M10-PA-011",
                            "continue_ab_evidence_collection",
                            "",
                        ),
                    ]
                }
            ),
            encoding="utf-8",
        )
        outcome_status = "passed" if fresh else "waiting_for_m12_47_fresh_refresh"
        post_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "fresh_refresh_observed": fresh,
                        "source_quote": "longbridge_quote_readonly" if fresh else "fallback_quotes_only",
                        "source_scan_date": "2026-05-26",
                        "latest_ledger_trading_date": "2026-05-26",
                    },
                    "rows": [
                        self._outcome_row("M10-PA-001-shadow", "M10-PA-001", "fresh_quote_recheck", outcome_status),
                        self._outcome_row(
                            "M10-PA-012-shadow",
                            "M10-PA-012",
                            "target_stop_shadow_compare",
                            outcome_status,
                        ),
                        self._outcome_row(
                            "M10-PA-008-broker-risk-cap-shadow",
                            "M10-PA-008",
                            "first_rescue_ledger_watch",
                            outcome_status,
                        ),
                        self._outcome_row(
                            "M10-PA-005",
                            "M10-PA-005",
                            "broker_rule_shadow_recheck",
                            "evidence_observed" if fresh else "waiting_for_m12_47_fresh_refresh",
                            rule_family="cooldown_quality_veto",
                        ),
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.rescue-parameter-activation-gate.config.v1",
                    "stage": "M14.rescue_parameter_activation_gate",
                    "inputs": {
                        "m14_rescue_parameter_experiment_queue": str(queue_path),
                        "m14_rescue_post_refresh_outcome_review": str(post_path),
                    },
                    "outputs": {
                        "activation_gate_json": str(root / "gate.json"),
                        "activation_gate_md": str(root / "gate.md"),
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
        readiness_family: str,
        *,
        dominant_issue: str = "",
    ) -> dict[str, object]:
        return {
            "experiment_row_id": experiment_row_id,
            "strategy_id": strategy_id,
            "parent_strategy_id": parent_strategy_id,
            "runtime_ids": [f"{strategy_id}-1d"],
            "priority": "P0",
            "issue_type": "fixture",
            "dominant_issue": dominant_issue,
            "experiment_family": experiment_family,
            "candidate_parameter_family": experiment_family,
            "candidate_change_scope": "fixture",
            "status": "blocked_until_fresh_refresh",
            "readiness_families": [readiness_family] if readiness_family else [],
        }

    def _outcome_row(
        self,
        strategy_id: str,
        parent_strategy_id: str,
        readiness_family: str,
        outcome_status: str,
        *,
        rule_family: str = "",
    ) -> dict[str, object]:
        return {
            "row_id": f"{readiness_family}-{strategy_id}",
            "strategy_id": strategy_id,
            "parent_strategy_id": parent_strategy_id,
            "runtime_id": f"{strategy_id}-1d",
            "readiness_family": readiness_family,
            "outcome_status": outcome_status,
            "outcome_passed": outcome_status in {"passed", "evidence_observed"},
            "outcome_failed": False,
            "next_action": "fixture next action",
            "source_metrics": {"rule_family": rule_family},
        }


if __name__ == "__main__":
    unittest.main()
