from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_parameter_experiment_queue_lib import (
    load_config,
    run_m14_rescue_parameter_experiment_queue,
)


class M14RescueParameterExperimentQueueTest(unittest.TestCase):
    def test_builds_queue_without_allowing_parameter_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_rescue_parameter_experiment_queue(
                load_config(config_path),
                generated_at="2026-05-26T20:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-parameter-experiment-queue.v1")
            self.assertEqual(result["summary"]["rescue_experiment_row_count"], 5)
            self.assertEqual(result["summary"]["broker_blocker_experiment_count"], 3)
            self.assertEqual(result["summary"]["experiment_row_count"], 8)
            self.assertEqual(result["summary"]["allowed_now_count"], 0)
            self.assertEqual(result["summary"]["parameter_change_allowed_now_count"], 0)
            self.assertEqual(result["summary"]["source_parameter_change_allowed_now_count"], 0)
            self.assertEqual(result["summary"]["shadow_runtime_wait_first_ledger_count"], 1)
            self.assertEqual(result["summary"]["target_stop_experiment_count"], 1)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])
            self.assertFalse(result["m13_registry_mutation"])
            self.assertFalse(result["m12_account_specs_mutation"])
            self.assertFalse(result["broker_readiness_status_mutation"])

            rows = {row["experiment_row_id"]: row for row in result["experiment_rows"]}
            stale = rows["m14-param-exp-m10-pa-001-m14-modify-20260522"]
            self.assertEqual(stale["experiment_family"], "fresh_quote_gate_recheck")
            self.assertEqual(stale["status"], "blocked_until_fresh_refresh")
            self.assertFalse(stale["allowed_now"])
            self.assertIn("source_quote_and_signal_count", stale["candidate_change_scope"])

            reward = rows["m14-param-exp-m10-pa-012-m14-modify-20260522"]
            self.assertEqual(reward["experiment_family"], "target_stop_reward_geometry_shadow")
            self.assertIn("not_lowering_frozen_min_r", reward["candidate_parameter_family"])
            self.assertIn("Fresh refresh", reward["activation_condition"])

            missing = rows["m14-param-exp-m10-pa-008-broker-risk-cap-shadow"]
            self.assertEqual(missing["experiment_family"], "ledger_path_mapping_audit")
            self.assertEqual(missing["status"], "shadow_runtime_wait_first_ledger")

            collect = rows["m14-param-exp-m10-pa-002-m14-modify-20260522"]
            self.assertEqual(collect["experiment_family"], "continue_ab_evidence_collection")
            self.assertEqual(collect["candidate_change_scope"], "no_parameter_change")

            quantity = rows["m14-param-exp-broker-m10-pa-008-max-risk-per-order-exceeded"]
            self.assertEqual(quantity["experiment_family"], "quantity_cap_shadow")
            self.assertEqual(quantity["candidate_change_scope"], "position_sizing_risk_cap")

            exposure = rows["m14-param-exp-broker-m10-pa-005-max-total-exposure-exceeded"]
            self.assertEqual(exposure["experiment_family"], "exposure_ranker_shadow")

            cooldown = rows["m14-param-exp-broker-m10-pa-005-consecutive-losses-limit"]
            self.assertEqual(cooldown["experiment_family"], "cooldown_quality_veto_shadow")

            for row in result["experiment_rows"]:
                self.assertFalse(row["allowed_now"])
                self.assertFalse(row["m13_registry_mutation"])
                self.assertFalse(row["m12_account_specs_mutation"])
                self.assertFalse(row["broker_readiness_status_mutation"])

            persisted = json.loads((root / "queue.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"]["experiment_row_count"], 8)
            md = (root / "queue.md").read_text(encoding="utf-8")
            self.assertIn("M14 Rescue Parameter Experiment Queue", md)
            self.assertIn("Allowed now: `0`", md)

    def test_rejects_mutation_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["m13_registry_mutation"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "m13_registry_mutation"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        backlog_path = root / "backlog.json"
        zero_path = root / "zero.json"
        next_refresh_path = root / "next_refresh.json"
        target_stop_path = root / "target_stop.json"
        external_map_path = root / "external_map.json"
        project_stage_path = root / "project_stage.json"
        config_path = root / "config.json"

        backlog_path.write_text(
            json.dumps(
                {
                    "rescue_rows": [
                        self._backlog_row("M10-PA-001-m14-modify-20260522", "zero_signal_after_connection"),
                        self._backlog_row("M10-PA-012-m14-modify-20260522", "zero_signal_after_connection"),
                        self._backlog_row("M10-PA-013-m14-modify-20260522", "zero_signal_after_connection"),
                        self._backlog_row("M10-PA-008-broker-risk-cap-shadow", "missing_rescue_ledger"),
                        self._backlog_row("M10-PA-002-m14-modify-20260522", "collect_more_ab_evidence"),
                    ],
                    "broker_dry_run_blockers": [
                        {
                            "strategy_id": "M10-PA-005",
                            "priority": "P0",
                            "reason_counts": {
                                "max_total_exposure_exceeded": 1,
                                "consecutive_losses_limit": 1,
                            },
                            "symbols": ["XLY", "XLV"],
                            "source_signal_ids": ["sig-exposure", "sig-cooldown"],
                        },
                        {
                            "strategy_id": "M10-PA-008",
                            "priority": "P0",
                            "reason_counts": {"max_risk_per_order_exceeded": 1},
                            "symbols": ["ADBE"],
                            "source_signal_ids": ["sig-risk"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        zero_path.write_text(
            json.dumps(
                {
                    "rows": [
                        self._zero_row("M10-PA-001-m14-modify-20260522", "stale_quote_source_blocks_candidate"),
                        self._zero_row("M10-PA-012-m14-modify-20260522", "reward_filter_blocks_all"),
                        self._zero_row("M10-PA-013-m14-modify-20260522", "parent_detector_zero_signal_for_timeframe"),
                    ]
                }
            ),
            encoding="utf-8",
        )
        next_refresh_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "parameter_change_allowed_now_count": 0,
                    },
                    "rows": [
                        self._next_row("M10-PA-001-m14-modify-20260522", "fresh_quote_recheck"),
                        self._next_row("M10-PA-012-m14-modify-20260522", "target_stop_shadow_compare"),
                        self._next_row("M10-PA-013-m14-modify-20260522", "parent_detector_evidence_wait"),
                        self._next_row("M10-PA-008-broker-risk-cap-shadow", "first_rescue_ledger_watch"),
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
                            "dominant_target_stop_issue": "target_reward_below_1r_after_quality_gates",
                            "reward_r_min": "0.71",
                            "reward_r_max": "0.98",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        external_map_path.write_text(
            json.dumps(
                {
                    "rescue_reference_rows": [
                        self._external_row("M10-PA-001-m14-modify-20260522"),
                        self._external_row("M10-PA-012-m14-modify-20260522"),
                    ],
                    "broker_blocker_reference_rows": [
                        self._external_row("M10-PA-005"),
                        self._external_row("M10-PA-008"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        project_stage_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "current_project_stage": "M14 fixture",
                        "post_refresh_fresh_refresh_observed": False,
                        "post_refresh_source_quote": "fallback_quotes_only",
                    }
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.rescue-parameter-experiment-queue.config.v1",
                    "stage": "M14.rescue_parameter_experiment_queue",
                    "inputs": {
                        "m14_rescue_optimization_backlog": str(backlog_path),
                        "m14_rescue_zero_signal_diagnostics": str(zero_path),
                        "m14_rescue_next_refresh_readiness": str(next_refresh_path),
                        "m14_rescue_target_stop_diagnostics": str(target_stop_path),
                        "m14_rescue_external_reference_map": str(external_map_path),
                        "m14_project_stage_assessment": str(project_stage_path),
                    },
                    "outputs": {
                        "experiment_queue_json": str(root / "queue.json"),
                        "experiment_queue_md": str(root / "queue.md"),
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                        "manual_m12_37_once": False,
                        "m13_registry_mutation": False,
                        "m12_account_specs_mutation": False,
                        "broker_readiness_status_mutation": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _backlog_row(self, strategy_id: str, issue_type: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "parent_strategy_id": strategy_id.split("-m14")[0],
            "runtime_ids": [f"{strategy_id}-1d"],
            "priority": "P0",
            "issue_type": issue_type,
            "observed_trading_days_count": 1,
            "remaining_ab_trading_days": 9,
            "source_row_count": 0,
            "signal_count": 0,
            "open_count": 0,
            "risk_blocked_count": 0,
        }

    def _zero_row(self, strategy_id: str, dominant_issue: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "dominant_issue": dominant_issue,
            "eligible_if_fresh_quote_count": 3,
        }

    def _next_row(self, strategy_id: str, readiness_family: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "readiness_family": readiness_family,
        }

    def _external_row(self, strategy_id: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "local_review_lanes": ["shadow_signal_scoreboard", "risk_portfolio_review", "decision_log_audit"],
        }


if __name__ == "__main__":
    unittest.main()
