from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from scripts.m12_29_current_day_scan_dashboard_lib import (
    m15_longbridge_closed_trade_quality_summary,
    m15_longbridge_strategy_quality_summary,
    m15_paper_short_execution_summary,
    m15_virtual_bucket_performance_from_order_reconciliation,
)
from scripts.m15_longbridge_realtime_account_state_lib import build_order_reconciliation, load_config as load_account_state_config
from scripts.m15_longbridge_realtime_execution_lib import (
    LEDGER_JSONL,
    ORDER_RECONCILIATION_JSON,
    VirtualCapitalBucket,
    hydrate_unconfirmed_execution_rows,
    longbridge_order_command,
    load_config as load_execution_config,
    run_realtime_execution,
    submitted_short_cover_key_set,
)
from scripts.m15_longbridge_realtime_position_manager_lib import (
    load_config as load_position_manager_config,
    run_realtime_position_manager,
)
from scripts.m15_longbridge_realtime_signal_router_lib import (
    PRICE_ACTION_RUNTIME_SPECS,
    price_action_signal_for_runtime,
)


SHORT_EPOCH = "m15-short-single-strategy-20260713"
SHORT_RUNTIME = "M10-PA-002-5m-short"


class FakeShortPaperClient:
    def __init__(self, *, max_quantity: str = "10") -> None:
        self.max_quantity = max_quantity
        self.orders: list[dict] = []

    def max_short_quantity(self, symbol: str, limit_price: object) -> dict:
        del symbol, limit_price
        quantity = int(self.max_quantity)
        return {
            "ok": quantity > 0,
            "status": "short_capacity_confirmed" if quantity > 0 else "short_capacity_zero_or_permission_denied",
            "max_quantity": self.max_quantity,
            "elapsed_ms": 2,
        }

    def submit_order(self, order_payload: dict) -> dict:
        self.orders.append(order_payload)
        return {"submitted": True, "order_id": f"SHORT-{len(self.orders)}"}


