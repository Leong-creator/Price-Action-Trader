import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.m12_29_current_day_scan_dashboard_lib import (
    ACCOUNT_SPECS,
    DEFAULT_ACCOUNT_EQUITY,
    PA008_BROKER_RISK_CAP_SHADOW_ADAPTER_ID,
    PA008_BROKER_RISK_CAP_SHADOW_RUNTIME_VARIANT_ID,
    PA008_BROKER_RISK_CAP_SHADOW_VARIANT_ID,
    PA011_ORB_REBUILD_ADAPTER_ID,
    PA011_ORB_REBUILD_VARIANT_ID,
    PA012_ORB_QUALITY_RESCUE_ADAPTER_ID,
    PA012_TARGET_STOP_NORMALIZED_RESCUE_ADAPTER_ID,
    PA012_TARGET_STOP_NORMALIZED_RESCUE_RUNTIME_VARIANT_ID,
    PA012_TARGET_STOP_NORMALIZED_RESCUE_VARIANT_ID,
    PA004_MOMENTUM_QUALITY_RESCUE_ADAPTER_ID,
    PA004_MOMENTUM_QUALITY_RESCUE_VARIANT_ID,
    PA004_MOMENTUM_QUALITY_VARIANT_ID,
    PA004_MOMENTUM_VARIANT_ID,
    account_ledger_trading_date,
    advance_account_runtime,
    assert_no_forbidden_output,
    bootstrap_account_state,
    build_accountized_run_status,
    build_dashboard_data_freshness_warning,
    build_dashboard_html,
    build_dashboard_update_status,
    build_dedicated_bucket_runtime_review_rows,
    build_local_simulation_history_quality,
    build_extended_session_monitor,
    build_longbridge_paper_dashboard_view,
    build_quote_lookup,
    current_us_scan_date,
    filter_rescue_signal_rows,
    load_config,
    is_longbridge_non_degraded_freshness_notice,
    market_session_status,
    m15_apply_longbridge_reconciliation_to_account_pnl,
    m15_longbridge_closed_trade_quality_summary,
    m15_longbridge_equity_curve_summary,
    m15_longbridge_account_pnl_summary,
    m15_longbridge_reconciliation_fresh_for_account_state,
    m15_longbridge_strategy_trade_pnl_rows,
    m15_longbridge_strategy_quality_summary,
    m15_longbridge_symbol_pnl_rows,
    m15_longbridge_trade_quality_summary,
    m15_unfilled_order_diagnostic_rows,
    m15_longbridge_virtual_bucket_rows,
    m15_submission_counts_for_date,
    open_new_positions,
    pa011_orb_rebuild_signal,
    pa004_event_is_long,
    pa004_momentum_breakout_quality_signal,
    pa004_momentum_breakout_signal,
    rescue_signal_filter,
    read_jsonl,
    run_m12_29_current_day_scan_dashboard,
    write_jsonl,
    write_text_atomic,
)
from scripts.run_m12_29_current_day_scan_dashboard import validate_generated_at


