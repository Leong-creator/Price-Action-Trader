#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.broker import BrokerAssessmentEnvelope, BrokerCredentialPolicy, BrokerReadinessConfig, build_broker_readiness_plan
from src.execution import ExecutionRequest
from src.risk import RiskDecision, RiskEvent, SessionRiskState
from src.strategy.contracts import Signal


DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_2_broker_readiness_scaffold.json"
DEFAULT_DAILY_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh" / "daily_observation"


@dataclass(frozen=True, slots=True)
class M142Config:
    stage: str
    mode: str
    broker_connection_enabled: bool
    real_order_enabled: bool
    live_execution_enabled: bool
    paper_trading_approval: bool
    requires_approved_internal_sim_gate: bool
    kill_switch_enabled: bool
    credential_policy: BrokerCredentialPolicy
    paper_gate_path: Path
    internal_paper_execution_ledger_path: Path
    dry_run_plan_path: Path
    audit_log_path: Path


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M142Config:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    inputs = payload.get("inputs", {})
    outputs = payload["outputs"]
    credential_policy = payload.get("credential_policy", {})
    config = M142Config(
        stage=str(payload["stage"]),
        mode=str(payload["mode"]),
        broker_connection_enabled=bool(payload["broker_connection_enabled"]),
        real_order_enabled=bool(payload["real_order_enabled"]),
        live_execution_enabled=bool(payload["live_execution_enabled"]),
        paper_trading_approval=bool(payload["paper_trading_approval"]),
        requires_approved_internal_sim_gate=bool(payload["requires_approved_internal_sim_gate"]),
        kill_switch_enabled=bool(payload["kill_switch_enabled"]),
        credential_policy=BrokerCredentialPolicy(
            required_fields=tuple(str(item) for item in credential_policy.get("required_fields", [])),
            allows_default_values=bool(credential_policy.get("allows_default_values", False)),
            requires_manual_secret_injection=bool(credential_policy.get("requires_manual_secret_injection", True)),
        ),
        paper_gate_path=resolve_repo_path(
            inputs.get(
                "m14_paper_trial_gate",
                DEFAULT_DAILY_DIR / "m14_strategy_challenge" / "m14_paper_trial_gate.json",
            )
        ),
        internal_paper_execution_ledger_path=resolve_repo_path(
            inputs.get(
                "m14_internal_paper_execution_ledger",
                DEFAULT_DAILY_DIR / "m14_strategy_challenge" / "m14_internal_paper_execution_ledger.jsonl",
            )
        ),
        dry_run_plan_path=resolve_repo_path(outputs["dry_run_plan"]),
        audit_log_path=resolve_repo_path(outputs["audit_log"]),
    )
    validate_config(config)
    return config


def validate_config(config: M142Config) -> None:
    if config.stage != "M14.2.broker_readiness_scaffold":
        raise ValueError("M14.2 broker readiness stage drift")
    if config.mode != "paper_dry_run_only":
        raise ValueError("M14.2 broker readiness must stay paper_dry_run_only")
    if config.broker_connection_enabled or config.real_order_enabled or config.live_execution_enabled or config.paper_trading_approval:
        raise ValueError("M14.2 cannot enable broker connection, real orders, live execution, or paper approval")
    if not config.kill_switch_enabled:
        raise ValueError("M14.2 kill switch must stay enabled")
    if config.credential_policy.allows_default_values:
        raise ValueError("M14.2 credential policy cannot allow default values")
    if not config.credential_policy.requires_manual_secret_injection:
        raise ValueError("M14.2 credential policy must require manual secret injection")


