from __future__ import annotations

import inspect
import json
import unittest
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from src.broker import (
    BrokerAssessmentEnvelope,
    BrokerCredentialPolicy,
    BrokerReadinessConfig,
    build_broker_readiness_plan,
)
from src.risk.contracts import RiskDecision, RiskEvent, SessionRiskState
from src.strategy.contracts import Signal
from src.execution.contracts import ExecutionRequest


class M142BrokerReadinessScaffoldTest(unittest.TestCase):
    def test_default_config_is_dry_run_only_with_no_broker_or_live(self) -> None:
        config = BrokerReadinessConfig()

        self.assertEqual(config.mode, "paper_dry_run_only")
        self.assertFalse(config.broker_connection_enabled)
        self.assertFalse(config.real_order_enabled)
        self.assertFalse(config.live_execution_enabled)
        self.assertFalse(config.paper_trading_approval)
        self.assertTrue(config.kill_switch_enabled)
        self.assertFalse(config.credential_policy.allows_default_values)

    def test_builds_order_preview_only_after_risk_and_internal_sim_gate(self) -> None:
        envelope = BrokerAssessmentEnvelope(request=self._request(), risk_decision=self._risk_decision())

        plan = build_broker_readiness_plan(
            envelope,
            approved_internal_sim_strategy_ids=("M10-PA-004",),
        )

        self.assertEqual(plan.status, "dry_run_ready")
        self.assertEqual(plan.reason_codes, ("paper_dry_run_only", "manual_approval_required_before_any_broker_connection"))
        self.assertIsNotNone(plan.order_preview)
        assert plan.order_preview is not None
        self.assertEqual(plan.order_preview.strategy_id, "M10-PA-004")
        self.assertEqual(plan.order_preview.symbol, "SAMPLE")
        self.assertEqual(plan.order_preview.quantity, Decimal("1"))
        self.assertTrue(plan.order_preview.dry_run_only)
        self.assertFalse(plan.order_preview.broker_connection)
        self.assertFalse(plan.order_preview.real_order)
        self.assertFalse(plan.order_preview.live_execution)
        self.assertTrue(plan.order_preview.approval_required)

    def test_missing_internal_sim_gate_blocks_preview(self) -> None:
        envelope = BrokerAssessmentEnvelope(request=self._request(), risk_decision=self._risk_decision())

        plan = build_broker_readiness_plan(envelope, approved_internal_sim_strategy_ids=())

        self.assertEqual(plan.status, "blocked")
        self.assertIn("strategy_not_approved_internal_sim", plan.reason_codes)
        self.assertIsNone(plan.order_preview)
        self.assertIn("No credentials were read", plan.audit_messages[1])

    def test_risk_block_prevents_preview(self) -> None:
        envelope = BrokerAssessmentEnvelope(
            request=self._request(),
            risk_decision=replace(self._risk_decision(), outcome="block", reason_codes=("fixture_block",)),
        )

        plan = build_broker_readiness_plan(
            envelope,
            approved_internal_sim_strategy_ids=("M10-PA-004",),
        )

        self.assertEqual(plan.status, "blocked")
        self.assertIn("risk_decision_not_allow", plan.reason_codes)
        self.assertIsNone(plan.order_preview)

    def test_unsafe_broker_or_live_config_blocks_before_preview(self) -> None:
        envelope = BrokerAssessmentEnvelope(request=self._request(), risk_decision=self._risk_decision())
        unsafe = BrokerReadinessConfig(
            broker_connection_enabled=True,
            real_order_enabled=True,
            live_execution_enabled=True,
            paper_trading_approval=True,
            kill_switch_enabled=False,
            credential_policy=BrokerCredentialPolicy(
                required_fields=("api_key",),
                allows_default_values=True,
                requires_manual_secret_injection=False,
            ),
        )

        plan = build_broker_readiness_plan(
            envelope,
            config=unsafe,
            approved_internal_sim_strategy_ids=("M10-PA-004",),
        )

        self.assertEqual(plan.status, "blocked")
        self.assertIn("broker_connection_must_stay_disabled", plan.reason_codes)
        self.assertIn("real_order_must_stay_disabled", plan.reason_codes)
        self.assertIn("live_execution_must_stay_disabled", plan.reason_codes)
        self.assertIn("kill_switch_required", plan.reason_codes)
        self.assertIn("default_credentials_disallowed", plan.reason_codes)
        self.assertIsNone(plan.order_preview)

    def test_scaffold_exposes_no_submit_login_or_connect_methods(self) -> None:
        methods = {name for name, member in inspect.getmembers(build_broker_readiness_plan) if inspect.isfunction(member)}

        self.assertFalse({"submit", "login", "connect"} & methods)

    def test_example_config_contains_no_credentials_and_no_live_switches(self) -> None:
        path = Path("config/examples/m14_2_broker_readiness_scaffold.json")
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["mode"], "paper_dry_run_only")
        self.assertFalse(payload["broker_connection_enabled"])
        self.assertFalse(payload["real_order_enabled"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertFalse(payload["paper_trading_approval"])
        self.assertEqual(payload["credential_policy"]["required_fields"], [])
        self.assertFalse(payload["credential_policy"]["allows_default_values"])

    def _request(self) -> ExecutionRequest:
        return ExecutionRequest(
            signal=Signal(
                signal_id="sig-m14-2",
                symbol="SAMPLE",
                market="US",
                timeframe="1d",
                direction="long",
                setup_type="M10-PA-004",
                pa_context="daily paper dry run",
                entry_trigger="approved internal sim signal",
                stop_rule="ledger stop",
                target_rule="ledger target",
                invalidation="ledger invalidation",
                confidence="paper_trial_gate",
                source_refs=("reports/m13_account_operation_ledger.jsonl",),
                explanation="fixture signal for broker readiness dry run",
                risk_notes=("broker_readiness_dry_run_only",),
            ),
            requested_at=datetime(2026, 5, 18, 9, 35, tzinfo=ZoneInfo("America/New_York")),
            session_key="2026-05-18",
            entry_price=Decimal("100"),
            stop_price=Decimal("98"),
            target_price=Decimal("104"),
            proposed_quantity=Decimal("1"),
        )

    def _risk_decision(self) -> RiskDecision:
        return RiskDecision(
            outcome="allow",
            approved_quantity=Decimal("1"),
            risk_amount=Decimal("2"),
            projected_total_exposure=Decimal("100"),
            projected_symbol_exposure_ratio=Decimal("0.05"),
            approved_signal_id="sig-m14-2",
            approved_symbol="SAMPLE",
            approved_market="US",
            approved_timeframe="1d",
            approved_direction="long",
            approved_session_key="2026-05-18",
            approved_entry_price=Decimal("100"),
            approved_stop_price=Decimal("98"),
            reason_codes=("risk_allow",),
            events=(RiskEvent(code="risk_allow", severity="info", message="fixture allow"),),
            resulting_state=SessionRiskState(session_key="2026-05-18"),
        )


if __name__ == "__main__":
    unittest.main()
