from __future__ import annotations

import json
import unittest
from pathlib import Path


M10_DIR = Path("reports/strategy_lab/m10_price_action_strategy_refresh")


class M10BusinessMetricPolicyTests(unittest.TestCase):
    def test_capital_model_freezes_client_defaults(self) -> None:
        model = json.loads((M10_DIR / "m10_7_capital_model.json").read_text(encoding="utf-8"))

        self.assertEqual(model["schema_version"], "m10.7.capital-model.v1")
        self.assertEqual(model["stage"], "M10.7.business_metric_policy")
        self.assertEqual(model["currency"], "USD")
        self.assertEqual(model["account_scope"], "independent_account_per_strategy_timeframe_symbol")
        self.assertEqual(model["initial_capital"], "100000.00")
        self.assertEqual(model["risk_per_trade_percent_of_equity"], "0.50")
        self.assertFalse(model["leverage_allowed"])
        self.assertTrue(model["fractional_shares_allowed"])

    def test_capital_model_contains_required_metrics_and_cost_tiers(self) -> None:
        model = json.loads((M10_DIR / "m10_7_capital_model.json").read_text(encoding="utf-8"))
        tiers = {item["tier"]: item["slippage_bps"] for item in model["cost_sensitivity_bps"]}

        self.assertEqual(tiers, {"baseline": 1, "stress_low": 2, "stress_high": 5})
        for metric in (
            "initial_capital",
            "final_equity",
            "net_profit",
            "return_percent",
            "trade_count",
            "win_rate",
            "profit_factor",
            "max_drawdown",
            "max_consecutive_losses",
            "average_holding_bars",
        ):
            self.assertIn(metric, model["required_metrics"])

    def test_policy_and_template_keep_simulated_boundaries(self) -> None:
        model = json.loads((M10_DIR / "m10_7_capital_model.json").read_text(encoding="utf-8"))
        policy = (M10_DIR / "m10_7_business_metric_policy.md").read_text(encoding="utf-8")
        template = (M10_DIR / "m10_7_client_report_template.md").read_text(encoding="utf-8")
        combined = f"{json.dumps(model, ensure_ascii=False)}\n{policy}\n{template}".lower()

        self.assertTrue(model["boundaries"]["paper_simulated_only"])
        self.assertFalse(model["boundaries"]["broker_connection"])
        self.assertFalse(model["boundaries"]["real_account"])
        self.assertFalse(model["boundaries"]["real_orders"])
        self.assertFalse(model["boundaries"]["paper_trading_approval"])
        for forbidden in ("live-ready", "broker_connection=true", "real_orders=true", "retain", "promote"):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
