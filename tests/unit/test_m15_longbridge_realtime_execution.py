from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_longbridge_realtime_execution_lib import (
    LEDGER_JSONL,
    LongbridgeCliRealtimePaperClient,
    SUMMARY_JSON,
    longbridge_order_command,
    load_config,
    run_realtime_execution,
)


class FakeRealtimePaperClient:
    def __init__(self) -> None:
        self.orders: list[dict] = []

    def submit_order(self, order_payload: dict) -> dict:
        self.orders.append(order_payload)
        return {"submitted": True, "order_id": f"PAPER-{len(self.orders)}"}


class M15LongbridgeRealtimeExecutionTest(unittest.TestCase):
    def test_realtime_execution_does_not_reference_local_simulation_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="sig-1")])
            (root / "m12_46_account_trade_ledger.jsonl").write_text(
                json.dumps({"event": "close", "symbol": "AAPL"}) + "\n",
                encoding="utf-8",
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")

            self.assertEqual(payload["source_mode"], "longbridge_realtime_signal_events")
            self.assertTrue(payload["local_simulation_isolated"])
            self.assertEqual(payload["inputs"]["local_simulation_ledger"], "")
            self.assertEqual(payload["inputs"]["fast_signal_queue"], "")
            summary_text = (config.output_dir / SUMMARY_JSON).read_text(encoding="utf-8")
            self.assertNotIn("m12_46_account_trade_ledger", summary_text)

    def test_local_simulation_close_event_does_not_block_longbridge_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="sig-close-ignored",
                        latest_close_event_time_after_open="2026-06-04T14:00:10Z",
                        local_close_event_id="local-close-1",
                    )
                ],
            )

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(rows[0]["realtime_decision_status"], "latency_target_met_ready")
            self.assertTrue(rows[0]["local_close_event_ignored"])
            self.assertFalse(rows[0]["m13_m14_gate_used_for_order"])
            self.assertEqual(rows[0]["submission_status"], "dry_run_ready_not_submitted")

    def test_repair_auxiliary_and_shadow_runtimes_are_local_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(signal_id="repair", runtime_id="M10-PA-002-5m", strategy_id="M10-PA-002"),
                    self.signal(signal_id="aux", runtime_id="M10-PA-003", strategy_id="M10-PA-003"),
                    self.signal(signal_id="shadow", runtime_id="M10-PA-004-MBF-1d", strategy_id="M10-PA-004"),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["ready_order_count"], 0)
            self.assertEqual(rows[0]["realtime_decision_status"], "blocked_repair_runtime_local_only")
            self.assertEqual(rows[1]["realtime_decision_status"], "blocked_auxiliary_module_local_only")
            self.assertEqual(rows[2]["realtime_decision_status"], "blocked_shadow_runtime_local_only")

    def test_latency_bands_and_delayed_signal_revalidation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(signal_id="target", symbol="AAPL", created_at="2026-06-04T13:59:59.500Z"),
                    self.signal(signal_id="acceptable", symbol="MSFT", created_at="2026-06-04T13:59:57Z"),
                    self.signal(signal_id="delayed", symbol="NVDA", created_at="2026-06-04T13:59:53Z"),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["latency_counts"]["target_met"], 1)
            self.assertEqual(payload["latency_counts"]["acceptable"], 1)
            self.assertEqual(payload["latency_counts"]["delayed_revalidated"], 1)
            self.assertEqual(rows["target"]["realtime_decision_status"], "latency_target_met_ready")
            self.assertEqual(rows["acceptable"]["realtime_decision_status"], "latency_acceptable_ready")
            self.assertEqual(rows["delayed"]["realtime_decision_status"], "latency_delayed_revalidated_ready")
            self.assertNotIn("missed", rows["delayed"]["realtime_decision_status"])

    def test_limit_and_trigger_limit_orders_are_built_from_realtime_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, execute_orders=True, paper_trading_approval=True)
            client = FakeRealtimePaperClient()
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(signal_id="limit-order", symbol="AAPL", order_type="limit"),
                    self.signal(signal_id="trigger-order", symbol="MSFT", order_type="trigger_limit", trigger_price="101.00"),
                ],
            )

            payload = run_realtime_execution(
                config,
                generated_at="2026-06-04T14:00:00Z",
                broker_client=client,
            )

            self.assertEqual(payload["submitted_count"], 2)
            self.assertEqual(client.orders[0]["order_type"], "limit")
            self.assertNotIn("trigger_price", client.orders[0])
            self.assertEqual(client.orders[1]["order_type"], "trigger_limit")
            self.assertEqual(client.orders[1]["trigger_price"], "101.00")

    def test_longbridge_cli_client_builds_limit_and_trigger_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, execute_orders=True, paper_trading_approval=True)
            commands: list[list[str]] = []

            def runner(command: list[str]):
                commands.append(command)
                return type("Result", (), {"returncode": 0, "stdout": json.dumps({"order_id": "rt-1"}), "stderr": ""})()

            client = LongbridgeCliRealtimePaperClient(config, command_runner=runner, cli_path="longbridge")
            response = client.submit_order(
                {
                    "signal_id": "sig-cli",
                    "runtime_id": "M10-PA-004-long-1d",
                    "symbol": "AAPL",
                    "side": "buy",
                    "order_type": "trigger_limit",
                    "quantity": 2,
                    "limit_price": "101.20",
                    "trigger_price": "101.00",
                }
            )

            self.assertTrue(response["submitted"])
            self.assertEqual(response["order_id"], "rt-1")
            self.assertEqual(commands[0][:4], ["longbridge", "order", "buy", "AAPL.US"])
            self.assertIn("--outside-rth", commands[0])
            self.assertIn("RTH_ONLY", commands[0])
            self.assertIn("--trigger-price", commands[0])
            self.assertNotIn("--yes", response["command"])

    def test_longbridge_order_command_rejects_unsupported_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)

            command, blockers = longbridge_order_command(
                config,
                "longbridge",
                {"symbol": "AAPL", "side": "sell_short", "order_type": "limit", "quantity": 1, "limit_price": "100"},
            )

            self.assertEqual(command, [])
            self.assertIn("unsupported_longbridge_order_side", blockers)

    def test_blocks_short_fractional_options_risk_exposure_nonpaper_and_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            config.output_dir.mkdir(parents=True, exist_ok=True)
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [{"signal_id": "dup", "submission_status": "submitted"}],
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(signal_id="short", side="sell_short", direction="short"),
                    self.signal(signal_id="frac", quantity="1.5", notional="150"),
                    self.signal(signal_id="option", symbol="AAPL250620C00100000"),
                    self.signal(signal_id="risk", risk_amount="21"),
                    self.signal(signal_id="exposure", notional="1600", quantity="16", limit_price="100"),
                    self.signal(signal_id="dup"),
                ],
            )

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertIn("blocked_short_disabled", rows["short"]["blockers"])
            self.assertIn("blocked_fractional_disabled", rows["frac"]["blockers"])
            self.assertIn("blocked_options_disabled", rows["option"]["blockers"])
            self.assertIn("blocked_risk_over_cap", rows["risk"]["blockers"])
            self.assertIn("blocked_symbol_exposure_over_cap", rows["exposure"]["blockers"])
            self.assertIn("duplicate_signal_already_submitted", rows["dup"]["blockers"])

    def test_existing_longbridge_position_or_open_order_blocks_new_buy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "held_symbols": ["AAPL"],
                "positions": [{"symbol": "AAPL.US", "quantity": "1", "market_price": "100"}],
                "open_orders": [{"symbol": "MSFT.US", "quantity": "1", "price": "100", "status": "Submitted"}],
                "position_notional_by_symbol": {"AAPL": "100"},
                "open_order_notional_by_symbol": {"MSFT": "100"},
                "total_position_notional": "100",
                "total_open_order_notional": "100",
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_config(root, account_state=account_state)
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(signal_id="held-aapl", symbol="AAPL"),
                    self.signal(signal_id="open-msft", symbol="MSFT"),
                ],
            )

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertIn("blocked_existing_position_same_symbol", rows["held-aapl"]["blockers"])
            self.assertIn("blocked_existing_open_order_same_symbol", rows["open-msft"]["blockers"])

    def test_existing_submitted_realtime_buy_blocks_duplicate_before_account_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            config.output_dir.mkdir(parents=True, exist_ok=True)
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    {
                        "signal_id": "already-submitted-aapl",
                        "submission_status": "submitted",
                        "submitted_at": "2026-06-04T13:31:00Z",
                        "side": "buy",
                        "symbol": "AAPL",
                        "quantity": "1",
                        "notional": "100.00",
                    }
                ],
            )
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="new-aapl", symbol="AAPL")])

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertIn("blocked_existing_submitted_order_same_symbol", rows["new-aapl"]["blockers"])
            self.assertTrue(rows["new-aapl"]["longbridge_realtime_submitted_ledger_checked"])

    def test_materialized_submitted_order_is_not_double_counted_after_account_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "held_symbols": ["AAPL"],
                "positions": [{"symbol": "AAPL.US", "quantity": "1", "market_price": "100"}],
                "position_notional_by_symbol": {"AAPL": "100"},
                "open_order_notional_by_symbol": {},
                "total_position_notional": "100",
                "total_open_order_notional": "0",
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_config(root, account_state=account_state)
            config.output_dir.mkdir(parents=True, exist_ok=True)
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    {
                        "signal_id": "already-materialized-aapl",
                        "submission_status": "submitted",
                        "submitted_at": "2026-06-04T13:31:00Z",
                        "side": "buy",
                        "symbol": "AAPL",
                        "quantity": "1",
                        "notional": "5900.00",
                    }
                ],
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [self.signal(signal_id="new-msft", symbol="MSFT", notional="500", quantity="5", limit_price="100")],
            )

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(rows["new-msft"]["realtime_decision_status"], "latency_target_met_ready")
            self.assertNotIn("blocked_total_exposure_over_cap", rows["new-msft"]["blockers"])

    def test_same_cycle_same_symbol_second_buy_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(signal_id="first-bidu", symbol="BIDU", notional="200", quantity="2", limit_price="100"),
                    self.signal(signal_id="second-bidu", symbol="BIDU", notional="100", quantity="1", limit_price="100"),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 1)
            self.assertEqual(rows["first-bidu"]["realtime_decision_status"], "latency_target_met_ready")
            self.assertIn("blocked_existing_selected_order_same_symbol", rows["second-bidu"]["blockers"])

    def test_close_long_can_sell_existing_position_without_becoming_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "held_symbols": ["AAPL"],
                "positions": [{"symbol": "AAPL.US", "quantity": "2", "market_price": "100"}],
                "position_notional_by_symbol": {"AAPL": "200"},
                "total_position_notional": "200",
                "open_order_notional_by_symbol": {},
                "total_open_order_notional": "0",
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_config(root, account_state=account_state)
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="close-aapl",
                        side="sell",
                        direction="long",
                        position_action="close_long",
                        quantity="1",
                        stop_price="",
                        target_price="",
                        risk_amount="0",
                        net_profit_after_fees_at_target="-1",
                    ),
                    self.signal(signal_id="short-aapl", side="sell_short", direction="short"),
                ],
            )

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(rows["close-aapl"]["realtime_decision_status"], "latency_target_met_ready")
            self.assertEqual(rows["close-aapl"]["side"], "sell")
            self.assertIn("blocked_short_disabled", rows["short-aapl"]["blockers"])

    def test_existing_account_exposure_counts_toward_total_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "held_symbols": [],
                "positions": [],
                "open_orders": [],
                "position_notional_by_symbol": {"SPY": "5950"},
                "open_order_notional_by_symbol": {},
                "total_position_notional": "5950",
                "total_open_order_notional": "0",
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_config(root, account_state=account_state)
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="over-total", symbol="MSFT")])

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertIn("blocked_total_exposure_over_cap", rows[0]["blockers"])

    def test_non_paper_account_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, account_state={"account_channel": "lb_trade", "paper_account_verified": False})
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="live-account")])

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertIn("blocked_non_paper_account", rows[0]["blockers"])

    def test_replay_before_session_start_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, session_started_at="2026-06-04T14:00:00Z")
            self.write_jsonl(
                root / "signals.jsonl",
                [self.signal(signal_id="old-signal", created_at="2026-06-04T13:59:59Z")],
            )

            run_realtime_execution(config, generated_at="2026-06-04T14:00:01Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertIn("blocked_replay_signal_before_session_start", rows[0]["blockers"])

    def test_auto_session_start_uses_current_regular_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, session_started_at="auto")
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(signal_id="fresh", created_at="2026-06-04T13:30:01Z"),
                    self.signal(signal_id="old", created_at="2026-06-04T13:29:59Z"),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["session_started_at"], "2026-06-04T13:30:00Z")
            self.assertEqual(rows["fresh"]["realtime_decision_status"], "latency_delayed_revalidated_ready")
            self.assertIn("blocked_replay_signal_before_session_start", rows["old"]["blockers"])

    def make_config(
        self,
        root: Path,
        *,
        execute_orders: bool = False,
        paper_trading_approval: bool = False,
        session_started_at: str = "2026-06-04T13:00:00Z",
        account_state: dict | None = None,
    ):
        state = account_state or {
            "account_channel": "lb_papertrading",
            "paper_account_verified": True,
            "buying_power": "10000",
            "live_execution": False,
            "real_money_actions": False,
        }
        self.write_json(root / "account_state.json", state)
        payload = {
            "stage": "M15.longbridge_realtime_execution",
            "title": "长桥模拟账户实时执行链路",
            "inputs": {
                "realtime_signal_events": str(root / "signals.jsonl"),
                "paper_account_state": str(root / "account_state.json"),
            },
            "outputs": {"output_dir": str(root / "out")},
            "longbridge_realtime": {
                "required_account_channel": "lb_papertrading",
                "cli_name": "longbridge",
                "cli_timeout_seconds": 6,
                "time_in_force": "day",
                "outside_rth": "RTH_ONLY",
                "execute_orders": execute_orders,
                "paper_trading_approval": paper_trading_approval,
                "session_started_at": session_started_at,
                "allow_replay": False,
                "watch_interval_seconds": 1,
                "latency_target_ms": 1000,
                "latency_acceptable_ms": 5000,
                "allowed_runtime_ids": ["M10-PA-004-long-1d", "M10-PA-013-1d"],
            },
            "paper_account_model": {
                "equity": "10000",
                "max_total_exposure": "6000",
                "max_symbol_exposure": "1500",
                "max_risk_per_order": "20",
                "min_cash_reserve": "4000",
                "allow_fractional_shares": False,
                "allow_short_selling": False,
                "allow_options": False,
                "minimum_net_profit_after_fees": "0",
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_order_source": False,
            },
        }
        config_path = root / "config.json"
        self.write_json(config_path, payload)
        return load_config(config_path)

    def signal(self, **overrides: object) -> dict:
        row = {
            "signal_id": "sig",
            "created_at": "2026-06-04T13:59:59.500Z",
            "runtime_id": "M10-PA-004-long-1d",
            "strategy_id": "M10-PA-004",
            "symbol": "AAPL",
            "timeframe": "1d",
            "direction": "long",
            "side": "buy",
            "order_type": "limit",
            "limit_price": "100.00",
            "stop_price": "95.00",
            "target_price": "110.00",
            "current_price": "100.00",
            "quantity": "1",
            "risk_amount": "5.00",
            "notional": "100.00",
            "net_profit_after_fees_at_target": "8.00",
            "source_market_event_id": "bar-1",
        }
        row.update(overrides)
        return row

    def write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def read_jsonl(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
