from __future__ import annotations

import json
import ast
import inspect
import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.m15_longbridge_sdk_analytics_lib import (
    APP_DAILY_PNL_METRIC_ID,
    TRUSTED_ORDER_HISTORY_JSON,
    is_sdk_timeout_error,
    app_intraday_window_start,
    build_app_display_metrics,
    build_sdk_account_summary,
    build_sdk_pnl_reconciliation,
    current_history_rows,
    incremental_history_start,
    load_previous_session_closes,
    load_runtime_quote_rows,
    market_profit_query_dates,
    merge_history_rows,
    normalize_order,
    read_with_timeout_recovery,
    run_sdk_analytics,
    refresh_order_and_execution_history,
    require_fresh_paper_account,
    require_live_sdk_runtime,
    write_sdk_analytics_outputs,
)


class M15LongbridgeSdkAnalyticsTest(unittest.TestCase):
    def test_pnl_reconciliation_keeps_account_asset_and_us_profit_currencies_separate(self) -> None:
        result = build_sdk_pnl_reconciliation(
            "2026-08-12T12:00:00Z",
            {
                "account_total_equity_estimate": "704835.23",
                "account_total_equity_currency": "HKD",
                "positions": [],
            },
            {"profit": "-1757.73", "stock_items": []},
            "2026-06-01",
            "2026-08-12",
        )

        account_pnl = result["account_pnl"]
        self.assertEqual(account_pnl["current_total_asset"], "704835.23")
        self.assertEqual(account_pnl["current_total_asset_currency"], "HKD")
        self.assertEqual(account_pnl["currency"], "HKD")
        self.assertEqual(account_pnl["sum_profit"], "-1757.73")
        self.assertEqual(account_pnl["sum_profit_currency"], "USD")

    def test_sdk_connect_error_is_treated_as_slow_statistics_failure(self) -> None:
        self.assertTrue(
            is_sdk_timeout_error(
                RuntimeError(
                    "error sending request for url (https://example): client error (Connect)"
                )
            )
        )

    def test_market_profit_analysis_never_replaces_app_daily_pnl(self) -> None:
        summary = build_sdk_account_summary(
            "2026-08-07T20:00:00Z",
            {
                "paper_account_verified": True,
                "account_channel": "lb_papertrading",
                "account_total_equity_estimate": "709967.81",
                "account_total_equity_currency": "HKD",
                "account_total_equity_source": "longbridge_sdk_account_balance.net_assets",
            },
            {},
            daily_profit_analysis={"profit": "63.12"},
            app_display_metrics={
                "status": "incomplete",
                "metric_contract_id": APP_DAILY_PNL_METRIC_ID,
                "today_pnl": "",
                "source": "longbridge_sdk_app_daily_pnl_inputs_incomplete",
            },
        )

        self.assertEqual(summary["account_today_total_pnl"], "暂不可计算")
        self.assertEqual(
            summary["account_today_total_pnl_metric_id"],
            APP_DAILY_PNL_METRIC_ID,
        )
        self.assertEqual(summary["market_day_profit_analysis"], "63.12")

    def test_incomplete_app_metrics_keep_sdk_equity_currency_and_source_together(self) -> None:
        summary = build_sdk_account_summary(
            "2026-08-07T02:00:00Z",
            {
                "paper_account_verified": True,
                "account_channel": "lb_papertrading",
                "account_buying_power": "1000",
                "cash": "500",
                "account_total_equity_estimate": "709274.95",
                "account_total_equity_currency": "HKD",
                "account_total_equity_source": "longbridge_sdk_account_balance.net_assets",
                "position_row_count": 0,
                "open_order_count": 0,
                "held_symbols": [],
            },
            {},
            app_display_metrics={
                "status": "incomplete",
                "currency": "USD",
                "total_asset": "",
                "total_cash": "500",
                "source": "longbridge_sdk_app_daily_pnl_inputs_incomplete",
            },
        )

        self.assertEqual(summary["account_total_equity_estimate"], "709274.95")
        self.assertEqual(summary["account_total_equity_currency"], "HKD")
        self.assertEqual(
            summary["account_total_equity_source"],
            "longbridge_sdk_account_balance.net_assets",
        )

    def test_background_analytics_never_creates_a_second_quote_context(self) -> None:
        tree = ast.parse(inspect.getsource(run_sdk_analytics))
        quote_context_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "QuoteContext"
        ]
        self.assertEqual(quote_context_calls, [])

    def test_cached_history_queries_two_day_overlap_and_applies_late_status_update(self) -> None:
        calls = []

        class Trade:
            def history_orders(self, *, start_at, end_at):
                calls.append(("orders", start_at, end_at))
                return [SimpleNamespace(order_id="1", status="Filled", side="Buy", order_type="LO")]

            def history_executions(self, *, start_at, end_at):
                calls.append(("executions", start_at, end_at))
                return [SimpleNamespace(trade_id="t1", order_id="1", quantity="1", price="10")]

        generated_at = datetime(2026, 7, 21, 9, 0, tzinfo=UTC)
        trade = Trade()
        orders, executions, returned_trade, mode = refresh_order_and_execution_history(
            trade,
            lambda: self.fail("healthy incremental query must not rebuild context"),
            start_at=datetime(2026, 6, 1, tzinfo=UTC),
            generated_at=generated_at,
            cached_orders=[{"order_id": "1", "status": "Submitted"}],
            cached_executions=[],
            account_state={"orders": [], "executions": []},
        )

        self.assertIs(returned_trade, trade)
        self.assertEqual(orders[0]["status"], "Filled")
        self.assertEqual(executions[0]["trade_id"], "t1")
        self.assertEqual(mode, "trusted_cache_plus_two_day_sdk_incremental_and_fresh_snapshot")
        self.assertEqual({call[1] for call in calls}, {datetime(2026, 7, 19, 9, 0, tzinfo=UTC)})

    def test_incremental_history_uses_two_day_overlap_after_cache_exists(self) -> None:
        full_start = datetime(2026, 6, 1, tzinfo=UTC)
        generated_at = datetime(2026, 7, 21, 9, 0, tzinfo=UTC)
        self.assertEqual(
            incremental_history_start(full_start, generated_at, cached_row_count=963),
            datetime(2026, 7, 19, 9, 0, tzinfo=UTC),
        )
        self.assertEqual(
            incremental_history_start(full_start, generated_at, cached_row_count=0),
            full_start,
        )

    def test_incremental_history_replaces_cached_order_with_recent_status(self) -> None:
        rows = merge_history_rows(
            [{"order_id": "1", "status": "Submitted"}, {"order_id": "2", "status": "Filled"}],
            [{"order_id": "1", "status": "Filled"}],
            identity_field="order_id",
        )
        self.assertEqual({row["order_id"]: row["status"] for row in rows}, {"1": "Filled", "2": "Filled"})

    def test_fresh_account_snapshot_updates_trusted_history_without_history_scan(self) -> None:
        rows = current_history_rows(
            [{"order_id": "1", "status": "Submitted"}, {"order_id": "2", "status": "Filled"}],
            [SimpleNamespace(order_id="1", status="Filled", side="Buy", order_type="LO")],
            identity_field="order_id",
            normalizer=normalize_order,
        )
        by_id = {row["order_id"]: row for row in rows}
        self.assertEqual(by_id["1"]["status"], "Filled")
        self.assertEqual(by_id["2"]["status"], "Filled")

    def test_incremental_history_timeout_falls_back_to_trusted_cache_and_marks_stale(self) -> None:
        class Trade:
            def history_orders(self, *, start_at, end_at):
                raise RuntimeError("request timeout")

            def history_executions(self, *, start_at, end_at):
                return [SimpleNamespace(trade_id="t1", order_id="1", quantity="1", price="10")]

        generated_at = datetime(2026, 7, 21, 9, 0, tzinfo=UTC)
        orders, executions, returned_trade, mode = refresh_order_and_execution_history(
            Trade(),
            lambda: Trade(),
            start_at=datetime(2026, 6, 1, tzinfo=UTC),
            generated_at=generated_at,
            cached_orders=[{"order_id": "1", "status": "Submitted"}],
            cached_executions=[],
            account_state={
                "orders": [SimpleNamespace(order_id="1", status="Filled", side="Buy", order_type="LO")],
                "executions": [],
            },
        )

        self.assertIsNotNone(returned_trade)
        self.assertEqual({row["order_id"]: row["status"] for row in orders}, {"1": "Filled"})
        self.assertEqual(executions[0]["trade_id"], "t1")
        self.assertEqual(
            mode,
            "trusted_cache_plus_fresh_snapshot_statistics_stale_history_orders_timeout",
        )

    def test_app_display_pnl_matches_longbridge_asset_formula(self) -> None:
        generated_at = datetime(2026, 7, 21, 3, 15, tzinfo=UTC)
        metrics = build_app_display_metrics(
            generated_at,
            {
                "usd_available_cash": "88073.95",
                "usd_frozen_cash": "180.39",
                "positions": [{"symbol": "AAPL.US", "quantity": "2"}],
            },
            [{"order_id": "buy-1", "symbol": "AAPL.US", "side": "Buy"}],
            [{"order_id": "buy-1", "symbol": "AAPL.US", "quantity": "2", "price": "100", "trade_done_at": "2026-07-20T14:00:00Z"}],
            [{"symbol": "AAPL.US", "current_price": "110", "prev_close": "90", "price_phase": "post_market"}],
        )
        self.assertEqual(metrics["today_pnl"], "20.00")
        self.assertEqual(metrics["total_cash"], "88254.34")
        self.assertEqual(metrics["market_value"], "220.00")
        self.assertEqual(metrics["total_asset"], "88474.34")
        self.assertEqual(metrics["metric_contract_id"], APP_DAILY_PNL_METRIC_ID)
        self.assertEqual(
            metrics["source"],
            "longbridge_sdk_app_asset_daily_pnl_formula_v1",
        )

    def test_round_trip_closed_today_without_quote_still_counts_in_app_pnl(self) -> None:
        generated_at = datetime(2026, 7, 21, 20, 0, tzinfo=UTC)
        metrics = build_app_display_metrics(
            generated_at,
            {
                "usd_available_cash": "1000",
                "usd_frozen_cash": "0",
                "positions": [],
            },
            [
                {"order_id": "buy-1", "symbol": "AAPL.US", "side": "Buy"},
                {"order_id": "sell-1", "symbol": "AAPL.US", "side": "Sell"},
            ],
            [
                {"order_id": "buy-1", "symbol": "AAPL.US", "quantity": "2", "price": "100", "trade_done_at": "2026-07-21T14:00:00Z"},
                {"order_id": "sell-1", "symbol": "AAPL.US", "quantity": "2", "price": "105", "trade_done_at": "2026-07-21T18:00:00Z"},
            ],
            [],
        )

        self.assertEqual(metrics["status"], "fresh")
        self.assertEqual(metrics["today_pnl"], "10.00")
        self.assertEqual(metrics["missing_symbols"], [])
        self.assertEqual(metrics["symbol_pnl_rows"][0]["price_phase"], "round_trip_closed_without_quote")

    def test_open_or_overnight_symbol_without_quote_stays_incomplete(self) -> None:
        generated_at = datetime(2026, 7, 21, 20, 0, tzinfo=UTC)
        metrics = build_app_display_metrics(
            generated_at,
            {
                "usd_available_cash": "1000",
                "usd_frozen_cash": "0",
                "positions": [{"symbol": "AAPL.US", "quantity": "2"}],
            },
            [{"order_id": "buy-1", "symbol": "AAPL.US", "side": "Buy"}],
            [
                {"order_id": "buy-1", "symbol": "AAPL.US", "quantity": "2", "price": "100", "trade_done_at": "2026-07-21T14:00:00Z"},
            ],
            [],
        )

        self.assertEqual(metrics["status"], "incomplete")
        self.assertEqual(metrics["today_pnl"], "")
        self.assertEqual(metrics["missing_symbols"], ["AAPL.US"])

    def test_runtime_quote_snapshot_supplies_app_formula_without_second_context(self) -> None:
        generated_at = datetime(2026, 7, 21, 15, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m15_longbridge_sdk_quote_snapshot.json").write_text(
                json.dumps(
                    {
                        "metric_contract_id": APP_DAILY_PNL_METRIC_ID,
                        "market_date": "2026-07-21",
                        "rows": [
                            {
                                "symbol": "AAPL.US",
                                "current_price": "210.5",
                                "prev_close": "205.0",
                                "received_at": "2026-07-21T14:59:50Z",
                                "price_phase": "regular",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rows = load_runtime_quote_rows(
                SimpleNamespace(output_dir=root),
                generated_at,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["prev_close"], "205.0")

    def test_fully_exited_symbol_uses_previous_sdk_session_close(self) -> None:
        generated_at = datetime(2026, 8, 21, 17, 0, tzinfo=UTC)
        metrics = build_app_display_metrics(
            generated_at,
            {"usd_available_cash": "1000", "usd_frozen_cash": "0", "positions": []},
            [{"order_id": "sell-1", "symbol": "DASH.US", "side": "Sell"}],
            [
                {
                    "order_id": "sell-1",
                    "symbol": "DASH.US",
                    "quantity": "2",
                    "price": "224.41",
                    "trade_done_at": "2026-08-21T14:45:03Z",
                }
            ],
            [],
            {"DASH.US": Decimal("222.42")},
        )

        self.assertEqual(metrics["status"], "fresh")
        self.assertEqual(metrics["today_pnl"], "3.98")
        self.assertEqual(metrics["missing_symbols"], [])
        self.assertEqual(
            metrics["symbol_pnl_rows"][0]["price_phase"],
            "previous_sdk_session_close_after_full_exit",
        )

    def test_previous_session_close_loader_uses_last_bar_of_latest_prior_day(self) -> None:
        generated_at = datetime(2026, 8, 21, 17, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                {
                    "timeframe": "5m",
                    "bar_final": True,
                    "event_time": "2026-08-20T19:55:00Z",
                    "symbol": "DASH",
                    "close": "222.10",
                },
                {
                    "timeframe": "5m",
                    "bar_final": True,
                    "event_time": "2026-08-20T20:00:00Z",
                    "symbol": "DASH",
                    "close": "222.42",
                },
                {
                    "timeframe": "5m",
                    "bar_final": True,
                    "event_time": "2026-08-21T14:45:00Z",
                    "symbol": "DASH",
                    "close": "224.54",
                },
            ]
            (root / "m15_realtime_market_events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            closes = load_previous_session_closes(
                SimpleNamespace(output_dir=root),
                generated_at,
            )

        self.assertEqual(closes, {"DASH.US": Decimal("222.42")})

    def test_runtime_quote_snapshot_rejects_stale_or_wrong_contract_data(self) -> None:
        generated_at = datetime(2026, 7, 21, 15, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "m15_longbridge_sdk_quote_snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "metric_contract_id": APP_DAILY_PNL_METRIC_ID,
                        "market_date": "2026-07-21",
                        "rows": [
                            {
                                "symbol": "AAPL.US",
                                "current_price": "210.5",
                                "prev_close": "205.0",
                                "received_at": "2026-07-21T14:58:00Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                load_runtime_quote_rows(SimpleNamespace(output_dir=root), generated_at),
                [],
            )
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
            payload["metric_contract_id"] = "wrong_metric"
            payload["rows"][0]["received_at"] = "2026-07-21T14:59:50Z"
            snapshot.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(
                load_runtime_quote_rows(SimpleNamespace(output_dir=root), generated_at),
                [],
            )

    def test_runtime_quote_snapshot_keeps_previous_session_after_midnight(self) -> None:
        generated_at = datetime(2026, 8, 11, 4, 16, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m15_longbridge_sdk_quote_snapshot.json").write_text(
                json.dumps(
                    {
                        "metric_contract_id": APP_DAILY_PNL_METRIC_ID,
                        "market_date": "2026-08-11",
                        "latest_quote_received_at": "2026-08-11T04:15:58Z",
                        "rows": [
                            {
                                "symbol": "AAPL.US",
                                "current_price": "210.5",
                                "prev_close": "205.0",
                                "source_event_at": "2026-08-10T20:00:00Z",
                                "received_at": "2026-08-11T04:15:58Z",
                                "price_phase": "regular",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            rows = load_runtime_quote_rows(
                SimpleNamespace(output_dir=root),
                generated_at,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["current_price"], "210.5")

    def test_app_window_uses_previous_new_york_0400_before_boundary(self) -> None:
        self.assertEqual(
            app_intraday_window_start(datetime(2026, 7, 21, 7, 0, tzinfo=UTC)),
            datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
        )

    def test_read_timeout_rebuilds_context_and_retries_once(self) -> None:
        calls = []

        def read(context):
            calls.append(context)
            if context == "old":
                raise RuntimeError("request timeout")
            return "ok"

        with patch("scripts.m15_longbridge_sdk_analytics_lib.time.sleep"):
            result, context = read_with_timeout_recovery("old", lambda: "new", read)

        self.assertEqual(result, "ok")
        self.assertEqual(context, "new")
        self.assertEqual(calls, ["old", "new"])

    def test_connect_timeout_rebuilds_context_and_retries_once(self) -> None:
        calls = []

        def read(context):
            calls.append(context)
            if context == "old":
                raise RuntimeError("OpenApiException: connect timeout")
            return "ok"

        with patch("scripts.m15_longbridge_sdk_analytics_lib.time.sleep"):
            result, context = read_with_timeout_recovery("old", lambda: "new", read)

        self.assertEqual(result, "ok")
        self.assertEqual(context, "new")
        self.assertEqual(calls, ["old", "new"])

    def test_read_non_timeout_error_is_not_retried(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "permission denied"):
            read_with_timeout_recovery(
                "old",
                lambda: self.fail("must not rebuild for non-timeout errors"),
                lambda _context: (_ for _ in ()).throw(RuntimeError("permission denied")),
            )

    def test_market_profit_query_uses_new_york_date_and_next_day_boundary(self) -> None:
        self.assertEqual(
            market_profit_query_dates(datetime(2026, 7, 21, 2, 0, tzinfo=UTC)),
            ("2026-07-20", "2026-07-21"),
        )

    def test_sdk_analytics_requires_live_fresh_matching_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "runtime.json"
            runtime_config = SimpleNamespace(
                runtime_status_path=status_path,
                heartbeat_interval_seconds=1,
            )
            status_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "runtime_engine": "sdk",
                        "sdk_connected": True,
                        "market_data_mode": "sdk_subscription",
                        "runtime_pid": __import__("os").getpid(),
                        "config_fingerprint": "expected",
                        "generated_at": "2026-07-18T05:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            with patch("scripts.m15_longbridge_sdk_analytics_lib.config_fingerprint", return_value="expected"):
                require_live_sdk_runtime(runtime_config, datetime(2026, 7, 18, 5, 0, 5, tzinfo=UTC))

    def test_sdk_analytics_rejects_dead_runtime_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "runtime.json"
            runtime_config = SimpleNamespace(runtime_status_path=status_path, heartbeat_interval_seconds=1)
            status_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "runtime_engine": "sdk",
                        "sdk_connected": True,
                        "market_data_mode": "sdk_subscription",
                        "runtime_pid": 999999999,
                        "config_fingerprint": "expected",
                        "generated_at": "2026-07-18T05:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            with patch("scripts.m15_longbridge_sdk_analytics_lib.config_fingerprint", return_value="expected"):
                with self.assertRaisesRegex(RuntimeError, "live_sdk_runtime"):
                    require_live_sdk_runtime(runtime_config, datetime(2026, 7, 18, 5, 0, 5, tzinfo=UTC))

    def test_sdk_analytics_rejects_snapshot_runtime_during_quote_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "runtime.json"
            runtime_config = SimpleNamespace(runtime_status_path=status_path, heartbeat_interval_seconds=1)
            status_path.write_text(
                json.dumps(
                    {
                        "status": "connecting",
                        "runtime_engine": "sdk",
                        "sdk_connected": False,
                        "runtime_pid": __import__("os").getpid(),
                        "config_fingerprint": "expected",
                        "generated_at": "2026-07-18T05:00:00Z",
                        "market_data_mode": "sdk_snapshot_poll",
                        "paper_simulated_only": True,
                        "real_money_actions": False,
                    }
                ),
                encoding="utf-8",
            )
            with patch("scripts.m15_longbridge_sdk_analytics_lib.config_fingerprint", return_value="expected"):
                with self.assertRaisesRegex(RuntimeError, "live_sdk_runtime"):
                    require_live_sdk_runtime(runtime_config, datetime(2026, 7, 18, 5, 0, 1, tzinfo=UTC))

    def test_sdk_analytics_accepts_validated_paper_snapshot_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "runtime.json"
            runtime_config = SimpleNamespace(
                runtime_status_path=status_path,
                heartbeat_interval_seconds=1,
            )
            status_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "runtime_engine": "sdk",
                        "sdk_connected": True,
                        "runtime_pid": __import__("os").getpid(),
                        "config_fingerprint": "expected",
                        "generated_at": "2026-07-18T05:00:00Z",
                        "market_data_mode": "sdk_snapshot_poll",
                        "market_data_fallback_validated": True,
                        "snapshot_poll_is_fast_and_complete": True,
                        "snapshot_poll_consecutive_failures": 0,
                        "paper_simulated_only": True,
                        "real_money_actions": False,
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "scripts.m15_longbridge_sdk_analytics_lib.config_fingerprint",
                return_value="expected",
            ):
                require_live_sdk_runtime(
                    runtime_config,
                    datetime(2026, 7, 18, 5, 0, 1, tzinfo=UTC),
                )

    def test_sdk_analytics_rejects_non_paper_snapshot_runtime_during_quote_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "runtime.json"
            runtime_config = SimpleNamespace(runtime_status_path=status_path, heartbeat_interval_seconds=1)
            status_path.write_text(
                json.dumps(
                    {
                        "status": "connecting",
                        "runtime_engine": "sdk",
                        "sdk_connected": False,
                        "runtime_pid": __import__("os").getpid(),
                        "config_fingerprint": "expected",
                        "generated_at": "2026-07-18T05:00:00Z",
                        "market_data_mode": "sdk_snapshot_poll",
                        "paper_simulated_only": False,
                        "real_money_actions": True,
                    }
                ),
                encoding="utf-8",
            )
            with patch("scripts.m15_longbridge_sdk_analytics_lib.config_fingerprint", return_value="expected"):
                with self.assertRaisesRegex(RuntimeError, "live_sdk_runtime"):
                    require_live_sdk_runtime(runtime_config, datetime(2026, 7, 18, 5, 0, 1, tzinfo=UTC))

    def test_sdk_analytics_rejects_stale_runtime_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "runtime.json"
            runtime_config = SimpleNamespace(runtime_status_path=status_path, heartbeat_interval_seconds=1)
            status_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "runtime_engine": "sdk",
                        "sdk_connected": True,
                        "market_data_mode": "sdk_subscription",
                        "runtime_pid": __import__("os").getpid(),
                        "config_fingerprint": "expected",
                        "generated_at": "2026-07-18T04:59:00Z",
                    }
                ),
                encoding="utf-8",
            )
            with patch("scripts.m15_longbridge_sdk_analytics_lib.config_fingerprint", return_value="expected"):
                with self.assertRaisesRegex(RuntimeError, "fresh_runtime_status"):
                    require_live_sdk_runtime(runtime_config, datetime(2026, 7, 18, 5, 0, 0, tzinfo=UTC))

    def test_sdk_analytics_rejects_runtime_config_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "runtime.json"
            runtime_config = SimpleNamespace(runtime_status_path=status_path, heartbeat_interval_seconds=1)
            status_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "runtime_engine": "sdk",
                        "sdk_connected": True,
                        "market_data_mode": "sdk_subscription",
                        "runtime_pid": __import__("os").getpid(),
                        "config_fingerprint": "old",
                        "generated_at": "2026-07-18T05:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            with patch("scripts.m15_longbridge_sdk_analytics_lib.config_fingerprint", return_value="expected"):
                with self.assertRaisesRegex(RuntimeError, "matching_runtime_config"):
                    require_live_sdk_runtime(runtime_config, datetime(2026, 7, 18, 5, 0, 1, tzinfo=UTC))
    def test_sdk_analytics_rejects_stale_account_snapshot(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "fresh_account_snapshot"):
            require_fresh_paper_account(
                {
                    "paper_account_verified": True,
                    "account_channel": "lb_papertrading",
                    "generated_at": "2026-07-18T04:59:00Z",
                },
                datetime(2026, 7, 18, 5, 0, 0, tzinfo=UTC),
            )

    def test_sdk_analytics_accepts_fresh_verified_paper_snapshot(self) -> None:
        require_fresh_paper_account(
            {
                "paper_account_verified": True,
                "account_channel": "lb_papertrading",
                "generated_at": "2026-07-18T04:59:30Z",
            },
            datetime(2026, 7, 18, 5, 0, 0, tzinfo=UTC),
        )

    def test_normalize_order_removes_sdk_enum_prefixes(self) -> None:
        row = normalize_order(
            type(
                "Order",
                (),
                {
                    "symbol": "AAPL.US",
                    "order_id": "1",
                    "side": "OrderSide.Buy",
                    "status": "OrderStatus.Filled",
                    "order_type": "OrderType.LO",
                    "quantity": "2",
                    "executed_quantity": "2",
                    "executed_price": "200",
                },
            )()
        )
        self.assertEqual(row["side"], "Buy")
        self.assertEqual(row["status"], "Filled")
        self.assertEqual(row["order_type"], "LO")

    def test_sdk_outputs_count_only_actual_longbridge_fills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "out"
            account_config = root / "account.json"
            account_config.write_text(
                json.dumps(
                    {
                        "stage": "M15.longbridge_realtime_account_state",
                        "outputs": {"output_dir": str(output), "account_state": str(output / "account_state.json")},
                        "longbridge_account_state": {
                            "required_account_channel": "lb_papertrading",
                            "historical_order_start_date": "2026-07-01",
                        },
                        "hard_boundaries": {
                            "paper_simulated_only": True,
                            "live_execution": False,
                            "real_money_actions": False,
                            "local_simulation_as_account_source": False,
                            "order_submit_or_cancel_commands": False,
                        },
                        "fault_day_registry_overrides": {
                            "2026-07-18": ["sdk_market_data_gap"]
                        },
                    }
                ),
                encoding="utf-8",
            )
            output.mkdir(parents=True)
            (output / "m15_longbridge_realtime_execution_ledger.jsonl").write_text(
                json.dumps(
                    {
                        "submission_status": "submitted",
                        "order_id": "filled-1",
                        "signal_id": "signal-1",
                        "runtime_id": "M10-PA-002-5m",
                        "strategy_id": "M10-PA-002",
                        "capital_bucket": "pa002",
                        "direction": "long",
                        "position_action": "open_long",
                        "side": "buy",
                        "symbol": "AAPL",
                        "quantity": "2",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (output / "m15_account_reconciliation_adjustments.json").write_text(
                json.dumps(
                    {
                        "approved": True,
                        "adjustments": [
                            {
                                "approved": True,
                                "adjustment_id": "manual-cleanup",
                                "symbol": "AAPL",
                                "open_order_ids": ["filled-1"],
                                "resolve_symbol_anomalies": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (output / "m15_sdk_formal_test_epoch.json").write_text(
                json.dumps(
                    {
                        "test_epoch_id": "m15-sdk-contract-v1-current",
                        "short_test_epoch_id": "m15-sdk-contract-v1-short-current",
                        "test_started_at": "2026-07-18T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            result = write_sdk_analytics_outputs(
                account_config_path=account_config,
                generated_at=datetime(2026, 7, 18, tzinfo=UTC),
                account_state={
                    "paper_account_verified": True,
                    "account_channel": "lb_papertrading",
                    "position_row_count": 0,
                    "open_order_count": 0,
                    "positions": [],
                    "orders": [],
                },
                historical_orders=[
                    {
                        "order_id": "filled-1",
                        "symbol": "AAPL.US",
                        "side": "Buy",
                        "status": "Filled",
                        "quantity": "2",
                        "executed_quantity": "2",
                        "executed_price": "200",
                    },
                    {
                        "order_id": "cancelled-1",
                        "symbol": "MSFT.US",
                        "side": "Buy",
                        "status": "Canceled",
                        "quantity": "1",
                        "executed_quantity": "0",
                    },
                ],
                historical_executions=[],
                profit_analysis={"profit": "12.34", "stock_items": []},
                daily_profit_analysis={
                    "profit": "-3.21",
                    "stock_items": [{"name": "Apple", "market": "US", "profit": "-3.21"}],
                },
                app_display_metrics={
                    "status": "fresh",
                    "currency": "USD",
                    "today_pnl": "7.89",
                    "total_cash": "1000.00",
                    "total_asset": "1200.00",
                    "source": "longbridge_sdk_app_asset_daily_pnl_formula_v1",
                    "symbol_pnl_rows": [{"symbol": "Apple.US", "today_pnl": "7.89"}],
                },
            )
            reconciliation = json.loads((output / "m15_longbridge_order_reconciliation.json").read_text())
            fill_attribution = json.loads((output / "m15_longbridge_fill_attribution_v2.json").read_text())
            summary = json.loads((output / "m15_longbridge_realtime_account_state_summary.json").read_text())
            self.assertEqual(result["filled_order_count"], 1)
            self.assertEqual(reconciliation["summary"]["unfilled_order_count"], 1)
            self.assertEqual(fill_attribution["schema_version"], "m15.longbridge-fill-attribution.v2")
            self.assertEqual(result["fill_attribution_anomaly_count"], 0)
            self.assertEqual(fill_attribution["summary"]["account_reconciliation_adjustment_count"], 1)
            self.assertEqual(fill_attribution["account_reconciliation_adjustments"][0]["status"], "applied")
            self.assertEqual(
                fill_attribution["fault_day_registry"]["2026-07-18"],
                ["sdk_market_data_gap"],
            )
            self.assertEqual(summary["account_today_total_pnl"], "7.89")
            self.assertEqual(
                summary["account_today_total_pnl_source"],
                "longbridge_sdk_app_asset_daily_pnl_formula_v1",
            )
            pnl = json.loads((output / "m15_longbridge_account_pnl_reconciliation.json").read_text())
            self.assertEqual(pnl["today_account_pnl"]["symbol_pnl_rows"][0]["symbol"], "Apple.US")
            self.assertEqual(pnl["market_day_profit_analysis"]["sum_profit"], "-3.21")
            self.assertFalse(summary["order_submit_or_cancel_command_used"])

    def test_sdk_outputs_mark_statistics_stale_when_history_refresh_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "out"
            account_config = root / "account.json"
            account_config.write_text(
                json.dumps(
                    {
                        "stage": "M15.longbridge_realtime_account_state",
                        "outputs": {"output_dir": str(output), "account_state": str(output / "account_state.json")},
                        "longbridge_account_state": {
                            "required_account_channel": "lb_papertrading",
                            "historical_order_start_date": "2026-07-01",
                        },
                        "hard_boundaries": {
                            "paper_simulated_only": True,
                            "live_execution": False,
                            "real_money_actions": False,
                            "local_simulation_as_account_source": False,
                            "order_submit_or_cancel_commands": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            output.mkdir(parents=True)
            (output / "m15_longbridge_realtime_execution_ledger.jsonl").write_text("", encoding="utf-8")
            (output / "m15_account_reconciliation_adjustments.json").write_text(
                json.dumps({"approved": True, "adjustments": []}),
                encoding="utf-8",
            )
            (output / "m15_sdk_formal_test_epoch.json").write_text(json.dumps({}), encoding="utf-8")

            result = write_sdk_analytics_outputs(
                account_config_path=account_config,
                generated_at=datetime(2026, 7, 18, tzinfo=UTC),
                account_state={
                    "paper_account_verified": True,
                    "account_channel": "lb_papertrading",
                    "position_row_count": 0,
                    "open_order_count": 0,
                    "positions": [],
                    "orders": [],
                },
                historical_orders=[],
                historical_executions=[],
                profit_analysis={"profit": "0", "stock_items": []},
                daily_profit_analysis={"profit": "0", "stock_items": []},
                app_display_metrics={
                    "status": "incomplete",
                    "currency": "USD",
                    "today_pnl": "",
                    "total_cash": "1000.00",
                    "total_asset": "",
                    "source": "longbridge_sdk_app_daily_pnl_inputs_incomplete",
                    "symbol_pnl_rows": [],
                },
                history_refresh_mode="trusted_cache_plus_fresh_snapshot_statistics_stale_history_orders_timeout",
                statistics_stale=True,
            )

            summary = json.loads((output / "m15_longbridge_realtime_account_state_summary.json").read_text())
            pnl = json.loads((output / "m15_longbridge_account_pnl_reconciliation.json").read_text())
            trusted_history = json.loads((output / TRUSTED_ORDER_HISTORY_JSON).read_text())
            self.assertTrue(result["statistics_stale"])
            self.assertTrue(summary["statistics_stale"])
            self.assertTrue(pnl["statistics_stale"])
            self.assertEqual(pnl["source_status"]["status"], "statistics_stale")
            self.assertTrue(trusted_history["statistics_stale"])
            self.assertIn("statistics_stale=true", summary["plain_language_result"])


if __name__ == "__main__":
    unittest.main()
