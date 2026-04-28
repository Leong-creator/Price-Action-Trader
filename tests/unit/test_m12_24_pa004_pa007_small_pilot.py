from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_24_pa004_pa007_small_pilot_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1224Pa004Pa007SmallPilotTests(unittest.TestCase):
    def test_temp_run_uses_m12_23_gate_and_outputs_client_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_24_pa004_pa007_small_pilot(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(tmp),
            )
            with (Path(tmp) / "m12_24_pa004_pa007_metrics.csv").open(encoding="utf-8") as handle:
                metrics = list(csv.DictReader(handle))
            with (Path(tmp) / "m12_24_pa004_pa007_trade_ledger.csv").open(encoding="utf-8") as handle:
                trades = list(csv.DictReader(handle))

        self.assertEqual(summary["source_gate"], "m12_23_passed_tightening_gate")
        self.assertEqual(set(summary["strategy_ids"]), {"M10-PA-004", "M10-PA-007"})
        self.assertEqual(summary["timeframe"], "1d")
        self.assertGreater(summary["candidate_trade_count"], 0)
        self.assertGreater(summary["baseline_executed_trade_count"], 0)
        strategy_rows = [row for row in metrics if row["grain"] == "strategy" and row["cost_tier"] == "baseline"]
        self.assertEqual({row["strategy_id"] for row in strategy_rows}, {"M10-PA-004", "M10-PA-007"})
        for row in strategy_rows:
            for field in ("initial_capital", "final_equity", "net_profit", "return_percent", "win_rate", "max_drawdown_percent", "trade_count", "profit_factor"):
                self.assertNotEqual(row[field], "")
        self.assertTrue(trades)
        self.assertFalse(summary["paper_trading_approval"])
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])

    def test_checked_in_outputs_are_complete_and_safe(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_24_pa004_pa007_small_pilot.py first")
        expected = {
            "m12_24_pa004_pa007_small_pilot_summary.json",
            "m12_24_pa004_pa007_metrics.csv",
            "m12_24_pa004_pa007_trade_ledger.csv",
            "m12_24_pa004_pa007_skipped_events.csv",
            "m12_24_pa004_pa007_failure_examples.csv",
            "m12_24_pa004_pa007_decision_matrix.csv",
            "m12_24_pa004_pa007_client_report.md",
            "m12_24_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_24_pa004_pa007_small_pilot_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["strategy_ids"], ["M10-PA-004", "M10-PA-007"])
        self.assertGreater(summary["baseline_executed_trade_count"], 0)
        decisions = {row["strategy_id"]: row["decision"] for row in summary["decision_rows"]}
        self.assertIn(decisions["M10-PA-004"], {"保留图形研究", "继续收紧", "进入每日观察", "继续收集样本"})
        self.assertIn(decisions["M10-PA-007"], {"保留图形研究", "继续收紧", "进入每日观察", "继续收集样本"})
        report = (OUTPUT_DIR / "m12_24_pa004_pa007_client_report.md").read_text(encoding="utf-8")
        for text in ("先说结果", "收益率", "胜率", "最大回撤", "不是模拟买卖试运行"):
            self.assertIn(text, report)
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
