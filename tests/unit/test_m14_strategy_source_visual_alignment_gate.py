from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_source_visual_alignment_gate_lib import (
    load_config,
    run_m14_strategy_source_visual_alignment_gate,
)


class M14StrategySourceVisualAlignmentGateTest(unittest.TestCase):
    def test_builds_visual_alignment_gate_without_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_source_visual_alignment_gate(
                load_config(config_path),
                generated_at="2026-05-27T10:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.strategy-source-visual-alignment-gate.v1")
            self.assertEqual(result["summary"]["source_visual_alignment_gate_row_count"], 2)
            self.assertEqual(result["summary"]["candidate_strategy_count"], 2)
            self.assertEqual(result["summary"]["visual_case_count"], 10)
            self.assertEqual(result["summary"]["positive_case_count"], 6)
            self.assertEqual(result["summary"]["counterexample_case_count"], 2)
            self.assertEqual(result["summary"]["boundary_case_count"], 2)
            self.assertEqual(result["summary"]["checksum_match_count"], 10)
            self.assertEqual(result["summary"]["old_worktree_asset_exists_count"], 10)
            self.assertEqual(result["summary"]["ready_for_manual_visual_alignment_count"], 2)
            self.assertEqual(result["summary"]["manual_visual_confirmation_required_count"], 2)
            self.assertEqual(result["summary"]["can_draft_future_source_reextract_spec_now_count"], 0)
            self.assertEqual(result["summary"]["can_create_strategy_now_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["strategy_state_mutation"])

            rows = {row["strategy_id"]: row for row in result["alignment_rows"]}
            self.assertEqual(rows["M10-PA-003"]["visual_alignment_state"], "ready_for_manual_visual_alignment")
            self.assertEqual(rows["M10-PA-010"]["future_spec_gate_state"], "blocked_until_manual_visual_confirmation")
            for row in result["alignment_rows"]:
                self.assertFalse(row["can_draft_future_source_reextract_spec_now"])
                self.assertFalse(row["can_create_strategy_now"])
                self.assertFalse(row["can_promote_now"])
                self.assertFalse(row["parameter_mutation_allowed_now"])
                self.assertFalse(row["manual_m12_37_once_allowed"])

            persisted = json.loads((root / "gate.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "gate.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Source Visual Alignment Gate", md)
            self.assertIn("Gate rows / strategies: `2/2`", md)
            self.assertIn("no strategy creation", md)

    def test_rejects_broker_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["broker_connection"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "broker_connection"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        review_path = root / "review.json"
        visual_dir = root / "visual"
        old_root = root / "old"
        config_path = root / "config.json"
        visual_dir.mkdir()
        old_root.mkdir()
        review_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                    },
                    "review_rows": [
                        self._review_row("M10-PA-003", "Tight Channel Trend Continuation"),
                        self._review_row("M10-PA-010", "Final Flag or Climax TBTL Reversal"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        for strategy_id in ("M10-PA-003", "M10-PA-010"):
            cases = [
                self._case(old_root, strategy_id, "positive", 1),
                self._case(old_root, strategy_id, "positive", 2),
                self._case(old_root, strategy_id, "positive", 3),
                self._case(old_root, strategy_id, "counterexample", 1),
                self._case(old_root, strategy_id, "boundary", 1),
            ]
            (visual_dir / f"{strategy_id}.json").write_text(
                json.dumps(
                    {
                        "pack_status": "visual_pack_ready",
                        "review_status": "agent_selected_pending_manual_review",
                        "cases": cases,
                    }
                ),
                encoding="utf-8",
            )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-source-visual-alignment-gate.config.v1",
                    "stage": "M14.strategy_source_visual_alignment_gate",
                    "inputs": {
                        "m14_strategy_source_reextract_review": str(review_path),
                        "visual_golden_case_dir": str(visual_dir),
                        "old_m10_worktree_root": str(old_root),
                    },
                    "outputs": {
                        "source_visual_alignment_gate_json": str(root / "gate.json"),
                        "source_visual_alignment_gate_md": str(root / "gate.md"),
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

    def _review_row(self, strategy_id: str, title: str) -> dict[str, object]:
        return {
            "review_id": f"source_reextract_review::{strategy_id}",
            "strategy_id": strategy_id,
            "catalog_title": title,
            "priority": "P2",
            "setup_hypothesis": "fixture_hypothesis",
            "visual_review_required": True,
            "source_backed_atoms": [{"field": "context"}] * 5,
            "source_review_answers": [{"question_id": "q"}] * 3,
        }

    def _case(self, old_root: Path, strategy_id: str, case_type: str, index: int) -> dict[str, object]:
        rel = Path("assets") / strategy_id / f"{case_type}_{index}.webp"
        path = old_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"{strategy_id}:{case_type}:{index}".encode()
        path.write_bytes(payload)
        return {
            "case_id": f"{strategy_id}-{case_type}-{index}",
            "strategy_id": strategy_id,
            "case_type": case_type,
            "brooks_unit_ref": "raw:fixture.md",
            "evidence_video_id": "video_fixture",
            "evidence_page": index,
            "evidence_image_logical_path": rel.as_posix(),
            "evidence_image_checksum": hashlib.sha256(payload).hexdigest(),
            "evidence_exists": True,
            "checksum_resolved": True,
            "review_status": "agent_selected_pending_manual_review",
            "matched_terms": ["fixture"],
            "pattern_decision_points": ["confirm visual geometry"],
            "disqualifiers": ["opposite follow-through"],
            "ohlcv_approximation_risk": "visual review required",
        }


if __name__ == "__main__":
    unittest.main()
