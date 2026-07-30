from __future__ import annotations

import json
import ast
import inspect
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.m15_longbridge_sdk_analytics_lib import (
    app_intraday_window_start,
    build_app_display_metrics,
    current_history_rows,
    incremental_history_start,
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
                    "source": "longbridge_sdk_asset_page_formula_positions_executions_extended_quotes",
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
            self.assertEqual(summary["account_today_total_pnl"], "7.89")
            self.assertEqual(
                summary["account_today_total_pnl_source"],
                "longbridge_sdk_asset_page_formula_positions_executions_extended_quotes",
            )
            pnl = json.loads((output / "m15_longbridge_account_pnl_reconciliation.json").read_text())
            self.assertEqual(pnl["today_account_pnl"]["symbol_pnl_rows"][0]["symbol"], "Apple.US")
            self.assertEqual(pnl["market_day_profit_analysis"]["sum_profit"], "-3.21")
            self.assertFalse(summary["order_submit_or_cancel_command_used"])


if __name__ == "__main__":
    unittest.main()
