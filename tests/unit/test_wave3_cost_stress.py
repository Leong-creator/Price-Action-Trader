from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import load_json


class TestWave3CostStress(unittest.TestCase):
    def test_cost_stress_layers_are_persisted_for_all_strategies(self) -> None:
        for strategy_id in ("SF-001", "SF-002", "SF-003", "SF-004"):
            payload = load_json(f"reports/strategy_lab/{strategy_id}/wave3/cost_stress.json")
            for layer in ("proxy_holdout", "strict_holdout", "aggregate_oos"):
                self.assertIn(layer, payload)
                self.assertEqual(
                    set(payload[layer].keys()),
                    {
                        "baseline",
                        "stress_0.05r_per_trade",
                        "stress_0.10r_per_trade",
                        "stress_0.15r_per_trade",
                    },
                )
                self.assertIn("total_pnl_r", payload[layer]["baseline"])
                self.assertIn("cash_net_pnl", payload[layer]["stress_0.10r_per_trade"])


if __name__ == "__main__":
    unittest.main()
