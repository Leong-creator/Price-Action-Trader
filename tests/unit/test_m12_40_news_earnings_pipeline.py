import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m12_40_news_earnings_lib import (
    load_config,
    run_m11_7,
    run_m12_40,
    run_m12_41,
    run_m12_42,
    run_m12_43,
    run_m12_44,
    run_m12_45,
)


class M1240NewsEarningsPipelineTest(unittest.TestCase):
    def run_pipeline(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = replace(load_config(), output_root=Path(tmp.name))
        m1240 = run_m12_40(config, generated_at="2026-05-01T01:00:00Z")
        m1241 = run_m12_41(config, generated_at="2026-05-01T01:00:00Z")
        m1242 = run_m12_42(config, generated_at="2026-05-01T01:00:00Z")
        m1243 = run_m12_43(config, generated_at="2026-05-01T01:00:00Z")
        m1244 = run_m12_44(config, generated_at="2026-05-01T01:00:00Z")
        m1245 = run_m12_45(config, generated_at="2026-05-01T01:00:00Z")
        m117 = run_m11_7(config, generated_at="2026-05-01T01:00:00Z")
        return config, m1240, m1241, m1242, m1243, m1244, m1245, m117

    def test_event_tags_are_sidecar_and_detect_google(self):
        config, m1240, *_ = self.run_pipeline()
        out = config.output_root / "news_earnings" / "m12_40_event_tags"
        tags = (out / "m12_40_news_event_tags.csv").read_text(encoding="utf-8")
        self.assertTrue(m1240["google_case_detected"])
        self.assertEqual(m1240["event_tagged_signal_count"], 2)
        self.assertIn("GOOG", tags)
        self.assertIn("GOOGL", tags)
        self.assertIn("earnings_gap_opposite", tags)
        self.assertIn("paper_simulated_only", tags)
        self.assertNotIn("real_orders=true", tags)
        self.assertNotIn("broker_connection=true", tags)

    def test_news_impact_and_gap_strategy_are_observation_only(self):
        _, _, m1241, _, m1243, *_ = self.run_pipeline()
        self.assertEqual(m1241["overall_conclusion"], "risk_filter_only")
        self.assertFalse(m1241["paper_trading_approval"])
        self.assertEqual(m1243["decision"], "enter_observation_queue")
        self.assertEqual(len(m1243["google_case_rows"]), 2)
        for row in m1243["google_case_rows"]:
            self.assertEqual(row["price_confirmation_found"], "true")
            self.assertEqual(row["paper_simulated_only"], "true")
            self.assertEqual(row["real_orders"], "false")

    def test_ftd_loss_streak_guard_reduces_drawdown_without_approval(self):
        _, _, _, m1242, *_ = self.run_pipeline()
        rows = {row["variant_id"]: row for row in m1242["metric_rows"]}
        self.assertEqual(m1242["best_variant"]["variant_id"], "loss_streak_guard")
        self.assertLess(
            float(rows["loss_streak_guard"]["max_drawdown_percent"]),
            float(rows["baseline"]["max_drawdown_percent"]),
        )
        self.assertFalse(m1242["paper_trading_approval"])

    def test_scanner_and_unified_scorecard_include_news_fields(self):
        config, *_prefix, m1244, m1245, m117 = self.run_pipeline()
        scanner = config.output_root / "news_earnings" / "m12_44_data_scanner_news_expansion" / "m12_44_news_weighted_scanner_candidates.csv"
        text = scanner.read_text(encoding="utf-8")
        self.assertIn("news_priority", text)
        self.assertIn("high_risk_pause", text)
        self.assertEqual(m1244["news_tagged_candidate_count"], 2)
        self.assertEqual(m1245["portfolio_metrics"]["group"], "shared_capital_portfolio")
        self.assertFalse(m1245["paper_trading_approval"])
        self.assertFalse(m117["paper_trial_approval"])
        self.assertIn("1/10", m117["plain_language_result"])


if __name__ == "__main__":
    unittest.main()
