from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import ROOT, load_json


class TestWave3SpecImmutability(unittest.TestCase):
    def test_wave3_run_did_not_modify_frozen_specs(self) -> None:
        summary = load_json("reports/strategy_lab/wave3_robustness_summary.json")
        for strategy_id, expected_digest in summary["input_spec_hashes"].items():
            path = ROOT / "reports" / "strategy_lab" / "specs" / f"{strategy_id}-v0.2-candidate.yaml"
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_digest)


if __name__ == "__main__":
    unittest.main()
