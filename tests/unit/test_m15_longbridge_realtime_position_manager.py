from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from scripts.m15_longbridge_realtime_position_manager_lib import (
    LEDGER_JSONL,
    SUMMARY_JSON,
    broker_failed_long_exit_signal_ids,
    evaluate_position,
    exit_event_priority,
    fill_attributed_open_exposure_by_bucket_symbol,
    load_config,
    run_realtime_position_manager,
    select_exit_events,
)


class M15LongbridgeRealtimePositionManagerTest(unittest.TestCase):
    def test_daily_contract_exits_at_fifth_market_session_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(
                self.make_config(Path(tmp)),
                maximum_holding_sessions_by_runtime={"M10-PA-001-1d": 5},
                market_holidays=frozenset(),
            )
            row, event = evaluate_position(
                config,
                {"symbol": "AAPL", "quantity": "2", "available": "2", "cost_price": "100"},
                {
                    "runtime_id": "M10-PA-001-1d",
                    "strategy_id": "M10-PA-001",
                    "position_direction": "long",
                    "open_order_id": "open-order",
                    "source_open_trade_id": "open-trade",
                    "signal_id": "open-signal",
                    "stop_price": "95",
                    "target_price": "110",
                    "open_market_date": "2026-08-03",
                },
                latest_price=Decimal("101"),
                generated_at="2026-08-07T19:55:00Z",
                existing_signal_ids=set(),
                recent_exit_attempts=set(),
                retriable_exit_signal_ids=set(),
            )

            self.assertEqual(row["holding_session_count"], 5)
            self.assertEqual(row["exit_reason"], "maximum_holding_sessions_exit")
            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(event["order_type"], "market")
            self.assertEqual(event["position_action"], "close_long")

    def test_pa002_repaired_five_minute_position_exits_next_market_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            row, event = evaluate_position(
                config,
                {"symbol": "AAPL", "quantity": "2", "available": "2", "cost_price": "100"},
                {
                    "runtime_id": "M10-PA-002-5m-repaired-v1",
                    "strategy_id": "M10-PA-002",
                    "position_direction": "long",
                    "open_order_id": "open-order",
                    "source_open_trade_id": "open-trade",
                    "signal_id": "open-signal",
                    "stop_price": "98",
                    "target_price": "103",
                    "open_market_date": "2026-08-03",
                },
                latest_price=Decimal("101"),
                generated_at="2026-08-04T14:00:00Z",
                existing_signal_ids=set(),
                recent_exit_attempts=set(),
                retriable_exit_signal_ids=set(),
            )

            self.assertEqual(row["exit_reason"], "next_market_day_timeout")
            self.assertIsNotNone(event)
            assert event is not None
            self.assertEqual(event["position_action"], "close_long")
            self.assertEqual(event["source_open_order_id"], "open-order")
            self.assertEqual(event["source_open_trade_id"], "open-trade")

    def test_filled_historical_broker_exit_is_never_retried(self) -> None:
        rows = [
            {
                "signal_id": "exit-timeout",
                "client_request_id": "request-timeout",
                "side": "sell",
                "position_action": "stop_loss",
                "submission_status": "broker_submit_failed:TimeoutError",
            }
        ]
        account = {
            "orders_ok": True,
            "historical_orders": [
                {
                    "order_id": "broker-filled",
                    "status": "Filled",
                    "executed_quantity": "2",
                    "remark": "PAT-RT exit-timeout request-timeout",
                }
            ],
        }

        self.assertEqual(
            broker_failed_long_exit_signal_ids(rows, account),
            set(),
        )

    def test_fill_attribution_exposure_uses_unclosed_quantity_and_open_price(self) -> None:
        result = fill_attributed_open_exposure_by_bucket_symbol({
            "batches": [
                {
                    "capital_bucket": "pa004_long",
                    "symbol": "AAPL.US",
                    "remaining_quantity": "2",
                    "open_price": "100.50",
                },
                {
                    "capital_bucket": "pa004_long",
                    "symbol": "AAPL",
                    "remaining_quantity": "1",
                    "open_price": "99",
                },
                {
                    "capital_bucket": "pa004_long",
                    "symbol": "MSFT",
                    "remaining_quantity": "0",
                    "open_price": "500",
                },
            ]
        })

        self.assertEqual(result, {"pa004_long": {"AAPL": "300.00"}})

    def test_exit_event_priority_puts_stop_loss_before_take_profit(self) -> None:
        rows = [
            {"signal_id": "target", "exit_reason": "take_profit", "created_at": "2026-07-22T14:00:00Z"},
            {"signal_id": "stop", "exit_reason": "stop_loss", "created_at": "2026-07-22T14:01:00Z"},
        ]

        ordered = sorted(rows, key=exit_event_priority)

        self.assertEqual([row["signal_id"] for row in ordered], ["stop", "target"])

    def test_verified_stop_losses_bypass_non_stop_batch_cap(self) -> None:
        rows = [
            *[
                {"signal_id": f"stop-{index}", "exit_reason": "stop_loss", "created_at": f"2026-07-22T14:{index:02d}:00Z"}
                for index in range(12)
            ],
            *[
                {"signal_id": f"target-{index}", "exit_reason": "take_profit", "created_at": f"2026-07-22T15:{index:02d}:00Z"}
                for index in range(12)
            ],
        ]

        selected, deferred = select_exit_events(
            rows,
            max_non_stop_events=10,
            stop_loss_events_bypass_run_cap=True,
        )

        self.assertEqual(sum(row["exit_reason"] == "stop_loss" for row in selected), 12)
        self.assertEqual(sum(row["exit_reason"] == "take_profit" for row in selected), 10)
        self.assertEqual([row["signal_id"] for row in deferred], ["target-10", "target-11"])

    def test_contract_epoch_same_symbol_uses_exact_fill_batches_for_two_strategies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = replace(
                self.make_config(root),
                test_epoch_id="m15-sdk-contract-v1-test",
                test_started_at="2026-07-16T13:31:40Z",
            )
            account = self.account_state(quantity="5", available="5", cost_price="100")
            account["orders"] = [
                {
                    "order_id": "order-a",
                    "status": "Filled",
                    "symbol": "AAPL.US",
                    "side": "Buy",
                    "quantity": "2",
                    "executed_quantity": "2",
                    "executed_price": "100",
                },
                {
                    "order_id": "order-b",
                    "status": "Filled",
                    "symbol": "AAPL.US",
                    "side": "Buy",
                    "quantity": "3",
                    "executed_quantity": "3",
                    "executed_price": "101",
                },
            ]
            account["executions"] = [
                {"order_id": "order-a", "trade_id": "trade-a", "quantity": "2", "price": "100"},
                {"order_id": "order-b", "trade_id": "trade-b", "quantity": "3", "price": "101"},
            ]
            self.write_json(root / "account_state.json", account)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="94")])
            self.write_jsonl(root / "execution_ledger.jsonl", [
                {**self.open_row(stop_price="95"), "order_id": "order-a", "longbridge_order_id": "order-a", "test_epoch_id": config.test_epoch_id, "capital_bucket": "pa004-long-single"},
                {**self.open_row(stop_price="96", runtime_id="M10-PA-002-5m", strategy_id="M10-PA-002", quantity="3"), "order_id": "order-b", "longbridge_order_id": "order-b", "test_epoch_id": config.test_epoch_id, "capital_bucket": "pa002-5m-single"},
            ])

            payload = run_realtime_position_manager(config, generated_at="2026-07-16T14:00:00Z")
            signals = self.read_jsonl(root / "signals.jsonl")

        self.assertEqual(payload["fill_attribution_mismatch_count"], 0)
        self.assertEqual(payload["new_exit_signal_event_count"], 2)
        self.assertEqual({row["source_open_order_id"] for row in signals}, {"order-a", "order-b"})
        self.assertEqual({row["source_open_trade_id"] for row in signals}, {"trade-a", "trade-b"})
        self.assertEqual({row["quantity"] for row in signals}, {"2", "3"})
        self.assertEqual(
            payload["fill_attributed_open_exposure_by_bucket_symbol"],
            {
                "pa002-5m-single": {"AAPL": "303.00"},
                "pa004-long-single": {"AAPL": "200.00"},
            },
        )

    def test_formal_epoch_freezes_symbol_when_fill_batches_do_not_match_broker_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = replace(
                self.make_config(root),
                test_epoch_id="m15-sdk-formal-single-strategy-test",
                test_started_at="2026-07-16T13:31:40Z",
            )
            account = self.account_state(quantity="4", available="4", cost_price="100")
            account["orders"] = [{"order_id": "order-a", "status": "Filled"}]
            account["executions"] = [
                {"order_id": "order-a", "trade_id": "trade-a", "quantity": "2", "price": "100"},
            ]
            self.write_json(root / "account_state.json", account)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="94")])
            self.write_jsonl(root / "execution_ledger.jsonl", [{
                **self.open_row(stop_price="95"),
                "order_id": "order-a",
                "longbridge_order_id": "order-a",
                "test_epoch_id": config.test_epoch_id,
                "capital_bucket": "pa004-long-single",
            }])

            payload = run_realtime_position_manager(config, generated_at="2026-07-16T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

        self.assertEqual(payload["fill_attribution_mismatch_count"], 1)
        self.assertEqual(payload["new_exit_signal_event_count"], 0)
        self.assertEqual(rows[0]["manager_status"], "fill_attribution_mismatch_frozen")

    def test_runtime_uses_more_complete_canonical_fill_baseline_and_filters_legacy_fills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = replace(
                self.make_config(root),
                test_epoch_id="m15-sdk-formal-single-strategy-test",
                test_started_at="2026-07-16T13:31:40Z",
            )
            account = self.account_state(quantity="5", available="5", cost_price="100")
            account["orders"] = [
                {"order_id": "order-a", "status": "Filled"},
                {"order_id": "legacy-order", "status": "Filled"},
            ]
            account["executions"] = [
                {"order_id": "order-a", "trade_id": "trade-a", "quantity": "2", "price": "100"},
                {"order_id": "legacy-order", "trade_id": "legacy-trade", "quantity": "9", "price": "90"},
            ]
            self.write_json(root / "account_state.json", account)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="94")])
            self.write_jsonl(root / "execution_ledger.jsonl", [{
                **self.open_row(stop_price="95"),
                "order_id": "order-a",
                "longbridge_order_id": "order-a",
                "test_epoch_id": config.test_epoch_id,
                "capital_bucket": "pa004-long-single",
            }])
            canonical = {
                "schema_version": "m15.longbridge-fill-attribution.v2",
                "batches": [{
                    "batch_id": f"{config.test_epoch_id}|pa002_5m|M10-PA-002-5m|long|AAPL|order-b|trade-b",
                    "test_epoch_id": config.test_epoch_id,
                    "capital_bucket": "pa002_5m",
                    "runtime_id": "M10-PA-002-5m",
                    "direction": "long",
                    "symbol": "AAPL",
                    "open_order_id": "order-b",
                    "trade_id": "trade-b",
                    "filled_quantity": "3.0000",
                    "remaining_quantity": "3.0000",
                    "open_price": "101.00",
                    "metadata": {
                        "strategy_id": "M10-PA-002",
                        "signal_id": "open-b",
                        "stop_price": "96",
                        "target_price": "110",
                    },
                }],
                "events": [{
                    "attribution_status": "matched_fill_batch",
                    "order_id": "order-b",
                    "trade_id": "trade-b",
                    "filled_quantity": "3.0000",
                }],
                "anomalies": [],
                "summary": {"matched_event_count": 1, "anomaly_count": 0, "open_batch_count": 1},
            }
            config.canonical_fill_attribution_path.parent.mkdir(parents=True, exist_ok=True)
            self.write_json(config.canonical_fill_attribution_path, canonical)

            payload = run_realtime_position_manager(config, generated_at="2026-07-16T14:00:00Z")
            signals = self.read_jsonl(root / "signals.jsonl")
            runtime = json.loads(config.fill_attribution_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["fill_attribution_mismatch_count"], 0)
        self.assertEqual(payload["new_exit_signal_event_count"], 2)
        self.assertEqual(runtime["baseline_source"], "canonical_full_history")
        self.assertEqual(runtime["summary"]["anomaly_count"], 0)
        order_a_batch = next(row for row in runtime["batches"] if row["open_order_id"] == "order-a")
        self.assertEqual(order_a_batch["metadata"]["stop_price"], "95")
        self.assertEqual({row["source_open_order_id"] for row in signals}, {"order-a", "order-b"})

    def test_prior_epoch_open_does_not_control_current_account_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = replace(
                self.make_config(root),
                test_epoch_id="formal-current",
                test_started_at="2026-07-16T13:31:40Z",
            )
            self.write_json(root / "account_state.json", self.account_state(cost_price="100"))
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="100")])
            self.write_jsonl(root / "execution_ledger.jsonl", [{
                **self.open_row(target_price="99"),
                "test_epoch_id": "prior-test",
                "submitted_at": "2026-07-08T14:00:00Z",
            }])

            payload = run_realtime_position_manager(config, generated_at="2026-07-16T14:00:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

        self.assertEqual(payload["managed_position_count"], 0)
        self.assertEqual(payload["exit_only_position_count"], 1)
        self.assertEqual(payload["new_exit_signal_event_count"], 0)
        self.assertEqual(rows[0]["runtime_id"], "M15-LONGBRIDGE-EXIT-ONLY")

    def test_take_profit_generates_close_long_signal_from_longbridge_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            account = self.account_state()
            account["orders_ok"] = True
            account["orders"] = []
            self.write_json(root / "account_state.json", account)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="111")])
            self.write_jsonl(root / "execution_ledger.jsonl", [self.open_row(target_price="110")])

            payload = run_realtime_position_manager(config, generated_at="2026-06-04T14:00:00Z")
            signals = self.read_jsonl(root / "signals.jsonl")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["new_exit_signal_event_count"], 1)
            self.assertEqual(signals[0]["side"], "sell")
            self.assertEqual(signals[0]["position_action"], "take_profit")
            self.assertEqual(signals[0]["quantity"], "2")
            self.assertEqual(signals[0]["limit_price"], "110.44")
            self.assertEqual(signals[0]["order_type"], "limit")
            self.assertEqual(signals[0]["exit_limit_price_source"], "current_price_minus_long_exit_buffer")
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
            self.assertEqual(signals[0]["order_type"], "market")
            self.assertEqual(signals[0]["limit_price"], "")
            self.assertTrue(signals[0]["market_exit_no_reprice"])

    def test_intraday_contract_position_forces_market_exit_at_1555_new_york(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            _, event = evaluate_position(
                config,
                {"symbol": "AAPL", "quantity": "2", "available": "2", "cost_price": "100"},
                {
                    "runtime_id": "M10-PA-002-5m",
                    "strategy_id": "M10-PA-002",
                    "position_direction": "long",
                    "open_order_id": "open-order",
                    "source_open_trade_id": "open-trade",
                    "signal_id": "open-signal",
                    "stop_price": "90",
                    "target_price": "120",
                    "open_market_date": "2026-08-05",
                },
                latest_price=Decimal("101"),
                generated_at="2026-08-05T19:55:00Z",
                existing_signal_ids=set(),
                recent_exit_attempts=set(),
                retriable_exit_signal_ids=set(),
            )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["exit_reason"], "intraday_forced_exit_1555_ny")
        self.assertEqual(event["order_type"], "market")
        self.assertEqual(event["limit_price"], "")

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
            first_signal = self.read_jsonl(root / "signals.jsonl")[0]
            self.write_jsonl(root / "execution_ledger.jsonl", [
                self.open_row(stop_price="95"),
                {
                    "signal_id": first_signal["signal_id"],
                    "symbol": "AAPL",
                    "side": "sell",
                    "position_action": "stop_loss",
                    "submission_status": "submitted",
                    "order_id": "exit-order-1",
                    "processed_at": "2026-06-04T14:00:01Z",
                },
            ])
            second = run_realtime_position_manager(config, generated_at="2026-06-04T14:01:00Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(first["new_exit_signal_event_count"], 1)
            self.assertEqual(second["new_exit_signal_event_count"], 0)
            self.assertEqual(rows[0]["manager_status"], "recent_exit_attempt_cooldown")
            self.assertEqual(len(signals), 1)

    def test_broker_failed_long_exit_can_issue_a_new_retry_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            account = self.account_state()
            account["orders_ok"] = True
            account["orders"] = []
            self.write_json(root / "account_state.json", account)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="106")])
            self.write_jsonl(root / "execution_ledger.jsonl", [self.open_row(target_price="105")])

            first = run_realtime_position_manager(config, generated_at="2026-06-04T14:00:00Z")
            first_signal = self.read_jsonl(root / "signals.jsonl")[0]
            self.write_jsonl(
                root / "execution_ledger.jsonl",
                [self.open_row(target_price="105"), {
                    "signal_id": first_signal["signal_id"],
                    "symbol": "AAPL",
                    "side": "sell",
                    "position_action": "take_profit",
                    "exit_reason": "take_profit",
                    "submission_status": "broker_submit_failed:OpenApiException",
                    "processed_at": "2026-06-04T14:00:01Z",
                }],
            )

            second = run_realtime_position_manager(config, generated_at="2026-06-04T14:01:00Z")
            third = run_realtime_position_manager(config, generated_at="2026-06-04T14:16:02Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(first["new_exit_signal_event_count"], 1)
            self.assertEqual(second["new_exit_signal_event_count"], 0)
            self.assertEqual(third["new_exit_signal_event_count"], 1)
            self.assertEqual(signals[-1]["signal_id"], f"{first_signal['signal_id']}-retry-2")

    def test_broker_failed_exit_does_not_retry_when_broker_order_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            account = self.account_state()
            account["orders_ok"] = True
            account["orders"] = []
            self.write_json(root / "account_state.json", account)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="106")])
            self.write_jsonl(root / "execution_ledger.jsonl", [self.open_row(target_price="105")])

            run_realtime_position_manager(
                config, generated_at="2026-06-04T14:00:00Z"
            )
            first_signal = self.read_jsonl(root / "signals.jsonl")[0]
            failed_row = {
                "signal_id": first_signal["signal_id"],
                "client_request_id": "m15rt-exit-request",
                "symbol": "AAPL",
                "side": "sell",
                "position_action": "take_profit",
                "exit_reason": "take_profit",
                "submission_status": "broker_submit_failed:TimeoutError",
                "processed_at": "2026-06-04T14:00:01Z",
                "source_open_order_id": first_signal.get("source_open_order_id", ""),
                "source_open_trade_id": first_signal.get("source_open_trade_id", ""),
            }
            self.write_jsonl(
                root / "execution_ledger.jsonl",
                [self.open_row(target_price="105"), failed_row],
            )
            account["orders"] = [
                {
                    "order_id": "broker-exit-order",
                    "status": "Submitted",
                    "executed_quantity": "0",
                    "remark": (
                        f"PAT-RT {first_signal['signal_id']} "
                        "m15rt-exit-request"
                    ),
                }
            ]
            self.write_json(root / "account_state.json", account)

            payload = run_realtime_position_manager(
                config, generated_at="2026-06-04T14:16:02Z"
            )
            signals = self.read_jsonl(root / "signals.jsonl")

        self.assertEqual(payload["new_exit_signal_event_count"], 0)
        self.assertEqual(len(signals), 1)

    def test_exit_signal_that_never_reached_executor_can_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(root / "account_state.json", self.account_state())
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(close="94")])
            self.write_jsonl(root / "execution_ledger.jsonl", [self.open_row(stop_price="95")])

            first = run_realtime_position_manager(config, generated_at="2026-06-04T14:00:00Z")
            first_signal = self.read_jsonl(root / "signals.jsonl")[0]
            second = run_realtime_position_manager(config, generated_at="2026-06-04T14:01:00Z")
            third = run_realtime_position_manager(config, generated_at="2026-06-04T14:16:02Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(first["new_exit_signal_event_count"], 1)
            self.assertEqual(second["new_exit_signal_event_count"], 0)
            self.assertEqual(third["new_exit_signal_event_count"], 1)
            self.assertEqual(signals[-1]["signal_id"], f"{first_signal['signal_id']}-retry-2")

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