class M15PaperShortBucketsTest(unittest.TestCase):
    def test_three_short_detectors_require_bearish_structure_and_market_confirmation(self) -> None:
        generated_at = datetime(2026, 7, 13, 15, 5, tzinfo=UTC)
        market = {
            ("SPY", "5m"): [self.bar("SPY-1", "2026-07-13T15:00:00Z", "100", "100.2", "99.7", "100", "100"), self.bar("SPY-2", "2026-07-13T15:05:00Z", "99.6", "99.8", "99.4", "99.7", "200")],
            ("QQQ", "5m"): [self.bar("QQQ-1", "2026-07-13T15:00:00Z", "100", "100.2", "99.7", "100", "100"), self.bar("QQQ-2", "2026-07-13T15:05:00Z", "99.6", "99.8", "99.4", "99.7", "200")],
        }
        pa002_rows = [
            self.bar("PA002-1", "2026-07-13T14:50:00Z", "100.3", "100.6", "99.7", "100.2", "100"),
            self.bar("PA002-2", "2026-07-13T14:55:00Z", "100.0", "100.4", "99.7", "100.1", "100"),
            self.bar("PA002-3", "2026-07-13T15:00:00Z", "98.5", "99.5", "98.4", "98.5", "200"),
        ]
        pa013_rows = [
            self.bar("PA013-1", "2026-07-13T14:50:00Z", "101.8", "101.9", "101.5", "101.8", "100"),
            self.bar("PA013-2", "2026-07-13T14:55:00Z", "102.5", "102.5", "102.0", "102.5", "100"),
            self.bar("PA013-3", "2026-07-13T15:00:00Z", "101.2", "102.66", "101.15", "101.2", "200"),
        ]
        pa011_rows = [
            self.bar(f"PA011-{index}", f"2026-07-13T{14 + index // 6:02d}:{30 + (index % 6) * 5:02d}:00Z", "101", "102", "100", "101", "100")
            for index in range(6)
        ] + [
            self.bar("PA011-previous", "2026-07-13T15:00:00Z", "101.9", "102.0", "100.0", "101.9", "100"),
            self.bar("PA011-latest", "2026-07-13T15:05:00Z", "98.8", "99.0", "98.79", "98.8", "200"),
        ]

        cases = [
            ("M10-PA-002-5m-short", "PA002", pa002_rows),
            ("M10-PA-013-5m-short", "PA013", pa013_rows),
            ("M10-PA-011-ORB-R1-5m-short", "PA011", pa011_rows),
        ]
        for runtime_id, symbol, rows in cases:
            grouped = {**market, (symbol, "5m"): rows}
            signal = price_action_signal_for_runtime(
                runtime_id=runtime_id,
                spec=PRICE_ACTION_RUNTIME_SPECS[runtime_id],
                symbol=symbol,
                rows=rows,
                grouped_events=grouped,
                generated_at=generated_at,
            )
            self.assertIsNotNone(signal, runtime_id)
            assert signal is not None
            self.assertEqual(signal["direction"], "short")
            self.assertEqual(signal["side"], "sell_short")
            self.assertEqual(signal["position_action"], "open_short")
            self.assertGreaterEqual(float(signal["quality_score"]), float(signal["minimum_quality_score"]))

    def test_execution_floors_short_quantity_and_submits_sell_after_capacity_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_execution_config(root)
            self.write_jsonl(root / "signals.jsonl", [self.short_signal(quantity="4.9")])
            client = FakeShortPaperClient(max_quantity="8")

            payload = run_realtime_execution(config, generated_at="2026-07-13T15:05:01Z", broker_client=client)
            row = self.read_jsonl(config.output_dir / "m15_longbridge_realtime_execution_ledger.jsonl")[0]

            self.assertEqual(payload["submitted_count"], 1)
            self.assertEqual(row["submitted_quantity"], "4")
            self.assertEqual(row["submission_status"], "submitted")
            self.assertEqual(row["short_capacity_check_status"], "short_capacity_confirmed")
            self.assertEqual(client.orders[0]["side"], "sell_short")
            command, blockers = longbridge_order_command(config, "longbridge", client.orders[0])
            self.assertEqual(blockers, [])
            self.assertEqual(command[2], "sell")
            self.assertIn("open_short", command[command.index("--remark") + 1])

    def test_short_open_blocks_existing_long_and_broker_capacity_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [{"symbol": "AAPL.US", "quantity": "1", "position_side": "long"}],
                "orders": [],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_execution_config(root, account_state=account_state)
            self.write_jsonl(root / "signals.jsonl", [self.short_signal()])
            payload = run_realtime_execution(config, generated_at="2026-07-13T15:05:01Z", broker_client=FakeShortPaperClient(max_quantity="0"))
            row = self.read_jsonl(config.output_dir / "m15_longbridge_realtime_execution_ledger.jsonl")[0]

            self.assertEqual(payload["submitted_count"], 0)
            self.assertIn("blocked_short_conflicts_with_existing_long_position", row["blockers"])
            self.assertNotIn("blocked_short_broker_capacity_unavailable", row["blockers"])

    def test_short_reconciliation_requires_exact_order_identity_and_calculates_cover_pnl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_account_state_config(root)
            account_state = {
                "orders": [
                    {
                        "order_id": "short-open-order",
                        "symbol": "AAPL.US",
                        "side": "Sell",
                        "status": "Filled",
                        "quantity": "2",
                        "price": "100",
                        "executed_quantity": "2",
                        "executed_price": "100",
                        "created_at": "2026-07-13T15:05:00Z",
                    },
                    {
                        "order_id": "short-cover-order",
                        "symbol": "AAPL.US",
                        "side": "Buy",
                        "status": "Filled",
                        "quantity": "2",
                        "price": "95",
                        "executed_quantity": "2",
                        "executed_price": "95",
                        "created_at": "2026-07-13T15:15:00Z",
                    },
                ]
            }
            ledger = [
                self.short_ledger_row("short-open", "short-open-order", "open_short", "sell_short", "2026-07-13T15:05:00Z"),
                self.short_ledger_row(
                    "short-cover", "short-cover-order", "close_short", "buy", "2026-07-13T15:15:00Z", source_open_order_id="short-open-order"
                ),
                self.short_ledger_row("unconfirmed", "", "open_short", "sell_short", "2026-07-13T15:20:00Z"),
            ]

            reconciliation = build_order_reconciliation(config, "2026-07-13T15:20:01Z", account_state, ledger)
            rows = reconciliation["rows"]
            self.assertEqual(sum(1 for row in rows if row["attribution_status"] == "matched_m15_realtime_ledger"), 2)
            unmatched = next(row for row in rows if row["signal_id"] == "unconfirmed")
            self.assertEqual(unmatched["attribution_status"], "local_submitted_no_longbridge_order")
            self.assertEqual(unmatched["attribution_match_method"], "no_longbridge_order_match")
            self.assertTrue(all("|short|AAPL|" in row["attribution_key"] for row in rows if row["attribution_key"]))

            performance = m15_virtual_bucket_performance_from_order_reconciliation(
                reconciliation,
                {"current_holdings": []},
                SHORT_EPOCH,
                "2026-07-13",
            )
            self.assertEqual(performance["pa002_5m_short"]["closed_trade_count"], "1")
            self.assertEqual(performance["pa002_5m_short"]["realized_pnl"], "10.00")
            self.assertEqual(performance["pa002_5m_short"]["filled_open_count"], "1")
            self.assertEqual(performance["pa002_5m_short"]["filled_close_count"], "1")
            self.assertEqual(performance["pa002_5m_short"]["open_position_quantity"], "0.00")
            short_summary = m15_paper_short_execution_summary(
                ledger,
                SHORT_EPOCH,
                [
                    {
                        "position_direction": "short",
                        "used_exposure": "0.00",
                        "open_position_quantity": "0.00",
                        "submitted_open_count": "1",
                        "filled_close_count": "1",
                    }
                ],
            )
            self.assertEqual(short_summary["filled_open_count"], "1")
            self.assertEqual(short_summary["filled_close_count"], "1")

            quality_account_state = {
                "historical_executions": [
                    {
                        "order_id": "short-open-order",
                        "time": "2026-07-13T15:05:00Z",
                        "side": "Sell",
                        "symbol": "AAPL.US",
                        "quantity": "2",
                        "price": "100",
                    },
                    {
                        "order_id": "short-cover-order",
                        "time": "2026-07-13T15:15:00Z",
                        "side": "Buy",
                        "symbol": "AAPL.US",
                        "quantity": "2",
                        "price": "95",
                    },
                ]
            }
            closed_quality = m15_longbridge_closed_trade_quality_summary(quality_account_state, reconciliation)
            strategy_quality = m15_longbridge_strategy_quality_summary(
                quality_account_state,
                ledger[:2],
                order_reconciliation=reconciliation,
            )
            self.assertEqual(closed_quality["sample_count"], "0")
            self.assertEqual(closed_quality["short_excluded_count"], "2")
            self.assertEqual(strategy_quality["closed_trade_count"], "0")
            self.assertEqual(strategy_quality["short_excluded_execution_count"], "2")

    def test_attributed_pending_short_open_does_not_block_a_second_short_bucket(self) -> None:
        second_runtime = "M10-PA-013-5m-short"
        second_bucket_id = "pa013_5m_short"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [],
                "orders": [],
                "open_orders": [
                    {"order_id": "tracked-first-short", "symbol": "AAPL.US", "side": "Sell", "quantity": "2"}
                ],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_execution_config(root, account_state=account_state)
            buckets = dict(config.virtual_capital_buckets)
            buckets[second_bucket_id] = VirtualCapitalBucket(
                bucket_id=second_bucket_id,
                label="PA013-5m做空测试仓（M10-PA-013-5m）",
                position_direction="short",
                equity=config.paper_account_equity,
                max_total_exposure=Decimal("2000"),
                max_symbol_exposure=Decimal("500"),
                max_risk_per_order=Decimal("10"),
                min_cash_reserve=Decimal("8000"),
                daily_new_symbol_limit=0,
                runtime_daily_new_symbol_limits={},
                runtime_ids=(second_runtime,),
            )
            config = replace(
                config,
                allowed_runtime_ids=(SHORT_RUNTIME, second_runtime),
                paper_short_runtime_ids=(SHORT_RUNTIME, second_runtime),
                virtual_capital_buckets=buckets,
                runtime_capital_bucket_map={SHORT_RUNTIME: "pa002_5m_short", second_runtime: second_bucket_id},
                runtime_minimum_net_profit_after_fees={SHORT_RUNTIME: Decimal("12"), second_runtime: Decimal("12")},
                runtime_minimum_reward_r={SHORT_RUNTIME: Decimal("2"), second_runtime: Decimal("2")},
            )
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [self.short_ledger_row("first-short", "tracked-first-short", "open_short", "sell_short", "2026-07-13T15:04:00Z")],
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.short_signal(
                        signal_id="second-short",
                        runtime_id=second_runtime,
                        strategy_id="M10-PA-013",
                        capital_bucket=second_bucket_id,
                    )
                ],
            )

            payload = run_realtime_execution(
                config,
                generated_at="2026-07-13T15:05:01Z",
                broker_client=FakeShortPaperClient(max_quantity="8"),
            )
            row = self.read_jsonl(config.output_dir / LEDGER_JSONL)[-1]

            self.assertEqual(payload["submitted_count"], 1)
            self.assertNotIn("blocked_unattributed_open_sell_order_same_symbol", row["blockers"])

    def test_two_short_buckets_can_cover_their_own_confirmed_lots_without_cross_blocking(self) -> None:
        second_runtime = "M10-PA-013-5m-short"
        second_bucket_id = "pa013_5m_short"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [{"symbol": "AAPL.US", "quantity": "4", "position_side": "short"}],
                "orders": [
                    {"order_id": "short-open-a", "symbol": "AAPL.US", "side": "Sell", "status": "Filled", "executed_quantity": "2", "executed_price": "100"},
                    {"order_id": "short-open-b", "symbol": "AAPL.US", "side": "Sell", "status": "Filled", "executed_quantity": "2", "executed_price": "100"},
                ],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_execution_config(root, account_state=account_state)
            buckets = dict(config.virtual_capital_buckets)
            buckets[second_bucket_id] = VirtualCapitalBucket(
                bucket_id=second_bucket_id,
                label="PA013-5m做空测试仓（M10-PA-013-5m）",
                position_direction="short",
                equity=config.paper_account_equity,
                max_total_exposure=Decimal("2000"),
                max_symbol_exposure=Decimal("500"),
                max_risk_per_order=Decimal("10"),
                min_cash_reserve=Decimal("8000"),
                daily_new_symbol_limit=0,
                runtime_daily_new_symbol_limits={},
                runtime_ids=(second_runtime,),
            )
            config = replace(
                config,
                allowed_runtime_ids=(SHORT_RUNTIME, second_runtime),
                paper_short_runtime_ids=(SHORT_RUNTIME, second_runtime),
                virtual_capital_buckets=buckets,
                runtime_capital_bucket_map={SHORT_RUNTIME: "pa002_5m_short", second_runtime: second_bucket_id},
            )
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    self.short_ledger_row("short-open-a", "short-open-a", "open_short", "sell_short", "2026-07-13T15:00:00Z"),
                    {
                        **self.short_ledger_row("short-open-b", "short-open-b", "open_short", "sell_short", "2026-07-13T15:01:00Z"),
                        "runtime_id": second_runtime,
                        "strategy_id": "M10-PA-013",
                        "capital_bucket": second_bucket_id,
                    },
                ],
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.short_signal(
                        signal_id="cover-a",
                        position_action="close_short",
                        side="buy",
                        quantity="2",
                        source_open_order_id="short-open-a",
                    ),
                    self.short_signal(
                        signal_id="cover-b",
                        runtime_id=second_runtime,
                        strategy_id="M10-PA-013",
                        capital_bucket=second_bucket_id,
                        position_action="close_short",
                        side="buy",
                        quantity="2",
                        source_open_order_id="short-open-b",
                    ),
                ],
            )

            client = FakeShortPaperClient()
            payload = run_realtime_execution(config, generated_at="2026-07-13T15:05:01Z", broker_client=client)
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)[-2:]

            self.assertEqual(payload["submitted_count"], 2)
            self.assertEqual([row["position_action"] for row in rows], ["close_short", "close_short"])
            self.assertTrue(all(order["side"] == "buy" for order in client.orders))
            self.assertNotIn("blocked_existing_submitted_short_cover_same_short_lot", rows[1]["blockers"])

    def test_short_cover_requires_exact_open_order_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [{"symbol": "AAPL.US", "quantity": "2", "position_side": "short"}],
                "orders": [{"order_id": "short-open", "symbol": "AAPL.US", "side": "Sell", "status": "Filled", "executed_quantity": "2", "executed_price": "100"}],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_execution_config(root, account_state=account_state)
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [self.short_ledger_row("short-open", "short-open", "open_short", "sell_short", "2026-07-13T15:00:00Z")],
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [self.short_signal(signal_id="cover-without-source", position_action="close_short", side="buy", quantity="2")],
            )

            payload = run_realtime_execution(config, generated_at="2026-07-13T15:05:01Z", broker_client=FakeShortPaperClient())
            row = self.read_jsonl(config.output_dir / LEDGER_JSONL)[-1]

            self.assertEqual(payload["submitted_count"], 0)
            self.assertIn("blocked_close_short_missing_source_open_order_id", row["blockers"])

    def test_pending_short_cover_blocks_duplicate_cover_after_old_time_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [{"symbol": "AAPL.US", "quantity": "2", "position_side": "short"}],
                "orders": [
                    {"order_id": "short-open", "symbol": "AAPL.US", "side": "Sell", "status": "Filled", "executed_quantity": "2", "executed_price": "100"},
                    {"order_id": "short-cover-pending", "symbol": "AAPL.US", "side": "Buy", "status": "Submitted", "quantity": "2", "price": "95"},
                ],
                "open_orders": [
                    {"order_id": "short-cover-pending", "symbol": "AAPL.US", "side": "Buy", "status": "Submitted", "quantity": "2", "price": "95"}
                ],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_execution_config(root, account_state=account_state)
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    self.short_ledger_row("short-open", "short-open", "open_short", "sell_short", "2026-07-13T15:00:00Z"),
                    self.short_ledger_row(
                        "cover-pending",
                        "short-cover-pending",
                        "close_short",
                        "buy",
                        "2026-07-13T15:00:01Z",
                        source_open_order_id="short-open",
                    ),
                ],
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.short_signal(
                        signal_id="cover-new-after-two-minutes",
                        created_at="2026-07-13T15:03:00Z",
                        position_action="close_short",
                        side="buy",
                        quantity="2",
                        source_open_order_id="short-open",
                    )
                ],
            )

            payload = run_realtime_execution(
                config,
                generated_at="2026-07-13T15:03:01Z",
                broker_client=FakeShortPaperClient(),
            )
            row = self.read_jsonl(config.output_dir / LEDGER_JSONL)[-1]

            self.assertEqual(payload["submitted_count"], 0)
            self.assertIn("blocked_existing_submitted_short_cover_same_short_lot", row["blockers"])

    def test_short_cover_source_from_another_bucket_does_not_authorize_cover(self) -> None:
        second_runtime = "M10-PA-013-5m-short"
        second_bucket_id = "pa013_5m_short"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [{"symbol": "AAPL.US", "quantity": "2", "position_side": "short"}],
                "orders": [{"order_id": "other-short-open", "symbol": "AAPL.US", "side": "Sell", "status": "Filled", "executed_quantity": "2", "executed_price": "100"}],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_execution_config(root, account_state=account_state)
            buckets = dict(config.virtual_capital_buckets)
            buckets[second_bucket_id] = VirtualCapitalBucket(
                bucket_id=second_bucket_id,
                label="PA013-5m做空测试仓（M10-PA-013-5m）",
                position_direction="short",
                equity=config.paper_account_equity,
                max_total_exposure=Decimal("2000"),
                max_symbol_exposure=Decimal("500"),
                max_risk_per_order=Decimal("10"),
                min_cash_reserve=Decimal("8000"),
                daily_new_symbol_limit=0,
                runtime_daily_new_symbol_limits={},
                runtime_ids=(second_runtime,),
            )
            config = replace(
                config,
                allowed_runtime_ids=(SHORT_RUNTIME, second_runtime),
                paper_short_runtime_ids=(SHORT_RUNTIME, second_runtime),
                virtual_capital_buckets=buckets,
                runtime_capital_bucket_map={SHORT_RUNTIME: "pa002_5m_short", second_runtime: second_bucket_id},
            )
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    {
                        **self.short_ledger_row("other-short", "other-short-open", "open_short", "sell_short", "2026-07-13T15:00:00Z"),
                        "runtime_id": second_runtime,
                        "strategy_id": "M10-PA-013",
                        "capital_bucket": second_bucket_id,
                    }
                ],
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.short_signal(
                        signal_id="wrong-bucket-cover",
                        position_action="close_short",
                        side="buy",
                        quantity="2",
                        source_open_order_id="other-short-open",
                    )
                ],
            )

            payload = run_realtime_execution(config, generated_at="2026-07-13T15:05:01Z", broker_client=FakeShortPaperClient())
            row = self.read_jsonl(config.output_dir / LEDGER_JSONL)[-1]

            self.assertEqual(payload["submitted_count"], 0)
            self.assertIn("blocked_close_short_without_verified_short_position", row["blockers"])

    def test_reconciled_terminal_cover_releases_lot_without_rewriting_execution_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [{"symbol": "AAPL.US", "quantity": "2", "position_side": "short"}],
                "orders": [{"order_id": "short-open", "symbol": "AAPL.US", "side": "Sell", "status": "Filled", "executed_quantity": "2", "executed_price": "100"}],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_execution_config(root, account_state=account_state)
            unconfirmed_cover = self.short_ledger_row(
                "cover-unconfirmed",
                "",
                "close_short",
                "buy",
                "2026-07-13T15:00:00Z",
                source_open_order_id="short-open",
            )
            unconfirmed_cover.update(
                {
                    "submission_status": "submit_unconfirmed_missing_order_id",
                    "submission_confirmation_state": "awaiting_broker_reconciliation",
                    "confirmation_required": True,
                }
            )
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    self.short_ledger_row("short-open", "short-open", "open_short", "sell_short", "2026-07-13T14:59:00Z"),
                    unconfirmed_cover,
                ],
            )
            self.write_json(
                config.output_dir / ORDER_RECONCILIATION_JSON,
                {
                    "rows": [
                        {
                            "order_id": "cover-canceled",
                            "signal_id": "cover-unconfirmed",
                            "status": "Canceled",
                            "canonical_status": "canceled",
                            "executed_quantity": "0",
                            "attribution_status": "matched_m15_realtime_ledger",
                            "attribution_match_method": "remark_signal_id",
                        }
                    ]
                },
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.short_signal(
                        signal_id="cover-after-cancel",
                        created_at="2026-07-13T15:05:00Z",
                        position_action="close_short",
                        side="buy",
                        quantity="2",
                        source_open_order_id="short-open",
                    )
                ],
            )

            client = FakeShortPaperClient()
            payload = run_realtime_execution(config, generated_at="2026-07-13T15:05:01Z", broker_client=client)
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["submitted_count"], 1)
            self.assertEqual(client.orders[0]["side"], "buy")
            self.assertEqual(rows[-2]["submission_status"], "submit_unconfirmed_missing_order_id")
            self.assertEqual(rows[-2]["order_id"], "")
            self.assertNotIn("blocked_existing_submitted_short_cover_same_short_lot", rows[-1]["blockers"])

    def test_partial_terminal_cover_leaves_only_remaining_short_quantity_for_new_cover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_state = {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [{"symbol": "AAPL.US", "quantity": "1", "position_side": "short"}],
                "orders": [{"order_id": "short-open", "symbol": "AAPL.US", "side": "Sell", "status": "Filled", "executed_quantity": "2", "executed_price": "100"}],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            }
            config = self.make_execution_config(root, account_state=account_state)
            unconfirmed_cover = self.short_ledger_row(
                "cover-partial",
                "",
                "close_short",
                "buy",
                "2026-07-13T15:00:00Z",
                source_open_order_id="short-open",
            )
            unconfirmed_cover["submission_status"] = "submit_unconfirmed_missing_order_id"
            self.write_jsonl(
                config.output_dir / LEDGER_JSONL,
                [
                    self.short_ledger_row("short-open", "short-open", "open_short", "sell_short", "2026-07-13T14:59:00Z"),
                    unconfirmed_cover,
                ],
            )
            self.write_json(
                config.output_dir / ORDER_RECONCILIATION_JSON,
                {
                    "rows": [
                        {
                            "order_id": "cover-partial-canceled",
                            "signal_id": "cover-partial",
                            "status": "Canceled",
                            "canonical_status": "canceled",
                            "executed_quantity": "1",
                            "executed_price": "99",
                            "attribution_status": "matched_m15_realtime_ledger",
                            "attribution_match_method": "remark_signal_id",
                        }
                    ]
                },
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [
                    self.short_signal(
                        signal_id="cover-partial-remainder",
                        created_at="2026-07-13T15:05:00Z",
                        position_action="close_short",
                        side="buy",
                        quantity="1",
                        source_open_order_id="short-open",
                    )
                ],
            )

            client = FakeShortPaperClient()
            payload = run_realtime_execution(config, generated_at="2026-07-13T15:05:01Z", broker_client=client)

            self.assertEqual(payload["submitted_count"], 1)
            self.assertEqual(str(client.orders[0]["quantity"]), "1")

    def test_reconciliation_terminal_statuses_release_unconfirmed_short_cover(self) -> None:
        unconfirmed_cover = self.short_ledger_row(
            "cover-terminal",
            "",
            "close_short",
            "buy",
            "2026-07-13T15:00:00Z",
            source_open_order_id="short-open",
        )
        unconfirmed_cover["submission_status"] = "submit_unconfirmed_missing_order_id"
        for status in ("filled", "canceled", "rejected", "expired"):
            with self.subTest(status=status):
                hydrated = hydrate_unconfirmed_execution_rows(
                    [unconfirmed_cover],
                    {},
                    {
                        "rows": [
                            {
                                "order_id": f"cover-{status}",
                                "signal_id": "cover-terminal",
                                "status": status.title(),
                                "canonical_status": status,
                                "executed_quantity": "2" if status == "filled" else "0",
                                "attribution_status": "matched_m15_realtime_ledger",
                                "attribution_match_method": "remark_signal_id",
                            }
                        ]
                    },
                )

                self.assertEqual(hydrated[0]["submission_confirmation_state"], "broker_reconciled_terminal")
                self.assertEqual(
                    submitted_short_cover_key_set(
                        hydrated,
                        "2026-07-13T14:30:00Z",
                        account_state={},
                    ),
                    set(),
                )

    def test_position_manager_uses_reconciled_short_open_order_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager_config = self.make_position_manager_config(root)
            self.write_json(
                root / "account_state.json",
                {
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "positions": [{"symbol": "AAPL.US", "quantity": "2", "position_side": "short", "cost_price": "100"}],
                    "orders": [],
                    "open_orders": [],
                },
            )
            unconfirmed_open = self.short_ledger_row(
                "short-open-unconfirmed",
                "",
                "open_short",
                "sell_short",
                "2026-07-13T15:00:00Z",
            )
            unconfirmed_open.update(
                {
                    "submission_status": "submit_unconfirmed_missing_order_id",
                    "stop_price": "101",
                    "target_price": "98",
                    "source_market_event_id": "short-bar-1",
                }
            )
            self.write_jsonl(root / "execution_ledger.jsonl", [unconfirmed_open])
            manager_config.output_dir.mkdir(parents=True, exist_ok=True)
            self.write_json(
                manager_config.output_dir / ORDER_RECONCILIATION_JSON,
                {
                    "rows": [
                        {
                            "order_id": "short-open-reconciled",
                            "signal_id": "short-open-unconfirmed",
                            "status": "Filled",
                            "canonical_status": "filled",
                            "executed_quantity": "2",
                            "executed_price": "100",
                            "attribution_status": "matched_m15_realtime_ledger",
                            "attribution_match_method": "remark_signal_id",
                        }
                    ]
                },
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [{"event_id": "short-stop", "symbol": "AAPL", "event_time": "2026-07-13T15:10:00Z", "close": "101.20"}],
            )

            payload = run_realtime_position_manager(manager_config, generated_at="2026-07-13T15:10:01Z")
            events = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["managed_short_position_count"], 1)
            self.assertEqual(events[0]["position_action"], "close_short")
            self.assertEqual(events[0]["source_open_order_id"], "short-open-reconciled")

    def test_confirmed_short_position_generates_buy_to_cover_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            execution_config = self.make_execution_config(root)
            manager_config = self.make_position_manager_config(root)
            self.write_json(
                root / "account_state.json",
                {
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "positions": [
                        {
                            "symbol": "AAPL.US",
                            "quantity": "2",
                            "position_side": "short",
                            "cost_price": "100",
                        }
                    ],
                    "orders": [
                        {
                            "order_id": "short-open-order",
                            "symbol": "AAPL.US",
                            "side": "Sell",
                            "status": "Filled",
                            "executed_quantity": "2",
                            "executed_price": "100",
                        }
                    ],
                    "open_orders": [],
                },
            )
            self.write_jsonl(
                root / "execution_ledger.jsonl",
                [
                    {
                        **self.short_ledger_row(
                            "short-open", "short-open-order", "open_short", "sell_short", "2026-07-13T15:05:00Z"
                        ),
                        "stop_price": "101",
                        "target_price": "98",
                        "source_market_event_id": "short-bar-1",
                    }
                ],
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    {
                        "event_id": "short-stop-bar",
                        "symbol": "AAPL",
                        "event_time": "2026-07-13T15:10:00Z",
                        "close": "101.20",
                    }
                ],
            )

            payload = run_realtime_position_manager(manager_config, generated_at="2026-07-13T15:10:01Z")
            events = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["managed_short_position_count"], 1)
            self.assertEqual(payload["new_exit_signal_event_count"], 1)
            self.assertEqual(events[0]["position_action"], "close_short")
            self.assertEqual(events[0]["side"], "buy")
            self.assertEqual(events[0]["source_open_order_id"], "short-open-order")
            command, blockers = longbridge_order_command(execution_config, "longbridge", events[0])
            self.assertEqual(blockers, [])
            self.assertEqual(command[2], "buy")

    def test_short_position_manager_preserves_exact_open_lot_when_a_cover_is_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager_config = self.make_position_manager_config(root)
            self.write_json(
                root / "account_state.json",
                {
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "positions": [{"symbol": "AAPL.US", "quantity": "2", "position_side": "short", "cost_price": "100"}],
                    "orders": [
                        {"order_id": "short-open-a", "symbol": "AAPL.US", "side": "Sell", "status": "Filled", "executed_quantity": "2", "executed_price": "100"},
                        {"order_id": "short-open-b", "symbol": "AAPL.US", "side": "Sell", "status": "Filled", "executed_quantity": "2", "executed_price": "100"},
                        {"order_id": "short-cover-a", "symbol": "AAPL.US", "side": "Buy", "status": "Filled", "executed_quantity": "2", "executed_price": "101"},
                    ],
                    "open_orders": [],
                },
            )
            self.write_jsonl(
                root / "execution_ledger.jsonl",
                [
                    {**self.short_ledger_row("short-open-a", "short-open-a", "open_short", "sell_short", "2026-07-13T15:00:00Z"), "stop_price": "101", "target_price": "98"},
                    {**self.short_ledger_row("short-open-b", "short-open-b", "open_short", "sell_short", "2026-07-13T15:01:00Z"), "stop_price": "101", "target_price": "98"},
                    self.short_ledger_row("short-cover-a", "short-cover-a", "close_short", "buy", "2026-07-13T15:03:00Z", source_open_order_id="short-open-a"),
                ],
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [{"event_id": "short-stop", "symbol": "AAPL", "event_time": "2026-07-13T15:10:00Z", "close": "101.20"}],
            )

            payload = run_realtime_position_manager(manager_config, generated_at="2026-07-13T15:10:01Z")
            events = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["managed_short_position_count"], 1)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["source_open_order_id"], "short-open-b")

    def test_position_manager_rebuilds_terminal_short_cover_and_execution_submits_retry(self) -> None:
        for executed_quantity, remaining_quantity in (("0", "2"), ("1", "1")):
            with self.subTest(executed_quantity=executed_quantity):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    execution_config = self.make_execution_config(root)
                    manager_config = replace(
                        self.make_position_manager_config(root),
                        realtime_execution_ledger_path=execution_config.output_dir / LEDGER_JSONL,
                    )
                    self.write_json(
                        root / "account_state.json",
                        {
                            "account_channel": "lb_papertrading",
                            "paper_account_verified": True,
                            "positions": [{"symbol": "AAPL.US", "quantity": "2", "position_side": "short", "cost_price": "100"}],
                            "orders": [
                                {
                                    "order_id": "short-open-order",
                                    "symbol": "AAPL.US",
                                    "side": "Sell",
                                    "status": "Filled",
                                    "executed_quantity": "2",
                                    "executed_price": "100",
                                }
                            ],
                            "open_orders": [],
                            "live_execution": False,
                            "real_money_actions": False,
                        },
                    )
                    self.write_jsonl(
                        execution_config.output_dir / LEDGER_JSONL,
                        [
                            {
                                **self.short_ledger_row(
                                    "short-open", "short-open-order", "open_short", "sell_short", "2026-07-13T15:00:00Z"
                                ),
                                "stop_price": "101",
                                "target_price": "98",
                                "source_market_event_id": "short-stop-bar",
                            }
                        ],
                    )
                    self.write_jsonl(
                        root / "market_events.jsonl",
                        [{"event_id": "short-stop-bar", "symbol": "AAPL", "event_time": "2026-07-13T15:10:00Z", "close": "101.20"}],
                    )

                    first_manager = run_realtime_position_manager(manager_config, generated_at="2026-07-13T15:10:01Z")
                    client = FakeShortPaperClient()
                    first_execution = run_realtime_execution(
                        execution_config,
                        generated_at="2026-07-13T15:10:02Z",
                        broker_client=client,
                    )
                    first_event = self.read_jsonl(root / "signals.jsonl")[0]

                    self.write_json(
                        root / "account_state.json",
                        {
                            "account_channel": "lb_papertrading",
                            "paper_account_verified": True,
                            "positions": [
                                {
                                    "symbol": "AAPL.US",
                                    "quantity": remaining_quantity,
                                    "position_side": "short",
                                    "cost_price": "100",
                                }
                            ],
                            "orders": [
                                {
                                    "order_id": "short-open-order",
                                    "symbol": "AAPL.US",
                                    "side": "Sell",
                                    "status": "Filled",
                                    "executed_quantity": "2",
                                    "executed_price": "100",
                                },
                                {
                                    "order_id": "SHORT-1",
                                    "symbol": "AAPL.US",
                                    "side": "Buy",
                                    "status": "Canceled",
                                    "quantity": "2",
                                    "executed_quantity": executed_quantity,
                                    "executed_price": "101.20",
                                },
                            ],
                            "open_orders": [],
                            "live_execution": False,
                            "real_money_actions": False,
                        },
                    )

                    retry_manager = run_realtime_position_manager(manager_config, generated_at="2026-07-13T15:11:00Z")
                    events = self.read_jsonl(root / "signals.jsonl")
                    retry_execution = run_realtime_execution(
                        execution_config,
                        generated_at="2026-07-13T15:11:01Z",
                        broker_client=client,
                    )

                    self.assertEqual(first_manager["new_exit_signal_event_count"], 1)
                    self.assertEqual(first_execution["submitted_count"], 1)
                    self.assertEqual(retry_manager["new_exit_signal_event_count"], 1)
                    self.assertEqual(retry_execution["submitted_count"], 1)
                    self.assertEqual(len(events), 2)
                    self.assertEqual(events[-1]["signal_id"], f"{first_event['signal_id']}-retry-2")
                    self.assertEqual(events[-1]["exit_retry_attempt"], 2)
                    self.assertEqual(events[-1]["exit_retry_of_signal_id"], first_event["signal_id"])
                    self.assertEqual(events[-1]["quantity"], remaining_quantity)
                    self.assertEqual(client.orders[-1]["side"], "buy")

    def test_filled_short_cover_does_not_retry_when_position_snapshot_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager_config = self.make_position_manager_config(root)
            self.write_json(
                root / "account_state.json",
                {
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "positions": [{"symbol": "AAPL.US", "quantity": "2", "position_side": "short", "cost_price": "100"}],
                    "orders": [
                        {"order_id": "short-open-order", "symbol": "AAPL.US", "side": "Sell", "status": "Filled", "executed_quantity": "2", "executed_price": "100"},
                        {"order_id": "short-cover-filled", "symbol": "AAPL.US", "side": "Buy", "status": "Filled", "executed_quantity": "2", "executed_price": "101"},
                    ],
                    "open_orders": [],
                },
            )
            self.write_jsonl(
                root / "execution_ledger.jsonl",
                [
                    {**self.short_ledger_row("short-open", "short-open-order", "open_short", "sell_short", "2026-07-13T15:00:00Z"), "stop_price": "101", "target_price": "98"},
                    self.short_ledger_row(
                        "m15exit-filled", "short-cover-filled", "close_short", "buy", "2026-07-13T15:05:00Z", source_open_order_id="short-open-order"
                    ),
                ],
            )
            self.write_jsonl(
                root / "signals.jsonl",
                [{"signal_id": "m15exit-filled", "position_action": "close_short"}],
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [{"event_id": "short-stop", "symbol": "AAPL", "event_time": "2026-07-13T15:10:00Z", "close": "101.20"}],
            )

            payload = run_realtime_position_manager(manager_config, generated_at="2026-07-13T15:10:01Z")

            self.assertEqual(payload["managed_short_position_count"], 0)
            self.assertEqual(payload["new_exit_signal_event_count"], 0)

    def make_execution_config(self, root: Path, *, account_state: dict | None = None):
        state = account_state or {
            "account_channel": "lb_papertrading",
            "paper_account_verified": True,
            "positions": [],
            "orders": [],
            "open_orders": [],
            "live_execution": False,
            "real_money_actions": False,
        }
        self.write_json(root / "account_state.json", state)
        payload = {
            "stage": "M15.longbridge_realtime_execution",
            "inputs": {
                "realtime_signal_events": str(root / "signals.jsonl"),
                "paper_account_state": str(root / "account_state.json"),
            },
            "outputs": {"output_dir": str(root / "out")},
            "longbridge_realtime": {
                "required_account_channel": "lb_papertrading",
                "cli_timeout_seconds": 6,
                "time_in_force": "day",
                "outside_rth": "RTH_ONLY",
                "execute_orders": True,
                "paper_trading_approval": True,
                "session_started_at": "2026-07-13T14:30:00Z",
                "allow_replay": False,
                "watch_interval_seconds": 1,
                "latency_target_ms": 1000,
                "latency_acceptable_ms": 5000,
                "max_delayed_signal_age_seconds": 60,
                "allowed_runtime_ids": [SHORT_RUNTIME],
            },
            "paper_short_testing": {
                "enabled": True,
                "test_epoch_id": SHORT_EPOCH,
                "test_started_at": "2026-07-13T14:30:00Z",
                "runtime_ids": [SHORT_RUNTIME],
            },
            "paper_account_model": {
                "equity": "10000",
                "max_total_exposure": "6000",
                "max_symbol_exposure": "1500",
                "max_risk_per_order": "20",
                "min_cash_reserve": "4000",
                "allow_fractional_shares": False,
                "allow_short_selling": True,
                "allow_options": False,
                "allow_margin_financing": False,
                "minimum_net_profit_after_fees": "5",
                "normal_minimum_net_profit_after_fees": "8",
                "minimum_reward_r": "1.5",
                "runtime_minimum_net_profit_after_fees": {SHORT_RUNTIME: "12"},
                "runtime_minimum_reward_r": {SHORT_RUNTIME: "2"},
            },
            "virtual_capital_buckets": {
                "pa002_5m_short": {
                    "label": "PA002-5m做空测试仓（M10-PA-002-5m）",
                    "position_direction": "short",
                    "equity": "10000",
                    "max_total_exposure": "2000",
                    "max_symbol_exposure": "500",
                    "max_risk_per_order": "10",
                    "min_cash_reserve": "8000",
                    "runtime_ids": [SHORT_RUNTIME],
                }
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_order_source": False,
                "short_selling": True,
            },
        }
        path = root / "execution.json"
        self.write_json(path, payload)
        return load_execution_config(path)

    def make_account_state_config(self, root: Path):
        path = root / "account_state_config.json"
        self.write_json(
            path,
            {
                "stage": "M15.longbridge_realtime_account_state",
                "outputs": {"output_dir": str(root / "out")},
                "longbridge_account_state": {"required_account_channel": "lb_papertrading"},
                "hard_boundaries": {
                    "paper_simulated_only": True,
                    "live_execution": False,
                    "real_money_actions": False,
                    "local_simulation_as_account_source": False,
                    "order_submit_or_cancel_commands": False,
                },
            },
        )
        return load_account_state_config(path)

    def make_position_manager_config(self, root: Path):
        path = root / "position_manager.json"
        self.write_json(
            path,
            {
                "stage": "M15.longbridge_realtime_position_manager",
                "inputs": {
                    "account_state": str(root / "account_state.json"),
                    "market_events": str(root / "market_events.jsonl"),
                    "realtime_signal_events": str(root / "signals.jsonl"),
                    "realtime_execution_ledger": str(root / "execution_ledger.jsonl"),
                },
                "outputs": {"output_dir": str(root / "position_out")},
                "longbridge_position_manager": {
                    "max_exit_events_per_run": 10,
                    "paper_short_testing": {
                        "enabled": True,
                        "test_epoch_id": SHORT_EPOCH,
                        "runtime_ids": [SHORT_RUNTIME],
                    },
                },
                "hard_boundaries": {
                    "paper_simulated_only": True,
                    "live_execution": False,
                    "real_money_actions": False,
                    "local_simulation_as_exit_source": False,
                    "short_selling": True,
                },
            },
        )
        return load_position_manager_config(path)

    def short_signal(self, **overrides: object) -> dict:
        row = {
            "signal_id": "short-signal",
            "created_at": "2026-07-13T15:05:00Z",
            "runtime_id": SHORT_RUNTIME,
            "strategy_id": "M10-PA-002",
            "capital_bucket": "pa002_5m_short",
            "test_epoch_id": SHORT_EPOCH,
            "symbol": "AAPL",
            "timeframe": "5m",
            "direction": "short",
            "side": "sell_short",
            "position_action": "open_short",
            "order_type": "limit",
            "limit_price": "100.00",
            "stop_price": "101.00",
            "target_price": "98.00",
            "current_price": "100.00",
            "quantity": "4",
            "quality_score": "90",
            "minimum_quality_score": "85",
            "net_profit_after_fees_at_target": "15.00",
            "source_market_event_id": "short-bar-1",
            "short_structure_low": "99.50",
        }
        row.update(overrides)
        return row

    def short_ledger_row(
        self,
        signal_id: str,
        order_id: str,
        position_action: str,
        side: str,
        submitted_at: str,
        *,
        source_open_order_id: str = "",
    ) -> dict:
        return {
            "signal_id": signal_id,
            "submission_status": "submitted",
            "submitted_at": submitted_at,
            "runtime_id": SHORT_RUNTIME,
            "strategy_id": "M10-PA-002",
            "capital_bucket": "pa002_5m_short",
            "test_epoch_id": SHORT_EPOCH,
            "direction": "short",
            "position_action": position_action,
            "side": side,
            "symbol": "AAPL",
            "quantity": "2",
            "limit_price": "100" if position_action == "open_short" else "95",
            "order_id": order_id,
            "source_open_order_id": source_open_order_id,
        }

    def bar(self, event_id: str, event_time: str, close: str, high: str, low: str, previous_close: str, volume: str) -> dict:
        del previous_close
        return {
            "event_id": event_id,
            "event_time": event_time,
            "received_at": event_time,
            "close": close,
            "high": high,
            "low": low,
            "volume": volume,
        }

    def write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def read_jsonl(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
