from __future__ import annotations

import copy
import unittest

from scripts.kb_atomization_lib import SOURCE_SPECS, validate_source_manifest
from tests.reliability._atomization_support import load_fixture, validation_errors


class KnowledgeCoverageTests(unittest.TestCase):
    def test_source_manifest_covers_all_in_scope_sources(self) -> None:
        fixture = load_fixture()
        manifest = fixture["source_manifest"]

        self.assertEqual(len(manifest["sources"]), len(SOURCE_SPECS))
        raw_paths = {record["raw_path"] for record in manifest["sources"]}
        self.assertEqual(raw_paths, {spec.raw_path for spec in SOURCE_SPECS})

    def test_zone_identifier_is_filtered_and_not_treated_as_source(self) -> None:
        fixture = load_fixture()
        manifest = fixture["source_manifest"]
        filtered = manifest["coverage_summary"]["filtered_files"]

        self.assertTrue(all(item.endswith(":Zone.Identifier") for item in filtered))
        self.assertNotIn(
            "knowledge/raw/youtube/fangfangtu/transcripts/Price_Action方方土.pdf:Zone.Identifier",
            {record["raw_path"] for record in manifest["sources"]},
        )

    def test_source_manifest_validation_passes_and_blocked_threshold_is_not_hit(self) -> None:
        source_errors, atom_errors = validation_errors()
        self.assertEqual(source_errors, [])
        self.assertEqual(atom_errors, [])

        fixture = load_fixture()
        blocked = fixture["source_manifest"]["coverage_summary"]["parse_status_counts"]["blocked"]
        self.assertLess(blocked, 4)

    def test_validator_fails_fast_when_blocked_sources_hit_fuse_gate(self) -> None:
        fixture = load_fixture()
        mutated = copy.deepcopy(fixture["source_manifest"])
        mutated["coverage_summary"]["parse_status_counts"]["blocked"] = 4

        errors = validate_source_manifest(mutated)
        self.assertTrue(any("blocked source fuse triggered" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
