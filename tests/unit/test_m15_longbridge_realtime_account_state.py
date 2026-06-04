from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_longbridge_realtime_account_state_lib import (
    ACCOUNT_STATE_JSON,
    CommandResult,
    LEDGER_JSONL,
    SUMMARY_JSON,
    assert_account_state_command,
    load_config,
    run_realtime_account_state,
)


class M15LongbridgeRealtimeAccountStateTest(unittest.TestCase):
    def test_reads_paper_account_state_without_order_submit_or_local_simulation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            commands: list[list[str]] = []

            payload = run_realtime_account_state(
                config,
                generated_at="2026-06-04T14:00:00Z",
                command_runner=self.runner(commands=commands),
            )
            account_state = json.loads((config.output_dir / ACCOUNT_STATE_JSON).read_text(encoding="utf-8"))
            ledger = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["account_status"], "paper_account_ready")
            self.assertTrue(account_state["paper_account_verified"])
            self.assertEqual(account_state["account_channel"], "lb_papertrading")
            self.assertEqual(account_state["buying_power"], "10000.00")
            self.assertEqual(account_state["held_symbols"], ["AAPL"])
            self.assertEqual(account_state["position_notional_by_symbol"], {"AAPL": "200.00"})
            self.assertEqual(account_state["open_order_count"], 1)
            self.assertEqual(account_state["open_order_notional_by_symbol"], {"MSFT": "300.00"})
            self.assertTrue(payload["local_simulation_isolated"])
            self.assertFalse(payload["order_submit_or_cancel_command_used"])
            self.assertEqual(ledger[0]["account_status"], "paper_account_ready")
            self.assertFalse(any(command[1:3] in (["order", "buy"], ["order", "sell"]) for command in commands))

    def test_non_paper_account_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)

            payload = run_realtime_account_state(
                config,
                generated_at="2026-06-04T14:00:00Z",
                command_runner=self.runner(account_channel="lb_trade"),
            )

            self.assertEqual(payload["account_status"], "account_channel_not_paper")
            self.assertIn("account_channel_not_paper", payload["blockers"])

    def test_command_guard_rejects_submit_or_cancel_shapes(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot submit or cancel"):
            assert_account_state_command(["longbridge", "order", "buy", "AAPL.US", "1", "--yes", "--format", "json"])
        with self.assertRaisesRegex(ValueError, "cannot submit or cancel"):
            assert_account_state_command(["longbridge", "order", "cancel", "123", "--format", "json"])

    def make_config(self, root: Path):
        payload = {
            "stage": "M15.longbridge_realtime_account_state",
            "title": "长桥模拟账户实时账户状态",
            "outputs": {
                "output_dir": str(root / "out"),
                "account_state": str(root / "out" / ACCOUNT_STATE_JSON),
            },
            "longbridge_account_state": {
                "cli_name": "longbridge",
                "required_account_channel": "lb_papertrading",
                "cli_timeout_seconds": 6,
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_account_source": False,
                "order_submit_or_cancel_commands": False,
            },
        }
        path = root / "config.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return load_config(path)

    def runner(self, *, commands: list[list[str]] | None = None, account_channel: str = "lb_papertrading"):
        def _run(command: list[str]) -> CommandResult:
            if commands is not None:
                commands.append(command)
            args = command[1:]
            if args[:2] == ["auth", "status"]:
                return CommandResult(0, json.dumps({"account": {"account_channel": account_channel, "account_type": "M"}}), "")
            if args[:1] == ["assets"]:
                return CommandResult(0, json.dumps([{"buy_power": "10000", "cash": "10000"}]), "")
            if args[:1] == ["positions"]:
                return CommandResult(0, json.dumps([{"symbol": "AAPL.US", "quantity": "2", "market_price": "100"}]), "")
            if args[:1] == ["order"]:
                return CommandResult(
                    0,
                    json.dumps(
                        [
                            {"order_id": "open-1", "symbol": "MSFT.US", "quantity": "3", "price": "100", "status": "Submitted"},
                            {"order_id": "filled-1", "symbol": "NVDA.US", "quantity": "1", "price": "120", "status": "Filled"},
                        ]
                    ),
                    "",
                )
            return CommandResult(1, "", "unexpected command")

        return _run

    def read_jsonl(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
