from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m15_monday_refresh_acceptance_lib import (
    MondayRefreshAcceptanceConfig,
    run_m15_monday_refresh_acceptance,
)


class M15MondayRefreshAcceptanceTest(unittest.TestCase):
    def test_non_trading_window_waits_for_monday_without_failing_fallback_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._write_fixture(root, session_should_run=False, child_running=False, quote_source="fallback_quotes_only")
            payload = run_m15_monday_refresh_acceptance(config, generated_at="2026-05-31T02:00:00Z")

            self.assertEqual(payload["acceptance_status"], "pretrade_preparation_ready_waiting_for_monday")
            self.assertFalse(payload["session_should_run"])
            self.assertEqual(payload["fail_count"], 0)
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["quote_source_longbridge"]["status"], "waiting_for_monday_refresh")
            self.assertFalse(payload["broker_connection"])
            self.assertFalse(payload["real_order"])
            self.assertFalse(payload["manual_m12_37_once"])

    def test_trading_window_passes_when_longbridge_data_and_ledgers_are_current(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._write_fixture(root, session_should_run=True, child_running=True, quote_source="longbridge_quote_readonly")
            payload = run_m15_monday_refresh_acceptance(config, generated_at="2026-06-01T15:00:00Z")

            self.assertEqual(payload["acceptance_status"], "ready_after_fresh_refresh")
            self.assertEqual(payload["fail_count"], 0)
            self.assertEqual(payload["waiting_count"], 0)
            self.assertEqual(payload["quote_source"], "longbridge_quote_readonly")

    def test_trading_window_without_child_is_runtime_abnormal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._write_fixture(
                root,
                session_should_run=True,
                child_running=False,
                quote_source="longbridge_quote_readonly",
                failure_state="child_not_running",
                failure_reason="fixture",
            )
            payload = run_m15_monday_refresh_acceptance(config, generated_at="2026-06-01T15:00:00Z")

            self.assertEqual(payload["acceptance_status"], "blocked_monday_acceptance")
            self.assertEqual(payload["failure_state"], "child_not_running")
            checks = {row["check"]: row for row in payload["checks"]}
            self.assertEqual(checks["m12_37_child_running_when_required"]["status"], "fail")

    def _write_fixture(
        self,
        root: Path,
        *,
        session_should_run: bool,
        child_running: bool,
        quote_source: str,
        failure_state: str = "",
        failure_reason: str = "",
    ) -> MondayRefreshAcceptanceConfig:
        supervisor_path = root / "supervisor.json"
        dashboard_path = root / "dashboard.json"
        manifest_path = root / "manifest.json"
        m13_path = root / "m13.json"
        m14_goal_path = root / "m14_goal.json"
        m14_summary_path = root / "m14_summary.json"
        preflight_path = root / "preflight.json"
        output_dir = root / "out"
        scan_date = "2026-06-01"

        supervisor_path.write_text(
            json.dumps(
                {
                    "supervisor_process_alive": True,
                    "session_should_run": session_should_run,
                    "child_running": child_running,
                    "market_status": "regular" if session_should_run else "closed",
                    "failure_state": failure_state,
                    "failure_reason": failure_reason,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        dashboard_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "scan_date": scan_date,
                        "quote_source": quote_source,
                        "first50_daily_ready_symbols": 50,
                        "first50_current_5m_ready_symbols": 50,
                        "data_freshness_warning": "fallback snapshot" if "fallback" in quote_source else "",
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        manifest_path.write_text(json.dumps({"stage": "M12.37"}, ensure_ascii=False), encoding="utf-8")
        m13_path.write_text(json.dumps({"trading_date": scan_date}, ensure_ascii=False), encoding="utf-8")
        m14_goal_path.write_text(json.dumps({"trading_date": scan_date}, ensure_ascii=False), encoding="utf-8")
        m14_summary_path.write_text(json.dumps({"data_freshness_warning": ""}, ensure_ascii=False), encoding="utf-8")
        preflight_path.write_text(
            json.dumps(
                {
                    "paper_preflight_status": "ready_for_user_paper_credential_approval",
                    "broker_connection_attempted": False,
                    "order_submitted": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return MondayRefreshAcceptanceConfig(
            stage="M15.monday_refresh_acceptance",
            supervisor_status_path=supervisor_path,
            dashboard_path=dashboard_path,
            auto_runner_manifest_path=manifest_path,
            m13_goal_status_path=m13_path,
            m14_goal_status_path=m14_goal_path,
            m14_summary_path=m14_summary_path,
            m15_preflight_path=preflight_path,
            output_dir=output_dir,
        )


if __name__ == "__main__":
    unittest.main()
