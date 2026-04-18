from __future__ import annotations

import csv
import json
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / "reports" / "backtests" / "m8e2_longer_window_daily_validation"


def _load_artifact_json(name: str) -> dict:
    return json.loads((ARTIFACT_ROOT / name).read_text(encoding="utf-8"))


class LongerWindowDailyValidationReliabilityTests(unittest.TestCase):
    def test_checked_in_longer_window_artifact_set_is_complete(self) -> None:
        required = (
            "summary.json",
            "report.md",
            "knowledge_trace.json",
            "knowledge_trace_coverage.json",
            "no_trade_wait.jsonl",
            "trades.csv",
            "split_summary.json",
            "regime_breakdown.json",
            "equity_curve.png",
        )

        for name in required:
            self.assertTrue((ARTIFACT_ROOT / name).exists(), name)

    def test_checked_in_longer_window_summary_and_report_capture_sample_adequacy(self) -> None:
        summary = _load_artifact_json("summary.json")
        report_text = (ARTIFACT_ROOT / "report.md").read_text(encoding="utf-8")

        self.assertEqual(summary["run_id"], "m8e2_longer_window_daily_validation")
        self.assertEqual(
            summary["time_range"],
            {
                "start": "2018-01-01",
                "end": "2026-04-17",
                "interval": "1d",
            },
        )
        self.assertFalse(os.path.isabs(summary["cache_dir"]))
        self.assertFalse(os.path.isabs(summary["report_dir"]))
        self.assertTrue(all(not os.path.isabs(item["cache_csv"]) for item in summary["per_symbol"]))
        self.assertEqual(summary["sample_adequacy"]["overall_verdict"], "insufficient_sample")
        self.assertEqual(
            {item["split_name"]: item["verdict"] for item in summary["sample_adequacy"]["by_split"]},
            {
                "in_sample": "adequate",
                "validation": "insufficient_sample",
                "out_of_sample": "insufficient_sample",
            },
        )
        self.assertIn("2018-01-01 ~ 2026-04-17", report_text)
        self.assertIn("### 样本充分性", report_text)
        self.assertIn("Out-of-sample (out_of_sample)", report_text)
        self.assertIn("验证诚实但样本不足", report_text)

    def test_checked_in_longer_window_summary_matches_structured_outputs(self) -> None:
        summary = _load_artifact_json("summary.json")
        split_summary = _load_artifact_json("split_summary.json")
        regime_breakdown = _load_artifact_json("regime_breakdown.json")
        coverage = _load_artifact_json("knowledge_trace_coverage.json")
        with (ARTIFACT_ROOT / "trades.csv").open(encoding="utf-8", newline="") as handle:
            trades = list(csv.DictReader(handle))
        no_trade_wait_count = len(
            [
                line
                for line in (ARTIFACT_ROOT / "no_trade_wait.jsonl").read_text(encoding="utf-8").splitlines()
                if line
            ]
        )

        self.assertEqual(summary["split_summary_overview"], split_summary["windows"])
        self.assertEqual(summary["regime_breakdown_overview"], regime_breakdown["windows"])
        self.assertEqual(summary["knowledge_trace_coverage"], coverage["overall"])
        self.assertEqual(len(trades), summary["core_results"]["trade_count"])
        self.assertEqual(no_trade_wait_count, summary["core_results"]["no_trade_wait"])
        self.assertNotIn(b"\r\n", (ARTIFACT_ROOT / "trades.csv").read_bytes())

    def test_checked_in_longer_window_metrics_and_trace_regression(self) -> None:
        summary = _load_artifact_json("summary.json")
        coverage = _load_artifact_json("knowledge_trace_coverage.json")
        knowledge_trace = _load_artifact_json("knowledge_trace.json")

        self.assertEqual(
            summary["core_results"],
            {
                "total_pnl": "389.9846",
                "ending_equity": "25389.9846",
                "total_return_pct": "1.5599",
                "max_drawdown": "494.1026",
                "max_drawdown_pct": "1.9237",
                "trade_count": 14,
                "blocked_signals": 562,
                "no_trade_wait": 6210,
                "win_rate_pct": "42.8571",
                "profit_factor": "1.4914",
            },
        )
        self.assertEqual(
            [(item["symbol"], item["executed_trades"], item["pnl_cash"]) for item in summary["per_symbol"]],
            [
                ("NVDA", 3, "-0.0856"),
                ("TSLA", 5, "100.9702"),
                ("SPY", 6, "289.1000"),
            ],
        )
        self.assertEqual(coverage["overall"]["total_signals"], 595)
        self.assertEqual(coverage["executed"]["total_signals"], 14)
        self.assertEqual(
            coverage["overall"]["actual_hit_source_family_presence"]["curated_rule"],
            595,
        )
        executed = knowledge_trace["executed_trades"][0]
        self.assertTrue(set(executed["actual_source_refs"]).isdisjoint(set(executed["bundle_support_refs"])))
        self.assertNotIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", executed["actual_source_refs"])
        self.assertIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", executed["bundle_support_refs"])
