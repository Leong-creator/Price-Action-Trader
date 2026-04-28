from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_18_visual_strategy_observation_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1218VisualStrategyObservationTests(unittest.TestCase):
    def test_temp_run_observes_only_m10_008_and_009(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_18_visual_strategy_observation(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(tmp),
            )

        self.assertEqual(set(summary["strategy_scope"]), {"M10-PA-008", "M10-PA-009"})
        self.assertGreater(summary["event_count_by_strategy"]["M10-PA-008"], 0)
        self.assertGreater(summary["event_count_by_strategy"]["M10-PA-009"], 0)
        self.assertEqual(summary["visual_decision_user_review_count"], 0)
        self.assertFalse(summary["paper_trading_approval"])

    def test_checked_in_artifacts_are_observation_only(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_18_visual_strategy_observation.py before full validation")
        expected = {
            "m12_18_visual_observation_summary.json",
            "m12_18_visual_observation_events.jsonl",
            "m12_18_visual_observation_events.csv",
            "m12_18_strict_definition_rules.json",
            "m12_18_visual_example_pack.json",
            "m12_18_visual_observation_report.md",
            "m12_18_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_18_visual_observation_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(set(summary["strategy_scope"]), {"M10-PA-008", "M10-PA-009"})
        self.assertIn("三次推动", "；".join(summary["strict_rules"]["M10-PA-009"]["must_have"]))
        self.assertIn("二次测试", "；".join(summary["strict_rules"]["M10-PA-008"]["must_have"]))
        report = (OUTPUT_DIR / "m12_18_visual_observation_report.md").read_text(encoding="utf-8")
        for expected_text in ("用人话结论", "不是自动买卖信号", "严格规则", "主要趋势反转", "楔形反转"):
            self.assertIn(expected_text, report)
        all_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in OUTPUT_DIR.glob("*") if path.is_file())
        for forbidden in ("live-ready", "real_orders=true", "broker_connection=true", "paper approval", "order_id", "fill_id", "account_id"):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
