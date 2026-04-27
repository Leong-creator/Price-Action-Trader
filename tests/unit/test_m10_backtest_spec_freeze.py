from __future__ import annotations

import json
import unittest

from scripts.generate_m10_strategy_refresh import (
    M10_1_ALLOWED_WAVE_A_OUTCOMES,
    M10_1_BACKTEST_WAVE_A_IDS,
    M10_1_BACKTEST_WAVE_A_TIMEFRAMES,
    M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS,
    M10_1_RESEARCH_ONLY_IDS,
    M10_1_SUPPORTING_RULE_IDS,
    M10_1_VISUAL_GOLDEN_CASE_IDS,
    M10_3_COST_MODEL_POLICY,
    M10_3_NOT_ALLOWED,
    M10_3_SAMPLE_GATE_POLICY,
    STRATEGY_SEEDS,
    SourceDoc,
    build_catalog_from_docs,
    build_m10_1_review_rows,
    build_m10_1_strategy_test_queue,
    build_m10_3_backtest_spec_artifacts,
    build_strategy_catalog_m10_frozen,
    validate_m10_3_artifacts,
)


class M10BacktestSpecFreezeTests(unittest.TestCase):
    def build_m10_3_artifacts(self):
        keyword_text = " ".join(keyword for seed in STRATEGY_SEEDS for keyword in seed.keywords)
        docs = [
            SourceDoc(
                family="brooks_v2_manual_transcript",
                source_ref="raw:knowledge/raw/README.md",
                locator={"kind": "test_fixture"},
                title="M10.3 synthetic Brooks support",
                text=keyword_text,
            )
        ]
        catalog, support_matrix, _, backtest_matrix = build_catalog_from_docs(docs)
        review_rows = build_m10_1_review_rows(
            catalog=catalog,
            support_matrix=support_matrix,
            backtest_matrix=backtest_matrix,
        )
        frozen = build_strategy_catalog_m10_frozen(catalog, review_rows)
        queue = build_m10_1_strategy_test_queue(catalog)
        return build_m10_3_backtest_spec_artifacts(frozen_catalog=frozen, test_queue=queue)

    def test_m10_3_spec_index_contains_wave_a_only(self) -> None:
        specs, index, event_ledger, skip_ledger, cost_policy = self.build_m10_3_artifacts()

        self.assertEqual(
            validate_m10_3_artifacts(
                specs=specs,
                spec_index=index,
                event_definition_ledger=event_ledger,
                skip_rule_ledger=skip_ledger,
                cost_sample_policy=cost_policy,
            ),
            [],
        )
        self.assertEqual({spec["strategy_id"] for spec in specs}, set(M10_1_BACKTEST_WAVE_A_IDS))
        self.assertEqual(set(index["wave_a_strategy_ids"]), set(M10_1_BACKTEST_WAVE_A_IDS))
        excluded = set(index["excluded_strategy_ids"])
        self.assertTrue(set(M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS).issubset(excluded))
        self.assertTrue(set(M10_1_VISUAL_GOLDEN_CASE_IDS).issubset(excluded))
        self.assertTrue(set(M10_1_SUPPORTING_RULE_IDS).issubset(excluded))
        self.assertTrue(set(M10_1_RESEARCH_ONLY_IDS).issubset(excluded))

    def test_m10_3_specs_have_required_schema_and_guardrails(self) -> None:
        specs, _, _, _, _ = self.build_m10_3_artifacts()

        for spec in specs:
            self.assertEqual(spec["schema_version"], "m10.backtest-spec.v1")
            self.assertEqual(spec["stage"], "M10.3.backtest_spec_freeze")
            self.assertTrue(spec["paper_simulated_only"])
            self.assertTrue(spec["source_refs"])
            self.assertTrue(spec["event_definition"])
            self.assertTrue(spec["entry_rules"])
            self.assertTrue(spec["stop_rules"])
            self.assertTrue(spec["target_rules"])
            self.assertTrue(spec["skip_rules"])
            self.assertTrue(spec["outputs_required"])
            self.assertEqual(spec["allowed_outcomes"], list(M10_1_ALLOWED_WAVE_A_OUTCOMES))
            self.assertEqual(set(spec["not_allowed"]), set(M10_3_NOT_ALLOWED))
            self.assertFalse(spec["backtest_started"])
            self.assertEqual(spec["backtest_conclusions"], [])
            self.assertFalse(spec["retain_or_promote_allowed"])
            self.assertNotRegex(json.dumps(spec, ensure_ascii=False), r"\b(?:PA-SC|SF)-\d{3}\b")

    def test_m10_3_timeframes_and_opening_range_scope_are_locked(self) -> None:
        specs, _, _, _, _ = self.build_m10_3_artifacts()
        by_id = {spec["strategy_id"]: spec for spec in specs}

        for strategy_id, timeframes in M10_1_BACKTEST_WAVE_A_TIMEFRAMES.items():
            self.assertEqual(by_id[strategy_id]["timeframes"], list(timeframes))
        self.assertEqual(by_id["M10-PA-012"]["timeframes"], ["15m", "5m"])
        self.assertTrue(by_id["M10-PA-012"]["timeframe_policy"]["session_required"])
        session = by_id["M10-PA-012"]["event_definition"]["session"]
        self.assertEqual(session["opening_range_minutes"], 30)
        self.assertEqual(session["5m_opening_range_bars"], 6)
        self.assertEqual(session["15m_opening_range_bars"], 2)

    def test_m10_3_cost_sample_gate_and_ledgers_are_present(self) -> None:
        specs, _, event_ledger, skip_ledger, cost_policy = self.build_m10_3_artifacts()

        self.assertEqual(cost_policy["cost_model_policy"]["sensitivity_tiers"], M10_3_COST_MODEL_POLICY["sensitivity_tiers"])
        self.assertEqual(
            cost_policy["sample_gate_policy"]["minimum_candidate_events_per_strategy_timeframe"],
            M10_3_SAMPLE_GATE_POLICY["minimum_candidate_events_per_strategy_timeframe"],
        )
        self.assertEqual(
            cost_policy["sample_gate_policy"]["minimum_executed_trades_after_skips_per_strategy_timeframe"],
            M10_3_SAMPLE_GATE_POLICY["minimum_executed_trades_after_skips_per_strategy_timeframe"],
        )
        self.assertEqual({entry["strategy_id"] for entry in event_ledger["entries"]}, {spec["strategy_id"] for spec in specs})
        self.assertGreaterEqual(len(skip_ledger["entries"]), len(specs))

    def test_m10_3_supporting_rules_are_reference_only(self) -> None:
        specs, _, _, _, _ = self.build_m10_3_artifacts()

        for spec in specs:
            supporting_ids = {item["strategy_id"] for item in spec["supporting_rules"]}
            self.assertEqual(supporting_ids, {"M10-PA-014", "M10-PA-015"})
            for item in spec["supporting_rules"]:
                self.assertFalse(item["standalone_trigger_allowed"])


if __name__ == "__main__":
    unittest.main()
