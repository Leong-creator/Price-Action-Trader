from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_longbridge_realtime_position_manager_lib import (
    LEDGER_JSONL,
    SUMMARY_JSON,
    load_config,
    run_realtime_position_manager,
)


class M15LongbridgeRealtimePositionManagerTest(unittest.TestCase):
    def test_take_profit_generates_close_long_signal_from_longbridge_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(root / "account_state.json", self.account_state())
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="111")])
            self.write_jsonl(root / "execution_ledger.jsonl", [self.open_row(target_price="110")])

            payload = run_realtime_position_manager(config, generated_at="2026-06-04T14:00:00Z")
            signals = self.read_jsonl(root / "signals.jsonl")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["new_exit_signal_event_count"], 1)
            self.assertEqual(signals[0]["side"], "sell")
            self.assertEqual(signals[0]["position_action"], "take_profit")
            self.assertEqual(signals[0]["quantity"], "2")
            self.assertFalse(signals[0]["local_simulation_source"])
            self.assertTrue(signals[0]["longbridge_position_exit_source"])
            self.assertEqual(rows[0]["manager_status"], "exit_signal_created")

    def test_stop_loss_generates_close_long_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(root / "account_state.json", self.account_state())
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="94")])
            self.write_jsonl(root / "execution_ledger.jsonl", [self.open_row(stop_price="95")])

            run_realtime_position_manager(config, generated_at="2026-06-04T14:00:00Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(signals[0]["position_action"], "stop_loss")

    def test_unavailable_position_does_not_generate_repeated_exit_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(root / "account_state.json", self.account_state(available="0"))
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="94")])
            self.write_jsonl(root / "execution_ledger.jsonl", [self.open_row(stop_price="95")])

            payload = run_realtime_position_manager(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_exit_signal_event_count"], 0)
            self.assertEqual(rows[0]["manager_status"], "position_not_available_for_exit")
            self.assertEqual(rows[0]["available_quantity"], "0")
            self.assertEqual(signals, [])

    def test_exit_signal_id_is_stable_across_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(root / "account_state.json", self.account_state())
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="94")])
            self.write_jsonl(root / "execution_ledger.jsonl", [self.open_row(stop_price="95")])

            first = run_realtime_position_manager(config, generated_at="2026-06-04T14:00:00Z")
            second = run_realtime_position_manager(config, generated_at="2026-06-04T14:01:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(first["new_exit_signal_event_count"], 1)
            self.assertEqual(second["new_exit_signal_event_count"], 0)
            self.assertEqual(rows[0]["manager_status"], "duplicate_exit_signal_event")
            self.assertEqual(len(signals), 1)

    def test_untracked_position_is_exit_only_takeover_not_local_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(root / "account_state.json", self.account_state())
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="111")])
            self.write_jsonl(root / "execution_ledger.jsonl", [{"symbol": "AAPL", "side": "buy", "submission_status": "dry_run_ready_not_submitted"}])

            payload = run_realtime_position_manager(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["new_exit_signal_event_count"], 0)
            self.assertEqual(rows[0]["manager_status"], "exit_only_hold_no_exit_trigger")
            self.assertEqual(rows[0]["position_management_scope"], "longbridge_account_exit_only")
            self.assertTrue(rows[0]["exit_only_takeover"])
            self.assertTrue(rows[0]["exit_allowed"])
            self.assertEqual(payload["managed_position_count"], 0)
            self.assertEqual(payload["exit_only_position_count"], 1)
            self.assertEqual(payload["unmanaged_position_count"], 0)
            self.assertEqual(payload["exit_only_position_symbols"], ["AAPL"])
            self.assertIn("只接管退出", payload["plain_language_result"])
            self.assertEqual(payload["inputs"]["local_simulation_ledger"], "")

    def test_untracked_position_exit_only_can_create_stop_loss_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(root / "account_state.json", self.account_state(cost_price="100"))
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="96")])
            self.write_jsonl(root / "execution_ledger.jsonl", [])

            payload = run_realtime_position_manager(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_exit_signal_event_count"], 1)
            self.assertEqual(payload["exit_only_position_count"], 1)
            self.assertEqual(rows[0]["position_management_scope"], "longbridge_account_exit_only")
            self.assertEqual(signals[0]["position_action"], "stop_loss")
            self.assertTrue(signals[0]["longbridge_untracked_exit_only"])
            self.assertTrue(signals[0]["longbridge_position_exit_source"])

    def test_exit_quantity_is_capped_to_virtual_bucket_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(root / "account_state.json", self.account_state(quantity="10", available="10"))
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="111")])
            self.write_jsonl(
                root / "execution_ledger.jsonl",
                [
                    self.open_row(
                        signal_id="pa002-open",
                        runtime_id="M10-PA-002-5m",
                        strategy_id="M10-PA-002",
                        capital_bucket="pa002_5m",
                        quantity="3",
                        target_price="110",
                    ),
                    self.open_row(
                        signal_id="ftd-open",
                        runtime_id="M12-FTD-001-baseline-1d",
                        strategy_id="M12-FTD-001",
                        capital_bucket="ftd_baseline",
                        quantity="7",
                        target_price="120",
                    ),
                ],
            )

            payload = run_realtime_position_manager(config, generated_at="2026-06-04T14:00:00Z")
            signals = self.read_jsonl(root / "signals.jsonl")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["account_position_count"], 1)
            self.assertEqual(payload["managed_position_count"], 2)
            self.assertEqual(payload["new_exit_signal_event_count"], 1)
            self.assertEqual(signals[0]["runtime_id"], "M10-PA-002-5m")
            self.assertEqual(signals[0]["quantity"], "3")
            self.assertEqual(rows[0]["quantity"], "3")
            self.assertEqual(rows[0]["account_symbol_quantity"], "10")
            self.assertEqual(rows[0]["virtual_position_quantity"], "3")

    def make_config(self, root: Path):
        payload = {
            "stage": "M15.longbridge_realtime_position_manager",
            "title": "长桥模拟账户实时持仓退出管理",
            "inputs": {
                "account_state": str(root / "account_state.json"),
                "market_events": str(root / "market_events.jsonl"),
                "realtime_signal_events": str(root / "signals.jsonl"),
                "realtime_execution_ledger": str(root / "execution_ledger.jsonl"),
            },
            "outputs": {"output_dir": str(root / "out")},
            "longbridge_position_manager": {"max_exit_events_per_run": 10},
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_exit_source": False,
                "short_selling": False,
            },
        }
        path = root / "config.json"
        self.write_json(path, payload)
        return load_config(path)

    def account_state(self, *, quantity: str = "2", available: str = "2", cost_price: str | None = None) -> dict:
        position = {"symbol": "AAPL.US", "quantity": quantity, "available": available, "market_price": "100"}
        if cost_price is not None:
            position["cost_price"] = cost_price
        return {
            "account_channel": "lb_papertrading",
            "paper_account_verified": True,
            "positions": [position],
            "held_symbols": ["AAPL"],
        }

    def market_event(self, **overrides: object) -> dict:
        row = {"event_id": "bar-1", "symbol": "AAPL", "event_time": "2026-06-04T14:00:00Z", "close": "100"}
        row.update(overrides)
        return row

    def open_row(self, **overrides: object) -> dict:
        row = {
            "signal_id": "open-1",
            "runtime_id": "M10-PA-004-long-1d",
            "strategy_id": "M10-PA-004",
            "symbol": "AAPL",
            "timeframe": "1d",
            "side": "buy",
            "quantity": "2",
            "stop_price": "95",
            "target_price": "110",
            "submission_status": "submitted",
            "source_market_event_id": "bar-1",
        }
        row.update(overrides)
        return row

    def write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def read_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
