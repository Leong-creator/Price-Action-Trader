from __future__ import annotations

import unittest

from scripts.m12_liquid_universe_scanner_lib import US_LIQUID_SEED_V1
from scripts.m15_universe_lib import load_m15_universe, validate_expansion


class M15UniverseTest(unittest.TestCase):
    def test_expanded_universe_preserves_local_147_prefix(self) -> None:
        expanded = load_m15_universe()
        result = validate_expansion(tuple(US_LIQUID_SEED_V1), expanded)
        self.assertTrue(result["valid"])
        self.assertEqual(result["base_count"], 147)
        self.assertEqual(result["expanded_count"], 300)
        self.assertEqual(result["added_count"], 153)


if __name__ == "__main__":
    unittest.main()
