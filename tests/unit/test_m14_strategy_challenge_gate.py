import csv
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from scripts.m14_strategy_challenge_gate_lib import (
    build_strategy_aggregates,
    build_strategy_decision_rows,
    load_config,
    read_jsonl,
    run_m14_strategy_challenge_gate,
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
            gate = {row["strategy_id"]: row for row in second["paper_gate"]["rows"]}
            self.assertEqual(gate["M10-PA-001"]["paper_trial_gate"], "not_approved_data_quality")
            self.assertIn("fallback quotes / no-fetch", second["summary"]["data_freshness_warning"])

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
            self.assertEqual(decision["decision"], "modify")
            self.assertTrue(decision["circuit_breaker_triggered"])
            self.assertTrue(decision["frozen"])
            self.assertEqual(decision["next_variant_id"], "M10-PA-001-m14-modify-20260508")

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
            gate = {row["strategy_id"]: row for row in result["paper_gate"]["rows"]}
            self.assertEqual(gate["M10-PA-001"]["paper_trial_gate"], "approved_internal_sim_only")
            actions = [row["action"] for row in result["appended_execution_rows"]]
            self.assertLess(actions.index("risk_check"), actions.index("simulated_fill"))
            fill_rows = [row for row in result["appended_execution_rows"] if row["action"] == "simulated_fill"]
            self.assertEqual(len(fill_rows), 1)
            self.assertTrue(fill_rows[0]["fill_simulated"])
            self.assertTrue(all(not row["broker_paper_connection"] and not row["live_execution"] for row in result["appended_execution_rows"]))


if __name__ == "__main__":
    unittest.main()
