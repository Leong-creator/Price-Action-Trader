from __future__ import annotations

import csv
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.m10_capital_backtest_lib import (
    CAPITAL_MODEL_PATH,
    M10_8_DIR,
    WAVE_A_IDS,
    CandidateTrade,
    load_capital_model,
    run_m10_wave_a_capital_backtest,
    simulate_account,
)


class M10WaveACapitalBacktestTests(unittest.TestCase):
    def test_simulation_uses_risk_budget_and_cost_tier(self) -> None:
        model = load_capital_model(CAPITAL_MODEL_PATH)
        candidates = [
            CandidateTrade(
                strategy_id="M10-PA-001",
                symbol="SPY",
                timeframe="5m",
                direction="long",
                signal_timestamp="2024-04-01T09:30:00-04:00",
                entry_timestamp="2024-04-01T09:35:00-04:00",
                entry_price=Decimal("100"),
                stop_price=Decimal("99"),
                target_price=Decimal("102"),
                risk_per_share=Decimal("1"),
                exit_timestamp="2024-04-01T09:45:00-04:00",
                exit_price=Decimal("102"),
                exit_reason="target_hit",
                gross_r=Decimal("2"),
                baseline_net_r=Decimal("1.99"),
                setup_notes="fixture",
            )
        ]

        trades = simulate_account(
            candidates=candidates,
            model=model,
            tier={"tier": "baseline", "slippage_bps": 1, "fee_per_order": "0.00"},
            spec_ref="spec.json",
            source_ledger_ref="source.json",
            quality_flag="normal_density_review",
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].quantity, Decimal("500.0000"))
        self.assertEqual(trades[0].equity_before, Decimal("100000.00"))
        self.assertGreater(trades[0].pnl, Decimal("0"))
        self.assertEqual(trades[0].cost_tier, "baseline")

    def test_generated_outputs_cover_wave_a_scope_and_business_metrics(self) -> None:
        summary = run_m10_wave_a_capital_backtest()
        metrics_path = M10_8_DIR / "m10_8_wave_a_metrics.csv"
        ledger_path = M10_8_DIR / "m10_8_wave_a_trade_ledger.csv"
        report_path = M10_8_DIR / "m10_8_wave_a_client_report.md"
        curves_dir = M10_8_DIR / "m10_8_wave_a_equity_curves"

        self.assertEqual(summary["wave_a_strategy_ids"], list(WAVE_A_IDS))
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertTrue(metrics_path.exists())
        self.assertTrue(ledger_path.exists())
        self.assertTrue(report_path.exists())
        self.assertTrue(any(curves_dir.glob("M10-PA-001_5m*_equity.csv")))
        self.assertTrue((curves_dir / "M10-PA-001_5m_baseline_equity.svg").exists())

        with metrics_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        with ledger_path.open(newline="", encoding="utf-8") as handle:
            first_trade = next(csv.DictReader(handle))
        baseline_strategy_rows = [
            row for row in rows if row["grain"] == "strategy" and row["cost_tier"] == "baseline"
        ]
        self.assertEqual({row["strategy_id"] for row in baseline_strategy_rows}, set(WAVE_A_IDS))
        for field in ("initial_capital", "final_equity", "net_profit", "win_rate", "max_drawdown"):
            self.assertTrue(all(row[field] != "" for row in baseline_strategy_rows))
        for field in ("event_id", "trade_id", "risk_budget", "risk_budget_quantity", "notional_cap_quantity", "gross_pnl", "cost_pnl", "pnl"):
            self.assertIn(field, first_trade)
            self.assertNotEqual(first_trade[field], "")

    def test_m10_pa_005_intraday_keeps_definition_review_status(self) -> None:
        run_m10_wave_a_capital_backtest()
        with (M10_8_DIR / "m10_8_wave_a_metrics.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        flagged = [
            row for row in rows
            if row["strategy_id"] == "M10-PA-005"
            and row["timeframe"] in {"1h", "15m", "5m"}
            and row["grain"] == "strategy_timeframe"
        ]
        self.assertTrue(flagged)
        self.assertTrue(all(row["status"] == "needs_definition_fix" for row in flagged))

    def test_missing_candidate_prices_are_skipped_without_fake_capital_result(self) -> None:
        model = load_capital_model(CAPITAL_MODEL_PATH)
        candidates = [
            CandidateTrade(
                strategy_id="M10-PA-001",
                symbol="SPY",
                timeframe="5m",
                direction="long",
                signal_timestamp="2024-04-01T09:30:00-04:00",
                entry_timestamp="2024-04-01T09:35:00-04:00",
                entry_price=Decimal("100"),
                stop_price=Decimal("100"),
                target_price=Decimal("102"),
                risk_per_share=Decimal("0"),
                exit_timestamp="2024-04-01T09:45:00-04:00",
                exit_price=Decimal("102"),
                exit_reason="target_hit",
                gross_r=Decimal("0"),
                baseline_net_r=Decimal("0"),
                setup_notes="fixture",
            )
        ]

        trades = simulate_account(
            candidates=candidates,
            model=model,
            tier={"tier": "baseline", "slippage_bps": 1, "fee_per_order": "0.00"},
            spec_ref="spec.json",
            source_ledger_ref="source.json",
            quality_flag="normal_density_review",
        )

        self.assertEqual(trades[0].skip_reason, "non_positive_stop_distance")
        self.assertEqual(trades[0].pnl, Decimal("0"))
        self.assertEqual(trades[0].equity_after, Decimal("100000.00"))

    def test_generated_reports_keep_boundaries(self) -> None:
        run_m10_wave_a_capital_backtest()
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in [
                M10_8_DIR / "m10_8_wave_a_capital_summary.json",
                M10_8_DIR / "m10_8_wave_a_strategy_scorecard.md",
                M10_8_DIR / "m10_8_wave_a_client_report.md",
            ]
        )
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true"):
            self.assertNotIn(forbidden.lower(), lowered)


if __name__ == "__main__":
    unittest.main()
