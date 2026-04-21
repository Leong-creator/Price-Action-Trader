from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_json(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class TestStrategyFactoryPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.batch_summary = _load_json("reports/strategy_lab/backtest_batch_summary.json")
        self.triage = _load_json("reports/strategy_lab/strategy_triage_matrix.json")
        self.run_state = _load_json("reports/strategy_lab/strategy_factory/run_state.json")
        self.final_corroboration = _load_json(
            "reports/strategy_lab/cross_source_corroboration_final.json"
        )

    def test_pipeline_respects_frozen_catalog_and_provider_contract(self) -> None:
        self.assertEqual(self.batch_summary["frozen_strategy_count"], 5)
        self.assertEqual(self.run_state["current_phase"], "M9H.batch_backtest_triage_completed")
        self.assertEqual(self.run_state["primary_provider"], "longbridge")
        self.assertTrue(self.run_state["text_extractable_closure"])
        self.assertFalse(self.run_state["full_source_closure"])

    def test_all_reported_artifacts_exist(self) -> None:
        for result in self.batch_summary["results"]:
            for _, relative_path in result["artifact_paths"].items():
                if relative_path is None:
                    continue
                self.assertTrue((ROOT / relative_path).exists(), relative_path)

    def test_only_four_families_were_tested_and_sf005_stayed_deferred(self) -> None:
        tested = [item for item in self.batch_summary["results"] if item["backtest_status"] == "completed"]
        deferred = [item for item in self.batch_summary["results"] if item["backtest_status"] != "completed"]
        self.assertEqual(len(tested), 4)
        self.assertEqual(len(deferred), 1)
        self.assertEqual(deferred[0]["strategy_id"], "SF-005")
        support = {
            item["strategy_id"]: item["source_family_support_breadth"]
            for item in self.final_corroboration["families"]
        }
        for item in tested:
            self.assertGreaterEqual(support[item["strategy_id"]], 2)
        self.assertEqual(support["SF-005"], 1)

    def test_triage_counts_align_with_triage_matrix(self) -> None:
        counts: dict[str, int] = {}
        for record in self.triage["records"]:
            counts[record["triage_status"]] = counts.get(record["triage_status"], 0) + 1
        self.assertEqual(counts, self.batch_summary["triage_counts"])


if __name__ == "__main__":
    unittest.main()
