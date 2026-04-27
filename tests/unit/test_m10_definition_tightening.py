from __future__ import annotations

import csv
import json
import unittest
from dataclasses import replace
from decimal import Decimal

from scripts.m10_definition_tightening_lib import (
    INTRADAY_COOLDOWN_MINUTES,
    M10_9_DIR,
    STRATEGY_ID,
    TIMEFRAMES,
    load_pa005_candidates,
    run_m10_9_definition_tightening,
    tighten_candidates,
)


class M10DefinitionTighteningTests(unittest.TestCase):
    def test_tightening_only_targets_m10_pa_005(self) -> None:
        summary = run_m10_9_definition_tightening()

        self.assertEqual(summary["strategy_id"], STRATEGY_ID)
        self.assertEqual(summary["affected_timeframes"], list(TIMEFRAMES))
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["paper_trading_approval"])

    def test_intraday_filter_reduces_candidates_without_clearing_definition(self) -> None:
        summary = run_m10_9_definition_tightening()
        rows = {row["timeframe"]: row for row in summary["filter_ledger"]}

        for timeframe in INTRADAY_COOLDOWN_MINUTES:
            self.assertLess(rows[timeframe]["after_tightening_candidates"], rows[timeframe]["before_candidates"])
            self.assertGreater(rows[timeframe]["cooldown_removed"], 0)
            self.assertFalse(rows[timeframe]["range_geometry_fields_available"])
            self.assertEqual(
                rows[timeframe]["definition_tightening_status"],
                "definition_breadth_reduced_not_cleared",
            )
        self.assertFalse(summary["definition_cleared"])

    def test_filter_does_not_use_trade_outcomes(self) -> None:
        candidates = load_pa005_candidates("5m")
        kept, ledger = tighten_candidates(candidates, "5m")
        outcome_mutated = [
            replace(
                candidate,
                exit_price=Decimal("1"),
                exit_reason="mutated_outcome_should_not_affect_filter",
                gross_r=Decimal("99"),
                baseline_net_r=Decimal("99"),
            )
            for candidate in candidates
        ]
        kept_after_mutation, _ = tighten_candidates(outcome_mutated, "5m")

        self.assertLess(len(kept), len(candidates))
        self.assertIn("20-bar", ledger.review_note)
        self.assertEqual(
            [(item.symbol, item.direction, item.signal_timestamp, item.entry_timestamp) for item in kept],
            [(item.symbol, item.direction, item.signal_timestamp, item.entry_timestamp) for item in kept_after_mutation],
        )

    def test_before_after_metrics_keep_cost_tiers_and_review_status(self) -> None:
        run_m10_9_definition_tightening()
        metrics_path = M10_9_DIR / "m10_9_before_after_metrics.csv"
        with metrics_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual({row["strategy_id"] for row in rows}, {STRATEGY_ID})
        self.assertEqual({row["cost_tier"] for row in rows}, {"baseline", "stress_low", "stress_high"})
        intraday_rows = [row for row in rows if row["timeframe"] in INTRADAY_COOLDOWN_MINUTES]
        self.assertTrue(intraday_rows)
        self.assertTrue(all(row["after_status"] == "needs_definition_fix" for row in intraday_rows))
        self.assertTrue(all(row["range_geometry_fields_available"] == "false" for row in intraday_rows))

    def test_reports_keep_legacy_and_live_boundaries(self) -> None:
        run_m10_9_definition_tightening()
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in [
                M10_9_DIR / "m10_9_retest_summary.json",
                M10_9_DIR / "m10_9_definition_filter_ledger.json",
                M10_9_DIR / "m10_9_definition_fix_report.md",
                M10_9_DIR / "m10_9_wave_a_retest_client_summary.md",
            ]
        )
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true"):
            self.assertNotIn(forbidden.lower(), lowered)

        summary = json.loads((M10_9_DIR / "m10_9_retest_summary.json").read_text(encoding="utf-8"))
        self.assertIn("range geometry", summary["definition_cleared_reason"])


if __name__ == "__main__":
    unittest.main()
