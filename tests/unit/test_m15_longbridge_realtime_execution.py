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

    def test_fractional_quantity_at_least_one_is_floored_by_execution_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="fractional-ge-one",
                        quantity="24.0964",
                        limit_price="20.00",
                        stop_price="19.50",
                        target_price="21.00",
                        current_price="20.00",
                        risk_amount="999.00",
                        notional="9999.00",
                        net_profit_after_fees_at_target="30.00",
                    )
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 1)
            self.assertEqual(payload["quantity_normalized_count"], 1)
            self.assertEqual(rows["fractional-ge-one"]["raw_suggested_quantity"], "24.0964")
            self.assertEqual(rows["fractional-ge-one"]["submitted_quantity"], "24")
            self.assertEqual(rows["fractional-ge-one"]["quantity_rounding_adjustment"], "0.0964")
            self.assertEqual(rows["fractional-ge-one"]["quantity_normalization_status"], "rounded_down_to_whole_share")
            self.assertNotIn("blocked_fractional_disabled", rows["fractional-ge-one"]["blockers"])
            self.assertEqual(rows["fractional-ge-one"]["quantity"], "24")
            self.assertEqual(rows["fractional-ge-one"]["notional"], "480.00")
            self.assertEqual(rows["fractional-ge-one"]["risk_amount"], "12.00")
            self.assertEqual(rows["fractional-ge-one"]["order_payload"]["quantity"], 24)

    def test_repair_auxiliary_and_shadow_runtimes_are_local_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(signal_id="repair", runtime_id="M10-PA-007-1d", strategy_id="M10-PA-007"),
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

    def test_pa004_mbf_and_qc_are_allowed_when_whitelisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                allowed_runtime_ids=["M10-PA-004-MBF-1d", "M10-PA-004-MBF-QC-1d"],
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="mbf",
                        runtime_id="M10-PA-004-MBF-1d",
                        strategy_id="M10-PA-004",
                        symbol="AAPL",
                    ),
                    self.signal(
                        signal_id="mbf-qc",
                        runtime_id="M10-PA-004-MBF-QC-1d",
                        strategy_id="M10-PA-004",
                        symbol="MSFT",
                    ),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 2)
            self.assertEqual(rows["mbf"]["capital_bucket"], "pa004_mbf")
            self.assertEqual(rows["mbf-qc"]["capital_bucket"], "pa004_mbf_qc")
            self.assertNotIn("blocked_shadow_runtime_local_only", rows["mbf"]["blockers"])
            self.assertNotIn("blocked_shadow_runtime_local_only", rows["mbf-qc"]["blockers"])

    def test_ftd_loss_streak_guard_is_allowed_when_whitelisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, allowed_runtime_ids=["M12-FTD-001-loss-streak-guard-1d"])
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="ftd-loss-streak",
                        runtime_id="M12-FTD-001-loss-streak-guard-1d",
                        strategy_id="M12-FTD-001",
                        symbol="SPY",
                        quantity="1",
                        net_profit_after_fees_at_target="15.00",
                    )
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 1)
            self.assertEqual(rows["ftd-loss-streak"]["capital_bucket"], "ftd_loss_streak")
            self.assertNotIn("blocked_shadow_runtime_local_only", rows["ftd-loss-streak"]["blockers"])

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
                    self.signal(
                        signal_id="rebuilt",
                        symbol="GOOG",
                        created_at="2026-06-04T13:59:53Z",
                        realtime_rebuilt_from_delayed_signal=True,
                    ),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {
                row["signal_id"]: row
                for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)
                if row.get("processed_at") == "2026-06-04T14:00:00Z"
            }

            self.assertEqual(payload["latency_counts"]["target_met"], 1)
            self.assertEqual(payload["latency_counts"]["acceptable"], 1)
            self.assertEqual(payload["latency_counts"]["delayed_revalidated"], 2)
            self.assertEqual(payload["delayed_rebuild_required_count"], 1)
            self.assertEqual(rows["target"]["realtime_decision_status"], "latency_target_met_ready")
            self.assertEqual(rows["acceptable"]["realtime_decision_status"], "latency_acceptable_ready")
            self.assertEqual(rows["delayed"]["realtime_decision_status"], "blocked_delayed_signal_requires_realtime_rebuild")
            self.assertIn("blocked_delayed_signal_requires_realtime_rebuild", rows["delayed"]["blockers"])
            self.assertEqual(rows["delayed"]["submission_status"], "blocked_not_submitted")
            self.assertEqual(rows["rebuilt"]["realtime_decision_status"], "latency_delayed_revalidated_ready")
            self.assertNotIn("missed", rows["rebuilt"]["realtime_decision_status"])
            self.assertEqual(rows["delayed"]["signal_age_limit_seconds"], 60)

    def test_profit_and_reward_r_gates_block_weak_longbridge_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(signal_id="low-profit", symbol="AAPL", net_profit_after_fees_at_target="4.99"),
                    self.signal(signal_id="below-normal-profit", symbol="MSFT", net_profit_after_fees_at_target="7.99"),
                    self.signal(
                        signal_id="low-reward-r",
                        symbol="GOOG",
                        net_profit_after_fees_at_target="20.00",
                        target_price="106.00",
                    ),
                    self.signal(signal_id="strong", symbol="META", net_profit_after_fees_at_target="9.00"),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 1)
            self.assertEqual(payload["low_profit_blocked_count"], 2)
            self.assertEqual(payload["reward_r_blocked_count"], 1)
            self.assertIn("blocked_fee_profit_below_minimum", rows["low-profit"]["blockers"])
            self.assertIn("blocked_fee_profit_below_minimum", rows["below-normal-profit"]["blockers"])
            self.assertIn("blocked_reward_r_below_minimum", rows["low-reward-r"]["blockers"])
            self.assertEqual(rows["strong"]["profit_quality_gate"], "normal_profit")

    def test_pa001_has_stricter_profit_and_reward_r_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, allowed_runtime_ids=["M10-PA-001-1d"])
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="pa001-low-profit",
                        runtime_id="M10-PA-001-1d",
                        strategy_id="M10-PA-001",
                        symbol="AAPL",
                        net_profit_after_fees_at_target="11.99",
                    ),
                    self.signal(
                        signal_id="pa001-low-r",
                        runtime_id="M10-PA-001-1d",
                        strategy_id="M10-PA-001",
                        symbol="MSFT",
                        net_profit_after_fees_at_target="20.00",
                        target_price="108.00",
                    ),
                    self.signal(
                        signal_id="pa001-strong",
                        runtime_id="M10-PA-001-1d",
                        strategy_id="M10-PA-001",
                        symbol="GOOG",
                        net_profit_after_fees_at_target="20.00",
                    ),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 1)
            self.assertIn("blocked_fee_profit_below_minimum", rows["pa001-low-profit"]["blockers"])
            self.assertIn("blocked_reward_r_below_minimum", rows["pa001-low-r"]["blockers"])
            self.assertEqual(rows["pa001-strong"]["minimum_net_profit_after_fees"], "12.00")
            self.assertEqual(rows["pa001-strong"]["minimum_reward_r"], "2")

    def test_pa001_5m_is_local_repair_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, allowed_runtime_ids=["M10-PA-001-5m"])
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="pa001-5m",
                        runtime_id="M10-PA-001-5m",
                        strategy_id="M10-PA-001",
                        net_profit_after_fees_at_target="30.00",
                    )
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["ready_order_count"], 0)
            self.assertEqual(rows[0]["realtime_decision_status"], "blocked_repair_runtime_local_only")

    def test_pa001_daily_new_symbol_limit_blocks_second_new_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, allowed_runtime_ids=["M10-PA-001-1d"])
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="pa001-first",
                        runtime_id="M10-PA-001-1d",
                        strategy_id="M10-PA-001",
                        symbol="AAPL",
                        net_profit_after_fees_at_target="20.00",
                    ),
                    self.signal(
                        signal_id="pa001-second",
                        runtime_id="M10-PA-001-1d",
                        strategy_id="M10-PA-001",
                        symbol="MSFT",
                        net_profit_after_fees_at_target="20.00",
                    ),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 1)
            self.assertEqual(payload["strategy_daily_limit_blocked_count"], 1)
            self.assertIn("blocked_strategy_daily_new_symbol_limit", rows["pa001-second"]["blockers"])

    def test_same_day_loss_exit_cools_symbol_for_new_buys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    {
                        "signal_id": "old-stop",
                        "symbol": "TSLA",
                        "capital_bucket": "pa004_long",
                        "side": "sell",
                        "position_action": "stop_loss",
                        "submission_status": "submitted",
                        "submitted_at": "2026-06-04T13:45:00Z",
                    }
                ],
            )
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="buy-tsla-again", symbol="TSLA")])

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 0)
            self.assertEqual(payload["same_day_loss_cooldown_blocked_count"], 1)
            self.assertIn("blocked_same_day_loss_exit_cooldown", rows["buy-tsla-again"]["blockers"])

    def test_over_age_delayed_signal_is_blocked_instead_of_backfilled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "signals.jsonl",
                [self.signal(signal_id="stale", created_at="2026-06-04T13:30:00Z")],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["ready_order_count"], 0)
            self.assertEqual(payload["delayed_signal_age_blocked_count"], 1)
            self.assertIn("blocked_delayed_signal_age_over_limit", rows[0]["blockers"])
            self.assertEqual(rows[0]["submission_status"], "blocked_not_submitted")

    def test_previously_processed_signals_are_not_reprocessed_each_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="repeat", symbol="AAPL")])

            first = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            second = run_realtime_execution(config, generated_at="2026-06-04T14:00:01Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(first["signal_event_count"], 1)
            self.assertEqual(second["input_signal_event_count"], 1)
            self.assertEqual(second["signal_event_count"], 0)
            self.assertEqual(second["skipped_previously_processed_signal_count"], 1)
            self.assertEqual(len(rows), 1)

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

    def test_longbridge_cli_client_does_not_count_empty_response_as_submitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, execute_orders=True, paper_trading_approval=True)

            def runner(command: list[str]):
                return type("Result", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

            client = LongbridgeCliRealtimePaperClient(config, command_runner=runner, cli_path="longbridge")
            response = client.submit_order(
                {
                    "signal_id": "sig-cli",
                    "runtime_id": "M10-PA-004-long-1d",
                    "symbol": "AAPL",
                    "side": "buy",
                    "order_type": "limit",
                    "quantity": 2,
                    "limit_price": "101.20",
                }
            )

            self.assertFalse(response["submitted"])
            self.assertEqual(response["status"], "submit_unconfirmed_missing_order_id")
            self.assertEqual(response["order_id"], "")

    def test_longbridge_cli_client_confirms_empty_submit_by_account_order_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, execute_orders=True, paper_trading_approval=True)
            commands: list[list[str]] = []

            def runner(command: list[str]):
                commands.append(command)
                if command[1:3] == ["order", "buy"]:
                    return type("Result", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()
                return type(
                    "Result",
                    (),
                    {
                        "returncode": 0,
                        "stdout": json.dumps(
                            [
                                {
                                    "order_id": "rt-lookup-1",
                                    "symbol": "KMB.US",
                                    "side": "Buy",
                                    "status": "New",
                                    "quantity": "1",
                                    "price": "98.10",
                                    "created_at": "2026-06-05T16:58:58Z",
                                }
                            ]
                        ),
                        "stderr": "",
                    },
                )()

            client = LongbridgeCliRealtimePaperClient(config, command_runner=runner, cli_path="longbridge")
            response = client.submit_order(
                {
                    "signal_id": "sig-cli",
                    "runtime_id": "M10-PA-001-1d",
                    "symbol": "KMB",
                    "side": "buy",
                    "order_type": "limit",
                    "quantity": 1,
                    "limit_price": "98.10",
                }
            )

            self.assertTrue(response["submitted"])
            self.assertEqual(response["order_id"], "rt-lookup-1")
            self.assertEqual(response["confirmation_source"], "account_state_lookup")
            self.assertEqual(commands[1], ["longbridge", "order", "--format", "json"])

    def test_unconfirmed_submission_is_not_counted_as_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, execute_orders=True, paper_trading_approval=True)

            class EmptyResponseClient:
                def submit_order(self, order_payload: dict) -> dict:
                    return {"submitted": False, "status": "submit_unconfirmed_missing_order_id", "order_id": ""}

            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="sig-unconfirmed")])
            payload = run_realtime_execution(
                config,
                generated_at="2026-06-04T14:00:00Z",
                broker_client=EmptyResponseClient(),
            )
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["attempted_order_count"], 1)
            self.assertEqual(payload["submitted_count"], 0)
            self.assertEqual(payload["unconfirmed_submission_count"], 1)
            self.assertEqual(rows[0]["submission_status"], "submit_unconfirmed_missing_order_id")

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
                    self.signal(signal_id="below-one", quantity="0.9999", notional="99.99"),
                    self.signal(signal_id="option", symbol="AAPL250620C00100000"),
                    self.signal(signal_id="risk", stop_price="79.00", target_price="140.00", net_profit_after_fees_at_target="40"),
                    self.signal(signal_id="exposure", notional="1600", quantity="16", limit_price="100"),
                    self.signal(signal_id="dup"),
                ],
            )

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {
                row["signal_id"]: row
                for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)
                if row.get("processed_at") == "2026-06-04T14:00:00Z"
            }

            self.assertIn("blocked_short_disabled", rows["short"]["blockers"])
            self.assertIn("blocked_quantity_below_one_share", rows["below-one"]["blockers"])
            self.assertNotIn("blocked_fractional_disabled", rows["below-one"]["blockers"])
            self.assertIn("blocked_options_disabled", rows["option"]["blockers"])
            self.assertIn("blocked_risk_over_cap", rows["risk"]["blockers"])
            self.assertIn("blocked_symbol_exposure_over_cap", rows["exposure"]["blockers"])
            self.assertNotIn("dup", rows)

    def test_us_buy_blocks_margin_financing_even_when_total_cash_is_high(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                account_state={
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "cash": "100000",
                    "buying_power": "100000",
                    "currency_cash": {
                        "USD": {
                            "available_cash": "-8728.61",
                            "total_cash": "-8537.25",
                            "settling_cash": "-11771.44",
                            "frozen_cash": "191.36",
                        },
                        "HKD": {"available_cash": "722057.68"},
                    },
                    "live_execution": False,
                    "real_money_actions": False,
                },
            )
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="usd-margin")])

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertIn("blocked_margin_financing_disabled", rows[0]["blockers"])
            self.assertEqual(rows[0]["order_currency"], "USD")
            self.assertEqual(rows[0]["order_currency_available_cash"], "-8728.61")
            self.assertEqual(rows[0]["submission_status"], "blocked_not_submitted")

    def test_existing_longbridge_position_or_open_order_does_not_block_new_bucket_buy(self) -> None:
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

            self.assertNotIn("blocked_existing_position_same_symbol", rows["held-aapl"]["blockers"])
            self.assertNotIn("blocked_existing_open_order_same_symbol", rows["open-msft"]["blockers"])
            self.assertEqual(rows["held-aapl"]["capital_bucket"], "pa004_long")
            self.assertEqual(rows["open-msft"]["capital_bucket"], "pa004_long")

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
                        "capital_bucket": "pa004_long",
                        "quantity": "1",
                        "notional": "100.00",
                    }
                ],
            )
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="new-aapl", symbol="AAPL")])

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertIn("blocked_existing_submitted_order_same_bucket_symbol", rows["new-aapl"]["blockers"])
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
                [
                    self.signal(
                        signal_id="new-msft",
                        symbol="MSFT",
                        notional="500",
                        quantity="5",
                        limit_price="100",
                        stop_price="99",
                        target_price="110",
                    )
                ],
            )

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(rows["new-msft"]["realtime_decision_status"], "latency_target_met_ready")
            self.assertNotIn("blocked_total_exposure_over_cap", rows["new-msft"]["blockers"])

    def test_canceled_broker_order_does_not_count_as_bucket_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "orders": [
                    {
                        "order_id": "PAPER-CANCELED",
                        "side": "Buy",
                        "symbol": "SPY.US",
                        "quantity": "1",
                        "price": "5950.00",
                        "executed_quantity": "0",
                        "executed_price": "-",
                        "status": "Canceled",
                    }
                ],
                "positions": [],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_config(root, account_state=account_state)
            config.output_dir.mkdir(parents=True, exist_ok=True)
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    {
                        "signal_id": "canceled-spy",
                        "submission_status": "submitted",
                        "submitted_at": "2026-06-04T13:31:00Z",
                        "side": "buy",
                        "symbol": "SPY",
                        "capital_bucket": "pa004_long",
                        "quantity": "1",
                        "notional": "5950.00",
                        "order_id": "PAPER-CANCELED",
                    }
                ],
            )
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="new-msft", symbol="MSFT")])

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}
            main_bucket = next(row for row in payload["virtual_capital_buckets"] if row["capital_bucket"] == "pa004_long")

            self.assertEqual(rows["new-msft"]["realtime_decision_status"], "latency_target_met_ready")
            self.assertNotIn("blocked_total_exposure_over_cap", rows["new-msft"]["blockers"])
            self.assertEqual(main_bucket["used_exposure"], "100.00")

    def test_filled_broker_order_with_position_counts_as_bucket_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "orders": [
                    {
                        "order_id": "PAPER-FILLED",
                        "side": "Buy",
                        "symbol": "SPY.US",
                        "quantity": "1",
                        "price": "5950.00",
                        "executed_quantity": "1",
                        "executed_price": "5950.00",
                        "status": "Filled",
                    }
                ],
                "positions": [{"symbol": "SPY.US", "quantity": "1", "cost_price": "5950.00"}],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_config(root, account_state=account_state)
            config.output_dir.mkdir(parents=True, exist_ok=True)
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    {
                        "signal_id": "filled-spy",
                        "submission_status": "submitted",
                        "submitted_at": "2026-06-04T13:31:00Z",
                        "side": "buy",
                        "symbol": "SPY",
                        "capital_bucket": "pa004_long",
                        "quantity": "1",
                        "notional": "5950.00",
                        "order_id": "PAPER-FILLED",
                    }
                ],
            )
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="new-msft", symbol="MSFT")])

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}
            main_bucket = next(row for row in payload["virtual_capital_buckets"] if row["capital_bucket"] == "pa004_long")

            self.assertIn("blocked_total_exposure_over_cap", rows["new-msft"]["blockers"])
            self.assertEqual(main_bucket["used_exposure"], "5950.00")

    def test_prior_session_filled_position_counts_toward_bucket_total_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "orders": [
                    {
                        "order_id": "PAPER-YESTERDAY-FILLED",
                        "side": "Buy",
                        "symbol": "SPY.US",
                        "quantity": "1",
                        "price": "5950.00",
                        "executed_quantity": "1",
                        "executed_price": "5950.00",
                        "status": "Filled",
                    }
                ],
                "positions": [{"symbol": "SPY.US", "quantity": "1", "cost_price": "5950.00"}],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_config(root, account_state=account_state, session_started_at="2026-06-04T13:30:00Z")
            config.output_dir.mkdir(parents=True, exist_ok=True)
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    {
                        "signal_id": "filled-spy-yesterday",
                        "submission_status": "submitted",
                        "submitted_at": "2026-06-03T19:55:00Z",
                        "side": "buy",
                        "symbol": "SPY",
                        "capital_bucket": "pa004_long",
                        "quantity": "1",
                        "notional": "5950.00",
                        "order_id": "PAPER-YESTERDAY-FILLED",
                    }
                ],
            )
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="new-msft", symbol="MSFT")])

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertIn("blocked_total_exposure_over_cap", rows["new-msft"]["blockers"])

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
            self.assertIn("blocked_existing_selected_order_same_bucket_symbol", rows["second-bidu"]["blockers"])

    def test_cross_bucket_same_symbol_can_be_selected_independently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, allowed_runtime_ids=["M10-PA-004-long-1d", "M10-PA-013-1d"])
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(signal_id="main-aapl", symbol="AAPL", runtime_id="M10-PA-004-long-1d", strategy_id="M10-PA-004"),
                    self.signal(signal_id="exp-aapl", symbol="AAPL", runtime_id="M10-PA-013-1d", strategy_id="M10-PA-013"),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 2)
            self.assertEqual(rows["main-aapl"]["capital_bucket"], "pa004_long")
            self.assertEqual(rows["exp-aapl"]["capital_bucket"], "experimental")

    def test_pa002_1d_runs_only_in_unified_experimental_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                allowed_runtime_ids=["M10-PA-002-1d"],
                virtual_capital_buckets={
                    "experimental": {
                        "label": "统一实验仓（M10-PA-002-1d/M10-PA-013-1d/M10-PA-008-1d/M10-PA-005-1d/M10-PA-005-5m/M10-PA-012-5m/M10-PA-001-1d）",
                        "equity": "10000",
                        "max_total_exposure": "6000",
                        "max_symbol_exposure": "1000",
                        "max_risk_per_order": "20",
                        "min_cash_reserve": "4000",
                        "runtime_ids": ["M10-PA-002-1d"],
                    },
                },
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="pa002-exp-msft",
                        symbol="MSFT",
                        runtime_id="M10-PA-002-1d",
                        strategy_id="M10-PA-002",
                        capital_bucket="experimental",
                        capital_bucket_label="统一实验仓（M10-PA-002-1d/M10-PA-013-1d/M10-PA-008-1d/M10-PA-005-1d/M10-PA-005-5m/M10-PA-012-5m/M10-PA-001-1d）",
                    ),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 1)
            self.assertEqual(rows["pa002-exp-msft"]["capital_bucket"], "experimental")

    def test_pa002_5m_can_run_in_dedicated_pa002_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                allowed_runtime_ids=["M10-PA-002-5m"],
                virtual_capital_buckets={
                    "pa002_5m": {
                        "label": "PA002-5m单仓（M10-PA-002-5m）",
                        "equity": "10000",
                        "max_total_exposure": "6000",
                        "max_symbol_exposure": "1500",
                        "max_risk_per_order": "20",
                        "min_cash_reserve": "4000",
                        "runtime_ids": ["M10-PA-002-5m"],
                    },
                },
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="pa002-5m-dedicated",
                        symbol="MSFT",
                        runtime_id="M10-PA-002-5m",
                        strategy_id="M10-PA-002",
                        capital_bucket="pa002_5m",
                        capital_bucket_label="PA002-5m单仓（M10-PA-002-5m）",
                    ),
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 1)
            self.assertEqual(rows["pa002-5m-dedicated"]["capital_bucket"], "pa002_5m")
            self.assertEqual(rows["pa002-5m-dedicated"]["realtime_decision_status"], "latency_target_met_ready")

    def test_pending_new_epoch_generates_flatten_sell_and_suppresses_new_buys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                account_state={
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "buying_power": "10000",
                    "positions": [{"symbol": "AAPL.US", "quantity": "2", "available": "2", "market_price": "100"}],
                    "open_orders": [],
                    "live_execution": False,
                    "real_money_actions": False,
                },
                test_epoch={
                    "enabled": True,
                    "test_epoch_id": "unit-dual-bucket-reset",
                    "state_path": str(root / "epoch.json"),
                    "flatten_existing_positions_before_activation": True,
                    "archive_previous_records": True,
                },
            )
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="new-buy-waiting", symbol="MSFT")])

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)
            epoch = json.loads((root / "epoch.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["test_epoch"]["status"], "pending_flatten")
            self.assertEqual(payload["epoch_pending_flatten_signal_input_suppressed_count"], 1)
            self.assertEqual(payload["ready_order_count"], 1)
            self.assertEqual(rows[0]["side"], "sell")
            self.assertEqual(rows[0]["runtime_id"], "M15-LONGBRIDGE-EPOCH-FLATTEN")
            self.assertEqual(rows[0]["limit_price"], "99.50")
            self.assertEqual(epoch["status"], "pending_flatten")

    def test_pending_new_epoch_uses_discounted_cost_when_position_has_no_market_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                account_state={
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "buying_power": "10000",
                    "positions": [{"symbol": "SLB.US", "quantity": "5", "available": "5", "cost_price": "55.73"}],
                    "open_orders": [],
                    "live_execution": False,
                    "real_money_actions": False,
                },
                test_epoch={
                    "enabled": True,
                    "test_epoch_id": "unit-dual-bucket-reset",
                    "state_path": str(root / "epoch.json"),
                    "flatten_existing_positions_before_activation": True,
                    "archive_previous_records": True,
                },
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["ready_order_count"], 1)
            self.assertEqual(rows[0]["side"], "sell")
            self.assertEqual(rows[0]["limit_price"], "52.94")
            self.assertEqual(rows[0]["order_payload"]["limit_price"], "52.94")

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
            self.assertEqual(rows["close-aapl"]["exit_state"], "ready_to_submit")
            self.assertIn("blocked_short_disabled", rows["short-aapl"]["blockers"])

    def test_exit_only_position_sell_skips_runtime_whitelist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "positions": [{"symbol": "AAPL.US", "quantity": "1", "available": "1", "market_price": "100"}],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_config(root, account_state=account_state)
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="exit-only-aapl",
                        runtime_id="M15-LONGBRIDGE-EXIT-ONLY",
                        strategy_id="M15-LONGBRIDGE-EXIT-ONLY",
                        symbol="AAPL",
                        side="sell",
                        position_action="stop_loss",
                        quantity="1",
                        limit_price="99",
                        stop_price="",
                        target_price="",
                        risk_amount="0",
                        net_profit_after_fees_at_target="0.01",
                        longbridge_position_exit_source=True,
                    )
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["ready_order_count"], 1)
            self.assertEqual(rows["exit-only-aapl"]["realtime_decision_status"], "latency_target_met_ready")
            self.assertTrue(rows["exit-only-aapl"]["exit_only_position_signal"])
            self.assertNotIn("blocked_not_whitelisted_runtime", rows["exit-only-aapl"]["blockers"])

    def test_close_long_blocks_existing_sell_open_order_same_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "positions": [{"symbol": "TEAM.US", "quantity": "1", "available": "1", "market_price": "100"}],
                "open_orders": [
                    {
                        "symbol": "TEAM.US",
                        "side": "Sell",
                        "quantity": "1",
                        "executed_quantity": "0",
                        "price": "100.60",
                        "status": "New",
                    }
                ],
                "position_notional_by_symbol": {"TEAM": "100"},
                "total_position_notional": "100",
                "open_order_notional_by_symbol": {"TEAM": "100.60"},
                "total_open_order_notional": "100.60",
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_config(root, account_state=account_state)
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="close-team-again",
                        symbol="TEAM",
                        side="sell",
                        position_action="stop_loss",
                        quantity="1",
                        stop_price="",
                        target_price="",
                        risk_amount="0",
                        net_profit_after_fees_at_target="-1",
                    )
                ],
            )

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

        self.assertIn("blocked_existing_sell_open_order_same_symbol", rows["close-team-again"]["blockers"])
        self.assertEqual(rows["close-team-again"]["submission_status"], "blocked_not_submitted")

    def test_old_submitted_sell_without_open_order_does_not_permanently_block_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "positions": [{"symbol": "SLB.US", "quantity": "5", "available": "5", "cost_price": "55.73"}],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_config(root, account_state=account_state)
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    {
                        "signal_id": "old-sell-slb",
                        "symbol": "SLB",
                        "side": "sell",
                        "quantity": "5",
                        "submission_status": "submitted",
                        "submitted_at": "2026-06-04T13:40:00Z",
                    }
                ],
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.signal(
                        signal_id="close-slb-after-cancel",
                        symbol="SLB",
                        side="sell",
                        position_action="close_long",
                        quantity="5",
                        limit_price="52.94",
                        stop_price="",
                        target_price="",
                        risk_amount="0",
                        net_profit_after_fees_at_target="-1",
                    )
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

        self.assertEqual(payload["ready_order_count"], 1)
        self.assertEqual(rows["close-slb-after-cancel"]["realtime_decision_status"], "latency_target_met_ready")
        self.assertNotIn("blocked_existing_submitted_sell_same_symbol", rows["close-slb-after-cancel"]["blockers"])

    def test_close_long_blocks_unavailable_position_quantity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "positions": [{"symbol": "TSLA.US", "quantity": "1", "available": "0", "market_price": "420"}],
                "open_orders": [],
                "position_notional_by_symbol": {"TSLA": "420"},
                "total_position_notional": "420",
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
                        signal_id="close-tsla-unavailable",
                        symbol="TSLA",
                        side="sell",
                        position_action="take_profit",
                        quantity="1",
                        stop_price="",
                        target_price="",
                        risk_amount="0",
                        net_profit_after_fees_at_target="-1",
                    )
                ],
            )

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

        self.assertIn("blocked_close_quantity_not_available", rows["close-tsla-unavailable"]["blockers"])
        self.assertEqual(rows["close-tsla-unavailable"]["submission_status"], "blocked_not_submitted")

    def test_existing_bucket_exposure_counts_toward_bucket_total_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            config.output_dir.mkdir(parents=True, exist_ok=True)
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    {
                        "signal_id": "main-bucket-near-cap",
                        "submission_status": "submitted",
                        "submitted_at": "2026-06-04T13:31:00Z",
                        "side": "buy",
                        "symbol": "SPY",
                        "capital_bucket": "pa004_long",
                        "quantity": "1",
                        "notional": "5950.00",
                    }
                ],
            )
            self.write_jsonl(root / "signals.jsonl", [self.signal(signal_id="over-total", symbol="MSFT")])

            run_realtime_execution(config, generated_at="2026-06-04T14:00:00Z")
            rows = {row["signal_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertIn("blocked_total_exposure_over_cap", rows["over-total"]["blockers"])

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
            self.assertIn("blocked_delayed_signal_age_over_limit", rows["fresh"]["blockers"])
            self.assertIn("blocked_replay_signal_before_session_start", rows["old"]["blockers"])

    def make_config(
        self,
        root: Path,
        *,
        execute_orders: bool = False,
        paper_trading_approval: bool = False,
        session_started_at: str = "2026-06-04T13:00:00Z",
        account_state: dict | None = None,
        allowed_runtime_ids: list[str] | None = None,
        test_epoch: dict | None = None,
        virtual_capital_buckets: dict[str, dict] | None = None,
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
                "max_delayed_signal_age_seconds": 60,
                "daily_new_symbol_limit_by_strategy": {"M10-PA-001": 1},
                "allowed_runtime_ids": allowed_runtime_ids or ["M10-PA-004-long-1d", "M10-PA-013-1d"],
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
                "minimum_net_profit_after_fees": "5",
                "normal_minimum_net_profit_after_fees": "8",
                "minimum_reward_r": "1.5",
                "runtime_minimum_net_profit_after_fees": {"M10-PA-001": "12"},
                "runtime_minimum_reward_r": {"M10-PA-001": "2.0"},
                "conditional_net_profit_requires_confluence": True,
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_order_source": False,
            },
        }
        if virtual_capital_buckets:
            payload["virtual_capital_buckets"] = virtual_capital_buckets
        if test_epoch:
            payload["test_epoch"] = test_epoch
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
