from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import load_json


ALLOWED_TRIAGE = {
    "retain_candidate",
    "modify_and_retest",
    "insufficient_sample",
    "rejected_variant",
    "parked",
}


class TestWave3Triage(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = load_json("reports/strategy_lab/wave3_robustness_summary.json")

    def test_wave3_triage_stays_within_allowed_states(self) -> None:
        for strategy in self.summary["strategies"]:
            self.assertIn(strategy["triage_status"], ALLOWED_TRIAGE)
            self.assertTrue(strategy["triage_reason"])
            self.assertIsInstance(strategy["robustness_score"], int)

    def test_retain_is_forbidden_without_strict_holdout(self) -> None:
        if self.summary["strict_holdout_available"]:
            return
        self.assertEqual(self.summary["retain_candidate_count"], 0)
        for strategy in self.summary["strategies"]:
            self.assertNotEqual(strategy["triage_status"], "retain_candidate")

    def test_r_cash_mismatch_requires_explanation(self) -> None:
        for strategy in self.summary["strategies"]:
            consistency = strategy["aggregate_oos_summary"]["r_cash_sign_consistency"]
            if consistency == "inconsistent_sign":
                self.assertIn("cash", strategy["r_cash_explanation"].lower())


if __name__ == "__main__":
    unittest.main()
