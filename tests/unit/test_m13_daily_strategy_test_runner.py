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
            self.assertEqual(
                states[("M10-PA-001-m14-modify-20260522", "M10-PA-001-m14-modify-20260522-1d")],
                "zero_signal",
            )
            self.assertEqual(
                states[("M10-PA-004-MBF-QC-m14-modify-20260522", "M10-PA-004-MBF-QC-m14-modify-20260522-1d")],
                "zero_signal",
            )
            self.assertEqual(
                states[("M10-PA-007-m14-modify-20260522", "M10-PA-007-m14-modify-20260522-1d")],
                "zero_signal",
            )
            self.assertEqual(
                states[("M10-PA-008-broker-risk-cap-shadow", "M10-PA-008-broker-risk-cap-shadow-1d")],
                "zero_signal",
            )
            self.assertEqual(
                states[("M10-PA-009-m14-modify-20260522", "M10-PA-009-m14-modify-20260522-1d")],
                "zero_signal",
            )
            self.assertEqual(
                states[("M10-PA-012-m14-modify-20260522", "M10-PA-012-m14-modify-20260522-5m")],
                "zero_signal",
            )
            self.assertEqual(
                states[("M10-PA-013-m14-modify-20260522", "M10-PA-013-m14-modify-20260522-1d")],
                "zero_signal",
            )
            self.assertEqual(
                states[("M10-PA-013-m14-modify-20260522", "M10-PA-013-m14-modify-20260522-5m")],
                "zero_signal",
            )
            self.assertEqual(
                states[("M12-FTD-001-m14-modify-20260522", "M12-FTD-001-m14-modify-20260522-1d")],
                "zero_signal",
            )
            self.assertEqual(states[("M10-PA-011-ORB-R1", "M10-PA-011-ORB-R1-5m")], "zero_signal")

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

    def test_open_operation_uses_signal_date_when_event_time_is_later(self):
        temp, config = self.build_fixture()
        with temp:
            audit_path = config.m12_29_output_dir / "m12_46_account_input_audit.json"
            audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
            for row in audit_payload["rows"]:
                if row["runtime_id"] == "M10-PA-011-ORB-R1-5m":
                    row["input_status"] = "connected_with_signal_today"
                    row["today_formal_signal_count"] = "1"
                    row["source_row_count"] = "1"
                    row["plain_language_result"] = "connected_with_signal_today"
                    break
            audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False), encoding="utf-8")
            ledger_path = config.m12_29_output_dir / "m12_46_account_trade_ledger.jsonl"
            legacy_open = {
                "event_type": "open",
                "runtime_id": "M10-PA-011-ORB-R1-5m",
                "strategy_id": "M10-PA-011-ORB-R1",
                "timeframe": "5m",
                "symbol": "XLY",
                "direction": "看涨",
                "quantity": "1",
                "entry_price": "100.00",
                "signal_time": "2026-05-07T13:30:00",
                "event_time": "2026-05-26T00:06:37Z",
            }
            with ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(legacy_open, sort_keys=True) + "\n")

            result = run_m13_daily_strategy_test_runner(
                config,
                generated_at="2026-05-07T20:30:00Z",
                trading_date="2026-05-07",
            )

            by_id = {row["strategy_id"]: row for row in result["scorecard_rows"]}
            orb = by_id["M10-PA-011-ORB-R1"]
            self.assertEqual(orb["test_states"], "signal_generated")
            self.assertEqual(orb["signal_count"], "1")
            self.assertEqual(orb["open_count"], "1")
            operations = [
                row for row in result["account_ledger_rows"]
                if row["runtime_id"] == "M10-PA-011-ORB-R1-5m"
            ]
            self.assertEqual(len(operations), 1)
            self.assertEqual(operations[0]["event_type"], "open")
            self.assertEqual(operations[0]["source_event_time"], "2026-05-26T00:06:37Z")

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

    def test_rescue_variants_are_visible_but_do_not_block_required_goal(self):
        temp, config = self.build_fixture()
        with temp:
            result = run_m13_daily_strategy_test_runner(
                config,
                generated_at="2026-05-07T20:30:00Z",
                trading_date="2026-05-07",
            )
            by_id = {row["strategy_id"]: row for row in result["scorecard_rows"]}
            rescue = by_id["M10-PA-012-m14-modify-20260522"]
            self.assertEqual(rescue["required_for_goal"], "false")
            self.assertEqual(rescue["test_states"], "zero_signal")
            self.assertEqual(rescue["challenge_status"], "ready_for_10_day_challenge")
            self.assertEqual(rescue["goal_blocked"], "false")
            pa007_rescue = by_id["M10-PA-007-m14-modify-20260522"]
            self.assertEqual(pa007_rescue["required_for_goal"], "false")
            self.assertEqual(pa007_rescue["test_states"], "zero_signal")
            self.assertEqual(pa007_rescue["challenge_status"], "ready_for_10_day_challenge")
            self.assertEqual(pa007_rescue["goal_blocked"], "false")
            pa009_rescue = by_id["M10-PA-009-m14-modify-20260522"]
            self.assertEqual(pa009_rescue["required_for_goal"], "false")
            self.assertEqual(pa009_rescue["test_states"], "zero_signal")
            self.assertEqual(pa009_rescue["challenge_status"], "ready_for_10_day_challenge")
            self.assertEqual(pa009_rescue["goal_blocked"], "false")
            pa008_broker_shadow = by_id["M10-PA-008-broker-risk-cap-shadow"]
            self.assertEqual(pa008_broker_shadow["required_for_goal"], "false")
            self.assertEqual(pa008_broker_shadow["test_states"], "zero_signal")
            self.assertEqual(pa008_broker_shadow["challenge_status"], "ready_for_10_day_challenge")
            self.assertEqual(pa008_broker_shadow["goal_blocked"], "false")
            pa013_rescue = by_id["M10-PA-013-m14-modify-20260522"]
            self.assertEqual(pa013_rescue["required_for_goal"], "false")
            self.assertEqual(pa013_rescue["test_states"], "zero_signal")
            self.assertEqual(pa013_rescue["challenge_status"], "ready_for_10_day_challenge")
            self.assertEqual(pa013_rescue["goal_blocked"], "false")
            ftd_rescue = by_id["M12-FTD-001-m14-modify-20260522"]
            self.assertEqual(ftd_rescue["required_for_goal"], "false")
            self.assertEqual(ftd_rescue["test_states"], "zero_signal")
            self.assertEqual(ftd_rescue["challenge_status"], "ready_for_10_day_challenge")
            self.assertEqual(ftd_rescue["goal_blocked"], "false")
            pa004_qc_rescue = by_id["M10-PA-004-MBF-QC-m14-modify-20260522"]
            self.assertEqual(pa004_qc_rescue["required_for_goal"], "false")
            self.assertEqual(pa004_qc_rescue["test_states"], "zero_signal")
            self.assertEqual(pa004_qc_rescue["challenge_status"], "ready_for_10_day_challenge")
            self.assertEqual(pa004_qc_rescue["goal_blocked"], "false")
            orb_rescue = by_id["M10-PA-011-ORB-R1"]
            self.assertEqual(orb_rescue["required_for_goal"], "false")
            self.assertEqual(orb_rescue["test_states"], "zero_signal")
            self.assertEqual(orb_rescue["challenge_status"], "ready_for_10_day_challenge")
            self.assertEqual(orb_rescue["goal_blocked"], "false")
            self.assertTrue(result["summary"]["ready_for_complete_reliable_testing"])
            self.assertEqual(result["summary"]["blocked_strategy_ids"], [])


if __name__ == "__main__":
    unittest.main()
