from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_strategy_pre_refresh_review_packet_lib import (
    load_config,
    run_m14_strategy_pre_refresh_review_packet,
)


class M14StrategyPreRefreshReviewPacketTest(unittest.TestCase):
    def test_builds_review_packet_without_closing_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_strategy_pre_refresh_review_packet(
                load_config(config_path),
                generated_at="2026-05-27T05:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.strategy-pre-refresh-review-packet.v1")
            self.assertEqual(result["summary"]["review_row_count"], 4)
            self.assertEqual(result["summary"]["held_no_pre_refresh_action_count"], 1)
            self.assertEqual(result["summary"]["p0_review_count"], 3)
            self.assertEqual(result["summary"]["p2_review_count"], 1)
            self.assertEqual(result["summary"]["m12_47_fresh_refresh_dependent_review_count"], 3)
            self.assertEqual(result["summary"]["artifact_only_review_count"], 1)
            self.assertEqual(result["summary"]["external_reference_review_row_count"], 2)
            self.assertEqual(result["summary"]["review_can_close_gap_now_count"], 0)
            self.assertEqual(result["summary"]["parameter_mutation_allowed_now_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["parameter_mutation"])

            rows = {row["strategy_id"]: row for row in result["review_rows"]}
            self.assertEqual(rows["M10-PA-004"]["review_focus"], "Confirm approved internal-sim runtime and broker-watch contracts before the next M12.47 refresh.")
            self.assertEqual(rows["M10-PA-001"]["fresh_refresh_dependency_state"], "waiting_for_m12_47_fresh_refresh")
            self.assertIn("ai_trader_shadow_signal_scoreboard", rows["M10-PA-001"]["external_reference_pattern_ids"])
            self.assertEqual(rows["M10-PA-003"]["fresh_refresh_dependency_state"], "artifact_only_pre_refresh_review")
            for row in result["review_rows"]:
                self.assertFalse(row["review_can_close_gap_now"])
                self.assertFalse(row["review_can_promote_now"])
                self.assertFalse(row["review_can_discard_now"])
                self.assertFalse(row["parameter_mutation_allowed_now"])
                self.assertFalse(row["manual_m12_37_once_allowed"])

            self.assertEqual(result["held_rows"][0]["strategy_id"], "M10-PA-004-MBF")
            persisted = json.loads((root / "review.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "review.md").read_text(encoding="utf-8")
            self.assertIn("M14 Strategy Pre-Refresh Review Packet", md)
            self.assertIn("Review rows / held rows: `4/1`", md)
            self.assertIn("No review row can close gaps", md)

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
        burndown_path = root / "burndown.json"
        external_path = root / "external.json"
        config_path = root / "config.json"
        burndown_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture stage",
                        "m14_trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                        "burndown_row_count": 5,
                    },
                    "burndown_rows": [
                        self._review_row("M10-PA-004", "P0", "approved_internal_sim_refresh", True, ["m12_47_fresh_refresh"]),
                        self._review_row("M10-PA-001", "P0", "rescue_shadow_parameter_review", True, ["m12_47_fresh_refresh", "shadow_parameter_review"]),
                        self._review_row("M10-PA-011", "P0", "first_rescue_ledger", True, ["m12_47_fresh_refresh", "first_m13_rescue_ledger"]),
                        self._review_row("M10-PA-003", "P2", "shadow_plugin_research", False, ["independent_strategy_evidence_missing"]),
                        self._held_row("M10-PA-004-MBF"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        external_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "external_reference_project_count": 2,
                    },
                    "rescue_reference_rows": [
                        {
                            "strategy_id": "M10-PA-001-m14-modify-20260522",
                            "parent_strategy_id": "M10-PA-001",
                            "external_reference_pattern_ids": [
                                "ai_trader_shadow_signal_scoreboard",
                                "tradingagents_role_decomposed_review",
                            ],
                            "pre_refresh_action": "Prepare a local shadow-signal scoreboard contract only.",
                            "local_review_lanes": ["shadow_signal_scoreboard"],
                        }
                    ],
                    "broker_blocker_reference_rows": [
                        {
                            "strategy_id": "M10-PA-004",
                            "external_reference_pattern_ids": ["tradingagents_persistent_decision_log"],
                            "pre_refresh_action": "Keep a decision log for broker-watch constraints.",
                            "local_review_lanes": ["decision_log_audit"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.strategy-pre-refresh-review-packet.config.v1",
                    "stage": "M14.strategy_pre_refresh_review_packet",
                    "inputs": {
                        "m14_strategy_evidence_gap_burndown": str(burndown_path),
                        "m14_rescue_external_reference_map": str(external_path),
                    },
                    "outputs": {
                        "review_packet_json": str(root / "review.json"),
                        "review_packet_md": str(root / "review.md"),
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
    ) -> dict[str, object]:
        actions = ["Review existing artifacts only; wait for M12.47 to own any evidence-changing refresh."] if fresh_refresh else []
        if "shadow_parameter_review" in missing:
            actions.append("Check shadow parameter families and activation gates for review readiness; do not mutate parameters.")
        if "independent_strategy_evidence_missing" in missing:
            actions.append("Recheck source evidence and keep the item in shadow/plugin/research coverage unless an independent account is justified.")
        return {
            "strategy_id": strategy_id,
            "display_name": strategy_id,
            "priority": priority,
            "sequence_rank": 10,
            "burn_down_lane": lane,
            "pre_refresh_review_available": True,
            "pre_refresh_review_actions": actions,
            "requires_m12_47_fresh_refresh": fresh_refresh,
            "next_evidence_to_collect": "fixture next evidence",
            "blocked_by": ["manual_m14_review_pending"],
            "missing_evidence_categories": missing,
        }

    def _held_row(self, strategy_id: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "display_name": strategy_id,
            "priority": "P1",
            "sequence_rank": 110,
            "burn_down_lane": "rescue_ab_collection",
            "pre_refresh_review_available": False,
            "pre_refresh_review_actions": [],
            "requires_m12_47_fresh_refresh": False,
            "next_evidence_to_collect": "10 trading-day rescue A/B evidence window.",
            "blocked_by": ["rescue_10_day_ab_window_incomplete"],
            "missing_evidence_categories": ["rescue_10_day_ab_window"],
        }


if __name__ == "__main__":
    unittest.main()
