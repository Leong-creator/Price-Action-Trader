from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import m12_14_source_strategy_closure_lib as MODULE


class M1214SourceStrategyClosureTests(unittest.TestCase):
    def test_temp_run_outputs_multisource_early_strategy_and_closed_visual_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(MODULE, "OUTPUT_DIR", Path(tmp)):
                summary = MODULE.run_m12_14_source_strategy_closure(generated_at="2026-04-28T00:00:00Z")
                definition = json.loads((Path(tmp) / "m12_14_early_strategy_multisource_definition_ledger.json").read_text(encoding="utf-8"))
                candidates = json.loads((Path(tmp) / "m12_14_source_revisit_strategy_candidates.json").read_text(encoding="utf-8"))
                visual = json.loads((Path(tmp) / "m12_14_visual_decision_ledger.json").read_text(encoding="utf-8"))
                closure = json.loads((Path(tmp) / "m12_14_definition_closure.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["early_strategy_result"]["strategy_id"], "M12-FTD-001")
        self.assertEqual(summary["source_revisit_candidate_count"], 6)
        self.assertEqual(summary["visual_needs_user_review_count"], 0)
        self.assertEqual(definition["source_families"], [
            "fangfangtu_notes",
            "fangfangtu_youtube_transcript",
            "brooks_v2_manual_transcript",
            "al_brooks_ppt_or_supporting_source_pages",
        ])
        fields = {item["field"] for item in definition["upgrade_fields"]}
        self.assertTrue({"行情背景", "信号K质量", "长回调保护", "入场确认"} <= fields)
        self.assertFalse(any(item["needs_user_review"] for item in visual["case_decisions"]))
        self.assertEqual({item["strategy_id"] for item in visual["strategy_decisions"]}, {"M10-PA-008", "M10-PA-009"})
        self.assertEqual({item["strategy_id"] for item in closure["strategy_rows"]}, {"M10-PA-005", "M10-PA-004", "M10-PA-007"})
        self.assertEqual(candidates["candidates"][0]["candidate_id"], "M12-SRC-001")

    def test_checked_in_artifacts_are_plain_language_and_do_not_use_legacy_strategy_sources(self) -> None:
        output = MODULE.OUTPUT_DIR
        self.assertTrue(output.exists(), "Run scripts/run_m12_14_source_strategy_closure.py before validation")
        summary = json.loads((output / "m12_14_summary.json").read_text(encoding="utf-8"))
        definition = json.loads((output / "m12_14_early_strategy_multisource_definition_ledger.json").read_text(encoding="utf-8"))
        candidates = json.loads((output / "m12_14_source_revisit_strategy_candidates.json").read_text(encoding="utf-8"))
        visual = json.loads((output / "m12_14_visual_decision_ledger.json").read_text(encoding="utf-8"))
        report = (output / "m12_14_early_strategy_upgrade_plan.md").read_text(encoding="utf-8")

        self.assertIn("收益", report)
        self.assertIn("最大回撤", report)
        self.assertIn("胜率", report)
        self.assertEqual(summary["visual_cases_closed_without_user_review"], 4)
        self.assertEqual(summary["visual_needs_user_review_count"], 0)
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["live_execution"])
        self.assertEqual(definition["current_m12_12_metrics"]["return_percent"], "745.13")
        self.assertEqual(definition["current_m12_12_metrics"]["max_drawdown_percent"], "49.04")
        self.assertIn("fangfangtu_youtube_transcript", definition["source_families"])
        self.assertIn("brooks_v2_manual_transcript", definition["source_families"])
        for candidate in candidates["candidates"]:
            joined = "\n".join(candidate["source_refs"])
            self.assertNotIn("PA-SC-", joined)
            self.assertNotIn("SF-", joined)
        old_decisions = {item["case_id"]: item["old_decision"] for item in visual["case_decisions"]}
        self.assertEqual(old_decisions["M10-PA-008-boundary-001"], "ambiguous")
        self.assertEqual(old_decisions["M10-PA-009-boundary-001"], "ambiguous")
        self.assertTrue(all(item["direct_close"] for item in visual["case_decisions"]))


if __name__ == "__main__":
    unittest.main()
