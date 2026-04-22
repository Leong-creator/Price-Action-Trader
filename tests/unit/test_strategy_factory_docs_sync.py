from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import load_json, read_text


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
            self.assertIn("Wave3", text)
            self.assertIn("v0.2", text)

    def test_docs_do_not_claim_batch_backtest_never_started_after_m9h(self) -> None:
        run_state = load_json("reports/strategy_lab/strategy_factory/run_state.json")
        if not str(run_state["current_phase"]).startswith("M9H."):
            self.skipTest("batch backtest phase has not started")

        targets = [
            "plans/active-plan.md",
            "docs/status.md",
            "docs/strategy-factory.md",
            "reports/strategy_lab/strategy_factory_plan.md",
        ]
        forbidden = {
            "当前仍未进入 batch backtest",
            "当前不自动进入 batch backtest；是否启动下一阶段回测需要单独 Prompt / 用户决策。",
            "未启动任何 batch backtest。",
        }
        for target in targets:
            text = read_text(target)
            for snippet in forbidden:
                self.assertNotIn(snippet, text, f"{target} still contains stale batch-backtest wording")


if __name__ == "__main__":
    unittest.main()
