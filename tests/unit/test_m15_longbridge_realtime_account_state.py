from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from scripts.m15_longbridge_realtime_account_state_lib import (
    ACCOUNT_STATE_JSON,
    CommandResult,
    EQUITY_CURVE_JSONL,
    LEDGER_JSONL,
    ORDER_RECONCILIATION_JSON,
    PNL_RECONCILIATION_JSON,
    PNL_RECONCILIATION_MD,
    REALTIME_EXECUTION_LEDGER_JSONL,
    SUMMARY_JSON,
    UNFILLED_ORDER_DIAGNOSTICS_JSON,
    assert_account_state_command,
    build_order_reconciliation,
    enrich_order_reconciliation_with_stale_cleanup,
    load_config,
    longbridge_account_pnl_market_date,
    parse_json,
    historical_order_history_refresh_due,
    preserve_previous_holding_prices_if_degraded,
    refresh_trusted_order_history,
    restore_historical_order_history_if_unavailable,
    run_realtime_account_state,
)


class M15LongbridgeRealtimeAccountStateTest(unittest.TestCase):
    def test_account_pnl_market_date_uses_new_york_trading_date_after_utc_midnight(self) -> None:
        self.assertEqual(
            longbridge_account_pnl_market_date(datetime(2026, 7, 7, 2, 15, tzinfo=UTC)),
            "2026-07-06",
        )
        self.assertEqual(
            longbridge_account_pnl_market_date(datetime(2026, 7, 7, 14, 0, tzinfo=UTC)),
            "2026-07-07",
        )

    def test_reads_paper_account_state_without_order_submit_or_local_simulation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            commands: list[list[str]] = []
            config.output_dir.mkdir(parents=True, exist_ok=True)
            (config.output_dir / REALTIME_EXECUTION_LEDGER_JSONL).write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "submission_status": "submitted",
                                "submitted_at": "2026-06-03T13:59:59Z",
                                "symbol": "AAPL",
                                "side": "buy",
                                "quantity": "1",
                                "limit_price": "100",
                                "capital_bucket": "main",
                                "runtime_id": "M10-PA-004-long-1d",
                                "test_epoch_id": "epoch-1",
                            }
                        ),
                        json.dumps(
                            {
                                "submission_status": "submitted",
                                "submitted_at": "2026-06-03T14:10:00Z",
                                "symbol": "XYZ",
                                "side": "buy",
                                "quantity": "1",
                                "limit_price": "10",
                                "capital_bucket": "experimental",
                                "runtime_id": "M10-PA-013-1d",
                                "test_epoch_id": "epoch-1",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = run_realtime_account_state(
                config,
                generated_at="2026-06-04T14:00:00Z",
                command_runner=self.runner(commands=commands),
            )
            account_state = json.loads((config.output_dir / ACCOUNT_STATE_JSON).read_text(encoding="utf-8"))
            reconciliation = json.loads((config.output_dir / PNL_RECONCILIATION_JSON).read_text(encoding="utf-8"))
            order_reconciliation = json.loads((config.output_dir / ORDER_RECONCILIATION_JSON).read_text(encoding="utf-8"))
            unfilled_diagnostics = json.loads((config.output_dir / UNFILLED_ORDER_DIAGNOSTICS_JSON).read_text(encoding="utf-8"))
            reconciliation_report = (config.output_dir / PNL_RECONCILIATION_MD).read_text(encoding="utf-8")
            ledger = self.read_jsonl(config.output_dir / LEDGER_JSONL)
            equity_curve = self.read_jsonl(config.output_dir / EQUITY_CURVE_JSONL)

            self.assertEqual(payload["account_status"], "paper_account_ready")
            self.assertTrue(account_state["paper_account_verified"])
            self.assertEqual(account_state["account_channel"], "lb_papertrading")
            self.assertEqual(account_state["buying_power"], "10000.00")
            self.assertEqual(account_state["account_total_equity_estimate"], "10200.00")
            self.assertEqual(account_state["account_total_equity_source"], "cash_plus_position_market_value")
            self.assertEqual(account_state["held_symbols"], ["AAPL"])
            self.assertEqual(account_state["position_notional_by_symbol"], {"AAPL": "200.00"})
            self.assertEqual(account_state["open_order_count"], 1)
            self.assertEqual(account_state["order_row_count"], 2)
            self.assertEqual(account_state["historical_order_row_count"], 4)
            self.assertEqual(account_state["historical_execution_count"], 2)
            self.assertEqual([row["order_id"] for row in account_state["orders"]], ["open-1", "filled-1"])
            self.assertEqual([row["order_id"] for row in account_state["historical_executions"]], ["hist-buy", "hist-sell"])
            self.assertEqual(account_state["open_order_notional_by_symbol"], {"MSFT": "300.00"})
            self.assertTrue(payload["local_simulation_isolated"])
            self.assertFalse(payload["order_submit_or_cancel_command_used"])
            self.assertEqual(ledger[0]["account_status"], "paper_account_ready")
            self.assertEqual(ledger[0]["account_total_equity_estimate"], "10200.00")
            self.assertEqual(equity_curve[0]["account_total_equity_estimate"], "10200.00")
            self.assertEqual(equity_curve[0]["position_market_value"], "200.00")
            self.assertEqual(equity_curve[0]["open_order_notional"], "300.00")
            self.assertTrue(payload["pnl_reconciliation_ok"])
            self.assertEqual(payload["account_total_pnl_estimate"], "15.50")
            self.assertEqual(payload["longbridge_stock_total_pnl"], "12.00")
            self.assertEqual(payload["app_display_today_pnl"], "等待长桥字段对齐")
            self.assertEqual(payload["net_asset_intraday_pnl"], "15.50")
            self.assertEqual(payload["account_today_total_pnl"], "15.50")
            self.assertEqual(reconciliation["account_pnl"]["ending_asset_value"], "10215.50")
            self.assertEqual(reconciliation["trading_pnl"]["stock_total_pnl"], "12.00")
            self.assertEqual(reconciliation["trading_pnl"]["current_position_unrealized_pnl"], "10.00")
            self.assertEqual(reconciliation["trading_pnl"]["realized_pnl_estimate"], "2.00")
            self.assertEqual(order_reconciliation["summary"]["longbridge_order_count"], 6)
            self.assertEqual(order_reconciliation["summary"]["local_submission_count"], 2)
            self.assertEqual(order_reconciliation["summary"]["filled_order_count"], 3)
            self.assertEqual(order_reconciliation["summary"]["unfilled_order_count"], 4)
            self.assertEqual(order_reconciliation["summary"]["local_submitted_no_longbridge_order_count"], 1)
            self.assertIn("sell_available_quantity_insufficient_or_occupied", order_reconciliation["summary"]["diagnostic_category_counts"])
            self.assertEqual(unfilled_diagnostics["summary"]["diagnostic_row_count"], 4)
            self.assertIn("local_unconfirmed_submission", unfilled_diagnostics["summary"]["diagnostic_category_counts"])
            self.assertIn("2026-06-04T14:00:00Z", reconciliation_report)
            self.assertIn("账户区间净值盈亏: `15.50` USD", reconciliation_report)
            self.assertIn("股票交易合并盈亏: `12.00` USD", reconciliation_report)
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

    def test_hot_refresh_reads_only_order_safety_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            commands: list[list[str]] = []

            payload = run_realtime_account_state(
                config,
                generated_at="2026-06-04T14:00:00Z",
                command_runner=self.runner(commands=commands),
                refresh_historical_order_history=False,
                refresh_analytics=False,
            )

            self.assertEqual(payload["analytics_refresh_status"], "deferred_to_background")
            self.assertEqual(payload["account_status"], "paper_account_ready")
            self.assertTrue(payload["paper_account_verified"])
            self.assertFalse(any("history" in command for command in commands))
            self.assertFalse(any(command[1:2] == ["portfolio"] for command in commands))
            self.assertFalse(any(command[1:2] == ["profit-analysis"] for command in commands))

    def test_command_guard_rejects_submit_or_cancel_shapes(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot submit or cancel"):
            assert_account_state_command(["longbridge", "order", "buy", "AAPL.US", "1", "--yes", "--format", "json"])
        with self.assertRaisesRegex(ValueError, "cannot submit or cancel"):
            assert_account_state_command(["longbridge", "order", "cancel", "123", "--format", "json"])
        assert_account_state_command(["longbridge", "profit-analysis", "by-market", "US", "--format", "json"])
        with self.assertRaisesRegex(ValueError, "cannot submit or cancel"):
            assert_account_state_command(["longbridge", "profit-analysis", "buy", "AAPL.US", "--format", "json"])

    def test_parse_json_tolerates_cli_update_notice_after_payload(self) -> None:
        payload = parse_json('{"ok": true}\\nNew version 0.23.1 is available')
        self.assertEqual(payload, {"ok": True})

    def test_preserves_previous_holding_prices_when_portfolio_snapshot_degrades(self) -> None:
        current = {
            "generated_at": "2026-07-01T12:00:00Z",
            "current_holdings": [
                {"symbol": "A.US", "quantity": "1", "cost_price": "10", "market_price": "10", "prev_close": None},
                {"symbol": "B.US", "quantity": "1", "cost_price": "20", "market_price": "20", "prev_close": None},
                {"symbol": "C.US", "quantity": "1", "cost_price": "30", "market_price": "30", "prev_close": None},
            ],
            "account_snapshot": {
                "portfolio_total_pl": "0",
                "portfolio_total_today_pl": "0",
                "app_like_market_value": "60",
                "app_like_total_asset": "10060",
            },
            "trading_pnl": {
                "stock_total_pnl": "100.00",
                "realized_pnl_estimate": "100.00",
                "current_position_unrealized_pnl": "0.00",
            },
            "source_status": {"portfolio_ok": True},
        }
        previous = {
            "generated_at": "2026-07-01T11:59:00Z",
            "current_holdings": [
                {"symbol": "A.US", "quantity": "1", "cost_price": "10", "market_price": "11", "prev_close": "10.5"},
                {"symbol": "B.US", "quantity": "1", "cost_price": "20", "market_price": "19", "prev_close": "20.5"},
                {"symbol": "C.US", "quantity": "1", "cost_price": "30", "market_price": "33", "prev_close": "31"},
            ],
            "account_snapshot": {
                "portfolio_total_pl": "3.00",
                "portfolio_total_today_pl": "1.50",
                "app_like_market_value": "63.00",
                "app_like_total_asset": "10063.00",
            },
            "trading_pnl": {
                "stock_total_pnl": "100.00",
                "realized_pnl_estimate": "97.00",
                "current_position_unrealized_pnl": "3.00",
            },
        }

        preserved = preserve_previous_holding_prices_if_degraded(current, previous)

        self.assertEqual(preserved["current_holdings"][0]["market_price"], "11")
        self.assertEqual(preserved["account_snapshot"]["portfolio_total_pl"], "3.00")
        self.assertEqual(preserved["account_snapshot"]["portfolio_total_today_pl"], "1.50")
        self.assertEqual(preserved["trading_pnl"]["current_position_unrealized_pnl"], "3.00")
        self.assertTrue(preserved["source_status"]["portfolio_price_snapshot_degraded"])
        self.assertTrue(preserved["source_status"]["holding_prices_restored_from_previous_reconciliation"])

    def test_preserves_previous_holding_prices_when_prev_close_is_zero_string(self) -> None:
        current = {
            "generated_at": "2026-07-01T12:00:00Z",
            "current_holdings": [
                {"symbol": "A.US", "quantity": "1", "cost_price": "10", "market_price": "10", "prev_close": "0"},
                {"symbol": "B.US", "quantity": "1", "cost_price": "20", "market_price": "20", "prev_close": "0.00"},
                {"symbol": "C.US", "quantity": "1", "cost_price": "30", "market_price": "30", "prev_close": "0"},
            ],
            "account_snapshot": {
                "portfolio_total_pl": "0",
                "portfolio_total_today_pl": "0",
                "app_like_market_value": "60",
                "app_like_total_asset": "10060",
            },
            "trading_pnl": {
                "stock_total_pnl": "100.00",
                "realized_pnl_estimate": "100.00",
                "current_position_unrealized_pnl": "0.00",
            },
            "source_status": {"portfolio_ok": True},
        }
        previous = {
            "generated_at": "2026-07-01T11:59:00Z",
            "current_holdings": [
                {"symbol": "A.US", "quantity": "1", "cost_price": "10", "market_price": "11", "prev_close": "10.5"},
                {"symbol": "B.US", "quantity": "1", "cost_price": "20", "market_price": "19", "prev_close": "20.5"},
                {"symbol": "C.US", "quantity": "1", "cost_price": "30", "market_price": "33", "prev_close": "31"},
            ],
            "account_snapshot": {
                "portfolio_total_pl": "3.00",
                "portfolio_total_today_pl": "1.50",
                "app_like_market_value": "63.00",
                "app_like_total_asset": "10063.00",
            },
            "trading_pnl": {
                "stock_total_pnl": "100.00",
                "realized_pnl_estimate": "97.00",
                "current_position_unrealized_pnl": "3.00",
            },
        }

        preserved = preserve_previous_holding_prices_if_degraded(current, previous)

        self.assertEqual(preserved["account_snapshot"]["portfolio_total_pl"], "3.00")
        self.assertEqual(preserved["trading_pnl"]["current_position_unrealized_pnl"], "3.00")
        self.assertTrue(preserved["source_status"]["portfolio_price_snapshot_degraded"])

    def test_marks_degraded_snapshot_when_no_trustworthy_previous_snapshot_exists(self) -> None:
        current = {
            "current_holdings": [
                {"symbol": "A.US", "quantity": "1", "cost_price": "10", "market_price": "10", "prev_close": None},
                {"symbol": "B.US", "quantity": "1", "cost_price": "20", "market_price": "20", "prev_close": None},
                {"symbol": "C.US", "quantity": "1", "cost_price": "30", "market_price": "30", "prev_close": None},
            ],
            "account_snapshot": {"portfolio_total_pl": "0", "portfolio_total_today_pl": "0"},
            "source_status": {},
        }

        preserved = preserve_previous_holding_prices_if_degraded(current, {})

        self.assertEqual(preserved["account_snapshot"]["portfolio_total_pl"], "0")
        self.assertTrue(preserved["source_status"]["portfolio_price_snapshot_degraded"])
        self.assertFalse(preserved["source_status"]["holding_price_snapshot_available"])
        self.assertNotIn("holding_prices_restored_from_previous_reconciliation", preserved["source_status"])

    def test_restores_historical_orders_from_cache_when_longbridge_history_read_fails(self) -> None:
        orders, executions = restore_historical_order_history_if_unavailable(
            {"ok": False, "json": {}, "stderr": "timed out"},
            {"ok": False, "json": {}, "stderr": "timed out"},
            {
                "generated_at": "2026-07-10T10:00:00Z",
                "historical_orders": [{"order_id": "o-1"}],
                "historical_executions": [{"order_id": "o-1", "trade_id": "t-1"}],
            },
        )

        self.assertFalse(orders["ok"])
        self.assertTrue(orders["cache_used"])
        self.assertEqual(orders["json"], [{"order_id": "o-1"}])
        self.assertTrue(executions["cache_used"])
        self.assertEqual(executions["cache_generated_at"], "2026-07-10T10:00:00Z")

    def test_uses_recent_historical_order_cache_without_requerying(self) -> None:
        self.assertFalse(
            historical_order_history_refresh_due(
                {
                    "generated_at": "2026-07-10T10:00:00Z",
                    "historical_orders": [],
                    "historical_executions": [],
                },
                datetime(2026, 7, 10, 10, 4, 59, tzinfo=UTC),
                300,
            )
        )

    def test_reading_order_history_cache_does_not_extend_cache_freshness(self) -> None:
        existing = {
            "generated_at": "2026-07-10T10:00:00Z",
            "historical_orders": [{"order_id": "o-1"}],
            "historical_executions": [{"order_id": "o-1", "trade_id": "t-1"}],
        }

        refreshed = refresh_trusted_order_history(
            existing,
            {"ok": True, "json": existing["historical_orders"], "cache_used": True},
            {"ok": True, "json": existing["historical_executions"], "cache_used": True},
            "2026-07-10T10:04:00Z",
        )

        self.assertEqual(refreshed, existing)

    def test_can_skip_historical_order_queries_for_realtime_execution_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            config.output_dir.mkdir(parents=True, exist_ok=True)
            (config.output_dir / "m15_longbridge_last_trustworthy_order_history.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-10T10:00:00Z",
                        "historical_orders": [{"order_id": "o-1", "status": "Filled"}],
                        "historical_executions": [{"order_id": "o-1", "trade_id": "t-1"}],
                    }
                ),
                encoding="utf-8",
            )
            commands: list[list[str]] = []

            run_realtime_account_state(
                config,
                generated_at="2026-07-10T10:10:00Z",
                command_runner=self.runner(commands=commands),
                refresh_historical_order_history=False,
            )

            self.assertFalse(any("--history" in command for command in commands))

    def test_order_reconciliation_includes_current_orders_missing_from_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            account_state = {
                "historical_orders": [],
                "orders": [
                    {
                        "order_id": "current-filled-1",
                        "symbol": "AMAT.US",
                        "side": "Buy",
                        "quantity": "1",
                        "price": "100.00",
                        "status": "Filled",
                        "executed_quantity": "1",
                        "executed_price": "100.00",
                        "created_at": "2026-07-01T19:23:52Z",
                    }
                ],
            }
            ledger = [
                {
                    "submission_status": "submitted",
                    "order_id": "current-filled-1",
                    "symbol": "AMAT",
                    "side": "buy",
                    "quantity": "1",
                    "limit_price": "100.00",
                    "capital_bucket": "main",
                    "runtime_id": "M10-PA-004-long-1d",
                    "test_epoch_id": "epoch-2",
                    "submitted_at": "2026-07-01T19:23:51Z",
                }
            ]

            reconciliation = build_order_reconciliation(
                config,
                "2026-07-02T02:00:00Z",
                account_state,
                ledger,
            )

            self.assertEqual(reconciliation["summary"]["longbridge_order_count"], 1)
            self.assertEqual(reconciliation["summary"]["filled_order_count"], 1)
            self.assertEqual(reconciliation["summary"]["local_submitted_no_longbridge_order_count"], 0)
            self.assertEqual(reconciliation["rows"][0]["attribution_status"], "matched_m15_realtime_ledger")
            self.assertTrue(reconciliation["rows"][0]["include_in_bucket_performance"])

    def test_stale_cleanup_ledger_explains_system_canceled_buy_orders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            reconciliation = build_order_reconciliation(
                config,
                "2026-07-02T02:00:00Z",
                {
                    "historical_orders": [
                        {
                            "order_id": "stale-buy-1",
                            "symbol": "META.US",
                            "side": "Buy",
                            "quantity": "1",
                            "price": "605.96",
                            "status": "Canceled",
                            "created_at": "2026-07-01T13:59:58Z",
                        }
                    ],
                    "orders": [],
                },
                [
                    {
                        "submission_status": "submitted",
                        "order_id": "stale-buy-1",
                        "symbol": "META",
                        "side": "buy",
                        "quantity": "1",
                        "limit_price": "605.96",
                        "capital_bucket": "main",
                        "runtime_id": "M10-PA-004-long-1d",
                        "submitted_at": "2026-07-01T13:59:58Z",
                    }
                ],
            )

            enriched = enrich_order_reconciliation_with_stale_cleanup(
                reconciliation,
                [
                    {
                        "order_id": "stale-buy-1",
                        "cleanup_status": "canceled",
                        "cleanup_reason": "current_session_buy_order_ttl_expired",
                        "age_seconds": "928",
                        "generated_at": "2026-07-01T14:15:26Z",
                    }
                ],
            )

            row = enriched["rows"][0]
            self.assertEqual(row["diagnostic_category"], "canceled_by_system_stale_buy_ttl")
            self.assertFalse(row["requires_future_tracking"])
            self.assertIn("928", row["diagnostic_evidence"])

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
                "historical_order_start_date": "2026-06-01",
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
            if args[:1] == ["portfolio"]:
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "overview": {
                                "total_asset": "10215.50",
                                "market_cap": "210.00",
                                "total_cash": "10005.50",
                                "total_pl": "10.00",
                                "total_today_pl": "1.25",
                                "currency": "USD",
                            },
                            "holdings": [
                                {
                                    "symbol": "AAPL.US",
                                    "quantity": "2",
                                    "cost_price": "100.00",
                                    "market_price": "105.00",
                                    "market_value": "210.00",
                                }
                            ],
                        }
                    )
                    + "\nNew version 0.23.1 is available",
                    "",
                )
            if args[:1] == ["profit-analysis"] and args[1:2] == ["by-market"]:
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "currency": "USD",
                            "start_date": "2026-06-01",
                            "end_date": "2026-06-04",
                            "profit": "12.00",
                            "stock_items": [
                                {"code": "AAPL", "name": "Apple", "profit": "12.00", "underlying_profit": "12.00"}
                            ],
                        }
                    ),
                    "",
                )
            if args[:1] == ["profit-analysis"]:
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "currency": "USD",
                            "initial_asset_value": "10200.00",
                            "ending_asset_value": "10215.50",
                            "current_total_asset": "10215.50",
                            "sum_profit": "15.50",
                            "sum_profit_rate": "0.00152",
                            "updated_date": "2026-06-04",
                            "trade_update_date": "2026-06-04",
                            "profits": {"stock": "12.00", "cumulative_transaction_amount": "500.00"},
                            "sublist": {
                                "items": [
                                    {
                                        "security_code": "AAPL",
                                        "name": "Apple",
                                        "profit": "12.00",
                                        "profit_rate": "0.012",
                                        "holding_value": "210.00",
                                        "invest_cost": "200.00",
                                        "is_holding": True,
                                    }
                                ]
                            },
                        }
                    ),
                    "",
                )
            if args[:2] == ["order", "executions"]:
                return CommandResult(
                    0,
                    json.dumps(
                        [
                            {"order_id": "hist-buy", "symbol": "AAPL.US", "quantity": "1", "price": "100", "side": "Buy", "time": "2026-06-03T14:00:00Z"},
                            {"order_id": "hist-sell", "symbol": "AAPL.US", "quantity": "1", "price": "105", "side": "Sell", "time": "2026-06-03T14:05:00Z"},
                        ]
                    ),
                    "",
                )
            if args[:2] == ["order", "detail"]:
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "order_id": args[2],
                            "symbol": "GOOG.US",
                            "quantity": "1",
                            "price": "110",
                            "side": "Sell",
                            "status": "Rejected",
                            "remark": "Insufficient holdings, please check if there are pending orders occupying available positions",
                            "executed_quantity": "0",
                            "executed_price": "-",
                            "history": [
                                {
                                    "msg": "Insufficient holdings, please check if there are pending orders occupying available positions",
                                    "status": "Rejected",
                                }
                            ],
                        }
                    ),
                    "",
                )
            if args[:1] == ["order"] and "--history" in args:
                return CommandResult(
                    0,
                    json.dumps(
                        [
                            {"order_id": "hist-open", "symbol": "MSFT.US", "side": "Buy", "quantity": "3", "price": "100", "status": "Submitted"},
                            {"order_id": "hist-buy", "symbol": "AAPL.US", "side": "Buy", "quantity": "1", "price": "100", "status": "Filled"},
                            {"order_id": "hist-sell", "symbol": "AAPL.US", "side": "Sell", "quantity": "1", "price": "105", "status": "Filled"},
                            {"order_id": "hist-rejected", "symbol": "GOOG.US", "side": "Buy", "quantity": "1", "price": "110", "status": "Rejected"},
                        ]
                    ),
                    "",
                )
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
