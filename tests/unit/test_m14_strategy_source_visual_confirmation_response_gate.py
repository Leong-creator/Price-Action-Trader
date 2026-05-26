from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_source_visual_confirmation_response_gate_lib import (
    load_config,
    run_m14_strategy_source_visual_confirmation_response_gate,
)


class M14StrategySourceVisualConfirmationResponseGateTest(unittest.TestCase):
    def test_creates_pending_response_scaffold_without_unblocking_future_specs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_source_visual_confirmation_response_gate(
                load_config(config_path),
                generated_at="2026-05-27T12:00:00Z",
            )

            self.assertEqual(
                result["schema_version"],
                "m14.strategy-source-visual-confirmation-response-gate.v1",
            )
            self.assertEqual(result["summary"]["source_visual_confirmation_response_gate_row_count"], 2)
            self.assertTrue(result["summary"]["manual_visual_confirmation_response_created"])
            self.assertTrue(result["summary"]["manual_visual_confirmation_review_pack_ready"])
            self.assertEqual(result["summary"]["review_pack_question_count"], 6)
            self.assertEqual(result["summary"]["review_pack_case_asset_count"], 10)
            self.assertEqual(result["summary"]["review_pack_case_asset_exists_count"], 0)
            self.assertEqual(result["summary"]["review_pack_case_asset_missing_count"], 10)
            self.assertEqual(result["summary"]["required_question_response_count"], 6)
            self.assertEqual(result["summary"]["question_response_required_count"], 6)
            self.assertEqual(result["summary"]["confirmed_question_response_count"], 0)
            self.assertEqual(result["summary"]["question_response_confirmed_count"], 0)
            self.assertEqual(result["summary"]["pending_question_response_count"], 6)
            self.assertEqual(result["summary"]["question_response_pending_count"], 6)
            self.assertEqual(result["summary"]["required_case_response_count"], 10)
            self.assertEqual(result["summary"]["case_response_required_count"], 10)
            self.assertEqual(result["summary"]["confirmed_case_response_count"], 0)
            self.assertEqual(result["summary"]["case_response_confirmed_count"], 0)
            self.assertEqual(result["summary"]["pending_case_response_count"], 10)
            self.assertEqual(result["summary"]["case_response_pending_count"], 10)
            self.assertEqual(result["summary"]["manual_visual_confirmation_complete_count"], 0)
            self.assertEqual(result["summary"]["future_spec_unblocked_count"], 0)
            self.assertEqual(result["summary"]["ready_for_future_source_reextract_spec_draft_count"], 0)
            self.assertEqual(result["summary"]["can_create_strategy_now_count"], 0)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_now_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["strategy_state_mutation"])

            response = json.loads((root / "response.json").read_text(encoding="utf-8"))
            self.assertEqual(response["schema_version"], "m14.strategy-source-visual-confirmation-response.v1")
            self.assertEqual(len(response["response_rows"]), 2)
            self.assertIn("packet_id", response["response_rows"][0])
            self.assertIn("case_type", response["response_rows"][0]["case_responses"][0])
            self.assertTrue(
                all(
                    item["manual_response"] == "pending"
                    for row in response["response_rows"]
                    for item in row["question_responses"] + row["case_responses"]
                )
            )

            persisted = json.loads((root / "gate.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "gate.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Source Visual Confirmation Response Gate", md)
            self.assertIn("Future specs unblocked / ready-for-draft: `0/0`", md)
            review_md = (root / "review.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Source Visual Confirmation Review Pack", review_md)
            self.assertIn("Case assets existing / missing: `0/10`", review_md)
            review_html = (root / "review.html").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Source Visual Confirmation Review Pack", review_html)
            self.assertIn("Evidence asset missing", review_html)

    def test_confirmed_response_unblocks_future_spec_review_without_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            self._write_confirmed_response(root)

            result = run_m14_strategy_source_visual_confirmation_response_gate(
                load_config(config_path),
                generated_at="2026-05-27T12:30:00Z",
            )

            self.assertFalse(result["summary"]["manual_visual_confirmation_response_created"])
            self.assertEqual(result["summary"]["confirmed_question_response_count"], 6)
            self.assertEqual(result["summary"]["confirmed_case_response_count"], 10)
            self.assertEqual(result["summary"]["manual_visual_confirmation_complete_count"], 2)
            self.assertEqual(result["summary"]["future_spec_unblocked_count"], 2)
            self.assertEqual(result["summary"]["ready_for_future_source_reextract_spec_draft_count"], 2)
            self.assertEqual(result["summary"]["can_create_strategy_now_count"], 0)
            self.assertEqual(result["summary"]["can_promote_now_count"], 0)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_now_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["manual_m12_37_once"])

    def test_rejects_invalid_manual_response_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            self._write_confirmed_response(root)
            response = json.loads((root / "response.json").read_text(encoding="utf-8"))
            response["response_rows"][0]["question_responses"][0]["manual_response"] = "yes"
            (root / "response.json").write_text(json.dumps(response), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Invalid manual visual confirmation response"):
                run_m14_strategy_source_visual_confirmation_response_gate(load_config(config_path))

    def test_rejects_unknown_response_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            self._write_confirmed_response(root)
            response = json.loads((root / "response.json").read_text(encoding="utf-8"))
            response["response_rows"][0]["case_responses"][0]["case_id"] = "unknown-case"
            (root / "response.json").write_text(json.dumps(response), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Unknown manual visual confirmation case_id"):
                run_m14_strategy_source_visual_confirmation_response_gate(load_config(config_path))

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
        packet_path = root / "packet.json"
        config_path = root / "config.json"
        packet_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                    },
                    "packet_rows": [
                        self._packet_row("M10-PA-003", "Tight Channel Trend Continuation"),
                        self._packet_row("M10-PA-010", "Final Flag or Climax TBTL Reversal"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-source-visual-confirmation-response-gate.config.v1",
                    "stage": "M14.strategy_source_visual_confirmation_response_gate",
                    "inputs": {
                        "m14_strategy_source_visual_confirmation_packet": str(packet_path),
                        "manual_visual_confirmation_response": str(root / "response.json"),
                    },
                    "outputs": {
                        "source_visual_confirmation_response_gate_json": str(root / "gate.json"),
                        "source_visual_confirmation_response_gate_md": str(root / "gate.md"),
                        "source_visual_confirmation_response_review_md": str(root / "review.md"),
                        "source_visual_confirmation_response_review_html": str(root / "review.html"),
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

    def _write_confirmed_response(self, root: Path) -> None:
        response = {
            "schema_version": "m14.strategy-source-visual-confirmation-response.v1",
            "stage": "M14.strategy_source_visual_confirmation_response",
            "generated_at": "2026-05-27T12:20:00Z",
            "response_rows": [
                self._response_row("M10-PA-003"),
                self._response_row("M10-PA-010"),
            ],
        }
        (root / "response.json").write_text(json.dumps(response), encoding="utf-8")

    def _packet_row(self, strategy_id: str, title: str) -> dict[str, object]:
        return {
            "packet_id": f"source_visual_confirmation::{strategy_id}",
            "strategy_id": strategy_id,
            "catalog_title": title,
            "priority": "P2",
            "confirmation_items": [
                self._question(strategy_id, 1),
                self._question(strategy_id, 2),
                self._question(strategy_id, 3),
            ],
            "case_confirmation_rows": [
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
            "expected_visual_role": "fixture_role",
            "resolved_evidence_path": f"/tmp/{strategy_id}/{case_type}_{index}.webp",
        }

    def _response_row(self, strategy_id: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "manual_reviewer": "fixture",
            "manual_reviewed_at": "2026-05-27T12:20:00Z",
            "question_responses": [
                self._response_item(f"{strategy_id}-q1"),
                self._response_item(f"{strategy_id}-q2"),
                self._response_item(f"{strategy_id}-q3"),
            ],
            "case_responses": [
                self._response_item(f"{strategy_id}-positive-1"),
                self._response_item(f"{strategy_id}-positive-2"),
                self._response_item(f"{strategy_id}-positive-3"),
                self._response_item(f"{strategy_id}-counterexample-1"),
                self._response_item(f"{strategy_id}-boundary-1"),
            ],
        }

    def _response_item(self, item_id: str) -> dict[str, object]:
        key = "question_id" if "-q" in item_id else "case_id"
        return {
            key: item_id,
            "manual_response": "confirmed",
            "evidence_checked": True,
            "review_note": "fixture confirmed",
        }


if __name__ == "__main__":
    unittest.main()
