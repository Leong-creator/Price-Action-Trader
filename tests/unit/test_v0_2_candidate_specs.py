from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import ROOT, load_json, read_text


EXPECTED_OVERRIDES = {
    "SF-001": {
        "signal_bar_body_ratio_min": 0.5,
        "max_pullback_bars": 2,
    },
    "SF-002": {
        "breakout_bar_body_ratio_min": 0.6,
        "follow_through_bar_body_ratio_min": 0.6,
    },
    "SF-003": {
        "range_height_to_avg_bar_range_max": 6.0,
        "reversal_body_ratio_min": 0.55,
    },
    "SF-004": {
        "channel_overlap_ratio_max": 0.35,
    },
}


class TestV02CandidateSpecs(unittest.TestCase):
    def test_candidate_specs_exist_and_parse(self) -> None:
        for strategy_id in EXPECTED_OVERRIDES:
            path = ROOT / "reports" / "strategy_lab" / "specs" / f"{strategy_id}-v0.2-candidate.yaml"
            self.assertTrue(path.exists(), path)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["strategy_id"], strategy_id)
            self.assertEqual(payload["spec_version"], "v0.2-candidate")
            self.assertEqual(payload["selected_variant_id"], "quality_filter")
            self.assertEqual(payload["selected_variant_role"], "diagnostic_selected_variant")
            self.assertEqual(payload["candidate_status"], "frozen_candidate")

    def test_candidate_specs_bind_wave2_evidence(self) -> None:
        required_artifact_keys = {
            "batch_summary_json",
            "triage_matrix_json",
            "strategy_summary_json",
            "strategy_diagnostics_md",
            "selected_variant_summary_json",
            "trade_report_md",
            "cash_report_md",
        }
        required_claims = {
            "not_validated_production_strategy",
            "not_approved_for_live_or_real_money",
            "derived_only_from_wave2_observed_quality_filter",
        }
        for strategy_id in EXPECTED_OVERRIDES:
            path = ROOT / "reports" / "strategy_lab" / "specs" / f"{strategy_id}-v0.2-candidate.yaml"
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            base_spec_ref = payload["base_spec_ref"]
            self.assertTrue((ROOT / base_spec_ref).exists(), base_spec_ref)
            self.assertEqual(set(payload["wave2_artifacts"].keys()), required_artifact_keys)
            for artifact_path in payload["wave2_artifacts"].values():
                self.assertTrue((ROOT / artifact_path).exists(), artifact_path)
            self.assertTrue(required_claims.issubset(set(payload["validation_claims"])))

    def test_rule_overrides_match_wave2_tested_quality_filters(self) -> None:
        for strategy_id, expected in EXPECTED_OVERRIDES.items():
            path = ROOT / "reports" / "strategy_lab" / "specs" / f"{strategy_id}-v0.2-candidate.yaml"
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["rule_overrides"], expected)

    def test_catalog_freeze_semantics_unchanged_and_sf005_not_included(self) -> None:
        catalog = load_json("reports/strategy_lab/strategy_catalog.json")
        self.assertEqual(catalog["catalog_status"], "frozen")
        self.assertEqual(catalog["final_strategy_count"], 5)
        strategy_ids = [entry["strategy_id"] for entry in catalog["strategies"]]
        self.assertEqual(strategy_ids, [f"SF-{index:03d}" for index in range(1, 6)])
        self.assertFalse(
            (ROOT / "reports" / "strategy_lab" / "specs" / "SF-005-v0.2-candidate.yaml").exists()
        )

    def test_freeze_summary_records_candidate_semantics(self) -> None:
        summary = read_text("reports/strategy_lab/v0_2_spec_freeze_summary.md")
        self.assertIn("diagnostic_selected_variant", summary)
        self.assertIn("本轮未新增任何未测试过滤器", summary)
        self.assertIn("SF-005", summary)
        self.assertIn("deferred_single_source_risk", summary)


if __name__ == "__main__":
    unittest.main()
