from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_27_pa004_retest_live_snapshot_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1227Pa004RetestLiveSnapshotTests(unittest.TestCase):
    def test_temp_run_keeps_pa004_as_retest_not_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_27_pa004_retest_live_snapshot(
                generated_at="2026-04-28T14:00:00Z",
                output_dir=Path(tmp),
            )
            with (Path(tmp) / "m12_27_pa004_cohort_decisions.csv").open(encoding="utf-8", newline="") as handle:
                decisions = {
                    row["cohort_id"]: row
                    for row in csv.DictReader(handle)
                }

        self.assertEqual(summary["stage"], "M12.27.pa004_expanded_retest_live_snapshot")
        self.assertEqual(summary["pa004_long_only_retest"]["decision"], "PA004 做多版进入下一轮观察候选")
        self.assertEqual(decisions["short_only"]["decision"], "做空版本暂不进入主线")
        self.assertIn("不直接拒绝", summary["plain_language_result"])
        self.assertFalse(summary["paper_trading_approval"])
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["live_execution"])

    def test_checked_in_outputs_include_live_snapshot_and_client_report(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_27_pa004_retest_live_snapshot.py first")
        expected = {
            "m12_27_pa004_retest_live_snapshot_summary.json",
            "m12_27_pa004_retest_metrics.csv",
            "m12_27_pa004_retest_trade_ledger.csv",
            "m12_27_pa004_symbol_diagnostics.csv",
            "m12_27_pa004_cohort_decisions.csv",
            "m12_27_pa004_retest_live_snapshot_report.md",
            "m12_27_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_27_pa004_retest_live_snapshot_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["live_readonly_snapshot"]["status"], "ok")
        self.assertGreater(summary["live_readonly_snapshot"]["row_count"], 0)
        self.assertEqual(summary["live_readonly_snapshot"]["deferred_count"], 0)
        self.assertEqual(summary["pa004_long_only_retest"]["decision"], "PA004 做多版进入下一轮观察候选")

        report = (OUTPUT_DIR / "m12_27_pa004_retest_live_snapshot_report.md").read_text(encoding="utf-8")
        for expected_text in ("用人话先说结果", "PA004", "只做多", "开盘只读测试状态", "下一步"):
            self.assertIn(expected_text, report)
        all_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in OUTPUT_DIR.glob("*") if path.is_file())
        for forbidden in (
            "live-ready",
            "real_orders=true",
            "broker_connection=true",
            "paper approval",
            "order_id",
            "fill_id",
            "account_id",
            "cash_balance",
            "position_qty",
        ):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
