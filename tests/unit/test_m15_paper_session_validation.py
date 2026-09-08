from dataclasses import replace
from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from scripts.m15_longbridge_sdk_runtime_lib import load_config
from scripts.m15_paper_session_validation_lib import (
    paper_validation_authorized, entry_session_authorized,
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
        status = {"paper_validation_authorized": True, "complete_session_gate_passed": False}
        with patch("scripts.m15_opening_trade_readiness_lib.paper_validation_authorized", return_value=True):
            result = marketdata_gate_truth(status, self.config)
        self.assertTrue(result["gate_passed"])
        self.assertFalse(result["complete_session_passed"])
        self.assertEqual(result["status"], "paper_order_validation")
        self.assertFalse(status["complete_session_gate_passed"])

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
