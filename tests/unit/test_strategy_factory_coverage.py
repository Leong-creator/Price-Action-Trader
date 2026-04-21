from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import FORMAL_CATEGORIES, load_json, load_jsonl


class TestStrategyFactoryCoverage(unittest.TestCase):
    def test_chunk_adjudication_covers_every_parseable_chunk_once(self) -> None:
        audit = load_json("reports/strategy_lab/full_extraction_audit.json")
        adjudication = load_jsonl("reports/strategy_lab/chunk_adjudication.jsonl")

        self.assertEqual(len(adjudication), audit["total_parseable_chunks"])
        self.assertEqual(audit["unresolved_count"], 0)
        self.assertEqual(audit["unmapped_count"], 0)
        self.assertTrue({row["final_category"] for row in adjudication}.issubset(FORMAL_CATEGORIES))

        seen = {row["chunk_id"] for row in adjudication}
        self.assertEqual(len(seen), len(adjudication))

    def test_family_report_and_theme_coverage_are_complete(self) -> None:
        completeness = load_json("reports/strategy_lab/source_family_completeness_report.json")
        theme_coverage = load_json("reports/strategy_lab/source_theme_coverage.json")

        self.assertEqual(set(completeness["families"]), {"al_brooks_ppt", "fangfangtu_notes", "fangfangtu_transcript"})
        self.assertTrue(all(entry["audit_completed"] for entry in completeness["families"].values()))
        self.assertEqual(len(completeness["sources"]), 10)
        self.assertEqual(len(theme_coverage["sources"]), 10)
        self.assertTrue(all(entry["sections"] for entry in theme_coverage["sources"]))


if __name__ == "__main__":
    unittest.main()
