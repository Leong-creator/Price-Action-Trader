from __future__ import annotations

from hashlib import sha256

from .contracts import (
    BrokerAssessmentEnvelope,
    BrokerOrderPreview,
    BrokerReadinessConfig,
    BrokerReadinessPlan,
)


def build_broker_readiness_plan(
    envelope: BrokerAssessmentEnvelope,
    *,
    config: BrokerReadinessConfig | None = None,
    approved_internal_sim_strategy_ids: tuple[str, ...] = (),
) -> BrokerReadinessPlan:
    config = config or BrokerReadinessConfig()
    reason_codes = _boundary_reason_codes(config)
    request = envelope.request
    risk_decision = envelope.risk_decision
    strategy_id = request.signal.setup_type

    if risk_decision.outcome != "allow":
        reason_codes.append("risk_decision_not_allow")
    if risk_decision.approved_signal_id != request.signal.signal_id:
        reason_codes.append("risk_decision_signal_mismatch")
    if risk_decision.approved_symbol != request.signal.symbol:
        reason_codes.append("risk_decision_symbol_mismatch")
    if config.requires_approved_internal_sim_gate and strategy_id not in approved_internal_sim_strategy_ids:
        reason_codes.append("strategy_not_approved_internal_sim")

    if reason_codes:
        return BrokerReadinessPlan(
            status="blocked",
            reason_codes=tuple(reason_codes),
            request=request,
            risk_decision=risk_decision,
            order_preview=None,
            audit_messages=(
                "Broker readiness scaffold blocked before any broker connection or order submission.",
                "No credentials were read and no external broker API was called.",
            ),
            config=config,
        )

    preview = BrokerOrderPreview(
        preview_id=_preview_id(request.signal.signal_id, request.session_key),
        signal_id=request.signal.signal_id,
        strategy_id=strategy_id,
        symbol=request.signal.symbol,
        market=request.signal.market,
        timeframe=request.signal.timeframe,
        side=request.signal.direction,
        order_type="limit_entry_with_attached_stop_target",
        quantity=risk_decision.approved_quantity,
        limit_price=request.entry_price,
        stop_price=request.stop_price,
        target_price=request.target_price,
    )
    return BrokerReadinessPlan(
        status="dry_run_ready",
        reason_codes=("paper_dry_run_only", "manual_approval_required_before_any_broker_connection"),
        request=request,
        risk_decision=risk_decision,
        order_preview=preview,
        audit_messages=(
            "Broker order preview created for readiness only.",
            "The preview is not a broker order and cannot be submitted by this scaffold.",
            "Real broker paper/live activation still requires separate user approval.",
        ),
        config=config,
    )


def _boundary_reason_codes(config: BrokerReadinessConfig) -> list[str]:
    reasons: list[str] = []
    if config.mode != "paper_dry_run_only":
        reasons.append("unsupported_readiness_mode")
    if config.broker_connection_enabled:
        reasons.append("broker_connection_must_stay_disabled")
    if config.real_order_enabled:
        reasons.append("real_order_must_stay_disabled")
    if config.live_execution_enabled:
        reasons.append("live_execution_must_stay_disabled")
    if config.paper_trading_approval:
        reasons.append("paper_trading_approval_must_stay_false")
    if not config.kill_switch_enabled:
        reasons.append("kill_switch_required")
    if config.credential_policy.allows_default_values:
        reasons.append("default_credentials_disallowed")
    if not config.credential_policy.requires_manual_secret_injection:
        reasons.append("manual_secret_injection_required")
    return reasons


def _preview_id(signal_id: str, session_key: str) -> str:
    digest = sha256(f"{signal_id}:{session_key}".encode("utf-8")).hexdigest()[:16]
    return f"broker-preview-{digest}"
