from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_external_reference_map_lib import load_config, run_m14_rescue_external_reference_map


class M14RescueExternalReferenceMapTest(unittest.TestCase):
    def test_maps_external_patterns_to_local_rescue_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_rescue_external_reference_map(
                load_config(config_path),
                generated_at="2026-05-26T19:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-external-reference-map.v1")
            self.assertEqual(result["summary"]["mapped_rescue_row_count"], 3)
            self.assertEqual(result["summary"]["broker_blocker_reference_row_count"], 1)
            self.assertEqual(result["summary"]["next_refresh_dependent_count"], 4)
            self.assertEqual(result["summary"]["parameter_change_allowed_now_count"], 0)
            self.assertFalse(result["summary"]["copy_trading_allowed"])
            self.assertFalse(result["summary"]["external_decision_can_override_local_gate"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])

            rows = {row["strategy_id"]: row for row in result["rescue_reference_rows"]}
            missing = rows["M10-PA-008-broker-risk-cap-shadow"]
            self.assertIn("ai_trader_shadow_signal_scoreboard", missing["external_reference_pattern_ids"])
            self.assertIn("ledger-chain checklist", missing["local_application"])
            self.assertFalse(missing["parameter_change_allowed_now"])

            reward = rows["M10-PA-012-m14-modify-20260522"]
            self.assertIn("tradingagents_role_decomposed_review", reward["external_reference_pattern_ids"])
            self.assertIn("stop/target geometry", reward["local_application"])
            self.assertIn("Normalized target/stop", reward["post_refresh_acceptance_check"])

            stale = rows["M10-PA-001-m14-modify-20260522"]
            self.assertIn("ai_trader_shadow_signal_scoreboard", stale["external_reference_pattern_ids"])
            self.assertIn("stale/fallback", stale["local_application"])

            blocker = result["broker_blocker_reference_rows"][0]
            self.assertEqual(blocker["strategy_id"], "M10-PA-005")
            self.assertIn("risk/portfolio split", blocker["local_application"])
            self.assertFalse(blocker["broker_connection"])

            persisted = json.loads((root / "reference_map.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"]["mapped_rescue_row_count"], 3)
            md = (root / "reference_map.md").read_text(encoding="utf-8")
            self.assertIn("M14 Rescue External Reference Map", md)
            self.assertIn("No copy trading", md)

    def test_unsafe_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["live_execution"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "live_execution"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        stage_path = root / "stage.json"
        backlog_path = root / "backlog.json"
        zero_path = root / "zero.json"
        next_refresh_path = root / "next_refresh.json"
        target_stop_path = root / "target_stop.json"
        config_path = root / "config.json"

        stage_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture",
                        "ten_day_challenge_complete": True,
                    }
                }
            ),
            encoding="utf-8",
        )
        backlog_path.write_text(
            json.dumps(
                {
                    "rescue_rows": [
                        self._backlog_row("M10-PA-008-broker-risk-cap-shadow", "missing_rescue_ledger", "P0"),
                        self._backlog_row("M10-PA-012-m14-modify-20260522", "zero_signal_after_connection", "P0"),
                        self._backlog_row("M10-PA-001-m14-modify-20260522", "zero_signal_after_connection", "P0"),
                    ],
                    "broker_dry_run_blockers": [
                        {
                            "strategy_id": "M10-PA-005",
                            "priority": "P0",
                            "blocked_count": 2,
                            "reason_counts": {"max_total_exposure_exceeded": 1, "consecutive_losses_limit": 1},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        zero_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "strategy_id": "M10-PA-012-m14-modify-20260522",
                            "dominant_issue": "reward_filter_blocks_all",
                        },
                        {
                            "strategy_id": "M10-PA-001-m14-modify-20260522",
                            "dominant_issue": "stale_quote_source_blocks_candidate",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        next_refresh_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "next_refresh_dependent_count": 4,
                        "parameter_change_allowed_now_count": 0,
                    },
                    "rows": [
                        {
                            "strategy_id": "M10-PA-008-broker-risk-cap-shadow",
                            "readiness_family": "first_rescue_ledger_watch",
                        },
                        {
                            "strategy_id": "M10-PA-012-m14-modify-20260522",
                            "readiness_family": "target_stop_shadow_compare",
                        },
                        {
                            "strategy_id": "M10-PA-001-m14-modify-20260522",
                            "readiness_family": "fresh_quote_recheck",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        target_stop_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "strategy_id": "M10-PA-012-m14-modify-20260522",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.rescue-external-reference-map.config.v1",
                    "stage": "M14.rescue_external_reference_map",
                    "inputs": {
                        "m14_project_stage_assessment": str(stage_path),
                        "m14_rescue_optimization_backlog": str(backlog_path),
                        "m14_rescue_zero_signal_diagnostics": str(zero_path),
                        "m14_rescue_next_refresh_readiness": str(next_refresh_path),
                        "m14_rescue_target_stop_diagnostics": str(target_stop_path),
                    },
                    "outputs": {
                        "reference_map_json": str(root / "reference_map.json"),
                        "reference_map_md": str(root / "reference_map.md"),
                    },
                    "external_reference_patterns": [
                        {
                            "pattern_id": "ai_trader_shadow_signal_scoreboard",
                            "project": "HKUDS/AI-Trader",
                            "url": "https://github.com/HKUDS/AI-Trader",
                            "source_basis": "fixture",
                            "allowed_use": "fixture",
                            "forbidden_use": "fixture",
                        },
                        {
                            "pattern_id": "tradingagents_role_decomposed_review",
                            "project": "TauricResearch/TradingAgents",
                            "url": "https://github.com/TauricResearch/TradingAgents",
                            "source_basis": "fixture",
                            "allowed_use": "fixture",
                            "forbidden_use": "fixture",
                        },
                        {
                            "pattern_id": "tradingagents_persistent_decision_log",
                            "project": "TauricResearch/TradingAgents",
                            "url": "https://github.com/TauricResearch/TradingAgents",
                            "source_basis": "fixture",
                            "allowed_use": "fixture",
                            "forbidden_use": "fixture",
                        },
                    ],
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                        "manual_m12_37_once": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _backlog_row(self, strategy_id: str, issue_type: str, priority: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "parent_strategy_id": strategy_id.split("-m14")[0],
            "runtime_ids": [f"{strategy_id}-1d"],
            "priority": priority,
            "issue_type": issue_type,
        }


if __name__ == "__main__":
    unittest.main()
