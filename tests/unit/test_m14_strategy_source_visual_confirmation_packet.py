from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_source_visual_confirmation_packet_lib import (
    load_config,
    run_m14_strategy_source_visual_confirmation_packet,
)


class M14StrategySourceVisualConfirmationPacketTest(unittest.TestCase):
    def test_builds_packet_without_recording_confirmation_or_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_source_visual_confirmation_packet(
                load_config(config_path),
                generated_at="2026-05-27T11:00:00Z",
            )

            self.assertEqual(
                result["schema_version"],
                "m14.strategy-source-visual-confirmation-packet.v1",
            )
            self.assertEqual(result["summary"]["source_visual_confirmation_packet_row_count"], 2)
            self.assertEqual(result["summary"]["candidate_strategy_count"], 2)
            self.assertEqual(result["summary"]["confirmation_item_count"], 6)
            self.assertEqual(result["summary"]["confirmation_case_row_count"], 10)
            self.assertEqual(result["summary"]["positive_case_count"], 6)
            self.assertEqual(result["summary"]["counterexample_case_count"], 2)
            self.assertEqual(result["summary"]["boundary_case_count"], 2)
            self.assertEqual(result["summary"]["packet_ready_count"], 2)
            self.assertEqual(result["summary"]["manual_visual_confirmation_required_count"], 2)
            self.assertEqual(result["summary"]["manual_visual_confirmation_recorded_count"], 0)
            self.assertEqual(result["summary"]["future_spec_unblocked_count"], 0)
            self.assertEqual(result["summary"]["can_draft_future_source_reextract_spec_now_count"], 0)
            self.assertEqual(result["summary"]["can_create_strategy_now_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["strategy_state_mutation"])

            rows = {row["strategy_id"]: row for row in result["packet_rows"]}
            self.assertEqual(rows["M10-PA-003"]["packet_state"], "manual_visual_confirmation_packet_ready")
            self.assertFalse(rows["M10-PA-003"]["manual_visual_confirmation_recorded"])
            self.assertEqual(
                rows["M10-PA-010"]["future_spec_gate_state"],
                "blocked_until_manual_visual_confirmation_recorded",
            )
            for row in result["packet_rows"]:
                self.assertFalse(row["can_draft_future_source_reextract_spec_now"])
                self.assertFalse(row["can_create_strategy_now"])
                self.assertFalse(row["can_promote_now"])
                self.assertFalse(row["parameter_mutation_allowed_now"])
                self.assertFalse(row["manual_m12_37_once_allowed"])

            case_rows = [
                case
                for row in result["packet_rows"]
                for case in row["case_confirmation_rows"]
            ]
            self.assertTrue(
                all(case["human_confirmation_state"] == "pending_manual_visual_confirmation" for case in case_rows)
            )
            self.assertTrue(all(case["paper_gate_evidence_now"] is False for case in case_rows))

            persisted = json.loads((root / "packet.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "packet.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Source Visual Confirmation Packet", md)
            self.assertIn("Packet rows / strategies: `2/2`", md)
            self.assertIn("no confirmation recorded", md)

    def test_rejects_mutation_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["parameter_mutation"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "parameter_mutation"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        alignment_path = root / "alignment.json"
        config_path = root / "config.json"
        alignment_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                    },
                    "alignment_rows": [
                        self._alignment_row("M10-PA-003", "Tight Channel Trend Continuation"),
                        self._alignment_row("M10-PA-010", "Final Flag or Climax TBTL Reversal"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-source-visual-confirmation-packet.config.v1",
                    "stage": "M14.strategy_source_visual_confirmation_packet",
                    "inputs": {
                        "m14_strategy_source_visual_alignment_gate": str(alignment_path),
                    },
                    "outputs": {
                        "source_visual_confirmation_packet_json": str(root / "packet.json"),
                        "source_visual_confirmation_packet_md": str(root / "packet.md"),
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
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _alignment_row(self, strategy_id: str, title: str) -> dict[str, object]:
        return {
            "alignment_id": f"source_visual_alignment::{strategy_id}",
            "strategy_id": strategy_id,
            "catalog_title": title,
            "priority": "P2",
            "setup_hypothesis": "fixture_hypothesis",
            "visual_alignment_state": "ready_for_manual_visual_alignment",
            "source_backed_atom_count": 5,
            "source_review_answer_count": 3,
            "visual_alignment_questions": [
                self._question(strategy_id, 1),
                self._question(strategy_id, 2),
                self._question(strategy_id, 3),
            ],
            "case_rows": [
                self._case(strategy_id, "positive", 1),
                self._case(strategy_id, "positive", 2),
                self._case(strategy_id, "positive", 3),
                self._case(strategy_id, "counterexample", 1),
                self._case(strategy_id, "boundary", 1),
            ],
        }

    def _question(self, strategy_id: str, index: int) -> dict[str, str]:
        return {
            "question_id": f"{strategy_id}-q{index}",
            "question": "Does the visual evidence support the source-backed rule?",
            "acceptance_signal": "The chart role is visually clear.",
        }

    def _case(self, strategy_id: str, case_type: str, index: int) -> dict[str, object]:
        return {
            "case_id": f"{strategy_id}-{case_type}-{index}",
            "case_type": case_type,
            "brooks_unit_ref": "raw:fixture.md",
            "evidence_video_id": "video_fixture",
            "evidence_page": index,
            "resolved_evidence_path": f"/tmp/{strategy_id}/{case_type}_{index}.webp",
            "evidence_asset_location": "old_m10_worktree",
            "checksum_match": True,
            "matched_terms": ["fixture"],
            "pattern_decision_points": ["confirm visual geometry"],
            "disqualifiers": ["opposite follow-through"],
            "ohlcv_approximation_risk": "visual review required",
        }


if __name__ == "__main__":
    unittest.main()
