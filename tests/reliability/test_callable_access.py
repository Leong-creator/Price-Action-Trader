from __future__ import annotations

import unittest

from scripts.kb_atomization_lib import SOURCE_SPECS
from tests.reliability._atomization_support import load_fixture, query_fixture


class CallableAccessTests(unittest.TestCase):
    def test_transcript_brooks_and_all_fangfangtu_notes_are_queryable(self) -> None:
        fixture = load_fixture()
        callable_index = fixture["callable_index"]

        for family in ("fangfangtu_transcript", "al_brooks_ppt", "fangfangtu_notes"):
            self.assertIn(family, callable_index["indices"]["by_source_family"])
            self.assertGreater(len(callable_index["indices"]["by_source_family"][family]), 0)

        by_source_id = callable_index["indices"]["by_source_id"]
        for spec in SOURCE_SPECS:
            self.assertIn(spec.source_id, by_source_id)
            self.assertGreater(len(by_source_id[spec.source_id]), 0)

    def test_statement_atoms_are_queryable_but_do_not_participate_in_trigger_tags(self) -> None:
        statements = query_fixture(atom_type="statement", callable_tag="statement_candidate")

        self.assertGreater(len(statements), 0)
        for atom in statements[:50]:
            self.assertNotIn("strategy_candidate", atom["callable_tags"])
            self.assertIn("review_only", atom["callable_tags"])
            self.assertIn("explanation_only", atom["callable_tags"])

    def test_curated_atoms_and_source_notes_can_be_filtered_separately(self) -> None:
        curated = query_fixture(callable_tag="curated_callable")
        source_notes = query_fixture(atom_type="source_note")

        self.assertGreaterEqual(len(curated), 3)
        self.assertGreater(len(source_notes), 0)
        self.assertTrue(all(atom["atom_type"] in {"concept", "setup", "rule", "open_question", "contradiction"} for atom in curated))


if __name__ == "__main__":
    unittest.main()
