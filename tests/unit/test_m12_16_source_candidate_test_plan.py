from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_16_source_candidate_test_plan_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1216SourceCandidateTestPlanTests(unittest.TestCase):
    def test_temp_run_splits_six_candidates_into_actionable_queues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_16_source_candidate_test_plan(
                generated_at="2026-04-28T00:00:00Z",
                output_dir=Path(tmp),
            )

        self.assertEqual(summary["candidate_count"], 6)
        self.assertEqual(summary["daily_readonly_test_count"], 3)
        self.assertEqual(summary["filter_or_ranking_factor_count"], 2)
        self.assertEqual(summary["strict_observation_count"], 1)
        rows = {row["candidate_id"]: row for row in summary["rows"]}
        self.assertEqual(rows["M12-SRC-001"]["selected_variant"], "pullback_guard")
        self.assertEqual(rows["M12-SRC-004"]["queue"], "filter_or_ranking_factor")
        self.assertEqual(rows["M12-SRC-005"]["queue"], "filter_or_ranking_factor")
        self.assertEqual(rows["M12-SRC-006"]["queue"], "strict_observation")
        self.assertFalse(summary["paper_trading_approval"])

    def test_checked_in_artifacts_are_client_facing_and_no_trading_claims(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_16_source_candidate_test_plan.py before full validation")
        expected = {
            "m12_16_source_candidate_test_plan.json",
            "m12_16_daily_test_queue.json",
            "m12_16_filter_queue.json",
            "m12_16_observation_queue.json",
            "m12_16_source_candidate_status.md",
            "m12_16_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_16_source_candidate_test_plan.json").read_text(encoding="utf-8"))
        daily = json.loads((OUTPUT_DIR / "m12_16_daily_test_queue.json").read_text(encoding="utf-8"))
        filters = json.loads((OUTPUT_DIR / "m12_16_filter_queue.json").read_text(encoding="utf-8"))
        observation = json.loads((OUTPUT_DIR / "m12_16_observation_queue.json").read_text(encoding="utf-8"))
        self.assertEqual({row["candidate_id"] for row in daily["rows"]}, {"M12-SRC-001", "M12-SRC-002", "M12-SRC-003"})
        self.assertEqual({row["candidate_id"] for row in filters["rows"]}, {"M12-SRC-004", "M12-SRC-005"})
        self.assertEqual({row["candidate_id"] for row in observation["rows"]}, {"M12-SRC-006"})
        self.assertEqual(summary["selected_ftd_variant"], "pullback_guard")
        report = (OUTPUT_DIR / "m12_16_source_candidate_status.md").read_text(encoding="utf-8")
        for expected_text in ("用人话结论", "进入每日只读测试", "先做过滤/排名因子", "严格观察队列"):
            self.assertIn(expected_text, report)
        all_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in OUTPUT_DIR.glob("*") if path.is_file())
        for forbidden in ("live-ready", "real_orders=true", "broker_connection=true", "order_id", "fill_id", "account_id"):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
