from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_source_reextract_plan_lib import (
    load_config,
    run_m14_strategy_source_reextract_plan,
)


class M14StrategySourceReextractPlanTest(unittest.TestCase):
    def test_builds_source_reextract_plan_without_strategy_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_source_reextract_plan(
                load_config(config_path),
                generated_at="2026-05-27T08:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.strategy-source-reextract-plan.v1")
            self.assertEqual(result["summary"]["source_reextract_plan_row_count"], 5)
            self.assertEqual(result["summary"]["future_source_reextract_candidate_count"], 2)
            self.assertEqual(result["summary"]["research_only_hold_no_reextract_count"], 1)
            self.assertEqual(result["summary"]["supporting_rule_no_standalone_reextract_count"], 1)
            self.assertEqual(result["summary"]["external_reference_hold_count"], 1)
            self.assertEqual(result["summary"]["can_draft_future_source_reextract_spec_count"], 2)
            self.assertEqual(result["summary"]["can_create_strategy_now_count"], 0)
            self.assertEqual(result["summary"]["can_close_gap_now_count"], 0)
            self.assertEqual(result["summary"]["can_promote_now_count"], 0)
            self.assertEqual(result["summary"]["can_discard_now_count"], 0)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_now_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["parameter_mutation"])

            rows = {row["strategy_id"]: row for row in result["plan_rows"]}
            self.assertEqual(rows["M10-PA-003"]["plan_state"], "future_source_reextract_candidate")
            self.assertEqual(rows["M10-PA-010"]["plan_state"], "future_source_reextract_candidate")
            self.assertEqual(rows["M10-PA-006"]["plan_state"], "research_only_hold_no_reextract")
            self.assertEqual(rows["M10-PA-014"]["plan_state"], "supporting_rule_no_standalone_reextract")
            self.assertEqual(rows["AI-TRADER-EXTERNAL"]["plan_state"], "external_reference_hold")
            self.assertIn("tight-channel", rows["M10-PA-003"]["source_review_tasks"][0])
            self.assertIn("climax", rows["M10-PA-010"]["source_review_tasks"][0])
            for row in result["plan_rows"]:
                self.assertFalse(row["can_create_strategy_now"])
                self.assertFalse(row["can_close_gap_now"])
                self.assertFalse(row["can_promote_now"])
                self.assertFalse(row["can_discard_now"])
                self.assertFalse(row["parameter_mutation_allowed_now"])
                self.assertFalse(row["manual_m12_37_once_allowed"])

            persisted = json.loads((root / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "plan.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Source Reextract Plan", md)
            self.assertIn("Future source-reextract candidates: `2`", md)
            self.assertIn("no strategy creation", md)

    def test_rejects_live_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["live_execution"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "live_execution"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        triage_path = root / "triage.json"
        config_path = root / "config.json"
        triage_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                    },
                    "triage_rows": [
                        self._triage_row("M10-PA-003", "Tight Channel Trend Continuation", "source_visual_recheck_candidate"),
                        self._triage_row("M10-PA-010", "Final Flag or Climax TBTL Reversal", "source_visual_recheck_candidate"),
                        self._triage_row("M10-PA-006", "Trading Range BLSHS Limit-Order Framework", "research_only_risk_definition_hold"),
                        self._triage_row("M10-PA-014", "Measured Move Target Engine", "supporting_rule_attach_to_parent"),
                        self._triage_row("AI-TRADER-EXTERNAL", "", "external_reference_hold_no_local_strategy"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-source-reextract-plan.config.v1",
                    "stage": "M14.strategy_source_reextract_plan",
                    "inputs": {
                        "m14_strategy_source_recheck_triage": str(triage_path),
                    },
                    "outputs": {
                        "source_reextract_plan_json": str(root / "plan.json"),
                        "source_reextract_plan_md": str(root / "plan.md"),
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

    def _triage_row(self, strategy_id: str, title: str, triage_state: str) -> dict[str, object]:
        return {
            "triage_id": f"source_recheck::{strategy_id}",
            "review_id": f"pre_refresh::{strategy_id}",
            "strategy_id": strategy_id,
            "display_name": strategy_id,
            "catalog_title": title,
            "priority": "P2",
            "triage_state": triage_state,
            "source_ref_count": 2,
            "source_families": ["brooks_v2_manual_transcript"],
            "source_refs": [
                {
                    "source_ref": "raw:fixture.md",
                    "source_family": "brooks_v2_manual_transcript",
                    "title": "fixture source",
                }
            ],
            "prerequisites": ["source_refs_exist", "paper_simulated_only"],
        }


if __name__ == "__main__":
    unittest.main()
