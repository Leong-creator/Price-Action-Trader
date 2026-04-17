from __future__ import annotations

import unittest

from tests.reliability._atomization_support import load_fixture


class KnowledgeAtomTests(unittest.TestCase):
    def test_statement_contract_is_complete(self) -> None:
        fixture = load_fixture()
        statements = [atom for atom in fixture["atoms"] if atom["atom_type"] == "statement"]

        self.assertGreater(len(statements), 0)
        for atom in statements[:50]:
            self.assertTrue(atom["atom_id"])
            self.assertEqual(atom["status"], "draft")
            self.assertTrue(atom["source_ref"])
            self.assertTrue(atom["raw_locator"])
            self.assertTrue(atom["evidence_chunk_ids"])
            self.assertTrue(atom["callable_tags"])
            self.assertNotIn("strategy_candidate", atom["callable_tags"])

    def test_no_evidence_no_statement_atom(self) -> None:
        fixture = load_fixture()
        for atom in fixture["atoms"]:
            if atom["atom_type"] != "statement":
                continue
            self.assertTrue(atom["evidence_chunk_ids"])
            self.assertIn("fragment_index", atom["raw_locator"])
            self.assertTrue(atom["content"].strip())

    def test_header_or_boilerplate_fragments_do_not_become_statements(self) -> None:
        fixture = load_fixture()
        statements = [atom["content"] for atom in fixture["atoms"] if atom["atom_type"] == "statement"]
        normalized = {content.lower().replace(" ", "").replace("1", "i") for content in statements}

        self.assertNotIn("brookstradingcourse", normalized)
        self.assertTrue(all(".com" not in content.lower() for content in statements))
        self.assertTrue(all("slide " not in content.lower() for content in statements))
        self.assertTrue(all("qihua" not in content.lower() for content in statements))
        self.assertNotIn("exit with limit order", {content.lower() for content in statements})
        self.assertNotIn("day trading examples 2", {content.lower() for content in statements})
        self.assertTrue(all(not content.startswith("专题系列") for content in statements))

    def test_key_curated_atoms_are_evidence_backed(self) -> None:
        fixture = load_fixture()
        by_source_ref = {atom["source_ref"]: atom for atom in fixture["atoms"] if atom["atom_type"] in {"concept", "setup", "rule"}}

        for source_ref in (
            "wiki:knowledge/wiki/concepts/market-cycle-overview.md",
            "wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md",
            "wiki:knowledge/wiki/rules/m3-research-reference-pack.md",
        ):
            self.assertIn(source_ref, by_source_ref)
            atom = by_source_ref[source_ref]
            self.assertTrue(atom["evidence_chunk_ids"])
            self.assertEqual(atom["raw_locator"]["locator_kind"], "chunk_set")
            self.assertGreater(atom["raw_locator"]["member_count"], 0)


if __name__ == "__main__":
    unittest.main()
