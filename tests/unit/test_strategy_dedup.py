from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import load_json


class TestStrategyDedup(unittest.TestCase):
    def test_candidate_outcomes_reference_valid_catalog_entries(self) -> None:
        catalog = load_json("reports/strategy_lab/strategy_catalog.json")
        dedup = load_json("reports/strategy_lab/strategy_dedup_map.json")
        valid_strategy_ids = {entry["strategy_id"] for entry in catalog["strategies"]}

        self.assertGreaterEqual(len(dedup["review_only_relations"]), 3)
        for record in dedup["candidate_outcomes"].values():
            if record["strategy_id"] is not None:
                self.assertIn(record["strategy_id"], valid_strategy_ids)

    def test_overmerge_review_pairs_are_structured(self) -> None:
        overmerge = load_json("reports/strategy_lab/overmerge_review.json")

        self.assertIn("reviewed_candidate_pairs", overmerge)
        self.assertIn("kept_merged_pairs", overmerge)
        self.assertIn("restored_pairs", overmerge)
        for pair in overmerge["reviewed_candidate_pairs"]:
            self.assertIn("merge_dimensions", pair)
            self.assertIn("reason", pair)
            self.assertIn("evidence_summary", pair)


if __name__ == "__main__":
    unittest.main()
