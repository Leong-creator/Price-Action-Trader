from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_runtime_coverage_lib import (
    load_config,
    run_m14_rescue_runtime_coverage,
)


class M14RescueRuntimeCoverageTest(unittest.TestCase):
    PA008_BROKER_RISK_CAP_SHADOW_ID = "M10-PA-008-broker-risk-cap-shadow"
    PA012_TARGET_STOP_NORMALIZED_RESCUE_ID = (
        "M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow"
    )

    def test_runner_audits_registered_rescue_runtime_coverage_without_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_config(root)

            result = run_m14_rescue_runtime_coverage(
                load_config(config_path),
                generated_at="2026-05-26T12:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-runtime-coverage.v1")
            self.assertEqual(result["registered_rescue_strategy_count"], 11)
            self.assertEqual(result["registered_rescue_account_count"], 12)
            self.assertEqual(result["connected_rescue_strategy_count"], 11)
            self.assertEqual(result["pending_rescue_strategy_ids"], [])
            self.assertTrue(result["all_registered_rescue_inputs_connected"])
            self.assertTrue(result["coverage_complete_but_not_promoted"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["paper_or_live_approval"])

            rows = {row["strategy_id"]: row for row in result["rows"]}
            self.assertIn("M10-PA-004-MBF-QC-m14-modify-20260522", rows)
            self.assertIn(self.PA008_BROKER_RISK_CAP_SHADOW_ID, rows)
            self.assertIn("M10-PA-011-ORB-R1", rows)
            self.assertIn(self.PA012_TARGET_STOP_NORMALIZED_RESCUE_ID, rows)
            for row in rows.values():
                self.assertEqual(row["coverage_status"], "connected_not_promoted")
                self.assertEqual(row["promotion_status"], "not_promoted_requires_10_day_ab_evidence")
                self.assertFalse(row["required_for_goal"])
                self.assertFalse(row["broker_connection"])
                self.assertFalse(row["real_order"])
                self.assertFalse(row["live_execution"])
                self.assertFalse(row["paper_trading_approval"])
                self.assertTrue(row["parent_strategy_id"])
                self.assertEqual(row["missing_account_spec_runtime_ids"], [])
                self.assertEqual(row["mismatched_account_spec_runtime_ids"], [])
                self.assertEqual(row["disconnected_account_spec_runtime_ids"], [])

            self.assertIn(
                "m14_rescue_pa004_mbf_qc_risk_compression_adapter",
                rows["M10-PA-004-MBF-QC-m14-modify-20260522"]["input_source_types"],
            )
            self.assertIn(
                "m14_rescue_pa011_failed_orb_retest_adapter",
                rows["M10-PA-011-ORB-R1"]["input_source_types"],
            )
            self.assertIn(
                "m14_broker_blocker_pa008_quantity_cap_adapter",
                rows[self.PA008_BROKER_RISK_CAP_SHADOW_ID]["input_source_types"],
            )
            self.assertIn(
                "m14_rescue_orb_quality_filter_adapter",
                rows["M10-PA-012-m14-modify-20260522"]["input_source_types"],
            )
            self.assertIn(
                "m14_rescue_pa012_target_stop_risk_normalized_1_0r_adapter",
                rows[self.PA012_TARGET_STOP_NORMALIZED_RESCUE_ID]["input_source_types"],
            )

            persisted = json.loads((root / "coverage.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["connected_rescue_strategy_count"], 11)
            md = (root / "coverage.md").read_text(encoding="utf-8")
            self.assertIn("Connected does not mean passed or approved", md)

    def test_plan_action_rows_are_covered_but_still_need_ab_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = run_m14_rescue_runtime_coverage(
                load_config(self._write_config(root)),
                generated_at="2026-05-26T12:00:00Z",
            )

            self.assertEqual(result["planned_action_row_count"], 10)
            self.assertEqual(result["planned_action_covered_count"], 10)
            self.assertEqual(result["pending_planned_action_strategy_ids"], [])
            plan_rows = {row["strategy_id"]: row for row in result["planned_action_rows"]}
            self.assertEqual(plan_rows["M10-PA-004-MBF"]["coverage_status"], "covered_by_existing_runtime")
            self.assertIn("M10-PA-004-MBF-QC", plan_rows["M10-PA-004-MBF"]["coverage_strategy_ids"])
            self.assertEqual(plan_rows["M10-PA-011"]["coverage_status"], "covered_by_rescue_runtime")
            self.assertIn("M10-PA-011-ORB-R1", plan_rows["M10-PA-011"]["coverage_strategy_ids"])
            for row in plan_rows.values():
                self.assertTrue(row["connected_does_not_mean_passed"])
                self.assertEqual(row["needs_ab_trading_days"], 10)
                self.assertFalse(row["broker_connection"])
                self.assertFalse(row["real_order"])
                self.assertFalse(row["live_execution"])
                self.assertFalse(row["paper_trading_approval"])

    def test_unsafe_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_config(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["broker_connection"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(config_path)

    def _write_config(self, root: Path) -> Path:
        config_path = root / "m14_rescue_runtime_coverage.json"
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.rescue-runtime-coverage.config.v1",
                    "stage": "M14.rescue_runtime_coverage",
                    "min_ab_trading_days": 10,
                    "inputs": {
                        "m13_strategy_runtime_registry": "config/examples/m13_strategy_runtime_registry.json",
                        "m14_strategy_rescue_plan": (
                            "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/"
                            "m14_strategy_rescue/m14_strategy_rescue_plan.json"
                        ),
                    },
                    "outputs": {
                        "coverage_json": str(root / "coverage.json"),
                        "coverage_md": str(root / "coverage.md"),
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path


if __name__ == "__main__":
    unittest.main()
