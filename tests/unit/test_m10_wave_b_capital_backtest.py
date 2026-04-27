from __future__ import annotations

import csv
import json
import unittest

from scripts.m10_wave_b_capital_backtest_lib import M10_11_DIR, run_m10_11_wave_b_capital_backtest


class M10WaveBCapitalBacktestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = run_m10_11_wave_b_capital_backtest()

    def test_wave_b_outputs_cover_queue_scope(self) -> None:
        summary = self.summary

        self.assertEqual(
            summary["wave_b_strategy_ids"],
            ["M10-PA-013", "M10-PA-003", "M10-PA-008", "M10-PA-009", "M10-PA-011"],
        )
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["paper_trading_approval"])
        self.assertGreater(summary["trade_ledger_rows"], 0)

    def test_metrics_include_client_capital_fields_for_all_wave_b_strategies(self) -> None:
        metrics_path = M10_11_DIR / "m10_11_wave_b_metrics.csv"
        with metrics_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        strategy_rows = [row for row in rows if row["grain"] == "strategy" and row["cost_tier"] == "baseline"]
        self.assertEqual(
            {row["strategy_id"] for row in strategy_rows},
            {"M10-PA-013", "M10-PA-003", "M10-PA-008", "M10-PA-009", "M10-PA-011"},
        )
        for field in ("initial_capital", "final_equity", "net_profit", "win_rate", "max_drawdown"):
            self.assertTrue(all(row[field] != "" for row in strategy_rows))

    def test_m10_pa_011_stays_intraday_only(self) -> None:
        metrics_path = M10_11_DIR / "m10_11_wave_b_metrics.csv"
        with metrics_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        pa011_timeframes = {
            row["timeframe"]
            for row in rows
            if row["strategy_id"] == "M10-PA-011" and row["grain"] == "strategy_timeframe"
        }
        self.assertEqual(pa011_timeframes, {"15m", "5m"})

    def test_detection_ledger_records_derived_lineage(self) -> None:
        ledger = json.loads((M10_11_DIR / "m10_11_wave_b_detection_ledger.json").read_text(encoding="utf-8"))

        lineage = {row["data_lineage"] for row in ledger["rows"]}
        self.assertIn("native_cache", lineage)
        self.assertIn("derived_from_5m", lineage)
        self.assertTrue(all(row["strategy_id"].startswith("M10-PA-") for row in ledger["rows"]))

    def test_trade_ledger_keeps_source_refs_and_no_order_fields(self) -> None:
        ledger_path = M10_11_DIR / "m10_11_wave_b_trade_ledger.csv"
        with ledger_path.open(newline="", encoding="utf-8") as handle:
            first_trade = next(csv.DictReader(handle))

        for field in ("event_id", "trade_id", "risk_budget", "gross_pnl", "cost_pnl", "pnl", "spec_ref", "source_ledger_ref"):
            self.assertIn(field, first_trade)
            self.assertNotEqual(first_trade[field], "")
        for forbidden_field in ("order_id", "fill_id", "position_id", "cash_balance"):
            self.assertNotIn(forbidden_field, first_trade)

    def test_reports_keep_legacy_and_live_boundaries(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in [
                M10_11_DIR / "m10_11_wave_b_capital_summary.json",
                M10_11_DIR / "m10_11_wave_b_strategy_scorecard.md",
                M10_11_DIR / "m10_11_wave_b_client_report.md",
            ]
        )
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true"):
            self.assertNotIn(forbidden.lower(), lowered)


if __name__ == "__main__":
    unittest.main()
