import unittest

from scripts.m13_daily_strategy_test_runner_lib import (
    PLUGIN_ROLE,
    VALID_DAILY_STATES,
    load_config,
    load_registry,
)


class M13StrategyRuntimeRegistryTest(unittest.TestCase):
    def test_registry_declares_required_daily_states(self):
        config = load_config()
        registry = load_registry(config.registry_path)
        self.assertEqual(set(registry["required_daily_states"]), VALID_DAILY_STATES)

    def test_registry_covers_required_m10_m12_runtime_scope(self):
        config = load_config()
        registry = load_registry(config.registry_path)
        ids = {row["strategy_id"] for row in registry["strategies"]}
        required = {
            "M10-PA-001",
            "M10-PA-002",
            "M10-PA-003",
            "M10-PA-004",
            "M10-PA-005",
            "M10-PA-006",
            "M10-PA-007",
            "M10-PA-008",
            "M10-PA-009",
            "M10-PA-011",
            "M10-PA-012",
            "M10-PA-013",
            "M10-PA-014",
            "M10-PA-015",
            "M10-PA-016",
            "M12-FTD-001",
        }
        self.assertTrue(required.issubset(ids))

    def test_supporting_rules_are_plugins_not_independent_accounts(self):
        config = load_config()
        registry = load_registry(config.registry_path)
        by_id = {row["strategy_id"]: row for row in registry["strategies"]}
        for strategy_id in ["M10-PA-003", "M10-PA-006", "M10-PA-014", "M10-PA-015", "M10-PA-016"]:
            row = by_id[strategy_id]
            self.assertEqual(row["module_role"], PLUGIN_ROLE)
            self.assertEqual(row.get("runtime_accounts", []), [])
            self.assertTrue(row["plugin_targets"])

    def test_ai_trader_is_external_research_only(self):
        config = load_config()
        registry = load_registry(config.registry_path)
        row = {item["strategy_id"]: item for item in registry["strategies"]}["AI-TRADER-EXTERNAL"]
        self.assertEqual(row["module_role"], "external_research")
        self.assertFalse(row["required_for_goal"])
        self.assertIn("copy_trading_or_direct_execution", registry["ai_trader_policy"]["forbidden"])

    def test_pa004_momentum_variant_is_separate_optional_runtime(self):
        config = load_config()
        registry = load_registry(config.registry_path)
        rows = {item["strategy_id"]: item for item in registry["strategies"]}
        original = rows["M10-PA-004-MBF"]
        self.assertEqual(original["module_role"], "independent_runtime")
        self.assertFalse(original["required_for_goal"])
        self.assertEqual(original["runtime_accounts"][0]["runtime_id"], "M10-PA-004-MBF-1d")
        self.assertIn("do not overwrite PA004", original["next_action"])

        quality = rows["M10-PA-004-MBF-QC"]
        self.assertEqual(quality["module_role"], "independent_runtime")
        self.assertFalse(quality["required_for_goal"])
        self.assertEqual(quality["runtime_accounts"][0]["runtime_id"], "M10-PA-004-MBF-QC-1d")
        self.assertIn("keep the original PA004-MBF account running", quality["next_action"])


if __name__ == "__main__":
    unittest.main()
