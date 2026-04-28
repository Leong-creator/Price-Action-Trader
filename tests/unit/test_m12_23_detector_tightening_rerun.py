from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_23_detector_tightening_rerun_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1223DetectorTighteningRerunTests(unittest.TestCase):
    def test_temp_run_reduces_false_positive_and_borderline_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_23_detector_tightening_rerun(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(tmp),
            )
            with (Path(tmp) / "m12_23_tightened_visual_review_ledger.csv").open(encoding="utf-8") as handle:
                visual_rows = list(csv.DictReader(handle))
            audit = json.loads((Path(tmp) / "m12_23_raw_capped_audit.json").read_text(encoding="utf-8"))

        before = summary["baseline_m12_22_visual_review_counts"]
        after = summary["strict_visual_review_counts"]
        self.assertGreater(summary["strict_retained_event_count"], 0)
        self.assertEqual(len(visual_rows), summary["strict_retained_event_count"])
        self.assertLess(after["likely_false_positive"], before["likely_false_positive"])
        self.assertLess(after["borderline_needs_chart_review"], before["borderline_needs_chart_review"])
        self.assertEqual(after["likely_false_positive"], 0)
        self.assertTrue(summary["can_enter_small_pilot_next"])
        self.assertFalse(summary["can_enter_full_backtest_now"])
        self.assertFalse(summary["paper_trading_approval"])
        self.assertEqual({row["strategy_id"] for row in audit["items"]}, {"M10-PA-004", "M10-PA-007"})
        for row in audit["items"]:
            self.assertGreater(row["raw_before_tightening"], row["raw_after_tightening"])
            self.assertGreater(row["raw_after_tightening"], 0)

    def test_checked_in_outputs_are_complete_and_guardrailed(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_23_detector_tightening_rerun.py first")
        expected = {
            "m12_23_detector_tightening_summary.json",
            "m12_23_raw_capped_audit.json",
            "m12_23_raw_capped_audit.csv",
            "m12_23_tightened_detector_events.jsonl",
            "m12_23_tightened_detector_events.csv",
            "m12_23_tightened_quality_ledger.jsonl",
            "m12_23_tightened_quality_ledger.csv",
            "m12_23_tightened_visual_review_ledger.csv",
            "m12_23_before_after_comparison.csv",
            "m12_23_detector_tightening_report.md",
            "m12_23_next_step.md",
            "m12_23_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_23_detector_tightening_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["strict_visual_review_counts"]["likely_false_positive"], 0)
        self.assertLess(
            summary["strict_visual_review_counts"]["borderline_needs_chart_review"],
            summary["baseline_m12_22_visual_review_counts"]["borderline_needs_chart_review"],
        )
        self.assertTrue(summary["can_enter_small_pilot_next"])
        report = (OUTPUT_DIR / "m12_23_detector_tightening_report.md").read_text(encoding="utf-8")
        for text in ("用人话结论", "边界样例减少", "raw/capped 审计", "不是买卖信号"):
            self.assertIn(text, report)
        all_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in OUTPUT_DIR.glob("*") if path.is_file())
        for forbidden in (
            "live-ready",
            "real_orders=true",
            "broker_connection=true",
            "paper approval",
            "order_id",
            "fill_id",
            "trade_id",
            "account_id",
            "cash_balance",
            "position_qty",
            "profit_factor",
            "win_rate",
            "drawdown",
            "equity_curve",
        ):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
