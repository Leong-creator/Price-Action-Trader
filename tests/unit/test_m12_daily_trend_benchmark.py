from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from scripts import m12_daily_trend_benchmark_lib as MODULE


OUTPUT_DIR = MODULE.M12_7_DIR


class M12DailyTrendBenchmarkTests(unittest.TestCase):
    def test_config_freezes_benchmark_boundary(self) -> None:
        config = MODULE.load_benchmark_config()

        self.assertEqual(config.strategy_id, "M12-BENCH-001")
        self.assertEqual(config.start.isoformat(), "2010-06-29")
        self.assertEqual(config.end.isoformat(), "2026-04-21")
        self.assertEqual(config.interval, "1d")
        self.assertEqual(config.runtime_scope, "historical_simulation_benchmark_only")
        self.assertFalse(config.gate_evidence)
        self.assertEqual(config.decision_policy.scanner_factor_min_event_count, 30)
        self.assertEqual(tuple(item.symbol for item in config.instruments), ("SPY", "QQQ", "NVDA", "TSLA"))

    def test_cache_window_parser_and_covering_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            csv_path = cache_dir / "us_QQQ_1d_1990-01-01_2026-04-21_longbridge.csv"
            csv_path.write_text(
                "symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume\n"
                "QQQ,US,1d,2010-06-29T16:00:00-04:00,America/New_York,1,2,1,2,100\n",
                encoding="utf-8",
            )
            config = replace(MODULE.load_benchmark_config(), cache_dir=cache_dir)

            selection = MODULE.select_local_cache(config, config.instruments[1])

        self.assertEqual(MODULE.parse_cache_window(csv_path.name), (date(1990, 1, 1), date(2026, 4, 21)))
        self.assertEqual(selection.selected_reason, "covering_window_match")
        self.assertEqual(selection.row_count, 1)
        self.assertIsNone(selection.deferred_reason)

    def test_generated_summary_is_benchmark_only_and_compares_tier_a(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_daily_trend_benchmark.py before full validation")
        summary = json.loads((OUTPUT_DIR / "m12_7_daily_trend_benchmark_summary.json").read_text(encoding="utf-8"))
        with (OUTPUT_DIR / "m12_7_daily_trend_benchmark_comparison.csv").open(newline="", encoding="utf-8") as handle:
            comparison_rows = list(csv.DictReader(handle))

        self.assertEqual(summary["strategy_id"], "M12-BENCH-001")
        self.assertFalse(summary["clean_room_catalog_source"])
        self.assertEqual(summary["boundary"]["runtime_scope"], "historical_simulation_benchmark_only")
        self.assertFalse(summary["boundary"]["gate_evidence"])
        self.assertFalse(summary["boundary"]["clean_room_catalog_source"])
        self.assertEqual(
            summary["benchmark_signal_contract"]["contract_version"],
            "m12-bench-001.frozen-signal-bar-placeholder.v1",
        )
        self.assertIn(summary["benchmark_decision"], MODULE.ALLOWED_DECISIONS)
        self.assertGreaterEqual(int(summary["core_results"]["benchmark_event_count"]), 1)
        self.assertEqual(summary["deferred_symbol_count"], 0)
        self.assertEqual({row["strategy_id"] for row in comparison_rows}, {"M12-BENCH-001", "M10-PA-001", "M10-PA-002", "M10-PA-012"})
        benchmark_row = next(row for row in comparison_rows if row["strategy_id"] == "M12-BENCH-001")
        self.assertEqual(benchmark_row["capital_test_status"], summary["benchmark_decision"])
        self.assertTrue(all(row["gate_evidence"] == "false" for row in comparison_rows))

    def test_runner_can_regenerate_artifacts_with_consistent_decision(self) -> None:
        config = MODULE.load_benchmark_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_daily_trend_benchmark(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
            )
            with (Path(tmp) / "m12_7_daily_trend_benchmark_comparison.csv").open(newline="", encoding="utf-8") as handle:
                comparison_rows = list(csv.DictReader(handle))
        benchmark_row = next(row for row in comparison_rows if row["strategy_id"] == "M12-BENCH-001")

        self.assertEqual(summary["generated_at"], "2026-04-28T00:00:00Z")
        self.assertEqual(benchmark_row["capital_test_status"], summary["benchmark_decision"])
        self.assertEqual(summary["boundary"]["runtime_scope"], "historical_simulation_benchmark_only")

    def test_decision_degrades_to_benchmark_only_when_sample_is_too_small(self) -> None:
        config = MODULE.load_benchmark_config()
        strict_policy = replace(config.decision_policy, scanner_factor_min_event_count=999_999)
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_daily_trend_benchmark(
                replace(config, output_dir=Path(tmp), decision_policy=strict_policy),
                generated_at="2026-04-28T00:00:00Z",
            )

        self.assertEqual(summary["benchmark_decision"], "benchmark_only")
        self.assertFalse(summary["scanner_factor_allowed"])

    def test_decision_rejects_when_positive_result_is_too_concentrated(self) -> None:
        config = MODULE.load_benchmark_config()
        strict_policy = replace(config.decision_policy, scanner_factor_max_symbol_profit_share=Decimal("0.10"))
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_daily_trend_benchmark(
                replace(config, output_dir=Path(tmp), decision_policy=strict_policy),
                generated_at="2026-04-28T00:00:00Z",
            )

        self.assertEqual(summary["benchmark_decision"], "reject_as_overfit")
        self.assertFalse(summary["scanner_factor_allowed"])

    def test_required_artifacts_exist_and_forbidden_claims_absent(self) -> None:
        expected = {
            "m12_7_daily_trend_benchmark_summary.json",
            "m12_7_daily_trend_benchmark_report.md",
            "m12_7_daily_trend_benchmark_simulated_events.csv",
            "m12_7_daily_trend_benchmark_equity_curve.csv",
            "m12_7_daily_trend_benchmark_comparison.csv",
            "m12_7_daily_trend_benchmark_deferred_inputs.json",
            "m12_7_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("m12_7_*")})
        combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in OUTPUT_DIR.glob("m12_7_*") if path.is_file())
        lowered = combined.lower()
        forbidden = (
            "PA-SC-",
            "SF-",
            "live" + "-ready",
            "broker",
            "account",
            "position",
            "order",
            "fill",
        )
        for forbidden_text in forbidden:
            self.assertNotIn(forbidden_text.lower(), lowered)
        self.assertIn("historical_simulation_benchmark_only", combined)


if __name__ == "__main__":
    unittest.main()
