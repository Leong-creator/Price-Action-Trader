from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_future_source_reextract_spec_prep_lib import (
    load_config,
    run_m14_strategy_future_source_reextract_spec_prep,
)


class M14StrategyFutureSourceReextractSpecPrepTest(unittest.TestCase):
    def test_builds_blocked_conditional_specs_without_state_changes_or_legacy_profit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root, confirmed=False)

            result = run_m14_strategy_future_source_reextract_spec_prep(
                load_config(config_path),
                generated_at="2026-05-27T14:00:00Z",
            )

            self.assertEqual(
                result["schema_version"],
                "m14.strategy-future-source-reextract-spec-prep.v1",
            )
            self.assertEqual(result["summary"]["future_source_reextract_spec_prep_row_count"], 2)
            self.assertEqual(result["summary"]["candidate_strategy_count"], 2)
            self.assertEqual(result["summary"]["source_backed_atom_count"], 4)
            self.assertEqual(result["summary"]["source_review_answer_count"], 2)
            self.assertEqual(result["summary"]["future_spec_unblocked_count"], 0)
            self.assertEqual(result["summary"]["blocked_until_manual_visual_confirmation_count"], 2)
            self.assertEqual(result["summary"]["manual_confirmation_pending_count"], 4)
            self.assertEqual(result["summary"]["strategy_creation_allowed_count"], 0)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_now_count"], 0)
            self.assertEqual(result["summary"]["legacy_historical_profit_planning_input_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["legacy_historical_profit_planning_input"])

            rows = {row["strategy_id"]: row for row in result["future_source_reextract_spec_prep_rows"]}
            self.assertEqual(rows["M10-PA-003"]["draft_state"], "blocked_until_manual_visual_confirmation")
            self.assertFalse(rows["M10-PA-003"]["can_create_strategy_now"])
            self.assertFalse(rows["M10-PA-003"]["parameter_mutation_allowed_now"])
            self.assertFalse(rows["M10-PA-003"]["legacy_historical_profit_planning_input"])
            self.assertEqual(
                rows["M10-PA-003"]["planning_input_policy"]["decision_basis"],
                "source_atoms_visual_confirmation_internal_sim_evidence_only",
            )
            self.assertIn(
                "manual_visual_case::M10-PA-003-case",
                rows["M10-PA-003"]["required_before_activation"],
            )

            persisted = json.loads((root / "prep.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "prep.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Future Source Reextract Spec Prep", md)
            self.assertIn("Legacy historical profit planning inputs: `0`", md)

    def test_confirmed_visual_gate_moves_to_manual_draft_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root, confirmed=True)

            result = run_m14_strategy_future_source_reextract_spec_prep(
                load_config(config_path),
                generated_at="2026-05-27T14:30:00Z",
            )

            self.assertEqual(result["summary"]["future_spec_unblocked_count"], 2)
            self.assertEqual(result["summary"]["blocked_until_manual_visual_confirmation_count"], 0)
            self.assertEqual(result["summary"]["manual_confirmation_pending_count"], 0)
            for row in result["future_source_reextract_spec_prep_rows"]:
                self.assertEqual(row["draft_state"], "ready_for_manual_m14_draft_review")
                self.assertFalse(row["can_create_strategy_now"])
                self.assertFalse(row["can_promote_now"])
                self.assertFalse(row["parameter_mutation_allowed_now"])

    def test_rejects_legacy_history_planning_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root, confirmed=False)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["legacy_historical_profit_planning_input"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "legacy_historical_profit_planning_input"):
                load_config(config_path)

    def _write_fixture(self, root: Path, *, confirmed: bool) -> Path:
        review_path = root / "review.json"
        gate_path = root / "gate.json"
        config_path = root / "config.json"
        review_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                        "source_reextract_review_row_count": 2,
                    },
                    "review_rows": [
                        self._review_row("M10-PA-003", "Tight Channel Trend Continuation"),
                        self._review_row("M10-PA-010", "Final Flag or Climax TBTL Reversal"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        gate_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "source_visual_confirmation_response_gate_row_count": 2,
                        "manual_visual_confirmation_complete_count": 2 if confirmed else 0,
                    },
                    "response_gate_rows": [
                        self._gate_row("M10-PA-003", confirmed=confirmed),
                        self._gate_row("M10-PA-010", confirmed=confirmed),
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-future-source-reextract-spec-prep.config.v1",
                    "stage": "M14.strategy_future_source_reextract_spec_prep",
                    "inputs": {
                        "m14_strategy_source_reextract_review": str(review_path),
                        "m14_strategy_source_visual_confirmation_response_gate": str(gate_path),
                    },
                    "outputs": {
                        "future_source_reextract_spec_prep_json": str(root / "prep.json"),
                        "future_source_reextract_spec_prep_md": str(root / "prep.md"),
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
                        "strategy_state_mutation": False,
                        "legacy_historical_profit_planning_input": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _review_row(self, strategy_id: str, title: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "catalog_title": title,
            "priority": "P2",
            "setup_hypothesis": f"{strategy_id}-setup",
            "future_spec_readiness": "draftable_after_visual_case_alignment",
            "can_draft_future_source_reextract_spec": True,
            "source_refs_reviewed": [{"source_ref": f"raw:{strategy_id}.md"}],
            "source_backed_atoms": [
                {
                    "field": "entry_trigger",
                    "implementation_hint": f"{strategy_id} entry hint",
                    "extracted_rule": "entry rule",
                },
                {
                    "field": "invalidation",
                    "implementation_hint": f"{strategy_id} invalidation hint",
                    "extracted_rule": "invalidation rule",
                },
            ],
            "source_review_answers": [
                {
                    "question_id": f"{strategy_id}-q",
                    "answer": "source supported",
                    "evidence_state": "source_supported",
                }
            ],
            "ohlcv_proxy_assessment": {
                "approximable_fields": ["bar_count", "follow_through"],
                "visual_first_fields": ["shape"],
            },
        }

    def _gate_row(self, strategy_id: str, *, confirmed: bool) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "future_spec_gate_state": (
                "ready_for_future_source_reextract_spec_draft_review"
                if confirmed
                else "blocked_until_manual_visual_confirmation_recorded"
            ),
            "future_spec_unblocked_after_manual_confirmation": confirmed,
            "rejected_or_unclear_response_count": 0,
            "question_gate_rows": [
                {
                    "question_id": f"{strategy_id}-question",
                    "blocks_future_spec": not confirmed,
                }
            ],
            "case_gate_rows": [
                {
                    "case_id": f"{strategy_id}-case",
                    "blocks_future_spec": not confirmed,
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
