from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import load_json


class TestStrategyFactoryDatasetInventory(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = load_json("reports/strategy_lab/backtest_dataset_inventory.json")

    def test_wave2_inventory_covers_four_symbols(self) -> None:
        self.assertEqual(self.inventory["schema_version"], "m9-batch-backtest-v11")
        self.assertEqual(self.inventory["provider"], "longbridge")
        self.assertEqual(
            [item["symbol"] for item in self.inventory["datasets"]],
            ["SPY", "QQQ", "NVDA", "TSLA"],
        )

    def test_all_inventory_rows_share_same_window_and_timeframe(self) -> None:
        for item in self.inventory["datasets"]:
            self.assertEqual(item["timeframe"], "5m")
            self.assertEqual(item["start"], "2025-04-01")
            self.assertEqual(item["end"], "2026-04-21")
            self.assertIn(item["fetch_mode"], {"local_cache", "fetched_from_provider"})
            self.assertGreater(item["row_count"], 0)


if __name__ == "__main__":
    unittest.main()
