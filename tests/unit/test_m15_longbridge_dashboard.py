from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.m15_longbridge_dashboard_lib import build_dashboard, run_dashboard


def _write(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class LongbridgeDashboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_dashboard_uses_sdk_and_actual_longbridge_sources(self) -> None:
        tmp_path = self.tmp_path
        now = "2026-07-16T00:00:00Z"
        runtime = _write(tmp_path / "runtime.json", {
            "generated_at": now,
            "runtime_pid": os.getpid(),
            "runtime_engine": "sdk",
            "sdk_connected": True,
            "configured_symbol_count": 300,
            "subscription_coverage": "300/300",
            "trading_symbol_count": 147,
            "trading_subscription_coverage": "147/147",
            "readonly_expansion_symbol_count": 153,
            "readonly_expansion_subscription_coverage": "153/153",
            "readonly_expansion_acceptance_status": "daily_context_incomplete",
            "daily_context_state": "loading",
            "trading_daily_context_ready": True,
            "trading_daily_context_row_count": 8820,
            "trading_daily_context_expected_row_count": 8820,
            "new_position_submission_enabled": True,
        })
        account = _write(tmp_path / "account.json", {
            "generated_at": now,
            "paper_account_verified": True,
            "account_channel": "lb_papertrading",
            "position_row_count": 2,
            "open_order_count": 0,
            "positions": [
                {"symbol": "AAPL.US", "quantity": "5", "cost_price": "100", "market_price": "110", "unrealized_pnl": "50.00"},
                {"symbol": "TSLA.US", "quantity": "1", "cost_price": "250", "market_price": "260", "unrealized_pnl": "10.00"},
            ],
        })
        summary = _write(tmp_path / "summary.json", {"generated_at": now, "account_today_total_pnl": "12.3", "account_today_total_pnl_source": "longbridge"})
        execution = _write(tmp_path / "execution.json", {"pending_confirmation_count": 0})
        epoch = _write(tmp_path / "epoch.json", {"status": "active", "test_epoch_id": "formal"})
        formal = _write(tmp_path / "formal.json", {"status": "active", "test_epoch_id": "formal"})
        orders = _write(tmp_path / "orders.json", {
            "generated_at": now,
            "summary": {"filled": 2},
            "rows": [{"order_id": "SHORT-1", "status": "Filled"}],
        })
        pnl = _write(tmp_path / "pnl.json", {
            "generated_at": now,
            "account_pnl": {"sum_profit": "5"},
            "market_day_profit_analysis": {"sum_profit": "-3"},
            "source_status": {"ok": True},
            "current_holdings": [
                {"symbol": "AAPL.US", "quantity": "5", "cost_price": "100", "market_price": "110", "unrealized_pnl": "50.00"},
                {"symbol": "TSLA.US", "quantity": "1", "cost_price": "250", "market_price": "260", "unrealized_pnl": "10.00"},
            ],
        })
        fills = _write(tmp_path / "fills.json", {
            "generated_at": now,
            "summary": {
                "matched_event_count": 4,
                "exit_fill_event_count": 3,
                "completed_trade_count": 2,
                "gross_realized_pnl": "20.00",
                "estimated_fees": "8.00",
                "estimated_net_realized_pnl": "12.00",
            },
            "fee_model": {"source": "configured_conservative_estimate"},
            "strategy_performance": [{
                "runtime_id": "R1",
                "completed_trade_count": 2,
                "win_rate_after_estimated_fees_pct": "50.0000",
                "gross_realized_pnl": "20.00",
                "estimated_fees": "8.00",
                "estimated_net_realized_pnl": "12.00",
                "profit_factor_after_estimated_fees": "1.5000",
                "maximum_drawdown_after_estimated_fees": "4.00",
            }],
            "bucket_performance": [{
                "capital_bucket": "bucket-r1",
                "completed_trade_count": 2,
                "win_rate_after_estimated_fees_pct": "50.0000",
                "gross_realized_pnl": "20.00",
                "estimated_fees": "8.00",
                "estimated_net_realized_pnl": "12.00",
                "profit_factor_after_estimated_fees": "1.5000",
                "maximum_drawdown_after_estimated_fees": "4.00",
            }],
            "completed_trades": [
                {
                    "batch_id": "b1",
                    "runtime_id": "R1",
                    "capital_bucket": "bucket-r1",
                    "estimated_net_pnl": "12.00",
                    "gross_realized_pnl": "20.00",
                    "estimated_fees": "8.00",
                    "open_market_date": "2026-07-15",
                    "opened_at": "2026-07-15T14:00:00Z",
                    "exit_fill_event_count": 1,
                },
                {
                    "batch_id": "b2",
                    "runtime_id": "R1",
                    "capital_bucket": "bucket-r1",
                    "estimated_net_pnl": "0.00",
                    "gross_realized_pnl": "0.00",
                    "estimated_fees": "0.00",
                    "open_market_date": "2026-07-15",
                    "opened_at": "2026-07-15T15:00:00Z",
                    "exit_fill_event_count": 2,
                },
            ],
            "batches": [
                {
                    "batch_id": "open-a",
                    "runtime_id": "R1",
                    "capital_bucket": "bucket-r1",
                    "symbol": "AAPL",
                    "direction": "long",
                    "remaining_quantity": "5.0000",
                    "open_price": "100.00",
                    "metadata": {"submitted_at": "2026-07-15T14:00:00Z"},
                }
            ],
            "symbol_checks": [],
            "anomalies": [],
        })
        short_diagnostics = _write(tmp_path / "short.json", {
            "generated_at": now,
            "test_epoch_id": "short-formal",
            "summary": {"runtime_count": 3, "candidate_count": 4, "signal_ready_count": 0, "blocked_count": 4},
            "runtime_summaries": [{
                "runtime_id": "M10-PA-002-5m-short",
                "candidate_count": 4,
                "signal_ready_count": 0,
                "blocked_count": 4,
                "blockers": {"blocked_fee_profit_below_minimum": 4},
                "last_candidate_at": now,
            }],
            "decision_rows": [],
        })
        execution_ledger = tmp_path / "execution.jsonl"
        execution_ledger.write_text(json.dumps({
            "test_epoch_id": "short-formal",
            "runtime_id": "M10-PA-002-5m-short",
            "position_action": "open_short",
            "direction": "short",
            "short_capacity_check_status": "sdk_short_capacity_cached",
            "short_capacity_source": "broker_sdk_cache",
            "blockers": [],
            "longbridge_order_id": "SHORT-1",
        }) + "\n", encoding="utf-8")
        config_file = _write(tmp_path / "execution_config.json", {"virtual_capital_buckets": {"one": {"runtime_ids": ["R1"], "equity": "10000"}}})
        config = {"inputs": {"sdk_runtime_status": runtime, "account_state": account, "account_state_summary": summary, "execution_status": execution, "execution_ledger": str(execution_ledger), "epoch_state": epoch, "formal_epoch_marker": formal, "order_reconciliation": orders, "fill_attribution": fills, "short_signal_diagnostics": short_diagnostics, "pnl_reconciliation": pnl, "execution_config": config_file}, "outputs": {"json": str(tmp_path / "out.json"), "html": str(tmp_path / "out.html")}}
        payload = run_dashboard(config, generated_at="2026-07-16T00:00:00Z")
        self.assertEqual(payload["data_status"], "trustworthy")
        self.assertEqual(payload["source_of_truth"], "longbridge_sdk_paper_account")
        self.assertFalse(payload["legacy_cli_used"])
        self.assertEqual(payload["strategy_inventory"]["runtime_count"], 1)
        self.assertEqual(payload["account"]["today_pnl"], "12.3")
        self.assertEqual(payload["pnl"]["market_day_profit_analysis"]["sum_profit"], "-3")
        self.assertEqual(payload["paper_short_diagnostics"]["summary"]["candidate_count"], 4)
        self.assertEqual(payload["paper_short_diagnostics"]["summary"]["broker_capacity_checked_count"], 1)
        self.assertEqual(payload["paper_short_diagnostics"]["summary"]["broker_capacity_cache_hit_count"], 1)
        self.assertEqual(payload["paper_short_diagnostics"]["summary"]["broker_order_id_count"], 1)
        self.assertEqual(payload["paper_short_diagnostics"]["summary"]["broker_filled_order_count"], 1)
        self.assertEqual(payload["fill_attribution"]["summary"]["completed_trade_count"], 2)
        self.assertEqual(payload["fill_attribution"]["position_layers"]["actual_account_total"]["gross_market_value"], "810.00")
        self.assertEqual(payload["fill_attribution"]["position_layers"]["attributed_virtual_total"]["gross_market_value"], "550.00")
        self.assertEqual(payload["fill_attribution"]["position_layers"]["unreconciled_delta"]["gross_market_value"], "260.00")
        self.assertEqual(payload["fill_attribution"]["summary"]["exit_fill_event_count"], 3)
        self.assertEqual(payload["fill_attribution"]["strategy_performance"][0]["runtime_id"], "R1")
        self.assertTrue(payload["runtime"]["daily_context_complete"])
        self.assertEqual(payload["runtime"]["trading_subscription_coverage"], "147/147")
        self.assertEqual(payload["runtime"]["readonly_expansion_subscription_coverage"], "153/153")
        self.assertFalse(payload["pa004_migration"]["enabled"])
        html = (tmp_path / "out.html").read_text(encoding="utf-8")
        self.assertIn("交易核心正常，统计待刷新", html)
        self.assertIn("账户净资产", html)
        self.assertIn("当前持仓三层口径", html)
        self.assertIn("策略实际成交成绩", html)
        self.assertIn("分仓实际成交成绩", html)
        self.assertIn("扣费后盈利因子", html)
        self.assertIn("做空信号诊断", html)

    def test_dashboard_blocks_stale_statistics_and_dead_runtime(self) -> None:
        tmp_path = self.tmp_path
        stale = "2026-07-15T00:00:00Z"
        files = {}
        for name, payload in {
            "runtime": {"generated_at": stale, "runtime_pid": 99999999, "runtime_engine": "sdk", "sdk_connected": True},
            "account": {"generated_at": stale, "paper_account_verified": True},
            "summary": {"generated_at": stale, "account_today_total_pnl": "99"},
            "execution": {}, "epoch": {"status": "active"}, "formal": {"status": "active"},
            "orders": {"generated_at": stale, "summary": {"filled": 99}},
            "pnl": {"generated_at": stale, "account_pnl": {"sum_profit": "99"}},
            "config": {"virtual_capital_buckets": {}},
        }.items():
            files[name] = _write(tmp_path / f"{name}.json", payload)
        config = {"inputs": {"sdk_runtime_status": files["runtime"], "account_state": files["account"], "account_state_summary": files["summary"], "execution_status": files["execution"], "epoch_state": files["epoch"], "formal_epoch_marker": files["formal"], "order_reconciliation": files["orders"], "pnl_reconciliation": files["pnl"], "execution_config": files["config"]}, "outputs": {"json": str(tmp_path / "out.json"), "html": str(tmp_path / "out.html")}}

        payload = build_dashboard(config, generated_at="2026-07-16T00:00:00Z")

        self.assertEqual(payload["data_status"], "temporarily_unavailable")
        self.assertFalse(payload["runtime"]["runtime_process_alive"])
        self.assertIsNone(payload["account"]["today_pnl"])
        self.assertIsNone(payload["pnl"]["account_pnl"])
        self.assertEqual(payload["orders"]["rows"], [])

    def test_dashboard_keeps_trading_health_separate_from_stale_statistics(self) -> None:
        tmp_path = self.tmp_path
        now = "2026-07-16T00:00:00Z"
        stale = "2026-07-15T00:00:00Z"
        files = {}
        for name, payload in {
            "runtime": {"generated_at": now, "runtime_pid": os.getpid(), "runtime_engine": "sdk", "sdk_connected": True},
            "account": {"generated_at": now, "paper_account_verified": True},
            "summary": {"generated_at": stale, "account_today_total_pnl": "99"},
            "execution": {}, "epoch": {"status": "active"}, "formal": {"status": "active"},
            "orders": {"generated_at": stale, "summary": {"filled": 99}},
            "pnl": {"generated_at": stale, "account_pnl": {"sum_profit": "99"}},
            "config": {"virtual_capital_buckets": {}},
        }.items():
            files[name] = _write(tmp_path / f"{name}.json", payload)
        config = {"inputs": {"sdk_runtime_status": files["runtime"], "account_state": files["account"], "account_state_summary": files["summary"], "execution_status": files["execution"], "epoch_state": files["epoch"], "formal_epoch_marker": files["formal"], "order_reconciliation": files["orders"], "pnl_reconciliation": files["pnl"], "execution_config": files["config"]}, "outputs": {"json": str(tmp_path / "out.json"), "html": str(tmp_path / "out.html")}}

        payload = build_dashboard(config, generated_at=now)

        self.assertEqual(payload["data_status"], "trading_ready_statistics_stale")
        self.assertTrue(payload["source_checks"]["sdk_runtime"])
        self.assertTrue(payload["source_checks"]["account"])
        self.assertIsNone(payload["account"]["today_pnl"])
        self.assertEqual(payload["orders"]["summary"], {"status": "stale_source_blocked"})

    def test_dashboard_uses_sdk_dispatch_state_when_legacy_entry_field_is_absent(self) -> None:
        tmp_path = self.tmp_path
        now = "2026-07-16T00:00:00Z"
        files = {}
        for name, payload in {
            "runtime": {
                "generated_at": now,
                "runtime_pid": os.getpid(),
                "runtime_engine": "sdk",
                "sdk_connected": True,
                "dispatch_enabled": True,
                "dispatch_requested": True,
            },
            "account": {"generated_at": now, "paper_account_verified": True},
            "summary": {"generated_at": now},
            "execution": {},
            "epoch": {"status": "active"},
            "formal": {"status": "active"},
            "orders": {"generated_at": now},
            "pnl": {"generated_at": now},
            "config": {"virtual_capital_buckets": {}},
        }.items():
            files[name] = _write(tmp_path / f"{name}.json", payload)
        config = {
            "inputs": {
                "sdk_runtime_status": files["runtime"],
                "account_state": files["account"],
                "account_state_summary": files["summary"],
                "execution_status": files["execution"],
                "epoch_state": files["epoch"],
                "formal_epoch_marker": files["formal"],
                "order_reconciliation": files["orders"],
                "pnl_reconciliation": files["pnl"],
                "execution_config": files["config"],
            },
            "outputs": {"json": str(tmp_path / "out.json"), "html": str(tmp_path / "out.html")},
        }

        payload = build_dashboard(config, generated_at=now)

        self.assertTrue(payload["runtime"]["new_position_submission_enabled"])
        self.assertTrue(payload["runtime"]["submission_armed"])

    def test_dashboard_marks_daily_context_loading_as_not_ready(self) -> None:
        tmp_path = self.tmp_path
        now = "2026-07-16T00:00:00Z"
        files = {}
        for name, payload in {
            "runtime": {
                "generated_at": now,
                "runtime_pid": os.getpid(),
                "runtime_engine": "sdk",
                "sdk_connected": True,
                "daily_context_state": "loading",
                "daily_context_row_count": 1680,
                "paper_order_dispatch_enabled": True,
                "dispatch_enabled": False,
                "dispatch_requested": True,
            },
            "account": {"generated_at": now, "paper_account_verified": True},
            "summary": {"generated_at": now},
            "execution": {},
            "epoch": {"status": "active"},
            "formal": {"status": "active"},
            "orders": {"generated_at": now},
            "pnl": {"generated_at": now},
            "config": {"virtual_capital_buckets": {}},
        }.items():
            files[name] = _write(tmp_path / f"{name}.json", payload)
        config = {
            "inputs": {
                "sdk_runtime_status": files["runtime"],
                "account_state": files["account"],
                "account_state_summary": files["summary"],
                "execution_status": files["execution"],
                "epoch_state": files["epoch"],
                "formal_epoch_marker": files["formal"],
                "order_reconciliation": files["orders"],
                "pnl_reconciliation": files["pnl"],
                "execution_config": files["config"],
            },
            "outputs": {"json": str(tmp_path / "out.json"), "html": str(tmp_path / "out.html")},
        }

        payload = run_dashboard(config, generated_at=now)

        self.assertEqual(payload["data_status"], "sdk_starting_daily_context")
        self.assertFalse(payload["runtime"]["daily_context_complete"])
        self.assertFalse(payload["runtime"]["dispatch_enabled"])
        self.assertFalse(payload["runtime"]["new_position_submission_enabled"])
        self.assertIn("日线装载中，暂不允许新开仓", (tmp_path / "out.html").read_text(encoding="utf-8"))


    def test_pending_flatten_forces_new_entries_off(self) -> None:
        tmp_path = self.tmp_path
        files = {}
        for name, payload in {
            "runtime": {"generated_at": "2026-07-16T00:00:00Z", "runtime_pid": os.getpid(), "runtime_engine": "sdk", "sdk_connected": True, "new_position_submission_enabled": True},
            "account": {"generated_at": "2026-07-16T00:00:00Z", "paper_account_verified": True, "position_row_count": 16},
            "summary": {}, "execution": {}, "epoch": {"status": "pending_flatten"},
            "formal": {"status": "pending_flatten"}, "orders": {}, "pnl": {}, "config": {"virtual_capital_buckets": {}},
        }.items():
            files[name] = _write(tmp_path / f"{name}.json", payload)
        config = {"inputs": {"sdk_runtime_status": files["runtime"], "account_state": files["account"], "account_state_summary": files["summary"], "execution_status": files["execution"], "epoch_state": files["epoch"], "formal_epoch_marker": files["formal"], "order_reconciliation": files["orders"], "pnl_reconciliation": files["pnl"], "execution_config": files["config"]}, "outputs": {"json": str(tmp_path / "out.json"), "html": str(tmp_path / "out.html")}}
        payload = build_dashboard(config)
        self.assertEqual(payload["formal_test"]["positions"], 16)
        self.assertFalse(payload["runtime"]["new_position_submission_enabled"])

    def test_dashboard_uses_pa004_migration_baseline_for_default_performance_view(self) -> None:
        tmp_path = self.tmp_path
        now = "2026-07-31T20:00:00Z"
        runtime = _write(tmp_path / "runtime.json", {
            "generated_at": now,
            "runtime_pid": os.getpid(),
            "runtime_engine": "sdk",
            "sdk_connected": True,
        })
        account = _write(tmp_path / "account.json", {
            "generated_at": now,
            "paper_account_verified": True,
            "positions": [{"symbol": "AAPL.US", "quantity": "1", "cost_price": "100", "market_price": "110", "unrealized_pnl": "10.00"}],
        })
        summary = _write(tmp_path / "summary.json", {"generated_at": now})
        execution = _write(tmp_path / "execution.json", {})
        epoch = _write(tmp_path / "epoch.json", {"status": "active"})
        formal = _write(tmp_path / "formal.json", {"status": "active"})
        orders = _write(tmp_path / "orders.json", {"generated_at": now})
        pnl = _write(tmp_path / "pnl.json", {
            "generated_at": now,
            "current_holdings": [{"symbol": "AAPL.US", "quantity": "1", "cost_price": "100", "market_price": "110", "unrealized_pnl": "10.00"}],
        })
        fills = _write(tmp_path / "fills.json", {
            "generated_at": now,
            "summary": {"completed_trade_count": 2, "estimated_net_realized_pnl": "7.00"},
            "completed_trades": [
                {
                    "batch_id": "old",
                    "runtime_id": "M10-PA-004-MBF-1d",
                    "capital_bucket": "pa004_mbf",
                    "estimated_net_pnl": "5.00",
                    "gross_realized_pnl": "8.00",
                    "estimated_fees": "3.00",
                    "opened_at": "2026-07-20T14:00:00Z",
                    "exit_fill_event_count": 1,
                },
                {
                    "batch_id": "new",
                    "runtime_id": "M10-PA-004-MBF-1d",
                    "capital_bucket": "pa004_mbf",
                    "estimated_net_pnl": "2.00",
                    "gross_realized_pnl": "4.00",
                    "estimated_fees": "2.00",
                    "opened_at": "2026-07-30T14:00:00Z",
                    "exit_fill_event_count": 1,
                },
            ],
            "batches": [],
            "symbol_checks": [],
            "anomalies": [],
        })
        migration = _write(tmp_path / "m15_pa004_bucket_migration_status.json", {
            "bucket_baselines": {
                "pa004_mbf": {"started_at": "2026-07-25T00:00:00Z"},
            }
        })
        config_file = _write(tmp_path / "execution_config.json", {"virtual_capital_buckets": {"pa004_mbf": {"runtime_ids": ["M10-PA-004-MBF-1d"]}}})
        config = {
            "inputs": {
                "sdk_runtime_status": runtime,
                "account_state": account,
                "account_state_summary": summary,
                "execution_status": execution,
                "epoch_state": epoch,
                "formal_epoch_marker": formal,
                "order_reconciliation": orders,
                "fill_attribution": fills,
                "pnl_reconciliation": pnl,
                "execution_config": config_file,
                "pa004_migration_status": migration,
            },
            "outputs": {"json": str(tmp_path / "out.json"), "html": str(tmp_path / "out.html")},
        }

        payload = build_dashboard(config, generated_at=now)

        self.assertTrue(payload["pa004_migration"]["enabled"])
        self.assertEqual(payload["fill_attribution"]["display_summary"]["completed_trade_count"], 1)
        self.assertEqual(payload["fill_attribution"]["display_summary"]["estimated_net_realized_pnl"], "2.00")
        self.assertEqual(payload["fill_attribution"]["archived_summary"]["completed_trade_count"], 1)
        self.assertEqual(payload["fill_attribution"]["archived_summary"]["estimated_net_realized_pnl"], "5.00")
        self.assertEqual(payload["fill_attribution"]["strategy_performance"][0]["runtime_id"], "M10-PA-004-MBF-1d")


if __name__ == "__main__":
    unittest.main()
