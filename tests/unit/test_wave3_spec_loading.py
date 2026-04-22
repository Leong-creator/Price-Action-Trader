from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import ROOT, load_json


class TestWave3SpecLoading(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = load_json("reports/strategy_lab/wave3_robustness_summary.json")

    def test_wave3_only_uses_frozen_v02_specs(self) -> None:
        self.assertEqual(self.summary["tested_strategies"], ["SF-001", "SF-002", "SF-003", "SF-004"])
        for strategy_id in self.summary["tested_strategies"]:
            path = ROOT / "reports" / "strategy_lab" / "specs" / f"{strategy_id}-v0.2-candidate.yaml"
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["spec_version"], "v0.2-candidate")
            self.assertEqual(payload["selected_variant_id"], "quality_filter")
            self.assertEqual(payload["candidate_status"], "frozen_candidate")
        self.assertFalse(
            (ROOT / "reports" / "strategy_lab" / "specs" / "SF-005-v0.2-candidate.yaml").exists()
        )

    def test_input_spec_hashes_match_current_files(self) -> None:
        for strategy_id, digest in self.summary["input_spec_hashes"].items():
            path = ROOT / "reports" / "strategy_lab" / "specs" / f"{strategy_id}-v0.2-candidate.yaml"
            current_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(current_digest, digest)


if __name__ == "__main__":
    unittest.main()
