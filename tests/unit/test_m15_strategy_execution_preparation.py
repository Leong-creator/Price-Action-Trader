from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m15_strategy_execution_preparation_lib import (
    load_config,
    run_m15_strategy_execution_preparation,
)


class M15StrategyExecutionPreparationTest(unittest.TestCase):
    def test_builds_monday_plan_with_first_paper_order_limited_to_pa004(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = replace(load_config(), output_dir=root)
            payload = run_m15_strategy_execution_preparation(
                config,
                generated_at="2026-05-31T02:00:00Z",
            )

            self.assertEqual(payload["summary"]["first_batch_internal_sim_count"], 4)
            self.assertEqual(payload["summary"]["first_paper_order_strategy_id"], "M10-PA-004")
            first_batch = {row["runtime_id"]: row for row in payload["first_batch_internal_sim"]}
            self.assertEqual(first_batch["M10-PA-004-long-1d"]["longbridge_paper_scope"], "first_order_candidate_after_user_approval")
            self.assertEqual(first_batch["M10-PA-005-5m"]["position_size_multiplier"], "0.25")
            self.assertEqual(first_batch["M10-PA-008-1d"]["position_size_multiplier"], "0.25")
            self.assertFalse(payload["broker_connection"])
            self.assertFalse(payload["real_order"])
            self.assertFalse(payload["live_execution"])
            self.assertFalse(payload["paper_trading_approval"])
            self.assertFalse(payload["credential_injection_allowed_now"])
            self.assertFalse(payload["manual_m12_37_once"])

            persisted = json.loads((root / "m15_strategy_execution_preparation.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], payload["summary"])
            md = (root / "m15_strategy_execution_preparation.md").read_text(encoding="utf-8")
            self.assertIn("M10-PA-004-long-1d", md)
            self.assertIn("M10-PA-005-5m", md)

    def test_auxiliary_modules_are_explicit_not_pause_or_research_hold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload = run_m15_strategy_execution_preparation(
                replace(load_config(), output_dir=root),
                generated_at="2026-05-31T02:00:00Z",
            )

            auxiliary = {row["strategy_id"]: row for row in payload["auxiliary_modules"]}
            for strategy_id in ("M10-PA-003", "M10-PA-006", "M10-PA-010", "M10-PA-014", "M10-PA-015", "M10-PA-016"):
                self.assertEqual(auxiliary[strategy_id]["runtime_role"], "auxiliary_module")
                self.assertFalse(auxiliary[strategy_id]["standalone_trading_allowed"])
                self.assertIn("辅助模块", auxiliary[strategy_id]["display_action"])

            text = json.dumps(payload, ensure_ascii=False) + (root / "m15_strategy_execution_preparation.md").read_text(encoding="utf-8")
            self.assertNotIn("继续观察", text)
            self.assertNotIn("研究保留", text)
            self.assertNotIn("historical_net_profit", text)
            self.assertNotIn("历史净利润", text)

    def test_repair_queue_has_specific_fix_steps_and_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload = run_m15_strategy_execution_preparation(
                replace(load_config(), output_dir=root),
                generated_at="2026-05-31T02:00:00Z",
            )

            repairs = {row["runtime_id"]: row for row in payload["repair_execution_queue"]}
            self.assertEqual(payload["summary"]["repair_priority_counts"], {"P0": 4, "P1": 5})
            self.assertTrue(payload["summary"]["repair_queue_ready_before_monday"])

            pa001 = repairs["M10-PA-001-1d"]
            self.assertEqual(pa001["action_state"], "repair_now")
            self.assertEqual(pa001["position_size_multiplier"], "0.10")
            self.assertIn("入场质量", "".join(pa001["fix_steps"]))
            self.assertIn("连续亏损", "".join(pa001["fix_steps"]))
            self.assertFalse(pa001["broker_paper_start_allowed"])

            pa002_5m = repairs["M10-PA-002-5m"]
            self.assertIn("假突破", "".join(pa002_5m["fix_steps"]))
            self.assertIn("冷却", "".join(pa002_5m["fix_steps"]))
            self.assertEqual(pa002_5m["longbridge_paper_scope"], "blocked_until_repaired")

            pa007 = repairs["M10-PA-007-1d"]
            self.assertIn("第二腿", "".join(pa007["fix_steps"]))
            self.assertIn("图形证据", "".join(pa007["acceptance_checks"]))

            ftd = repairs["M12-FTD-001-baseline-1d"]
            self.assertIn("趋势过滤", "".join(ftd["fix_steps"]))
            self.assertIn("loss-streak-guard", "".join(ftd["fix_steps"]))

            text = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("不批准", text)
            self.assertNotIn("继续观察", text)
            self.assertNotIn("waiting_for_review", text)

    def test_rejects_unsafe_boundary_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            payload = {
                "stage": "M15.strategy_execution_preparation",
                "output_dir": str(root / "out"),
                "hard_boundaries": {
                    "paper_simulated_only": True,
                    "internal_simulated_account": True,
                    "broker_connection": True,
                },
            }
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "broker_connection"):
                load_config(config_path)


if __name__ == "__main__":
    unittest.main()
