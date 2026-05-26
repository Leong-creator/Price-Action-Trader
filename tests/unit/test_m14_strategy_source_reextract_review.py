from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_source_reextract_review_lib import (
    load_config,
    run_m14_strategy_source_reextract_review,
)


class M14StrategySourceReextractReviewTest(unittest.TestCase):
    def test_builds_source_reextract_review_packets_without_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_source_reextract_review(
                load_config(config_path),
                generated_at="2026-05-27T09:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.strategy-source-reextract-review.v1")
            self.assertEqual(result["summary"]["source_reextract_review_row_count"], 2)
            self.assertEqual(result["summary"]["candidate_strategy_count"], 2)
            self.assertEqual(result["summary"]["source_backed_atom_count"], 10)
            self.assertEqual(result["summary"]["source_review_answer_count"], 6)
            self.assertEqual(result["summary"]["markdown_source_ref_exists_count"], 6)
            self.assertEqual(result["summary"]["future_spec_draftable_count"], 2)
            self.assertEqual(result["summary"]["visual_review_required_count"], 2)
            self.assertEqual(result["summary"]["can_create_strategy_now_count"], 0)
            self.assertEqual(result["summary"]["can_promote_now_count"], 0)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_now_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["strategy_state_mutation"])

            rows = {row["strategy_id"]: row for row in result["review_rows"]}
            self.assertEqual(
                rows["M10-PA-003"]["setup_hypothesis"],
                "tight_channel_small_pullback_trend_continuation",
            )
            self.assertEqual(rows["M10-PA-003"]["future_spec_readiness"], "draftable_after_visual_case_alignment")
            self.assertEqual(rows["M10-PA-003"]["ohlcv_proxy_assessment"]["proxy_state"], "partially_ohlcv_approximable")
            self.assertEqual(
                rows["M10-PA-010"]["setup_hypothesis"],
                "climax_exhaustion_gap_tbtl_reversal",
            )
            self.assertEqual(rows["M10-PA-010"]["future_spec_readiness"], "draftable_as_visual_first_dual_route_spec")
            self.assertEqual(rows["M10-PA-010"]["ohlcv_proxy_assessment"]["proxy_state"], "visual_first_with_ohlcv_support")
            for row in result["review_rows"]:
                self.assertFalse(row["can_create_strategy_now"])
                self.assertFalse(row["can_close_gap_now"])
                self.assertFalse(row["can_promote_now"])
                self.assertFalse(row["can_discard_now"])
                self.assertFalse(row["parameter_mutation_allowed_now"])
                self.assertFalse(row["manual_m12_37_once_allowed"])

            persisted = json.loads((root / "review.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "review.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Source Reextract Review", md)
            self.assertIn("Review rows: `2`", md)
            self.assertIn("no strategy creation", md)

    def test_rejects_strategy_state_mutation_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["strategy_state_mutation"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "strategy_state_mutation"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        plan_path = root / "plan.json"
        config_path = root / "config.json"
        source_dir = root / "sources"
        source_dir.mkdir()
        filenames = [
            "video_014E_trends_tight_channel_small_pullback.md",
            "video_017A_tight_channels_micro_channels_definitions.md",
            "video_014C_trends_types_spike_channel_traps.md",
            "video_029A_climaxes_definition_breakout_exhaustion_vacuum_support_resistance.md",
            "video_029C_climaxes_climactic_reversals_gaps_exhaustion_measuring.md",
            "video_029E_climaxes_options_firms_failed_consecutive_climaxes.md",
        ]
        for filename in filenames:
            (source_dir / filename).write_text(f"# {filename}\n", encoding="utf-8")
        plan_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                    },
                    "plan_rows": [
                        self._plan_row(
                            "M10-PA-003",
                            "Tight Channel Trend Continuation",
                            [source_dir / filename for filename in filenames[:3]],
                        ),
                        self._plan_row(
                            "M10-PA-010",
                            "Final Flag or Climax TBTL Reversal",
                            [source_dir / filename for filename in filenames[3:]],
                        ),
                        {
                            **self._plan_row(
                                "M10-PA-006",
                                "Trading Range BLSHS Limit-Order Framework",
                                [source_dir / filenames[0]],
                            ),
                            "plan_state": "research_only_hold_no_reextract",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-source-reextract-review.config.v1",
                    "stage": "M14.strategy_source_reextract_review",
                    "inputs": {
                        "m14_strategy_source_reextract_plan": str(plan_path),
                    },
                    "outputs": {
                        "source_reextract_review_json": str(root / "review.json"),
                        "source_reextract_review_md": str(root / "review.md"),
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

    def _plan_row(self, strategy_id: str, title: str, source_paths: list[Path]) -> dict[str, object]:
        return {
            "plan_id": f"source_reextract::{strategy_id}",
            "strategy_id": strategy_id,
            "catalog_title": title,
            "priority": "P2",
            "plan_state": "future_source_reextract_candidate",
            "source_refs_to_review": [
                {
                    "source_ref": f"raw:{path}",
                    "source_family": "brooks_v2_manual_transcript",
                    "title": path.name,
                }
                for path in source_paths
            ],
        }


if __name__ == "__main__":
    unittest.main()
