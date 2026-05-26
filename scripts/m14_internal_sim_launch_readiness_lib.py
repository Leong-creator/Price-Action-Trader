#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_internal_sim_launch_readiness.json"


@dataclass(frozen=True, slots=True)
class InternalSimLaunchReadinessConfig:
    stage: str
    project_stage_label: str
    m14_summary_path: Path
    paper_gate_path: Path
    runtime_registry_path: Path
    account_input_audit_path: Path
    m13_scorecard_path: Path
    broker_readiness_path: Path
    readiness_json_path: Path
    readiness_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> InternalSimLaunchReadinessConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = InternalSimLaunchReadinessConfig(
        stage=str(payload["stage"]),
        project_stage_label=str(payload["project_stage_label"]),
        m14_summary_path=resolve_repo_path(inputs["m14_summary"]),
        paper_gate_path=resolve_repo_path(inputs["m14_paper_trial_gate"]),
        runtime_registry_path=resolve_repo_path(inputs["m13_strategy_runtime_registry"]),
        account_input_audit_path=resolve_repo_path(inputs["m12_account_input_audit"]),
        m13_scorecard_path=resolve_repo_path(inputs["m13_daily_strategy_scorecard"]),
        broker_readiness_path=resolve_repo_path(inputs["m14_2_broker_readiness_plan"]),
        readiness_json_path=resolve_repo_path(outputs["readiness_json"]),
        readiness_md_path=resolve_repo_path(outputs["readiness_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: InternalSimLaunchReadinessConfig) -> None:
    if config.stage != "M14.internal_sim_launch_readiness":
        raise ValueError("M14 internal simulated launch readiness stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 internal simulated launch readiness must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 internal simulated launch readiness must keep internal simulated account enabled")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 internal simulated launch readiness cannot enable {key}")


def run_m14_internal_sim_launch_readiness(
    config: InternalSimLaunchReadinessConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary = read_json(config.m14_summary_path)
    paper_gate = read_json(config.paper_gate_path)
    registry = read_json(config.runtime_registry_path)
    account_audit = read_json(config.account_input_audit_path)
    m13_scorecard = read_json(config.m13_scorecard_path)
    broker_readiness = read_json(config.broker_readiness_path)

    approved_ids = tuple(str(item) for item in paper_gate.get("approved_internal_sim_strategy_ids", []))
    gate_rows = {str(row.get("strategy_id", "")): row for row in paper_gate.get("rows", [])}
    registry_rows = {str(row.get("strategy_id", "")): row for row in registry.get("strategies", [])}
    audit_rows = list_rows(account_audit)
    audit_by_runtime = {str(row.get("runtime_id", "")): row for row in audit_rows}
    scorecard_rows = list_rows(m13_scorecard)
    scorecard_by_strategy = {str(row.get("strategy_id", "")): row for row in scorecard_rows}
    broker_rows = [dict(row) for row in broker_readiness.get("rows", [])]
    broker_rows_by_strategy: dict[str, list[dict[str, Any]]] = {}
    for row in broker_rows:
        broker_rows_by_strategy.setdefault(str(row.get("strategy_id", "")), []).append(row)

    boundaries = build_boundaries(summary, paper_gate, broker_readiness)
    hard_boundary_violation_count = sum(1 for value in boundaries.values() if not value)
    ten_day_complete = (
        int_or_zero(summary.get("effective_challenge_trading_days")) >= int_or_zero(summary.get("required_challenge_trading_days"))
        and str(summary.get("challenge_progress_label", "")) == "10/10"
    )

    rows = [
        build_strategy_row(
            strategy_id=strategy_id,
            gate_row=gate_rows.get(strategy_id, {}),
            registry_row=registry_rows.get(strategy_id, {}),
            audit_by_runtime=audit_by_runtime,
            scorecard_row=scorecard_by_strategy.get(strategy_id, {}),
            broker_rows=broker_rows_by_strategy.get(strategy_id, []),
            ten_day_complete=ten_day_complete,
            hard_boundary_violation_count=hard_boundary_violation_count,
        )
        for strategy_id in approved_ids
    ]

    summary_payload = build_summary(rows, broker_readiness, ten_day_complete, hard_boundary_violation_count)
    payload: dict[str, Any] = {
        "schema_version": "m14.internal-sim-launch-readiness.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "project_stage_label": config.project_stage_label,
        "m14_trading_date": str(summary.get("trading_date", "")),
        "input_refs": {
            "m14_summary": project_path(config.m14_summary_path),
            "m14_paper_trial_gate": project_path(config.paper_gate_path),
            "m13_strategy_runtime_registry": project_path(config.runtime_registry_path),
            "m12_account_input_audit": project_path(config.account_input_audit_path),
            "m13_daily_strategy_scorecard": project_path(config.m13_scorecard_path),
            "m14_2_broker_readiness_plan": project_path(config.broker_readiness_path),
        },
        "challenge": {
            "challenge_progress_label": str(summary.get("challenge_progress_label", "")),
            "effective_challenge_trading_days": int_or_zero(summary.get("effective_challenge_trading_days")),
            "required_challenge_trading_days": int_or_zero(summary.get("required_challenge_trading_days")),
            "ten_day_challenge_complete": ten_day_complete,
            "data_quality_state": str(summary.get("data_quality_state", "")),
            "m12_current_day_runtime_ready": bool(summary.get("m12_current_day_runtime_ready", False)),
        },
        "summary": summary_payload,
        "strategy_rows": rows,
        "execution_boundaries": boundaries,
        "hard_boundaries": dict(config.hard_boundaries),
        "plain_language_result": build_plain_language_result(summary_payload),
    }
    write_json(config.readiness_json_path, payload)
    config.readiness_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.readiness_md_path.write_text(build_readiness_md(payload), encoding="utf-8")
    return payload


def build_strategy_row(
    *,
    strategy_id: str,
    gate_row: dict[str, Any],
    registry_row: dict[str, Any],
    audit_by_runtime: dict[str, dict[str, Any]],
    scorecard_row: dict[str, Any],
    broker_rows: list[dict[str, Any]],
    ten_day_complete: bool,
    hard_boundary_violation_count: int,
) -> dict[str, Any]:
    gate_runtime_ids = tuple(str(item) for item in gate_row.get("runtime_ids", []))
    registry_accounts = list(registry_row.get("runtime_accounts", []))
    registry_runtime_ids = tuple(str(account.get("runtime_id", "")) for account in registry_accounts)
    missing_registry_runtime_ids = [runtime_id for runtime_id in gate_runtime_ids if runtime_id not in registry_runtime_ids]
    account_input_rows = [audit_by_runtime.get(runtime_id, {}) for runtime_id in gate_runtime_ids]
    missing_account_input_runtime_ids = [
        runtime_id for runtime_id, audit in zip(gate_runtime_ids, account_input_rows, strict=False) if not audit
    ]
    connected_runtime_count = sum(1 for audit in account_input_rows if truthy_string(audit.get("formal_input_stream")))
    ready_broker_rows = [row for row in broker_rows if row.get("readiness_status") == "dry_run_ready"]
    blocked_broker_rows = [row for row in broker_rows if row.get("readiness_status") == "blocked"]
    reason_counts = Counter(
        reason
        for row in blocked_broker_rows
        for reason in list(row.get("source_risk_reason_codes", [])) + list(row.get("reason_codes", []))
        if reason
    )
    gate_approved = str(gate_row.get("paper_trial_gate", "")) == "approved_internal_sim_only"
    runtime_registry_connected = bool(registry_row) and not missing_registry_runtime_ids
    account_inputs_connected = not missing_account_input_runtime_ids and connected_runtime_count == len(gate_runtime_ids)
    can_continue_internal_sim = bool(
        ten_day_complete
        and gate_approved
        and runtime_registry_connected
        and account_inputs_connected
        and hard_boundary_violation_count == 0
    )
    status = "blocked_internal_sim_launch_check"
    if can_continue_internal_sim and blocked_broker_rows:
        status = "ready_internal_sim_continue_with_broker_dry_run_watch"
    elif can_continue_internal_sim:
        status = "ready_internal_sim_continue"

    return {
        "strategy_id": strategy_id,
        "display_name": str(gate_row.get("display_name") or registry_row.get("display_name", "")),
        "paper_trial_gate": str(gate_row.get("paper_trial_gate", "")),
        "decision": str(gate_row.get("decision", "")),
        "completed_trading_days": int_or_zero(gate_row.get("completed_trading_days")),
        "required_trading_days": int_or_zero(gate_row.get("required_trading_days")),
        "gate_runtime_ids": list(gate_runtime_ids),
        "registry_runtime_ids": list(registry_runtime_ids),
        "missing_registry_runtime_ids": missing_registry_runtime_ids,
        "missing_account_input_runtime_ids": missing_account_input_runtime_ids,
        "m13_runtime_registry_connected": runtime_registry_connected,
        "m12_account_input_connected_runtime_count": connected_runtime_count,
        "m12_account_input_runtime_count": len(gate_runtime_ids),
        "m12_account_input_status_counts": dict(sorted(Counter(str(row.get("input_status", "")) for row in account_input_rows if row).items())),
        "m13_scorecard_present": bool(scorecard_row),
        "m13_signal_count": int_or_zero(scorecard_row.get("signal_count")),
        "m13_open_count": int_or_zero(scorecard_row.get("open_count")),
        "m13_close_count": int_or_zero(scorecard_row.get("close_count")),
        "m13_test_states": str(scorecard_row.get("test_states", "")),
        "broker_dry_run_ready_count": len(ready_broker_rows),
        "broker_dry_run_blocked_count": len(blocked_broker_rows),
        "broker_blocker_reason_counts": dict(sorted(reason_counts.items())),
        "can_continue_internal_simulated_account": can_continue_internal_sim,
        "can_start_broker_paper": False,
        "internal_sim_launch_status": status,
        "next_action": next_action(status),
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_summary(
    rows: list[dict[str, Any]],
    broker_readiness: dict[str, Any],
    ten_day_complete: bool,
    hard_boundary_violation_count: int,
) -> dict[str, Any]:
    ready_rows = [row for row in rows if row["can_continue_internal_simulated_account"]]
    broker_watch_rows = [row for row in rows if int_or_zero(row["broker_dry_run_blocked_count"])]
    runtime_total = sum(int_or_zero(row["m12_account_input_runtime_count"]) for row in rows)
    runtime_connected = sum(int_or_zero(row["m12_account_input_connected_runtime_count"]) for row in rows)
    status_counts = Counter(str(row["internal_sim_launch_status"]) for row in rows)
    return {
        "approved_internal_sim_strategy_count": len(rows),
        "launch_ready_strategy_count": len(ready_rows),
        "broker_watch_strategy_count": len(broker_watch_rows),
        "m13_registry_connected_strategy_count": sum(1 for row in rows if row["m13_runtime_registry_connected"]),
        "m12_account_input_connected_runtime_count": runtime_connected,
        "m12_account_input_runtime_count": runtime_total,
        "m13_scorecard_present_strategy_count": sum(1 for row in rows if row["m13_scorecard_present"]),
        "broker_dry_run_ready_count": int_or_zero(broker_readiness.get("dry_run_ready_count")),
        "broker_dry_run_blocked_count": int_or_zero(broker_readiness.get("blocked_count")),
        "source_risk_check_count": int_or_zero(broker_readiness.get("source_risk_check_count")),
        "ten_day_challenge_complete": ten_day_complete,
        "can_continue_internal_simulated_account": len(rows) > 0 and len(ready_rows) == len(rows),
        "can_start_broker_paper": False,
        "manual_approval_required_before_broker_paper": True,
        "hard_boundary_violation_count": hard_boundary_violation_count,
        "launch_status_counts": dict(sorted(status_counts.items())),
        "broker_watch_strategy_ids": [row["strategy_id"] for row in broker_watch_rows],
        "launch_ready_strategy_ids": [row["strategy_id"] for row in ready_rows],
        "broker_connection_enabled": False,
        "real_order_enabled": False,
        "live_execution_enabled": False,
        "paper_trading_approval": False,
    }


def build_boundaries(
    summary: dict[str, Any],
    paper_gate: dict[str, Any],
    broker_readiness: dict[str, Any],
) -> dict[str, bool]:
    return {
        "paper_simulated_only": bool(summary.get("paper_simulated_only")) and bool(paper_gate.get("paper_simulated_only")),
        "internal_simulated_account": bool(summary.get("internal_simulated_account")) and bool(paper_gate.get("internal_simulated_account")),
        "broker_connection_disabled": not (
            bool(summary.get("broker_paper_connection"))
            or bool(paper_gate.get("broker_paper_connection"))
            or bool(paper_gate.get("trading_connection"))
            or bool(broker_readiness.get("broker_connection_enabled"))
        ),
        "real_order_disabled": not (
            bool(summary.get("real_money_actions"))
            or bool(paper_gate.get("real_money_actions"))
            or bool(broker_readiness.get("real_order_enabled"))
        ),
        "live_execution_disabled": not (
            bool(summary.get("live_execution"))
            or bool(paper_gate.get("live_execution"))
            or bool(broker_readiness.get("live_execution_enabled"))
        ),
        "paper_trading_approval_disabled": not (
            bool(summary.get("paper_trading_approval"))
            or bool(paper_gate.get("paper_trading_approval"))
            or bool(broker_readiness.get("paper_trading_approval"))
        ),
        "dry_run_only_not_broker_paper": str(broker_readiness.get("mode", "")) == "paper_dry_run_only",
    }


def build_plain_language_result(summary: dict[str, Any]) -> str:
    return (
        f"Internal simulated-account launch readiness: {summary['launch_ready_strategy_count']}/"
        f"{summary['approved_internal_sim_strategy_count']} approved strategies can continue internal simulation. "
        f"Runtime inputs are connected for {summary['m12_account_input_connected_runtime_count']}/"
        f"{summary['m12_account_input_runtime_count']} approved runtimes. "
        f"Broker dry-run remains preview-only: {summary['broker_dry_run_ready_count']} ready rows, "
        f"{summary['broker_dry_run_blocked_count']} blocked rows; broker paper/live stays disabled and still needs manual approval."
    )


def build_readiness_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Internal Sim Launch Readiness",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Project stage: `{payload['project_stage_label']}`",
        f"- Challenge progress: `{payload['challenge']['challenge_progress_label']}`",
        f"- Launch-ready strategies: `{summary['launch_ready_strategy_count']}/{summary['approved_internal_sim_strategy_count']}`",
        f"- Runtime input coverage: `{summary['m12_account_input_connected_runtime_count']}/{summary['m12_account_input_runtime_count']}`",
        f"- Broker dry-run preview rows: `{summary['broker_dry_run_ready_count']}` ready, `{summary['broker_dry_run_blocked_count']}` blocked",
        "- Boundary: internal simulated accounts only; broker paper, live execution, real orders, and paper-trading approval remain disabled.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Approved Strategy Rows",
        "",
    ]
    for row in payload["strategy_rows"]:
        lines.append(
            f"- `{row['strategy_id']}` `{row['internal_sim_launch_status']}`; "
            f"inputs `{row['m12_account_input_connected_runtime_count']}/{row['m12_account_input_runtime_count']}`; "
            f"broker blocked `{row['broker_dry_run_blocked_count']}`; next `{row['next_action']}`"
        )
    lines.extend(
        [
            "",
            "## Boundary Check",
            "",
        ]
    )
    for key, value in payload["execution_boundaries"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def next_action(status: str) -> str:
    if status == "ready_internal_sim_continue_with_broker_dry_run_watch":
        return "continue_internal_simulated_account_testing_and_track_broker_dry_run_blockers"
    if status == "ready_internal_sim_continue":
        return "continue_internal_simulated_account_testing"
    return "fix_gate_runtime_or_boundary_before_internal_sim_launch"


def list_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows", payload if isinstance(payload, list) else [])
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def truthy_string(value: Any) -> bool:
    return str(value).lower() == "true" or value is True
