from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_longbridge_paper_session_report_lib import (
    RECONCILIATION_CSV,
    SUMMARY_JSON,
    load_config,
    run_session_report,
)


class M15LongbridgePaperSessionReportTest(unittest.TestCase):
    def test_report_summarizes_first_hour_and_reconciles_account_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            out.mkdir()
            execution_ledger = root / "execution.jsonl"
            account_state = root / "account.json"
            execution_summary = root / "execution_summary.json"
            position_manager = root / "position_manager.json"
            session_supervisor = root / "session_supervisor.json"
            self.write_jsonl(
                execution_ledger,
                [
                    self.submitted("sig-aapl", "M10-PA-004-long-1d", "AAPL", "buy", 1, "100.00", "2026-06-04T13:31:00Z"),
                    self.submitted("sig-msft", "M10-PA-004-long-1d", "MSFT", "buy", 2, "200.00", "2026-06-04T13:40:00Z"),
                    self.submitted("sig-baba", "M10-PA-005-1d", "BABA", "buy", 3, "126.00", "2026-06-04T13:45:00Z"),
                    self.submitted("sig-baba-exit", "M10-PA-005-1d", "BABA", "sell", 3, "125.00", "2026-06-04T14:35:00Z"),
                ],
            )
            self.write_json(
                account_state,
                {
                    "generated_at": "2026-06-04T14:40:00Z",
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "cash": "9900",
                    "buying_power": "10000",
                    "total_position_notional": "100",
                    "total_open_order_notional": "400",
                    "positions": [
                        {"symbol": "AAPL.US", "quantity": "1", "cost_price": "100.00"},
                    ],
                    "orders": [
                        {
                            "symbol": "AAPL.US",
                            "side": "Buy",
                            "quantity": "1",
                            "price": "100.000",
                            "order_id": "order-aapl",
                            "status": "Filled",
                            "executed_quantity": "1",
                        },
                        {
                            "symbol": "MSFT.US",
                            "side": "Buy",
                            "quantity": "2",
                            "price": "200.000",
                            "order_id": "order-msft",
                            "status": "New",
                            "executed_quantity": "0",
                        },
                        {
                            "symbol": "BABA.US",
                            "side": "Buy",
                            "quantity": "3",
                            "price": "126.000",
                            "order_id": "order-baba-buy",
                            "status": "Filled",
                            "executed_quantity": "3",
                        },
                        {
                            "symbol": "BABA.US",
                            "side": "Sell",
                            "quantity": "3",
                            "price": "125.000",
                            "order_id": "order-baba-sell",
                            "status": "Filled",
                            "executed_quantity": "3",
                        },
                    ],
                    "open_orders": [
                        {
                            "symbol": "MSFT.US",
                            "side": "Buy",
                            "quantity": "2",
                            "price": "200.000",
                            "order_id": "order-msft",
                            "status": "New",
                            "executed_quantity": "0",
                        }
                    ],
                },
            )
            self.write_json(
                execution_summary,
                {
                    "generated_at": "2026-06-04T14:40:00Z",
                    "ready_order_count": 0,
                    "submitted_count": 0,
                    "blocked_signal_count": 8,
                    "blocked_by_reason": {"blocked_total_exposure_over_cap": 7, "duplicate_signal_already_submitted": 1},
                },
            )
            self.write_json(
                position_manager,
                {
                    "generated_at": "2026-06-04T14:40:00Z",
                    "managed_position_count": 1,
                    "new_exit_signal_event_count": 1,
                    "blocked_by_reason": {"hold_no_exit_trigger": 1},
                },
            )
            self.write_json(
                session_supervisor,
                {
                    "generated_at": "2026-06-04T14:40:00Z",
                    "window": {"market_date": "2026-06-04"},
                },
            )
            config_path = root / "config.json"
            self.write_json(
                config_path,
                {
                    "stage": "M15.longbridge_paper_session_report",
                    "inputs": {
                        "execution_ledger": str(execution_ledger),
                        "execution_summary": str(execution_summary),
                        "account_state": str(account_state),
                        "position_manager": str(position_manager),
                        "session_supervisor": str(session_supervisor),
                    },
                    "outputs": {"output_dir": str(out)},
                    "report": {
                        "market_timezone": "America/New_York",
                        "regular_session_start_time": "09:30",
                        "first_window_minutes": 60,
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "live_execution": False,
                        "real_money_actions": False,
                        "local_simulation_as_order_source": False,
                        "manual_m12_37_once": False,
                    },
                },
            )

            payload = run_session_report(load_config(config_path), generated_at="2026-06-04T14:40:00Z")

            self.assertEqual(payload["submitted_order_count"], 4)
            self.assertEqual(payload["first_window_submitted_order_count"], 3)
            self.assertEqual(payload["after_first_window_submitted_order_count"], 1)
            self.assertEqual(payload["submitted_buy_count"], 3)
            self.assertEqual(payload["submitted_sell_count"], 1)
            self.assertEqual(payload["current_position_symbols"], ["AAPL"])
            self.assertEqual(payload["current_open_order_symbols"], ["MSFT"])
            statuses = {row["signal_id"]: row for row in payload["reconciliation_rows"]}
            self.assertEqual(statuses["sig-aapl"]["reconciliation_status"], "materialized_position")
            self.assertEqual(statuses["sig-aapl"]["inferred_order_id"], "order-aapl")
            self.assertEqual(statuses["sig-msft"]["reconciliation_status"], "open_order")
            self.assertEqual(statuses["sig-msft"]["inferred_order_id"], "order-msft")
            self.assertEqual(statuses["sig-baba"]["reconciliation_status"], "closed_or_flattened_by_later_sell")
            self.assertEqual(statuses["sig-baba"]["inferred_order_id"], "order-baba-buy")
            self.assertEqual(statuses["sig-baba-exit"]["reconciliation_status"], "sell_materialized_flat_position")
            self.assertEqual(statuses["sig-baba-exit"]["inferred_order_id"], "order-baba-sell")
            self.assertEqual(payload["reconciliation"]["unmatched_count"], 0)
            self.assertEqual(payload["reconciliation"]["inferred_order_id_count"], 4)
            self.assertEqual(payload["reconciliation"]["reconciled_order_id_count"], 4)
            self.assertEqual(payload["reconciliation"]["unresolved_order_id_count"], 0)
            self.assertTrue((out / SUMMARY_JSON).exists())
            self.assertTrue((out / RECONCILIATION_CSV).exists())

    def test_config_rejects_live_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            self.write_json(
                config_path,
                {
                    "stage": "M15.longbridge_paper_session_report",
                    "outputs": {"output_dir": str(root / "out")},
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "live_execution": True,
                        "real_money_actions": False,
                        "local_simulation_as_order_source": False,
                        "manual_m12_37_once": False,
                    },
                },
            )

            with self.assertRaisesRegex(ValueError, "live execution"):
                load_config(config_path)

    def submitted(
        self,
        signal_id: str,
        runtime_id: str,
        symbol: str,
        side: str,
        quantity: int,
        limit_price: str,
        submitted_at: str,
    ) -> dict:
        return {
            "submission_status": "submitted",
            "submitted_at": submitted_at,
            "processed_at": submitted_at,
            "created_at": submitted_at,
            "signal_id": signal_id,
            "runtime_id": runtime_id,
            "strategy_id": "-".join(runtime_id.split("-")[:3]),
            "symbol": symbol,
            "side": side,
            "order_type": "limit",
            "quantity": str(quantity),
            "limit_price": limit_price,
            "notional": str(quantity * float(limit_price)),
            "submission_response": {"order_id": "", "submitted": True},
        }

    def write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
