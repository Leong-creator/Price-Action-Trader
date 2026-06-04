from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_longbridge_realtime_session_supervisor_lib import (
    LEDGER_JSONL,
    SUMMARY_JSON,
    load_config,
    run_realtime_session_once,
)


class M15LongbridgeRealtimeSessionSupervisorTest(unittest.TestCase):
    def test_waits_outside_regular_session_without_running_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            calls: list[str] = []

            payload = run_realtime_session_once(
                config,
                generated_at="2026-06-04T12:00:00Z",
                ingestor_runner=lambda _ts: calls.append("ingestor") or {},
                router_runner=lambda _ts: calls.append("router") or {},
                execution_runner=lambda _ts: calls.append("execution") or {},
            )

            self.assertEqual(payload["supervisor_status"], "waiting_market_window")
            self.assertFalse(payload["cycle_ran"])
            self.assertEqual(calls, [])
            self.assertIn("等待下一次美股常规交易时段", payload["plain_language_result"])

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
            self.assertEqual(calls, ["ingestor", "router", "account_state", "position_manager", "execution"])
            self.assertEqual(status["new_market_event_count"], 2)
            self.assertEqual(status["new_signal_event_count"], 1)
            self.assertTrue(status["paper_account_verified"])
            self.assertEqual(status["account_position_row_count"], 1)
            self.assertEqual(status["account_open_order_count"], 2)
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
                "position_manager_config": str(root / "position_manager.json"),
                "execution_config": str(root / "execution.json"),
            },
            "outputs": {
                "output_dir": str(root / "out"),
            },
            "realtime_session_supervisor": {
                "check_interval_seconds": 1,
                "market_timezone": "America/New_York",
                "regular_session_start_time": "09:30",
                "regular_session_end_time": "16:00",
                "active_market_phases": ["regular_session"],
                "market_holidays": ["2026-05-25"],
                "max_consecutive_failures": 3,
                "run_ingestor": True,
                "run_router": True,
                "run_account_state": True,
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
