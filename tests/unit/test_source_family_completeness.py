from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import load_json


class TestSourceFamilyCompleteness(unittest.TestCase):
    def test_cross_source_corroboration_final_matches_catalog(self) -> None:
        catalog = load_json("reports/strategy_lab/strategy_catalog.json")
        corroboration = load_json("reports/strategy_lab/cross_source_corroboration_final.json")

        self.assertEqual(
            {entry["strategy_id"] for entry in catalog["strategies"]},
            {entry["strategy_id"] for entry in corroboration["families"]},
        )

    def test_source_completeness_and_bias_fields_exist(self) -> None:
        report = load_json("reports/strategy_lab/source_family_completeness_report.json")
        self.assertIn("family_bias_assessment", report)
        self.assertEqual(len(report["sources"]), 10)
        self.assertTrue(all(entry["audit_completed"] for entry in report["sources"]))


if __name__ == "__main__":
    unittest.main()
