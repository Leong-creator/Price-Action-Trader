from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import m12_10_definition_fix_retest_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1210DefinitionFixRetestTests(unittest.TestCase):
    def test_scope_and_boundaries_are_locked(self) -> None:
        config = MODULE.load_m12_10_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_10_definition_fix_and_retest(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
            )

        self.assertEqual(summary["strategy_ids"], ["M10-PA-005", "M10-PA-004", "M10-PA-007"])
        self.assertEqual(summary["stage"], "M12.10.definition_fix_and_retest")
        self.assertTrue(summary["paper_simulated_only"])
        self.assertFalse(summary["paper_trading_approval"])
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["real_orders"])
        self.assertFalse(summary["live_execution"])

    def test_pa005_geometry_fields_are_persisted(self) -> None:
        config = MODULE.load_m12_10_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_10_definition_fix_and_retest(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
            )
            with (Path(tmp) / "m12_10_pa005_geometry_events.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertTrue(summary["pa005_geometry_fields_available"])
        self.assertTrue(summary["pa005_geometry_event_id_unique"])
        self.assertGreater(summary["pa005_geometry_event_count"], 0)
        self.assertEqual(summary["pa005_geometry_event_count"], len(rows))
        self.assertEqual(len({row["event_id"] for row in rows}), len(rows))
        required = {
            "range_high",
            "range_low",
            "range_height",
            "breakout_edge",
            "reentry_close",
            "failed_breakout_extreme",
        }
        self.assertTrue(required <= set(rows[0]))
        for row in rows[:50]:
            for field in required:
                self.assertNotEqual(row[field], "")

    def test_pa005_event_identity_includes_geometry_candidate(self) -> None:
        config = MODULE.load_m12_10_config()
        with tempfile.TemporaryDirectory() as tmp:
            MODULE.run_m12_10_definition_fix_and_retest(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
            )
            with (Path(tmp) / "m12_10_pa005_geometry_events.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            ledger = json.loads((Path(tmp) / "m12_10_definition_field_ledger.json").read_text(encoding="utf-8"))

        identity = ledger["strategy_rows"][0]["geometry_event_identity"]
        self.assertTrue(identity["event_id_unique"])
        self.assertIn("breakout_timestamp", identity["identity_fields"])
        self.assertIn("range_high", identity["identity_fields"])
        self.assertIn("range_low", identity["identity_fields"])
        by_signal = {}
        for row in rows:
            signal_key = (
                row["strategy_id"],
                row["symbol"],
                row["timeframe"],
                row["direction"],
                row["signal_timestamp"],
                row["setup_notes"],
            )
            by_signal.setdefault(signal_key, set()).add(
                (row["event_id"], row["breakout_timestamp"], row["range_high"], row["range_low"])
            )
        self.assertTrue(any(len(candidates) > 1 for candidates in by_signal.values()))

    def test_definition_field_ledger_downgrades_visual_definition_strategies(self) -> None:
        config = MODULE.load_m12_10_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_10_definition_fix_and_retest(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
            )
            ledger = json.loads((Path(tmp) / "m12_10_definition_field_ledger.json").read_text(encoding="utf-8"))

        rows = {row["strategy_id"]: row for row in ledger["strategy_rows"]}
        self.assertEqual(rows["M10-PA-004"]["definition_decision"], "visual_only_not_backtestable_without_manual_labels")
        self.assertEqual(rows["M10-PA-007"]["definition_decision"], "visual_only_not_backtestable_without_manual_labels")
        self.assertEqual(
            set(rows["M10-PA-004"]["required_fields"]),
            {"wide_channel_boundary", "boundary_touch", "reversal_confirmation", "channel_invalidation"},
        )
        self.assertEqual(
            set(rows["M10-PA-007"]["required_fields"]),
            {"first_leg_count", "second_leg_count", "trap_confirmation", "opposite_failure_point"},
        )
        self.assertEqual(summary["visual_definition_decisions"]["M10-PA-004"], "visual_only_not_backtestable_without_manual_labels")
        self.assertEqual(summary["visual_definition_decisions"]["M10-PA-007"], "visual_only_not_backtestable_without_manual_labels")

    def test_metrics_do_not_fake_retests_for_m10_004_or_m10_007(self) -> None:
        config = MODULE.load_m12_10_config()
        with tempfile.TemporaryDirectory() as tmp:
            MODULE.run_m12_10_definition_fix_and_retest(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
            )
            with (Path(tmp) / "m12_10_before_after_metrics.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual({row["strategy_id"] for row in rows}, {"M10-PA-005", "M10-PA-004", "M10-PA-007"})
        pa005_rows = [row for row in rows if row["strategy_id"] == "M10-PA-005"]
        self.assertEqual({row["timeframe"] for row in pa005_rows}, {"1d", "1h", "15m", "5m"})
        for strategy_id in ("M10-PA-004", "M10-PA-007"):
            [row] = [item for item in rows if item["strategy_id"] == strategy_id]
            self.assertEqual(row["geometry_fields_available"], "false")
            self.assertEqual(row["before_trade_count"], "")
            self.assertEqual(row["after_trade_count"], "")
            self.assertEqual(row["after_net_profit"], "")
            self.assertEqual(row["after_win_rate"], "")
            self.assertEqual(row["after_max_drawdown"], "")

    def test_no_profit_tuning_or_paper_gate_evidence(self) -> None:
        config = MODULE.load_m12_10_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_10_definition_fix_and_retest(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
            )
            combined = "\n".join(path.read_text(encoding="utf-8") for path in Path(tmp).glob("m12_10_*") if path.is_file())

        self.assertFalse(summary["uses_profit_curve_tuning"])
        self.assertEqual(
            {item["strategy_id"] for item in summary["priority_visual_gate_guard"]},
            {"M10-PA-008", "M10-PA-009"},
        )
        self.assertTrue(all(item["paper_gate_evidence_now"] is False for item in summary["priority_visual_gate_guard"]))
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "promote", "live-ready", "paper_trading_approval=true", "broker_connection=true", "real_orders=true"):
            self.assertNotIn(forbidden.lower(), lowered)
        self.assertNotIn("uses_profit_curve_tuning,true", lowered)

    def test_checked_in_artifacts_exist(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_10_definition_fix_retest.py before full validation")
        expected = {
            "m12_10_definition_field_ledger.json",
            "m12_10_pa005_geometry_events.csv",
            "m12_10_before_after_metrics.csv",
            "m12_10_retest_summary.json",
            "m12_10_definition_fix_report.md",
            "m12_10_retest_client_summary.md",
            "m12_10_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("m12_10_*")})


if __name__ == "__main__":
    unittest.main()
