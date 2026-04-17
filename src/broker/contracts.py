from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from src.execution.contracts import ExecutionRequest
from src.risk.contracts import RiskDecision

AssessmentMode = Literal["assessment_only"]
ReadinessStatus = Literal["not_started", "needs_review", "ready_for_manual_approval"]


@dataclass(frozen=True, slots=True)
class BrokerCapabilityRequirement:
    code: str
    description: str
    mandatory: bool = True


@dataclass(frozen=True, slots=True)
class BrokerCredentialPolicy:
    required_fields: tuple[str, ...] = ()
    allows_default_values: bool = False
    requires_manual_secret_injection: bool = True


@dataclass(frozen=True, slots=True)
class BrokerExecutionGateDependency:
    requires_execution_request: bool = True
    requires_risk_decision: bool = True
    allowed_risk_outcomes: tuple[str, ...] = ("allow",)
    allowed_execution_modes: tuple[str, ...] = ("paper", "simulated")


@dataclass(frozen=True, slots=True)
class FormalBrokerAdapterDraft:
    adapter_name: str = "FormalBrokerAdapter"
    mode: AssessmentMode = "assessment_only"
    readiness_status: ReadinessStatus = "not_started"
    live_execution_enabled: bool = False
    assessment_only: bool = True
    requires_manual_approval: bool = True
    credential_policy: BrokerCredentialPolicy = field(default_factory=BrokerCredentialPolicy)
    gate_dependency: BrokerExecutionGateDependency = field(
        default_factory=BrokerExecutionGateDependency
    )
    capability_requirements: tuple[BrokerCapabilityRequirement, ...] = field(
        default_factory=lambda: (
            BrokerCapabilityRequirement(
                code="risk_gate_required",
                description="A pre-approved RiskDecision must exist before any broker readiness review.",
            ),
            BrokerCapabilityRequirement(
                code="paper_execution_baseline_required",
                description="Paper/simulated execution must remain the default path before broker assessment advances.",
            ),
            BrokerCapabilityRequirement(
                code="manual_approval_required",
                description="Any future broker activation requires explicit manual approval outside this draft.",
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class BrokerAssessmentEnvelope:
    request: ExecutionRequest
    risk_decision: RiskDecision
    draft: FormalBrokerAdapterDraft = field(default_factory=FormalBrokerAdapterDraft)
