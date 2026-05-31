import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from scripts.m12_29_current_day_scan_dashboard_lib import (
    advance_account_runtime,
    load_config,
    run_m12_29_current_day_scan_dashboard,
)


class M1246RuntimeAccountsTest(unittest.TestCase):
    def run_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_46"
            config = replace(load_config(), output_dir=output_dir)
            result = run_m12_29_current_day_scan_dashboard(
                config,
                generated_at="2026-04-29T14:00:00Z",
                execute_fetch=False,
                refresh_quotes=False,
            )
            return result

    def test_supporting_rules_do_not_become_independent_runtime_accounts(self):
        result = self.run_stage()
        runtime_ids = {row["strategy_id"] for row in result["dashboard"]["strategy_scorecard_rows"]}
        self.assertNotIn("M10-PA-006", runtime_ids)
        self.assertNotIn("M10-PA-014", runtime_ids)
        self.assertNotIn("M10-PA-015", runtime_ids)
        self.assertNotIn("M10-PA-016", runtime_ids)
        supporting_rows = result["dashboard"]["supporting_rule_ab_results"]["rows"]
        self.assertEqual(
            [row["supporting_rule_id"] for row in supporting_rows],
            ["M10-PA-006", "M10-PA-014", "M10-PA-015", "M10-PA-016"],
        )

    def test_all_runtime_accounts_keep_paper_only_boundary(self):
        result = self.run_stage()
        for row in result["dashboard"]["strategy_scorecard_rows"]:
            self.assertEqual(row["starting_capital"], "20000.00")
        self.assertTrue(result["dashboard"]["paper_simulated_only"])
        self.assertFalse(result["dashboard"]["trading_connection"])
        self.assertFalse(result["dashboard"]["real_money_actions"])
        self.assertFalse(result["dashboard"]["live_execution"])

    def test_runtime_state_isolated_by_runtime_id_even_when_symbol_overlaps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_46"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            runtime = advance_account_runtime(
                config,
                generated_at="2026-04-29T14:00:00Z",
                scan_date=date.fromisoformat("2026-04-29"),
                trade_rows=[
                    {
                        "strategy_id": "M10-PA-001",
                        "timeframe": "5m",
                        "symbol": "SPY",
                        "direction": "long",
                        "signal_time": "2026-04-29T14:00:00Z",
                        "signal_date": "2026-04-29",
                        "latest_price": "101.00",
                        "latest_price_source": "longbridge_quote_readonly",
                        "hypothetical_entry_price": "100.00",
                        "hypothetical_stop_price": "99.00",
                        "hypothetical_target_price": "103.00",
                        "review_status": "ready",
                        "risk_level": "medium",
                        "source_refs": "src-a",
                        "spec_ref": "spec-a",
                    },
                    {
                        "strategy_id": "M10-PA-005",
                        "timeframe": "5m",
                        "symbol": "SPY",
                        "direction": "long",
                        "signal_time": "2026-04-29T14:00:00Z",
                        "signal_date": "2026-04-29",
                        "latest_price": "101.00",
                        "latest_price_source": "longbridge_quote_readonly",
                        "hypothetical_entry_price": "100.00",
                        "hypothetical_stop_price": "99.00",
                        "hypothetical_target_price": "103.00",
                        "review_status": "ready",
                        "risk_level": "medium",
                        "source_refs": "src-b",
                        "spec_ref": "spec-b",
                    },
                    {
                        "strategy_id": "M12-FTD-001",
                        "timeframe": "1d",
                        "symbol": "SPY",
                        "direction": "long",
                        "signal_time": "2026-04-29T14:00:00Z",
                        "signal_date": "2026-04-29",
                        "latest_price": "101.00",
                        "latest_price_source": "longbridge_quote_readonly",
                        "hypothetical_entry_price": "100.00",
                        "hypothetical_stop_price": "98.00",
                        "hypothetical_target_price": "106.00",
                        "review_status": "ready",
                        "risk_level": "medium",
                        "source_refs": "src-c",
                        "spec_ref": "spec-c",
                    },
                ],
                pa004_formal_rows=[],
                closure_rows=[],
                current_day_complete=True,
            )
            state = json.loads((output_dir / "m12_46_account_runtime_state.json").read_text(encoding="utf-8"))
        accounts = state["accounts"]
        self.assertEqual(len(accounts["M10-PA-001-5m"]["open_positions"]), 1)
        self.assertEqual(len(accounts["M10-PA-005-5m"]["open_positions"]), 1)
        self.assertEqual(len(accounts["M12-FTD-001-baseline-1d"]["open_positions"]), 1)
        self.assertEqual(len(accounts["M12-FTD-001-loss-streak-guard-1d"]["open_positions"]), 1)
        self.assertNotEqual(
            accounts["M10-PA-001-5m"]["processed_signal_ids"][0],
            accounts["M10-PA-005-5m"]["processed_signal_ids"][0],
        )
        self.assertNotEqual(
            accounts["M12-FTD-001-baseline-1d"]["processed_signal_ids"][0],
            accounts["M12-FTD-001-loss-streak-guard-1d"]["processed_signal_ids"][0],
        )
        self.assertEqual(runtime["state"]["accounts"]["M10-PA-001-5m"]["cash"], "19000.00")
        self.assertEqual(runtime["state"]["accounts"]["M10-PA-005-5m"]["cash"], "17500.00")
        self.assertEqual(runtime["state"]["accounts"]["M12-FTD-001-baseline-1d"]["cash"], "15000.00")
        self.assertEqual(runtime["state"]["accounts"]["M12-FTD-001-loss-streak-guard-1d"]["cash"], "15000.00")

    def test_today_signal_count_uses_trade_ledger_not_open_position_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_46"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            runtime = advance_account_runtime(
                config,
                generated_at="2026-04-29T14:00:00Z",
                scan_date=date.fromisoformat("2026-04-29"),
                trade_rows=[
                    {
                        "strategy_id": "M10-PA-001",
                        "timeframe": "1d",
                        "symbol": "SPY",
                        "direction": "long",
                        "signal_time": "2026-04-29T14:00:00Z",
                        "signal_date": "2026-04-29",
                        "latest_price": "101.00",
                        "latest_price_source": "longbridge_quote_readonly",
                        "hypothetical_entry_price": "100.00",
                        "hypothetical_stop_price": "99.75",
                        "hypothetical_target_price": "100.50",
                        "review_status": "ready",
                        "risk_level": "medium",
                        "source_refs": "src-a",
                        "spec_ref": "spec-a",
                    },
                ],
                pa004_formal_rows=[],
                closure_rows=[],
                current_day_runtime_ready=True,
            )
        rows = {row["runtime_id"]: row for row in runtime["account_rows"]}
        account = rows["M10-PA-001-1d"]
        self.assertEqual(account["today_signal_count"], "1")
        self.assertEqual(account["today_opened_count"], "1")
        self.assertEqual(account["today_closed_count"], "1")
        self.assertEqual(account["open_position_count"], "0")

    def test_repair_runtime_filters_low_quality_and_sizes_down(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_46"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            runtime = advance_account_runtime(
                config,
                generated_at="2026-04-29T14:00:00Z",
                scan_date=date.fromisoformat("2026-04-29"),
                trade_rows=[
                    {
                        "strategy_id": "M10-PA-001",
                        "timeframe": "5m",
                        "symbol": "BAD",
                        "direction": "long",
                        "signal_time": "2026-04-29T14:00:00Z",
                        "signal_date": "2026-04-29",
                        "latest_price": "100.20",
                        "hypothetical_entry_price": "100.00",
                        "hypothetical_stop_price": "99.00",
                        "hypothetical_target_price": "100.50",
                        "review_status": "低质量入场",
                        "risk_level": "高",
                    },
                    {
                        "strategy_id": "M10-PA-001",
                        "timeframe": "5m",
                        "symbol": "GOOD",
                        "direction": "long",
                        "signal_time": "2026-04-29T14:05:00Z",
                        "signal_date": "2026-04-29",
                        "latest_price": "101.00",
                        "hypothetical_entry_price": "100.00",
                        "hypothetical_stop_price": "99.00",
                        "hypothetical_target_price": "103.00",
                        "review_status": "ready",
                        "risk_level": "medium",
                    },
                ],
                pa004_formal_rows=[],
                closure_rows=[],
                current_day_runtime_ready=True,
            )
        account = runtime["state"]["accounts"]["M10-PA-001-5m"]
        self.assertEqual([position["symbol"] for position in account["open_positions"]], ["GOOD"])
        self.assertEqual(account["open_positions"][0]["quantity"], "10.0000")
        audit = {row["runtime_id"]: row for row in runtime["account_input_audit_rows"]}
        self.assertEqual(audit["M10-PA-001-5m"]["source_row_count"], "1")
        self.assertEqual(audit["M10-PA-001-5m"]["position_size_multiplier"], "0.10")
        self.assertEqual(
            audit["M10-PA-001-5m"]["runtime_repair_policy"],
            "entry_quality_stop_distance_loss_cooldown",
        )

    def test_pa002_5m_false_breakout_confirmation_blocks_failed_probe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_46"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            runtime = advance_account_runtime(
                config,
                generated_at="2026-04-29T14:00:00Z",
                scan_date=date.fromisoformat("2026-04-29"),
                trade_rows=[
                    {
                        "strategy_id": "M10-PA-002",
                        "timeframe": "5m",
                        "symbol": "FAIL",
                        "direction": "long",
                        "signal_time": "2026-04-29T14:00:00Z",
                        "signal_date": "2026-04-29",
                        "latest_price": "99.50",
                        "hypothetical_entry_price": "100.00",
                        "hypothetical_stop_price": "99.00",
                        "hypothetical_target_price": "103.00",
                        "review_status": "ready",
                        "risk_level": "medium",
                    },
                    {
                        "strategy_id": "M10-PA-002",
                        "timeframe": "5m",
                        "symbol": "PASS",
                        "direction": "long",
                        "signal_time": "2026-04-29T14:05:00Z",
                        "signal_date": "2026-04-29",
                        "latest_price": "101.00",
                        "hypothetical_entry_price": "100.00",
                        "hypothetical_stop_price": "99.00",
                        "hypothetical_target_price": "103.00",
                        "review_status": "ready",
                        "risk_level": "medium",
                    },
                ],
                pa004_formal_rows=[],
                closure_rows=[],
                current_day_runtime_ready=True,
            )
        account = runtime["state"]["accounts"]["M10-PA-002-5m"]
        self.assertEqual([position["symbol"] for position in account["open_positions"]], ["PASS"])
        self.assertEqual(account["open_positions"][0]["quantity"], "10.0000")

    def test_pa011_5m_requires_orb_repair_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_46"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            runtime = advance_account_runtime(
                config,
                generated_at="2026-04-29T14:00:00Z",
                scan_date=date.fromisoformat("2026-04-29"),
                trade_rows=[
                    {
                        "strategy_id": "M10-PA-011",
                        "timeframe": "5m",
                        "symbol": "GENERIC",
                        "direction": "long",
                        "signal_time": "2026-04-29T14:00:00Z",
                        "signal_date": "2026-04-29",
                        "latest_price": "101.00",
                        "hypothetical_entry_price": "100.00",
                        "hypothetical_stop_price": "99.00",
                        "hypothetical_target_price": "103.00",
                        "simulated_context": "m13_m10_pa_011_wave_b_adapter",
                        "review_status": "generic opening reversal",
                        "risk_level": "medium",
                    },
                    {
                        "strategy_id": "M10-PA-011",
                        "timeframe": "5m",
                        "symbol": "ORB",
                        "direction": "long",
                        "signal_time": "2026-04-29T14:05:00Z",
                        "signal_date": "2026-04-29",
                        "latest_price": "101.00",
                        "hypothetical_entry_price": "100.00",
                        "hypothetical_stop_price": "99.00",
                        "hypothetical_target_price": "101.50",
                        "simulated_context": "m14_rescue_pa011_failed_orb_retest_adapter",
                        "signal_source_type": "m14_rescue_pa011_failed_orb_retest_adapter",
                        "variant_id": "orb_rebuild_r1",
                        "review_status": "failed ORB retest confirmed",
                        "risk_level": "medium",
                    },
                ],
                pa004_formal_rows=[],
                closure_rows=[],
                current_day_runtime_ready=True,
            )
        account = runtime["state"]["accounts"]["M10-PA-011-5m"]
        self.assertEqual([position["symbol"] for position in account["open_positions"]], ["ORB"])
        self.assertEqual(account["open_positions"][0]["quantity"], "10.0000")


if __name__ == "__main__":
    unittest.main()
