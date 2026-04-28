from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from scripts import m12_universe_kline_cache_lib as MODULE


OUTPUT_DIR = MODULE.M12_8_DIR


class M12UniverseKlineCacheTests(unittest.TestCase):
    def test_config_consumes_m12_5_universe_and_keeps_inventory_only_boundary(self) -> None:
        config = MODULE.load_universe_kline_cache_config()
        symbols = MODULE.load_universe_symbols(config)

        self.assertEqual(len(symbols), 147)
        self.assertEqual(config.daily_start.isoformat(), "2010-06-29")
        self.assertEqual(config.intraday_start.isoformat(), "2024-04-01")
        self.assertEqual(config.derived_timeframes, ("15m", "1h"))
        self.assertFalse(config.fetch_policy.allow_readonly_fetch)
        self.assertFalse(config.fetch_policy.write_local_data)
        self.assertEqual(config.fetch_policy.max_fetch_symbols, 0)

    def test_config_rejects_boundary_drift(self) -> None:
        config = MODULE.load_universe_kline_cache_config()
        bad_policy = replace(config.fetch_policy, allow_readonly_fetch=True)
        cases = (
            replace(config, stage="M12.8.bad_stage"),
            replace(config, daily_interval="1h"),
            replace(config, intraday_interval="15m"),
            replace(config, derived_timeframes=("15m",)),
            replace(config, fetch_policy=bad_policy),
            replace(config, fetch_policy=replace(config.fetch_policy, write_local_data=True)),
            replace(config, fetch_policy=replace(config.fetch_policy, max_fetch_symbols=1)),
            replace(config, fetch_policy=replace(config.fetch_policy, max_requests_per_run=1)),
        )
        for bad_config in cases:
            with self.subTest(bad_config=bad_config):
                with self.assertRaises(ValueError):
                    MODULE.validate_config(bad_config)

    def test_universe_definition_drift_is_rejected(self) -> None:
        config = MODULE.load_universe_kline_cache_config()

        def write_universe(path: Path, *, stage: str, market: str, count: int) -> None:
            path.write_text(
                json.dumps(
                    {
                        "stage": stage,
                        "market": market,
                        "symbols": [f"T{i:03d}" for i in range(count)],
                    }
                ),
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_stage = tmp_path / "bad_stage.json"
            bad_market = tmp_path / "bad_market.json"
            bad_count = tmp_path / "bad_count.json"
            write_universe(bad_stage, stage="M12.4.other", market="US", count=147)
            write_universe(bad_market, stage="M12.5.liquid_universe_scanner", market="HK", count=147)
            write_universe(bad_count, stage="M12.5.liquid_universe_scanner", market="US", count=146)

            for path in (bad_stage, bad_market, bad_count):
                with self.subTest(path=path.name):
                    with self.assertRaises(ValueError):
                        MODULE.load_universe_symbols(replace(config, universe_definition_path=path))

    def test_best_cache_file_uses_latest_window_then_row_count(self) -> None:
        def write_cache(path: Path, rows: int) -> None:
            lines = ["timestamp,timezone,open,high,low,close,volume\n"]
            for idx in range(rows):
                lines.append(f"2026-04-{20 + idx:02d}T16:00:00-04:00,America/New_York,1,2,0.5,1.5,100\n")
            path.write_text("".join(lines), encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root_a"
            sibling_root = Path(tmp) / "root_b"
            directory = root / "longbridge_history"
            sibling_directory = sibling_root / "longbridge_history"
            directory.mkdir(parents=True)
            sibling_directory.mkdir(parents=True)
            older = directory / "us_SPY_1d_2010-06-29_2026-04-26_longbridge.csv"
            newer_short = directory / "us_SPY_1d_2010-06-29_2026-04-27_longbridge.csv"
            newer_long = sibling_directory / "us_SPY_1d_2010-06-29_2026-04-27_longbridge.csv"
            write_cache(older, 3)
            write_cache(newer_short, 1)
            write_cache(newer_long, 2)

            selected = MODULE.best_cache_file((root, sibling_root), "longbridge_history", "US", "SPY", "1d")

        self.assertEqual(selected.name, newer_short.name)
        self.assertEqual(selected.parent.parent.name, sibling_root.name)

    def test_malformed_cache_timestamp_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us_SPY_1d_2010-06-29_2026-04-27_longbridge.csv"
            path.write_text(
                "timestamp,timezone,open,high,low,close,volume\nnot-a-date,America/New_York,1,2,0.5,1.5,100\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                MODULE.csv_stats(path)

    def test_forbidden_output_guard_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m12_8_bad_report.md"
            path.write_text("This output is live-ready and must fail.\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                MODULE.assert_no_forbidden_output(Path(tmp))

    def test_coverage_status_accepts_verified_first_available_bar(self) -> None:
        status = MODULE.coverage_status(
            {
                "row_count": 10,
                "start_date": "2020-01-01",
                "end_date": "2026-04-27",
                "timezone": "America/New_York",
                "request_start_date": "2010-06-29",
            },
            date(2010, 6, 29),
            date(2026, 4, 27),
        )

        self.assertEqual(status["status"], "complete_from_first_available_bar")

    def test_coverage_status_defers_unverified_start_gap(self) -> None:
        status = MODULE.coverage_status(
            {
                "row_count": 10,
                "start_date": "2020-01-01",
                "end_date": "2026-04-27",
                "timezone": "America/New_York",
                "request_start_date": "2020-01-01",
            },
            date(2010, 6, 29),
            date(2026, 4, 27),
        )

        self.assertEqual(status["status"], "start_after_target_or_availability_gap")

    def test_generated_manifest_covers_147_symbols_and_derived_lineage(self) -> None:
        manifest = json.loads((OUTPUT_DIR / "m12_8_universe_cache_manifest.json").read_text(encoding="utf-8"))
        rows = manifest["items"]

        self.assertEqual(len({row["symbol"] for row in rows}), 147)
        self.assertEqual(len(rows), 147 * 4)
        self.assertEqual({row["timeframe"] for row in rows}, {"1d", "5m", "15m", "1h"})
        derived = [row for row in rows if row["timeframe"] in {"15m", "1h"}]
        self.assertTrue(derived)
        self.assertTrue(all(row["lineage"] == "derived_from_5m" for row in derived))
        self.assertTrue(all(row["source_timeframe"] == "5m" for row in derived))

    def test_missing_or_stale_cache_is_deferred_without_fake_availability(self) -> None:
        summary = json.loads((OUTPUT_DIR / "m12_8_cache_completion_summary.json").read_text(encoding="utf-8"))
        deferred = json.loads((OUTPUT_DIR / "m12_8_deferred_or_error_ledger.json").read_text(encoding="utf-8"))
        available = json.loads((OUTPUT_DIR / "m12_8_scanner_available_universe.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["universe_symbol_count"], 147)
        self.assertEqual(summary["cache_present_symbol_count"], 4)
        self.assertEqual(summary["target_complete_symbol_count"], 0)
        self.assertEqual(summary["deferred_item_count"], 588)
        self.assertEqual(available["cache_present_symbol_count"], 4)
        self.assertEqual(available["target_complete_symbol_count"], 0)
        self.assertEqual(len(deferred["items"]), summary["deferred_item_count"])
        self.assertTrue(all(item["fake_data_created"] is False for item in deferred["items"]))

    def test_fetch_plan_is_plan_only_and_covers_incomplete_native_rows(self) -> None:
        plan = json.loads((OUTPUT_DIR / "m12_8_fetch_plan.json").read_text(encoding="utf-8"))

        self.assertFalse(plan["fetch_enabled"])
        self.assertEqual(plan["policy"]["mode"], "inventory_and_fetch_plan_only")
        self.assertEqual(plan["request_count"], 294)
        self.assertTrue(all(item["request_status"] == "planned_not_executed" for item in plan["requests"]))
        self.assertTrue(all(item["timeframe"] in {"1d", "5m"} for item in plan["requests"]))

    def test_artifacts_are_cross_file_consistent(self) -> None:
        summary = json.loads((OUTPUT_DIR / "m12_8_cache_completion_summary.json").read_text(encoding="utf-8"))
        manifest = json.loads((OUTPUT_DIR / "m12_8_universe_cache_manifest.json").read_text(encoding="utf-8"))
        deferred = json.loads((OUTPUT_DIR / "m12_8_deferred_or_error_ledger.json").read_text(encoding="utf-8"))
        plan = json.loads((OUTPUT_DIR / "m12_8_fetch_plan.json").read_text(encoding="utf-8"))
        available = json.loads((OUTPUT_DIR / "m12_8_scanner_available_universe.json").read_text(encoding="utf-8"))
        handoff = (OUTPUT_DIR / "m12_8_handoff.md").read_text(encoding="utf-8")

        for artifact_path in summary["artifacts"].values():
            self.assertTrue((MODULE.ROOT / artifact_path).exists(), artifact_path)
        self.assertEqual(len(manifest["items"]), summary["universe_symbol_count"] * 4)
        self.assertEqual(len(deferred["items"]), summary["deferred_item_count"])
        self.assertEqual(plan["request_count"], summary["fetch_plan_request_count"])
        self.assertEqual(available["cache_present_symbol_count"], summary["cache_present_symbol_count"])
        self.assertEqual(available["target_complete_symbol_count"], summary["target_complete_symbol_count"])
        self.assertIn(f"universe_symbol_count: {summary['universe_symbol_count']}", handoff)
        self.assertIn(f"deferred_item_count: {summary['deferred_item_count']}", handoff)

    def test_runner_can_generate_temp_artifacts_without_tracking_local_data(self) -> None:
        config = MODULE.load_universe_kline_cache_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_universe_kline_cache(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
            )

        self.assertEqual(summary["generated_at"], "2026-04-28T00:00:00Z")
        self.assertEqual(summary["local_data_git_policy"], "local_data_not_tracked; checked-in artifacts record path/checksum/coverage only")
        self.assertTrue(summary["no_fake_cache"])

    def test_required_artifacts_exist_and_forbidden_claims_absent(self) -> None:
        expected = {
            "m12_8_universe_cache_manifest.json",
            "m12_8_deferred_or_error_ledger.json",
            "m12_8_fetch_plan.json",
            "m12_8_scanner_available_universe.json",
            "m12_8_cache_completion_summary.json",
            "m12_8_cache_coverage_report.md",
            "m12_8_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("m12_8_*")})
        combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in OUTPUT_DIR.glob("m12_8_*") if path.is_file())
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "real_orders=true", "broker_connection=true"):
            self.assertNotIn(forbidden.lower(), lowered)
        self.assertIn("deferred_no_fake_cache", combined)


if __name__ == "__main__":
    unittest.main()