class M1229CurrentDayScanDashboardTest(unittest.TestCase):
    def test_local_simulation_history_quality_uses_closed_local_ledger_by_lane(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            write_jsonl(
                output_dir / "m12_46_account_trade_ledger.jsonl",
                [
                    {
                        "event_type": "close",
                        "runtime_id": "M10-PA-004-long-1d",
                        "strategy_id": "M10-PA-004",
                        "timeframe": "1d",
                        "symbol": "AAPL",
                        "realized_pnl": "20.00",
                    },
                    {
                        "event_type": "close",
                        "runtime_id": "M10-PA-004-long-1d",
                        "strategy_id": "M10-PA-004",
                        "timeframe": "1d",
                        "symbol": "MSFT",
                        "realized_pnl": "-10.00",
                    },
                    {
                        "event_type": "close",
                        "runtime_id": "M10-PA-013-5m",
                        "strategy_id": "M10-PA-013",
                        "timeframe": "5m",
                        "symbol": "NVDA",
                        "realized_pnl": "6.00",
                    },
                    {
                        "event_type": "close",
                        "runtime_id": "M10-PA-013-5m",
                        "strategy_id": "M10-PA-013",
                        "timeframe": "5m",
                        "symbol": "TSLA",
                        "realized_pnl": "4.00",
                    },
                    {
                        "event_type": "close",
                        "runtime_id": "M10-PA-013-5m",
                        "strategy_id": "M10-PA-013",
                        "timeframe": "5m",
                        "symbol": "META",
                        "realized_pnl": "-5.00",
                    },
                    {
                        "event_type": "open",
                        "runtime_id": "M10-PA-013-5m",
                        "strategy_id": "M10-PA-013",
                        "timeframe": "5m",
                        "symbol": "META",
                        "realized_pnl": "999.00",
                    },
                ],
            )
            config = SimpleNamespace(output_dir=output_dir)

            quality = build_local_simulation_history_quality(
                config,
                [
                    {"runtime_id": "M10-PA-004-long-1d", "strategy_id": "M10-PA-004", "timeframe": "1d", "lane": "mainline"},
                    {"runtime_id": "M10-PA-013-5m", "strategy_id": "M10-PA-013", "timeframe": "5m", "lane": "experimental"},
                ],
            )

        self.assertEqual(quality["overall"]["closed_trade_count"], "5")
        self.assertEqual(quality["overall"]["net_realized_pnl"], "15.00")
        self.assertEqual(quality["overall"]["profit_loss_ratio"], "1.33")
        self.assertEqual(quality["overall"]["profit_factor"], "2.00")
        by_lane = {row["lane"]: row for row in quality["lane_rows"]}
        self.assertEqual(by_lane["mainline"]["profit_loss_ratio"], "2.00")
        self.assertEqual(by_lane["experimental"]["profit_loss_ratio"], "1.00")
        by_timeframe = {row["timeframe"]: row for row in quality["timeframe_rows"]}
        self.assertEqual(by_timeframe["1d"]["net_realized_pnl"], "10.00")
        self.assertEqual(by_timeframe["5m"]["net_realized_pnl"], "5.00")

    def test_longbridge_account_pnl_summary_uses_reconciliation_when_available(self):
        summary = m15_longbridge_account_pnl_summary(
            {"cash": "97736.61", "buying_power": "100596.16", "total_open_order_notional": "0.00"},
            {"position_market_value": "4622.27", "position_cost_value": "4672.27", "total_unrealized_pnl": "-50.00"},
            "10000",
        )
        m15_apply_longbridge_reconciliation_to_account_pnl(
            summary,
            {
                "query_range": {"start": "2026-06-01", "end": "2026-06-08"},
                "account_pnl": {
                    "initial_asset_value": "102524.64",
                    "ending_asset_value": "102358.88",
                    "sum_profit": "-165.76",
                    "sum_profit_percent": "-0.16",
                },
                "trading_pnl": {
                    "stock_total_pnl": "-154.18",
                    "realized_pnl_estimate": "-104.18",
                    "current_position_unrealized_pnl": "-50.00",
                },
                "account_snapshot": {
                    "portfolio_total_cash": "97736.61",
                    "portfolio_market_cap": "4622.27",
                    "portfolio_total_today_pl": "12.34",
                },
            },
        )

        self.assertEqual(summary["account_total_equity_estimate"], "102358.88")
        self.assertEqual(summary["account_total_pnl_estimate"], "-165.76")
        self.assertEqual(summary["account_total_return_percent"], "-0.16")
        self.assertEqual(summary["longbridge_stock_total_pnl"], "-154.18")
        self.assertEqual(summary["longbridge_realized_pnl_estimate"], "-104.18")
        self.assertEqual(summary["longbridge_unrealized_pnl"], "-50.00")
        self.assertEqual(summary["longbridge_today_total_pnl"], "12.34")
        self.assertIn("profit-analysis", summary["account_total_pnl_note"])

    def test_longbridge_reconciliation_must_not_be_older_than_account_state(self):
        stale_reconciliation = {"generated_at": "2026-06-08T03:32:43Z", "pnl_reconciliation_ok": True}
        fresh_reconciliation = {"generated_at": "2026-06-12T20:00:00Z", "pnl_reconciliation_ok": True}
        account_state = {"generated_at": "2026-06-12T19:59:50Z"}

        self.assertFalse(
            m15_longbridge_reconciliation_fresh_for_account_state(stale_reconciliation, account_state)
        )
        self.assertTrue(
            m15_longbridge_reconciliation_fresh_for_account_state(fresh_reconciliation, account_state)
        )

    def test_longbridge_symbol_and_strategy_pnl_rows_use_reconciliation(self):
        symbol_rows = m15_longbridge_symbol_pnl_rows(
            {
                "symbol_pnl_rows": [
                    {
                        "security_code": "TSLA",
                        "name": "特斯拉",
                        "profit": "-36.43",
                        "profit_rate": "-0.0431",
                        "holding_value": "391",
                        "invest_cost": "845.32",
                        "realized_cash": "417.89",
                        "is_holding": False,
                    },
                    {
                        "security_code": "NVDA",
                        "name": "英伟达",
                        "profit": "12.50",
                        "profit_rate": "0.0125",
                        "holding_value": "500",
                        "invest_cost": "487.50",
                        "is_holding": True,
                    },
                ]
            }
        )
        strategy_rows = m15_longbridge_strategy_trade_pnl_rows(
            {
                "rows": [
                    {
                        "counts_for_performance": True,
                        "attribution_status": "matched_m15_realtime_ledger",
                        "side": "buy",
                        "symbol": "TSLA",
                        "runtime_id": "M10-PA-004-long-1d",
                    },
                    {
                        "counts_for_performance": True,
                        "attribution_status": "matched_m15_realtime_ledger",
                        "side": "buy",
                        "symbol": "NVDA",
                        "runtime_id": "M10-PA-013-1d",
                    },
                    {
                        "counts_for_performance": False,
                        "attribution_status": "matched_m15_realtime_ledger",
                        "side": "buy",
                        "symbol": "TSLA",
                        "runtime_id": "M10-PA-001-1d",
                    },
                ]
            },
            symbol_rows,
        )

        self.assertEqual(symbol_rows[0]["symbol"], "TSLA")
        self.assertEqual(symbol_rows[0]["profit"], "-36.43")
        by_runtime = {row["runtime_id"]: row for row in strategy_rows}
        self.assertEqual(by_runtime["M10-PA-004-long-1d"]["trade_pnl"], "-36.43")
        self.assertIn("实际成交", by_runtime["M10-PA-004-long-1d"]["attribution_note"])
        self.assertEqual(by_runtime["M10-PA-013-1d"]["trade_pnl"], "12.50")
        self.assertNotIn("M10-PA-001-1d", by_runtime)

    def test_longbridge_trade_quality_summary_uses_symbol_pnl_rows(self):
        symbol_rows = m15_longbridge_symbol_pnl_rows(
            {
                "symbol_pnl_rows": [
                    {
                        "security_code": "TSLA",
                        "profit": "-36.43",
                        "profit_rate": "-0.0431",
                    },
                    {
                        "security_code": "NVDA",
                        "profit": "12.50",
                        "profit_rate": "0.0125",
                    },
                    {
                        "security_code": "MSFT",
                        "profit": "0",
                        "profit_rate": "0",
                    },
                ]
            }
        )

        summary = m15_longbridge_trade_quality_summary(symbol_rows)

        self.assertEqual(summary["win_rate_percent"], "50.00")
        self.assertEqual(summary["win_rate_label"], "50.00%")
        self.assertEqual(summary["win_count"], "1")
        self.assertEqual(summary["loss_count"], "1")
        self.assertEqual(summary["flat_count"], "1")
        self.assertEqual(summary["average_win"], "12.50")
        self.assertEqual(summary["average_loss"], "36.43")
        self.assertEqual(summary["profit_loss_ratio"], "0.34")
        self.assertEqual(summary["worst_symbol"], "TSLA")
        self.assertEqual(summary["worst_symbol_loss_percent"], "-4.31")
        self.assertIn("逐标的盈亏", summary["source_note"])
        self.assertIn("最大回撤只看长桥账户权益曲线", summary["worst_symbol_loss_note"])

    def test_longbridge_equity_curve_summary_computes_full_max_drawdown(self):
        summary = m15_longbridge_equity_curve_summary(
            [
                {"generated_at": "2026-06-04T14:00:00Z", "account_total_equity_estimate": "10000.00"},
                {"generated_at": "2026-06-04T15:00:00Z", "account_total_equity_estimate": "10500.00"},
                {"generated_at": "2026-06-04T16:00:00Z", "account_total_equity_estimate": "9450.00"},
                {"generated_at": "2026-06-04T17:00:00Z", "account_total_equity_estimate": "9800.00"},
            ]
        )

        self.assertEqual(summary["snapshot_count"], "4")
        self.assertEqual(summary["max_drawdown_percent"], "10.00")
        self.assertEqual(summary["max_drawdown_label"], "10.00%")
        self.assertEqual(summary["peak_at"], "2026-06-04T15:00:00Z")
        self.assertEqual(summary["trough_at"], "2026-06-04T16:00:00Z")

    def test_longbridge_closed_trade_quality_summary_pairs_filled_orders(self):
        summary = m15_longbridge_closed_trade_quality_summary(
            {
                "orders": [
                    {"created_at": "2026-06-04T13:00:00Z", "status": "Filled", "side": "Buy", "symbol": "IGNORED.US", "executed_quantity": "1", "executed_price": "10"},
                    {"created_at": "2026-06-04T13:05:00Z", "status": "Filled", "side": "Sell", "symbol": "IGNORED.US", "executed_quantity": "1", "executed_price": "9"},
                ],
                "historical_executions": [
                    {"created_at": "2026-06-04T14:00:00Z", "status": "Filled", "side": "Buy", "symbol": "AAPL.US", "executed_quantity": "1", "executed_price": "100"},
                    {"created_at": "2026-06-04T14:05:00Z", "status": "Filled", "side": "Sell", "symbol": "AAPL.US", "executed_quantity": "1", "executed_price": "105"},
                    {"created_at": "2026-06-04T14:10:00Z", "status": "Filled", "side": "Buy", "symbol": "MSFT.US", "executed_quantity": "2", "executed_price": "50"},
                    {"created_at": "2026-06-04T14:15:00Z", "status": "Filled", "side": "Sell", "symbol": "MSFT.US", "executed_quantity": "2", "executed_price": "49"},
                    {"created_at": "2026-06-04T14:20:00Z", "status": "Filled", "side": "Sell", "symbol": "TSLA.US", "executed_quantity": "1", "executed_price": "300"},
                ]
            }
        )

        self.assertEqual(summary["win_rate_label"], "50.00%")
        self.assertEqual(summary["win_count"], "1")
        self.assertEqual(summary["loss_count"], "1")
        self.assertEqual(summary["sample_count"], "2")
        self.assertEqual(summary["unmatched_sell_count"], "1")
        self.assertEqual(summary["total_pnl"], "3.00")
        self.assertIn("历史成交明细", summary["source_note"])
        self.assertIn("不读取本地模拟账本", summary["source_note"])

    def test_longbridge_strategy_quality_summary_uses_longbridge_executions_and_submission_ledger(self):
        summary = m15_longbridge_strategy_quality_summary(
            {
                "historical_executions": [
                    {"time": "2026-06-08T14:00:00Z", "side": "buy", "symbol": "AAPL.US", "quantity": "1", "price": "100"},
                    {"time": "2026-06-08T14:05:00Z", "side": "sell", "symbol": "AAPL.US", "quantity": "1", "price": "96"},
                    {"time": "2026-06-09T03:20:00Z", "side": "buy", "symbol": "MSFT.US", "quantity": "1", "price": "200"},
                    {"time": "2026-06-09T03:25:00Z", "side": "sell", "symbol": "MSFT.US", "quantity": "1", "price": "212"},
                ]
            },
            [
                {
                    "submission_status": "submitted",
                    "submitted_at": "2026-06-08T13:59:30Z",
                    "runtime_id": "M10-PA-004-long-1d",
                    "strategy_id": "M10-PA-004",
                    "side": "buy",
                    "symbol": "AAPL",
                    "quantity": "1",
                },
                {
                    "submission_status": "submitted",
                    "submitted_at": "2026-06-08T14:04:30Z",
                    "runtime_id": "M10-PA-004-long-1d",
                    "strategy_id": "M10-PA-004",
                    "side": "sell",
                    "symbol": "AAPL",
                    "quantity": "1",
                },
                {
                    "submission_status": "submitted",
                    "submitted_at": "2026-06-09T03:19:30Z",
                    "runtime_id": "M10-PA-001-1d",
                    "strategy_id": "M10-PA-001",
                    "side": "buy",
                    "symbol": "MSFT",
                    "quantity": "1",
                },
                {
                    "submission_status": "submitted",
                    "submitted_at": "2026-06-09T03:24:30Z",
                    "runtime_id": "M10-PA-001-1d",
                    "strategy_id": "M10-PA-001",
                    "side": "sell",
                    "symbol": "MSFT",
                    "quantity": "1",
                },
            ],
        )

        rows = {row["runtime_id"]: row for row in summary["rows"]}

        self.assertEqual(summary["pre_fix_closed_trade_count"], "1")
        self.assertEqual(summary["post_fix_closed_trade_count"], "1")
        self.assertEqual(rows["M10-PA-004-long-1d"]["quality_tier"], "主交易策略")
        self.assertEqual(rows["M10-PA-004-long-1d"]["total_pnl"], "-4.00")
        self.assertEqual(rows["M10-PA-001-1d"]["quality_tier"], "严格小仓位测试策略")
        self.assertEqual(rows["M10-PA-001-1d"]["post_fix_closed_trade_count"], "1")
        self.assertIn("不读取本地模拟账本", summary["note"])

    def test_read_jsonl_ignores_partial_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text('{"ok": 1}\n{"broken"\n{"ok": 2}\n', encoding="utf-8")

            rows = read_jsonl(path)

        self.assertEqual(rows, [{"ok": 1}, {"ok": 2}])

    def test_write_helpers_replace_files_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jsonl_path = root / "events.jsonl"
            html_path = root / "dashboard.html"

            write_jsonl(jsonl_path, [{"symbol": "AAPL"}])
            write_text_atomic(html_path, "<html>ok</html>")

            self.assertEqual(read_jsonl(jsonl_path), [{"symbol": "AAPL"}])
            self.assertEqual(html_path.read_text(encoding="utf-8"), "<html>ok</html>")
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def run_stage(self, *, output_dir: Path | None = None, generated_at: str = "2026-04-29T02:30:00Z"):
        temp_dir = None
        if output_dir is None:
            temp_dir = tempfile.TemporaryDirectory()
            self.addCleanup(temp_dir.cleanup)
            output_dir = Path(temp_dir.name) / "m12_29"
        config = replace(load_config(), output_dir=output_dir)
        result = run_m12_29_current_day_scan_dashboard(
            config,
            generated_at=generated_at,
            execute_fetch=False,
            refresh_quotes=False,
        )
        return config, result, output_dir

    def test_scan_date_rolls_to_current_us_trading_day(self):
        _, result, _ = self.run_stage()
        summary = result["summary"]
        self.assertEqual(summary["scan_date"], "2026-04-28")
        self.assertEqual(summary["stage"], "M12.46.accountized_realtime_testing")

    def test_scan_date_uses_prior_session_before_regular_open(self):
        self.assertEqual(current_us_scan_date("2026-04-29T12:00:00Z").isoformat(), "2026-04-28")
        self.assertEqual(current_us_scan_date("2026-04-29T14:00:00Z").isoformat(), "2026-04-29")

    def test_market_calendar_skips_configured_holiday(self):
        self.assertEqual(market_session_status("2026-05-25T14:00:00Z")["status"], "非交易日")
        self.assertEqual(current_us_scan_date("2026-05-25T14:00:00Z").isoformat(), "2026-05-22")
        self.assertEqual(current_us_scan_date("2026-05-26T13:26:00Z").isoformat(), "2026-05-22")
        self.assertEqual(current_us_scan_date("2026-05-26T14:00:00Z").isoformat(), "2026-05-26")

    def test_account_ledger_trading_date_prefers_explicit_or_open_signal_date(self):
        self.assertEqual(
            account_ledger_trading_date(
                {
                    "event_type": "open",
                    "trading_date": "2026-05-22",
                    "signal_time": "2026-05-21T13:30:00",
                    "event_time": "2026-05-26T00:06:37Z",
                }
            ),
            date(2026, 5, 22),
        )
        self.assertEqual(
            account_ledger_trading_date(
                {
                    "event_type": "open",
                    "signal_time": "2026-05-22T13:30:00",
                    "event_time": "2026-05-26T00:06:37Z",
                }
            ),
            date(2026, 5, 22),
        )

    def test_cli_generated_at_guard_rejects_future_timestamp(self):
        with self.assertRaises(ValueError):
            validate_generated_at("2999-01-01T00:00:00Z")

    def test_data_freshness_warning_marks_fallback_or_no_fetch_as_not_ready(self):
        warning = build_dashboard_data_freshness_warning(
            quote_source="fallback_quotes_only",
            current_day_runtime_ready=False,
            current_day_scan_complete=False,
            daily_ready_symbols=0,
            current_5m_ready_symbols=0,
            active_universe_symbol_count=147,
            runtime_readiness_note="fixture",
        )
        self.assertIn("看板已生成但数据源降级", warning)
        self.assertIn("fallback quotes / no-fetch", warning)
        self.assertEqual(
            build_dashboard_data_freshness_warning(
                quote_source="longbridge_quote_readonly",
                current_day_runtime_ready=True,
                current_day_scan_complete=True,
                daily_ready_symbols=147,
                current_5m_ready_symbols=147,
                active_universe_symbol_count=147,
                runtime_readiness_note="ready",
            ),
            "",
        )

    def test_data_freshness_warning_does_not_call_longbridge_cache_gap_degraded(self):
        warning = build_dashboard_data_freshness_warning(
            quote_source="longbridge_quote_readonly",
            current_day_runtime_ready=True,
            current_day_scan_complete=False,
            daily_ready_symbols=0,
            current_5m_ready_symbols=147,
            active_universe_symbol_count=147,
            runtime_readiness_note="日线沿用上一份 cache",
        )

        self.assertIn("严格全量扫描口径未完成", warning)
        self.assertIn("长桥只读行情没有降级", warning)
        self.assertNotIn("数据源降级", warning)
        self.assertNotIn("fallback quotes / no-fetch", warning)

    def test_longbridge_paper_panel_uses_10000_model_and_fee_gate_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "daily" / "m12_29"
            daily_dir = output_dir.parent
            submitter_dir = daily_dir / "m15_longbridge_paper_order_submitter"
            queue_dir = daily_dir / "m15_longbridge_fast_signal_queue"
            connection_dir = daily_dir / "m15_longbridge_paper_connection_check"
            submitter_dir.mkdir(parents=True)
            queue_dir.mkdir(parents=True)
            connection_dir.mkdir(parents=True)
            (submitter_dir / "m15_longbridge_paper_order_submitter.json").write_text(
                json.dumps(
                    {
                        "paper_account_equity_model": "10000.00",
                        "eligible_order_count": 2,
                        "submitted_order_count": 0,
                        "attempted_order_count": 0,
                        "longbridge_account": {"paper_account_detected": True, "account_channel": "lb_papertrading"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (queue_dir / "m15_longbridge_fast_signal_queue.json").write_text(
                json.dumps(
                    {
                        "fast_queue_status": "fast_signal_queue_ready",
                        "summary": {
                            "ready_after_user_approval_count": 2,
                            "blocked_signal_count": 3,
                            "fee_profit_blocked_count": 1,
                            "net_profitable_ready_count": 2,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (connection_dir / "m15_longbridge_paper_connection_check.json").write_text(
                json.dumps({"paper_account_verified": True}, ensure_ascii=False),
                encoding="utf-8",
            )
            panel = build_longbridge_paper_dashboard_view(replace(load_config(), output_dir=output_dir))

        status_by_label = {row["label"]: row for row in panel["status_rows"]}
        queue_by_label = {row["label"]: row for row in panel["queue_rows"]}
        self.assertEqual(status_by_label["模拟资金模型"]["value"], "10000.00")
        self.assertIn("10000 USD", status_by_label["模拟资金模型"]["note"])
        self.assertEqual(queue_by_label["扣费后合格"]["value"], "2")
        self.assertIn("扣费后不赚钱阻断 1", queue_by_label["扣费后合格"]["note"])

    def test_dashboard_freshness_allows_full_first50_refresh_runtime(self):
        generated_at = (datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=500)).isoformat().replace("+00:00", "Z")
        status = build_dashboard_update_status(
            load_config(),
            {
                "generated_at": generated_at,
                "market_session": {
                    "status": "美股常规交易时段",
                    "beijing_time": "2026-05-14 23:16:59 CST",
                    "new_york_time": "2026-05-14 11:16:59 EDT",
                },
            },
            60,
        )
        self.assertEqual(status["freshness_state"], "fresh")
        self.assertEqual(status["stale_after_seconds"], "600")

    def test_strategy_closure_reflects_mainline_experimental_and_supporting_lanes(self):
        _, result, _ = self.run_stage()
        rows = {row["strategy_id"]: row for row in result["strategy_closure_rows"] if not row["strategy_id"].startswith("M12-SRC-")}
        self.assertEqual(rows["M10-PA-004"]["final_status"], "主线正式账户：只做多版")
        self.assertEqual(rows["M10-PA-005"]["final_status"], "实验账户测试")
        self.assertEqual(rows["M10-PA-007"]["final_status"], "实验账户测试")
        self.assertEqual(rows["M10-PA-014"]["final_status"], "挂件 A/B")
        self.assertEqual(rows["M10-PA-010"]["final_status"], "研究项")
        self.assertEqual(rows["M12-FTD-001"]["final_status"], "主线正式账户")

    def test_dashboard_uses_20000_independent_accounts_and_1d_5m_only(self):
        _, result, output_dir = self.run_stage()
        dashboard = json.loads((output_dir / "m12_32_minute_readonly_dashboard_data.json").read_text(encoding="utf-8"))
        html = (output_dir / "m12_32_minute_readonly_dashboard.html").read_text(encoding="utf-8")
        self.assertEqual(dashboard["schema_version"], "m12.46.accountized-readonly-dashboard.v1")
        self.assertIn("broker_terminal_view", dashboard)
        self.assertEqual(dashboard["timeframe_views"]["timeframe_order"], ["1d", "5m"])
        self.assertIn("券商式策略交易终端", html)
        self.assertIn("自选股与新闻", html)
        self.assertIn("美股七姐妹", html)
        self.assertIn("存储/闪存热点", html)
        self.assertIn("总PnL", html)
        self.assertIn("PA004 baseline / MBF / QC 对照", html)
        self.assertIn("审计与报告", html)
        self.assertIn("主线正式账户", html)
        self.assertIn("实验账户", html)
        self.assertIn("FTD001 双版本对照", html)
        self.assertIn("正式信号清单", html)
        self.assertIn("北京时间最后更新", html)
        self.assertIn("运行状态", html)
        self.assertIn("自动会话", html)
        self.assertIn("盘前 / 盘后异动", html)
        self.assertIn("长桥模拟账户", html)
        self.assertIn("看板新鲜度", html)
        self.assertNotIn("1h 小时线测试", html)
        self.assertNotIn("15m 十五分钟测试", html)
        mainline = dashboard["mainline_account_view"]
        experimental = dashboard["experimental_account_view"]
        self.assertEqual(mainline["strategy_account_count"], "8")
        self.assertEqual(experimental["strategy_account_count"], "10")
        self.assertEqual(mainline["starting_capital"], "160000.00")
        self.assertEqual(experimental["starting_capital"], "200000.00")
        first_account = dashboard["mainline_accounts"][0]
        self.assertEqual(first_account["starting_capital"], "20000.00")
        self.assertEqual(Decimal(first_account["starting_capital"]), DEFAULT_ACCOUNT_EQUITY)
        self.assertIn("CST", dashboard["update_status"]["beijing_time"])
        self.assertIn("session_liveness", dashboard["update_status"])
        self.assertIn("freshness_state", dashboard["update_status"])
        self.assertIn("longbridge_paper_account", dashboard)
        self.assertEqual(dashboard["longbridge_paper_account"]["data_available"], False)

    def test_dashboard_includes_longbridge_paper_account_panel_from_m15_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fresh_generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            output_dir = root / "m12_29"
            submitter_dir = root / "m15_longbridge_paper_order_submitter"
            queue_dir = root / "m15_longbridge_fast_signal_queue"
            realtime_dir = root / "m15_longbridge_realtime_execution"
            connection_dir = root / "m15_longbridge_paper_connection_check"
            output_dir.mkdir(parents=True)
            submitter_dir.mkdir(parents=True)
            queue_dir.mkdir(parents=True)
            realtime_dir.mkdir(parents=True)
            connection_dir.mkdir(parents=True)
            (output_dir / "m12_32_minute_readonly_dashboard_data.json").write_text(
                json.dumps(
                    {
                        "local_simulation_history_quality": {
                            "runtime_rows": [
                                {
                                    "runtime_id": "M10-PA-002-1d",
                                    "timeframe": "1d",
                                    "net_realized_pnl": "10.00",
                                    "win_rate_percent": "40.00",
                                    "profit_loss_ratio": "1.20",
                                    "closed_trade_count": "5",
                                },
                                {
                                    "runtime_id": "M10-PA-002-5m",
                                    "timeframe": "5m",
                                    "net_realized_pnl": "25.00",
                                    "win_rate_percent": "55.00",
                                    "profit_loss_ratio": "1.80",
                                    "closed_trade_count": "8",
                                },
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_account_state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-realtime-account-state.v1",
                        "generated_at": fresh_generated_at,
                        "account_channel": "lb_papertrading",
                        "account_type": "M",
                        "paper_account_detected": True,
                        "auth_ok": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "buying_power": "102524.64",
                        "total_open_order_notional": "200.00",
                        "position_row_count": 1,
                        "open_order_count": 2,
                        "held_symbols": ["NVDA"],
                        "positions": [{"symbol": "NVDA.US", "quantity": "2", "available": "2", "cost_price": "100.00"}],
                        "orders": [
                            {
                                "created_at": fresh_generated_at,
                                "status": "Filled",
                                "side": "Buy",
                                "symbol": "NVDA.US",
                                "executed_quantity": "2",
                                "executed_price": "100.00",
                            },
                            {
                                "created_at": fresh_generated_at,
                                "status": "Rejected",
                                "side": "Sell",
                                "symbol": "NVDA.US",
                                "quantity": "1",
                                "price": "95.00",
                            },
                            {
                                "created_at": fresh_generated_at,
                                "status": "New",
                                "side": "Buy",
                                "symbol": "MSFT.US",
                                "quantity": "1",
                                "price": "200.00",
                            },
                        ],
                        "local_sim_position_migration": False,
                        "real_money_actions": False,
                        "live_execution": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_account_pnl_reconciliation.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-account-pnl-reconciliation.v2",
                        "generated_at": fresh_generated_at,
                        "query_range": {"start": "2026-06-01", "end": "2026-06-30"},
                        "account_pnl": {
                            "initial_asset_value": "102500.00",
                            "ending_asset_value": "102735.00",
                            "sum_profit": "235.00",
                            "sum_profit_percent": "0.23",
                        },
                        "trading_pnl": {
                            "stock_total_pnl": "91.83",
                            "realized_pnl_estimate": "-178.04",
                            "current_position_unrealized_pnl": "269.87",
                        },
                        "account_snapshot": {
                            "portfolio_total_cash": "95948.45",
                            "portfolio_market_cap": "6686.85",
                            "portfolio_total_asset": "102635.30",
                            "portfolio_total_pl": "269.866",
                            "portfolio_total_today_pl": "234.00",
                        },
                        "current_holdings": [
                            {
                                "symbol": "NVDA.US",
                                "quantity": "2",
                                "market_price": "105.00",
                                "prev_close": "103.00",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_realtime_market_events.jsonl").write_text(
                json.dumps(
                    {
                        "event_id": "nvda-latest",
                        "symbol": "NVDA",
                        "event_time": fresh_generated_at,
                        "close": "105.00",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (submitter_dir / "m15_longbridge_paper_account_state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-paper-account-state.v1",
                        "generated_at": fresh_generated_at,
                        "account_channel": "lb_papertrading",
                        "account_type": "M",
                        "paper_account_detected": True,
                        "auth_ok": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "buying_power": "102524.64",
                        "position_row_count": 1,
                        "open_order_count": 2,
                        "held_symbols": ["NVDA"],
                        "local_sim_position_migration": False,
                        "real_money_actions": False,
                        "live_execution": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (submitter_dir / "m15_longbridge_paper_order_submitter.json").write_text(
                json.dumps(
                    {
                        "generated_at": fresh_generated_at,
                        "submission_status": "no_eligible_orders",
                        "eligible_order_count": 0,
                        "attempted_order_count": 0,
                        "submitted_order_count": 0,
                        "paper_account_equity_model": "6000.00",
                        "global_blockers": [],
                        "plain_language_result": "当前没有符合提交条件的模拟订单。",
                        "market_window": {
                            "market_status": "regular_session",
                            "market_date": "2026-06-02",
                            "new_york_time": "2026-06-02 10:02:06 EDT",
                        },
                        "latency_ms": {"total": 1027},
                        "next_interval_seconds": 15,
                        "longbridge_account": {
                            "account_channel": "lb_papertrading",
                            "account_type": "M",
                            "paper_account_detected": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (queue_dir / "m15_longbridge_fast_signal_queue.json").write_text(
                json.dumps(
                    {
                        "scan_date": "2026-06-02",
                        "current_market_date": "2026-06-02",
                        "fast_queue_status": "no_submit_ready_fast_signals",
                        "snapshot_freshness_status": "current_market_date",
                        "plain_language_result": "快速通道发现 17 条当天新开仓信号，其中 0 条通过快速队列风控。",
                        "summary": {
                            "new_open_signal_count": 17,
                            "blocked_signal_count": 17,
                            "ready_after_user_approval_count": 0,
                            "ready_after_user_approval_notional": "0.00",
                            "repair_signal_count": 10,
                            "stale_snapshot_blocked_count": 0,
                            "confluence_primary_count": 0,
                            "confluence_support_count": 0,
                            "status_counts": {"local_order_preview_created_short_disabled": 6},
                        },
                        "confluence_summary": {"max_confluence_multiplier": "1"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_session_supervisor.json").write_text(
                json.dumps(
                    {
                        "generated_at": fresh_generated_at,
                        "supervisor_status": "cycle_completed",
                        "cycle_ran": True,
                        "new_market_event_count": 2,
                        "new_signal_event_count": 1,
                        "ready_order_count": 1,
                        "submitted_count": 0,
                        "legacy_fast_queue_used": False,
                        "manual_m12_37_once_used": False,
                        "plain_language_result": "长桥实时链路本轮已完成：只读行情、实时信号、模拟账户执行链路已按顺序串联；没有读取本地模拟账本。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_market_event_ingestor.json").write_text(
                json.dumps(
                    {
                        "generated_at": fresh_generated_at,
                        "new_market_event_count": 2,
                        "market_event_total_count": 12,
                        "deferred_count": 0,
                        "plain_language_result": "长桥只读行情采集器新增 2 条实时行情事件；没有读取本地模拟账本。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_signal_router.json").write_text(
                json.dumps(
                    {
                        "generated_at": fresh_generated_at,
                        "market_event_count": 2,
                        "new_signal_event_count": 1,
                        "plain_language_result": "实时信号路由器从 2 条行情事件生成 1 条长桥实时信号；没有读取本地模拟账本。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_execution.json").write_text(
                json.dumps(
                    {
                        "generated_at": fresh_generated_at,
                        "ready_order_count": 1,
                        "signal_event_count": 1,
                        "blocked_signal_count": 0,
                        "submitted_count": 0,
                        "latency_counts": {"target_met": 1, "acceptable": 0, "delayed_revalidated": 0},
                        "runtime_whitelist": [
                            "M10-PA-004-long-1d",
                            "M10-PA-002-5m",
                            "M12-FTD-001-baseline-1d",
                            "M12-FTD-001-loss-streak-guard-1d",
                            "M10-PA-004-MBF-1d",
                            "M10-PA-004-MBF-QC-1d",
                            "M10-PA-013-5m",
                            "M10-PA-011-ORB-R1-5m",
                        ],
                        "virtual_capital_buckets": [
                            {"capital_bucket": "pa004_long", "label": "PA004-long单仓（M10-PA-004-long-1d）", "runtime_ids": ["M10-PA-004-long-1d"]},
                            {"capital_bucket": "pa002_5m", "label": "PA002-5m单仓（M10-PA-002-5m）", "runtime_ids": ["M10-PA-002-5m"]},
                            {"capital_bucket": "ftd_baseline", "label": "FTD原版单仓（M12-FTD-001-baseline-1d）", "runtime_ids": ["M12-FTD-001-baseline-1d"]},
                            {"capital_bucket": "ftd_loss_streak", "label": "FTD连亏保护单仓（M12-FTD-001-loss-streak-guard-1d）", "runtime_ids": ["M12-FTD-001-loss-streak-guard-1d"]},
                            {"capital_bucket": "pa004_mbf", "label": "PA004-MBF单仓（M10-PA-004-MBF-1d）", "runtime_ids": ["M10-PA-004-MBF-1d"]},
                            {"capital_bucket": "pa004_mbf_qc", "label": "PA004-MBF-QC单仓（M10-PA-004-MBF-QC-1d）", "runtime_ids": ["M10-PA-004-MBF-QC-1d"]},
                            {"capital_bucket": "pa013_5m", "label": "PA013-5m单仓（M10-PA-013-5m）", "runtime_ids": ["M10-PA-013-5m"]},
                            {"capital_bucket": "pa011_orb_r1", "label": "PA011-ORB-R1单仓（M10-PA-011-ORB-R1-5m）", "runtime_ids": ["M10-PA-011-ORB-R1-5m"]},
                        ],
                        "plain_language_result": "长桥实时链路有 1 条实时信号通过风控，但当前是只读演练，未提交订单。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (connection_dir / "m15_longbridge_paper_connection_check.json").write_text(
                json.dumps(
                    {
                        "paper_account_verified": True,
                        "paper_account_equity_model": "6000",
                        "real_money_actions": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            config = replace(load_config(), output_dir=output_dir)
            panel = build_longbridge_paper_dashboard_view(config)
            panel_json = json.dumps(panel, ensure_ascii=False)
            html = build_dashboard_html(config, self._minimal_dashboard_for_html(panel))
        self.assertTrue(panel["data_available"])
        self.assertTrue(panel["paper_account_detected"])
        self.assertEqual(panel["account_channel"], "lb_papertrading")
        self.assertEqual(panel["longbridge_panel_generated_at"], fresh_generated_at)
        self.assertEqual(panel["position_count"], "1")
        self.assertEqual(panel["position_row_count"], "1")
        self.assertEqual(panel["open_order_count"], "2")
        self.assertEqual(panel["today_total_pnl"], "234.00")
        self.assertEqual(panel["longbridge_account_today_total_pnl"], "234.00")
        self.assertEqual(panel["longbridge_account_total_pnl"], "269.866")
        self.assertEqual(panel["total_pnl"], "269.866")
        self.assertEqual(panel["account_total_equity_estimate"], "102635.30")
        self.assertEqual(panel["account_total_pnl_estimate"], "235.00")
        self.assertEqual(panel["account_total_return_percent"], "0.23")
        self.assertEqual(panel["project_model_exposure_label"], "410.00 / 6000.00 (6.83%)")
        self.assertIn("成交 1 / 拒单 1 / 挂单 1", panel_json)
        self.assertEqual(panel["submit_ready_count"], "1")
        self.assertEqual(panel["new_open_signal_count"], "1")
        self.assertIn("长桥账户总资产", panel_json)
        self.assertIn("当前持仓总盈亏", panel_json)
        self.assertIn("portfolio.total_pl", panel_json)
        self.assertIn("项目资金模型占用", panel_json)
        pnl_cards_by_label = {row["label"]: row for row in panel["realtime_pnl_cards"]}
        self.assertEqual(pnl_cards_by_label["接口持仓今日浮动"]["value"], "234.00")
        self.assertEqual(pnl_cards_by_label["账户当日盈亏"]["value"], "无法计算")
        self.assertEqual(pnl_cards_by_label["当前持仓总盈亏"]["value"], "269.87")
        self.assertEqual(pnl_cards_by_label["持仓浮动"]["value"], "269.87")
        self.assertNotIn("长桥总盈亏", panel_json)
        self.assertIn("项目按 10000 USD 模型控制仓位", panel_json)
        self.assertIn("长桥实时链路本轮已完成", panel_json)
        self.assertIn("长桥只读行情采集器新增 2 条实时行情事件", panel_json)
        self.assertIn("实时信号路由器从 2 条行情事件生成 1 条长桥实时信号", panel_json)
        self.assertIn("长桥模拟账户已连接", panel["plain_language_result"])
        self.assertIn("实时守护器", html)
        self.assertIn("实时行情采集", html)
        self.assertIn("实时信号生成", html)
        self.assertIn("实时链路", html)
        self.assertIn("实时盈亏", html)
        self.assertIn("持仓浮动", html)
        self.assertIn("逐标的盈亏", html)
        self.assertIn("逐策略成交盈亏", html)
        dedicated_rows = {row["runtime_id"]: row for row in panel["dedicated_bucket_runtime_review_rows"]}
        self.assertEqual(dedicated_rows["M10-PA-002-5m"]["review_status"], "已按运行单元复核")
        self.assertEqual(dedicated_rows["M10-PA-004-MBF-QC-1d"]["review_status"], "已按运行单元复核")
        self.assertIn("单策略仓运行单元复核", html)
        self.assertIn("PA002-5m单仓", html)
        self.assertNotIn("实时链路与旧队列", html)
        self.assertIn('http-equiv="Cache-Control"', html)
        self.assertIn('content="no-store, no-cache, must-revalidate"', html)
        self.assertIn("dashboard_reload", html)
        self.assertNotIn("order_id", panel_json)

    def test_longbridge_panel_includes_trade_quality_metrics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fresh_generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            output_dir = root / "m12_29"
            realtime_dir = root / "m15_longbridge_realtime_execution"
            realtime_dir.mkdir(parents=True)
            (realtime_dir / "m15_longbridge_realtime_account_state.json").write_text(
                json.dumps(
                    {
                        "generated_at": fresh_generated_at,
                        "account_channel": "lb_papertrading",
                        "account_type": "M",
                        "paper_account_detected": True,
                        "auth_ok": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "buying_power": "10000.00",
                        "position_row_count": 0,
                        "open_order_count": 0,
                        "local_sim_position_migration": False,
                        "real_money_actions": False,
                        "live_execution": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_account_pnl_reconciliation.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-account-pnl-reconciliation.v1",
                        "generated_at": fresh_generated_at,
                        "query_range": {"start": "2026-06-01", "end": "2026-06-08"},
                        "account_pnl": {"sum_profit": "-10.00"},
                        "trading_pnl": {"stock_total_pnl": "-10.00", "current_position_unrealized_pnl": "0.00"},
                        "symbol_pnl_rows": [
                            {"security_code": "NVDA", "profit": "20.00", "profit_rate": "0.0200"},
                            {"security_code": "TSLA", "profit": "-10.00", "profit_rate": "-0.0500"},
                            {"security_code": "MSFT", "profit": "0", "profit_rate": "0"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_equity_curve.jsonl").write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in [
                        {"generated_at": "2026-06-04T14:00:00Z", "account_total_equity_estimate": "10000.00"},
                        {"generated_at": "2026-06-04T15:00:00Z", "account_total_equity_estimate": "10500.00"},
                        {"generated_at": "2026-06-04T16:00:00Z", "account_total_equity_estimate": "9450.00"},
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            panel = build_longbridge_paper_dashboard_view(replace(load_config(), output_dir=output_dir))
            panel_json = json.dumps(panel, ensure_ascii=False)

        self.assertEqual(panel["longbridge_symbol_win_rate_label"], "50.00%")
        self.assertEqual(panel["longbridge_worst_symbol_loss_label"], "-5.00%")
        self.assertEqual(panel["longbridge_max_drawdown_label"], "10.00%")
        self.assertEqual(panel["longbridge_profit_loss_ratio"], "2.00")
        self.assertIn("长桥逐标的胜率", panel_json)
        self.assertIn("长桥完整最大回撤", panel_json)
        self.assertNotIn("长桥回撤代理", panel_json)

    def test_longbridge_panel_prefers_realtime_account_state_over_legacy_submitter_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fresh_generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            output_dir = root / "m12_29"
            submitter_dir = root / "m15_longbridge_paper_order_submitter"
            realtime_dir = root / "m15_longbridge_realtime_execution"
            connection_dir = root / "m15_longbridge_paper_connection_check"
            submitter_dir.mkdir(parents=True)
            realtime_dir.mkdir(parents=True)
            connection_dir.mkdir(parents=True)
            (submitter_dir / "m15_longbridge_paper_account_state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-paper-account-state.v1",
                        "generated_at": fresh_generated_at,
                        "account_channel": "lb_papertrading",
                        "account_type": "M",
                        "paper_account_detected": True,
                        "auth_ok": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "buying_power": "111.00",
                        "position_row_count": 9,
                        "open_order_count": 9,
                        "held_symbols": ["OLD"],
                        "local_sim_position_migration": False,
                        "real_money_actions": False,
                        "live_execution": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_account_state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-realtime-account-state.v1",
                        "generated_at": fresh_generated_at,
                        "account_channel": "lb_papertrading",
                        "account_type": "M",
                        "paper_account_detected": True,
                        "paper_account_verified": True,
                        "auth_ok": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "buying_power": "10000.00",
                        "cash": "10000.00",
                        "position_row_count": 1,
                        "open_order_count": 0,
                        "held_symbols": ["AAPL"],
                        "local_simulation_isolated": True,
                        "real_money_actions": False,
                        "live_execution": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_account_state_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-realtime-account-state-summary.v1",
                        "generated_at": fresh_generated_at,
                        "account_status": "paper_account_ready",
                        "plain_language_result": "长桥实时账户状态已只读读取，本地模拟没有参与持仓和挂单判断。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_position_manager.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-realtime-position-manager.v1",
                        "generated_at": fresh_generated_at,
                        "position_count": 1,
                        "managed_position_count": 0,
                        "unmanaged_position_count": 1,
                        "unmanaged_position_symbols": ["AAPL"],
                        "new_exit_signal_event_count": 0,
                        "plain_language_result": "AAPL 是账户已有但非本轮 M15 开仓的持仓，只展示，不自动平仓。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (connection_dir / "m15_longbridge_paper_connection_check.json").write_text(
                json.dumps({"paper_account_verified": True}, ensure_ascii=False),
                encoding="utf-8",
            )

            config = replace(load_config(), output_dir=output_dir)
            panel = build_longbridge_paper_dashboard_view(config)

        status_by_label = {row["label"]: row for row in panel["status_rows"]}
        self.assertEqual(panel["buying_power"], "10000.00")
        self.assertEqual(panel["position_row_count"], "1")
        self.assertEqual(panel["open_order_count"], "0")
        self.assertIn("AAPL", status_by_label["持仓 / 挂单"]["note"])
        self.assertNotIn("OLD", status_by_label["持仓 / 挂单"]["note"])
        self.assertEqual(status_by_label["实时账户状态"]["value"], "paper_account_ready")
        self.assertEqual(panel["managed_position_count"], "0")
        self.assertEqual(panel["exit_only_position_count"], "1")
        self.assertEqual(panel["exit_only_position_symbols"], ["AAPL"])
        self.assertEqual(panel["unmanaged_position_count"], "0")
        self.assertEqual(panel["raw_unmanaged_position_count"], "1")
        self.assertEqual(panel["raw_unmanaged_position_symbols"], ["AAPL"])
        self.assertIn("非本轮 M15 开仓", status_by_label["实时持仓退出"]["note"])
        self.assertIn("只接管退出待实时复核", status_by_label["实时持仓退出"]["note"])
        self.assertEqual(panel["submission_status"], "paper_account_ready")
        self.assertNotEqual(panel["submission_status"], "submitter_state_stale_waiting_refresh")
        self.assertTrue(panel["refs"]["realtime_account_state"])
        self.assertTrue(panel["refs"]["paper_account_state"])

    def test_longbridge_panel_keeps_realtime_snapshot_while_waiting_next_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "m12_29"
            realtime_dir = root / "m15_longbridge_realtime_execution"
            connection_dir = root / "m15_longbridge_paper_connection_check"
            realtime_dir.mkdir(parents=True)
            connection_dir.mkdir(parents=True)
            old_generated_at = "2026-06-05T01:00:00Z"
            (realtime_dir / "m15_longbridge_realtime_account_state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-realtime-account-state.v1",
                        "generated_at": old_generated_at,
                        "account_channel": "lb_papertrading",
                        "account_type": "M",
                        "paper_account_detected": True,
                        "paper_account_verified": True,
                        "auth_ok": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "buying_power": "100582.01",
                        "position_row_count": 9,
                        "open_order_count": 5,
                        "held_symbols": ["AAPL", "XLU", "CRM"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_account_state_summary.json").write_text(
                json.dumps(
                    {
                        "generated_at": old_generated_at,
                        "account_status": "paper_account_ready",
                        "plain_language_result": "长桥模拟账户状态已读取：持仓 9 条，未完成挂单 5 条。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_session_supervisor.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-05T02:25:00Z",
                        "supervisor_status": "waiting_market_window",
                        "window": {
                            "market_status": "等待下一交易日",
                            "new_york_time": "2026-06-04 22:25:00 EDT",
                        },
                        "plain_language_result": "长桥实时链路守护器未运行交易循环：当前是等待下一交易日。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_execution.json").write_text(
                json.dumps(
                    {
                        "generated_at": old_generated_at,
                        "input_signal_event_count": 609,
                        "signal_event_count": 0,
                        "skipped_previously_processed_signal_count": 609,
                        "ready_order_count": 0,
                        "blocked_signal_count": 0,
                        "submitted_count": 4,
                        "plain_language_result": "长桥实时链路已就绪；当前没有新的实时信号事件。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_position_manager.json").write_text(
                json.dumps(
                    {
                        "generated_at": old_generated_at,
                        "managed_position_count": 7,
                        "unmanaged_position_count": 2,
                        "unmanaged_position_symbols": ["AAPL", "XLU"],
                        "new_exit_signal_event_count": 0,
                        "plain_language_result": "AAPL, XLU 是账户已有但非本轮 M15 开仓的持仓，只展示，不自动平仓。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (connection_dir / "m15_longbridge_paper_connection_check.json").write_text(
                json.dumps({"paper_account_verified": True}, ensure_ascii=False),
                encoding="utf-8",
            )

            config = replace(load_config(), output_dir=output_dir)
            with patch("scripts.m12_29_current_day_scan_dashboard_lib.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = datetime.fromisoformat("2026-06-05T02:25:00+00:00")
                mocked_datetime.fromisoformat = datetime.fromisoformat
                panel = build_longbridge_paper_dashboard_view(config)

        self.assertFalse(panel["account_state_stale"])
        self.assertFalse(panel["realtime_execution_state_stale"])
        self.assertEqual(panel["top_metric"], "模拟账户已连接 / 9持仓 / 5挂单")
        self.assertEqual(panel["position_row_count"], "9")
        self.assertEqual(panel["open_order_count"], "5")
        self.assertEqual(panel["skipped_previously_processed_signal_count"], "609")
        self.assertEqual(panel["generated_at"], old_generated_at)
        self.assertEqual(panel["account_state_generated_at"], old_generated_at)
        self.assertIn("账户状态已只读刷新", panel["plain_language_result"])
        self.assertIn("等待下一交易日自动运行", panel["plain_language_result"])
        self.assertIn("长桥面板刷新时间", json.dumps(panel["status_rows"], ensure_ascii=False))
        self.assertNotIn("累计提交 4", panel["plain_language_result"])
        self.assertNotIn("实时链路本轮已提交", panel["plain_language_result"])
        self.assertIn("7系统管理 / 2只接管退出 / 0未接管退出", json.dumps(panel["status_rows"], ensure_ascii=False))

    def test_longbridge_panel_does_not_show_legacy_submitter_blocker_when_realtime_is_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fresh_generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            output_dir = root / "m12_29"
            submitter_dir = root / "m15_longbridge_paper_order_submitter"
            realtime_dir = root / "m15_longbridge_realtime_execution"
            connection_dir = root / "m15_longbridge_paper_connection_check"
            submitter_dir.mkdir(parents=True)
            realtime_dir.mkdir(parents=True)
            connection_dir.mkdir(parents=True)
            (submitter_dir / "m15_longbridge_paper_order_submitter.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-03T22:00:00Z",
                        "submission_status": "blocked",
                        "global_blockers": ["not_us_regular_session"],
                        "market_window": {
                            "market_status": "收盘后",
                            "new_york_time": "2026-06-03 18:00:00 EDT",
                        },
                        "longbridge_account": {
                            "account_channel": "lb_papertrading",
                            "account_type": "M",
                            "paper_account_detected": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_account_state.json").write_text(
                json.dumps(
                    {
                        "generated_at": fresh_generated_at,
                        "account_channel": "lb_papertrading",
                        "account_type": "M",
                        "paper_account_detected": True,
                        "paper_account_verified": True,
                        "auth_ok": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "buying_power": "10000.00",
                        "position_row_count": 9,
                        "open_order_count": 1,
                        "held_symbols": ["AAPL"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_account_state_summary.json").write_text(
                json.dumps({"generated_at": fresh_generated_at, "account_status": "paper_account_ready"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_session_supervisor.json").write_text(
                json.dumps(
                    {
                        "generated_at": fresh_generated_at,
                        "supervisor_status": "cycle_completed",
                        "window": {
                            "market_status": "美股常规交易时段",
                            "new_york_time": "2026-06-04 09:53:26 EDT",
                        },
                        "plain_language_result": "实时链路本轮已完成。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (realtime_dir / "m15_longbridge_realtime_execution.json").write_text(
                json.dumps(
                    {
                        "generated_at": fresh_generated_at,
                        "ready_order_count": 0,
                        "submitted_count": 0,
                        "blocked_signal_count": 3,
                        "signal_event_count": 3,
                        "plain_language_result": "实时链路已隔离本地模拟。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (connection_dir / "m15_longbridge_paper_connection_check.json").write_text(
                json.dumps({"paper_account_verified": True}, ensure_ascii=False),
                encoding="utf-8",
            )

            panel = build_longbridge_paper_dashboard_view(replace(load_config(), output_dir=output_dir))

        status_by_label = {row["label"]: row for row in panel["status_rows"]}
        self.assertNotIn("not_us_regular_session", panel["plain_language_result"])
        self.assertNotIn("提交器状态来自旧交易日", panel["plain_language_result"])
        self.assertNotEqual(panel["submission_status"], "submitter_state_stale_waiting_refresh")
        self.assertEqual(status_by_label["市场窗口"]["value"], "美股常规交易时段")

    def test_m15_submission_counts_infers_market_date_from_realtime_timestamps(self):
        rows = [
            {
                "submission_status": "submitted",
                "signal_id": "signal-a",
                "submitted_at": "2026-06-04T13:31:19Z",
            },
            {
                "submission_status": "submitted",
                "signal_id": "signal-a",
                "submitted_at": "2026-06-04T13:31:20Z",
            },
            {
                "submission_status": "submit_failed",
                "signal_id": "signal-b",
                "processed_at": "2026-06-04T13:32:00Z",
            },
            {
                "submission_status": "submitted",
                "signal_id": "prior-day",
                "submitted_at": "2026-06-03T20:00:00Z",
            },
        ]

        counts = m15_submission_counts_for_date(rows, "2026-06-04")

        self.assertEqual(counts["submitted"], 1)
        self.assertEqual(counts["attempted"], 2)

    def test_longbridge_panel_marks_stale_account_state_instead_of_showing_old_orders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "m12_29"
            submitter_dir = root / "m15_longbridge_paper_order_submitter"
            queue_dir = root / "m15_longbridge_fast_signal_queue"
            connection_dir = root / "m15_longbridge_paper_connection_check"
            submitter_dir.mkdir(parents=True)
            queue_dir.mkdir(parents=True)
            connection_dir.mkdir(parents=True)
            (submitter_dir / "m15_longbridge_paper_account_state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-paper-account-state.v1",
                        "generated_at": "2026-06-02T16:10:00Z",
                        "account_channel": "lb_papertrading",
                        "account_type": "M",
                        "paper_account_detected": True,
                        "auth_ok": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "buying_power": "102335.94",
                        "position_row_count": 0,
                        "open_order_count": 1,
                        "held_symbols": [],
                        "local_sim_position_migration": False,
                        "real_money_actions": False,
                        "live_execution": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (submitter_dir / "m15_longbridge_paper_order_submitter.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-02T16:10:00Z",
                        "submission_status": "no_eligible_orders",
                        "eligible_order_count": 0,
                        "attempted_order_count": 0,
                        "submitted_order_count": 0,
                        "preview_scan_date": "2026-06-02",
                        "paper_account_equity_model": "6000.00",
                        "global_blockers": [],
                        "plain_language_result": "当前没有符合提交条件的模拟订单。",
                        "market_window": {
                            "market_status": "regular_session",
                            "market_date": "2026-06-02",
                            "new_york_time": "2026-06-02 12:10:00 EDT",
                        },
                        "longbridge_account": {
                            "account_channel": "lb_papertrading",
                            "account_type": "M",
                            "paper_account_detected": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (queue_dir / "m15_longbridge_fast_signal_queue.json").write_text(
                json.dumps(
                    {
                        "scan_date": "2026-06-03",
                        "current_market_date": "2026-06-03",
                        "fast_queue_status": "fast_signal_queue_ready",
                        "snapshot_freshness_status": "current_market_date",
                        "plain_language_result": "快速通道发现 25 条当天新开仓信号，其中 2 条通过快速队列风控。",
                        "summary": {
                            "new_open_signal_count": 25,
                            "blocked_signal_count": 23,
                            "ready_after_user_approval_count": 2,
                            "ready_after_user_approval_notional": "1560.65",
                            "repair_signal_count": 15,
                            "stale_snapshot_blocked_count": 0,
                            "confluence_primary_count": 2,
                            "confluence_support_count": 2,
                            "status_counts": {},
                        },
                        "confluence_summary": {"max_confluence_multiplier": "1.25"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (connection_dir / "m15_longbridge_paper_connection_check.json").write_text(
                json.dumps(
                    {
                        "paper_account_verified": True,
                        "paper_account_equity_model": "10000",
                        "real_money_actions": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            config = replace(load_config(), output_dir=output_dir)
            panel = build_longbridge_paper_dashboard_view(config)

        self.assertTrue(panel["account_state_stale"])
        self.assertTrue(panel["submitter_state_stale"])
        self.assertTrue(panel["fast_queue_state_stale"])
        self.assertEqual(panel["top_metric"], "模拟账户已连接 / 账户状态待刷新")
        self.assertEqual(panel["open_order_count"], "状态未刷新")
        self.assertEqual(panel["submit_ready_count"], "0")
        self.assertIn("旧交易日", panel["plain_language_result"])
        self.assertIn("旧提交器仅审计", json.dumps(panel["status_rows"], ensure_ascii=False))

    def test_longbridge_panel_marks_old_same_day_account_state_as_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "m12_29"
            submitter_dir = root / "m15_longbridge_paper_order_submitter"
            queue_dir = root / "m15_longbridge_fast_signal_queue"
            connection_dir = root / "m15_longbridge_paper_connection_check"
            submitter_dir.mkdir(parents=True)
            queue_dir.mkdir(parents=True)
            connection_dir.mkdir(parents=True)
            (submitter_dir / "m15_longbridge_paper_account_state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-paper-account-state.v1",
                        "generated_at": "2020-01-02T16:10:00Z",
                        "account_channel": "lb_papertrading",
                        "account_type": "M",
                        "paper_account_detected": True,
                        "auth_ok": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "buying_power": "102335.94",
                        "position_row_count": 1,
                        "open_order_count": 1,
                        "held_symbols": ["AAPL"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (submitter_dir / "m15_longbridge_paper_order_submitter.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2020-01-02T16:10:00Z",
                        "submission_status": "no_eligible_orders",
                        "eligible_order_count": 0,
                        "preview_scan_date": "2020-01-02",
                        "market_window": {
                            "market_status": "regular_session",
                            "market_date": "2020-01-02",
                            "new_york_time": "2020-01-02 11:10:00 EST",
                        },
                        "longbridge_account": {
                            "account_channel": "lb_papertrading",
                            "account_type": "M",
                            "paper_account_detected": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (queue_dir / "m15_longbridge_fast_signal_queue.json").write_text(
                json.dumps(
                    {
                        "scan_date": "2020-01-02",
                        "current_market_date": "2020-01-02",
                        "fast_queue_status": "no_submit_ready_fast_signals",
                        "snapshot_freshness_status": "current_market_date",
                        "summary": {
                            "new_open_signal_count": 0,
                            "blocked_signal_count": 0,
                            "ready_after_user_approval_count": 0,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (connection_dir / "m15_longbridge_paper_connection_check.json").write_text(
                json.dumps({"paper_account_verified": True, "paper_account_equity_model": "10000"}, ensure_ascii=False),
                encoding="utf-8",
            )

            config = replace(load_config(), output_dir=output_dir)
            panel = build_longbridge_paper_dashboard_view(config)

        self.assertTrue(panel["account_state_stale"])
        self.assertEqual(panel["top_metric"], "模拟账户已连接 / 账户状态待刷新")
        self.assertEqual(panel["position_row_count"], "状态未刷新")
        self.assertIn("已经过期", panel["plain_language_result"])

    def test_longbridge_panel_keeps_fresh_account_state_when_fast_queue_is_old(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "m12_29"
            submitter_dir = root / "m15_longbridge_paper_order_submitter"
            queue_dir = root / "m15_longbridge_fast_signal_queue"
            connection_dir = root / "m15_longbridge_paper_connection_check"
            submitter_dir.mkdir(parents=True)
            queue_dir.mkdir(parents=True)
            connection_dir.mkdir(parents=True)
            (submitter_dir / "m15_longbridge_paper_account_state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-paper-account-state.v1",
                        "generated_at": "2026-06-04T07:55:43Z",
                        "account_channel": "lb_papertrading",
                        "account_type": "M",
                        "paper_account_detected": True,
                        "auth_ok": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "buying_power": "102043.72",
                        "position_row_count": 2,
                        "open_order_count": 0,
                        "held_symbols": ["AAPL", "XLU"],
                        "local_sim_position_migration": False,
                        "real_money_actions": False,
                        "live_execution": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (submitter_dir / "m15_longbridge_paper_order_submitter.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-04T01:10:12Z",
                        "submission_status": "blocked_global_gate",
                        "eligible_order_count": 0,
                        "attempted_order_count": 0,
                        "submitted_order_count": 0,
                        "preview_scan_date": "2026-06-03",
                        "market_window": {
                            "market_status": "after_regular_session",
                            "market_date": "2026-06-03",
                            "new_york_time": "2026-06-03 21:10:12 EDT",
                        },
                        "longbridge_account": {
                            "account_channel": "lb_papertrading",
                            "account_type": "M",
                            "paper_account_detected": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (queue_dir / "m15_longbridge_fast_signal_queue.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-04T01:10:12Z",
                        "scan_date": "2026-06-03",
                        "current_market_date": "2026-06-03",
                        "fast_queue_status": "no_submit_ready_fast_signals",
                        "snapshot_freshness_status": "current_market_date",
                        "summary": {
                            "new_open_signal_count": 17,
                            "blocked_signal_count": 15,
                            "ready_after_user_approval_count": 2,
                            "repair_signal_count": 10,
                            "stale_snapshot_blocked_count": 0,
                            "confluence_primary_count": 2,
                            "confluence_support_count": 0,
                        },
                        "confluence_summary": {"max_confluence_multiplier": "1"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (connection_dir / "m15_longbridge_paper_connection_check.json").write_text(
                json.dumps({"paper_account_verified": True, "paper_account_equity_model": "10000"}, ensure_ascii=False),
                encoding="utf-8",
            )

            config = replace(load_config(), output_dir=output_dir)
            with patch("scripts.m12_29_current_day_scan_dashboard_lib.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = datetime.fromisoformat("2026-06-04T07:56:00+00:00")
                mocked_datetime.fromisoformat = datetime.fromisoformat
                panel = build_longbridge_paper_dashboard_view(config)

        self.assertFalse(panel["account_state_stale"])
        self.assertTrue(panel["submitter_state_stale"])
        self.assertTrue(panel["fast_queue_state_stale"])
        self.assertEqual(panel["position_row_count"], "2")
        self.assertEqual(panel["open_order_count"], "0")
        self.assertEqual(panel["submit_ready_count"], "0")
        self.assertIn("实时链路状态尚未刷新", panel["plain_language_result"])
        self.assertIn("旧快速队列、旧本地账本和平仓记录不作为长桥实时下单来源", json.dumps(panel["queue_rows"], ensure_ascii=False))
        self.assertIn("AAPL, XLU", json.dumps(panel, ensure_ascii=False))

    def test_longbridge_panel_counts_today_submissions_from_ledger(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "m12_29"
            submitter_dir = root / "m15_longbridge_paper_order_submitter"
            queue_dir = root / "m15_longbridge_fast_signal_queue"
            connection_dir = root / "m15_longbridge_paper_connection_check"
            submitter_dir.mkdir(parents=True)
            queue_dir.mkdir(parents=True)
            connection_dir.mkdir(parents=True)
            (submitter_dir / "m15_longbridge_paper_account_state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m15.longbridge-paper-account-state.v1",
                        "generated_at": "2026-06-03T15:08:42Z",
                        "account_channel": "lb_papertrading",
                        "account_type": "M",
                        "paper_account_detected": True,
                        "auth_ok": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "buying_power": "102041.02",
                        "position_row_count": 1,
                        "open_order_count": 1,
                        "held_symbols": ["AAPL"],
                        "local_sim_position_migration": False,
                        "real_money_actions": False,
                        "live_execution": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (submitter_dir / "m15_longbridge_paper_order_submitter.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-03T15:08:42Z",
                        "submission_status": "no_eligible_orders",
                        "eligible_order_count": 0,
                        "attempted_order_count": 0,
                        "submitted_order_count": 0,
                        "preview_scan_date": "2026-06-03",
                        "paper_account_equity_model": "10000.00",
                        "global_blockers": [],
                        "plain_language_result": "当前没有符合提交条件的模拟订单。",
                        "market_window": {
                            "market_status": "regular_session",
                            "market_date": "2026-06-03",
                            "new_york_time": "2026-06-03 11:08:42 EDT",
                        },
                        "longbridge_account": {
                            "account_channel": "lb_papertrading",
                            "account_type": "M",
                            "paper_account_detected": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (submitter_dir / "m15_longbridge_paper_order_submitter_ledger.jsonl").write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in [
                        {
                            "trading_date": "2026-06-03",
                            "submission_status": "submitted",
                            "signal_fingerprint": "aapl",
                            "submission_response": {"order_id": "order-aapl"},
                        },
                        {
                            "trading_date": "2026-06-03",
                            "submission_status": "submitted",
                            "signal_fingerprint": "xlu",
                            "submission_response": {"order_id": "order-xlu"},
                        },
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (queue_dir / "m15_longbridge_fast_signal_queue.json").write_text(
                json.dumps(
                    {
                        "scan_date": "2026-06-03",
                        "current_market_date": "2026-06-03",
                        "fast_queue_status": "fast_signal_queue_ready",
                        "snapshot_freshness_status": "current_market_date",
                        "plain_language_result": "快速通道发现 25 条当天新开仓信号，其中 0 条通过快速队列风控。",
                        "summary": {
                            "new_open_signal_count": 25,
                            "blocked_signal_count": 25,
                            "ready_after_user_approval_count": 0,
                            "ready_after_user_approval_notional": "0.00",
                            "repair_signal_count": 15,
                            "stale_snapshot_blocked_count": 0,
                            "confluence_primary_count": 0,
                            "confluence_support_count": 0,
                            "status_counts": {},
                        },
                        "confluence_summary": {"max_confluence_multiplier": "1"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (connection_dir / "m15_longbridge_paper_connection_check.json").write_text(
                json.dumps({"paper_account_verified": True, "paper_account_equity_model": "10000"}, ensure_ascii=False),
                encoding="utf-8",
            )

            config = replace(load_config(), output_dir=output_dir)
            with patch("scripts.m12_29_current_day_scan_dashboard_lib.datetime") as mocked_datetime:
                mocked_datetime.now.return_value = datetime.fromisoformat("2026-06-03T15:10:00+00:00")
                mocked_datetime.fromisoformat = datetime.fromisoformat
                panel = build_longbridge_paper_dashboard_view(config)

        self.assertEqual(panel["submitted_order_count"], "2")
        self.assertIn("2 / 2", json.dumps(panel["queue_rows"], ensure_ascii=False))

    def test_longbridge_virtual_bucket_rows_separate_new_epoch_from_old_history(self):
        realtime = {
            "virtual_capital_buckets": [
                {
                    "capital_bucket": "main",
                    "label": "主力仓",
                    "equity": "10000.00",
                    "max_total_exposure": "6000.00",
                    "max_symbol_exposure": "1500.00",
                    "used_exposure": "100.00",
                },
                {
                    "capital_bucket": "experimental",
                    "label": "实验仓",
                    "equity": "10000.00",
                    "max_total_exposure": "6000.00",
                    "max_symbol_exposure": "1000.00",
                    "used_exposure": "0.00",
                },
            ]
        }
        epoch = {"test_epoch_id": "unit-new-epoch", "status": "active"}
        ledger = [
            {
                "test_epoch_id": "unit-new-epoch",
                "capital_bucket": "main",
                "side": "buy",
                "submission_status": "submitted",
                "notional": "100.00",
            },
            {
                "test_epoch_id": "old-epoch",
                "capital_bucket": "main",
                "side": "buy",
                "submission_status": "submitted",
                "notional": "100.00",
            },
        ]

        rows = m15_longbridge_virtual_bucket_rows(realtime, ledger, epoch)
        by_bucket = {row["capital_bucket"]: row for row in rows}

        self.assertEqual(by_bucket["main"]["submitted_buy_count"], "1")
        self.assertEqual(by_bucket["experimental"]["label"], "实验仓")
        self.assertEqual(by_bucket["old_history"]["submitted_buy_count"], "1")
        self.assertEqual(by_bucket["local_repair"]["submitted_buy_count"], "0")

    def test_longbridge_virtual_bucket_rows_prefer_configured_single_buckets_when_runtime_epoch_stale(self):
        realtime = {
            "test_epoch": {"test_epoch_id": "old-dual-bucket", "status": "active"},
            "virtual_capital_buckets": [
                {"capital_bucket": "main", "label": "主力仓", "runtime_ids": ["M10-PA-004-long-1d"]},
                {"capital_bucket": "pa002_main", "label": "002专项主力仓", "runtime_ids": ["M10-PA-002-1d", "M10-PA-002-5m"]},
            ],
        }
        configured_epoch = {
            "test_epoch_id": "m15-single-strategy-buckets-20260702",
            "status": "waiting_runtime_refresh",
        }
        configured_buckets = [
            {"capital_bucket": "pa004_long", "label": "PA004-long单仓（M10-PA-004-long-1d）", "runtime_ids": ["M10-PA-004-long-1d"]},
            {"capital_bucket": "pa002_5m", "label": "PA002-5m单仓（M10-PA-002-5m）", "runtime_ids": ["M10-PA-002-5m"]},
            {"capital_bucket": "experimental", "label": "统一实验仓（M10-PA-002-1d）", "runtime_ids": ["M10-PA-002-1d"]},
        ]

        rows = m15_longbridge_virtual_bucket_rows(
            realtime,
            [],
            {"test_epoch_id": "old-dual-bucket", "status": "active"},
            configured_bucket_defs=configured_buckets,
            configured_epoch=configured_epoch,
        )
        by_bucket = {row["capital_bucket"]: row for row in rows}

        self.assertIn("pa004_long", by_bucket)
        self.assertIn("pa002_5m", by_bucket)
        self.assertIn("experimental", by_bucket)
        self.assertNotIn("main", by_bucket)
        self.assertNotIn("pa002_main", by_bucket)
        self.assertEqual(by_bucket["pa002_5m"]["test_epoch_id"], "m15-single-strategy-buckets-20260702")
        self.assertEqual(by_bucket["pa002_5m"]["epoch_status"], "waiting_runtime_refresh")
        self.assertIn("新单策略仓", by_bucket["pa002_5m"]["note"])

    def test_longbridge_virtual_bucket_rows_count_only_actual_fills_when_reconciled(self):
        realtime = {
            "virtual_capital_buckets": [
                {
                    "capital_bucket": "main",
                    "label": "主力仓",
                    "equity": "10000.00",
                    "max_total_exposure": "6000.00",
                    "max_symbol_exposure": "1500.00",
                    "used_exposure": "999.00",
                }
            ]
        }
        epoch = {"test_epoch_id": "epoch-live", "status": "active"}
        ledger = [
            {
                "test_epoch_id": "epoch-live",
                "capital_bucket": "main",
                "side": "buy",
                "submission_status": "submitted",
                "notional": "999.00",
            }
        ]
        reconciliation = {
            "current_holdings": [
                {"symbol": "AAPL.US", "quantity": "1", "market_price": "110.00", "cost_price": "100.00"}
            ]
        }
        order_reconciliation = {
            "rows": [
                {
                    "test_epoch_id": "epoch-live",
                    "capital_bucket": "main",
                    "symbol": "AAPL",
                    "side": "buy",
                    "executed_quantity": "1",
                    "executed_price": "100.00",
                    "price": "100.00",
                    "counts_for_performance": True,
                    "attribution_status": "matched_m15_realtime_ledger",
                },
                {
                    "test_epoch_id": "epoch-live",
                    "capital_bucket": "main",
                    "symbol": "MSFT",
                    "side": "buy",
                    "quantity": "1",
                    "price": "300.00",
                    "counts_for_performance": False,
                    "attribution_status": "matched_m15_realtime_ledger",
                },
            ]
        }

        rows = m15_longbridge_virtual_bucket_rows(realtime, ledger, epoch, reconciliation, order_reconciliation)
        by_bucket = {row["capital_bucket"]: row for row in rows}

        self.assertEqual(by_bucket["main"]["submitted_buy_count"], "1")
        self.assertEqual(by_bucket["main"]["used_exposure"], "110.00")
        self.assertEqual(by_bucket["main"]["current_position_total_pnl"], "10.00")
        self.assertEqual(by_bucket["main"]["realized_pnl"], "0.00")
        self.assertEqual(by_bucket["main"]["trading_total_pnl"], "10.00")
        self.assertEqual(by_bucket["main"]["bucket_today_pnl"], "0.00")
        self.assertEqual(by_bucket["main"]["total_pnl"], "10.00")
        self.assertIn("未成交请求不计入表现", by_bucket["main"]["note"])

    def test_unfilled_order_diagnostics_hide_raw_order_ids_from_dashboard(self):
        rows = m15_unfilled_order_diagnostic_rows(
            {
                "rows": [
                    {
                        "order_id": "1246481618579767296",
                        "symbol": "VTI",
                        "side": "buy",
                        "status": "Expired",
                        "runtime_id": "M10-PA-004-long-1d",
                        "capital_bucket": "main",
                        "diagnostic_category": "expired_price_not_touched",
                        "diagnostic_evidence": "长桥订单历史显示过期。",
                        "repair_action": "后续订单继续记录触价路径。",
                    }
                ]
            }
        )

        self.assertEqual(rows[0]["diagnostic_ref"], "未成交-1")
        self.assertNotIn("order_id", rows[0])
        self.assertNotIn("1246481618579767296", json.dumps(rows, ensure_ascii=False))

    def test_dedicated_pa002_review_requires_runtime_level_bucket_match(self):
        local_history = {
            "runtime_rows": [
                {
                    "runtime_id": "M10-PA-002-1d",
                    "timeframe": "1d",
                    "net_realized_pnl": "10.00",
                    "win_rate_percent": "40.00",
                    "profit_loss_ratio": "1.20",
                    "closed_trade_count": "5",
                },
                {
                    "runtime_id": "M10-PA-002-5m",
                    "timeframe": "5m",
                    "net_realized_pnl": "25.00",
                    "win_rate_percent": "55.00",
                    "profit_loss_ratio": "1.80",
                    "closed_trade_count": "8",
                },
            ]
        }
        longbridge = {
            "runtime_whitelist": [
                "M10-PA-004-long-1d",
                "M10-PA-002-5m",
                "M12-FTD-001-baseline-1d",
                "M12-FTD-001-loss-streak-guard-1d",
                "M10-PA-004-MBF-1d",
                "M10-PA-004-MBF-QC-1d",
                "M10-PA-013-5m",
                "M10-PA-011-ORB-R1-5m",
            ],
            "virtual_capital_bucket_definitions": [
                {"capital_bucket": "pa004_long", "label": "PA004-long单仓（M10-PA-004-long-1d）", "runtime_ids": ["M10-PA-004-long-1d"]},
                {"capital_bucket": "pa002_5m", "label": "PA002-5m单仓（M10-PA-002-5m）", "runtime_ids": ["M10-PA-002-5m"]},
                {"capital_bucket": "ftd_baseline", "label": "FTD原版单仓（M12-FTD-001-baseline-1d）", "runtime_ids": ["M12-FTD-001-baseline-1d"]},
                {"capital_bucket": "ftd_loss_streak", "label": "FTD连亏保护单仓（M12-FTD-001-loss-streak-guard-1d）", "runtime_ids": ["M12-FTD-001-loss-streak-guard-1d"]},
                {"capital_bucket": "pa004_mbf", "label": "PA004-MBF单仓（M10-PA-004-MBF-1d）", "runtime_ids": ["M10-PA-004-MBF-1d"]},
                {"capital_bucket": "pa004_mbf_qc", "label": "PA004-MBF-QC单仓（M10-PA-004-MBF-QC-1d）", "runtime_ids": ["M10-PA-004-MBF-QC-1d"]},
                {"capital_bucket": "pa013_5m", "label": "PA013-5m单仓（M10-PA-013-5m）", "runtime_ids": ["M10-PA-013-5m"]},
                {"capital_bucket": "pa011_orb_r1", "label": "PA011-ORB-R1单仓（M10-PA-011-ORB-R1-5m）", "runtime_ids": ["M10-PA-011-ORB-R1-5m"]},
            ],
        }

        rows = {row["runtime_id"]: row for row in build_dedicated_bucket_runtime_review_rows(local_history, longbridge)}

        self.assertEqual(rows["M10-PA-002-5m"]["review_status"], "已按运行单元复核")
        self.assertEqual(rows["M10-PA-002-5m"]["expected_bucket"], "pa002_5m")
        self.assertIn("PA002-5m单仓", rows["M10-PA-002-5m"]["longbridge_buckets"])
        self.assertEqual(rows["M12-FTD-001-loss-streak-guard-1d"]["expected_bucket"], "ftd_loss_streak")
        self.assertEqual(rows["M10-PA-004-MBF-QC-1d"]["expected_bucket"], "pa004_mbf_qc")

        broken = {
            **longbridge,
            "virtual_capital_bucket_definitions": [
                {"capital_bucket": "pa002_5m", "label": "PA002-5m单仓（M10-PA-002-5m）", "runtime_ids": ["M10-PA-002-5m"]},
            ],
        }
        broken_rows = {
            row["runtime_id"]: row for row in build_dedicated_bucket_runtime_review_rows(local_history, broken)
        }
        self.assertEqual(broken_rows["M10-PA-004-long-1d"]["review_status"], "需要修正配置")
        self.assertEqual(broken_rows["M10-PA-002-5m"]["review_status"], "已按运行单元复核")

    def _minimal_dashboard_for_html(self, longbridge_panel: dict) -> dict:
        empty_overview = {
            "starting_capital": "0.00",
            "current_equity": "0.00",
            "day_pnl": "0.00",
            "cumulative_return_percent": "0.00",
            "today_opened_count": "0",
            "today_closed_count": "0",
            "win_rate_percent": "0.00",
            "max_drawdown_percent": "0.00",
        }
        empty_timeframe = {
            "display_name": "fixture",
            "account_count": "0",
            "today_total_pnl": "0.00",
            "win_rate_percent": "0.00",
            "plain_language_note": "fixture",
            "strategy_rows": [],
        }
        return {
            "top_metrics": {},
            "summary": {"audit_only_snapshot": True, "audit_only_snapshot_note": "fixture", "data_freshness_warning": ""},
            "mainline_account_view": empty_overview,
            "experimental_account_view": empty_overview,
            "timeframe_views": {"views": {"1d": empty_timeframe, "5m": empty_timeframe}},
            "ftd001_monitor": {"plain_language_summary": "fixture", "accounts": [], "current_plain_status": "fixture", "risk_flags": []},
            "update_status": {
                "beijing_time": "2026-06-02 22:02:06 CST",
                "wall_clock_beijing_time": "2026-06-02 22:02:06 CST",
                "freshness_state": "fresh",
                "dashboard_age_seconds": "0",
                "new_york_time": "2026-06-02 10:02:06 EDT",
                "market_status": "美股常规交易时段",
                "runtime_status": "fixture",
                "session_liveness": "alive",
                "supervisor_process_alive": "true",
                "last_heartbeat_beijing_time": "2026-06-02 22:02:06 CST",
                "heartbeat_age_seconds": "0",
            },
            "strategy_scorecard_rows": [],
            "strategy_detail_views": {},
            "trade_rows": [],
            "signal_watchlist": [],
            "reference_watchlist": [],
            "broker_terminal_view": {"top_status": {}, "strategy_accounts": [], "pa004_comparison": {"rows": []}, "watchlists": {"groups": []}, "news_panel": {}},
            "extended_session_monitor": {
                "plain_language_summary": "fixture",
                "threshold_percent": "2.00",
                "premarket_rows": [],
                "postmarket_rows": [],
                "focus_hits": [],
            },
            "longbridge_paper_account": longbridge_panel,
            "strategy_status_rows": [],
            "supporting_rule_ab_results": {"rows": []},
            "account_input_audit": {"rows": []},
        }

    def test_broker_terminal_view_has_accounts_watchlists_news_and_pa004_split(self):
        _, result, output_dir = self.run_stage()
        dashboard = result["dashboard"]
        terminal = result["dashboard"]["broker_terminal_view"]
        self.assertEqual(terminal["schema_version"], "m14.1.broker-terminal-view.v1")
        self.assertEqual(terminal["top_status"]["fully_ready_for_trading_display"], "false")
        self.assertNotIn("legacy_history_metric_policy", dashboard)
        self.assertNotIn("legacy_history_metric_policy", terminal)
        self.assertEqual(len(terminal["strategy_accounts"]), len(ACCOUNT_SPECS))
        for row in dashboard["strategy_scorecard_rows"]:
            self.assertFalse(any(key.startswith("historical_") for key in row))
            self.assertNotIn("legacy_history_metric_planning_input", row)
        for row in terminal["strategy_accounts"]:
            for key in (
                "today_total_pnl",
                "today_realized_pnl",
                "today_unrealized_pnl",
                "total_pnl",
                "equity",
                "open_position_count",
                "today_signal_count",
                "today_opened_count",
                "today_closed_count",
                "m14_decision",
                "paper_trial_gate",
            ):
                self.assertIn(key, row)
        group_by_id = {group["group_id"]: group for group in terminal["watchlists"]["groups"]}
        self.assertEqual(
            [row["symbol"] for row in group_by_id["magnificent_seven"]["rows"]],
            ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA"],
        )
        self.assertIn("MU", [row["symbol"] for row in group_by_id["memory_flash"]["rows"]])
        self.assertIn("SNDK", [row["symbol"] for row in group_by_id["memory_flash"]["rows"]])
        self.assertIn("QCOM", [row["symbol"] for row in group_by_id["ai_chips"]["rows"]])
        self.assertTrue(group_by_id["strategy_active"]["rows"])
        self.assertEqual(group_by_id["strategy_active"]["generated_from"], "当日信号、持仓和账户账本自动聚合")
        for group in terminal["watchlists"]["groups"]:
            for row in group["rows"]:
                if row["strategy_signal_count"] == "0":
                    self.assertEqual(row["strategy_ids"], "")
                if row["strategy_ids"]:
                    self.assertGreater(int(row["strategy_signal_count"]), 0)
                    signal_ids = {item.strip() for item in row["strategy_ids"].split(",") if item.strip()}
                    related_ids = {item.strip() for item in row["related_strategy_ids"].split(",") if item.strip()}
                    self.assertTrue(signal_ids.issubset(related_ids))
        pa004_ids = {row["runtime_id"] for row in terminal["pa004_comparison"]["rows"]}
        self.assertEqual(pa004_ids, {"M10-PA-004-long-1d", "M10-PA-004-MBF-1d", "M10-PA-004-MBF-QC-1d"})
        self.assertFalse(terminal["news_panel"]["news_drives_trading_signal"])
        self.assertIn("audit_drawer", terminal)
        html = (output_dir / "m12_32_minute_readonly_dashboard.html").read_text(encoding="utf-8")
        self.assertNotIn("> %<", html)
        self.assertNotIn("% / %", html)
        self.assertNotIn("historical_net_profit", json.dumps(dashboard, ensure_ascii=False))
        self.assertNotIn("历史净利润", html)
        self.assertNotIn("历史收益", html)

    def test_audit_only_snapshot_uses_notice_not_data_refresh_failure_panel(self):
        from scripts.m12_29_current_day_scan_dashboard_lib import build_dashboard_html

        empty_overview = {
            "starting_capital": "0.00",
            "current_equity": "0.00",
            "day_pnl": "0.00",
            "cumulative_return_percent": "0.00",
            "today_opened_count": "0",
            "today_closed_count": "0",
            "win_rate_percent": "0.00",
            "max_drawdown_percent": "0.00",
        }
        empty_timeframe = {
            "display_name": "fixture",
            "account_count": "0",
            "today_total_pnl": "0.00",
            "win_rate_percent": "0.00",
            "plain_language_note": "fixture",
            "strategy_rows": [],
        }
        dashboard = {
            "top_metrics": {},
            "summary": {
                "audit_only_snapshot": True,
                "audit_only_snapshot_note": "市场状态由 M12.47 守护器覆盖为 非交易日等待；当前面板是上一有效审计快照，不代表新的交易日测试。",
                "data_freshness_warning": "",
            },
            "mainline_account_view": empty_overview,
            "experimental_account_view": empty_overview,
            "timeframe_views": {"views": {"1d": empty_timeframe, "5m": empty_timeframe}},
            "ftd001_monitor": {"plain_language_summary": "fixture", "accounts": [], "current_plain_status": "fixture", "risk_flags": []},
            "update_status": {
                "beijing_time": "2026-05-26 02:55:04 CST",
                "wall_clock_beijing_time": "2026-05-26 02:55:04 CST",
                "freshness_state": "supervisor_idle",
                "dashboard_age_seconds": "0",
                "new_york_time": "2026-05-25 14:55:04 EDT",
                "market_status": "非交易日等待",
                "runtime_status": "非交易日等待",
                "session_liveness": "idle",
                "supervisor_process_alive": "true",
                "last_heartbeat_beijing_time": "2026-05-26 02:55:04 CST",
                "heartbeat_age_seconds": "0",
            },
            "strategy_scorecard_rows": [],
            "strategy_detail_views": {},
            "trade_rows": [],
            "signal_watchlist": [],
            "reference_watchlist": [],
            "broker_terminal_view": {"top_status": {}, "strategy_accounts": [], "pa004_comparison": {"rows": []}, "watchlists": {"groups": []}, "news_panel": {}},
            "extended_session_monitor": {
                "plain_language_summary": "fixture",
                "threshold_percent": "2.00",
                "premarket_rows": [],
                "postmarket_rows": [],
                "focus_hits": [],
            },
            "strategy_status_rows": [],
            "supporting_rule_ab_results": {"rows": []},
            "account_input_audit": {"rows": []},
        }
        html = build_dashboard_html(load_config(), dashboard)
        self.assertIn("非交易日审计快照", html)
        self.assertNotIn("<h2>数据刷新告警</h2>", html)

    def test_longbridge_not_degraded_scan_gap_renders_as_notice_not_warning(self):
        warning = build_dashboard_data_freshness_warning(
            quote_source="longbridge_quote_readonly",
            current_day_runtime_ready=True,
            current_day_scan_complete=False,
            daily_ready_symbols=0,
            current_5m_ready_symbols=147,
            active_universe_symbol_count=147,
            runtime_readiness_note="日线沿用缓存。",
        )
        dashboard = self._minimal_dashboard_for_html({})
        dashboard["summary"] = {
            "audit_only_snapshot": False,
            "data_freshness_warning": warning,
            "quote_source": "longbridge_quote_readonly",
            "current_day_runtime_ready": True,
            "current_day_scan_complete": False,
            "active_universe_daily_ready_symbols": 0,
            "active_universe_current_5m_ready_symbols": 147,
            "active_universe_symbol_count": 147,
            "runtime_readiness_note": "日线沿用缓存。",
        }

        html = build_dashboard_html(load_config(), dashboard)

        self.assertTrue(is_longbridge_non_degraded_freshness_notice(warning))
        self.assertIn("<h2>数据刷新提示</h2>", html)
        self.assertNotIn("<h2>数据刷新告警</h2>", html)

    def test_mainline_and_experimental_accounts_are_separated(self):
        _, result, _ = self.run_stage()
        dashboard = result["dashboard"]
        mainline_ids = {row["strategy_id"] for row in dashboard["mainline_accounts"]}
        experimental_ids = {row["strategy_id"] for row in dashboard["experimental_accounts"]}
        rescue_ids = {row["strategy_id"] for row in dashboard["rescue_accounts"]}
        self.assertIn("M10-PA-004", mainline_ids)
        self.assertIn("M10-PA-005", experimental_ids)
        self.assertIn("M10-PA-007", experimental_ids)
        self.assertIn(PA004_MOMENTUM_VARIANT_ID, experimental_ids)
        self.assertIn(PA004_MOMENTUM_QUALITY_VARIANT_ID, experimental_ids)
        self.assertIn("M10-PA-013", experimental_ids)
        self.assertIn("M10-PA-001-m14-modify-20260522", rescue_ids)
        self.assertIn("M10-PA-002-m14-modify-20260522", rescue_ids)
        self.assertIn(PA004_MOMENTUM_QUALITY_RESCUE_VARIANT_ID, rescue_ids)
        self.assertIn("M10-PA-007-m14-modify-20260522", rescue_ids)
        self.assertIn(PA008_BROKER_RISK_CAP_SHADOW_VARIANT_ID, rescue_ids)
        self.assertIn("M10-PA-009-m14-modify-20260522", rescue_ids)
        self.assertIn("M10-PA-012-m14-modify-20260522", rescue_ids)
        self.assertIn(PA012_TARGET_STOP_NORMALIZED_RESCUE_VARIANT_ID, rescue_ids)
        self.assertIn("M10-PA-013-m14-modify-20260522", rescue_ids)
        self.assertIn("M12-FTD-001-m14-modify-20260522", rescue_ids)
        self.assertIn(PA011_ORB_REBUILD_VARIANT_ID, rescue_ids)
        self.assertNotIn("M10-PA-005", mainline_ids)
        self.assertNotIn("M10-PA-004", experimental_ids)
        self.assertEqual(
            result["run_status"]["daily_realtime_strategy_ids"],
            ["M10-PA-001", "M10-PA-002", "M10-PA-004", "M10-PA-012", "M12-FTD-001"],
        )
        self.assertEqual(
            result["run_status"]["experimental_strategy_ids"],
            [
                "M10-PA-005",
                "M10-PA-007",
                PA004_MOMENTUM_VARIANT_ID,
                PA004_MOMENTUM_QUALITY_VARIANT_ID,
                "M10-PA-008",
                "M10-PA-009",
                "M10-PA-011",
                "M10-PA-013",
            ],
        )
        self.assertEqual(
            result["run_status"]["rescue_strategy_ids"],
            [
                "M10-PA-001-m14-modify-20260522",
                "M10-PA-002-m14-modify-20260522",
                PA004_MOMENTUM_QUALITY_RESCUE_VARIANT_ID,
                "M10-PA-007-m14-modify-20260522",
                PA008_BROKER_RISK_CAP_SHADOW_VARIANT_ID,
                "M10-PA-009-m14-modify-20260522",
                "M10-PA-012-m14-modify-20260522",
                PA012_TARGET_STOP_NORMALIZED_RESCUE_VARIANT_ID,
                "M10-PA-013-m14-modify-20260522",
                "M12-FTD-001-m14-modify-20260522",
                PA011_ORB_REBUILD_VARIANT_ID,
            ],
        )
        self.assertEqual(
            result["gate_recheck"]["candidate_strategy_ids"],
            ["M10-PA-001", "M10-PA-002", "M10-PA-004", "M10-PA-012", "M12-FTD-001"],
        )

    def test_ftd_monitor_shows_baseline_and_loss_streak_guard(self):
        _, result, output_dir = self.run_stage()
        monitor = result["dashboard"]["ftd001_monitor"]
        self.assertEqual([row["variant_id"] for row in monitor["accounts"]], ["baseline", "loss_streak_guard"])
        self.assertIn("原版", monitor["plain_language_summary"])
        self.assertIn("连亏保护", monitor["plain_language_summary"])
        self.assertTrue((output_dir / "m12_36_ftd001_monitor.json").exists())
        self.assertTrue((output_dir / "m12_46_supporting_rule_ab_results.json").exists())

    def test_runtime_trade_view_and_detail_views_use_runtime_id_not_real_account_terms(self):
        _, result, output_dir = self.run_stage()
        dashboard = result["dashboard"]
        self.assertTrue(dashboard["trade_rows"])
        self.assertIn("runtime_id", dashboard["trade_rows"][0])
        self.assertNotIn("account_id", dashboard["trade_rows"][0])
        detail_views = dashboard["strategy_detail_views"]
        self.assertTrue(detail_views)
        first_key = next(iter(detail_views))
        self.assertTrue(first_key)
        text = (output_dir / "m12_29_trade_view.csv").read_text(encoding="utf-8")
        self.assertIn("runtime_id", text)
        self.assertNotIn("account_id", text)

    def test_pa004_mainline_uses_formal_detector_input_and_reference_rows_stay_outside_runtime_watchlist(self):
        _, result, output_dir = self.run_stage()
        dashboard = result["dashboard"]
        audit_rows = {row["runtime_id"]: row for row in dashboard["account_input_audit"]["rows"]}
        self.assertEqual(audit_rows["M10-PA-004-long-1d"]["input_source_type"], "formal_detector_entry")
        self.assertEqual(audit_rows["M10-PA-004-long-1d"]["formal_input_stream"], "true")
        runtime_watchlist = dashboard["signal_watchlist"]
        self.assertTrue(all(row.get("signal_source_type") != "reference_observation" for row in runtime_watchlist))
        self.assertTrue(all("观察版" not in row.get("review_status", "") for row in runtime_watchlist if row["strategy_id"] == "M10-PA-004"))
        reference_watchlist = dashboard["reference_watchlist"]
        self.assertTrue(all(row.get("signal_source_type") == "reference_observation" for row in reference_watchlist))
        audit_path = output_dir / "m12_46_account_input_audit.json"
        self.assertTrue(audit_path.exists())

    def test_pa004_formal_detector_accepts_chinese_and_english_long_direction(self):
        self.assertTrue(pa004_event_is_long({"direction": "long"}))
        self.assertTrue(pa004_event_is_long({"direction": "看涨"}))
        self.assertFalse(pa004_event_is_long({"direction": "short"}))
        self.assertFalse(pa004_event_is_long({"direction": "看跌"}))

    def test_pa004_momentum_breakout_variant_is_separate_from_baseline(self):
        bars = [
            SimpleNamespace(
                timestamp="2026-05-08T16:00:00-04:00",
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
            ),
            SimpleNamespace(
                timestamp="2026-05-11T16:00:00-04:00",
                open=Decimal("104"),
                high=Decimal("110"),
                low=Decimal("103"),
                close=Decimal("108"),
            ),
        ]
        signal = pa004_momentum_breakout_signal("QCOM", bars, date.fromisoformat("2026-05-11"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal["entry"], Decimal("108"))
        self.assertLess(signal["stop"], signal["entry"])
        self.assertGreater(signal["target"], signal["entry"])
        quality_signal = pa004_momentum_breakout_quality_signal("QCOM", bars, date.fromisoformat("2026-05-11"))
        self.assertIsNotNone(quality_signal)
        self.assertEqual(quality_signal["entry"], Decimal("108"))
        self.assertLess(quality_signal["target"], signal["target"])
        self.assertIsNone(pa004_momentum_breakout_signal("TQQQ", bars, date.fromisoformat("2026-05-11")))

        lower_quality_bars = [
            SimpleNamespace(
                timestamp="2026-05-08T16:00:00-04:00",
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
            ),
            SimpleNamespace(
                timestamp="2026-05-11T16:00:00-04:00",
                open=Decimal("104"),
                high=Decimal("112"),
                low=Decimal("103"),
                close=Decimal("106"),
            ),
        ]
        self.assertIsNotNone(pa004_momentum_breakout_signal("QCOM", lower_quality_bars, date.fromisoformat("2026-05-11")))
        self.assertIsNone(pa004_momentum_breakout_quality_signal("QCOM", lower_quality_bars, date.fromisoformat("2026-05-11")))

    def test_pa004_qc_rescue_adapter_is_stricter_than_parent_qc(self):
        spec = {"strategy_id": PA004_MOMENTUM_QUALITY_RESCUE_VARIANT_ID, "timeframe": "1d"}
        base_row = {
            "symbol": "QCOM",
            "direction": "看涨",
            "hypothetical_entry_price": "100.00",
            "hypothetical_target_price": "106.00",
            "signal_date": "2026-05-11",
            "latest_price_source": "longbridge_quote_readonly",
        }
        self.assertTrue(rescue_signal_filter(spec, base_row | {"hypothetical_stop_price": "96.00"}))
        self.assertFalse(rescue_signal_filter(spec, base_row | {"hypothetical_stop_price": "95.00"}))
        self.assertFalse(rescue_signal_filter(spec, base_row | {"hypothetical_target_price": "105.00", "hypothetical_stop_price": "96.00"}))
        self.assertFalse(rescue_signal_filter(spec, base_row | {"symbol": "TQQQ", "hypothetical_stop_price": "96.00"}))

    def test_pa012_target_stop_normalized_rescue_uses_shadow_1r_without_changing_frozen_rescue(self):
        base_row = {
            "symbol": "QCOM",
            "direction": "看涨",
            "hypothetical_entry_price": "100.00",
            "hypothetical_stop_price": "98.00",
            "hypothetical_target_price": "101.90",
            "signal_date": "2026-05-11",
            "signal_time": "2026-05-11T09:35:00-04:00",
            "latest_price_source": "longbridge_quote_readonly",
            "timeframe": "5m",
        }
        frozen_spec = {
            "strategy_id": "M10-PA-012-m14-modify-20260522",
            "timeframe": "5m",
            "variant_id": "m14_modify_20260522",
            "display_name": "M10-PA-012 救援五分钟账户",
        }
        shadow_spec = {
            "strategy_id": PA012_TARGET_STOP_NORMALIZED_RESCUE_VARIANT_ID,
            "timeframe": "5m",
            "variant_id": PA012_TARGET_STOP_NORMALIZED_RESCUE_RUNTIME_VARIANT_ID,
            "display_name": "M10-PA-012 1.0R目标修复影子账户",
        }

        self.assertFalse(rescue_signal_filter(frozen_spec, base_row))
        filtered = filter_rescue_signal_rows(shadow_spec, [base_row])

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["hypothetical_target_price"], "102.00")
        self.assertEqual(filtered[0]["target_stop_original_target_price"], "101.90")
        self.assertEqual(filtered[0]["target_stop_normalized_reward_r"], "1.00")
        self.assertEqual(filtered[0]["signal_source_type"], PA012_TARGET_STOP_NORMALIZED_RESCUE_ADAPTER_ID)
        self.assertIn("1.0R", filtered[0]["review_status"])
        self.assertIn("frozen rescue runtime", filtered[0]["review_status"])

    def test_pa008_broker_risk_cap_shadow_accepts_short_and_caps_simulated_risk(self):
        base_row = {
            "symbol": "ADBE",
            "direction": "看跌",
            "hypothetical_entry_price": "245.89",
            "hypothetical_stop_price": "265.09",
            "hypothetical_target_price": "207.49",
            "hypothetical_quantity": "5.2469",
            "signal_date": "2026-05-22",
            "signal_time": "2026-05-22T09:32:16-04:00",
            "latest_price": "245.89",
            "latest_price_source": "longbridge_quote_readonly",
            "timeframe": "1d",
        }
        shadow_spec = {
            "account_id": f"{PA008_BROKER_RISK_CAP_SHADOW_VARIANT_ID}-1d",
            "strategy_id": PA008_BROKER_RISK_CAP_SHADOW_VARIANT_ID,
            "timeframe": "1d",
            "lane": "rescue",
            "variant_id": PA008_BROKER_RISK_CAP_SHADOW_RUNTIME_VARIANT_ID,
            "display_name": "M10-PA-008 风险上限影子账户",
        }

        filtered = filter_rescue_signal_rows(shadow_spec, [base_row])

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["direction"], "看跌")
        self.assertEqual(filtered[0]["signal_source_type"], PA008_BROKER_RISK_CAP_SHADOW_ADAPTER_ID)
        self.assertEqual(filtered[0]["hypothetical_quantity"], "5.2083")
        self.assertEqual(filtered[0]["broker_risk_cap_quantity_cap"], "5.2083")
        self.assertIn("100.00", filtered[0]["review_status"])
        account = bootstrap_account_state(shadow_spec)
        account["cash"] = "20200.00"
        account["equity"] = "20200.00"
        ledger_rows, opened = open_new_positions(
            account,
            shadow_spec,
            filtered,
            date.fromisoformat("2026-05-22"),
            "2026-05-22T20:30:00Z",
        )

        self.assertEqual(opened, 1)
        self.assertEqual(account["open_positions"][0]["quantity"], "5.2083")
        self.assertEqual(account["open_positions"][0]["broker_risk_cap_amount"], "100.00")
        self.assertEqual(account["open_positions"][0]["broker_risk_cap_applied"], "true")
        self.assertEqual(ledger_rows[0]["broker_risk_cap_uncapped_risk_budget"], "101.00")
        self.assertEqual(ledger_rows[0]["broker_risk_cap_uncapped_quantity"], "5.2604")

    def test_pa011_orb_rebuild_requires_failed_opening_range_retest(self):
        bars = [
            SimpleNamespace(timestamp="2026-05-11T09:30:00-04:00", open=Decimal("100.00"), high=Decimal("100.60"), low=Decimal("99.50"), close=Decimal("100.10")),
            SimpleNamespace(timestamp="2026-05-11T09:35:00-04:00", open=Decimal("100.10"), high=Decimal("100.90"), low=Decimal("99.70"), close=Decimal("100.30")),
            SimpleNamespace(timestamp="2026-05-11T09:40:00-04:00", open=Decimal("100.30"), high=Decimal("101.00"), low=Decimal("99.80"), close=Decimal("100.50")),
            SimpleNamespace(timestamp="2026-05-11T09:45:00-04:00", open=Decimal("100.50"), high=Decimal("100.80"), low=Decimal("99.60"), close=Decimal("100.20")),
            SimpleNamespace(timestamp="2026-05-11T09:50:00-04:00", open=Decimal("100.20"), high=Decimal("100.70"), low=Decimal("99.40"), close=Decimal("99.90")),
            SimpleNamespace(timestamp="2026-05-11T09:55:00-04:00", open=Decimal("99.90"), high=Decimal("100.40"), low=Decimal("99.00"), close=Decimal("99.70")),
            SimpleNamespace(timestamp="2026-05-11T10:00:00-04:00", open=Decimal("99.20"), high=Decimal("99.90"), low=Decimal("98.70"), close=Decimal("99.40")),
            SimpleNamespace(timestamp="2026-05-11T10:05:00-04:00", open=Decimal("99.50"), high=Decimal("100.80"), low=Decimal("99.30"), close=Decimal("100.40")),
        ]
        signal = pa011_orb_rebuild_signal("QCOM", bars, date.fromisoformat("2026-05-11"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "long")
        self.assertEqual(signal["entry"], Decimal("100.40"))
        self.assertLess(signal["stop"], signal["entry"])
        self.assertGreater(signal["target"], signal["entry"])
        self.assertIsNone(pa011_orb_rebuild_signal("TQQQ", bars, date.fromisoformat("2026-05-11")))

    def test_all_runtime_accounts_are_marked_as_formal_input_streams(self):
        _, result, _ = self.run_stage()
        rows = result["dashboard"]["account_input_audit"]["rows"]
        self.assertEqual(len(rows), len(ACCOUNT_SPECS))
        self.assertTrue(all(row["watchlist_only"] == "false" for row in rows))
        mainline_rows = [row for row in rows if row["lane"] == "mainline"]
        experimental_rows = [row for row in rows if row["lane"] == "experimental"]
        rescue_rows = [row for row in rows if row["lane"] == "rescue"]
        self.assertTrue(all(row["formal_input_stream"] == "true" for row in mainline_rows))
        self.assertTrue(all(row["current_scanner_connected"] == "true" for row in mainline_rows))
        self.assertTrue(all(row["formal_input_stream"] == "true" for row in experimental_rows))
        self.assertTrue(all(row["current_scanner_connected"] == "true" for row in experimental_rows))
        self.assertEqual(
            {row["runtime_id"] for row in rescue_rows},
            {
                "M10-PA-001-m14-modify-20260522-1d",
                "M10-PA-002-m14-modify-20260522-1d",
                "M10-PA-004-MBF-QC-m14-modify-20260522-1d",
                "M10-PA-007-m14-modify-20260522-1d",
                f"{PA008_BROKER_RISK_CAP_SHADOW_VARIANT_ID}-1d",
                "M10-PA-009-m14-modify-20260522-1d",
                "M10-PA-012-m14-modify-20260522-5m",
                f"{PA012_TARGET_STOP_NORMALIZED_RESCUE_VARIANT_ID}-5m",
                "M10-PA-013-m14-modify-20260522-1d",
                "M10-PA-013-m14-modify-20260522-5m",
                "M12-FTD-001-m14-modify-20260522-1d",
                "M10-PA-011-ORB-R1-5m",
            },
        )
        self.assertTrue(all(row["formal_input_stream"] == "true" for row in rescue_rows))
        self.assertTrue(all(row["current_scanner_connected"] == "true" for row in rescue_rows))
        rescue_source_by_runtime = {row["runtime_id"]: row["input_source_type"] for row in rescue_rows}
        self.assertEqual(
            rescue_source_by_runtime["M10-PA-004-MBF-QC-m14-modify-20260522-1d"],
            PA004_MOMENTUM_QUALITY_RESCUE_ADAPTER_ID,
        )
        self.assertEqual(
            rescue_source_by_runtime[f"{PA008_BROKER_RISK_CAP_SHADOW_VARIANT_ID}-1d"],
            PA008_BROKER_RISK_CAP_SHADOW_ADAPTER_ID,
        )
        self.assertEqual(
            rescue_source_by_runtime["M10-PA-011-ORB-R1-5m"],
            PA011_ORB_REBUILD_ADAPTER_ID,
        )
        self.assertEqual(
            rescue_source_by_runtime["M10-PA-012-m14-modify-20260522-5m"],
            PA012_ORB_QUALITY_RESCUE_ADAPTER_ID,
        )
        self.assertEqual(
            rescue_source_by_runtime[f"{PA012_TARGET_STOP_NORMALIZED_RESCUE_VARIANT_ID}-5m"],
            PA012_TARGET_STOP_NORMALIZED_RESCUE_ADAPTER_ID,
        )
        self.assertTrue(
            all(
                row["input_source_type"] == "m14_rescue_parent_quality_filter_adapter"
                for row in rescue_rows
                if row["runtime_id"] not in {
                    "M10-PA-004-MBF-QC-m14-modify-20260522-1d",
                    f"{PA008_BROKER_RISK_CAP_SHADOW_VARIANT_ID}-1d",
                    "M10-PA-011-ORB-R1-5m",
                    "M10-PA-012-m14-modify-20260522-5m",
                    f"{PA012_TARGET_STOP_NORMALIZED_RESCUE_VARIANT_ID}-5m",
                }
            )
        )
        self.assertTrue(
            all(row["input_status"] in {"connected_with_signal_today", "connected_zero_signal_today"} for row in experimental_rows)
        )
        self.assertTrue(
            all(row["input_status"] in {"connected_with_signal_today", "connected_zero_signal_today"} for row in rescue_rows)
        )

    def test_postmarket_runtime_uses_postmarket_wording_and_runtime_ready_note(self):
        _, result, _ = self.run_stage(generated_at="2026-05-06T23:59:17Z")
        summary = result["summary"]
        dashboard = result["dashboard"]
        observer = dashboard["codex_observer"]
        self.assertEqual(summary["market_session"]["status"], "盘后")
        self.assertTrue(summary["current_day_runtime_ready"])
        self.assertIsInstance(summary["current_day_scan_complete"], bool)
        self.assertTrue(summary["runtime_readiness_note"])
        self.assertIn("盘后异动", summary["plain_language_result"])
        self.assertNotIn("盘前异动 6 条", observer["recommended_codex_message"])
        self.assertIn("盘后只读快照", observer["recommended_codex_message"])
        self.assertEqual(dashboard["extended_session_monitor"]["active_session"], "盘后")

    def test_observation_lane_does_not_claim_unwired_experimental_accounts_are_running(self):
        _, result, _ = self.run_stage()
        lane = result["dashboard"]["observation_test_lane"]
        self.assertIn("已接入正式输入流", lane["plain_language_result"])

    def test_observed_trading_days_accumulate_by_new_york_trading_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_29"
            self.run_stage(output_dir=output_dir, generated_at="2026-04-29T14:00:00Z")
            _, result_same_day, _ = self.run_stage(output_dir=output_dir, generated_at="2026-04-29T18:00:00Z")
            _, result_next_day, _ = self.run_stage(output_dir=output_dir, generated_at="2026-04-30T14:00:00Z")
        self.assertEqual(result_same_day["run_status"]["observed_trading_days"], 1)
        self.assertEqual(result_next_day["run_status"]["observed_trading_days"], 2)

    def test_success_then_degraded_rerun_does_not_roll_back_observed_trading_days(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_29"
            config, _, _ = self.run_stage(output_dir=output_dir, generated_at="2026-04-29T14:00:00Z")
            degraded_runtime = advance_account_runtime(
                config,
                generated_at="2026-04-29T18:00:00Z",
                scan_date=date.fromisoformat("2026-04-29"),
                trade_rows=[],
                pa004_formal_rows=[],
                closure_rows=[],
                current_day_runtime_ready=False,
            )
            state = json.loads((output_dir / "m12_46_account_runtime_state.json").read_text(encoding="utf-8"))
        self.assertEqual(build_accountized_run_status(config, degraded_runtime)["observed_trading_days"], 1)
        self.assertTrue(state["trading_day_registry"]["2026-04-29"]["counted"])
        self.assertFalse(state["trading_day_registry"]["2026-04-29"]["last_run_complete"])

    def test_today_closed_count_uses_new_york_trading_day_not_utc_calendar_day(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_29"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            spec = next(item for item in ACCOUNT_SPECS if item["account_id"] == "M10-PA-001-1d")
            account = bootstrap_account_state(spec)
            account["cash"] = "19000.00"
            account["open_positions"] = [
                {
                    "position_id": "manual-close-test",
                    "signal_id": "manual-close-test",
                    "strategy_id": spec["strategy_id"],
                    "runtime_id": spec["account_id"],
                    "display_name": spec["display_name"],
                    "lane": spec["lane"],
                    "timeframe": spec["timeframe"],
                    "symbol": "SPY",
                    "direction": "long",
                    "signal_time": "2026-04-28T19:30:00Z",
                    "signal_date": "2026-04-28",
                    "opened_at": "2026-04-28T19:35:00Z",
                    "entry_price": "100.00",
                    "stop_price": "97.00",
                    "target_price": "108.00",
                    "latest_price": "95.00",
                    "latest_price_source": "longbridge_quote_readonly",
                    "quantity": "10.0000",
                    "reserved_notional": "1000.00",
                    "current_pnl": "0.00",
                    "current_state": "持仓中",
                    "review_status": "test",
                    "risk_level": "medium",
                    "source_refs": "manual",
                    "spec_ref": "manual",
                }
            ]
            state = {
                "schema_version": "m12.46.account-runtime-state.v1",
                "stage": "M12.46.accountized_realtime_testing",
                "starting_capital": "20000.00",
                "risk_rate": "0.005",
                "accounts": {spec["account_id"]: account},
                "trading_day_registry": {},
            }
            (output_dir / "m12_46_account_runtime_state.json").write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            runtime = advance_account_runtime(
                config,
                generated_at="2026-04-29T01:05:00Z",
                scan_date=date.fromisoformat("2026-04-28"),
                trade_rows=[
                    {
                        "symbol": "SPY",
                        "latest_price": "95.00",
                        "latest_price_source": "longbridge_quote_readonly",
                    }
                ],
                pa004_formal_rows=[],
                closure_rows=[],
                current_day_runtime_ready=False,
            )
        row = next(item for item in runtime["account_rows"] if item["runtime_id"] == spec["account_id"])
        close_row = next(item for item in runtime["new_trade_ledger_rows"] if item["event_type"] == "close")
        self.assertEqual(row["today_closed_count"], "1")
        self.assertEqual(row["today_realized_pnl"], "-30.00")
        self.assertEqual(row["today_total_pnl"], "-30.00")
        self.assertEqual(close_row["exit_price"], "97.00")
        self.assertEqual(close_row["exit_price_source"], "longbridge_quote_readonly")

    def test_fallback_quotes_do_not_close_positions_or_expand_stop_loss(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_29"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            spec = next(item for item in ACCOUNT_SPECS if item["account_id"] == "M10-PA-001-1d")
            account = bootstrap_account_state(spec)
            account["cash"] = "19000.00"
            account["open_positions"] = [
                {
                    "position_id": "fallback-close-block-test",
                    "signal_id": "fallback-close-block-test",
                    "strategy_id": spec["strategy_id"],
                    "runtime_id": spec["account_id"],
                    "display_name": spec["display_name"],
                    "lane": spec["lane"],
                    "timeframe": spec["timeframe"],
                    "symbol": "SPY",
                    "direction": "long",
                    "signal_time": "2026-04-28T19:30:00Z",
                    "signal_date": "2026-04-28",
                    "opened_at": "2026-04-28T19:35:00Z",
                    "entry_price": "100.00",
                    "stop_price": "97.00",
                    "target_price": "108.00",
                    "latest_price": "100.00",
                    "latest_price_source": "longbridge_quote_readonly",
                    "quantity": "10.0000",
                    "reserved_notional": "1000.00",
                    "current_pnl": "0.00",
                    "current_state": "持仓中",
                    "review_status": "test",
                    "risk_level": "medium",
                    "source_refs": "manual",
                    "spec_ref": "manual",
                }
            ]
            state = {
                "schema_version": "m12.46.account-runtime-state.v1",
                "stage": "M12.46.accountized_realtime_testing",
                "starting_capital": "20000.00",
                "risk_rate": "0.005",
                "accounts": {spec["account_id"]: account},
                "trading_day_registry": {},
            }
            (output_dir / "m12_46_account_runtime_state.json").write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            runtime = advance_account_runtime(
                config,
                generated_at="2026-04-29T01:05:00Z",
                scan_date=date.fromisoformat("2026-04-28"),
                trade_rows=[
                    {
                        "symbol": "SPY",
                        "latest_price": "80.00",
                        "latest_price_source": "m12_12_cached_reference_fallback",
                    }
                ],
                pa004_formal_rows=[],
                closure_rows=[],
                current_day_runtime_ready=False,
            )
            state = json.loads((output_dir / "m12_46_account_runtime_state.json").read_text(encoding="utf-8"))
        row = next(item for item in runtime["account_rows"] if item["runtime_id"] == spec["account_id"])
        position = state["accounts"][spec["account_id"]]["open_positions"][0]
        self.assertEqual(row["today_closed_count"], "0")
        self.assertEqual(row["closed_trade_count"], "0")
        self.assertEqual(row["today_total_pnl"], "0.00")
        self.assertEqual(position["current_state"], "行情过期，暂停平仓")
        self.assertEqual(position["mark_to_market_blocker"], "stale_quote_blocked_mark_to_market")
        self.assertEqual(position["blocked_quote_source"], "m12_12_cached_reference_fallback")

    def test_full_quote_pool_marks_existing_positions_even_without_new_signal_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "m12_29"
            output_dir.mkdir(parents=True, exist_ok=True)
            config = replace(load_config(), output_dir=output_dir)
            spec = next(item for item in ACCOUNT_SPECS if item["account_id"] == "M10-PA-001-1d")
            account = bootstrap_account_state(spec)
            account["cash"] = "19000.00"
            account["open_positions"] = [
                {
                    "position_id": "quote-pool-close-test",
                    "signal_id": "quote-pool-close-test",
                    "strategy_id": spec["strategy_id"],
                    "runtime_id": spec["account_id"],
                    "display_name": spec["display_name"],
                    "lane": spec["lane"],
                    "timeframe": spec["timeframe"],
                    "symbol": "SPY",
                    "direction": "long",
                    "signal_time": "2026-04-28T19:30:00Z",
                    "signal_date": "2026-04-28",
                    "opened_at": "2026-04-28T19:35:00Z",
                    "entry_price": "100.00",
                    "stop_price": "97.00",
                    "target_price": "108.00",
                    "latest_price": "100.00",
                    "latest_price_source": "longbridge_quote_readonly",
                    "quantity": "10.0000",
                    "reserved_notional": "1000.00",
                    "current_pnl": "0.00",
                    "current_state": "持仓中",
                    "review_status": "test",
                    "risk_level": "medium",
                    "source_refs": "manual",
                    "spec_ref": "manual",
                }
            ]
            state = {
                "schema_version": "m12.46.account-runtime-state.v1",
                "stage": "M12.46.accountized_realtime_testing",
                "starting_capital": "20000.00",
                "risk_rate": "0.005",
                "accounts": {spec["account_id"]: account},
                "trading_day_registry": {},
            }
            (output_dir / "m12_46_account_runtime_state.json").write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            runtime = advance_account_runtime(
                config,
                generated_at="2026-04-29T01:05:00Z",
                scan_date=date.fromisoformat("2026-04-28"),
                trade_rows=[],
                pa004_formal_rows=[],
                closure_rows=[],
                current_day_runtime_ready=True,
                quotes={
                    "SPY": {
                        "latest_price": "95.00",
                        "quote_source": "longbridge_quote_readonly",
                    }
                },
            )
        row = next(item for item in runtime["account_rows"] if item["runtime_id"] == spec["account_id"])
        close_row = next(item for item in runtime["new_trade_ledger_rows"] if item["event_type"] == "close")
        self.assertEqual(row["today_closed_count"], "1")
        self.assertEqual(row["today_realized_pnl"], "-30.00")
        self.assertEqual(close_row["exit_price"], "97.00")
        self.assertEqual(close_row["exit_price_source"], "longbridge_quote_readonly")

    def test_quote_lookup_keeps_live_quote_over_stale_trade_row(self):
        lookup = build_quote_lookup(
            trade_rows=[
                {
                    "symbol": "INTC",
                    "latest_price": "84.99",
                    "latest_price_source": "m12_12_cached_reference_fallback",
                }
            ],
            pa004_formal_rows=[],
            quotes={
                "INTC": {
                    "latest_price": "118.23",
                    "quote_source": "longbridge_quote_readonly",
                }
            },
        )

        self.assertEqual(lookup["INTC"]["latest_price"], "118.23")
        self.assertEqual(lookup["INTC"]["latest_price_source"], "longbridge_quote_readonly")

    def test_forbidden_output_scan_ignores_runtime_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "m12_37_session.log").write_text("旧日志：历史收益", encoding="utf-8")
            assert_no_forbidden_output(output_dir)

    def test_extended_session_monitor_detects_premarket_and_postmarket_focus_movers(self):
        quotes = {
            "AMD": {
                "quote_source": "longbridge_quote_readonly",
                "quote_status": "Normal",
                "pre_market_last": "425.58",
                "pre_market_reference_close": "355.26",
                "pre_market_move_amount": "70.32",
                "pre_market_move_percent": "19.79",
                "pre_market_timestamp": "2026-05-06 11:00:45",
                "post_market_last": "414.00",
                "post_market_reference_close": "355.26",
                "post_market_move_amount": "58.74",
                "post_market_move_percent": "16.53",
                "post_market_timestamp": "2026-05-05 23:59:59",
            },
            "MU": {
                "quote_source": "longbridge_quote_readonly",
                "quote_status": "Normal",
                "pre_market_last": "675.72",
                "pre_market_reference_close": "640.20",
                "pre_market_move_amount": "35.52",
                "pre_market_move_percent": "5.55",
                "pre_market_timestamp": "2026-05-06 11:00:45",
            },
        }
        monitor = build_extended_session_monitor(quotes, "盘前")
        self.assertEqual(monitor["premarket_count"], 2)
        self.assertEqual(monitor["postmarket_count"], 1)
        self.assertEqual(monitor["active_session"], "盘前")
        self.assertGreaterEqual(monitor["focus_hit_count"], 2)
        self.assertIn("AMD", monitor["plain_language_summary"])

    def test_dashboard_includes_extended_session_monitor_from_live_quotes(self):
        live_quotes = {
            "AMD": {
                "symbol": "AMD",
                "latest_price": "355.26",
                "previous_close": "341.54",
                "open": "351.51",
                "high": "359.57",
                "low": "344.88",
                "volume": "64235117",
                "quote_status": "Normal",
                "quote_timestamp": "2026-05-06T14:00:00Z",
                "quote_source": "longbridge_quote_readonly",
                "pre_market_last": "425.58",
                "pre_market_reference_close": "355.26",
                "pre_market_move_amount": "70.32",
                "pre_market_move_percent": "19.79",
                "pre_market_timestamp": "2026-05-06 11:00:45",
            }
        }
        with patch("scripts.m12_29_current_day_scan_dashboard_lib.build_quotes", return_value=(live_quotes, {"quote_source": "longbridge_quote_readonly", "quote_count": 1})):
            _, result, output_dir = self.run_stage(generated_at="2026-05-06T14:00:00Z")
        monitor = result["dashboard"]["extended_session_monitor"]
        self.assertEqual(monitor["premarket_count"], 1)
        self.assertEqual(monitor["active_session"], "盘前")
        self.assertEqual(monitor["premarket_rows"][0]["symbol"], "AMD")
        self.assertTrue((output_dir / "m12_48_extended_session_monitor.json").exists())


if __name__ == "__main__":
    unittest.main()