def run_broker_readiness_scaffold(
    config: M142Config | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    paper_gate = read_json(config.paper_gate_path)
    approved_ids = tuple(str(item) for item in paper_gate.get("approved_internal_sim_strategy_ids", []))
    source_rows = [
        row
        for row in read_jsonl(config.internal_paper_execution_ledger_path)
        if row.get("action") == "risk_check"
    ]
    broker_config = BrokerReadinessConfig(
        mode="paper_dry_run_only",
        broker_connection_enabled=config.broker_connection_enabled,
        real_order_enabled=config.real_order_enabled,
        live_execution_enabled=config.live_execution_enabled,
        paper_trading_approval=config.paper_trading_approval,
        requires_approved_internal_sim_gate=config.requires_approved_internal_sim_gate,
        kill_switch_enabled=config.kill_switch_enabled,
        credential_policy=config.credential_policy,
    )

    plan_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for row in source_rows:
        envelope = broker_envelope_from_internal_paper_row(row, config.internal_paper_execution_ledger_path)
        plan = build_broker_readiness_plan(
            envelope,
            config=broker_config,
            approved_internal_sim_strategy_ids=approved_ids,
        )
        plan_row = broker_plan_row(generated_at, row, plan)
        plan_rows.append(plan_row)
        audit_rows.append(
            {
                "schema_version": "m14.2.broker-readiness-audit.v1",
                "stage": config.stage,
                "generated_at": generated_at,
                "source_execution_event_id": row.get("execution_event_id", ""),
                "strategy_id": row.get("strategy_id", ""),
                "runtime_id": row.get("runtime_id", ""),
                "signal_id": row.get("signal_id", ""),
                "status": plan.status,
                "reason_codes": list(plan.reason_codes),
                "audit_messages": list(plan.audit_messages),
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )

    summary = {
        "schema_version": "m14.2.broker-readiness-plan.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "paper_gate_ref": project_path(config.paper_gate_path),
        "internal_paper_execution_ledger_ref": project_path(config.internal_paper_execution_ledger_path),
        "audit_log_ref": project_path(config.audit_log_path),
        "approved_internal_sim_strategy_ids": list(approved_ids),
        "source_risk_check_count": len(source_rows),
        "dry_run_ready_count": sum(1 for row in plan_rows if row["readiness_status"] == "dry_run_ready"),
        "blocked_count": sum(1 for row in plan_rows if row["readiness_status"] == "blocked"),
        "rows": plan_rows,
        "mode": "paper_dry_run_only",
        "broker_connection_enabled": False,
        "real_order_enabled": False,
        "live_execution_enabled": False,
        "paper_trading_approval": False,
        "plain_language_result": (
            f"M14.2 inspected {len(source_rows)} internal simulated risk-check events; "
            f"{sum(1 for row in plan_rows if row['readiness_status'] == 'dry_run_ready')} are broker dry-run ready, "
            f"{sum(1 for row in plan_rows if row['readiness_status'] == 'blocked')} remain blocked. "
            "No broker connection, credentials, real orders, or live execution were used."
        ),
    }
    write_json(config.dry_run_plan_path, summary)
    write_jsonl(config.audit_log_path, audit_rows)
    return summary


def broker_envelope_from_internal_paper_row(row: dict[str, Any], source_path: Path) -> BrokerAssessmentEnvelope:
    signal_id = str(row.get("signal_id", ""))
    strategy_id = str(row.get("strategy_id", ""))
    symbol = str(row.get("symbol", ""))
    timeframe = str(row.get("timeframe", ""))
    direction = str(row.get("direction", ""))
    trading_date = str(row.get("trading_date", ""))
    generated_at = str(row.get("generated_at") or trading_date)
    entry_price = decimal(row.get("entry_price"))
    stop_price = decimal(row.get("stop_price"))
    target_price = decimal(row.get("target_price"))
    quantity = decimal(row.get("quantity"))
    risk_outcome = str(row.get("risk_outcome", "block"))
    reason_codes = tuple(code for code in str(row.get("reason_codes", "")).split(",") if code)
    risk_amount = abs(entry_price - stop_price) * quantity
    signal = Signal(
        signal_id=signal_id,
        symbol=symbol,
        market="US",
        timeframe=timeframe,
        direction=direction,
        setup_type=strategy_id,
        pa_context="m14_2_broker_readiness_from_internal_sim",
        entry_trigger="m14_internal_paper_execution_risk_check",
        stop_rule="m14_internal_paper_stop_price",
        target_rule="m14_internal_paper_target_price",
        invalidation="broker_readiness_dry_run_only",
        confidence="paper_trial_gate",
        source_refs=(project_path(source_path),),
        explanation="M14.2 reconstructs a dry-run broker readiness request from the internal simulated execution ledger.",
        risk_notes=("no_broker_connection_no_real_order",),
    )
    request = ExecutionRequest(
        signal=signal,
        requested_at=parse_datetime(generated_at),
        session_key=trading_date,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        proposed_quantity=quantity,
    )
    approved_quantity = quantity if risk_outcome == "allow" else Decimal("0")
    risk_decision = RiskDecision(
        outcome=risk_outcome if risk_outcome in {"allow", "block", "halted", "config_error"} else "block",
        approved_quantity=approved_quantity,
        risk_amount=risk_amount,
        projected_total_exposure=entry_price * quantity,
        projected_symbol_exposure_ratio=Decimal("0"),
        approved_signal_id=signal_id,
        approved_symbol=symbol,
        approved_market="US",
        approved_timeframe=timeframe,
        approved_direction=direction,
        approved_session_key=trading_date,
        approved_entry_price=entry_price,
        approved_stop_price=stop_price,
        reason_codes=reason_codes or (risk_outcome,),
        events=tuple(
            RiskEvent(
                code=code,
                severity="info" if risk_outcome == "allow" else "warning",
                message=f"M14.2 reconstructed risk event from internal paper ledger: {code}",
            )
            for code in (reason_codes or (risk_outcome,))
        ),
        resulting_state=SessionRiskState(session_key=trading_date),
    )
    return BrokerAssessmentEnvelope(request=request, risk_decision=risk_decision)


def broker_plan_row(generated_at: str, source_row: dict[str, Any], plan: Any) -> dict[str, Any]:
    preview = plan.order_preview
    return {
        "schema_version": "m14.2.broker-readiness-row.v1",
        "stage": "M14.2.broker_readiness_scaffold",
        "generated_at": generated_at,
        "source_execution_event_id": source_row.get("execution_event_id", ""),
        "source_action": source_row.get("action", ""),
        "strategy_id": source_row.get("strategy_id", ""),
        "runtime_id": source_row.get("runtime_id", ""),
        "trading_date": source_row.get("trading_date", ""),
        "signal_id": source_row.get("signal_id", ""),
        "symbol": source_row.get("symbol", ""),
        "timeframe": source_row.get("timeframe", ""),
        "direction": source_row.get("direction", ""),
        "risk_outcome": source_row.get("risk_outcome", ""),
        "source_risk_reason_codes": [code for code in str(source_row.get("reason_codes", "")).split(",") if code],
        "readiness_status": plan.status,
        "reason_codes": list(plan.reason_codes),
        "preview_id": preview.preview_id if preview else "",
        "order_type": preview.order_type if preview else "",
        "quantity": fmt_decimal(preview.quantity) if preview else "",
        "limit_price": fmt_decimal(preview.limit_price) if preview else "",
        "stop_price": fmt_decimal(preview.stop_price) if preview else "",
        "target_price": fmt_decimal(preview.target_price) if preview else "",
        "dry_run_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "approval_required": True,
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def parse_datetime(value: str) -> datetime:
    if not value:
        return datetime.now(UTC).replace(microsecond=0)
    candidate = value
    if candidate.endswith("Z"):
        candidate = candidate.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = datetime.fromisoformat(f"{value}T00:00:00+00:00")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value}") from exc


def fmt_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text == "-0" else text
