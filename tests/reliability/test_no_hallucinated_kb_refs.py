from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.strategy import (
    DEFAULT_CONCEPT_PATH,
    KnowledgeReferenceError,
    discover_golden_cases,
    load_strategy_knowledge,
    reference_exists,
)


class NoHallucinatedKBRefsTests(unittest.TestCase):
    def test_golden_cases_have_required_shape(self) -> None:
        cases = discover_golden_cases()

        self.assertGreaterEqual(len(cases), 5)
        for case in cases:
            self.assertTrue(case.case_id)
            self.assertTrue(case.market)
            self.assertTrue(case.timeframe)
            self.assertIsInstance(case.expected_context, dict)
            self.assertIsInstance(case.allowed_setups, tuple)
            self.assertIsInstance(case.forbidden_setups, tuple)
            self.assertTrue(case.allowed_actions)
            self.assertTrue(case.must_explain)
            self.assertTrue(case.must_not_claim)
            for reference in case.required_source_refs:
                self.assertTrue(reference_exists(reference), msg=f"missing golden-case ref: {reference}")

    def test_missing_source_refs_fail_fast(self) -> None:
        setup_path = self._write_temp_setup(source_refs="[]")

        with self.assertRaisesRegex(KnowledgeReferenceError, "missing source_refs"):
            load_strategy_knowledge(DEFAULT_CONCEPT_PATH, setup_path)

    def test_nonexistent_wiki_ref_fail_fast(self) -> None:
        setup_path = self._write_temp_setup(
            source_refs='["wiki:knowledge/wiki/rules/does-not-exist.md"]'
        )

        with self.assertRaisesRegex(KnowledgeReferenceError, "does not exist"):
            load_strategy_knowledge(DEFAULT_CONCEPT_PATH, setup_path)

    def _write_temp_setup(self, *, source_refs: str) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="pat-m8b-refs-"))
        path = temp_dir / "setup.md"
        path.write_text(
            f"""---
title: Temporary Setup
type: setup
status: draft
confidence: low
market: ["US"]
timeframes: ["5m"]
direction: both
source_refs: {source_refs}
applicability: ["reliability test only"]
not_applicable: []
contradictions: []
pa_context: ["trend"]
higher_timeframe_context: ["pending"]
bar_by_bar_notes: ["pending"]
entry_trigger: ["pending"]
stop_rule: ["pending"]
target_rule: ["pending"]
invalidation: ["pending"]
last_reviewed: 2026-04-17
---
""",
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
