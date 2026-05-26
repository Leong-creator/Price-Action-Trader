#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_parameter_activation_gate.json"
PASS_STATUSES = frozenset({"passed", "evidence_observed"})
FAIL_STATUSES = frozenset(
    {
        "failed_missing_first_ledger_after_fresh_refresh",
        "failed_zero_signal_after_fresh_refresh",
        "failed_missing_shadow_ledger_after_fresh_refresh",
        "failed_missing_comparable_broker_row_after_fresh_refresh",
        "still_waiting_parent_detector_after_fresh_refresh",
        "unsupported_watch_family",
    }
)


@dataclass(frozen=True, slots=True)
class RescueParameterActivationGateConfig:
    stage: str
    parameter_experiment_queue_path: Path
    post_refresh_outcome_review_path: Path
    activation_gate_json_path: Path
    activation_gate_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescueParameterActivationGateConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescueParameterActivationGateConfig(
        stage=str(payload["stage"]),
        parameter_experiment_queue_path=resolve_repo_path(inputs["m14_rescue_parameter_experiment_queue"]),
        post_refresh_outcome_review_path=resolve_repo_path(inputs["m14_rescue_post_refresh_outcome_review"]),
        activation_gate_json_path=resolve_repo_path(outputs["activation_gate_json"]),
        activation_gate_md_path=resolve_repo_path(outputs["activation_gate_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescueParameterActivationGateConfig) -> None:
    if config.stage != "M14.rescue_parameter_activation_gate":
        raise ValueError("M14 rescue parameter activation gate stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue parameter activation gate must stay paper/simulated only")
    forbidden = (
        "broker_connection",
        "real_order",
        "live_execution",
        "paper_trading_approval",
        "manual_m12_37_once",
        "m13_registry_mutation",
        "m12_account_specs_mutation",
        "broker_readiness_status_mutation",
        "parameter_mutation",
    )
    for key in forbidden:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue parameter activation gate cannot enable {key}")


def run_m14_rescue_parameter_activation_gate(
    config: RescueParameterActivationGateConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    queue = read_json(config.parameter_experiment_queue_path)
    post_refresh = read_json(config.post_refresh_outcome_review_path)

    post_summary = post_refresh.get("summary", {})
    fresh_refresh_observed = bool(post_summary.get("fresh_refresh_observed", False))
    outcome_rows = list(post_refresh.get("rows", []))
    gate_rows = [
        build_gate_row(
            experiment_row=dict(row),
            outcome_row=matching_outcome_row(dict(row), outcome_rows),
            fresh_refresh_observed=fresh_refresh_observed,
        )
        for row in queue.get("experiment_rows", [])
    ]
    gate_rows.sort(key=lambda row: (row["priority"], row["strategy_id"], row["experiment_family"], row["gate_row_id"]))
    gate_counts = Counter(row["gate_state"] for row in gate_rows)
    family_counts = Counter(row["experiment_family"] for row in gate_rows)
    summary = {
        "fresh_refresh_observed": fresh_refresh_observed,
        "source_quote": str(post_summary.get("source_quote", "")),
        "source_scan_date": str(post_summary.get("source_scan_date", "")),
        "latest_ledger_trading_date": str(post_summary.get("latest_ledger_trading_date", "")),
        "gate_row_count": len(gate_rows),
        "shadow_review_candidate_count": sum(1 for row in gate_rows if row["shadow_review_candidate"]),
        "first_ledger_ready_count": gate_counts.get("first_ledger_observed_start_ab_evidence_count", 0),
        "waiting_for_fresh_refresh_count": gate_counts.get("waiting_for_m12_47_fresh_refresh", 0),
        "waiting_for_matching_outcome_count": gate_counts.get("waiting_for_matching_post_refresh_evidence", 0),
        "evidence_failed_count": gate_counts.get("evidence_failed_keep_blocked", 0),
        "continue_ab_collection_count": gate_counts.get("continue_ab_collection_only", 0),
        "manual_review_required_count": sum(1 for row in gate_rows if row["manual_m14_review_required"]),
        "implementation_mutation_allowed_count": 0,
        "parameter_mutation_allowed_count": 0,
        "m13_registry_mutation_count": 0,
        "m12_account_specs_mutation_count": 0,
        "broker_readiness_status_mutation_count": 0,
        "broker_or_live_enabled": False,
        "manual_m12_37_once_allowed": False,
        "gate_state_counts": dict(sorted(gate_counts.items())),
        "experiment_family_counts": dict(sorted(family_counts.items())),
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.rescue-parameter-activation-gate.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_rescue_parameter_experiment_queue": project_path(config.parameter_experiment_queue_path),
            "m14_rescue_post_refresh_outcome_review": project_path(config.post_refresh_outcome_review_path),
        },
        "summary": summary,
        "gate_rows": gate_rows,
        "hard_boundaries": {
            "paper_simulated_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
            "manual_m12_37_once": False,
            "m13_registry_mutation": False,
            "m12_account_specs_mutation": False,
            "broker_readiness_status_mutation": False,
            "parameter_mutation": False,
        },
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
        "parameter_mutation": False,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.activation_gate_json_path, payload)
    config.activation_gate_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.activation_gate_md_path.write_text(build_activation_gate_md(payload), encoding="utf-8")
    return payload


def build_gate_row(
    *,
    experiment_row: dict[str, Any],
    outcome_row: dict[str, Any],
    fresh_refresh_observed: bool,
) -> dict[str, Any]:
    gate_state, gate_reason, next_action, shadow_candidate, manual_review = classify_gate_state(
        experiment_row=experiment_row,
        outcome_row=outcome_row,
        fresh_refresh_observed=fresh_refresh_observed,
    )
    return {
        "gate_row_id": f"m14-param-gate-{slug(str(experiment_row.get('experiment_row_id', '')))}",
        "experiment_row_id": str(experiment_row.get("experiment_row_id", "")),
        "strategy_id": str(experiment_row.get("strategy_id", "")),
        "parent_strategy_id": str(experiment_row.get("parent_strategy_id", "")),
        "runtime_ids": list(experiment_row.get("runtime_ids", [])),
        "priority": str(experiment_row.get("priority", "")),
        "issue_type": str(experiment_row.get("issue_type", "")),
        "dominant_issue": str(experiment_row.get("dominant_issue", "")),
        "experiment_family": str(experiment_row.get("experiment_family", "")),
        "candidate_parameter_family": str(experiment_row.get("candidate_parameter_family", "")),
        "candidate_change_scope": str(experiment_row.get("candidate_change_scope", "")),
        "source_experiment_status": str(experiment_row.get("status", "")),
        "required_readiness_family": readiness_family_for_experiment(experiment_row),
        "matched_outcome_row_id": str(outcome_row.get("row_id", "")),
        "matched_outcome_status": str(outcome_row.get("outcome_status", "")),
        "matched_outcome_passed": bool(outcome_row.get("outcome_passed", False)),
        "matched_outcome_failed": bool(outcome_row.get("outcome_failed", False)),
        "fresh_refresh_observed": fresh_refresh_observed,
        "gate_state": gate_state,
        "gate_reason": gate_reason,
        "next_action": next_action,
        "shadow_review_candidate": shadow_candidate,
        "manual_m14_review_required": manual_review,
        "implementation_mutation_allowed": False,
        "parameter_mutation_allowed": False,
        "parameter_change_allowed_now": False,
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
        "paper_simulated_only": True,
    }


def classify_gate_state(
    *,
    experiment_row: dict[str, Any],
    outcome_row: dict[str, Any],
    fresh_refresh_observed: bool,
) -> tuple[str, str, str, bool, bool]:
    experiment_family = str(experiment_row.get("experiment_family", ""))
    if experiment_family == "continue_ab_evidence_collection":
        return (
            "continue_ab_collection_only",
            "This row already has active rescue evidence; keep collecting the 10-day A/B window.",
            "Continue A/B evidence collection; no parameter activation.",
            False,
            False,
        )
    if not fresh_refresh_observed:
        return (
            "waiting_for_m12_47_fresh_refresh",
            "No fresh M12.47-owned refresh is visible yet.",
            "Wait for M12.47 supervisor-owned refresh; do not run M12.37 once-mode manually.",
            False,
            False,
        )
    outcome_status = str(outcome_row.get("outcome_status", ""))
    if not outcome_status:
        return (
            "waiting_for_matching_post_refresh_evidence",
            "Fresh refresh exists, but no matching post-refresh outcome row was found.",
            "Add or inspect the matching post-refresh watch row before using this parameter family.",
            False,
            False,
        )
    if outcome_status in FAIL_STATUSES:
        return (
            "evidence_failed_keep_blocked",
            f"Post-refresh outcome is {outcome_status}; keep the family blocked.",
            str(outcome_row.get("next_action", "")) or "Keep blocked and repair evidence path.",
            False,
            False,
        )
    if outcome_status in PASS_STATUSES:
        if experiment_family == "ledger_path_mapping_audit":
            return (
                "first_ledger_observed_start_ab_evidence_count",
                "First rescue ledger evidence is present; start or continue the rescue-specific 10-day count.",
                "Start this runtime's own 10-day A/B evidence count; do not promote or mutate parameters yet.",
                False,
                False,
            )
        return (
            "ready_for_shadow_parameter_review",
            "Required post-refresh evidence exists; this family can be reviewed for a later shadow-only parameter experiment.",
            "Prepare manual M14 shadow-review notes; implementation still requires a separate audited change.",
            True,
            True,
        )
    return (
        "waiting_for_matching_post_refresh_evidence",
        f"Outcome status {outcome_status} is not a pass/fail terminal state.",
        "Wait for a terminal post-refresh outcome before activating a parameter family.",
        False,
        False,
    )


def matching_outcome_row(experiment_row: dict[str, Any], outcome_rows: list[dict[str, Any]]) -> dict[str, Any]:
    family = readiness_family_for_experiment(experiment_row)
    strategy_id = str(experiment_row.get("strategy_id", ""))
    parent_strategy_id = str(experiment_row.get("parent_strategy_id", ""))
    runtime_ids = {str(item) for item in experiment_row.get("runtime_ids", []) if str(item)}
    broker_rule_family = broker_rule_family_for_experiment(experiment_row)
    candidates = [
        dict(row)
        for row in outcome_rows
        if str(row.get("readiness_family", "")) == family
        and outcome_matches_strategy(
            row=dict(row),
            strategy_id=strategy_id,
            parent_strategy_id=parent_strategy_id,
            runtime_ids=runtime_ids,
            broker_rule_family=broker_rule_family,
        )
    ]
    if not candidates:
        return {}
    candidates.sort(key=outcome_priority)
    return candidates[0]


def outcome_matches_strategy(
    *,
    row: dict[str, Any],
    strategy_id: str,
    parent_strategy_id: str,
    runtime_ids: set[str],
    broker_rule_family: str,
) -> bool:
    row_strategy = str(row.get("strategy_id", ""))
    row_parent = str(row.get("parent_strategy_id", ""))
    row_runtime = str(row.get("runtime_id", ""))
    if broker_rule_family:
        row_rule_family = str(row.get("source_metrics", {}).get("rule_family", ""))
        if row_rule_family and row_rule_family != broker_rule_family:
            return False
    return (
        row_strategy == strategy_id
        or row_parent == strategy_id
        or (parent_strategy_id and row_strategy == parent_strategy_id)
        or (parent_strategy_id and row_parent == parent_strategy_id)
        or (row_runtime in runtime_ids)
    )


def outcome_priority(row: dict[str, Any]) -> tuple[int, str]:
    status = str(row.get("outcome_status", ""))
    if status in PASS_STATUSES:
        bucket = 0
    elif status in FAIL_STATUSES:
        bucket = 1
    elif status == "waiting_for_m12_47_fresh_refresh":
        bucket = 2
    else:
        bucket = 3
    return (bucket, str(row.get("row_id", "")))


def readiness_family_for_experiment(experiment_row: dict[str, Any]) -> str:
    family = str(experiment_row.get("experiment_family", ""))
    mapping = {
        "fresh_quote_gate_recheck": "fresh_quote_recheck",
        "target_stop_reward_geometry_shadow": "target_stop_shadow_compare",
        "ledger_path_mapping_audit": "first_rescue_ledger_watch",
        "parent_detector_timeframe_mapping_review": "parent_detector_evidence_wait",
        "quantity_cap_shadow": "first_rescue_ledger_watch",
        "exposure_ranker_shadow": "broker_rule_shadow_recheck",
        "cooldown_quality_veto_shadow": "broker_rule_shadow_recheck",
    }
    if family in mapping:
        return mapping[family]
    readiness_families = [str(item) for item in experiment_row.get("readiness_families", []) if str(item)]
    return readiness_families[0] if readiness_families else ""


def broker_rule_family_for_experiment(experiment_row: dict[str, Any]) -> str:
    dominant_issue = str(experiment_row.get("dominant_issue", ""))
    if dominant_issue == "consecutive_losses_limit":
        return "cooldown_quality_veto"
    if dominant_issue == "max_total_exposure_exceeded":
        return "portfolio_exposure_ranker"
    return ""


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Parameter activation gate checked {summary['gate_row_count']} experiment rows. "
        f"Fresh refresh observed: {summary['fresh_refresh_observed']} with quote_source={summary['source_quote']}. "
        f"Shadow-review candidates: {summary['shadow_review_candidate_count']}; "
        f"first-ledger ready rows: {summary['first_ledger_ready_count']}; "
        f"waiting for fresh refresh: {summary['waiting_for_fresh_refresh_count']}; "
        f"evidence failed: {summary['evidence_failed_count']}. "
        "Implementation mutation, parameter mutation, M13 registry mutation, M12 account-spec mutation, broker readiness mutation, "
        "broker connection, real orders, live execution, paper approval, and manual M12.37 once-mode remain disabled."
    )


def build_activation_gate_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Rescue Parameter Activation Gate",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Fresh refresh observed: `{summary['fresh_refresh_observed']}`",
        f"- Quote source: `{summary['source_quote']}`",
        f"- Gate rows: `{summary['gate_row_count']}`",
        f"- Shadow-review candidates: `{summary['shadow_review_candidate_count']}`",
        f"- First-ledger ready rows: `{summary['first_ledger_ready_count']}`",
        f"- Waiting for fresh refresh: `{summary['waiting_for_fresh_refresh_count']}`",
        f"- Evidence failed: `{summary['evidence_failed_count']}`",
        f"- Parameter mutation allowed: `{summary['parameter_mutation_allowed_count']}`",
        "- Boundary: read-only gate; no parameter mutation, no registry/account-spec/broker-readiness mutation, no broker/live, no manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Gate Rows",
        "",
    ]
    for row in payload["gate_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} / {row['experiment_family']}",
                "",
                f"- Gate state: `{row['gate_state']}`",
                f"- Outcome: `{row['matched_outcome_status']}`",
                f"- Shadow-review candidate: `{row['shadow_review_candidate']}`",
                f"- Parameter mutation allowed: `{row['parameter_mutation_allowed']}`",
                f"- Reason: {row['gate_reason']}",
                f"- Next action: {row['next_action']}",
                "",
            ]
        )
    return "\n".join(lines)


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def slug(value: str) -> str:
    chars: list[str] = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    return "-".join(part for part in "".join(chars).split("-") if part)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
