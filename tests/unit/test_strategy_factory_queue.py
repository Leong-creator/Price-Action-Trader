from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strategy_factory_test_support import load_json


ROOT = Path(__file__).resolve().parents[2]


class TestStrategyFactoryQueue(unittest.TestCase):
    def setUp(self) -> None:
        self.exec_queue = load_json("reports/strategy_lab/executable_spec_queue.json")
        self.backtest_queue = load_json("reports/strategy_lab/backtest_queue.json")
        self.dataset_inventory = load_json("reports/strategy_lab/backtest_dataset_inventory.json")
        self.factory_queue = load_json("reports/strategy_lab/strategy_factory/backtest_queue.json")
        self.triage_ledger = load_json("reports/strategy_lab/strategy_factory/triage_ledger.json")

    def test_executable_spec_queue_matches_wave_scope(self) -> None:
        items = {item["strategy_id"]: item for item in self.exec_queue["items"]}
        self.assertEqual(set(items), {"SF-001", "SF-002", "SF-003", "SF-004", "SF-005"})
        self.assertEqual(self.exec_queue["schema_version"], "m9-batch-backtest-v11")
        self.assertEqual(self.exec_queue["symbols"], ["SPY", "QQQ", "NVDA", "TSLA"])
        self.assertEqual(len(self.exec_queue["dataset_paths"]), 4)
        for strategy_id in ("SF-001", "SF-002", "SF-003", "SF-004"):
            self.assertEqual(items[strategy_id]["queue_status"], "ready")
        self.assertEqual(items["SF-005"]["queue_status"], "deferred")

    def test_backtest_queue_only_schedules_four_tested_strategies(self) -> None:
        items = {item["strategy_id"]: item for item in self.backtest_queue["items"]}
        for strategy_id in ("SF-001", "SF-002", "SF-003", "SF-004"):
            self.assertEqual(items[strategy_id]["queue_status"], "pending")
            self.assertEqual(items[strategy_id]["variants"], ["baseline", "quality_filter"])
            self.assertEqual(items[strategy_id]["timeframe"], "5m")
            self.assertEqual(items[strategy_id]["symbols"], ["SPY", "QQQ", "NVDA", "TSLA"])
            self.assertEqual(len(items[strategy_id]["dataset_paths"]), 4)
        self.assertEqual(items["SF-005"]["queue_status"], "deferred")
        self.assertEqual(items["SF-005"]["variants"], [])

    def test_dataset_inventory_tracks_wave2_scope(self) -> None:
        self.assertEqual(self.dataset_inventory["provider"], "longbridge")
        self.assertEqual([item["symbol"] for item in self.dataset_inventory["datasets"]], ["SPY", "QQQ", "NVDA", "TSLA"])
        self.assertTrue(all(item["start"] == "2025-04-01" for item in self.dataset_inventory["datasets"]))
        self.assertTrue(all(item["end"] == "2026-04-21" for item in self.dataset_inventory["datasets"]))

    def test_factory_ledgers_mark_completed_or_deferred(self) -> None:
        items = {item["strategy_id"]: item for item in self.factory_queue["items"]}
        for strategy_id in ("SF-001", "SF-002", "SF-003", "SF-004"):
            self.assertEqual(items[strategy_id]["queue_status"], "completed")
        self.assertEqual(items["SF-005"]["queue_status"], "deferred")
        self.assertEqual(len(self.triage_ledger["records"]), 5)

    def test_strategy_artifacts_exist_for_every_frozen_strategy(self) -> None:
        self.assertTrue((ROOT / "reports" / "strategy_lab" / "final_strategy_factory_trade_report.md").exists())
        self.assertTrue((ROOT / "reports" / "strategy_lab" / "final_strategy_factory_cash_report.md").exists())
        for strategy_id in ("SF-001", "SF-002", "SF-003", "SF-004", "SF-005"):
            strategy_dir = ROOT / "reports" / "strategy_lab" / strategy_id
            self.assertTrue((strategy_dir / "executable_spec.md").exists())
            self.assertTrue((strategy_dir / "test_plan.md").exists())
            self.assertTrue((strategy_dir / "summary.json").exists())
            self.assertTrue((strategy_dir / "candidate_events.csv").exists())
            self.assertTrue((strategy_dir / "skip_summary.json").exists())
            self.assertTrue((strategy_dir / "diagnostics.md").exists())
            if strategy_id != "SF-005":
                variants_dir = strategy_dir / "variants"
                self.assertTrue((variants_dir / "baseline" / "summary.json").exists())
                self.assertTrue((variants_dir / "quality_filter" / "summary.json").exists())
                for symbol in ("SPY", "QQQ", "NVDA", "TSLA"):
                    self.assertTrue((variants_dir / "baseline" / "datasets" / symbol / "summary.json").exists())
                    self.assertTrue((variants_dir / "quality_filter" / "datasets" / symbol / "summary.json").exists())

    def test_heartbeat_covers_all_wave_strategies(self) -> None:
        heartbeat_path = ROOT / "reports" / "strategy_lab" / "heartbeat.jsonl"
        rows = [
            json.loads(line)
            for line in heartbeat_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = {
            row["strategy_id"]: row
            for row in rows
            if row.get("strategy_id") in {"SF-001", "SF-002", "SF-003", "SF-004", "SF-005"}
        }
        self.assertEqual(set(latest), {"SF-001", "SF-002", "SF-003", "SF-004", "SF-005"})
        self.assertEqual(latest["SF-005"]["backtest_status"], "deferred")


if __name__ == "__main__":
    unittest.main()
