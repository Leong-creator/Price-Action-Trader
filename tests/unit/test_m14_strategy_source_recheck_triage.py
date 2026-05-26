from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_source_recheck_triage_lib import (
    load_config,
    run_m14_strategy_source_recheck_triage,
)


class M14StrategySourceRecheckTriageTest(unittest.TestCase):
    def test_builds_source_recheck_triage_without_status_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_source_recheck_triage(
                load_config(config_path),
                generated_at="2026-05-27T07:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.strategy-source-recheck-triage.v1")
            self.assertEqual(result["summary"]["source_recheck_row_count"], 5)
            self.assertEqual(result["summary"]["source_visual_recheck_candidate_count"], 2)
            self.assertEqual(result["summary"]["supporting_rule_attach_to_parent_count"], 1)
            self.assertEqual(result["summary"]["research_only_risk_definition_hold_count"], 1)
            self.assertEqual(result["summary"]["external_reference_hold_count"], 1)
            self.assertEqual(result["summary"]["standalone_strategy_creation_allowed_count"], 0)
            self.assertEqual(result["summary"]["recheck_can_promote_now_count"], 0)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_now_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["parameter_mutation"])

            rows = {row["strategy_id"]: row for row in result["triage_rows"]}
            self.assertEqual(rows["M10-PA-003"]["triage_state"], "source_visual_recheck_candidate")
            self.assertEqual(rows["M10-PA-010"]["triage_state"], "source_visual_recheck_candidate")
            self.assertEqual(rows["M10-PA-014"]["triage_state"], "supporting_rule_attach_to_parent")
            self.assertEqual(rows["M10-PA-006"]["triage_state"], "research_only_risk_definition_hold")
            self.assertEqual(
                rows["AI-TRADER-EXTERNAL"]["triage_state"],
                "external_reference_hold_no_local_strategy",
            )
            for row in result["triage_rows"]:
                self.assertFalse(row["recheck_can_create_new_strategy_now"])
                self.assertFalse(row["recheck_can_close_gap_now"])
                self.assertFalse(row["recheck_can_promote_now"])
                self.assertFalse(row["recheck_can_discard_now"])
                self.assertFalse(row["parameter_mutation_allowed_now"])
                self.assertFalse(row["manual_m12_37_once_allowed"])

            persisted = json.loads((root / "triage.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "triage.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Source Recheck Triage", md)
            self.assertIn("Source/visual candidates: `2`", md)
            self.assertIn("No row can create a new strategy", md)

    def test_rejects_unsafe_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["paper_trading_approval"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "paper_trading_approval"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        audit_path = root / "audit.json"
        ladder_path = root / "ladder.json"
        catalog_path = root / "catalog.json"
        support_path = root / "support.json"
        eligibility_path = root / "eligibility.json"
        config_path = root / "config.json"
        audit_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                        "ready_for_artifact_review_now_count": 5,
                    },
                    "audit_rows": [
                        self._audit_row("AI-TRADER-EXTERNAL"),
                        self._audit_row("M10-PA-003"),
                        self._audit_row("M10-PA-006"),
                        self._audit_row("M10-PA-010"),
                        self._audit_row("M10-PA-014"),
                        {
                            **self._audit_row("M10-PA-001"),
                            "audit_state": "pre_review_ready_wait_fresh_evidence",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        ladder_path.write_text(
            json.dumps(
                {
                    "ladder_rows": [
                        {
                            "strategy_id": strategy_id,
                            "ladder_state": "shadow_or_plugin_hold",
                            "next_decision": "keep_shadow_research_coverage",
                        }
                        for strategy_id in [
                            "AI-TRADER-EXTERNAL",
                            "M10-PA-003",
                            "M10-PA-006",
                            "M10-PA-010",
                            "M10-PA-014",
                        ]
                    ]
                }
            ),
            encoding="utf-8",
        )
        catalog_path.write_text(
            json.dumps(
                {
                    "strategies": [
                        self._catalog_row("M10-PA-003", "backtest_candidate", True, True, "visual_golden_case_then_historical_backtest"),
                        self._catalog_row("M10-PA-006", "research_only", False, False, "research_or_visual_review_queue"),
                        self._catalog_row("M10-PA-010", "visual_review_then_backtest", True, True, "visual_golden_case_then_historical_backtest"),
                        self._catalog_row("M10-PA-014", "supporting_rule", False, True, "supporting_rule_attached_to_parent_setups"),
                    ]
                }
            ),
            encoding="utf-8",
        )
        support_path.write_text(
            json.dumps(
                {
                    "matrix": [
                        {
                            "strategy_id": strategy_id,
                            "support_counts": {"brooks_v2_manual_transcript": 3},
                            "supported_families": ["brooks_v2_manual_transcript"],
                        }
                        for strategy_id in ["M10-PA-003", "M10-PA-006", "M10-PA-010", "M10-PA-014"]
                    ]
                }
            ),
            encoding="utf-8",
        )
        eligibility_path.write_text(
            json.dumps(
                {
                    "matrix": [
                        self._eligibility_row("M10-PA-003", True, True, "visual_golden_case_then_historical_backtest"),
                        self._eligibility_row("M10-PA-006", False, False, "research_or_visual_review_queue"),
                        self._eligibility_row("M10-PA-010", True, True, "visual_golden_case_then_historical_backtest"),
                        self._eligibility_row("M10-PA-014", False, True, "supporting_rule_attached_to_parent_setups"),
                    ]
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-source-recheck-triage.config.v1",
                    "stage": "M14.strategy_source_recheck_triage",
                    "inputs": {
                        "m14_strategy_pre_refresh_review_audit": str(audit_path),
                        "m14_strategy_decision_ladder": str(ladder_path),
                        "m10_strategy_catalog": str(catalog_path),
                        "m10_source_support_matrix": str(support_path),
                        "m10_backtest_eligibility_matrix": str(eligibility_path),
                    },
                    "outputs": {
                        "source_recheck_triage_json": str(root / "triage.json"),
                        "source_recheck_triage_md": str(root / "triage.md"),
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

    def _audit_row(self, strategy_id: str) -> dict[str, object]:
        return {
            "review_id": f"pre_refresh::{strategy_id}",
            "strategy_id": strategy_id,
            "display_name": strategy_id,
            "priority": "P2",
            "burn_down_lane": "shadow_plugin_research",
            "audit_state": "ready_for_artifact_review_now",
            "missing_evidence_categories": ["independent_strategy_evidence_missing", "manual_m14_review"],
        }

    def _catalog_row(
        self,
        strategy_id: str,
        status: str,
        eligible: bool,
        approximable: bool,
        route: str,
    ) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "title": strategy_id,
            "status": status,
            "visual_dependency": "high",
            "source_families": ["brooks_v2_manual_transcript"],
            "source_refs": [{"source_ref": "raw:fixture.md", "source_family": "brooks_v2_manual_transcript"}],
            "backtest_eligibility": {
                "eligible_for_historical_backtest": eligible,
                "ohlcv_approximable": approximable,
                "route": route,
            },
        }

    def _eligibility_row(
        self,
        strategy_id: str,
        eligible: bool,
        approximable: bool,
        route: str,
    ) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "eligible_for_historical_backtest": eligible,
            "ohlcv_approximable": approximable,
            "test_route": route,
            "prerequisites": ["source_refs_exist", "paper_simulated_only"],
        }


if __name__ == "__main__":
    unittest.main()
