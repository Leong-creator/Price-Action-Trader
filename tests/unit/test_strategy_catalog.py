from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import ROOT, load_json


class TestStrategyCatalog(unittest.TestCase):
    def test_catalog_is_frozen_and_uses_sf_namespace(self) -> None:
        catalog = load_json("reports/strategy_lab/strategy_catalog.json")

        self.assertEqual(catalog["catalog_status"], "frozen")
        self.assertEqual(catalog["final_strategy_count"], 5)
        strategy_ids = [entry["strategy_id"] for entry in catalog["strategies"]]
        self.assertEqual(strategy_ids, [f"SF-{index:03d}" for index in range(1, 6)])

    def test_every_strategy_has_card_and_spec(self) -> None:
        catalog = load_json("reports/strategy_lab/strategy_catalog.json")
        for entry in catalog["strategies"]:
            card_path = ROOT / "reports/strategy_lab/cards" / f"{entry['strategy_id']}.md"
            spec_path = ROOT / "reports/strategy_lab/specs" / f"{entry['strategy_id']}.yaml"
            self.assertTrue(card_path.exists(), card_path)
            self.assertTrue(spec_path.exists(), spec_path)
            self.assertTrue(entry["source_refs"])
            self.assertTrue(entry["evidence_refs"])
            self.assertTrue(entry["legacy_overlap_refs"])


if __name__ == "__main__":
    unittest.main()
