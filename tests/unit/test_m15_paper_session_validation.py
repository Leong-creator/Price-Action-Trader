from dataclasses import replace
from datetime import UTC, datetime
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import json

from scripts.m15_longbridge_sdk_runtime_lib import load_config
from scripts.m15_paper_session_validation_lib import (
    paper_validation_authorized, entry_session_authorized, validation_status_current,
)
from scripts.m15_opening_trade_readiness_lib import marketdata_gate_truth
from scripts.run_m15_longbridge_sdk_runtime import effective_runtime_dispatch_enabled


class PaperSessionValidationTests(unittest.TestCase):
    def setUp(self):
        self.config = replace(load_config("config/m15_longbridge_marketdata.production.json"),
                              paper_validation_approved=True, paper_validation_market_date="2026-09-08")
        self.now = datetime(2026, 9, 8, 14, tzinfo=UTC)

    def test_explicit_date_only(self):
        self.assertTrue(paper_validation_authorized(self.config, self.now))
        self.assertFalse(paper_validation_authorized(self.config, datetime(2026, 9, 9, 14, tzinfo=UTC)))
        self.assertFalse(paper_validation_authorized(replace(self.config, paper_validation_approved=False), self.now))
        self.assertFalse(paper_validation_authorized(self.config, self.now.replace(tzinfo=None)))
        self.assertFalse(paper_validation_authorized(self.config, "invalid"))

    def test_new_york_not_beijing_date(self):
        self.assertTrue(paper_validation_authorized(self.config, "2026-09-09T00:00:00Z"))
        self.assertFalse(paper_validation_authorized(self.config, "2026-09-09T04:00:00Z"))

    def test_paper_only_no_fallback(self):
        for changes in ({"paper_trading_only": False}, {"live_execution": True},
                        {"real_money_actions": True}, {"market_data_transport": "snapshot_poll"},
                        {"market_holidays": ("2026-09-08",)}):
            self.assertFalse(paper_validation_authorized(replace(self.config, **changes), self.now))

    def test_full_session_evidence_not_overwritten(self):
        status = {"paper_validation_authorized": True, "complete_session_gate_passed": False,
                  "paper_validation_market_date": "2026-09-08", "generated_at": self.now.isoformat()}
        with patch("scripts.m15_opening_trade_readiness_lib.paper_validation_authorized", return_value=True):
            result = marketdata_gate_truth(status, self.config, self.now)
        self.assertTrue(result["gate_passed"])
        self.assertFalse(result["complete_session_passed"])
        self.assertEqual(result["status"], "paper_order_validation")
        self.assertFalse(status["complete_session_gate_passed"])

    def test_missing_raw_safety_fields_rejected(self):
        payload = json.loads(self.config.config_path.read_text())
        for key in ("paper_trading_only", "live_execution", "real_money_actions", "market_data_transport"):
            value = json.loads(json.dumps(payload))
            value["runtime"].pop(key)
            with TemporaryDirectory() as directory:
                path = Path(directory) / "runtime.json"
                path.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, "explicit_paper_only"):
                    load_config(path)

    def test_stale_and_cross_date_status_not_authority(self):
        status = dict(paper_validation_authorized=True, paper_validation_market_date="2026-09-08", generated_at=self.now.isoformat())
        self.assertTrue(validation_status_current(status, self.now))
        self.assertFalse(validation_status_current(status, "2026-09-08T14:00:46Z"))
        self.assertFalse(validation_status_current(status, "2026-09-09T14:00:00Z"))
        self.assertFalse(validation_status_current(dict(status, generated_at=""), self.now))

    def test_dispatch_is_not_complete_session_evidence(self):
        from scripts.m15_monday_refresh_acceptance_lib import marketdata_gate_truth as combined
        result = combined(dict(sdk_connected=True, dispatch_enabled=True),
                          dict(new_position_submission_enabled=True, readiness_status="ready_regular_session"),
                          {"status": "ok"}, {"status": "ok"}, self.now)
        self.assertFalse(result["gate_passed"])
        self.assertFalse(result["complete_session_passed"])

    def test_expiry_does_not_grant_unproven_next_session(self):
        self.assertTrue(entry_session_authorized(self.config, False, self.now))
        tomorrow = datetime(2026, 9, 9, 14, tzinfo=UTC)
        self.assertFalse(entry_session_authorized(self.config, False, tomorrow))
        self.assertTrue(entry_session_authorized(self.config, True, tomorrow))

    def test_all_runtime_safety_checks_still_required(self):
        gates = dict(dispatch_requested=True, paper_client_ready=True, trade_context_ready=True,
                     market_data_ready=True, trading_daily_context_ready=True,
                     flatten_blocks_new_entries=False, account_snapshot_ready=True,
                     deployment_ready=True, position_monitoring_ready=True)
        self.assertTrue(effective_runtime_dispatch_enabled(**gates))
        for key in gates:
            altered = dict(gates, **{key: not gates[key]})
            self.assertFalse(effective_runtime_dispatch_enabled(**altered), key)


if __name__ == "__main__":
    unittest.main()
