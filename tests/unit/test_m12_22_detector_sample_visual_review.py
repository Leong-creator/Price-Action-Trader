from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_22_detector_sample_visual_review_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1222DetectorSampleVisualReviewTests(unittest.TestCase):
    def test_temp_run_reviews_all_retained_events_and_all_needs_spot_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_22_detector_sample_visual_review(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(tmp),
            )
            with (Path(tmp) / "m12_22_sample_visual_review_ledger.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            packet = (Path(tmp) / "m12_22_annotated_review_packet.html").read_text(encoding="utf-8")

        self.assertEqual(summary["review_scope"], "all_m12_21_retained_candidates")
        self.assertEqual(summary["reviewed_event_count"], 4801)
        self.assertEqual(len(rows), 4801)
        self.assertEqual(summary["needs_spot_check_reviewed_count"], 371)
        self.assertGreaterEqual(summary["annotated_chart_packet_count"], 371)
        self.assertFalse(summary["can_enter_full_backtest_now"])
        self.assertFalse(summary["paper_trading_approval"])
        self.assertIn("M10-PA-004", packet)
        self.assertIn("M10-PA-007", packet)
        self.assertIn("range_high", packet)
        self.assertIn("L1", packet)
        self.assertIn("L2", packet)

    def test_checked_in_outputs_are_plain_language_and_guardrailed(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_22_detector_sample_visual_review.py first")
        expected = {
            "m12_22_sample_visual_review_summary.json",
            "m12_22_sample_visual_review_ledger.csv",
            "m12_22_sample_visual_review_report.md",
            "m12_22_annotated_review_packet.html",
            "m12_22_next_test_plan.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_22_sample_visual_review_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["reviewed_event_count"], 4801)
        self.assertEqual(summary["needs_spot_check_reviewed_count"], 371)
        self.assertFalse(summary["can_enter_full_backtest_now"])
        self.assertFalse(summary["paper_trading_approval"])
        report = (OUTPUT_DIR / "m12_22_sample_visual_review_report.md").read_text(encoding="utf-8")
        for text in ("用人话结论", "全量严格复核", "不能直接进入完整历史回测", "分策略结果"):
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
        ):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
