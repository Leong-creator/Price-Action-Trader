from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_m10_strategy_refresh import (
    FORBIDDEN_CLEAN_ROOM_READ_PATHS,
    M10_1_ALLOWED_WAVE_A_OUTCOMES,
    M10_1_BACKTEST_WAVE_A_IDS,
    M10_1_BACKTEST_WAVE_A_TIMEFRAMES,
    M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS,
    M10_1_RESEARCH_ONLY_IDS,
    M10_1_SUPPORTING_RULE_IDS,
    M10_1_VISUAL_GOLDEN_CASE_IDS,
    M10_2_VISUAL_CASE_COUNTS,
    STRATEGY_SEEDS,
    SourceDoc,
    assert_clean_room_inputs,
    build_catalog_from_docs,
    build_m10_1_review_rows,
    build_m10_1_strategy_test_queue,
    build_m10_2_visual_artifacts,
    build_m10_3_backtest_spec_handoff,
    build_strategy_catalog_m10_frozen,
    classify_support_for_strategy,
    validate_m10_1_artifacts,
    validate_m10_2_artifacts,
)


class M10StrategyRefreshTests(unittest.TestCase):
    def build_all_supported_catalog(self):
        keyword_text = " ".join(keyword for seed in STRATEGY_SEEDS for keyword in seed.keywords)
        docs = [
            SourceDoc(
                family="brooks_v2_manual_transcript",
                source_ref="raw:knowledge/raw/README.md",
                locator={"kind": "test_fixture"},
                title="M10.1 synthetic Brooks support",
                text=keyword_text,
            )
        ]
        return build_catalog_from_docs(docs)

    def build_all_supported_frozen_catalog(self):
        catalog, support_matrix, _, backtest_matrix = self.build_all_supported_catalog()
        review_rows = build_m10_1_review_rows(
            catalog=catalog,
            support_matrix=support_matrix,
            backtest_matrix=backtest_matrix,
        )
        return build_strategy_catalog_m10_frozen(catalog, review_rows), catalog

    def build_fake_brooks_evidence_root(self, root: Path) -> None:
        evidence_dir = root / "assets" / "evidence" / "video_014E"
        evidence_dir.mkdir(parents=True)
        evidence_rows = []
        checksum_lines = []
        texts = [
            "Tight Channel small pullback trend higher time frame breakout.",
            "Micro channel not much space between the lines.",
            "Tight channel only look to sell with the trend.",
            "First reversal is usually minor and can fail.",
            "Difficult to know if breakout or tight channel; boundary example.",
            "Fallback evidence slide with chart context.",
        ]
        for index, text in enumerate(texts, start=1):
            image_name = f"case_{index:02d}.webp"
            crop_name = f"case_{index:02d}_crop.webp"
            image_bytes = f"image-{index}".encode()
            crop_bytes = f"crop-{index}".encode()
            (evidence_dir / image_name).write_bytes(image_bytes)
            (evidence_dir / crop_name).write_bytes(crop_bytes)
            checksum_lines.append(f"{hashlib.sha256(image_bytes).hexdigest()}  assets/evidence/video_014E/{image_name}")
            checksum_lines.append(f"{hashlib.sha256(crop_bytes).hexdigest()}  assets/evidence/video_014E/{crop_name}")
            evidence_rows.append(
                {
                    "source_key": "unit",
                    "page": index,
                    "page_image": f"knowledge_base_v2/assets/evidence/video_014E/{image_name}",
                    "crop_image": f"knowledge_base_v2/assets/evidence/video_014E/{crop_name}",
                    "raw_text": text,
                }
            )
        (evidence_dir / "evidence.json").write_text(json.dumps(evidence_rows), encoding="utf-8")
        checksum_lines.append(
            f"{hashlib.sha256((evidence_dir / 'evidence.json').read_bytes()).hexdigest()}  assets/evidence/video_014E/evidence.json"
        )
        (root / "assets_evidence_checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    def build_fake_visual_frozen_catalog(self):
        frozen, _ = self.build_all_supported_frozen_catalog()
        for strategy in frozen["strategies"]:
            if strategy["strategy_id"] in M10_1_VISUAL_GOLDEN_CASE_IDS:
                strategy["source_refs"] = [
                    {
                        "source_family": "brooks_v2_manual_transcript",
                        "source_ref": "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_014E_fake.md",
                        "locator": {"kind": "markdown_unit", "path": "units/video_014E_fake.md"},
                        "title": "Fake visual source",
                    }
                ]
        return frozen

    def test_brooks_only_support_is_eligible(self) -> None:
        result = classify_support_for_strategy({"brooks_v2_manual_transcript"})

        self.assertEqual(result["support_level"], "high_priority_supported")
        self.assertEqual(result["policy_decision"], "eligible_from_brooks_v2_without_cross_source_requirement")

    def test_youtube_only_support_is_eligible(self) -> None:
        result = classify_support_for_strategy({"fangfangtu_youtube_transcript"})

        self.assertEqual(result["support_level"], "high_priority_supported")
        self.assertEqual(result["policy_decision"], "eligible_from_youtube_without_cross_source_requirement")

    def test_notes_only_support_is_downgraded(self) -> None:
        result = classify_support_for_strategy({"fangfangtu_notes"})

        self.assertEqual(result["support_level"], "notes_only")
        self.assertEqual(result["policy_decision"], "downgrade_to_needs_corroboration")

    def test_clean_room_guard_blocks_legacy_paths(self) -> None:
        with self.assertRaises(ValueError):
            assert_clean_room_inputs([FORBIDDEN_CLEAN_ROOM_READ_PATHS[0] / "combined" / "PA-SC-001.md"])

    def test_strategy_seed_namespace_does_not_use_legacy_ids(self) -> None:
        for seed in STRATEGY_SEEDS:
            self.assertTrue(seed.strategy_id.startswith("M10-PA-"))
            self.assertNotIn("PA-SC-", seed.strategy_id)
            self.assertNotIn("SF-", seed.strategy_id)

    def test_catalog_builder_does_not_require_cross_source_for_brooks_only(self) -> None:
        docs = [
            SourceDoc(
                family="brooks_v2_manual_transcript",
                source_ref="raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/example.md",
                locator={"kind": "markdown_unit", "path": "units/example.md"},
                title="Breakouts need follow-through",
                text="Strong breakout follow-through second bar trend continuation.",
            )
        ]

        catalog, support_matrix, _, _ = build_catalog_from_docs(docs)
        breakout = next(item for item in catalog if item["strategy_id"] == "M10-PA-002")
        matrix = next(item for item in support_matrix if item["strategy_id"] == "M10-PA-002")

        self.assertEqual(breakout["support_level"], "high_priority_supported")
        self.assertEqual(breakout["policy_decision"], "eligible_from_brooks_v2_without_cross_source_requirement")
        self.assertTrue(matrix["brooks_or_youtube_only_allowed"])

    def test_m10_1_route_sets_match_review_plan(self) -> None:
        all_ids = {seed.strategy_id for seed in STRATEGY_SEEDS}
        routed_ids = (
            set(M10_1_BACKTEST_WAVE_A_IDS)
            | set(M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS)
            | set(M10_1_VISUAL_GOLDEN_CASE_IDS)
            | set(M10_1_SUPPORTING_RULE_IDS)
            | set(M10_1_RESEARCH_ONLY_IDS)
        )

        self.assertEqual(routed_ids, all_ids)
        self.assertEqual(set(M10_1_BACKTEST_WAVE_A_IDS), {"M10-PA-001", "M10-PA-002", "M10-PA-005", "M10-PA-012"})
        self.assertEqual(set(M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS), {"M10-PA-013"})
        self.assertEqual(
            set(M10_1_VISUAL_GOLDEN_CASE_IDS),
            {"M10-PA-003", "M10-PA-004", "M10-PA-007", "M10-PA-008", "M10-PA-009", "M10-PA-010", "M10-PA-011"},
        )
        self.assertEqual(set(M10_1_SUPPORTING_RULE_IDS), {"M10-PA-014", "M10-PA-015"})
        self.assertEqual(set(M10_1_RESEARCH_ONLY_IDS), {"M10-PA-006", "M10-PA-016"})

    def test_m10_1_test_queue_is_exact_and_visual_gate_is_not_global(self) -> None:
        catalog, _, _, _ = self.build_all_supported_catalog()
        queue = build_m10_1_strategy_test_queue(catalog)
        queues = queue["queues"]

        self.assertTrue(queue["boundaries"]["visual_golden_case_is_not_global_prerequisite"])
        self.assertEqual({item["strategy_id"] for item in queues["backtest_wave_a"]}, set(M10_1_BACKTEST_WAVE_A_IDS))
        self.assertEqual({item["strategy_id"] for item in queues["backtest_wave_b_candidate"]}, {"M10-PA-013"})
        self.assertEqual({item["strategy_id"] for item in queues["visual_golden_case_first"]}, set(M10_1_VISUAL_GOLDEN_CASE_IDS))
        self.assertNotIn("M10-PA-006", {item["strategy_id"] for item in queues["visual_golden_case_first"]})
        self.assertNotIn("M10-PA-016", {item["strategy_id"] for item in queues["visual_golden_case_first"]})

    def test_m10_1_wave_a_timeframes_and_outcomes_are_locked(self) -> None:
        catalog, _, _, _ = self.build_all_supported_catalog()
        queue = build_m10_1_strategy_test_queue(catalog)
        wave_a = {item["strategy_id"]: item for item in queue["queues"]["backtest_wave_a"]}

        for strategy_id, timeframes in M10_1_BACKTEST_WAVE_A_TIMEFRAMES.items():
            self.assertEqual(wave_a[strategy_id]["timeframes"], list(timeframes))
            self.assertEqual(wave_a[strategy_id]["allowed_outcomes"], list(M10_1_ALLOWED_WAVE_A_OUTCOMES))
            self.assertFalse(wave_a[strategy_id]["retain_or_promote_allowed"])
        self.assertNotIn("retain", M10_1_ALLOWED_WAVE_A_OUTCOMES)
        self.assertNotIn("promote", M10_1_ALLOWED_WAVE_A_OUTCOMES)

    def test_m10_1_frozen_catalog_blocks_supporting_and_research_triggers(self) -> None:
        catalog, support_matrix, _, backtest_matrix = self.build_all_supported_catalog()
        review_rows = build_m10_1_review_rows(
            catalog=catalog,
            support_matrix=support_matrix,
            backtest_matrix=backtest_matrix,
        )
        frozen = build_strategy_catalog_m10_frozen(catalog, review_rows)
        queue = build_m10_1_strategy_test_queue(catalog)

        self.assertEqual(validate_m10_1_artifacts(frozen, queue), [])
        strategy_by_id = {item["strategy_id"]: item for item in frozen["strategies"]}
        for strategy_id in M10_1_SUPPORTING_RULE_IDS + M10_1_RESEARCH_ONLY_IDS:
            self.assertFalse(strategy_by_id[strategy_id]["standalone_trigger_allowed"])
        for strategy_id in M10_1_VISUAL_GOLDEN_CASE_IDS:
            self.assertTrue(strategy_by_id[strategy_id]["visual_golden_case_required"])
        frozen_text = json.dumps(frozen, ensure_ascii=False)
        self.assertNotIn("PA-SC-", frozen_text)
        self.assertNotIn("SF-", frozen_text)

    def test_m10_2_visual_case_pack_covers_only_visual_strategies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            brooks_root = Path(tmpdir) / "brooks_v2"
            self.build_fake_brooks_evidence_root(brooks_root)
            frozen = self.build_fake_visual_frozen_catalog()
            visual_packs, visual_index, _ = build_m10_2_visual_artifacts(frozen, brooks_root=brooks_root)

        self.assertEqual({pack["strategy_id"] for pack in visual_packs}, set(M10_1_VISUAL_GOLDEN_CASE_IDS))
        self.assertEqual(set(visual_index["visual_strategy_ids"]), set(M10_1_VISUAL_GOLDEN_CASE_IDS))
        excluded = set(visual_index["excluded_strategy_ids"])
        self.assertTrue(set(M10_1_BACKTEST_WAVE_A_IDS).issubset(excluded))
        self.assertTrue(set(M10_1_SUPPORTING_RULE_IDS).issubset(excluded))
        self.assertTrue(set(M10_1_RESEARCH_ONLY_IDS).issubset(excluded))

    def test_m10_2_ready_visual_packs_have_required_cases_and_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            brooks_root = Path(tmpdir) / "brooks_v2"
            self.build_fake_brooks_evidence_root(brooks_root)
            frozen = self.build_fake_visual_frozen_catalog()
            visual_packs, visual_index, selection_ledger = build_m10_2_visual_artifacts(frozen, brooks_root=brooks_root)
            queue = build_m10_1_strategy_test_queue(frozen["strategies"])
            handoff = build_m10_3_backtest_spec_handoff(queue)

            self.assertEqual(validate_m10_2_artifacts(visual_packs, visual_index, handoff), [])
            self.assertEqual(visual_index["ready_count"], len(M10_1_VISUAL_GOLDEN_CASE_IDS))
            self.assertEqual(visual_index["blocked_count"], 0)
            self.assertEqual(len(selection_ledger["strategies"]), len(M10_1_VISUAL_GOLDEN_CASE_IDS))
            for pack in visual_packs:
                self.assertEqual(pack["pack_status"], "visual_pack_ready")
                for case_type, required in M10_2_VISUAL_CASE_COUNTS.items():
                    self.assertGreaterEqual(pack["case_counts"][case_type], required)
                for case in pack["cases"]:
                    self.assertTrue(case["evidence_image_logical_path"])
                    self.assertTrue(case["evidence_image_checksum"])
                    self.assertTrue(case["evidence_exists"])
                    self.assertTrue(case["checksum_resolved"])
                    self.assertEqual(case["review_status"], "agent_selected_pending_manual_review")

    def test_m10_3_handoff_is_wave_a_only_and_not_a_backtest_conclusion(self) -> None:
        frozen, catalog = self.build_all_supported_frozen_catalog()
        del frozen
        queue = build_m10_1_strategy_test_queue(catalog)
        handoff = build_m10_3_backtest_spec_handoff(queue)

        self.assertEqual(set(handoff["wave_a_strategy_ids"]), set(M10_1_BACKTEST_WAVE_A_IDS))
        self.assertFalse(set(M10_1_VISUAL_GOLDEN_CASE_IDS) & set(handoff["wave_a_strategy_ids"]))
        self.assertFalse(handoff["formal_spec_generated"])
        self.assertFalse(handoff["backtest_started"])
        self.assertEqual(handoff["backtest_conclusions"], [])
        self.assertFalse(handoff["promote_or_retain_allowed"])


if __name__ == "__main__":
    unittest.main()
