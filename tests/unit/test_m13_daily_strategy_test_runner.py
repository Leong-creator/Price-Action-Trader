import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m13_daily_strategy_test_runner_lib import (
    INDEPENDENT_ROLE,
    load_config,
    load_registry,
    run_m13_daily_strategy_test_runner,
)


class M13DailyStrategyTestRunnerTest(unittest.TestCase):
    def build_fixture(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        m12_dir = root / "m12"
        output_dir = root / "m13"
        m12_dir.mkdir(parents=True, exist_ok=True)
        config = replace(load_config(), output_dir=output_dir, m12_29_output_dir=m12_dir)
        registry = load_registry(config.registry_path)

        audit_rows = []
        scorecard_rows = []
        for strategy in registry["strategies"]:
            if strategy["module_role"] != INDEPENDENT_ROLE:
                continue
            for account in strategy["runtime_accounts"]:
                connected = strategy["detector_status"] == "connected"
                signal_today = account["runtime_id"] == "M12-FTD-001-baseline-1d"
                if connected and signal_today:
                    input_status = "connected_with_signal_today"
                    signal_count = "1"
                elif connected:
                    input_status = "connected_zero_signal_today"
                    signal_count = "0"
                else:
                    input_status = "not_connected_to_current_scanner"
                    signal_count = "0"
                audit_rows.append(
                    {
                        "runtime_id": account["runtime_id"],
                        "strategy_id": strategy["strategy_id"],
                        "lane": account["lane"],
                        "timeframe": account["timeframe"],
                        "current_scanner_connected": str(connected).lower(),
                        "formal_input_stream": str(connected).lower(),
                        "input_status": input_status,
                        "today_formal_signal_count": signal_count,
                        "source_row_count": signal_count,
                        "plain_language_result": input_status,
                    }
                )
                scorecard_rows.append({"runtime_id": account["runtime_id"], "equity": "20000.00"})
        (m12_dir / "m12_46_account_input_audit.json").write_text(
            json.dumps({"rows": audit_rows}, ensure_ascii=False),
            encoding="utf-8",
        )
        with (m12_dir / "m12_46_account_scorecards.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["runtime_id", "equity"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(scorecard_rows)
        ledger_rows = [
            {
                "event_type": "open",
                "runtime_id": "M12-FTD-001-baseline-1d",
                "strategy_id": "M12-FTD-001",
                "timeframe": "1d",
                "symbol": "SPY",
                "direction": "long",
                "quantity": "1",
                "entry_price": "100.00",
                "event_time": "2026-05-07T16:39:00Z",
            },
            {
                "event_type": "close",
                "runtime_id": "M12-FTD-001-baseline-1d",
                "strategy_id": "M12-FTD-001",
                "timeframe": "1d",
                "symbol": "SPY",
                "direction": "long",
                "quantity": "1",
                "entry_price": "100.00",
                "exit_price": "101.00",
                "realized_pnl": "1.00",
                "event_time": "2026-05-07T17:10:00Z",
            },
        ]
        (m12_dir / "m12_46_account_trade_ledger.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in ledger_rows),
            encoding="utf-8",
        )
        return temp, config

    def test_runner_writes_daily_ledgers_for_required_scope(self):
        temp, config = self.build_fixture()
        with temp:
            result = run_m13_daily_strategy_test_runner(
                config,
                generated_at="2026-05-07T20:30:00Z",
                trading_date="2026-05-07",
            )
            self.assertTrue((config.output_dir / "m13_strategy_signal_ledger.jsonl").exists())
            self.assertTrue((config.output_dir / "m13_account_operation_ledger.jsonl").exists())
            self.assertTrue(result["summary"]["all_required_have_ledger_state"])
            states = {
                (row["strategy_id"], row["runtime_id"]): row["test_state"]
                for row in result["signal_ledger_rows"]
            }
            self.assertEqual(states[("M10-PA-004", "M10-PA-004-long-1d")], "zero_signal")
            self.assertEqual(states[("M10-PA-004-MBF", "M10-PA-004-MBF-1d")], "zero_signal")
            self.assertEqual(states[("M10-PA-004-MBF-QC", "M10-PA-004-MBF-QC-1d")], "zero_signal")
            self.assertEqual(states[("M10-PA-005", "M10-PA-005-1d")], "zero_signal")
            self.assertEqual(states[("M12-FTD-001", "M12-FTD-001-baseline-1d")], "signal_generated")

    def test_connected_required_scope_is_ready_for_reliable_testing_goal(self):
        temp, config = self.build_fixture()
        with temp:
            result = run_m13_daily_strategy_test_runner(
                config,
                generated_at="2026-05-07T20:30:00Z",
                trading_date="2026-05-07",
            )
            self.assertTrue(result["summary"]["ready_for_complete_reliable_testing"])
            self.assertEqual(result["summary"]["blocked_strategy_ids"], [])
            self.assertFalse(result["goal_status"]["continue_without_stopping"])

    def test_account_ledger_counts_open_and_close_from_trade_ledger(self):
        temp, config = self.build_fixture()
        with temp:
            result = run_m13_daily_strategy_test_runner(
                config,
                generated_at="2026-05-07T20:30:00Z",
                trading_date="2026-05-07",
            )
            ftd = {
                row["strategy_id"]: row
                for row in result["scorecard_rows"]
                if row["strategy_id"] == "M12-FTD-001"
            }["M12-FTD-001"]
            self.assertEqual(ftd["open_count"], "1")
            self.assertEqual(ftd["close_count"], "1")

    def test_plugins_and_ai_trader_do_not_create_independent_accounts(self):
        temp, config = self.build_fixture()
        with temp:
            result = run_m13_daily_strategy_test_runner(
                config,
                generated_at="2026-05-07T20:30:00Z",
                trading_date="2026-05-07",
            )
            by_id = {row["strategy_id"]: row for row in result["scorecard_rows"]}
            self.assertEqual(by_id["M10-PA-006"]["challenge_status"], "plugin_ab_ledger")
            self.assertEqual(by_id["M10-PA-006"]["runtime_account_count"], "0")
            self.assertEqual(by_id["AI-TRADER-EXTERNAL"]["challenge_status"], "external_shadow_research_only")
            self.assertEqual(by_id["AI-TRADER-EXTERNAL"]["goal_blocked"], "false")


if __name__ == "__main__":
    unittest.main()
