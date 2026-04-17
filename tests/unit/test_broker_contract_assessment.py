from __future__ import annotations

import inspect
import unittest
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.broker import (
    BrokerAssessmentEnvelope,
    BrokerCredentialPolicy,
    BrokerExecutionGateDependency,
    FormalBrokerAdapterDraft,
)
from src.execution.contracts import ExecutionRequest
from src.risk.contracts import RiskDecision, RiskEvent, SessionRiskState
from src.strategy.contracts import Signal


class BrokerContractAssessmentTests(unittest.TestCase):
    def test_formal_broker_adapter_draft_is_assessment_only(self) -> None:
        draft = FormalBrokerAdapterDraft()

        self.assertEqual(draft.adapter_name, "FormalBrokerAdapter")
        self.assertEqual(draft.mode, "assessment_only")
        self.assertTrue(draft.assessment_only)
        self.assertFalse(draft.live_execution_enabled)
        self.assertTrue(draft.requires_manual_approval)

    def test_gate_dependency_requires_existing_execution_and_risk_gates(self) -> None:
        draft = FormalBrokerAdapterDraft()

        self.assertIsInstance(draft.gate_dependency, BrokerExecutionGateDependency)
        self.assertTrue(draft.gate_dependency.requires_execution_request)
        self.assertTrue(draft.gate_dependency.requires_risk_decision)
        self.assertEqual(draft.gate_dependency.allowed_risk_outcomes, ("allow",))
        self.assertEqual(draft.gate_dependency.allowed_execution_modes, ("paper", "simulated"))

    def test_contract_has_no_default_credential_values(self) -> None:
        draft = FormalBrokerAdapterDraft()

        self.assertIsInstance(draft.credential_policy, BrokerCredentialPolicy)
        self.assertEqual(draft.credential_policy.required_fields, ())
        self.assertFalse(draft.credential_policy.allows_default_values)
        self.assertTrue(draft.credential_policy.requires_manual_secret_injection)

    def test_contract_surface_has_no_live_submit_login_or_connect_methods(self) -> None:
        draft_attributes = {name for name, member in inspect.getmembers(FormalBrokerAdapterDraft) if inspect.isfunction(member)}

        self.assertFalse({"submit", "login", "connect"} & draft_attributes)
        self.assertNotIn("live_execution_enabled", {field.name for field in fields(BrokerCredentialPolicy)})

    def test_assessment_envelope_reuses_existing_request_and_risk_types(self) -> None:
        envelope = BrokerAssessmentEnvelope(
            request=self._request(),
            risk_decision=self._risk_decision(),
        )

        self.assertIsInstance(envelope.request, ExecutionRequest)
        self.assertIsInstance(envelope.risk_decision, RiskDecision)
        self.assertEqual(envelope.draft.mode, "assessment_only")
        self.assertFalse(envelope.draft.live_execution_enabled)

    def _request(self) -> ExecutionRequest:
        return ExecutionRequest(
            signal=Signal(
                signal_id="sig-broker-assessment",
                symbol="SAMPLE",
                market="US",
                timeframe="5m",
                direction="long",
                setup_type="signal_bar_entry_placeholder",
                pa_context="trend",
                entry_trigger="placeholder entry",
                stop_rule="signal-bar low",
                target_rule="2R target",
                invalidation="close back below prior high",
                confidence="low",
                source_refs=("wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md",),
                explanation="research-only paper signal",
                risk_notes=("research-only placeholder",),
            ),
            requested_at=datetime(2026, 1, 5, 9, 30, tzinfo=ZoneInfo("America/New_York")),
            session_key="2026-01-05",
            entry_price=Decimal("100"),
            stop_price=Decimal("99"),
            target_price=Decimal("102"),
            proposed_quantity=Decimal("1"),
        )

    def _risk_decision(self) -> RiskDecision:
        return RiskDecision(
            outcome="allow",
            approved_quantity=Decimal("1"),
            risk_amount=Decimal("1"),
            projected_total_exposure=Decimal("100"),
            projected_symbol_exposure_ratio=Decimal("1"),
            approved_signal_id="sig-broker-assessment",
            approved_symbol="SAMPLE",
            approved_market="US",
            approved_timeframe="5m",
            approved_direction="long",
            approved_session_key="2026-01-05",
            approved_entry_price=Decimal("100"),
            approved_stop_price=Decimal("99"),
            reason_codes=("risk_allow",),
            events=(RiskEvent(code="risk_allow", severity="info", message="paper gate passed"),),
            resulting_state=SessionRiskState(session_key="2026-01-05"),
        )


if __name__ == "__main__":
    unittest.main()
