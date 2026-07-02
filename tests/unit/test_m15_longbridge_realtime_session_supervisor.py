from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_longbridge_realtime_session_supervisor_lib import (
    LEDGER_JSONL,
    SUMMARY_JSON,
    apply_dashboard_longbridge_panel_overlay,
    load_config,
    rotate_jsonl_if_needed,
    rotate_text_log_if_needed,
    run_realtime_session_once,
    write_json,
)
from scripts.run_m15_longbridge_realtime_session_supervisor import (
    should_print_watch_payload,
    watch_print_key,
    watch_sleep_seconds,
)


class M15LongbridgeRealtimeSessionSupervisorTest(unittest.TestCase):
    def test_write_json_replaces_status_without_tmp_leftover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / SUMMARY_JSON

            write_json(status_path, {"schema_version": "test", "status": "ok"})

            self.assertEqual(json.loads(status_path.read_text(encoding="utf-8"))["status"], "ok")
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_waits_outside_regular_session_without_running_trade_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            calls: list[str] = []

            payload = run_realtime_session_once(
                config,
                generated_at="2026-06-04T12:00:00Z",
                ingestor_runner=lambda _ts: calls.append("ingestor") or {},
                router_runner=lambda _ts: calls.append("router") or {},
                account_state_runner=lambda _ts: calls.append("account_state") or {
                    "account_status": "paper_account_ready",
                    "paper_account_verified": True,
                    "position_row_count": 2,
                    "open_order_count": 0,
                },
                execution_runner=lambda _ts: calls.append("execution") or {},
            )

            self.assertEqual(payload["supervisor_status"], "waiting_market_window")
            self.assertFalse(payload["cycle_ran"])
            self.assertEqual(calls, ["account_state"])
            self.assertEqual(payload["step_rows"][0]["step_id"], "account_state_refresh_only")
            self.assertIn("等待下一次美股常规交易时段", payload["plain_language_result"])
            self.assertIn("已只读刷新长桥账户状态", payload["plain_language_result"])

    def test_waiting_window_uses_fresh_paper_account_state_without_running_trade_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(
                root / "account_state.json",
                {
                    "stage": "M15.longbridge_realtime_account_state",
                    "outputs": {
                        "output_dir": str(root / "out"),
                        "account_state": str(root / "out" / "m15_longbridge_realtime_account_state.json"),
                    },
                    "longbridge_account_state": {
                        "required_account_channel": "lb_papertrading",
                        "cli_timeout_seconds": 6,
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "live_execution": False,
                        "real_money_actions": False,
                        "local_simulation_as_account_source": False,
                        "order_submit_or_cancel_commands": False,
                    },
                },
            )
            (root / "out").mkdir(parents=True, exist_ok=True)
            self.write_json(
                root / "out" / "m15_longbridge_realtime_account_state.json",
                {
                    "paper_account_verified": True,
                    "position_row_count": 3,
                    "open_order_count": 1,
                },
            )
            calls: list[str] = []

            payload = run_realtime_session_once(
                config,
                generated_at="2026-06-04T12:00:00Z",
                account_state_runner=lambda _ts: calls.append("account_state") or {
                    "paper_account_verified": True,
                    "position_row_count": 4,
                    "open_order_count": 2,
                },
                execution_runner=lambda _ts: calls.append("execution") or {},
            )

            self.assertEqual(payload["supervisor_status"], "waiting_market_window")
            self.assertFalse(payload["cycle_ran"])
            self.assertEqual(calls, ["account_state"])
            self.assertTrue(payload["paper_account_verified"])
            self.assertEqual(payload["account_position_row_count"], 4)
            self.assertEqual(payload["account_open_order_count"], 2)

    def test_waiting_window_falls_back_to_cached_account_state_when_refresh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(
                root / "account_state.json",
                {
                    "stage": "M15.longbridge_realtime_account_state",
                    "outputs": {
                        "output_dir": str(root / "out"),
                        "account_state": str(root / "out" / "m15_longbridge_realtime_account_state.json"),
                    },
                    "longbridge_account_state": {
                        "required_account_channel": "lb_papertrading",
                        "cli_timeout_seconds": 6,
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "live_execution": False,
                        "real_money_actions": False,
                        "local_simulation_as_account_source": False,
                        "order_submit_or_cancel_commands": False,
                    },
                },
            )
            (root / "out").mkdir(parents=True, exist_ok=True)
            self.write_json(
                root / "out" / "m15_longbridge_realtime_account_state.json",
                {
                    "paper_account_verified": True,
                    "position_row_count": 3,
                    "open_order_count": 1,
                },
            )

            def failing_account_state(_ts: str | None) -> dict:
                raise RuntimeError("longbridge account readonly failed")

            payload = run_realtime_session_once(
                config,
                generated_at="2026-06-04T12:00:00Z",
                account_state_runner=failing_account_state,
            )

            self.assertEqual(payload["supervisor_status"], "waiting_market_window")
            self.assertFalse(payload["cycle_ran"])
            self.assertEqual(payload["failure_state"], "account_state_refresh_failed")
            self.assertTrue(payload["paper_account_verified"])
            self.assertEqual(payload["account_position_row_count"], 3)
            self.assertEqual(payload["account_open_order_count"], 1)
            self.assertIn("长桥账户只读刷新失败", payload["plain_language_result"])

    def test_waiting_window_ignores_empty_nonpaper_refresh_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_json(
                root / "account_state.json",
                {
                    "stage": "M15.longbridge_realtime_account_state",
                    "outputs": {
                        "output_dir": str(root / "out"),
                        "account_state": str(root / "out" / "m15_longbridge_realtime_account_state.json"),
                    },
                    "longbridge_account_state": {
                        "required_account_channel": "lb_papertrading",
                        "cli_timeout_seconds": 6,
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "live_execution": False,
                        "real_money_actions": False,
                        "local_simulation_as_account_source": False,
                        "order_submit_or_cancel_commands": False,
                    },
                },
            )
            account_state_path = root / "out" / "m15_longbridge_realtime_account_state.json"
            account_state_path.parent.mkdir(parents=True, exist_ok=True)
            self.write_json(
                account_state_path,
                {
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "position_row_count": 5,
                    "open_order_count": 0,
                },
            )
            summary_path = root / "out" / "m15_longbridge_realtime_account_state_summary.json"
            pnl_path = root / "out" / "m15_longbridge_account_pnl_reconciliation.json"
            report_path = root / "out" / "m15_longbridge_account_pnl_reconciliation.md"
            self.write_json(
                summary_path,
                {
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "cash": "98481.28",
                    "buying_power": "100270.09",
                    "today_total_pnl": "12.34",
                },
            )
            self.write_json(
                pnl_path,
                {
                    "pnl_reconciliation_ok": True,
                    "account_snapshot": {
                        "portfolio_total_today_pl": "12.34",
                    },
                    "trading_pnl": {
                        "stock_total_pnl": "-45.67",
                    },
                },
            )
            report_path.write_text("cached pnl report\n", encoding="utf-8")

            payload = run_realtime_session_once(
                config,
                generated_at="2026-06-04T12:00:00Z",
                account_state_runner=lambda _ts: {
                    "account_channel": None,
                    "paper_account_verified": False,
                    "position_row_count": 0,
                    "open_order_count": 0,
                },
            )

            self.assertEqual(payload["supervisor_status"], "waiting_market_window")
            self.assertEqual(payload["failure_state"], "account_state_refresh_failed")
            self.assertTrue(payload["paper_account_verified"])
            self.assertEqual(payload["account_position_row_count"], 5)
            self.assertEqual(payload["account_open_order_count"], 0)
            self.assertEqual(json.loads(account_state_path.read_text(encoding="utf-8"))["position_row_count"], 5)
            self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8"))["cash"], "98481.28")
            self.assertTrue(json.loads(pnl_path.read_text(encoding="utf-8"))["pnl_reconciliation_ok"])
            self.assertEqual(report_path.read_text(encoding="utf-8"), "cached pnl report\n")

    def test_watch_loop_uses_idle_sleep_outside_trading_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            idle_payload = {
                "cycle_ran": False,
                "window": {
                    "session_should_run": False,
                    "seconds_until_next_session": 3600,
                },
            }
            preopen_payload = {
                "cycle_ran": False,
                "window": {
                    "session_should_run": False,
                    "seconds_until_next_session": 90,
                },
            }
            trading_payload = {
                "cycle_ran": True,
                "window": {
                    "session_should_run": True,
                    "seconds_until_next_session": 0,
                },
            }

            self.assertEqual(watch_sleep_seconds(config, idle_payload), 60)
            self.assertEqual(watch_sleep_seconds(config, preopen_payload), 1)
            self.assertEqual(watch_sleep_seconds(config, trading_payload), 1)

    def test_regular_session_runs_ingestor_router_execution_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            calls: list[str] = []

            payload = run_realtime_session_once(
                config,
                generated_at="2026-06-04T14:00:00Z",
                ingestor_runner=lambda _ts: calls.append("ingestor") or {
                    "new_market_event_count": 2,
                    "market_event_total_count": 12,
                    "deferred_count": 0,
                },
                router_runner=lambda _ts: calls.append("router") or {
                    "market_event_count": 12,
                    "new_signal_event_count": 1,
                },
                account_state_runner=lambda _ts: calls.append("account_state") or {
                    "account_status": "paper_account_ready",
                    "paper_account_verified": True,
                    "position_row_count": 1,
                    "open_order_count": 2,
                },
                stale_order_cleanup_runner=lambda _ts: calls.append("stale_order_cleanup") or {
                    "cleanup_status": "stale_buy_open_orders_canceled",
                    "stale_buy_open_order_count": 2,
                    "canceled_count": 2,
                    "failed_count": 0,
                },
                position_manager_runner=lambda _ts: calls.append("position_manager") or {
                    "position_count": 1,
                    "new_exit_signal_event_count": 1,
                },
                execution_runner=lambda _ts: calls.append("execution") or {
                    "signal_event_count": 1,
                    "ready_order_count": 1,
                    "submitted_count": 0,
                },
            )
            status = json.loads((config.output_dir / SUMMARY_JSON).read_text(encoding="utf-8"))
            ledger = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["supervisor_status"], "cycle_completed")
            self.assertTrue(payload["cycle_ran"])
            self.assertEqual(
                calls,
                ["ingestor", "router", "account_state", "stale_order_cleanup", "account_state", "position_manager", "execution"],
            )
            self.assertEqual(status["new_market_event_count"], 2)
            self.assertEqual(status["new_signal_event_count"], 1)
            self.assertTrue(status["paper_account_verified"])
            self.assertEqual(status["account_position_row_count"], 1)
            self.assertEqual(status["account_open_order_count"], 2)
            self.assertEqual(status["stale_buy_open_order_canceled_count"], 2)
            self.assertEqual(status["new_exit_signal_event_count"], 1)
            self.assertEqual(status["ready_order_count"], 1)
            self.assertEqual(status["window"]["session_started_at"], "2026-06-04T13:30:00Z")
            self.assertFalse(status["manual_m12_37_once_used"])
            self.assertFalse(status["legacy_fast_queue_used"])
            self.assertEqual(status["inputs"]["local_simulation_ledger"], "")
            self.assertEqual(len(ledger), 1)

    def test_failure_breaker_trips_after_consecutive_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, max_consecutive_failures=2)
            call_count = 0

            def failing_ingestor(_ts: str | None) -> dict:
                nonlocal call_count
                call_count += 1
                raise RuntimeError("longbridge readonly kline failed")

            first = run_realtime_session_once(
                config,
                generated_at="2026-06-04T14:00:00Z",
                ingestor_runner=failing_ingestor,
            )
            second = run_realtime_session_once(
                config,
                generated_at="2026-06-04T14:01:00Z",
                ingestor_runner=failing_ingestor,
            )
            third = run_realtime_session_once(
                config,
                generated_at="2026-06-04T14:02:00Z",
                ingestor_runner=failing_ingestor,
            )

            self.assertEqual(first["supervisor_status"], "cycle_failed")
            self.assertEqual(second["supervisor_status"], "failure_breaker_tripped")
            self.assertEqual(third["supervisor_status"], "failure_breaker_tripped")
            self.assertEqual(call_count, 2)
            self.assertIn("连续失败熔断", third["plain_language_result"])

    def test_config_rejects_live_or_real_money_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = self.config_payload(root)
            payload["hard_boundaries"]["live_execution"] = True
            path = root / "config.json"
            self.write_json(path, payload)

            with self.assertRaisesRegex(ValueError, "live execution"):
                load_config(path)

    def test_longbridge_overlay_updates_only_dashboard_panel_and_metrics(self) -> None:
        dashboard = {
            "top_metrics": {
                "主线今日盈亏": "1.00",
                "长桥模拟账户": "旧状态",
                "长桥可提交订单": "9",
            },
            "longbridge_paper_account": {
                "top_metric": "旧状态",
                "submit_ready_count": "9",
            },
            "summary": {
                "scan_date": "2026-06-04",
            },
        }
        longbridge_context = {
            "top_metric": "模拟账户已连接 / 9持仓 / 1挂单",
            "submit_ready_count": "0",
            "account_total_equity_estimate": "102375.57",
            "account_total_pnl_estimate": "基准未确认",
            "longbridge_account_intraday_pnl": "-2.44",
            "today_total_pnl": "-2.46",
            "total_pnl": "117.88",
            "longbridge_stock_total_pnl": "-154.18",
            "longbridge_symbol_win_rate_label": "38.46%",
            "longbridge_closed_trade_win_rate_label": "33.33%",
            "longbridge_max_drawdown_label": "10.00%",
            "longbridge_worst_symbol_loss_label": "-6.58%",
            "project_model_exposure_label": "4638.96 / 10000.00 (46.39%)",
            "local_simulation_isolated": True,
            "legacy_fast_queue_used": False,
        }

        apply_dashboard_longbridge_panel_overlay(dashboard, longbridge_context)

        self.assertEqual(dashboard["longbridge_paper_account"], longbridge_context)
        self.assertEqual(dashboard["top_metrics"]["长桥模拟账户"], "模拟账户已连接 / 9持仓 / 1挂单")
        self.assertNotIn("长桥可提交订单", dashboard["top_metrics"])
        self.assertEqual(dashboard["top_metrics"]["长桥账户总资产"], "102375.57")
        self.assertEqual(dashboard["top_metrics"]["长桥账户当日盈亏"], "-2.44")
        self.assertEqual(dashboard["top_metrics"]["长桥接口持仓今日浮动"], "-2.46")
        self.assertEqual(dashboard["top_metrics"]["长桥当前持仓总盈亏"], "117.88")
        self.assertEqual(dashboard["top_metrics"]["长桥交易累计盈亏"], "-154.18")
        self.assertNotIn("长桥账户总盈亏", dashboard["top_metrics"])
        self.assertNotIn("长桥交易总盈亏", dashboard["top_metrics"])
        self.assertNotIn("长桥今日盈亏", dashboard["top_metrics"])
        self.assertNotIn("长桥总盈亏", dashboard["top_metrics"])
        self.assertEqual(dashboard["top_metrics"]["长桥逐标的胜率"], "38.46%")
        self.assertEqual(dashboard["top_metrics"]["长桥交易胜率"], "33.33%")
        self.assertEqual(dashboard["top_metrics"]["长桥最大回撤"], "10.00%")
        self.assertNotIn("长桥回撤代理", dashboard["top_metrics"])
        self.assertEqual(dashboard["top_metrics"]["长桥项目资金占用"], "4638.96 / 10000.00 (46.39%)")
        self.assertEqual(dashboard["top_metrics"]["长桥本轮可新开仓"], "0")
        self.assertEqual(dashboard["top_metrics"]["主线今日盈亏"], "1.00")
        self.assertEqual(dashboard["summary"]["scan_date"], "2026-06-04")

    def test_supervisor_ledger_rotates_when_too_large(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger_path = root / LEDGER_JSONL
            ledger_path.write_text("".join(json.dumps({"idx": idx}) + "\n" for idx in range(8)), encoding="utf-8")

            rotate_jsonl_if_needed(ledger_path, max_bytes=1, keep_lines=5)

            retained = self.read_jsonl(ledger_path)
            archives = list((root / "archive").glob("*.archived.jsonl"))
            archived = self.read_jsonl(archives[0])
            self.assertEqual([row["idx"] for row in retained], [3, 4, 5, 6, 7])
            self.assertEqual([row["idx"] for row in archived], [0, 1, 2])

    def test_supervisor_text_log_rotates_when_too_large(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "m15_longbridge_realtime_session_supervisor.log"
            log_path.write_text("old log\n", encoding="utf-8")

            archive_path = rotate_text_log_if_needed(log_path, max_bytes=1)

            self.assertIsNotNone(archive_path)
            self.assertFalse(log_path.exists())
            self.assertEqual(archive_path.read_text(encoding="utf-8"), "old log\n")

    def test_waiting_watch_payload_does_not_repeat_log_line(self) -> None:
        payload = {
            "supervisor_status": "waiting_market_window",
            "cycle_ran": False,
            "failure_state": "",
            "window": {"market_phase": "before_regular_session"},
        }
        print_key = watch_print_key(payload)

        self.assertTrue(should_print_watch_payload(payload, print_key, None))
        self.assertFalse(should_print_watch_payload(payload, print_key, print_key))

    def test_trade_cycle_watch_payload_still_logs_every_cycle(self) -> None:
        payload = {
            "supervisor_status": "cycle_completed",
            "cycle_ran": True,
            "failure_state": "",
            "window": {"market_phase": "regular_session"},
        }
        print_key = watch_print_key(payload)

        self.assertTrue(should_print_watch_payload(payload, print_key, print_key))

    def make_config(self, root: Path, *, max_consecutive_failures: int = 3):
        path = root / "config.json"
        payload = self.config_payload(root)
        payload["realtime_session_supervisor"]["max_consecutive_failures"] = max_consecutive_failures
        self.write_json(path, payload)
        return load_config(path)

    def config_payload(self, root: Path) -> dict:
        return {
            "stage": "M15.longbridge_realtime_session_supervisor",
            "title": "长桥实时链路守护器",
            "inputs": {
                "ingestor_config": str(root / "ingestor.json"),
                "router_config": str(root / "router.json"),
                "account_state_config": str(root / "account_state.json"),
                "stale_order_cleanup_config": str(root / "stale_cleanup.json"),
                "position_manager_config": str(root / "position_manager.json"),
                "execution_config": str(root / "execution.json"),
            },
            "outputs": {
                "output_dir": str(root / "out"),
            },
            "realtime_session_supervisor": {
                "check_interval_seconds": 1,
                "idle_check_interval_seconds": 60,
                "market_timezone": "America/New_York",
                "regular_session_start_time": "09:30",
                "regular_session_end_time": "16:00",
                "active_market_phases": ["regular_session"],
                "market_holidays": ["2026-05-25"],
                "max_consecutive_failures": 3,
                "run_ingestor": True,
                "run_router": True,
                "run_account_state": True,
                "run_stale_order_cleanup": True,
                "run_position_manager": True,
                "run_execution": True,
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_signal_source": False,
                "manual_m12_37_once": False,
                "legacy_fast_queue_as_order_source": False,
            },
        }

    def write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def read_jsonl(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
