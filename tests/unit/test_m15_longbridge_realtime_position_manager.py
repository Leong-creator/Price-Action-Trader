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

    def test_no_local_or_untracked_position_exit_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(root / "account_state.json", self.account_state())
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="111")])
            self.write_jsonl(root / "execution_ledger.jsonl", [{"symbol": "AAPL", "side": "buy", "submission_status": "dry_run_ready_not_submitted"}])

            payload = run_realtime_position_manager(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["new_exit_signal_event_count"], 0)
            self.assertEqual(rows[0]["manager_status"], "legacy_unmanaged_longbridge_position")
            self.assertEqual(rows[0]["position_management_scope"], "longbridge_account_unmanaged")
            self.assertEqual(payload["managed_position_count"], 0)
            self.assertEqual(payload["unmanaged_position_count"], 1)
            self.assertEqual(payload["unmanaged_position_symbols"], ["AAPL"])
            self.assertIn("只展示，不自动平仓", payload["plain_language_result"])
            self.assertEqual(payload["inputs"]["local_simulation_ledger"], "")

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

    def account_state(self) -> dict:
        return {
            "account_channel": "lb_papertrading",
            "paper_account_verified": True,
            "positions": [{"symbol": "AAPL.US", "quantity": "2", "market_price": "100"}],
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
