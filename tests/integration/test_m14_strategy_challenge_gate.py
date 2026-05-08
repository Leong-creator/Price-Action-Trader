import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m14_strategy_challenge_gate_lib import load_config, read_jsonl, run_m14_strategy_challenge_gate


class M14StrategyChallengeGateIntegrationTest(unittest.TestCase):
    def test_m13_daily_ledger_rolls_into_m14_challenge_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            m13_dir = root / "m13"
            m12_dir = root / "m12"
            output_dir = root / "m14"
            m13_dir.mkdir(parents=True)
            m12_dir.mkdir(parents=True)
            output_dir.mkdir(parents=True)
            config = replace(load_config(), m13_output_dir=m13_dir, m12_29_output_dir=m12_dir, output_dir=output_dir)

            existing_rows = [
                self.challenge_row("M10-PA-001", "M10-PA-001-1d", "2026-05-06", "5.00"),
                self.challenge_row("M10-PA-001", "M10-PA-001-1d", "2026-05-07", "5.00"),
            ]
            self.write_jsonl(output_dir / "m14_challenge_day_ledger.jsonl", existing_rows)
            self.write_jsonl(
                m13_dir / "m13_strategy_signal_ledger.jsonl",
                [
                    {
                        "schema_version": "m13.strategy-signal-ledger.v1",
                        "generated_at": "2026-05-08T16:00:00Z",
                        "trading_date": "2026-05-08",
                        "strategy_id": "M10-PA-001",
                        "display_name": "Trend pullback runtime",
                        "module_role": "independent_runtime",
                        "runtime_id": "M10-PA-001-1d",
                        "lane": "mainline",
                        "timeframe": "1d",
                        "variant_id": "base",
                        "required_for_goal": True,
                        "detector_id": "fixture",
                        "test_state": "signal_generated",
                        "signal_count": 1,
                        "next_action": "continue",
                    }
                ],
            )
            self.write_jsonl(
                m13_dir / "m13_account_operation_ledger.jsonl",
                [
                    {
                        "schema_version": "m13.account-operation-ledger.v1",
                        "generated_at": "2026-05-08T16:00:00Z",
                        "trading_date": "2026-05-08",
                        "strategy_id": "M10-PA-001",
                        "display_name": "Trend pullback runtime",
                        "module_role": "independent_runtime",
                        "required_for_goal": True,
                        "runtime_id": "M10-PA-001-1d",
                        "lane": "mainline",
                        "timeframe": "1d",
                        "variant_id": "base",
                        "event_type": "close",
                        "test_state": "close",
                        "symbol": "SPY",
                        "direction": "long",
                        "quantity": "1",
                        "entry_price": "10",
                        "exit_price": "15",
                        "realized_pnl": "5.00",
                        "source_event_time": "2026-05-08T15:00:00Z",
                        "equity": "20015.00",
                    }
                ],
            )
            (m13_dir / "m13_daily_strategy_test_summary.json").write_text(
                json.dumps({"ready_for_complete_reliable_testing": True, "trading_date": "2026-05-08"}),
                encoding="utf-8",
            )
            (m12_dir / "m12_32_minute_readonly_dashboard_data.json").write_text(
                json.dumps(
                    {
                        "summary": {
                            "scan_date": "2026-05-08",
                            "current_day_runtime_ready": True,
                            "current_day_scan_complete": True,
                            "quote_source": "longbridge_quote_readonly",
                            "first50_daily_ready_symbols": 50,
                            "first50_current_5m_ready_symbols": 50,
                            "runtime_readiness_note": "ready",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with (m12_dir / "m12_46_account_scorecards.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["runtime_id", "equity", "max_drawdown_percent"], lineterminator="\n")
                writer.writeheader()
                writer.writerow({"runtime_id": "M10-PA-001-1d", "equity": "20015.00", "max_drawdown_percent": "1.00"})
            self.write_jsonl(m12_dir / "m12_46_account_trade_ledger.jsonl", [])

            result = run_m14_strategy_challenge_gate(config, generated_at="2026-05-08T17:00:00Z", trading_date="2026-05-08")
            ledger_rows = read_jsonl(output_dir / "m14_challenge_day_ledger.jsonl")
            self.assertEqual(result["summary"]["challenge_day_ledger_row_count"], len(ledger_rows))
            self.assertEqual(result["strategy_aggregates"]["M10-PA-001"]["completed_trading_days"], 3)
            self.assertEqual(result["strategy_aggregates"]["M10-PA-001"]["realized_pnl"], "15.00")
            self.assertFalse(result["summary"]["broker_paper_connection"])
            self.assertIn("策略挑战榜", (output_dir / "m14_strategy_challenge_dashboard.html").read_text(encoding="utf-8"))

    def challenge_row(self, strategy_id: str, runtime_id: str, trading_date: str, realized_pnl: str) -> dict:
        return {
            "schema_version": "m14.challenge-day-ledger.v1",
            "generated_at": f"{trading_date}T20:00:00Z",
            "trading_date": trading_date,
            "strategy_id": strategy_id,
            "display_name": "Trend pullback runtime",
            "module_role": "independent_runtime",
            "runtime_id": runtime_id,
            "lane": "mainline",
            "timeframe": "1d",
            "variant_id": "base",
            "required_for_goal": True,
            "test_state": "signal_generated",
            "account_test_states": "close",
            "signal_count": 1,
            "zero_signal_day": False,
            "open_count": 1,
            "close_count": 1,
            "risk_blocked_count": 0,
            "realized_pnl": realized_pnl,
            "net_pnl_r": "0.05",
            "equity": "20000.00",
            "max_drawdown_percent": "1.00",
            "blocker_reason": "",
            "data_quality_state": "fully_ready",
            "data_freshness_warning": "",
        }

    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
