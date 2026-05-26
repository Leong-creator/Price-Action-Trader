#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_parameter_experiment_queue.json"


@dataclass(frozen=True, slots=True)
class RescueParameterExperimentQueueConfig:
    stage: str
    rescue_optimization_backlog_path: Path
    rescue_zero_signal_diagnostics_path: Path
    rescue_next_refresh_readiness_path: Path
    rescue_target_stop_diagnostics_path: Path
    rescue_external_reference_map_path: Path
    project_stage_assessment_path: Path
    experiment_queue_json_path: Path
    experiment_queue_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescueParameterExperimentQueueConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescueParameterExperimentQueueConfig(
        stage=str(payload["stage"]),
        rescue_optimization_backlog_path=resolve_repo_path(inputs["m14_rescue_optimization_backlog"]),
        rescue_zero_signal_diagnostics_path=resolve_repo_path(inputs["m14_rescue_zero_signal_diagnostics"]),
        rescue_next_refresh_readiness_path=resolve_repo_path(inputs["m14_rescue_next_refresh_readiness"]),
        rescue_target_stop_diagnostics_path=resolve_repo_path(inputs["m14_rescue_target_stop_diagnostics"]),
        rescue_external_reference_map_path=resolve_repo_path(inputs["m14_rescue_external_reference_map"]),
        project_stage_assessment_path=resolve_repo_path(inputs["m14_project_stage_assessment"]),
        experiment_queue_json_path=resolve_repo_path(outputs["experiment_queue_json"]),
        experiment_queue_md_path=resolve_repo_path(outputs["experiment_queue_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescueParameterExperimentQueueConfig) -> None:
    if config.stage != "M14.rescue_parameter_experiment_queue":
        raise ValueError("M14 rescue parameter experiment queue stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue parameter experiment queue must stay paper/simulated only")
    forbidden = (
        "broker_connection",
        "real_order",
        "live_execution",
        "paper_trading_approval",
        "manual_m12_37_once",
        "m13_registry_mutation",
        "m12_account_specs_mutation",
        "broker_readiness_status_mutation",
    )
    for key in forbidden:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue parameter experiment queue cannot enable {key}")


def run_m14_rescue_parameter_experiment_queue(
    config: RescueParameterExperimentQueueConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    backlog = read_json(config.rescue_optimization_backlog_path)
    zero_signal = read_json(config.rescue_zero_signal_diagnostics_path)
    next_refresh = read_json(config.rescue_next_refresh_readiness_path)
    target_stop = read_json(config.rescue_target_stop_diagnostics_path)
    external_map = read_json(config.rescue_external_reference_map_path)
    project_stage = read_json(config.project_stage_assessment_path)

    zero_rows_by_strategy = group_rows_by_strategy(list(zero_signal.get("rows", [])))
    next_rows_by_strategy = group_rows_by_strategy(list(next_refresh.get("rows", [])))
    target_stop_by_strategy = {str(row.get("strategy_id", "")): dict(row) for row in target_stop.get("rows", [])}
    external_rescue_by_strategy = {
        str(row.get("strategy_id", "")): dict(row) for row in external_map.get("rescue_reference_rows", [])
    }
    external_broker_by_strategy = {
        str(row.get("strategy_id", "")): dict(row) for row in external_map.get("broker_blocker_reference_rows", [])
    }

    rescue_rows = [
        build_rescue_experiment_row(
            backlog_row=dict(row),
            zero_diag_rows=zero_rows_by_strategy.get(str(row.get("strategy_id", "")), []),
            next_watch_rows=next_rows_by_strategy.get(str(row.get("strategy_id", "")), []),
            target_stop_diag=target_stop_by_strategy.get(str(row.get("strategy_id", "")), {}),
            external_row=external_rescue_by_strategy.get(str(row.get("strategy_id", "")), {}),
        )
        for row in backlog.get("rescue_rows", [])
    ]
    broker_rows = [
        broker_experiment
        for row in backlog.get("broker_dry_run_blockers", [])
        for broker_experiment in build_broker_blocker_experiment_rows(
            blocker_row=dict(row),
            external_row=external_broker_by_strategy.get(str(row.get("strategy_id", "")), {}),
        )
    ]
    experiment_rows = sorted(
        rescue_rows + broker_rows,
        key=lambda row: (row["priority"], row["strategy_id"], row["experiment_family"], row["experiment_row_id"]),
    )

    status_counts = Counter(row["status"] for row in experiment_rows)
    family_counts = Counter(row["experiment_family"] for row in experiment_rows)
    project_summary = project_stage.get("summary", {})
    next_summary = next_refresh.get("summary", {})
    summary = {
        "project_stage": str(project_summary.get("current_project_stage", "")),
        "fresh_refresh_observed": bool(project_summary.get("post_refresh_fresh_refresh_observed", False)),
        "source_quote": str(project_summary.get("post_refresh_source_quote", "")),
        "source_rescue_row_count": len(backlog.get("rescue_rows", [])),
        "rescue_experiment_row_count": len(rescue_rows),
        "broker_blocker_experiment_count": len(broker_rows),
        "experiment_row_count": len(experiment_rows),
        "allowed_now_count": sum(1 for row in experiment_rows if row["allowed_now"]),
        "parameter_change_allowed_now_count": 0,
        "source_parameter_change_allowed_now_count": int_or_zero(
            next_summary.get("parameter_change_allowed_now_count")
        ),
        "blocked_until_fresh_refresh_count": status_counts.get("blocked_until_fresh_refresh", 0),
        "shadow_runtime_wait_first_ledger_count": status_counts.get("shadow_runtime_wait_first_ledger", 0),
        "collect_more_ab_evidence_count": status_counts.get("collect_more_ab_evidence", 0),
        "blocked_until_parent_detector_evidence_count": status_counts.get(
            "blocked_until_parent_detector_evidence", 0
        ),
        "review_only_count": status_counts.get("review_only", 0),
        "target_stop_experiment_count": family_counts.get("target_stop_reward_geometry_shadow", 0),
        "broker_or_live_enabled": False,
        "copy_trading_allowed": False,
        "external_override_allowed": False,
        "manual_m12_37_once_allowed": False,
        "m13_registry_mutation_count": 0,
        "m12_account_specs_mutation_count": 0,
        "broker_readiness_status_mutation_count": 0,
        "status_counts": dict(sorted(status_counts.items())),
        "experiment_family_counts": dict(sorted(family_counts.items())),
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.rescue-parameter-experiment-queue.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_rescue_optimization_backlog": project_path(config.rescue_optimization_backlog_path),
            "m14_rescue_zero_signal_diagnostics": project_path(config.rescue_zero_signal_diagnostics_path),
            "m14_rescue_next_refresh_readiness": project_path(config.rescue_next_refresh_readiness_path),
            "m14_rescue_target_stop_diagnostics": project_path(config.rescue_target_stop_diagnostics_path),
            "m14_rescue_external_reference_map": project_path(config.rescue_external_reference_map_path),
            "m14_project_stage_assessment": project_path(config.project_stage_assessment_path),
        },
        "summary": summary,
        "experiment_rows": experiment_rows,
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
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.experiment_queue_json_path, payload)
    config.experiment_queue_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.experiment_queue_md_path.write_text(build_experiment_queue_md(payload), encoding="utf-8")
    return payload


def group_rows_by_strategy(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strategy_id = str(row.get("strategy_id", ""))
        if strategy_id:
            grouped[strategy_id].append(row)
    return grouped


def build_rescue_experiment_row(
    *,
    backlog_row: dict[str, Any],
    zero_diag_rows: list[dict[str, Any]],
    next_watch_rows: list[dict[str, Any]],
    target_stop_diag: dict[str, Any],
    external_row: dict[str, Any],
) -> dict[str, Any]:
    strategy_id = str(backlog_row.get("strategy_id", ""))
    issue_type = str(backlog_row.get("issue_type", ""))
    readiness_families = sorted(
        {str(row.get("readiness_family", "")) for row in next_watch_rows if row.get("readiness_family")}
    )
    zero_diag = select_zero_diagnostic_row(
        zero_diag_rows=zero_diag_rows,
        readiness_families=readiness_families,
        has_target_stop_diag=bool(target_stop_diag),
    )
    dominant_issue = str(zero_diag.get("dominant_issue", ""))
    experiment = classify_rescue_experiment(
        issue_type=issue_type,
        dominant_issue=dominant_issue,
        readiness_families=readiness_families,
        has_target_stop_diag=bool(target_stop_diag),
        strategy_id=strategy_id,
    )
    return {
        "experiment_row_id": f"m14-param-exp-{slug(strategy_id)}",
        "source_kind": "rescue_optimization_backlog",
        "strategy_id": strategy_id,
        "parent_strategy_id": str(backlog_row.get("parent_strategy_id", "")),
        "runtime_ids": list(backlog_row.get("runtime_ids", [])),
        "priority": str(backlog_row.get("priority", "")),
        "issue_type": issue_type,
        "dominant_issue": dominant_issue,
        "readiness_families": readiness_families,
        "experiment_family": experiment["experiment_family"],
        "candidate_parameter_family": experiment["candidate_parameter_family"],
        "candidate_change_scope": experiment["candidate_change_scope"],
        "status": experiment["status"],
        "allowed_now": False,
        "parameter_change_allowed_now": False,
        "activation_condition": experiment["activation_condition"],
        "required_evidence": experiment["required_evidence"],
        "external_review_lanes": list(external_row.get("local_review_lanes", [])),
        "source_metrics": {
            "observed_trading_days_count": int_or_zero(backlog_row.get("observed_trading_days_count")),
            "remaining_ab_trading_days": int_or_zero(backlog_row.get("remaining_ab_trading_days")),
            "source_row_count": int_or_zero(backlog_row.get("source_row_count")),
            "signal_count": int_or_zero(backlog_row.get("signal_count")),
            "open_count": int_or_zero(backlog_row.get("open_count")),
            "risk_blocked_count": int_or_zero(backlog_row.get("risk_blocked_count")),
            "eligible_if_fresh_quote_count": int_or_zero(zero_diag.get("eligible_if_fresh_quote_count")),
            "target_stop_issue": str(target_stop_diag.get("dominant_target_stop_issue", "")),
            "reward_r_min": str(target_stop_diag.get("reward_r_min", "")),
            "reward_r_max": str(target_stop_diag.get("reward_r_max", "")),
        },
        "promotion_gate": "10 rescue A/B trading days plus manual M14 review",
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
    }


def select_zero_diagnostic_row(
    *,
    zero_diag_rows: list[dict[str, Any]],
    readiness_families: list[str],
    has_target_stop_diag: bool,
) -> dict[str, Any]:
    if not zero_diag_rows:
        return {}
    issue_priority: list[str] = []
    if has_target_stop_diag or "target_stop_shadow_compare" in readiness_families:
        issue_priority.append("reward_filter_blocks_all")
    if "parent_detector_evidence_wait" in readiness_families:
        issue_priority.append("parent_detector_zero_signal_for_timeframe")
    issue_priority.extend(
        [
            "parent_detector_zero_signal_for_timeframe",
            "reward_filter_blocks_all",
            "strict_quality_filter_blocks_all",
            "stale_quote_source_blocks_candidate",
        ]
    )
    for issue in issue_priority:
        for row in zero_diag_rows:
            if str(row.get("dominant_issue", "")) == issue:
                return dict(row)
    return dict(zero_diag_rows[0])


def classify_rescue_experiment(
    *,
    issue_type: str,
    dominant_issue: str,
    readiness_families: list[str],
    has_target_stop_diag: bool,
    strategy_id: str,
) -> dict[str, Any]:
    if issue_type == "missing_rescue_ledger":
        return experiment_def(
            experiment_family="ledger_path_mapping_audit",
            candidate_parameter_family="registry_input_signal_account_ledger_mapping",
            candidate_change_scope="registry_to_signal_to_account_ledger",
            status="shadow_runtime_wait_first_ledger",
            activation_condition="First M13 signal/account ledger row appears after a M12.47-owned fresh refresh.",
            required_evidence=[
                "M12.47-owned fresh refresh, not manual M12.37 once-mode.",
                "First rescue-specific M13 signal or account ledger row.",
                "Then a full 10 rescue A/B trading-day evidence window before promote/modify/reject.",
            ],
        )
    if issue_type == "zero_signal_after_connection" and dominant_issue == "stale_quote_source_blocks_candidate":
        return experiment_def(
            experiment_family="fresh_quote_gate_recheck",
            candidate_parameter_family="quote_source_freshness_gate",
            candidate_change_scope="source_quote_and_signal_count",
            status="blocked_until_fresh_refresh",
            activation_condition="Next M12.47-owned fresh Longbridge quote refresh clears fallback/stale source rows.",
            required_evidence=[
                "Fresh quote source without fallback-only state.",
                "Source-row and signal-count comparison before any detector or threshold change.",
                "10 rescue A/B trading days if a later parameter variant is created.",
            ],
        )
    if issue_type == "zero_signal_after_connection" and (
        dominant_issue == "reward_filter_blocks_all" or has_target_stop_diag
    ):
        return experiment_def(
            experiment_family="target_stop_reward_geometry_shadow",
            candidate_parameter_family="target_stop_geometry_normalization_not_lowering_frozen_min_r",
            candidate_change_scope="target_stop_normalization_reward_r",
            status="blocked_until_fresh_refresh",
            activation_condition=(
                "Fresh refresh provides comparable ledger evidence for the frozen runtime and normalized target/stop shadow."
            ),
            required_evidence=[
                "Frozen rescue runtime remains unchanged.",
                "Normalized target/stop shadow runtime emits its own M13 ledger evidence.",
                "10 rescue A/B trading days before any min-R or target/stop policy decision.",
            ],
        )
    if issue_type == "zero_signal_after_connection" and dominant_issue == "parent_detector_zero_signal_for_timeframe":
        return experiment_def(
            experiment_family="parent_detector_timeframe_mapping_review",
            candidate_parameter_family="same_timeframe_parent_detector_mapping",
            candidate_change_scope="same_timeframe_parent_detector",
            status="blocked_until_parent_detector_evidence",
            activation_condition="Parent detector produces same-timeframe source rows in a fresh run.",
            required_evidence=[
                "Same-timeframe parent detector evidence.",
                "No cross-timeframe remap without a separate detector redesign review.",
                "10 rescue A/B trading days after a mapped variant exists.",
            ],
        )
    if issue_type == "collect_more_ab_evidence":
        return experiment_def(
            experiment_family="continue_ab_evidence_collection",
            candidate_parameter_family="none_ab_evidence_only",
            candidate_change_scope="no_parameter_change",
            status="collect_more_ab_evidence",
            activation_condition="Current rescue runtime keeps collecting its own 10-day A/B evidence.",
            required_evidence=[
                "Comparable baseline-vs-rescue ledger rows.",
                "Full 10 rescue A/B trading-day window.",
                "Manual M14 review before promote/modify/reject.",
            ],
        )
    if issue_type == "signal_generated_no_account_operation":
        return experiment_def(
            experiment_family="signal_to_account_bridge_audit",
            candidate_parameter_family="signal_account_bridge_mapping",
            candidate_change_scope="signal_to_account_operation_path",
            status="review_only",
            activation_condition="Signal ledger exists but account operation remains absent after the next refresh.",
            required_evidence=[
                "Signal-to-account bridge trace.",
                "M13 account ledger proof or explicit no-op reason.",
                "No parameter change before bridge path is explained.",
            ],
        )
    return experiment_def(
        experiment_family="manual_review_only",
        candidate_parameter_family=f"manual_review_for_{slug(strategy_id)}",
        candidate_change_scope="review_only",
        status="review_only",
        activation_condition="Manual M14 review determines whether this row needs a later shadow experiment.",
        required_evidence=[
            "10 rescue A/B trading-day evidence or explicit blocker evidence.",
            "Manual review before state change.",
        ],
    )


def experiment_def(
    *,
    experiment_family: str,
    candidate_parameter_family: str,
    candidate_change_scope: str,
    status: str,
    activation_condition: str,
    required_evidence: list[str],
) -> dict[str, Any]:
    return {
        "experiment_family": experiment_family,
        "candidate_parameter_family": candidate_parameter_family,
        "candidate_change_scope": candidate_change_scope,
        "status": status,
        "activation_condition": activation_condition,
        "required_evidence": required_evidence,
    }


def build_broker_blocker_experiment_rows(
    *,
    blocker_row: dict[str, Any],
    external_row: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    strategy_id = str(blocker_row.get("strategy_id", ""))
    reason_counts = dict(blocker_row.get("reason_counts", {}))
    for reason in sorted(reason_counts):
        experiment = classify_broker_blocker_experiment(reason)
        rows.append(
            {
                "experiment_row_id": f"m14-param-exp-broker-{slug(strategy_id)}-{slug(reason)}",
                "source_kind": "broker_dry_run_blocker",
                "strategy_id": strategy_id,
                "parent_strategy_id": strategy_id,
                "runtime_ids": [],
                "priority": str(blocker_row.get("priority", "")),
                "issue_type": "broker_dry_run_blocker",
                "dominant_issue": reason,
                "readiness_families": ["broker_rule_shadow_recheck"],
                "experiment_family": experiment["experiment_family"],
                "candidate_parameter_family": experiment["candidate_parameter_family"],
                "candidate_change_scope": experiment["candidate_change_scope"],
                "status": "blocked_until_fresh_refresh",
                "allowed_now": False,
                "parameter_change_allowed_now": False,
                "activation_condition": experiment["activation_condition"],
                "required_evidence": experiment["required_evidence"],
                "external_review_lanes": list(external_row.get("local_review_lanes", [])),
                "source_metrics": {
                    "blocked_count": int_or_zero(reason_counts.get(reason)),
                    "reason_counts": reason_counts,
                    "symbols": list(blocker_row.get("symbols", [])),
                    "source_signal_ids": list(blocker_row.get("source_signal_ids", [])),
                },
                "promotion_gate": "Internal-sim dry-run blocker improvement plus manual M14 review; broker readiness stays blocked.",
                "paper_simulated_only": True,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
                "manual_m12_37_once": False,
                "m13_registry_mutation": False,
                "m12_account_specs_mutation": False,
                "broker_readiness_status_mutation": False,
            }
        )
    return rows


def classify_broker_blocker_experiment(reason: str) -> dict[str, Any]:
    if reason == "max_risk_per_order_exceeded":
        return experiment_def(
            experiment_family="quantity_cap_shadow",
            candidate_parameter_family="position_size_quantity_cap",
            candidate_change_scope="position_sizing_risk_cap",
            status="blocked_until_fresh_refresh",
            activation_condition="Internal-sim dry-run shows risk <= 100 after sizing cap without unblocking broker readiness.",
            required_evidence=[
                "Same signal with capped quantity in internal simulation.",
                "Risk amount at or below 100.",
                "Original broker readiness row remains blocked until explicit approval.",
            ],
        )
    if reason == "max_total_exposure_exceeded":
        return experiment_def(
            experiment_family="exposure_ranker_shadow",
            candidate_parameter_family="portfolio_exposure_ranker",
            candidate_change_scope="portfolio_exposure_ordering",
            status="blocked_until_fresh_refresh",
            activation_condition="Internal-sim dry-run proves exposure ordering or deferral reduces total exposure blockers.",
            required_evidence=[
                "Exposure-ranked comparison row in internal simulation.",
                "No skipped risk gate or forced readiness unblock.",
                "Decision log explaining kept, deferred, or rejected entries.",
            ],
        )
    if reason == "consecutive_losses_limit":
        return experiment_def(
            experiment_family="cooldown_quality_veto_shadow",
            candidate_parameter_family="cooldown_quality_veto",
            candidate_change_scope="cooldown_quality_veto",
            status="blocked_until_fresh_refresh",
            activation_condition="Internal-sim dry-run preserves loss-streak halt and shows later entries would pass a stricter quality veto.",
            required_evidence=[
                "Cooldown state remains active where required.",
                "Quality-veto comparison for later same-session entries.",
                "No override of consecutive-loss protection.",
            ],
        )
    return experiment_def(
        experiment_family="broker_blocker_manual_review",
        candidate_parameter_family="manual_broker_blocker_review",
        candidate_change_scope="broker_dry_run_reason_review",
        status="blocked_until_fresh_refresh",
        activation_condition="Next internal-sim dry-run rechecks this blocker reason.",
        required_evidence=[
            "Reason-code comparison before and after the refresh.",
            "Broker readiness row remains blocked unless separately approved.",
        ],
    )


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Parameter experiment queue prepared {summary['experiment_row_count']} rows: "
        f"{summary['rescue_experiment_row_count']} rescue rows and "
        f"{summary['broker_blocker_experiment_count']} broker-blocker rows. "
        f"Allowed-now changes remain {summary['allowed_now_count']}; "
        f"{summary['blocked_until_fresh_refresh_count']} rows wait for the next M12.47-owned fresh refresh and "
        f"{summary['shadow_runtime_wait_first_ledger_count']} rows wait for first M13 ledger evidence. "
        "The queue only defines shadow/review families; it does not mutate M13 registry, M12 account specs, broker readiness, "
        "broker connection, paper approval, live execution, real orders, or manual M12.37 once-mode."
    )


def build_experiment_queue_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Rescue Parameter Experiment Queue",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Project stage: `{summary['project_stage']}`",
        f"- Fresh refresh observed: `{summary['fresh_refresh_observed']}`",
        f"- Quote source: `{summary['source_quote']}`",
        f"- Experiment rows: `{summary['experiment_row_count']}`",
        f"- Rescue/broker rows: `{summary['rescue_experiment_row_count']}/{summary['broker_blocker_experiment_count']}`",
        f"- Allowed now: `{summary['allowed_now_count']}`",
        f"- Blocked until fresh refresh: `{summary['blocked_until_fresh_refresh_count']}`",
        f"- Shadow runtime wait first ledger: `{summary['shadow_runtime_wait_first_ledger_count']}`",
        f"- Target/stop experiment rows: `{summary['target_stop_experiment_count']}`",
        "- Boundary: queue only; no parameter mutation, no registry/account-spec/broker-readiness mutation, no broker/live, no manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Experiment Rows",
        "",
    ]
    for row in payload["experiment_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} / {row['experiment_family']}",
                "",
                f"- Priority: `{row['priority']}`",
                f"- Issue: `{row['issue_type']}` / `{row['dominant_issue']}`",
                f"- Status: `{row['status']}`",
                f"- Allowed now: `{row['allowed_now']}`",
                f"- Candidate parameter family: `{row['candidate_parameter_family']}`",
                f"- Change scope: `{row['candidate_change_scope']}`",
                f"- Activation condition: {row['activation_condition']}",
                f"- Required evidence: {'; '.join(row['required_evidence'])}",
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
