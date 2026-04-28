from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_15_ftd_v02_ab_retest_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1215FtdV02AbRetestTests(unittest.TestCase):
    def test_temp_run_writes_five_variants_and_client_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_15_ftd_v02_ab_retest(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(tmp),
            )
            with (Path(tmp) / "m12_15_variant_metrics.csv").open(encoding="utf-8") as handle:
                metrics_rows = list(csv.DictReader(handle))

        self.assertEqual(summary["variant_count"], 5)
        self.assertEqual(
            [row["variant_id"] for row in metrics_rows],
            ["baseline", "pullback_guard", "follow_through_confirm", "context_signal_quality", "full_v02"],
        )
        for row in metrics_rows:
            for field in (
                "initial_capital",
                "final_equity",
                "net_profit",
                "return_percent",
                "win_rate",
                "profit_factor",
                "max_drawdown_percent",
                "trade_count",
                "max_consecutive_losses",
            ):
                self.assertIn(field, row)
        self.assertTrue(summary["not_profit_curve_tuned"])
        self.assertTrue(summary["paper_simulated_only"])
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["live_execution"])
        self.assertFalse(summary["paper_trading_approval"])
        self.assertFalse(summary["best_variant"]["paper_gate_evidence_now"])

    def test_checked_in_artifacts_are_complete_and_no_real_trading_boundary(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_15_ftd_v02_ab_retest.py before full validation")
        expected = {
            "m12_15_ftd_v02_ab_retest_summary.json",
            "m12_15_best_variant.json",
            "m12_15_variant_metrics.csv",
            "m12_15_per_symbol_metrics.csv",
            "m12_15_trade_ledger.csv",
            "m12_15_equity_curves.json",
            "m12_15_ab_retest_report.md",
            "m12_15_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_15_ftd_v02_ab_retest_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["strategy_id"], "M12-FTD-001")
        self.assertEqual(summary["variant_count"], 5)
        self.assertIn(summary["best_variant"]["selected_variant_id"], {item.variant_id for item in MODULE.VARIANTS})
        self.assertTrue(summary["source_refs"])
        self.assertTrue(summary["not_profit_curve_tuned"])
        self.assertFalse(summary["paper_trading_approval"])
        report = (OUTPUT_DIR / "m12_15_ab_retest_report.md").read_text(encoding="utf-8")
        for expected_text in ("用人话结论", "净利润", "收益率", "胜率", "最大回撤", "最大连续亏损"):
            self.assertIn(expected_text, report)
        trade_header = (OUTPUT_DIR / "m12_15_trade_ledger.csv").read_text(encoding="utf-8").splitlines()[0]
        for forbidden in ("order", "fill", "position", "cash", "broker"):
            self.assertNotIn(forbidden, trade_header.lower())
        all_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in OUTPUT_DIR.glob("*") if path.is_file())
        for forbidden in ("live-ready", "real_orders=true", "broker_connection=true", "real order", "real account"):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
