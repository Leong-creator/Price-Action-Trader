from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_19_visual_detector_prototypes_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1219VisualDetectorPrototypeTests(unittest.TestCase):
    def test_temp_run_creates_detector_candidates_without_trade_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_19_visual_detector_prototypes(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(tmp),
            )

        self.assertEqual(set(summary["strategy_scope"]), {"M10-PA-004", "M10-PA-007"})
        self.assertGreaterEqual(summary["candidate_count_by_strategy"]["M10-PA-004"], 5)
        self.assertGreaterEqual(summary["candidate_count_by_strategy"]["M10-PA-007"], 5)
        for decision in summary["strategy_decisions"].values():
            self.assertEqual(decision["decision"], "detector_prototype_ready_not_backtest_ready")
        self.assertFalse(summary["paper_trading_approval"])

    def test_checked_in_artifacts_close_waiting_state_as_detector_task(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_19_visual_detector_prototypes.py before full validation")
        expected = {
            "m12_19_visual_detector_summary.json",
            "m12_19_detector_rules.json",
            "m12_19_detector_candidates.jsonl",
            "m12_19_detector_candidates.csv",
            "m12_19_key_example_pack.json",
            "m12_19_visual_detector_report.md",
            "m12_19_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_19_visual_detector_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(set(summary["strategy_scope"]), {"M10-PA-004", "M10-PA-007"})
        self.assertIn("宽通道", "；".join(summary["detector_rules"]["M10-PA-004"]["machine_needs_to_detect"]))
        self.assertIn("第二腿", "；".join(summary["detector_rules"]["M10-PA-007"]["machine_needs_to_detect"]))
        report = (OUTPUT_DIR / "m12_19_visual_detector_report.md").read_text(encoding="utf-8")
        for expected_text in ("用人话结论", "机器检测器原型", "不是交易信号", "宽通道", "第二腿"):
            self.assertIn(expected_text, report)
        all_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in OUTPUT_DIR.glob("*") if path.is_file())
        for forbidden in ("live-ready", "real_orders=true", "broker_connection=true", "paper approval", "order_id", "fill_id", "account_id"):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
