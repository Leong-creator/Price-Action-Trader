from __future__ import annotations

import unittest

from src.strategy import discover_golden_cases, reference_exists


class GoldenCatalogSmokeTests(unittest.TestCase):
    def test_catalog_is_discoverable_and_references_real_sources(self) -> None:
        cases = discover_golden_cases()

        self.assertGreaterEqual(len(cases), 5)
        self.assertEqual(len({case.case_id for case in cases}), len(cases))
        for case in cases:
            self.assertTrue(case.case_id)
            self.assertTrue(case.market)
            self.assertTrue(case.timeframe)
            self.assertTrue(case.allowed_actions)
            self.assertTrue(case.must_explain)
            self.assertTrue(case.must_not_claim)
            for reference in case.required_source_refs:
                self.assertTrue(reference_exists(reference), msg=f"missing golden-case ref: {reference}")


if __name__ == "__main__":
    unittest.main()
