import csv
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from scripts.m14_strategy_challenge_gate_lib import (
    build_paper_trial_gate,
    build_strategy_aggregates,
    build_strategy_decision_rows,
    load_config,
    read_json,
    read_jsonl,
    run_m14_strategy_challenge_gate,
    run_m14_strategy_challenge_recompute,
)


class M14StrategyChallengeGateTest(unittest.TestCase):
    def build_dirs(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        m13_dir = root / "m13"
        m12_dir = root / "m12"
        output_dir = root / "m14"
        m13_dir.mkdir(parents=True, exist_ok=True)
        m12_dir.mkdir(parents=True, exist_ok=True)
        config = replace(load_config(), m13_output_dir=m13_dir, m12_29_output_dir=m12_dir, output_dir=output_dir)
        return temp, config, m13_dir, m12_dir, output_dir

    def write_fixture(
        self,
        *,
        m13_dir: Path,
        m12_dir: Path,
        trading_date: str = "2026-05-08",
        data_ready: bool = False,
        signal_count: int = 1,
        account_event_type: str = "open",
        realized_pnl: str = "",
    ) -> None:
        signal_rows = [
            {
                "schema_version": "m13.strategy-signal-ledger.v1",
                "generated_at": "2026-05-08T16:00:00Z",
                "trading_date": trading_date,
                "strategy_id": "M10-PA-001",
                "display_name": "Trend pullback runtime",
                "module_role": "independent_runtime",
                "runtime_id": "M10-PA-001-1d",
                "lane": "mainline",
                "timeframe": "1d",
                "variant_id": "base",
                "required_for_goal": True,
                "detector_id": "fixture_detector",
                "test_state": "signal_generated" if signal_count else "zero_signal",
                "signal_count": signal_count,
                "next_action": "fixture",
            },
            {
                "schema_version": "m13.strategy-signal-ledger.v1",
                "generated_at": "2026-05-08T16:00:00Z",
                "trading_date": trading_date,
                "strategy_id": "M10-PA-003",
                "display_name": "Filter module",
                "module_role": "plugin_filter",
                "runtime_id": "",
                "lane": "",
                "timeframe": "",
                "variant_id": "",
                "required_for_goal": True,
                "detector_id": "plugin_fixture",
                "test_state": "plugin_ab_attached",
                "signal_count": 0,
                "next_action": "fixture",
            },
        ]
        account_rows = [
            {
                "schema_version": "m13.account-operation-ledger.v1",
                "generated_at": "2026-05-08T16:00:00Z",
                "trading_date": trading_date,
                "strategy_id": "M10-PA-001",
                "display_name": "Trend pullback runtime",
                "module_role": "independent_runtime",
                "required_for_goal": True,
                "runtime_id": "M10-PA-001-1d",
                "lane": "mainline",
                "timeframe": "1d",
                "variant_id": "base",
                "event_type": account_event_type,
                "test_state": account_event_type,
                "symbol": "SPY",
                "direction": "看涨",
                "quantity": "1",
                "entry_price": "10",
                "exit_price": "",
                "realized_pnl": realized_pnl,
                "source_event_time": f"{trading_date}T15:00:00Z",
                "equity": "20000.00",
            },
            {
                "schema_version": "m13.account-operation-ledger.v1",
                "generated_at": "2026-05-08T16:00:00Z",
                "trading_date": trading_date,
                "strategy_id": "M10-PA-003",
                "display_name": "Filter module",
                "module_role": "plugin_filter",
                "required_for_goal": True,
                "runtime_id": "",
                "event_type": "plugin_ab_attached",
                "test_state": "plugin_ab_attached",
            },
        ]
        self.write_jsonl(m13_dir / "m13_strategy_signal_ledger.jsonl", signal_rows)
        self.write_jsonl(m13_dir / "m13_account_operation_ledger.jsonl", account_rows)
        (m13_dir / "m13_daily_strategy_test_summary.json").write_text(
            json.dumps({"ready_for_complete_reliable_testing": True, "trading_date": trading_date}, ensure_ascii=False),
            encoding="utf-8",
        )
        quote_source = "longbridge_quote_readonly" if data_ready else "fallback_quotes_only"
        ready_count = 50 if data_ready else 0
        dashboard = {
            "summary": {
                "scan_date": trading_date,
                "current_day_runtime_ready": data_ready,
                "current_day_scan_complete": data_ready,
                "quote_source": quote_source,
                "first50_daily_ready_symbols": ready_count,
                "first50_current_5m_ready_symbols": ready_count,
                "runtime_readiness_note": "fixture readiness note",
            }
        }
        (m12_dir / "m12_32_minute_readonly_dashboard_data.json").write_text(
            json.dumps(dashboard, ensure_ascii=False),
            encoding="utf-8",
        )
        with (m12_dir / "m12_46_account_scorecards.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["runtime_id", "equity", "max_drawdown_percent"], lineterminator="\n")
            writer.writeheader()
            writer.writerow({"runtime_id": "M10-PA-001-1d", "equity": "20000.00", "max_drawdown_percent": "1.00"})
        trade_rows = [
            {
                "event_type": "open",
                "runtime_id": "M10-PA-001-1d",
                "strategy_id": "M10-PA-001",
                "timeframe": "1d",
                "symbol": "SPY",
                "direction": "看涨",
                "quantity": "1",
                "entry_price": "10",
                "stop_price": "9",
                "target_price": "12",
                "event_time": f"{trading_date}T15:00:00Z",
            }
        ]
        self.write_jsonl(m12_dir / "m12_46_account_trade_ledger.jsonl", trade_rows)

    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")

    def base_challenge_row(self, trading_date: str, realized_pnl: str = "10.00") -> dict:
        return {
            "schema_version": "m14.challenge-day-ledger.v1",
            "generated_at": f"{trading_date}T20:00:00Z",
            "trading_date": trading_date,
            "strategy_id": "M10-PA-001",
            "display_name": "Trend pullback runtime",
            "module_role": "independent_runtime",
            "runtime_id": "M10-PA-001-1d",
            "lane": "mainline",
            "timeframe": "1d",
            "variant_id": "base",
            "required_for_goal": True,
            "test_state": "signal_generated",
            "account_test_states": "open",
            "signal_count": 1,
            "zero_signal_day": False,
            "open_count": 1,
            "close_count": 1,
            "risk_blocked_count": 0,
            "realized_pnl": realized_pnl,
            "net_pnl_r": "0.1",
            "equity": "20000.00",
            "max_drawdown_percent": "1.00",
            "blocker_reason": "",
            "data_quality_state": "fully_ready",
            "data_freshness_warning": "",
        }

    def test_challenge_ledger_is_append_only_and_fallback_blocks_gate(self):
        temp, config, m13_dir, m12_dir, output_dir = self.build_dirs()
        with temp:
            self.write_fixture(m13_dir=m13_dir, m12_dir=m12_dir, data_ready=False)
            first = run_m14_strategy_challenge_gate(config, generated_at="2026-05-08T17:00:00Z", trading_date="2026-05-08")
            second = run_m14_strategy_challenge_gate(config, generated_at="2026-05-08T18:00:00Z", trading_date="2026-05-08")
            self.assertEqual(first["summary"]["appended_challenge_day_row_count"], 2)
            self.assertEqual(second["summary"]["appended_challenge_day_row_count"], 0)
            rows = read_jsonl(output_dir / "m14_challenge_day_ledger.jsonl")
            self.assertEqual(len(rows), 2)
            gate = {row["runtime_id"]: row for row in second["paper_gate"]["rows"]}
            self.assertEqual(gate["M10-PA-001-1d"]["paper_trial_gate"], "pause_runtime")
            self.assertEqual(gate["M10-PA-001-1d"]["action_state"], "pause_runtime")
            self.assertFalse(gate["M10-PA-001-1d"]["paper_candidate"])
            self.assertEqual(gate["M10-PA-003"]["paper_trial_gate"], "auxiliary_module")
            self.assertEqual(gate["M10-PA-003"]["action_state"], "auxiliary_module")
            self.assertEqual(gate["M10-PA-003"]["runtime_role"], "auxiliary_module")
            self.assertFalse(gate["M10-PA-003"]["standalone_trading_allowed"])
            self.assertIn("辅助模块", gate["M10-PA-003"]["display_action"])
            self.assertNotIn("research-only", gate["M10-PA-003"]["gate_reason"])
            self.assertIn("fallback quotes / no-fetch", second["summary"]["data_freshness_warning"])

    def test_degraded_days_are_audit_only_and_do_not_poison_valid_challenge_progress(self):
        temp, config, m13_dir, m12_dir, output_dir = self.build_dirs()
        with temp:
            degraded = self.base_challenge_row("2026-05-07")
            degraded["data_quality_state"] = "degraded_no_fetch_or_fallback_quotes"
            degraded["data_freshness_warning"] = "fallback quotes / no-fetch"
            self.write_jsonl(output_dir / "m14_challenge_day_ledger.jsonl", [degraded])
            self.write_fixture(m13_dir=m13_dir, m12_dir=m12_dir, trading_date="2026-05-08", data_ready=True)
            result = run_m14_strategy_challenge_gate(config, generated_at="2026-05-08T17:00:00Z", trading_date="2026-05-08")
            aggregate = result["strategy_aggregates"]["M10-PA-001-1d"]
            gate = {row["runtime_id"]: row for row in result["paper_gate"]["rows"]}
            self.assertEqual(aggregate["observed_trading_days"], 2)
            self.assertEqual(aggregate["completed_trading_days"], 1)
            self.assertEqual(aggregate["data_mismatch_days"], 0)
            self.assertEqual(aggregate["observed_data_mismatch_days"], 1)
            self.assertEqual(result["summary"]["effective_challenge_trading_days"], 1)
            self.assertEqual(result["summary"]["challenge_progress_label"], "1/10")
            self.assertEqual(gate["M10-PA-001-1d"]["paper_trial_gate"], "repair_now")
            self.assertEqual(gate["M10-PA-001-1d"]["action_state"], "repair_now")
            self.assertFalse(gate["M10-PA-001-1d"]["paper_candidate"])
            self.assertIn("concrete repair", gate["M10-PA-001-1d"]["gate_reason"])

    def test_audit_only_degraded_day_does_not_block_promotion_after_ten_valid_days(self):
        temp, config, m13_dir, m12_dir, output_dir = self.build_dirs()
        with temp:
            degraded = self.base_challenge_row("2026-05-07")
            degraded["data_quality_state"] = "degraded_no_fetch_or_fallback_quotes"
            degraded["data_freshness_warning"] = "fallback quotes / no-fetch"
            existing = [degraded] + [
                self.base_challenge_row(day)
                for day in [
                    "2026-04-27",
                    "2026-04-28",
                    "2026-04-29",
                    "2026-04-30",
                    "2026-05-01",
                    "2026-05-04",
                    "2026-05-05",
                    "2026-05-06",
                    "2026-05-11",
                ]
            ]
            self.write_jsonl(output_dir / "m14_challenge_day_ledger.jsonl", existing)
            self.write_fixture(m13_dir=m13_dir, m12_dir=m12_dir, trading_date="2026-05-12", data_ready=True)
            result = run_m14_strategy_challenge_gate(config, generated_at="2026-05-12T17:00:00Z", trading_date="2026-05-12")
            aggregate = result["strategy_aggregates"]["M10-PA-001-1d"]
            gate = {row["runtime_id"]: row for row in result["paper_gate"]["rows"]}
            self.assertEqual(aggregate["completed_trading_days"], 10)
            self.assertEqual(aggregate["data_mismatch_days"], 0)
            self.assertEqual(aggregate["observed_data_mismatch_days"], 1)
            self.assertEqual(gate["M10-PA-001-1d"]["paper_trial_gate"], "approved_internal_sim_only")

    def test_recompute_only_updates_gate_without_new_challenge_rows(self):
        temp, config, m13_dir, m12_dir, output_dir = self.build_dirs()
        with temp:
            existing = [
                self.base_challenge_row(day)
                for day in [
                    "2026-04-27",
                    "2026-04-28",
                    "2026-04-29",
                    "2026-04-30",
                    "2026-05-01",
                    "2026-05-04",
                    "2026-05-05",
                    "2026-05-06",
                    "2026-05-07",
                    "2026-05-08",
                ]
            ]
            self.write_jsonl(output_dir / "m14_challenge_day_ledger.jsonl", existing)
            result = run_m14_strategy_challenge_recompute(config, generated_at="2026-05-12T17:00:00Z", trading_date="2026-05-08")
            gate = {row["runtime_id"]: row for row in result["paper_gate"]["rows"]}
            rows = read_jsonl(output_dir / "m14_challenge_day_ledger.jsonl")
            goal_status = read_json(output_dir / "m14_goal_status.json")
            self.assertEqual(len(rows), 10)
            self.assertTrue(result["summary"]["recompute_only"])
            self.assertEqual(gate["M10-PA-001-1d"]["paper_trial_gate"], "approved_internal_sim_only")
            self.assertEqual(goal_status["challenge_progress_label"], "10/10")
            self.assertEqual(goal_status["paper_trial_gate_approved_count"], 1)
            self.assertEqual(goal_status["approved_internal_sim_strategy_ids"], ["M10-PA-001"])
            decision_ledger_text = (output_dir / "m14_strategy_decision_ledger.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("continue_testing", decision_ledger_text)
            self.assertNotIn("not_approved_modify_candidate", decision_ledger_text)

    def test_challenge_corrections_are_appended_without_mutating_base_ledger(self):
        temp, config, m13_dir, m12_dir, output_dir = self.build_dirs()
        with temp:
            self.write_fixture(m13_dir=m13_dir, m12_dir=m12_dir, data_ready=True)
            first = run_m14_strategy_challenge_gate(config, generated_at="2026-05-08T17:00:00Z", trading_date="2026-05-08")
            self.write_fixture(
                m13_dir=m13_dir,
                m12_dir=m12_dir,
                data_ready=True,
                account_event_type="close",
                realized_pnl="-100.00",
            )
            second = run_m14_strategy_challenge_gate(config, generated_at="2026-05-08T18:00:00Z", trading_date="2026-05-08")
            base_rows = read_jsonl(output_dir / "m14_challenge_day_ledger.jsonl")
            correction_rows = read_jsonl(output_dir / "m14_challenge_day_correction_ledger.jsonl")
            self.assertEqual(len(base_rows), 2)
            self.assertEqual(second["summary"]["appended_challenge_day_row_count"], 0)
            self.assertEqual(second["summary"]["appended_challenge_correction_row_count"], 1)
            self.assertEqual(len(correction_rows), 1)
            self.assertEqual(correction_rows[0]["runtime_id"], "M10-PA-001-1d")
            self.assertEqual(correction_rows[0]["realized_pnl"], "-100.00")
            aggregate = second["strategy_aggregates"]["M10-PA-001-1d"]
            self.assertEqual(aggregate["net_pnl_r"], "-1")
            self.assertEqual(first["summary"]["appended_challenge_day_row_count"], 2)

    def test_losing_baseline_creates_modify_variant_without_mutating_history(self):
        temp, config, _, _, _ = self.build_dirs()
        with temp:
            challenge_rows = [
                self.base_challenge_row("2026-05-04", realized_pnl="-100.00"),
                self.base_challenge_row("2026-05-05", realized_pnl="-100.00"),
                self.base_challenge_row("2026-05-06", realized_pnl="-100.00"),
            ]
            aggregates = build_strategy_aggregates(config, challenge_rows)
            decisions = build_strategy_decision_rows(
                config=config,
                generated_at="2026-05-08T17:00:00Z",
                trading_date=date.fromisoformat("2026-05-08"),
                aggregates=aggregates,
            )
            decision = decisions[0]
            self.assertEqual(decision["decision"], "repair_now")
            self.assertEqual(decision["action_state"], "repair_now")
            self.assertTrue(decision["circuit_breaker_triggered"])
            self.assertFalse(decision["frozen"])
            self.assertEqual(decision["position_size_multiplier"], "0.1")
            self.assertEqual(decision["next_variant_id"], "M10-PA-001-m14-repair-20260508")

    def test_profitable_high_drawdown_runtime_is_risk_limited_not_rejected(self):
        temp, config, _, _, _ = self.build_dirs()
        with temp:
            rows = []
            for day in ["2026-05-04", "2026-05-05", "2026-05-06"]:
                row = self.base_challenge_row(day, realized_pnl="250.00")
                row["strategy_id"] = "M10-PA-005"
                row["runtime_id"] = "M10-PA-005-5m"
                row["timeframe"] = "5m"
                row["max_drawdown_percent"] = "20.30"
                rows.append(row)
            aggregates = build_strategy_aggregates(config, rows)
            decisions = build_strategy_decision_rows(
                config=config,
                generated_at="2026-05-08T17:00:00Z",
                trading_date=date.fromisoformat("2026-05-08"),
                aggregates=aggregates,
            )
            decision = decisions[0]
            self.assertEqual(decision["runtime_id"], "M10-PA-005-5m")
            self.assertEqual(decision["decision"], "risk_limited_advance")
            self.assertEqual(decision["position_size_multiplier"], "0.25")
            self.assertTrue(decision["paper_candidate"])

    def test_same_parent_1d_and_5m_are_independent_runtime_gate_rows(self):
        temp, config, _, _, _ = self.build_dirs()
        with temp:
            rows = []
            for runtime_id, timeframe, realized in [
                ("M10-PA-013-1d", "1d", "-25.00"),
                ("M10-PA-013-5m", "5m", "150.00"),
            ]:
                row = self.base_challenge_row("2026-05-04", realized_pnl=realized)
                row["strategy_id"] = "M10-PA-013"
                row["runtime_id"] = runtime_id
                row["timeframe"] = timeframe
                rows.append(row)
            aggregates = build_strategy_aggregates(config, rows)
            decisions = build_strategy_decision_rows(
                config=config,
                generated_at="2026-05-08T17:00:00Z",
                trading_date=date.fromisoformat("2026-05-08"),
                aggregates=aggregates,
            )
            paper_gate = {
                row["runtime_id"]: row
                for row in build_paper_trial_gate(
                    config,
                    "2026-05-08T17:00:00Z",
                    {row["runtime_id"]: row for row in decisions},
                    aggregates,
                )["rows"]
            }

            self.assertEqual(set(paper_gate), {"M10-PA-013-1d", "M10-PA-013-5m"})
            self.assertEqual(paper_gate["M10-PA-013-5m"]["action_state"], "risk_limited_advance")
            self.assertEqual(paper_gate["M10-PA-013-5m"]["position_size_multiplier"], "0.5")
            self.assertEqual(paper_gate["M10-PA-013-1d"]["action_state"], "repair_now")

    def test_pa004_mbf_starts_parallel_variant_but_original_keeps_testing(self):
        temp, config, _, _, _ = self.build_dirs()
        with temp:
            aggregates = {
                "M10-PA-004-MBF": {
                    "strategy_id": "M10-PA-004-MBF",
                    "display_name": "PA004 momentum breakout follow-through experimental runtime",
                    "module_role": "independent_runtime",
                    "required_for_goal": False,
                    "completed_trading_days": 3,
                    "signal_days": 3,
                    "zero_signal_days": 0,
                    "total_signal_count": 5,
                    "open_count": 5,
                    "close_count": 3,
                    "realized_pnl": "-300.00",
                    "net_pnl_r": "-3",
                    "max_drawdown_percent": "2.01",
                    "risk_blocked_count": 0,
                    "risk_block_ratio": "0",
                    "data_mismatch_days": 0,
                }
            }
            decisions = build_strategy_decision_rows(
                config=config,
                generated_at="2026-05-13T20:00:00Z",
                trading_date=date.fromisoformat("2026-05-13"),
                aggregates=aggregates,
            )
            decision = decisions[0]
            self.assertEqual(decision["decision"], "risk_limited_advance")
            self.assertEqual(decision["decision_reason"], "parallel_repair_variant_started_size_limited_original")
            self.assertTrue(decision["circuit_breaker_triggered"])
            self.assertFalse(decision["frozen"])
            self.assertTrue(decision["modify_candidate"])
            self.assertEqual(decision["next_variant_id"], "M10-PA-004-MBF-QC")

    def test_promoted_strategy_uses_risk_before_internal_simulated_fill(self):
        temp, config, m13_dir, m12_dir, output_dir = self.build_dirs()
        with temp:
            self.write_fixture(m13_dir=m13_dir, m12_dir=m12_dir, data_ready=True)
            existing = [
                self.base_challenge_row(day)
                for day in [
                    "2026-04-27",
                    "2026-04-28",
                    "2026-04-29",
                    "2026-04-30",
                    "2026-05-01",
                    "2026-05-04",
                    "2026-05-05",
                    "2026-05-06",
                    "2026-05-07",
                ]
            ]
            self.write_jsonl(output_dir / "m14_challenge_day_ledger.jsonl", existing)
            result = run_m14_strategy_challenge_gate(config, generated_at="2026-05-08T17:00:00Z", trading_date="2026-05-08")
            gate = {row["runtime_id"]: row for row in result["paper_gate"]["rows"]}
            self.assertEqual(gate["M10-PA-001-1d"]["paper_trial_gate"], "approved_internal_sim_only")
            actions = [row["action"] for row in result["appended_execution_rows"]]
            self.assertLess(actions.index("risk_check"), actions.index("simulated_fill"))
            fill_rows = [row for row in result["appended_execution_rows"] if row["action"] == "simulated_fill"]
            self.assertEqual(len(fill_rows), 1)
            self.assertTrue(fill_rows[0]["fill_simulated"])
            self.assertTrue(all(not row["broker_paper_connection"] and not row["live_execution"] for row in result["appended_execution_rows"]))

    def test_internal_paper_bridge_processes_closes_before_next_open_exposure_check(self):
        temp, config, m13_dir, m12_dir, output_dir = self.build_dirs()
        with temp:
            config = replace(
                config,
                internal_paper=replace(config.internal_paper, max_total_exposure=Decimal("250")),
            )
            self.write_fixture(m13_dir=m13_dir, m12_dir=m12_dir, data_ready=True)
            existing = [
                self.base_challenge_row(day)
                for day in [
                    "2026-04-27",
                    "2026-04-28",
                    "2026-04-29",
                    "2026-04-30",
                    "2026-05-01",
                    "2026-05-04",
                    "2026-05-05",
                    "2026-05-06",
                    "2026-05-07",
                ]
            ]
            self.write_jsonl(output_dir / "m14_challenge_day_ledger.jsonl", existing)
            self.write_jsonl(
                m12_dir / "m12_46_account_trade_ledger.jsonl",
                [
                    {
                        "event_type": "open",
                        "runtime_id": "M10-PA-001-1d",
                        "strategy_id": "M10-PA-001",
                        "timeframe": "1d",
                        "symbol": "SPY",
                        "direction": "看涨",
                        "quantity": "2",
                        "entry_price": "100",
                        "stop_price": "95",
                        "target_price": "110",
                        "event_time": "2026-05-08T15:00:00Z",
                    },
                    {
                        "event_type": "close",
                        "runtime_id": "M10-PA-001-1d",
                        "strategy_id": "M10-PA-001",
                        "timeframe": "1d",
                        "symbol": "SPY",
                        "direction": "看涨",
                        "quantity": "2",
                        "entry_price": "100",
                        "exit_price": "101",
                        "stop_price": "95",
                        "target_price": "110",
                        "exit_reason": "fixture_close",
                        "event_time": "2026-05-08T15:05:00Z",
                    },
                    {
                        "event_type": "open",
                        "runtime_id": "M10-PA-001-1d",
                        "strategy_id": "M10-PA-001",
                        "timeframe": "1d",
                        "symbol": "QQQ",
                        "direction": "看涨",
                        "quantity": "2",
                        "entry_price": "100",
                        "stop_price": "95",
                        "target_price": "110",
                        "event_time": "2026-05-08T15:10:00Z",
                    },
                ],
            )

            result = run_m14_strategy_challenge_gate(config, generated_at="2026-05-08T17:00:00Z", trading_date="2026-05-08")

            actions = [row["action"] for row in result["appended_execution_rows"]]
            self.assertEqual(actions.count("simulated_fill"), 2)
            self.assertIn("position_closed", actions)
            self.assertNotIn("paper_order_blocked", actions)
            close_row = next(row for row in result["appended_execution_rows"] if row["action"] == "position_closed")
            self.assertEqual(close_row["realized_pnl"], "2")


if __name__ == "__main__":
    unittest.main()
