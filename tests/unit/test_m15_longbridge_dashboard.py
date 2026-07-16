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
        runtime = _write(tmp_path / "runtime.json", {"generated_at": now, "runtime_pid": os.getpid(), "runtime_engine": "sdk", "sdk_connected": True, "configured_symbol_count": 147, "subscribed_symbol_count": 147, "new_position_submission_enabled": True})
        account = _write(tmp_path / "account.json", {"generated_at": now, "paper_account_verified": True, "account_channel": "lb_papertrading", "position_row_count": 0, "open_order_count": 0})
        summary = _write(tmp_path / "summary.json", {"generated_at": now, "account_today_total_pnl": "12.3", "account_today_total_pnl_source": "longbridge"})
        execution = _write(tmp_path / "execution.json", {"pending_confirmation_count": 0})
        epoch = _write(tmp_path / "epoch.json", {"status": "active", "test_epoch_id": "formal"})
        formal = _write(tmp_path / "formal.json", {"status": "active", "test_epoch_id": "formal"})
        orders = _write(tmp_path / "orders.json", {"generated_at": now, "summary": {"filled": 2}, "rows": []})
        pnl = _write(tmp_path / "pnl.json", {"generated_at": now, "account_pnl": {"sum_profit": "5"}, "source_status": {"ok": True}})
        config_file = _write(tmp_path / "execution_config.json", {"virtual_capital_buckets": {"one": {"runtime_ids": ["R1"], "equity": "10000"}}})
        registry = _write(tmp_path / "registry.json", {"strategies": [{"module_role": "independent_runtime", "runtime_accounts": [{"runtime_id": "R1"}]}, {"module_role": "plugin_filter"}]})
        config = {"inputs": {"sdk_runtime_status": runtime, "account_state": account, "account_state_summary": summary, "execution_status": execution, "epoch_state": epoch, "formal_epoch_marker": formal, "order_reconciliation": orders, "pnl_reconciliation": pnl, "execution_config": config_file, "local_runtime_registry": registry}, "outputs": {"json": str(tmp_path / "out.json"), "html": str(tmp_path / "out.html")}}
        payload = run_dashboard(config, generated_at="2026-07-16T00:00:00Z")
        self.assertEqual(payload["data_status"], "trustworthy")
        self.assertEqual(payload["source_of_truth"], "longbridge_sdk_paper_account")
        self.assertFalse(payload["legacy_cli_used"])
        self.assertEqual(payload["strategy_inventory"]["runtime_count"], 1)
        self.assertEqual(payload["account"]["today_pnl"], "12.3")
        self.assertEqual(payload["inventory_interface"], {"parent_strategy_count": 1, "local_runtime_count": 1, "auxiliary_module_count": 1, "longbridge_tradable_runtime_count": 1})
        html = (tmp_path / "out.html").read_text(encoding="utf-8")
        self.assertIn("交易核心正常，统计待刷新", html)
        self.assertIn("账户净资产", html)

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
        registry = _write(tmp_path / "registry.json", {"strategies": []})
        config = {"inputs": {"sdk_runtime_status": files["runtime"], "account_state": files["account"], "account_state_summary": files["summary"], "execution_status": files["execution"], "epoch_state": files["epoch"], "formal_epoch_marker": files["formal"], "order_reconciliation": files["orders"], "pnl_reconciliation": files["pnl"], "execution_config": files["config"], "local_runtime_registry": registry}, "outputs": {"json": str(tmp_path / "out.json"), "html": str(tmp_path / "out.html")}}

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
        registry = _write(tmp_path / "registry.json", {"strategies": []})
        config = {"inputs": {"sdk_runtime_status": files["runtime"], "account_state": files["account"], "account_state_summary": files["summary"], "execution_status": files["execution"], "epoch_state": files["epoch"], "formal_epoch_marker": files["formal"], "order_reconciliation": files["orders"], "pnl_reconciliation": files["pnl"], "execution_config": files["config"], "local_runtime_registry": registry}, "outputs": {"json": str(tmp_path / "out.json"), "html": str(tmp_path / "out.html")}}

        payload = build_dashboard(config, generated_at=now)

        self.assertEqual(payload["data_status"], "trading_ready_statistics_stale")
        self.assertTrue(payload["source_checks"]["sdk_runtime"])
        self.assertTrue(payload["source_checks"]["account"])
        self.assertIsNone(payload["account"]["today_pnl"])
        self.assertEqual(payload["orders"]["summary"], {"status": "stale_source_blocked"})


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
        registry = _write(tmp_path / "registry.json", {"strategies": []})
        config = {"inputs": {"sdk_runtime_status": files["runtime"], "account_state": files["account"], "account_state_summary": files["summary"], "execution_status": files["execution"], "epoch_state": files["epoch"], "formal_epoch_marker": files["formal"], "order_reconciliation": files["orders"], "pnl_reconciliation": files["pnl"], "execution_config": files["config"], "local_runtime_registry": registry}, "outputs": {"json": str(tmp_path / "out.json"), "html": str(tmp_path / "out.html")}}
        payload = build_dashboard(config)
        self.assertEqual(payload["formal_test"]["positions"], 16)
        self.assertFalse(payload["runtime"]["new_position_submission_enabled"])


if __name__ == "__main__":
    unittest.main()
