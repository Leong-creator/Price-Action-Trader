from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_longbridge_realtime_stale_order_cleanup_lib import load_config, run_stale_order_cleanup


class M15LongbridgeRealtimeStaleOrderCleanupTest(unittest.TestCase):
    def test_cancels_only_previous_session_buy_open_orders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = root / "account.json"
            config_path = root / "config.json"
            output_dir = root / "out"
            account_state.write_text(
                json.dumps(
                    {
                        "account_channel": "lb_papertrading",
                        "paper_account_verified": True,
                        "open_orders": [
                            {
                                "order_id": "old-buy",
                                "symbol": "GOOGL.US",
                                "side": "Buy",
                                "status": "New",
                                "created_at": "2026-06-04T17:00:00Z",
                                "quantity": "1",
                                "price": "364.00",
                            },
                            {
                                "order_id": "current-buy",
                                "symbol": "MSFT.US",
                                "side": "Buy",
                                "status": "New",
                                "created_at": "2026-06-05T13:35:00Z",
                                "quantity": "1",
                                "price": "400.00",
                            },
                            {
                                "order_id": "old-sell",
                                "symbol": "AAPL.US",
                                "side": "Sell",
                                "status": "New",
                                "created_at": "2026-06-04T17:00:00Z",
                                "quantity": "1",
                                "price": "320.00",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(
                    {
                        "stage": "M15.longbridge_realtime_stale_order_cleanup",
                        "inputs": {"account_state": str(account_state)},
                        "outputs": {"output_dir": str(output_dir)},
                        "stale_order_cleanup": {
                            "required_account_channel": "lb_papertrading",
                            "cli_name": "longbridge",
                            "cli_timeout_seconds": 6,
                            "cancel_stale_buy_orders": True,
                            "max_cancel_per_run": 20,
                        },
                        "hard_boundaries": {
                            "paper_simulated_only": True,
                            "live_execution": False,
                            "real_money_actions": False,
                            "cancel_sell_orders": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            commands: list[list[str]] = []

            def runner(command: list[str]):
                commands.append(command)
                return type("Result", (), {"returncode": 0, "stdout": json.dumps({"ok": True}), "stderr": ""})()

            payload = run_stale_order_cleanup(
                load_config(config_path),
                generated_at="2026-06-05T13:31:00Z",
                session_started_at="2026-06-05T13:30:00Z",
                command_runner=runner,
            )

            self.assertEqual(payload["cleanup_status"], "stale_buy_open_orders_canceled")
            self.assertEqual(payload["stale_buy_open_order_count"], 1)
            self.assertEqual(payload["current_session_stale_buy_open_order_count"], 0)
            self.assertEqual(payload["canceled_count"], 1)
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][1:4], ["order", "cancel", "old-buy"])
            self.assertIn("--yes", commands[0])

    def test_cancels_current_session_buy_order_after_ttl_but_keeps_sell_orders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = root / "account.json"
            config_path = root / "config.json"
            output_dir = root / "out"
            account_state.write_text(
                json.dumps(
                    {
                        "account_channel": "lb_papertrading",
                        "paper_account_verified": True,
                        "open_orders": [
                            {
                                "order_id": "stale-buy",
                                "symbol": "MRK.US",
                                "side": "Buy",
                                "status": "New",
                                "created_at": "2026-06-05T13:31:00Z",
                                "quantity": "1",
                                "price": "123.05",
                            },
                            {
                                "order_id": "fresh-buy",
                                "symbol": "MSFT.US",
                                "side": "Buy",
                                "status": "New",
                                "created_at": "2026-06-05T13:46:00Z",
                                "quantity": "1",
                                "price": "400.00",
                            },
                            {
                                "order_id": "stale-sell",
                                "symbol": "TSLA.US",
                                "side": "Sell",
                                "status": "New",
                                "created_at": "2026-06-05T13:31:00Z",
                                "quantity": "1",
                                "price": "420.00",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(
                    {
                        "stage": "M15.longbridge_realtime_stale_order_cleanup",
                        "inputs": {"account_state": str(account_state)},
                        "outputs": {"output_dir": str(output_dir)},
                        "stale_order_cleanup": {
                            "required_account_channel": "lb_papertrading",
                            "cli_name": "longbridge",
                            "cli_timeout_seconds": 6,
                            "cancel_stale_buy_orders": True,
                            "cleanup_current_session_stale_buy_orders": True,
                            "stale_buy_order_ttl_seconds": 900,
                            "max_cancel_per_run": 20,
                        },
                        "hard_boundaries": {
                            "paper_simulated_only": True,
                            "live_execution": False,
                            "real_money_actions": False,
                            "cancel_sell_orders": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            commands: list[list[str]] = []

            def runner(command: list[str]):
                commands.append(command)
                return type("Result", (), {"returncode": 0, "stdout": json.dumps({"ok": True}), "stderr": ""})()

            payload = run_stale_order_cleanup(
                load_config(config_path),
                generated_at="2026-06-05T13:47:00Z",
                session_started_at="2026-06-05T13:30:00Z",
                command_runner=runner,
            )

            self.assertEqual(payload["cleanup_status"], "stale_buy_open_orders_canceled")
            self.assertEqual(payload["stale_buy_open_order_count"], 1)
            self.assertEqual(payload["current_session_stale_buy_open_order_count"], 1)
            self.assertEqual(payload["canceled_count"], 1)
            self.assertEqual(commands[0][1:4], ["order", "cancel", "stale-buy"])

    def test_blocks_cleanup_when_paper_account_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = root / "account.json"
            config_path = root / "config.json"
            output_dir = root / "out"
            account_state.write_text(
                json.dumps(
                    {
                        "account_channel": "lb_papertrading",
                        "open_orders": [
                            {
                                "order_id": "old-buy",
                                "symbol": "GOOGL.US",
                                "side": "Buy",
                                "status": "New",
                                "created_at": "2026-06-04T17:00:00Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(
                    {
                        "stage": "M15.longbridge_realtime_stale_order_cleanup",
                        "inputs": {"account_state": str(account_state)},
                        "outputs": {"output_dir": str(output_dir)},
                        "stale_order_cleanup": {"required_account_channel": "lb_papertrading"},
                        "hard_boundaries": {
                            "paper_simulated_only": True,
                            "live_execution": False,
                            "real_money_actions": False,
                            "cancel_sell_orders": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            commands: list[list[str]] = []
            payload = run_stale_order_cleanup(
                load_config(config_path),
                generated_at="2026-06-05T13:31:00Z",
                session_started_at="2026-06-05T13:30:00Z",
                command_runner=lambda command: commands.append(command),
            )

            self.assertEqual(payload["cleanup_status"], "blocked_cleanup_not_safe")
            self.assertIn("paper_account_not_verified", payload["blockers"])
            self.assertFalse(payload["paper_account_verified"])
            self.assertEqual(commands, [])


if __name__ == "__main__":
    unittest.main()
