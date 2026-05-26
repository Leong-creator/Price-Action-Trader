from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_pre_refresh_review_audit_lib import (
    load_config,
    run_m14_strategy_pre_refresh_review_audit,
)


class M14StrategyPreRefreshReviewAuditTest(unittest.TestCase):
    def test_builds_artifact_readiness_audit_without_closing_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_pre_refresh_review_audit(
                load_config(config_path),
                generated_at="2026-05-27T06:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.strategy-pre-refresh-review-audit.v1")
            self.assertEqual(result["summary"]["audit_row_count"], 4)
            self.assertEqual(result["summary"]["held_row_count"], 1)
            self.assertEqual(result["summary"]["ready_for_artifact_review_now_count"], 1)
            self.assertEqual(result["summary"]["pre_review_ready_wait_fresh_evidence_count"], 2)
            self.assertEqual(result["summary"]["needs_supporting_artifact_backfill_count"], 1)
            self.assertEqual(result["summary"]["fresh_dependent_count"], 3)
            self.assertEqual(result["summary"]["artifact_only_count"], 1)
            self.assertEqual(result["summary"]["shadow_parameter_required_count"], 2)
            self.assertEqual(result["summary"]["shadow_parameter_artifact_audit_count"], 2)
            self.assertEqual(result["summary"]["shadow_parameter_artifact_ready_count"], 1)
            self.assertEqual(result["summary"]["activation_gate_artifact_ready_count"], 1)
            self.assertEqual(result["summary"]["external_reference_required_count"], 2)
            self.assertEqual(result["summary"]["external_reference_ready_count"], 2)
            self.assertEqual(result["summary"]["external_reference_artifact_audit_count"], 2)
            self.assertEqual(result["summary"]["external_reference_artifact_ready_count"], 2)
            self.assertEqual(result["summary"]["decision_ladder_present_count"], 4)
            self.assertEqual(result["summary"]["review_can_close_gap_now_count"], 0)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_now_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["parameter_mutation"])

            rows = {row["strategy_id"]: row for row in result["audit_rows"]}
            self.assertEqual(rows["M10-PA-004"]["audit_state"], "pre_review_ready_wait_fresh_evidence")
            self.assertEqual(rows["M10-PA-001"]["audit_state"], "pre_review_ready_wait_fresh_evidence")
            self.assertEqual(rows["M10-PA-003"]["audit_state"], "ready_for_artifact_review_now")
            self.assertEqual(rows["M10-PA-011"]["audit_state"], "needs_supporting_artifact_backfill")
            self.assertIn(
                "m14_rescue_parameter_shadow_spec_row",
                rows["M10-PA-011"]["missing_supporting_artifacts"],
            )
            for row in result["audit_rows"]:
                self.assertFalse(row["review_can_close_gap_now"])
                self.assertFalse(row["review_can_promote_now"])
                self.assertFalse(row["review_can_discard_now"])
                self.assertFalse(row["parameter_mutation_allowed_now"])
                self.assertFalse(row["manual_m12_37_once_allowed"])

            persisted = json.loads((root / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "audit.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Pre-Refresh Review Audit", md)
            self.assertIn("Ready now / ready waiting fresh / needs artifact backfill: `1/2/1`", md)
            self.assertIn("This audit cannot close gaps", md)

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
        packet_path = root / "packet.json"
        burndown_path = root / "burndown.json"
        ladder_path = root / "ladder.json"
        shadow_path = root / "shadow.json"
        activation_path = root / "activation.json"
        external_path = root / "external.json"
        config_path = root / "config.json"
        packet_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                        "review_row_count": 4,
                    },
                    "review_rows": [
                        self._review_row("M10-PA-004", "P0", "approved_internal_sim_refresh", True, ["m12_47_fresh_refresh"], ["tradingagents_persistent_decision_log"]),
                        self._review_row("M10-PA-001", "P0", "rescue_shadow_parameter_review", True, ["m12_47_fresh_refresh", "shadow_parameter_review"], ["ai_trader_shadow_signal_scoreboard"]),
                        self._review_row("M10-PA-011", "P0", "first_rescue_ledger", True, ["m12_47_fresh_refresh", "shadow_parameter_review"], []),
                        self._review_row("M10-PA-003", "P2", "shadow_plugin_research", False, ["independent_strategy_evidence_missing"], []),
                    ],
                    "held_rows": [
                        {
                            "strategy_id": "M10-PA-004-MBF",
                            "priority": "P1",
                            "burn_down_lane": "rescue_ab_collection",
                            "hold_reason": "wait for rescue A/B",
                            "next_evidence_to_collect": "10-day rescue A/B",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        burndown_path.write_text(
            json.dumps({"burndown_rows": [{"strategy_id": row} for row in ["M10-PA-004", "M10-PA-001", "M10-PA-011", "M10-PA-003"]]}),
            encoding="utf-8",
        )
        ladder_path.write_text(
            json.dumps({"ladder_rows": [{"strategy_id": row} for row in ["M10-PA-004", "M10-PA-001", "M10-PA-011", "M10-PA-003"]]}),
            encoding="utf-8",
        )
        shadow_path.write_text(
            json.dumps({"spec_rows": [{"strategy_id": "M10-PA-001-shadow", "parent_strategy_id": "M10-PA-001"}]}),
            encoding="utf-8",
        )
        activation_path.write_text(
            json.dumps({"gate_rows": [{"strategy_id": "M10-PA-001-shadow", "parent_strategy_id": "M10-PA-001"}]}),
            encoding="utf-8",
        )
        external_path.write_text(
            json.dumps(
                {
                    "rescue_reference_rows": [
                        {
                            "strategy_id": "M10-PA-001-shadow",
                            "parent_strategy_id": "M10-PA-001",
                            "external_reference_pattern_ids": ["ai_trader_shadow_signal_scoreboard"],
                        }
                    ],
                    "broker_blocker_reference_rows": [
                        {
                            "strategy_id": "M10-PA-004",
                            "external_reference_pattern_ids": ["tradingagents_persistent_decision_log"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-pre-refresh-review-audit.config.v1",
                    "stage": "M14.strategy_pre_refresh_review_audit",
                    "inputs": {
                        "m14_strategy_pre_refresh_review_packet": str(packet_path),
                        "m14_strategy_evidence_gap_burndown": str(burndown_path),
                        "m14_strategy_decision_ladder": str(ladder_path),
                        "m14_rescue_parameter_shadow_spec": str(shadow_path),
                        "m14_rescue_parameter_activation_gate": str(activation_path),
                        "m14_rescue_external_reference_map": str(external_path),
                    },
                    "outputs": {
                        "review_audit_json": str(root / "audit.json"),
                        "review_audit_md": str(root / "audit.md"),
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

    def _review_row(
        self,
        strategy_id: str,
        priority: str,
        lane: str,
        fresh_refresh: bool,
        missing: list[str],
        external_patterns: list[str],
    ) -> dict[str, object]:
        return {
            "review_id": f"pre_refresh::{strategy_id}",
            "strategy_id": strategy_id,
            "display_name": strategy_id,
            "priority": priority,
            "sequence_rank": 10,
            "burn_down_lane": lane,
            "review_focus": "fixture focus",
            "requires_m12_47_fresh_refresh": fresh_refresh,
            "missing_evidence_categories": missing,
            "external_reference_pattern_ids": external_patterns,
            "external_reference_review_actions": [],
            "pre_refresh_review_actions": ["fixture action"],
            "next_evidence_to_collect": "fixture next evidence",
            "blocked_by": ["manual_m14_review_pending"],
        }


if __name__ == "__main__":
    unittest.main()
