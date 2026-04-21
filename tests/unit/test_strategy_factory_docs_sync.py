from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import read_text


class TestStrategyFactoryDocsSync(unittest.TestCase):
    def test_core_docs_reference_v4_audit_and_dual_closure(self) -> None:
        targets = [
            "plans/active-plan.md",
            "docs/status.md",
            "docs/acceptance.md",
            "docs/strategy-factory.md",
            "reports/strategy_lab/strategy_factory_plan.md",
        ]
        for target in targets:
            text = read_text(target)
            self.assertIn("Full Extraction", text)
            self.assertIn("full_source_closure", text)


if __name__ == "__main__":
    unittest.main()
