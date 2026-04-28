from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import m12_26_cache_scanner_expansion_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1226CacheScannerExpansionTests(unittest.TestCase):
    def test_temp_run_summarizes_first50_and_deferred_147_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_26_cache_scanner_expansion(
                generated_at="2026-04-28T12:30:00Z",
                output_dir=Path(tmp),
            )

        self.assertEqual(summary["universe_symbol_count"], 147)
        self.assertEqual(summary["first50_daily_ready_symbols"], 50)
        self.assertEqual(summary["first50_current_5m_ready_symbols"], 50)
        self.assertEqual(summary["first50_long_history_5m_ready_symbols"], 0)
        self.assertEqual(summary["additional_deferred_symbol_count"], 97)
        self.assertFalse(summary["full_147_universe_available_now"])
        self.assertFalse(summary["full_intraday_history_available_now"])
        self.assertFalse(summary["paper_trading_approval"])

    def test_checked_in_candidates_use_only_available_symbols_and_allowed_strategies(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_26_cache_scanner_expansion.py before full validation")
        summary = json.loads((OUTPUT_DIR / "m12_26_cache_scanner_expansion_summary.json").read_text(encoding="utf-8"))
        available = json.loads((OUTPUT_DIR / "m12_26_scanner_available_symbols.json").read_text(encoding="utf-8"))
        with (OUTPUT_DIR / "m12_26_scanner_candidates.csv").open(encoding="utf-8", newline="") as handle:
            candidates = list(csv.DictReader(handle))

        ready_symbols = set(available["daily_and_current_session_ready_symbols"])
        allowed = set(summary["auto_scanner_strategy_ids"])
        self.assertEqual(len(candidates), summary["scanner_candidate_count"])
        self.assertTrue(candidates)
        self.assertTrue({row["symbol"] for row in candidates} <= ready_symbols)
        self.assertTrue({row["strategy_id"] for row in candidates} <= allowed)
        self.assertNotIn("M10-PA-004", {row["strategy_id"] for row in candidates})
        self.assertNotIn("M10-PA-007", {row["strategy_id"] for row in candidates})

    def test_observation_only_and_deferred_boundaries_are_explicit(self) -> None:
        summary = json.loads((OUTPUT_DIR / "m12_26_cache_scanner_expansion_summary.json").read_text(encoding="utf-8"))
        deferred = json.loads((OUTPUT_DIR / "m12_26_deferred_symbols.json").read_text(encoding="utf-8"))["items"]
        self.assertEqual(summary["observation_only_strategy_ids"], ["M10-PA-007"])
        self.assertIn("M10-PA-007", summary["excluded_auto_scanner_strategy_ids"])
        self.assertIn("M10-PA-004", summary["excluded_auto_scanner_strategy_ids"])
        self.assertEqual(sum(1 for row in deferred if row["scope"] == "universe147_expansion"), 97)
        self.assertEqual(sum(1 for row in deferred if row["scope"] == "first50_long_history_5m"), 50)

    def test_reports_are_chinese_client_facing_and_safe(self) -> None:
        report = (OUTPUT_DIR / "m12_26_scanner_expansion_report.md").read_text(encoding="utf-8")
        for expected in ("用人话结论", "第一批", "今日", "候选", "长历史", "下一步"):
            self.assertIn(expected, report)
        all_text = "\n".join(path.read_text(encoding="utf-8").lower() for path in OUTPUT_DIR.glob("*") if path.is_file())
        for forbidden in ("pa-sc-", "sf-", "live-ready", "real_orders=true", "broker_connection=true", "paper_trading_approval=true", "order_id", "fill_id", "account_id"):
            self.assertNotIn(forbidden, all_text)


if __name__ == "__main__":
    unittest.main()
