from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import load_json


class TestWave3SplitIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        summary = load_json("reports/strategy_lab/wave3_robustness_summary.json")
        self.split_sessions = summary["split_sessions"]
        self.core = set(self.split_sessions["core_history_sessions"])
        self.proxy = set(self.split_sessions["proxy_holdout_sessions"])
        self.strict = set(self.split_sessions["strict_holdout_sessions"])

    def test_core_proxy_and_strict_do_not_overlap(self) -> None:
        self.assertTrue(self.core.isdisjoint(self.proxy))
        self.assertTrue(self.core.isdisjoint(self.strict))
        self.assertTrue(self.proxy.isdisjoint(self.strict))

    def test_walk_forward_windows_do_not_leak_into_holdouts(self) -> None:
        for window in self.split_sessions["walk_forward_windows"]:
            is_sessions = set(window["is_sessions"])
            oos_sessions = set(window["oos_sessions"])
            self.assertTrue(is_sessions.isdisjoint(oos_sessions))
            self.assertTrue(is_sessions.issubset(self.core))
            self.assertTrue(oos_sessions.issubset(self.core))
            self.assertTrue(oos_sessions.isdisjoint(self.proxy))
            self.assertTrue(oos_sessions.isdisjoint(self.strict))


if __name__ == "__main__":
    unittest.main()
