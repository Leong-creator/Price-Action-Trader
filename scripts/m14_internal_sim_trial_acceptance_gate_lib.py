#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_internal_sim_trial_acceptance_gate.json"
FORBIDDEN_OPERATIONS = (
    "broker_connection",
    "real_order",
    "live_execution",
    "paper_trading_approval",
    "manual_m12_37_once",
    "m13_registry_mutation",
    "m12_account_specs_mutation",
    "broker_readiness_status_mutation",
    "parameter_mutation",
    "legacy_historical_profit_planning_input",
)


@dataclass(frozen=True, slots=True)
class InternalSimTrialAcceptanceGateConfig:
    stage: str
    project_stage_label: str
    internal_sim_next_session_plan_path: Path
    strategy_next_step_readiness_matrix_path: Path
    project_stage_assessment_path: Path
    post_fresh_refresh_recompute_checklist_path: Path
    objective_blocker_burndown_path: Path
    rescue_post_refresh_outcome_review_path: Path
    acceptance_gate_json_path: Path
    acceptance_gate_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> InternalSimTrialAcceptanceGateConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = InternalSimTrialAcceptanceGateConfig(
        stage=str(payload["stage"]),
        project_stage_label=str(payload["project_stage_label"]),
        internal_sim_next_session_plan_path=resolve_repo_path(inputs["m14_internal_sim_next_session_plan"]),
        strategy_next_step_readiness_matrix_path=resolve_repo_path(
            inputs["m14_strategy_next_step_readiness_matrix"]
        ),
        project_stage_assessment_path=resolve_repo_path(inputs["m14_project_stage_assessment"]),
        post_fresh_refresh_recompute_checklist_path=resolve_repo_path(
            inputs["m14_post_fresh_refresh_recompute_checklist"]
        ),
        objective_blocker_burndown_path=resolve_repo_path(inputs["m14_objective_blocker_burndown"]),
        rescue_post_refresh_outcome_review_path=resolve_repo_path(
            inputs["m14_rescue_post_refresh_outcome_review"]
        ),
        acceptance_gate_json_path=resolve_repo_path(outputs["acceptance_gate_json"]),
        acceptance_gate_md_path=resolve_repo_path(outputs["acceptance_gate_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: InternalSimTrialAcceptanceGateConfig) -> None:
    if config.stage != "M14.internal_sim_trial_acceptance_gate":
        raise ValueError("M14 internal sim trial acceptance gate stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 internal sim trial acceptance gate must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 internal sim trial acceptance gate must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 internal sim trial acceptance gate cannot enable {key}")


def run_m14_internal_sim_trial_acceptance_gate(
    config: InternalSimTrialAcceptanceGateConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    next_session = read_json(config.internal_sim_next_session_plan_path)
    next_step = read_json(config.strategy_next_step_readiness_matrix_path)
    project_stage = read_json(config.project_stage_assessment_path)
    post_fresh_checklist = read_json(config.post_fresh_refresh_recompute_checklist_path)
    objective_blocker = read_json(config.objective_blocker_burndown_path)
    post_refresh = read_json(config.rescue_post_refresh_outcome_review_path)

    matrix_by_strategy = {
        str(row.get("strategy_id", "")): dict(row)
        for row in next_step.get("matrix_rows", [])
        if str(row.get("strategy_id", ""))
    }
    trial_rows = build_trial_rows(next_session, matrix_by_strategy, post_refresh)
    global_gates = build_global_gates(
        next_session=next_session,
        next_step=next_step,
        project_stage=project_stage,
        post_fresh_checklist=post_fresh_checklist,
        objective_blocker=objective_blocker,
        post_refresh=post_refresh,
        trial_rows=trial_rows,
    )
    summary = build_summary(
        next_session=next_session,
        next_step=next_step,
        project_stage=project_stage,
        post_fresh_checklist=post_fresh_checklist,
        objective_blocker=objective_blocker,
        post_refresh=post_refresh,
        trial_rows=trial_rows,
        global_gates=global_gates,
    )
    payload: dict[str, Any] = {
        "schema_version": "m14.internal-sim-trial-acceptance-gate.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "project_stage_label": config.project_stage_label,
        "m14_trading_date": summary["m14_trading_date"],
        "input_refs": {
            "m14_internal_sim_next_session_plan": project_path(config.internal_sim_next_session_plan_path),
            "m14_strategy_next_step_readiness_matrix": project_path(
                config.strategy_next_step_readiness_matrix_path
            ),
            "m14_project_stage_assessment": project_path(config.project_stage_assessment_path),
            "m14_post_fresh_refresh_recompute_checklist": project_path(
                config.post_fresh_refresh_recompute_checklist_path
            ),
            "m14_objective_blocker_burndown": project_path(config.objective_blocker_burndown_path),
            "m14_rescue_post_refresh_outcome_review": project_path(
                config.rescue_post_refresh_outcome_review_path
            ),
        },
        "summary": summary,
        "trial_acceptance_rows": trial_rows,
        "global_acceptance_gates": global_gates,
        "post_trial_recompute_protocol": build_post_trial_recompute_protocol(post_fresh_checklist),
        "hard_boundaries": hard_boundaries(),
        "paper_simulated_only": True,
        "internal_simulated_account": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
        "parameter_mutation": False,
        "legacy_historical_profit_planning_input": False,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.acceptance_gate_json_path, payload)
    config.acceptance_gate_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.acceptance_gate_md_path.write_text(build_acceptance_gate_md(payload), encoding="utf-8")
    return payload


def build_trial_rows(
    next_session: dict[str, Any],
    matrix_by_strategy: dict[str, dict[str, Any]],
    post_refresh: dict[str, Any],
) -> list[dict[str, Any]]:
    post_refresh_summary = post_refresh.get("summary", {})
    rows: list[dict[str, Any]] = []
    for session_row in next_session.get("strategy_session_rows", []):
        strategy_id = str(session_row.get("strategy_id", ""))
        matrix_row = matrix_by_strategy.get(strategy_id, {})
        required_evidence = unique_strings(
            listify(matrix_row.get("required_next_evidence"))
            + [
                "m12_47_supervised_fresh_refresh",
                "post_run_m13_signal_and_account_ledgers",
                "post_refresh_m14_recompute_checklist",
                "legacy_history_metrics_display_only_not_planning_input",
            ]
        )
        if int_or_zero(session_row.get("broker_dry_run_blocked_count")):
            required_evidence.append("broker_dry_run_blockers_remain_watch_only")
        start_gate_passed = bool(
            session_row.get("can_continue_internal_simulated_account", False)
            and matrix_row.get("can_continue_internal_sim_now", False)
            and not matrix_row.get("legacy_historical_profit_planning_input", False)
        )
        status = "hold_internal_sim_trial"
        if start_gate_passed and int_or_zero(session_row.get("broker_dry_run_blocked_count")):
            status = "ready_internal_sim_trial_with_broker_watch_only"
        elif start_gate_passed:
            status = "ready_internal_sim_trial"
        rows.append(
            {
                "strategy_id": strategy_id,
                "display_name": first_non_empty(session_row.get("display_name"), matrix_row.get("display_name")),
                "runtime_ids": listify(session_row.get("runtime_ids")),
                "current_bucket": str(matrix_row.get("current_bucket", "")),
                "next_step_type": str(matrix_row.get("next_step_type", "")),
                "session_action": str(session_row.get("session_action", "")),
                "trial_mode": "m12_47_supervised_internal_simulated_account",
                "trial_start_status": status,
                "start_gate_passed": start_gate_passed,
                "post_refresh_acceptance_status": (
                    "waiting_for_m12_47_fresh_refresh"
                    if not bool(post_refresh_summary.get("fresh_refresh_observed", False))
                    else "ready_for_post_refresh_review"
                ),
                "fresh_refresh_required": "m12_47_fresh_refresh" in set(required_evidence)
                or "m12_47_fresh_refresh_not_observed" in set(listify(matrix_row.get("blocked_by"))),
                "post_refresh_fresh_refresh_observed": bool(post_refresh_summary.get("fresh_refresh_observed", False)),
                "post_refresh_source_quote": str(post_refresh_summary.get("source_quote", "")),
                "completed_trading_days": int_or_zero(matrix_row.get("completed_trading_days")),
                "linked_next_refresh_watch_count": int_or_zero(session_row.get("linked_next_refresh_watch_count")),
                "linked_next_refresh_family_counts": dict(session_row.get("linked_next_refresh_family_counts", {})),
                "m12_account_input_connected_runtime_count": int_or_zero(
                    session_row.get("m12_account_input_connected_runtime_count")
                ),
                "m12_account_input_runtime_count": int_or_zero(session_row.get("m12_account_input_runtime_count")),
                "m13_signal_count": int_or_zero(session_row.get("m13_signal_count")),
                "m13_open_count": int_or_zero(session_row.get("m13_open_count")),
                "m13_close_count": int_or_zero(session_row.get("m13_close_count")),
                "broker_dry_run_ready_count": int_or_zero(session_row.get("broker_dry_run_ready_count")),
                "broker_dry_run_blocked_count": int_or_zero(session_row.get("broker_dry_run_blocked_count")),
                "broker_blocker_reason_counts": dict(session_row.get("broker_blocker_reason_counts", {})),
                "required_trial_evidence": required_evidence,
                "post_refresh_acceptance_checks": post_refresh_acceptance_checks(session_row, matrix_row),
                "allowed_operations": ["m12_47_supervised_refresh_review", "artifact_review"],
                "forbidden_operations": list(FORBIDDEN_OPERATIONS),
                "can_start_broker_paper": False,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
                "manual_m12_37_once": False,
                "m13_registry_mutation": False,
                "m12_account_specs_mutation": False,
                "broker_readiness_status_mutation": False,
                "parameter_mutation": False,
                "legacy_historical_profit_planning_input": False,
            }
        )
    rows.sort(key=lambda row: (not row["start_gate_passed"], row["strategy_id"]))
    return rows


def post_refresh_acceptance_checks(session_row: dict[str, Any], matrix_row: dict[str, Any]) -> list[str]:
    checks = [
        "fresh_longbridge_quote_readonly_observed",
        "m12_47_owned_m12_m13_refresh",
        "m13_signal_and_account_ledgers_updated",
        "m14_post_fresh_recompute_checklist_rerun",
        "strategy_remains_approved_internal_sim_only",
        "legacy_history_metric_planning_input_false",
        "broker_live_real_order_boundaries_false",
    ]
    if int_or_zero(session_row.get("broker_dry_run_blocked_count")):
        checks.append("broker_dry_run_blockers_remain_watch_only")
    if "first_m13_rescue_ledger" in set(listify(matrix_row.get("required_next_evidence"))):
        checks.append("first_rescue_specific_m13_ledger_watch")
    if "shadow_parameter_review" in set(listify(matrix_row.get("required_next_evidence"))):
        checks.append("shadow_parameter_review_waits_for_fresh_evidence")
    return checks


def build_global_gates(
    *,
    next_session: dict[str, Any],
    next_step: dict[str, Any],
    project_stage: dict[str, Any],
    post_fresh_checklist: dict[str, Any],
    objective_blocker: dict[str, Any],
    post_refresh: dict[str, Any],
    trial_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    next_summary = next_session.get("summary", {})
    next_step_summary = next_step.get("summary", {})
    project_summary = project_stage.get("summary", {})
    checklist_summary = post_fresh_checklist.get("summary", {})
    blocker_summary = objective_blocker.get("summary", {})
    post_summary = post_refresh.get("summary", {})
    return [
        {
            "gate_id": "internal_sim_trial_start_gate",
            "state": "pass" if all(row["start_gate_passed"] for row in trial_rows) and trial_rows else "blocked",
            "evidence": (
                f"{int_or_zero(next_summary.get('launch_ready_strategy_count'))}/"
                f"{int_or_zero(next_summary.get('approved_internal_sim_strategy_count'))} approved strategies launch-ready; "
                f"{int_or_zero(next_summary.get('approved_runtime_input_connected_count'))}/"
                f"{int_or_zero(next_summary.get('approved_runtime_input_count'))} approved runtime inputs connected."
            ),
            "pass_action": "Wait for M12.47 to own the next trading-window refresh.",
            "fail_action": "Hold affected strategy until gate/runtime/input mapping is repaired.",
        },
        {
            "gate_id": "m12_47_fresh_refresh_gate",
            "state": "pass" if bool(post_summary.get("fresh_refresh_observed", False)) else "waiting",
            "evidence": f"fresh_refresh_observed={bool(post_summary.get('fresh_refresh_observed', False))}; source_quote={post_summary.get('source_quote', '')}",
            "pass_action": "Evaluate post-refresh trial rows and rescue watches.",
            "fail_action": "Keep current plan as waiting; do not manually run M12.37 once-mode.",
        },
        {
            "gate_id": "post_fresh_recompute_gate",
            "state": "waiting" if not bool(post_summary.get("fresh_refresh_observed", False)) else "ready",
            "evidence": (
                f"checklist steps={int_or_zero(checklist_summary.get('recompute_step_count'))}; "
                f"acceptance gates={int_or_zero(checklist_summary.get('acceptance_gate_count'))}; "
                f"two_pass_required={bool(checklist_summary.get('two_pass_stabilization_required', False))}."
            ),
            "pass_action": "Rerun M14 read-only recompute sequence and then refresh project stage assessment.",
            "fail_action": "Do not declare objective complete until recompute artifacts are refreshed.",
        },
        {
            "gate_id": "legacy_history_metric_exclusion_gate",
            "state": "pass"
            if int_or_zero(blocker_summary.get("legacy_historical_profit_planning_input_count"))
            + int_or_zero(next_step_summary.get("legacy_historical_profit_planning_input_count"))
            == 0
            else "blocked",
            "evidence": (
                "legacy inputs blocker/next-step="
                f"{int_or_zero(blocker_summary.get('legacy_historical_profit_planning_input_count'))}/"
                f"{int_or_zero(next_step_summary.get('legacy_historical_profit_planning_input_count'))}"
            ),
            "pass_action": "Keep account-dashboard history metrics display-only.",
            "fail_action": "Block strategy planning until legacy history input is removed.",
        },
        {
            "gate_id": "broker_live_boundary_gate",
            "state": "pass" if not bool(project_summary.get("broker_or_live_enabled", False)) else "blocked",
            "evidence": (
                f"can_start_broker_paper={bool(project_summary.get('can_start_broker_paper', False))}; "
                f"manual_m12_37_once_allowed={bool(project_summary.get('manual_m12_37_once_allowed', False))}"
            ),
            "pass_action": "Continue internal simulated-account trial only.",
            "fail_action": "Stop and inspect boundary regression before further readiness work.",
        },
    ]


def build_summary(
    *,
    next_session: dict[str, Any],
    next_step: dict[str, Any],
    project_stage: dict[str, Any],
    post_fresh_checklist: dict[str, Any],
    objective_blocker: dict[str, Any],
    post_refresh: dict[str, Any],
    trial_rows: list[dict[str, Any]],
    global_gates: list[dict[str, Any]],
) -> dict[str, Any]:
    next_summary = next_session.get("summary", {})
    next_step_summary = next_step.get("summary", {})
    project_summary = project_stage.get("summary", {})
    checklist_summary = post_fresh_checklist.get("summary", {})
    blocker_summary = objective_blocker.get("summary", {})
    post_summary = post_refresh.get("summary", {})
    gate_counts = Counter(str(row["state"]) for row in global_gates)
    ready_rows = [row for row in trial_rows if row["start_gate_passed"]]
    return {
        "m14_trading_date": str(project_stage.get("m14_trading_date") or next_session.get("m14_trading_date", "")),
        "current_project_stage": str(project_summary.get("current_project_stage", "")),
        "challenge_progress_label": str(project_summary.get("challenge_progress_label", "")),
        "approved_trial_strategy_count": len(trial_rows),
        "approved_trial_strategy_ids": [row["strategy_id"] for row in trial_rows],
        "trial_start_ready_count": len(ready_rows),
        "trial_start_ready_strategy_ids": [row["strategy_id"] for row in ready_rows],
        "can_start_internal_sim_trial_now": bool(
            next_summary.get("can_run_next_internal_sim_session", False)
            and len(ready_rows) == len(trial_rows)
            and bool(trial_rows)
        ),
        "next_session_mode": str(next_summary.get("next_session_mode", "")),
        "approved_runtime_input_connected_count": int_or_zero(
            next_summary.get("approved_runtime_input_connected_count")
        ),
        "approved_runtime_input_count": int_or_zero(next_summary.get("approved_runtime_input_count")),
        "broker_watch_strategy_count": int_or_zero(next_summary.get("broker_watch_strategy_count")),
        "broker_watch_strategy_ids": listify(next_summary.get("broker_watch_strategy_ids")),
        "fresh_refresh_required_count": sum(1 for row in trial_rows if row["fresh_refresh_required"]),
        "post_refresh_fresh_refresh_observed": bool(post_summary.get("fresh_refresh_observed", False)),
        "post_refresh_source_quote": str(post_summary.get("source_quote", "")),
        "post_refresh_waiting_count": int_or_zero(post_summary.get("waiting_count")),
        "post_fresh_recompute_step_count": int_or_zero(checklist_summary.get("recompute_step_count")),
        "post_fresh_recompute_acceptance_gate_count": int_or_zero(
            checklist_summary.get("acceptance_gate_count")
        ),
        "global_gate_count": len(global_gates),
        "global_gate_state_counts": dict(sorted(gate_counts.items())),
        "legacy_historical_profit_planning_input_count": sum(
            1 for row in trial_rows if row["legacy_historical_profit_planning_input"]
        )
        + int_or_zero(next_summary.get("legacy_historical_profit_planning_input_count"))
        + int_or_zero(next_step_summary.get("legacy_historical_profit_planning_input_count"))
        + int_or_zero(blocker_summary.get("legacy_historical_profit_planning_input_count")),
        "manual_m12_37_once_allowed": False,
        "can_start_broker_paper": False,
        "broker_or_live_enabled": False,
        "paper_trading_approval": False,
        "parameter_mutation_allowed_count": 0,
        "m13_registry_mutation_count": 0,
        "m12_account_specs_mutation_count": 0,
        "broker_readiness_status_mutation_count": 0,
    }


def build_post_trial_recompute_protocol(post_fresh_checklist: dict[str, Any]) -> list[dict[str, Any]]:
    protocol = []
    for step in post_fresh_checklist.get("recompute_steps", []):
        step_id = str(step.get("step_id", ""))
        if step_id in {
            "review_post_refresh_outcomes",
            "refresh_internal_sim_next_session_plan",
            "strategy_next_step_readiness_matrix_refresh",
            "project_stage_assessment_refresh",
        }:
            protocol.append(
                {
                    "step_id": step_id,
                    "order": int_or_zero(step.get("order")),
                    "command": str(step.get("command", "")),
                    "required_timing": str(step.get("required_timing", "")),
                    "acceptance_hint": str(step.get("acceptance_hint", "")),
                    "manual_m12_37_once_allowed": False,
                    "parameter_mutation": False,
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                }
            )
    return sorted(protocol, key=lambda row: row["order"])


def build_plain_language_result(payload: dict[str, Any]) -> list[str]:
    summary = payload["summary"]
    return [
        (
            f"Internal simulated-account trial start gate is ready for "
            f"{summary['trial_start_ready_count']}/{summary['approved_trial_strategy_count']} approved strategies."
        ),
        (
            f"Fresh refresh still required for {summary['fresh_refresh_required_count']} trial rows; "
            f"post-refresh observed={summary['post_refresh_fresh_refresh_observed']} "
            f"source_quote={summary['post_refresh_source_quote']}."
        ),
        (
            "Broker paper/live/manual M12.37/parameter mutation remain disabled; "
            f"legacy historical profit planning inputs={summary['legacy_historical_profit_planning_input_count']}."
        ),
    ]


def build_acceptance_gate_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Internal Sim Trial Acceptance Gate",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge progress: `{summary['challenge_progress_label']}`",
        f"- Approved trial strategies: `{summary['approved_trial_strategy_count']}`",
        f"- Trial start ready: `{summary['trial_start_ready_count']}`",
        f"- Can start internal sim trial now: `{summary['can_start_internal_sim_trial_now']}`",
        f"- Fresh-refresh-required rows: `{summary['fresh_refresh_required_count']}`",
        f"- Post-refresh observed/source/waiting: "
        f"`{summary['post_refresh_fresh_refresh_observed']}/"
        f"{summary['post_refresh_source_quote']}/"
        f"{summary['post_refresh_waiting_count']}`",
        f"- Legacy history metric planning inputs: `{summary['legacy_historical_profit_planning_input_count']}`",
        f"- Broker paper/live/manual M12.37/parameter mutation: "
        f"`{summary['can_start_broker_paper']}/"
        f"{summary['broker_or_live_enabled']}/"
        f"{summary['manual_m12_37_once_allowed']}/"
        f"{summary['parameter_mutation_allowed_count']}`",
        "",
        "## Plain Result",
        "",
    ]
    lines.extend(f"- {item}" for item in payload["plain_language_result"])
    lines.extend(["", "## Global Gates", ""])
    for gate in payload["global_acceptance_gates"]:
        lines.append(
            f"- `{gate['state']}` `{gate['gate_id']}`: {gate['evidence']} "
            f"Pass: {gate['pass_action']} Fail: {gate['fail_action']}"
        )
    lines.extend(["", "## Trial Rows", ""])
    lines.append(
        "| Strategy | Start status | Fresh required | Broker watch | Legacy input | Post-refresh checks |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for row in payload["trial_acceptance_rows"]:
        checks = ", ".join(row["post_refresh_acceptance_checks"][:6])
        if len(row["post_refresh_acceptance_checks"]) > 6:
            checks += f", +{len(row['post_refresh_acceptance_checks']) - 6} more"
        lines.append(
            "| "
            f"{row['strategy_id']} | "
            f"{row['trial_start_status']} | "
            f"{row['fresh_refresh_required']} | "
            f"{row['broker_dry_run_blocked_count']} | "
            f"{row['legacy_historical_profit_planning_input']} | "
            f"{checks} |"
        )
    lines.extend(["", "## Post-Trial Recompute Protocol", ""])
    for step in payload["post_trial_recompute_protocol"]:
        lines.append(f"- `{step['order']}` `{step['step_id']}`: `{step['command']}`")
    lines.append("")
    return "\n".join(lines)


def hard_boundaries() -> dict[str, bool]:
    return {
        "paper_simulated_only": True,
        "internal_simulated_account": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
        "parameter_mutation": False,
        "legacy_historical_profit_planning_input": False,
    }


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "")
        if text:
            return text
    return ""


def unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "")
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
