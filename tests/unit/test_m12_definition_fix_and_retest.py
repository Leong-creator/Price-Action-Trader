from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import m12_definition_fix_and_retest_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M12DefinitionFixAndRetestTests(unittest.TestCase):
    def test_scope_is_limited_to_three_definition_problem_strategies(self) -> None:
        config = MODULE.load_definition_fix_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_definition_fix_and_retest(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-27T12:30:00Z",
            )

        self.assertEqual(summary["strategy_ids"], list(MODULE.TARGET_IDS))
        self.assertEqual(summary["retest_completed_strategy_ids"], ["M10-PA-005"])
        self.assertEqual(summary["definition_field_only_strategy_ids"], ["M10-PA-004", "M10-PA-007"])
        self.assertFalse(summary["paper_trading_approval"])
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["live_execution"])

    def test_pa005_before_after_metrics_are_traceable_and_not_cleared(self) -> None:
        config = MODULE.load_definition_fix_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_definition_fix_and_retest(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-27T12:30:00Z",
            )
            metrics_path = Path(tmp) / "m12_4_before_after_metrics.csv"
            with metrics_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        pa005_rows = [row for row in rows if row["strategy_id"] == "M10-PA-005"]
        self.assertEqual(len(pa005_rows), 12)
        self.assertEqual({row["cost_tier"] for row in pa005_rows}, {"baseline", "stress_low", "stress_high"})
        self.assertTrue(all(row["source_metric_ref"].endswith("m10_9_before_after_metrics.csv") for row in pa005_rows))
        self.assertFalse(summary["pa005_definition_cleared"])
        self.assertTrue(all(row["definition_breadth_review_cleared"] == "false" for row in pa005_rows))
        self.assertTrue(all(row["uses_profit_curve_tuning"] == "false" for row in pa005_rows))
        required_metric_fields = {
            "before_trade_count",
            "after_trade_count",
            "before_net_profit",
            "after_net_profit",
            "before_return_percent",
            "after_return_percent",
            "before_win_rate",
            "after_win_rate",
            "before_max_drawdown",
            "after_max_drawdown",
        }
        for row in pa005_rows:
            self.assertTrue(all(row[field] for field in required_metric_fields))

    def test_visual_definition_strategies_are_not_reported_as_retested(self) -> None:
        config = MODULE.load_definition_fix_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_definition_fix_and_retest(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-27T12:30:00Z",
            )
            with (Path(tmp) / "m12_4_before_after_metrics.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(summary["visual_definition_case_count"], 10)
        for strategy_id in ("M10-PA-004", "M10-PA-007"):
            [row] = [item for item in rows if item["strategy_id"] == strategy_id]
            self.assertEqual(row["work_type"], "definition_fields_required_before_retest")
            self.assertEqual(row["retest_status"], "not_rerun_no_executable_definition_change")
            self.assertEqual(row["visual_case_count"], "5")
            self.assertEqual(row["before_trade_count"], "")
            self.assertEqual(row["after_trade_count"], "")
            self.assertIn("visual_review/m12_3_precheck", row["evidence_ref"])

    def test_source_lineage_is_limited_to_m10_clean_room_artifacts(self) -> None:
        config = MODULE.load_definition_fix_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_definition_fix_and_retest(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-27T12:30:00Z",
            )

        self.assertEqual(
            set(summary["source_refs"]),
            {"m10_9_summary", "m10_9_metrics", "m10_10_visual_gate", "m12_3_visual_precheck"},
        )
        allowed_fragments = (
            "definition_tightening/m10_9_pa_005",
            "visual_wave_b_gate/m10_10",
            "visual_review/m12_3_precheck",
        )
        for ref in summary["source_refs"].values():
            self.assertTrue(any(fragment in ref for fragment in allowed_fragments), ref)
            self.assertNotIn("PA-SC-", ref)
            self.assertNotIn("SF-", ref)

    def test_generated_outputs_keep_boundaries_and_no_profit_curve_tuning(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_definition_fix_and_retest.py before full validation")
        summary = json.loads((OUTPUT_DIR / "m12_4_definition_fix_summary.json").read_text(encoding="utf-8"))
        self.assertFalse(summary["uses_profit_curve_tuning"])
        self.assertFalse(summary["paper_trading_approval"])
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["live_execution"])
        self.assertEqual(summary["visual_definition_case_count"], 10)

        combined = "\n".join(path.read_text(encoding="utf-8") for path in OUTPUT_DIR.glob("m12_4_*") if path.is_file())
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "promote", "live-ready", "broker_connection=true", "real_orders=true"):
            self.assertNotIn(forbidden.lower(), lowered)
        self.assertNotIn("uses_profit_curve_tuning,true", lowered)


if __name__ == "__main__":
    unittest.main()
