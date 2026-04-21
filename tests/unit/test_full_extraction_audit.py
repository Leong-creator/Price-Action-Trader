from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import load_json


class TestFullExtractionAudit(unittest.TestCase):
    def test_closure_and_saturation_contract(self) -> None:
        audit = load_json("reports/strategy_lab/full_extraction_audit.json")
        saturation = load_json("reports/strategy_lab/saturation_report.json")

        self.assertTrue(audit["text_extractable_closure"])
        self.assertFalse(audit["full_source_closure"])
        self.assertGreater(audit["still_blocked_partial"], 0)
        self.assertTrue(audit["ready_for_backtest"])

        self.assertEqual(saturation["required_zero_passes"], 2)
        self.assertEqual(saturation["consecutive_zero_passes"], 2)
        self.assertTrue(saturation["closure_reached"])
        self.assertEqual(len(saturation["passes"]), 2)

    def test_gap_ledger_and_notes_findings_exist(self) -> None:
        audit = load_json("reports/strategy_lab/full_extraction_audit.json")
        gaps = load_json("reports/strategy_lab/unresolved_strategy_extraction_gaps.json")

        self.assertEqual(audit["notes_zero_candidate_analysis"]["family_summary"]["reason_code"], "promotions_found_after_audit")
        self.assertEqual(len(audit["notes_zero_candidate_analysis"]["per_source_findings"]), 7)
        self.assertTrue(gaps["gaps"])
        self.assertTrue(any(item["gap_type"] == "blocked_or_partial_evidence" for item in gaps["gaps"]))


if __name__ == "__main__":
    unittest.main()
