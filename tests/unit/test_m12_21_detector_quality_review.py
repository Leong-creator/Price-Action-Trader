from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_21_detector_quality_review_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1221DetectorQualityReviewTests(unittest.TestCase):
    def test_temp_run_reviews_all_m12_20_events_and_writes_sample_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_21_detector_quality_review(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(tmp),
            )
            with (Path(tmp) / "m12_21_full_quality_ledger.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            with (Path(tmp) / "m12_21_review_sample.csv").open(encoding="utf-8") as handle:
                sample_rows = list(csv.DictReader(handle))

        self.assertEqual(summary["source_event_count"], summary["reviewed_event_count"])
        self.assertEqual(summary["reviewed_event_count"], len(rows))
        self.assertGreater(summary["reviewed_event_count"], 4000)
        self.assertGreater(summary["machine_pass_count"], 0)
        self.assertGreater(len(sample_rows), 100)
        self.assertLessEqual(len(sample_rows), MODULE.SAMPLE_LIMIT)
        self.assertEqual({row["strategy_id"] for row in rows}, {"M10-PA-004", "M10-PA-007"})
        for row in rows[:25]:
            self.assertTrue(row["event_id"])
            self.assertIn(row["quality_status"], MODULE.QUALITY_STATUSES)
            self.assertEqual(row["not_trade_signal"], "true")
            self.assertEqual(row["paper_simulated_only"], "true")
            self.assertEqual(row["broker_connection"], "false")
            self.assertEqual(row["real_orders"], "false")
            self.assertEqual(row["live_execution"], "false")

    def test_checked_in_artifacts_are_complete_and_do_not_claim_trading_results(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_21_detector_quality_review.py first")
        expected = {
            "m12_21_detector_quality_summary.json",
            "m12_21_full_quality_ledger.jsonl",
            "m12_21_full_quality_ledger.csv",
            "m12_21_review_sample.csv",
            "m12_21_review_packet.md",
            "m12_21_review_packet.html",
            "m12_21_next_action_plan.md",
            "m12_21_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_21_detector_quality_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["source_event_count"], 4801)
        self.assertEqual(summary["reviewed_event_count"], 4801)
        self.assertFalse(summary["can_enter_backtest_now"])
        self.assertFalse(summary["paper_trading_approval"])
        packet = (OUTPUT_DIR / "m12_21_review_packet.md").read_text(encoding="utf-8")
        for text in ("用人话结论", "全量复核", "不是盈利结论", "分策略结果"):
            self.assertIn(text, packet)
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
            "pnl",
            "profit_factor",
            "win_rate",
            "drawdown",
            "equity_curve",
        ):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
