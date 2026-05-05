import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m12_29_current_day_scan_dashboard_lib import load_config, run_m12_29_current_day_scan_dashboard


class M1246RuntimeAccountsTest(unittest.TestCase):
    def run_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_46"
            config = replace(load_config(), output_dir=output_dir)
            result = run_m12_29_current_day_scan_dashboard(
                config,
                generated_at="2026-04-29T14:00:00Z",
                execute_fetch=False,
                refresh_quotes=False,
            )
            return result

    def test_supporting_rules_do_not_become_independent_runtime_accounts(self):
        result = self.run_stage()
        runtime_ids = {row["strategy_id"] for row in result["dashboard"]["strategy_scorecard_rows"]}
        self.assertNotIn("M10-PA-006", runtime_ids)
        self.assertNotIn("M10-PA-014", runtime_ids)
        self.assertNotIn("M10-PA-015", runtime_ids)
        self.assertNotIn("M10-PA-016", runtime_ids)
        supporting_rows = result["dashboard"]["supporting_rule_ab_results"]["rows"]
        self.assertEqual(
            [row["supporting_rule_id"] for row in supporting_rows],
            ["M10-PA-006", "M10-PA-014", "M10-PA-015", "M10-PA-016"],
        )

    def test_all_runtime_accounts_keep_paper_only_boundary(self):
        result = self.run_stage()
        for row in result["dashboard"]["strategy_scorecard_rows"]:
            self.assertEqual(row["starting_capital"], "20000.00")
        self.assertTrue(result["dashboard"]["paper_simulated_only"])
        self.assertFalse(result["dashboard"]["trading_connection"])
        self.assertFalse(result["dashboard"]["real_money_actions"])
        self.assertFalse(result["dashboard"]["live_execution"])


if __name__ == "__main__":
    unittest.main()
