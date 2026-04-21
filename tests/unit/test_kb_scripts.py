from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(module_name: str, relative_path: str):
    module_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


VALIDATE_KB = load_module("validate_kb", "scripts/validate_kb.py")
BUILD_KB_INDEX = load_module("build_kb_index", "scripts/build_kb_index.py")


VALID_STRATEGY_CARD = """---
title: Trend Pullback Resumption
type: setup
status: candidate
confidence: medium
market: ["US"]
timeframes: ["5m"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md"]
tags: ["strategy-card"]
applicability: ["research-only"]
not_applicable: []
contradictions: []
missing_visuals: []
open_questions: []
pa_context: ["trend"]
market_cycle: ["trend"]
higher_timeframe_context: ["pending-confirmation"]
bar_by_bar_notes: ["pending-detail"]
signal_bar: ["signal bar must align with trend context"]
entry_trigger: ["buy above signal bar high or sell below signal bar low"]
entry_bar: ["next bar"]
stop_rule: ["signal bar opposite extreme"]
target_rule: ["1R to 2R variants"]
trade_management: ["move to breakeven after follow-through"]
measured_move: false
invalidation: ["failed follow-through"]
risk_reward_min: 1.5
strategy_id: PA-SC-001
source_family: fangfangtu_transcript
setup_family: trend_pullback_resumption
market_context: ["trend", "pullback"]
evidence_quality: medium
chart_dependency: medium
needs_visual_review: false
test_priority: high
last_reviewed: 2026-04-20
last_updated: 2026-04-20
---

# Test
"""

VALID_STRATEGY_FACTORY_PAGE = """---
title: Fresh Strategy Factory Candidate
type: setup
status: draft
confidence: medium
market: ["US"]
timeframes: ["5m"]
direction: both
source_refs: ["wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md"]
tags: ["strategy-factory"]
applicability: ["research-only"]
not_applicable: []
contradictions: []
missing_visuals: []
open_questions: []
pa_context: ["trend"]
market_cycle: ["trend"]
higher_timeframe_context: ["pending-confirmation"]
bar_by_bar_notes: ["pending-detail"]
signal_bar: ["signal bar must align with trend context"]
entry_trigger: ["buy above signal bar high or sell below signal bar low"]
entry_bar: ["next bar"]
stop_rule: ["signal bar opposite extreme"]
target_rule: ["1R to 2R variants"]
trade_management: ["move to breakeven after follow-through"]
measured_move: false
invalidation: ["failed follow-through"]
risk_reward_min: 1.5
strategy_id: SF-001
source_family: fangfangtu_transcript
setup_family: fresh_breakout_family
market_context: ["trend", "breakout"]
evidence_quality: medium
chart_dependency: medium
needs_visual_review: false
test_priority: high
last_reviewed: 2026-04-21
last_updated: 2026-04-21
factory_stage: cataloged
readiness_gate: ready
factory_decision: parked
decision_reason: Waiting for first executable spec freeze.
legacy_overlap_refs: ["wiki:knowledge/wiki/strategy_cards/combined/pa-sc-002-breakout-follow-through.md"]
historical_comparison_refs: ["report:reports/strategy_lab/m9_strategy_lab_summary.md"]
historical_benchmark_refs: ["report:reports/strategy_lab/pa_sc_002_first_backtest_report.md"]
---

# Test
"""


class TestKbScripts(unittest.TestCase):
    def test_validate_kb_skips_templates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            template = root / "strategy_cards" / "templates" / "strategy-card-template.md"
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_text("# template only\n", encoding="utf-8")

            card = root / "strategy_cards" / "combined" / "pa-sc-001.md"
            card.parent.mkdir(parents=True, exist_ok=True)
            card.write_text(VALID_STRATEGY_CARD, encoding="utf-8")

            files = VALIDATE_KB.list_markdown_files(root)
            self.assertEqual(files, [card])
            self.assertEqual(VALIDATE_KB.validate_file(card), [])

    def test_validate_kb_requires_strategy_card_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            card = Path(tmpdir) / "strategy_cards" / "combined" / "pa-sc-001.md"
            card.parent.mkdir(parents=True, exist_ok=True)
            card.write_text(
                VALID_STRATEGY_CARD.replace("strategy_id: PA-SC-001\n", ""),
                encoding="utf-8",
            )

            errors = VALIDATE_KB.validate_file(card)
            self.assertIn(
                f"{card}: strategy card missing required field 'strategy_id'",
                errors,
            )

    def test_build_kb_index_includes_strategy_fields_and_skips_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            template = root / "strategy_cards" / "templates" / "strategy-card-template.md"
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_text("# template only\n", encoding="utf-8")

            card = root / "strategy_cards" / "brooks" / "pa-sc-008.md"
            card.parent.mkdir(parents=True, exist_ok=True)
            card.write_text(
                VALID_STRATEGY_CARD
                .replace("title: Trend Pullback Resumption", "title: Opening Range Breakout")
                .replace("strategy_id: PA-SC-001", "strategy_id: PA-SC-008")
                .replace("setup_family: trend_pullback_resumption", "setup_family: opening_range_breakout")
                .replace("source_family: fangfangtu_transcript", "source_family: combined")
                .replace("chart_dependency: medium", "chart_dependency: high")
                .replace("needs_visual_review: false", "needs_visual_review: true"),
                encoding="utf-8",
            )

            records = BUILD_KB_INDEX.build_index_records(root, root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["path"], "strategy_cards/brooks/pa-sc-008.md")
            self.assertEqual(records[0]["strategy_id"], "PA-SC-008")
            self.assertEqual(records[0]["setup_family"], "opening_range_breakout")
            self.assertEqual(records[0]["chart_dependency"], "high")
            self.assertTrue(records[0]["needs_visual_review"])

    def test_strategy_factory_page_requires_factory_fields_and_indexes_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            page = root / "strategy_factory" / "strategies" / "sf-001.md"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(VALID_STRATEGY_FACTORY_PAGE, encoding="utf-8")

            self.assertEqual(VALIDATE_KB.validate_file(page), [])

            records = BUILD_KB_INDEX.build_index_records(root, root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["strategy_id"], "SF-001")
            self.assertEqual(records[0]["factory_stage"], "cataloged")
            self.assertEqual(records[0]["readiness_gate"], "ready")
            self.assertEqual(records[0]["factory_decision"], "parked")
            self.assertEqual(
                records[0]["legacy_overlap_refs"],
                ["wiki:knowledge/wiki/strategy_cards/combined/pa-sc-002-breakout-follow-through.md"],
            )


if __name__ == "__main__":
    unittest.main()
