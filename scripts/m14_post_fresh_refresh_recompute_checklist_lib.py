#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_post_fresh_refresh_recompute_checklist.json"
FORBIDDEN_OPERATIONS = (
    "manual_m12_37_once",
    "broker_connection",
    "real_order",
    "live_execution",
    "paper_trading_approval",
    "m13_registry_mutation",
    "m12_account_specs_mutation",
    "broker_readiness_status_mutation",
    "parameter_mutation",
)


@dataclass(frozen=True, slots=True)
class PostFreshRefreshRecomputeChecklistConfig:
    stage: str
    project_stage_label: str
    internal_sim_next_session_plan_path: Path
    rescue_post_refresh_outcome_review_path: Path
    rescue_ab_evidence_tracker_path: Path
    rescue_next_refresh_readiness_path: Path
    rescue_parameter_experiment_queue_path: Path
    rescue_parameter_activation_gate_path: Path
    rescue_parameter_shadow_spec_path: Path
    strategy_decision_ladder_path: Path
    strategy_pre_refresh_review_audit_path: Path
    objective_completion_audit_path: Path
    objective_execution_plan_path: Path
    checklist_json_path: Path
    checklist_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> PostFreshRefreshRecomputeChecklistConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = PostFreshRefreshRecomputeChecklistConfig(
        stage=str(payload["stage"]),
        project_stage_label=str(payload["project_stage_label"]),
        internal_sim_next_session_plan_path=resolve_repo_path(inputs["m14_internal_sim_next_session_plan"]),
        rescue_post_refresh_outcome_review_path=resolve_repo_path(
            inputs["m14_rescue_post_refresh_outcome_review"]
        ),
        rescue_ab_evidence_tracker_path=resolve_repo_path(inputs["m14_rescue_ab_evidence_tracker"]),
        rescue_next_refresh_readiness_path=resolve_repo_path(inputs["m14_rescue_next_refresh_readiness"]),
        rescue_parameter_experiment_queue_path=resolve_repo_path(
            inputs["m14_rescue_parameter_experiment_queue"]
        ),
        rescue_parameter_activation_gate_path=resolve_repo_path(
            inputs["m14_rescue_parameter_activation_gate"]
        ),
        rescue_parameter_shadow_spec_path=resolve_repo_path(inputs["m14_rescue_parameter_shadow_spec"]),
        strategy_decision_ladder_path=resolve_repo_path(inputs["m14_strategy_decision_ladder"]),
        strategy_pre_refresh_review_audit_path=resolve_repo_path(
            inputs["m14_strategy_pre_refresh_review_audit"]
        ),
        objective_completion_audit_path=resolve_repo_path(inputs["m14_objective_completion_audit"]),
        objective_execution_plan_path=resolve_repo_path(inputs["m14_objective_execution_plan"]),
        checklist_json_path=resolve_repo_path(outputs["checklist_json"]),
        checklist_md_path=resolve_repo_path(outputs["checklist_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: PostFreshRefreshRecomputeChecklistConfig) -> None:
    if config.stage != "M14.post_fresh_refresh_recompute_checklist":
        raise ValueError("M14 post-fresh-refresh recompute checklist stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 post-fresh-refresh recompute checklist must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 post-fresh-refresh recompute checklist must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 post-fresh-refresh recompute checklist cannot enable {key}")


def run_m14_post_fresh_refresh_recompute_checklist(
    config: PostFreshRefreshRecomputeChecklistConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    next_session = read_json(config.internal_sim_next_session_plan_path)
    post_refresh = read_json(config.rescue_post_refresh_outcome_review_path)
    rescue_ab = read_json(config.rescue_ab_evidence_tracker_path)
    next_refresh = read_json(config.rescue_next_refresh_readiness_path)
    parameter_queue = read_json(config.rescue_parameter_experiment_queue_path)
    activation_gate = read_json(config.rescue_parameter_activation_gate_path)
    shadow_spec = read_json(config.rescue_parameter_shadow_spec_path)
    decision_ladder = read_json(config.strategy_decision_ladder_path)
    pre_refresh_audit = read_json(config.strategy_pre_refresh_review_audit_path)
    objective_audit = read_json(config.objective_completion_audit_path)
    objective_execution = read_json(config.objective_execution_plan_path)

    source_summary = build_source_summary(
        next_session=next_session,
        post_refresh=post_refresh,
        rescue_ab=rescue_ab,
        next_refresh=next_refresh,
        parameter_queue=parameter_queue,
        activation_gate=activation_gate,
        shadow_spec=shadow_spec,
        decision_ladder=decision_ladder,
        pre_refresh_audit=pre_refresh_audit,
        objective_audit=objective_audit,
        objective_execution=objective_execution,
    )
    preconditions = build_preconditions(source_summary)
    recompute_steps = build_recompute_steps(source_summary)
    acceptance_gates = build_acceptance_gates(source_summary)
    phase_counts = dict(sorted(Counter(step["phase"] for step in recompute_steps).items()))
    summary = {
        **source_summary,
        "precondition_count": len(preconditions),
        "recompute_step_count": len(recompute_steps),
        "m14_script_step_count": sum(1 for step in recompute_steps if step["step_type"] == "read_only_script"),
        "acceptance_gate_count": len(acceptance_gates),
        "phase_counts": phase_counts,
        "requires_m12_47_fresh_refresh_step_count": sum(
            1 for step in recompute_steps if step["requires_m12_47_fresh_refresh"]
        ),
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "parameter_mutation_allowed_count": 0,
        "m13_registry_mutation_count": 0,
        "m12_account_specs_mutation_count": 0,
        "broker_readiness_status_mutation_count": 0,
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.post-fresh-refresh-recompute-checklist.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "project_stage_label": config.project_stage_label,
        "m14_trading_date": summary["m14_trading_date"],
        "input_refs": {
            "m14_internal_sim_next_session_plan": project_path(config.internal_sim_next_session_plan_path),
            "m14_rescue_post_refresh_outcome_review": project_path(
                config.rescue_post_refresh_outcome_review_path
            ),
            "m14_rescue_ab_evidence_tracker": project_path(config.rescue_ab_evidence_tracker_path),
            "m14_rescue_next_refresh_readiness": project_path(config.rescue_next_refresh_readiness_path),
            "m14_rescue_parameter_experiment_queue": project_path(
                config.rescue_parameter_experiment_queue_path
            ),
            "m14_rescue_parameter_activation_gate": project_path(
                config.rescue_parameter_activation_gate_path
            ),
            "m14_rescue_parameter_shadow_spec": project_path(config.rescue_parameter_shadow_spec_path),
            "m14_strategy_decision_ladder": project_path(config.strategy_decision_ladder_path),
            "m14_strategy_pre_refresh_review_audit": project_path(
                config.strategy_pre_refresh_review_audit_path
            ),
            "m14_objective_completion_audit": project_path(config.objective_completion_audit_path),
            "m14_objective_execution_plan": project_path(config.objective_execution_plan_path),
        },
        "summary": summary,
        "preconditions": preconditions,
        "recompute_steps": recompute_steps,
        "acceptance_gates": acceptance_gates,
        "hard_boundaries": {
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
        },
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
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.checklist_json_path, payload)
    config.checklist_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.checklist_md_path.write_text(build_checklist_md(payload), encoding="utf-8")
    return payload


def build_source_summary(
    *,
    next_session: dict[str, Any],
    post_refresh: dict[str, Any],
    rescue_ab: dict[str, Any],
    next_refresh: dict[str, Any],
    parameter_queue: dict[str, Any],
    activation_gate: dict[str, Any],
    shadow_spec: dict[str, Any],
    decision_ladder: dict[str, Any],
    pre_refresh_audit: dict[str, Any],
    objective_audit: dict[str, Any],
    objective_execution: dict[str, Any],
) -> dict[str, Any]:
    next_summary = next_session.get("summary", {})
    post_summary = post_refresh.get("summary", {})
    rescue_summary = rescue_ab.get("summary", {})
    next_refresh_summary = next_refresh.get("summary", {})
    parameter_summary = parameter_queue.get("summary", {})
    activation_summary = activation_gate.get("summary", {})
    shadow_summary = shadow_spec.get("summary", {})
    decision_summary = decision_ladder.get("summary", {})
    pre_refresh_audit_summary = pre_refresh_audit.get("summary", {})
    objective_summary = objective_audit.get("summary", {})
    execution_summary = objective_execution.get("summary", {})
    return {
        "m14_trading_date": str(
            next_session.get("m14_trading_date")
            or decision_summary.get("m14_trading_date")
            or objective_audit.get("m14_trading_date", "")
        ),
        "can_run_next_internal_sim_session": bool(next_summary.get("can_run_next_internal_sim_session", False)),
        "next_session_mode": str(next_summary.get("next_session_mode", "")),
        "approved_runtime_input_connected_count": int_or_zero(
            next_summary.get("approved_runtime_input_connected_count")
        ),
        "approved_runtime_input_count": int_or_zero(next_summary.get("approved_runtime_input_count")),
        "fresh_refresh_observed": bool(post_summary.get("fresh_refresh_observed", False)),
        "source_quote": str(post_summary.get("source_quote", "")),
        "post_refresh_waiting_count": int_or_zero(post_summary.get("waiting_count")),
        "post_refresh_passed_count": int_or_zero(post_summary.get("passed_count")),
        "post_refresh_failed_count": int_or_zero(post_summary.get("failed_count")),
        "rescue_runtime_strategy_count": int_or_zero(rescue_summary.get("rescue_runtime_strategy_count")),
        "rescue_m13_ledger_observed_strategy_count": int_or_zero(
            rescue_summary.get("m13_ledger_observed_strategy_count")
        ),
        "rescue_no_m13_ledger_evidence_count": int_or_zero(
            rescue_summary.get("no_m13_ledger_evidence_count")
        ),
        "rescue_promotion_allowed_count": int_or_zero(rescue_summary.get("promotion_allowed_count")),
        "next_refresh_watch_rows": int_or_zero(
            next_refresh_summary.get("watch_row_count", next_refresh_summary.get("watch_rows"))
        ),
        "next_refresh_parameter_change_allowed_now_count": int_or_zero(
            next_refresh_summary.get("parameter_change_allowed_now_count")
        ),
        "parameter_experiment_row_count": int_or_zero(parameter_summary.get("experiment_row_count")),
        "parameter_activation_gate_row_count": int_or_zero(activation_summary.get("gate_row_count")),
        "parameter_activation_waiting_for_fresh_refresh_count": int_or_zero(
            activation_summary.get("waiting_for_fresh_refresh_count")
        ),
        "parameter_activation_shadow_review_candidate_count": int_or_zero(
            activation_summary.get("shadow_review_candidate_count")
        ),
        "parameter_shadow_spec_row_count": int_or_zero(shadow_summary.get("spec_row_count")),
        "parameter_shadow_spec_candidate_variant_count": int_or_zero(
            shadow_summary.get("candidate_variant_count")
        ),
        "strategy_decision_ladder_row_count": int_or_zero(decision_summary.get("strategy_ladder_row_count")),
        "strategy_decision_final_discard_allowed_count": int_or_zero(
            decision_summary.get("final_discard_allowed_count")
        ),
        "strategy_decision_promotion_candidate_count": int_or_zero(
            decision_summary.get("promotion_candidate_count")
        ),
        "strategy_pre_refresh_review_audit_row_count": int_or_zero(
            pre_refresh_audit_summary.get("audit_row_count")
        ),
        "strategy_pre_refresh_review_audit_ready_now_count": int_or_zero(
            pre_refresh_audit_summary.get("ready_for_artifact_review_now_count")
        ),
        "strategy_pre_refresh_review_audit_wait_fresh_count": int_or_zero(
            pre_refresh_audit_summary.get("pre_review_ready_wait_fresh_evidence_count")
        ),
        "strategy_pre_refresh_review_audit_backfill_count": int_or_zero(
            pre_refresh_audit_summary.get("needs_supporting_artifact_backfill_count")
        ),
        "objective_complete": bool(objective_summary.get("objective_complete", False)),
        "objective_blocked_count": int_or_zero(objective_summary.get("blocked_count")),
        "objective_in_progress_count": int_or_zero(objective_summary.get("in_progress_count")),
        "objective_execution_action_count": int_or_zero(execution_summary.get("execution_action_count")),
        "objective_execution_waiting_for_fresh_refresh_action_count": int_or_zero(
            execution_summary.get("waiting_for_fresh_refresh_action_count")
        ),
        "parameter_mutation_allowed_count": 0,
        "two_pass_stabilization_required": True,
    }


def build_preconditions(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "precondition_id": "m12_47_supervisor_owned_refresh",
            "state": "observed" if summary["fresh_refresh_observed"] else "waiting",
            "evidence": (
                f"fresh_refresh_observed={summary['fresh_refresh_observed']}; "
                f"quote_source={summary['source_quote']}."
            ),
            "required_before": "post_refresh_evidence_recompute",
            "manual_m12_37_once_allowed": False,
        },
        {
            "precondition_id": "approved_runtime_inputs_connected",
            "state": "ready"
            if summary["approved_runtime_input_connected_count"] == summary["approved_runtime_input_count"]
            else "blocked",
            "evidence": (
                f"approved runtimes connected "
                f"{summary['approved_runtime_input_connected_count']}/{summary['approved_runtime_input_count']}."
            ),
            "required_before": "approved_internal_sim_acceptance",
            "manual_m12_37_once_allowed": False,
        },
        {
            "precondition_id": "guardrails_intact",
            "state": "ready",
            "evidence": "broker/live, real orders, paper approval, parameter mutation, registry/account-spec mutation, and manual M12.37 once-mode remain disabled.",
            "required_before": "all_recompute_steps",
            "manual_m12_37_once_allowed": False,
        },
    ]


def build_recompute_steps(summary: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = [
        (
            "wait_for_m12_47_supervisor_refresh",
            "supervisor_refresh",
            "wait",
            "",
            "M12.47 supervisor owns the next trading-window refresh and may launch M12.37; do not run once-mode manually.",
        ),
        (
            "review_post_refresh_outcomes",
            "evidence_recompute",
            "read_only_script",
            "python scripts/run_m14_rescue_post_refresh_outcome_review.py",
            "Classify the 13 next-refresh watch rows against fresh M12/M13 evidence.",
        ),
        (
            "refresh_rescue_ab_evidence",
            "evidence_recompute",
            "read_only_script",
            "python scripts/run_m14_rescue_ab_evidence_tracker.py",
            "Update rescue ledger observed/no-ledger counts from refreshed M13 ledgers.",
        ),
        (
            "refresh_rescue_optimization_backlog",
            "rescue_diagnostics",
            "read_only_script",
            "python scripts/run_m14_rescue_optimization_backlog.py",
            "Re-rank rescue blockers after refreshed ledger evidence.",
        ),
        (
            "refresh_zero_signal_diagnostics",
            "rescue_diagnostics",
            "read_only_script",
            "python scripts/run_m14_rescue_zero_signal_diagnostics.py",
            "Separate fresh-quote misses from detector/parameter issues.",
        ),
        (
            "refresh_target_stop_diagnostics",
            "rescue_diagnostics",
            "read_only_script",
            "python scripts/run_m14_rescue_target_stop_diagnostics.py",
            "Recheck target/stop reward geometry after fresh source rows.",
        ),
        (
            "refresh_target_stop_shadow_normalization",
            "rescue_diagnostics",
            "read_only_script",
            "python scripts/run_m14_rescue_target_stop_shadow_normalization.py",
            "Rebuild shadow-only PA012 target normalization candidates if source rows changed.",
        ),
        (
            "refresh_next_refresh_readiness",
            "readiness_recompute",
            "read_only_script",
            "python scripts/run_m14_rescue_next_refresh_readiness.py",
            "Recompute watch rows for any remaining post-refresh blockers.",
        ),
        (
            "refresh_parameter_experiment_queue",
            "parameter_recompute",
            "read_only_script",
            "python scripts/run_m14_rescue_parameter_experiment_queue.py",
            "Refresh parameter experiment families without mutating runtime specs.",
        ),
        (
            "refresh_parameter_activation_gate",
            "parameter_recompute",
            "read_only_script",
            "python scripts/run_m14_rescue_parameter_activation_gate.py",
            "Promote only passed evidence into manual shadow-review candidates; keep mutations disabled.",
        ),
        (
            "refresh_parameter_shadow_specs",
            "parameter_recompute",
            "read_only_script",
            "python scripts/run_m14_rescue_parameter_shadow_spec.py",
            "Refresh shadow spec rows and candidate variants for manual review.",
        ),
        (
            "refresh_internal_sim_launch_readiness",
            "goal_readiness_recompute",
            "read_only_script",
            "python scripts/run_m14_internal_sim_launch_readiness.py",
            "Recheck approved internal-sim strategies and runtime input coverage.",
        ),
        (
            "refresh_goal_readiness_report",
            "goal_readiness_recompute",
            "read_only_script",
            "python scripts/run_m14_goal_readiness_report.py",
            "Rebuild the top-level goal readiness view from refreshed rescue and broker dry-run inputs.",
        ),
        (
            "refresh_internal_sim_next_session_plan",
            "goal_readiness_recompute",
            "read_only_script",
            "python scripts/run_m14_internal_sim_next_session_plan.py",
            "Refresh the next M12.47-supervised internal-sim session plan.",
        ),
        (
            "objective_audit_first_pass",
            "decision_stabilization",
            "read_only_script",
            "python scripts/run_m14_objective_completion_audit.py",
            "First objective audit pass after lower-level evidence refresh.",
        ),
        (
            "objective_execution_first_pass",
            "decision_stabilization",
            "read_only_script",
            "python scripts/run_m14_objective_execution_plan.py",
            "First execution queue pass from the refreshed objective audit.",
        ),
        (
            "strategy_decision_ladder_refresh",
            "decision_stabilization",
            "read_only_script",
            "python scripts/run_m14_strategy_decision_ladder.py",
            "Refresh strategy-level advance/rescue/hold/discard ladder.",
        ),
        (
            "strategy_evidence_gap_matrix_refresh",
            "decision_stabilization",
            "read_only_script",
            "python scripts/run_m14_strategy_evidence_gap_matrix.py",
            "Refresh per-strategy evidence gaps before the final project stage assessment.",
        ),
        (
            "objective_audit_after_ladder",
            "decision_stabilization",
            "read_only_script",
            "python scripts/run_m14_objective_completion_audit.py",
            "Final audit pass after the decision ladder is fresh.",
        ),
        (
            "objective_execution_after_ladder",
            "decision_stabilization",
            "read_only_script",
            "python scripts/run_m14_objective_execution_plan.py",
            "Final execution queue pass after the final audit.",
        ),
        (
            "strategy_evidence_gap_burndown_refresh",
            "decision_stabilization",
            "read_only_script",
            "python scripts/run_m14_strategy_evidence_gap_burndown.py",
            "Refresh the ordered strategy evidence gap burn-down queue before final assessment.",
        ),
        (
            "strategy_pre_refresh_review_packet_refresh",
            "decision_stabilization",
            "read_only_script",
            "python scripts/run_m14_strategy_pre_refresh_review_packet.py",
            "Refresh the pre-refresh artifact review packet before final assessment.",
        ),
        (
            "strategy_pre_refresh_review_audit_refresh",
            "decision_stabilization",
            "read_only_script",
            "python scripts/run_m14_strategy_pre_refresh_review_audit.py",
            "Audit supporting artifact coverage for pre-refresh review rows before final assessment.",
        ),
        (
            "project_stage_assessment_refresh",
            "final_assessment",
            "read_only_script",
            "python scripts/run_m14_project_stage_assessment.py",
            "Publish the final single-view project stage and goal status.",
        ),
    ]
    steps: list[dict[str, Any]] = []
    for order, (step_id, phase, step_type, command, expected_effect) in enumerate(raw_steps, start=1):
        requires_refresh = phase != "final_assessment" or step_id == "project_stage_assessment_refresh"
        steps.append(
            {
                "order": order,
                "step_id": step_id,
                "phase": phase,
                "step_type": step_type,
                "command": command,
                "required_timing": (
                    "after_m12_47_supervisor_fresh_refresh" if requires_refresh else "after_decision_stabilization"
                ),
                "requires_m12_47_fresh_refresh": requires_refresh,
                "current_state": "ready_after_refresh" if summary["fresh_refresh_observed"] else "waiting_for_m12_47_fresh_refresh",
                "expected_effect": expected_effect,
                "acceptance_hint": acceptance_hint_for(step_id, summary),
                "manual_m12_37_once_allowed": False,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
                "parameter_mutation": False,
                "m13_registry_mutation": False,
                "m12_account_specs_mutation": False,
                "broker_readiness_status_mutation": False,
            }
        )
    return steps


def acceptance_hint_for(step_id: str, summary: dict[str, Any]) -> str:
    hints = {
        "review_post_refresh_outcomes": (
            f"waiting rows should fall from current {summary['post_refresh_waiting_count']} after fresh evidence exists."
        ),
        "refresh_rescue_ab_evidence": (
            f"no-ledger rescue rows should be rechecked from current {summary['rescue_no_m13_ledger_evidence_count']}."
        ),
        "refresh_parameter_activation_gate": (
            "shadow-review candidates may increase only if post-refresh evidence passes; mutation counts must stay 0."
        ),
        "strategy_decision_ladder_refresh": (
            f"final discard allowed should remain 0 until rescue routes and 10-day A/B evidence are exhausted."
        ),
        "strategy_evidence_gap_matrix_refresh": "open-gap rows should explain exactly which evidence remains missing per strategy.",
        "strategy_evidence_gap_burndown_refresh": "P0/P1/P2 rows should translate open gaps into an ordered rescue/internal-sim queue.",
        "strategy_pre_refresh_review_packet_refresh": (
            "review rows should stay review-only, with zero close/promote/discard/mutation allowed."
        ),
        "strategy_pre_refresh_review_audit_refresh": (
            f"artifact backfill rows should stay explainable; current backfill count is {summary['strategy_pre_refresh_review_audit_backfill_count']}."
        ),
        "project_stage_assessment_refresh": "goal_complete must remain false unless objective audit proves every requirement.",
    }
    return hints.get(step_id, "Regenerate the artifact and inspect summary plus hard-boundary flags.")


def build_acceptance_gates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        acceptance_gate(
            "fresh_refresh_source_gate",
            "fresh_refresh_observed=true and quote source is supervisor-owned fresh data.",
            summary["fresh_refresh_observed"],
            f"Current fresh_refresh_observed={summary['fresh_refresh_observed']}, source_quote={summary['source_quote']}.",
        ),
        acceptance_gate(
            "approved_internal_sim_runtime_gate",
            "Approved internal-sim runtime input coverage remains complete.",
            summary["approved_runtime_input_connected_count"] == summary["approved_runtime_input_count"],
            f"{summary['approved_runtime_input_connected_count']}/{summary['approved_runtime_input_count']} approved runtime inputs connected.",
        ),
        acceptance_gate(
            "rescue_first_ledger_gate",
            "No-ledger rescue runtimes get first M13 ledger rows after the fresh refresh.",
            summary["rescue_no_m13_ledger_evidence_count"] == 0,
            f"Current no-ledger rescue count={summary['rescue_no_m13_ledger_evidence_count']}.",
        ),
        acceptance_gate(
            "parameter_shadow_review_gate",
            "Fresh evidence may open manual shadow-review candidates, but parameter mutation remains disabled.",
            summary["parameter_activation_shadow_review_candidate_count"] > 0
            and summary["parameter_mutation_allowed_count"] == 0,
            f"Current shadow-review candidates={summary['parameter_activation_shadow_review_candidate_count']}; mutation allowed=0.",
        ),
        acceptance_gate(
            "no_final_discard_without_rescue_exhaustion_gate",
            "Final discard remains blocked until rescue routes, shadow specs, first ledgers, and 10-day A/B evidence are exhausted.",
            summary["strategy_decision_final_discard_allowed_count"] == 0,
            f"Current final_discard_allowed_count={summary['strategy_decision_final_discard_allowed_count']}.",
        ),
        acceptance_gate(
            "objective_completion_gate",
            "Full objective may only complete when objective audit has no blocked/in-progress requirements.",
            summary["objective_complete"],
            f"Current objective_complete={summary['objective_complete']}; blocked={summary['objective_blocked_count']}; in_progress={summary['objective_in_progress_count']}.",
        ),
        acceptance_gate(
            "broker_live_boundary_gate",
            "Broker/live, real orders, paper approval, registry/account-spec mutation, and manual M12.37 once-mode stay disabled.",
            True,
            "All hard-boundary flags are forced false in this checklist.",
        ),
    ]


def acceptance_gate(gate_id: str, label: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "label": label,
        "state": "passed" if passed else "waiting",
        "evidence": evidence,
        "manual_m12_37_once_allowed": False,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "parameter_mutation": False,
    }


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Post-fresh-refresh recompute checklist has {summary['recompute_step_count']} steps, "
        f"including {summary['m14_script_step_count']} read-only M14 script steps and "
        f"{summary['acceptance_gate_count']} acceptance gates. Current evidence still waits for fresh refresh: "
        f"fresh_refresh_observed={summary['fresh_refresh_observed']}, quote_source={summary['source_quote']}, "
        f"post-refresh waiting rows={summary['post_refresh_waiting_count']}. "
        f"The checklist requires two-pass objective/decision stabilization and keeps final-discard allowed at "
        f"{summary['strategy_decision_final_discard_allowed_count']}. Pre-refresh review audit has "
        f"{summary['strategy_pre_refresh_review_audit_row_count']} rows, with "
        f"{summary['strategy_pre_refresh_review_audit_backfill_count']} supporting-artifact backfills. "
        "Manual M12.37 once-mode, broker/live, "
        "real orders, paper approval, parameter mutation, registry/account-spec mutation, and broker readiness "
        "mutation remain disabled."
    )


def build_checklist_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Post-Fresh-Refresh Recompute Checklist",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Fresh refresh observed: `{summary['fresh_refresh_observed']}`",
        f"- Quote source: `{summary['source_quote']}`",
        f"- Recompute steps: `{summary['recompute_step_count']}`",
        f"- M14 read-only script steps: `{summary['m14_script_step_count']}`",
        f"- Acceptance gates: `{summary['acceptance_gate_count']}`",
        f"- Two-pass stabilization required: `{summary['two_pass_stabilization_required']}`",
        f"- Rescue no-ledger count: `{summary['rescue_no_m13_ledger_evidence_count']}`",
        f"- Parameter shadow specs/variants: `{summary['parameter_shadow_spec_row_count']}/{summary['parameter_shadow_spec_candidate_variant_count']}`",
        f"- Final discard allowed: `{summary['strategy_decision_final_discard_allowed_count']}`",
        f"- Pre-refresh review audit rows/ready/waiting/backfill: `{summary['strategy_pre_refresh_review_audit_row_count']}/{summary['strategy_pre_refresh_review_audit_ready_now_count']}/{summary['strategy_pre_refresh_review_audit_wait_fresh_count']}/{summary['strategy_pre_refresh_review_audit_backfill_count']}`",
        "- Boundary: internal simulated accounts only; no broker connection, no real orders, no live execution, no manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Preconditions",
        "",
    ]
    for row in payload["preconditions"]:
        lines.extend(
            [
                f"- `{row['precondition_id']}`: `{row['state']}` - {row['evidence']}",
            ]
        )
    lines.extend(["", "## Recompute Steps", ""])
    for row in payload["recompute_steps"]:
        command = row["command"] or "(wait for supervisor-owned refresh)"
        lines.extend(
            [
                f"{row['order']}. `{row['step_id']}` ({row['phase']})",
                f"   - Command: `{command}`",
                f"   - Current state: `{row['current_state']}`",
                f"   - Acceptance hint: {row['acceptance_hint']}",
            ]
        )
    lines.extend(["", "## Acceptance Gates", ""])
    for row in payload["acceptance_gates"]:
        lines.append(f"- `{row['gate_id']}`: `{row['state']}` - {row['evidence']}")
    lines.append("")
    return "\n".join(lines)


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
