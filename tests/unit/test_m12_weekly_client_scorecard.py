from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import m12_weekly_client_scorecard_lib as MODULE


OUTPUT_DIR = MODULE.M12_6_DIR


class M12WeeklyClientScorecardTests(unittest.TestCase):
    def test_generated_summary_rolls_up_observation_scanner_visual_and_definition(self) -> None:
        config = MODULE.load_scorecard_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_weekly_client_scorecard(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-27T13:00:00Z",
            )
            with (Path(tmp) / "m12_6_strategy_dashboard.csv").open(newline="", encoding="utf-8") as handle:
                dashboard_rows = list(csv.DictReader(handle))

        self.assertEqual(summary["strategy_count"], 16)
        self.assertEqual(len(dashboard_rows), 16)
        self.assertEqual(summary["daily_observation"]["event_count"], 32)
        self.assertEqual(summary["daily_observation"]["candidate_event_count"], 0)
        self.assertEqual(summary["scanner"]["universe_symbol_count"], 147)
        self.assertEqual(summary["scanner"]["candidate_count"], 12)
        self.assertEqual(summary["scanner"]["deferred_symbol_count"], 143)
        self.assertEqual(summary["visual_review"]["case_count"], 30)
        self.assertFalse(summary["definition_fix"]["pa005_definition_cleared"])
        self.assertEqual(summary["trading_status"], "closed_not_authorized")

    def test_dashboard_strategy_actions_match_current_plan(self) -> None:
        config = MODULE.load_scorecard_config()
        with tempfile.TemporaryDirectory() as tmp:
            MODULE.run_m12_weekly_client_scorecard(replace(config, output_dir=Path(tmp)))
            with (Path(tmp) / "m12_6_strategy_dashboard.csv").open(newline="", encoding="utf-8") as handle:
                rows = {row["strategy_id"]: row for row in csv.DictReader(handle)}

        self.assertEqual(rows["M10-PA-001"]["current_week_status"], "continue_read_only_observation")
        self.assertEqual(rows["M10-PA-002"]["current_week_status"], "continue_read_only_observation")
        self.assertEqual(rows["M10-PA-012"]["current_week_status"], "continue_read_only_observation")
        self.assertEqual(rows["M10-PA-008"]["current_week_status"], "manual_visual_review_required")
        self.assertEqual(rows["M10-PA-009"]["current_week_status"], "manual_visual_review_required")
        self.assertEqual(rows["M10-PA-005"]["current_week_status"], "definition_fix_required")
        self.assertEqual(rows["M10-PA-014"]["current_week_status"], "not_independent_trigger")
        self.assertEqual(rows["M10-PA-015"]["current_week_status"], "not_independent_trigger")
        self.assertEqual(rows["M10-PA-001"]["scanner_candidates"], "6")
        self.assertEqual(rows["M10-PA-012"]["scanner_candidates"], "6")
        self.assertEqual(rows["M10-PA-002"]["scanner_candidates"], "0")

    def test_report_and_outputs_avoid_trading_approval_claims(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_weekly_client_scorecard.py before full validation")
        combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in OUTPUT_DIR.glob("m12_6_*") if path.is_file())
        lowered = combined.lower()

        for forbidden in ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true", "paper approval"):
            self.assertNotIn(forbidden.lower(), lowered)
        self.assertIn("closed_not_authorized", combined)
        self.assertIn("不作为交易批准", combined)

    def test_required_artifacts_exist_and_handoff_has_protocol_fields(self) -> None:
        expected = {
            "m12_6_strategy_dashboard.csv",
            "m12_6_weekly_client_scorecard.md",
            "m12_6_next_week_action_plan.md",
            "m12_6_weekly_client_scorecard_summary.json",
            "m12_6_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("m12_6_*")})
        handoff = (OUTPUT_DIR / "m12_6_handoff.md").read_text(encoding="utf-8")
        for field in ("task_id:", "role:", "status:", "commands_run:", "tests_run:", "rollback_notes:"):
            self.assertIn(field, handoff)
        summary = json.loads((OUTPUT_DIR / "m12_6_weekly_client_scorecard_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["output_dir"], "reports/strategy_lab/m10_price_action_strategy_refresh/weekly_scorecard/m12_6")


if __name__ == "__main__":
    unittest.main()
