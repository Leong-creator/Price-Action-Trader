from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import load_json


class TestStrategyFactoryBacktestEligibility(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = load_json("reports/strategy_lab/backtest_eligibility_matrix.json")
        self.records = {
            item["strategy_id"]: item
            for item in self.matrix["records"]
        }

    def test_frozen_catalog_is_five_sf_strategies(self) -> None:
        self.assertEqual(self.matrix["schema_version"], "m9-batch-backtest-v11")
        self.assertEqual(len(self.records), 5)
        self.assertEqual(set(self.records), {"SF-001", "SF-002", "SF-003", "SF-004", "SF-005"})

    def test_four_multi_source_strategies_are_eligible(self) -> None:
        for strategy_id in ("SF-001", "SF-002", "SF-003", "SF-004"):
            record = self.records[strategy_id]
            self.assertEqual(record["eligibility_status"], "eligible_for_batch_backtest")
            self.assertEqual(record["readiness_gate"], "ready")
            self.assertEqual(record["queue_kind"], "batch_backtest")
            self.assertGreaterEqual(record["source_family_support_breadth"], 2)
            self.assertNotEqual(record["family_bias_risk"], "single_source_risk")

    def test_sf005_remains_deferred_for_single_source_risk(self) -> None:
        record = self.records["SF-005"]
        self.assertEqual(record["eligibility_status"], "deferred_single_source_risk")
        self.assertEqual(record["readiness_gate"], "deferred")
        self.assertEqual(record["queue_kind"], "deferred")
        self.assertEqual(record["family_bias_risk"], "single_source_risk")
        self.assertEqual(record["source_family_support_breadth"], 1)


if __name__ == "__main__":
    unittest.main()
