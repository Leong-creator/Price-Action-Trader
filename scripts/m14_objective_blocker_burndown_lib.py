#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_objective_blocker_burndown.json"
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
class ObjectiveBlockerBurndownConfig:
    stage: str
    objective_completion_audit_path: Path
    project_stage_assessment_path: Path
    strategy_evidence_gap_burndown_path: Path
    strategy_source_visual_confirmation_response_gate_path: Path
    strategy_future_source_reextract_spec_prep_path: Path
    blocker_burndown_json_path: Path
    blocker_burndown_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> ObjectiveBlockerBurndownConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = ObjectiveBlockerBurndownConfig(
        stage=str(payload["stage"]),
        objective_completion_audit_path=resolve_repo_path(inputs["m14_objective_completion_audit"]),
        project_stage_assessment_path=resolve_repo_path(inputs["m14_project_stage_assessment"]),
        strategy_evidence_gap_burndown_path=resolve_repo_path(
            inputs["m14_strategy_evidence_gap_burndown"]
        ),
        strategy_source_visual_confirmation_response_gate_path=resolve_repo_path(
            inputs["m14_strategy_source_visual_confirmation_response_gate"]
        ),
        strategy_future_source_reextract_spec_prep_path=resolve_repo_path(
            inputs["m14_strategy_future_source_reextract_spec_prep"]
        ),
        blocker_burndown_json_path=resolve_repo_path(outputs["blocker_burndown_json"]),
        blocker_burndown_md_path=resolve_repo_path(outputs["blocker_burndown_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: ObjectiveBlockerBurndownConfig) -> None:
    if config.stage != "M14.objective_blocker_burndown":
        raise ValueError("M14 objective blocker burndown stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 objective blocker burndown must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 objective blocker burndown must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 objective blocker burndown cannot enable {key}")


def run_m14_objective_blocker_burndown(
    config: ObjectiveBlockerBurndownConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    objective_audit = read_json(config.objective_completion_audit_path)
    project_stage = read_json(config.project_stage_assessment_path)
    evidence_burndown = read_json(config.strategy_evidence_gap_burndown_path)
    visual_response_gate = read_json(config.strategy_source_visual_confirmation_response_gate_path)
    future_spec_prep = read_json(config.strategy_future_source_reextract_spec_prep_path)

    summary = build_summary(
        objective_audit=objective_audit,
        project_stage=project_stage,
        evidence_burndown=evidence_burndown,
        visual_response_gate=visual_response_gate,
        future_spec_prep=future_spec_prep,
    )
    blocker_rows = build_blocker_rows(summary)
    blocker_rows.sort(key=lambda row: (priority_rank(row["priority"]), int(row["sequence_rank"])))
    row_summary = build_row_summary(blocker_rows)
    summary.update(row_summary)
    summary["legacy_historical_profit_planning_input_count"] = int_or_zero(
        summary.get("future_source_reextract_spec_prep_legacy_historical_profit_planning_input_count")
    ) + int_or_zero(row_summary.get("blocker_row_legacy_historical_profit_planning_input_count"))

    payload: dict[str, Any] = {
        "schema_version": "m14.objective-blocker-burndown.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_objective_completion_audit": project_path(config.objective_completion_audit_path),
            "m14_project_stage_assessment": project_path(config.project_stage_assessment_path),
            "m14_strategy_evidence_gap_burndown": project_path(
                config.strategy_evidence_gap_burndown_path
            ),
            "m14_strategy_source_visual_confirmation_response_gate": project_path(
                config.strategy_source_visual_confirmation_response_gate_path
            ),
            "m14_strategy_future_source_reextract_spec_prep": project_path(
                config.strategy_future_source_reextract_spec_prep_path
            ),
        },
        "summary": summary,
        "blocker_rows": blocker_rows,
        "planning_policy": {
            "purpose": "Summarize the remaining objective blockers without changing strategy state.",
            "evidence_rule": (
                "Planning may use M14 objective audit, project stage, evidence gap burndown, "
                "source visual confirmation response gate, future source-reextract spec prep, "
                "M13 ledger evidence, and M12.47-owned fresh-refresh status."
            ),
            "legacy_history_metric_rule": (
                "Legacy dashboard history fields are excluded from promotion, rescue priority, "
                "parameter activation, broker readiness, and objective completion decisions."
            ),
            "fresh_refresh_rule": "Any evidence-changing refresh must be owned by the M12.47 supervisor.",
            "mutation_rule": "No parameter, registry, account-spec, broker-readiness, broker/live, or manual M12.37 once-mode mutation is allowed.",
        },
        "legacy_history_metric_exclusion": legacy_history_metric_exclusion(),
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.blocker_burndown_json_path, payload)
    config.blocker_burndown_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.blocker_burndown_md_path.write_text(build_burndown_md(payload), encoding="utf-8")
    return payload


def build_summary(
    *,
    objective_audit: dict[str, Any],
    project_stage: dict[str, Any],
    evidence_burndown: dict[str, Any],
    visual_response_gate: dict[str, Any],
    future_spec_prep: dict[str, Any],
) -> dict[str, Any]:
    objective_summary = objective_audit.get("summary", {})
    stage_summary = project_stage.get("summary", {})
    evidence_summary = evidence_burndown.get("summary", {})
    visual_summary = visual_response_gate.get("summary", {})
    future_spec_summary = future_spec_prep.get("summary", {})
    return {
        "current_project_stage": str(
            objective_summary.get("current_project_stage")
            or stage_summary.get("current_project_stage", "")
        ),
        "m14_trading_date": str(
            objective_summary.get("m14_trading_date")
            or project_stage.get("m14_trading_date", "")
        ),
        "objective_complete": bool(objective_summary.get("objective_complete", False)),
        "objective_blockers": list(objective_summary.get("objective_blockers", [])),
        "requirement_count": int_or_zero(objective_summary.get("requirement_count")),
        "proven_count": int_or_zero(objective_summary.get("proven_count")),
        "blocked_count": int_or_zero(objective_summary.get("blocked_count")),
        "in_progress_count": int_or_zero(objective_summary.get("in_progress_count")),
        "guardrail_count": int_or_zero(objective_summary.get("guardrail_count")),
        "ten_day_challenge_complete": bool(objective_summary.get("ten_day_challenge_complete", False)),
        "challenge_progress_label": str(objective_summary.get("challenge_progress_label", "")),
        "approved_internal_sim_strategy_count": int_or_zero(
            objective_summary.get("approved_internal_sim_strategy_count")
        ),
        "approved_internal_sim_strategy_ids": list(
            objective_summary.get("approved_internal_sim_strategy_ids", [])
        ),
        "approved_runtime_input_connected_count": int_or_zero(
            objective_summary.get("approved_runtime_input_connected_count")
        ),
        "approved_runtime_input_count": int_or_zero(objective_summary.get("approved_runtime_input_count")),
        "can_run_next_internal_sim_session": bool(
            stage_summary.get("can_run_next_internal_sim_session", False)
        ),
        "next_session_mode": str(stage_summary.get("next_session_mode", "")),
        "post_refresh_fresh_refresh_observed": bool(
            stage_summary.get("post_refresh_fresh_refresh_observed", False)
        ),
        "post_refresh_source_quote": str(stage_summary.get("post_refresh_source_quote", "")),
        "post_refresh_waiting_count": int_or_zero(stage_summary.get("post_refresh_waiting_count")),
        "rescue_runtime_strategy_count": int_or_zero(
            objective_summary.get("rescue_runtime_strategy_count")
        ),
        "rescue_m13_ledger_observed_strategy_count": int_or_zero(
            objective_summary.get("rescue_m13_ledger_observed_strategy_count")
        ),
        "rescue_no_m13_ledger_evidence_count": int_or_zero(
            objective_summary.get("rescue_no_m13_ledger_evidence_count")
        ),
        "rescue_promotion_allowed_count": int_or_zero(
            objective_summary.get("rescue_promotion_allowed_count")
        ),
        "strategy_evidence_open_gap_row_count": int_or_zero(
            objective_summary.get("strategy_evidence_open_gap_row_count")
        ),
        "strategy_evidence_requires_fresh_refresh_count": int_or_zero(
            objective_summary.get("strategy_evidence_requires_fresh_refresh_count")
        ),
        "strategy_evidence_wait_first_ledger_gap_count": int_or_zero(
            objective_summary.get("strategy_evidence_wait_first_ledger_gap_count")
        ),
        "strategy_evidence_rescue_10_day_ab_gap_count": int_or_zero(
            objective_summary.get("strategy_evidence_rescue_10_day_ab_gap_count")
        ),
        "strategy_evidence_shadow_review_gap_count": int_or_zero(
            objective_summary.get("strategy_evidence_shadow_review_gap_count")
        ),
        "strategy_evidence_burndown_row_count": int_or_zero(evidence_summary.get("burndown_row_count")),
        "strategy_evidence_burndown_p0_count": int_or_zero(evidence_summary.get("p0_row_count")),
        "strategy_evidence_burndown_p1_count": int_or_zero(evidence_summary.get("p1_row_count")),
        "strategy_evidence_burndown_p2_count": int_or_zero(evidence_summary.get("p2_row_count")),
        "strategy_evidence_burndown_pre_refresh_review_available_count": int_or_zero(
            evidence_summary.get("pre_refresh_review_available_count")
        ),
        "parameter_experiment_row_count": int_or_zero(
            objective_summary.get("parameter_experiment_row_count")
        ),
        "parameter_activation_waiting_for_fresh_refresh_count": int_or_zero(
            objective_summary.get("parameter_activation_waiting_for_fresh_refresh_count")
        ),
        "parameter_activation_shadow_review_candidate_count": int_or_zero(
            objective_summary.get("parameter_activation_shadow_review_candidate_count")
        ),
        "parameter_mutation_allowed_count": int_or_zero(
            objective_summary.get("parameter_activation_parameter_mutation_allowed_count")
        ),
        "source_visual_response_gate_row_count": int_or_zero(
            visual_summary.get("source_visual_confirmation_response_gate_row_count")
        ),
        "source_visual_review_pack_ready": bool(
            visual_summary.get("manual_visual_confirmation_review_pack_ready", False)
        ),
        "source_visual_review_pack_question_count": int_or_zero(
            visual_summary.get("review_pack_question_count")
        ),
        "source_visual_review_pack_case_asset_exists_count": int_or_zero(
            visual_summary.get("review_pack_case_asset_exists_count")
        ),
        "source_visual_review_pack_case_asset_count": int_or_zero(
            visual_summary.get("review_pack_case_asset_count")
        ),
        "source_visual_question_pending_count": int_or_zero(
            visual_summary.get("question_response_pending_count")
        ),
        "source_visual_case_pending_count": int_or_zero(visual_summary.get("case_response_pending_count")),
        "source_visual_future_spec_unblocked_count": int_or_zero(
            visual_summary.get("future_spec_unblocked_count")
        ),
        "future_source_reextract_spec_prep_row_count": int_or_zero(
            future_spec_summary.get("future_source_reextract_spec_prep_row_count")
        ),
        "future_source_reextract_spec_prep_conditional_draft_count": int_or_zero(
            future_spec_summary.get("conditional_spec_draft_count")
        ),
        "future_source_reextract_spec_prep_unblocked_count": int_or_zero(
            future_spec_summary.get("future_spec_unblocked_count")
        ),
        "future_source_reextract_spec_prep_blocked_visual_count": int_or_zero(
            future_spec_summary.get("blocked_until_manual_visual_confirmation_count")
        ),
        "future_source_reextract_spec_prep_pending_confirmation_count": int_or_zero(
            future_spec_summary.get("manual_confirmation_pending_count")
        ),
        "future_source_reextract_spec_prep_legacy_historical_profit_planning_input_count": int_or_zero(
            future_spec_summary.get("legacy_historical_profit_planning_input_count")
        ),
        "broker_dry_run_ready_count": int_or_zero(stage_summary.get("broker_dry_run_ready_count")),
        "broker_dry_run_blocked_count": int_or_zero(stage_summary.get("broker_dry_run_blocked_count")),
        "can_start_broker_paper": False,
        "broker_or_live_enabled": False,
        "manual_m12_37_once_allowed": False,
        "legacy_historical_profit_ignored": True,
        "legacy_historical_profit_planning_input_count": int_or_zero(
            future_spec_summary.get("legacy_historical_profit_planning_input_count")
        ),
    }


def build_blocker_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        blocker_row(
            blocker_id="legacy_historical_profit_contamination_guardrail",
            category="metric_exclusion_guardrail",
            priority="P0",
            state="active_guardrail",
            sequence_rank=5,
            evidence=(
                "Legacy account dashboard historical_net_profit/history return fields are treated as old-version "
                "display artifacts and are excluded from every M14 planning decision."
            ),
            next_action="Keep planning tied to M13/M14 ledger, gate, evidence-gap, and M12.47 fresh-refresh artifacts only.",
            waiting_on=[],
            allowed_now=["artifact_review"],
        ),
        blocker_row(
            blocker_id="fresh_refresh_required_before_parameter_activation",
            category="fresh_refresh",
            priority="P0",
            state=(
                "waiting_for_m12_47_fresh_refresh"
                if not summary["post_refresh_fresh_refresh_observed"]
                else "fresh_refresh_observed_recompute_required"
            ),
            sequence_rank=10,
            evidence=(
                f"{summary['post_refresh_waiting_count']} post-refresh watch rows are still waiting; "
                f"source quote state is {summary['post_refresh_source_quote']}."
            ),
            next_action="Wait for the M12.47 supervisor to own the next fresh refresh, then run the read-only post-refresh recompute checklist.",
            waiting_on=["m12_47_supervised_fresh_refresh"],
            allowed_now=["artifact_review", "post_refresh_checklist_review"],
        ),
        blocker_row(
            blocker_id="rescue_first_ledger_gap",
            category="rescue_evidence",
            priority="P0",
            state="waiting_for_first_m13_ledger",
            sequence_rank=20,
            evidence=(
                f"{summary['rescue_no_m13_ledger_evidence_count']} rescue runtimes still need first M13 ledger evidence; "
                f"{summary['rescue_m13_ledger_observed_strategy_count']}/{summary['rescue_runtime_strategy_count']} have ledger evidence."
            ),
            next_action="After the next M12.47-owned refresh, verify first strategy/account ledger rows before any promotion or discard decision.",
            waiting_on=["m12_47_supervised_fresh_refresh", "m13_rescue_ledger_rows"],
            allowed_now=["runtime_registry_readonly_review", "ledger_mapping_review"],
        ),
        blocker_row(
            blocker_id="rescue_10_day_ab_gap",
            category="rescue_evidence",
            priority="P0",
            state="rescue_ab_window_incomplete",
            sequence_rank=30,
            evidence=(
                f"{summary['strategy_evidence_rescue_10_day_ab_gap_count']} rescue 10-day A/B gaps remain; "
                f"promotion allowed count is {summary['rescue_promotion_allowed_count']}."
            ),
            next_action="Continue collecting rescue A/B evidence under M12.47/M13/M14; do not promote or abandon weak strategies from old history metrics.",
            waiting_on=["rescue_10_day_ab_window", "manual_m14_review"],
            allowed_now=["artifact_review", "ab_contract_review"],
        ),
        blocker_row(
            blocker_id="parameter_shadow_activation_gap",
            category="parameter_optimization",
            priority="P1",
            state="waiting_for_fresh_evidence_no_mutation",
            sequence_rank=40,
            evidence=(
                f"{summary['parameter_experiment_row_count']} parameter experiment rows exist; "
                f"{summary['parameter_activation_waiting_for_fresh_refresh_count']} activation rows are waiting for fresh refresh; "
                f"mutation allowed count is {summary['parameter_mutation_allowed_count']}."
            ),
            next_action="Keep parameter variants in shadow review until fresh M13/M14 evidence clears activation gates.",
            waiting_on=["fresh_m13_m14_evidence", "activation_gate_review"],
            allowed_now=["shadow_spec_review", "activation_gate_readonly_review"],
        ),
        blocker_row(
            blocker_id="source_visual_manual_confirmation_gap",
            category="source_reextract",
            priority="P1",
            state="manual_visual_confirmation_pending",
            sequence_rank=50,
            evidence=(
                f"Review pack ready={summary['source_visual_review_pack_ready']} with "
                f"{summary['source_visual_review_pack_case_asset_exists_count']}/"
                f"{summary['source_visual_review_pack_case_asset_count']} local case assets; "
                f"{summary['source_visual_question_pending_count']} question responses and "
                f"{summary['source_visual_case_pending_count']} case responses are pending; "
                f"future spec unblocked count is {summary['source_visual_future_spec_unblocked_count']}; "
                f"spec-prep conditional/unblocked/blocked rows are "
                f"{summary['future_source_reextract_spec_prep_conditional_draft_count']}/"
                f"{summary['future_source_reextract_spec_prep_unblocked_count']}/"
                f"{summary['future_source_reextract_spec_prep_blocked_visual_count']}, "
                f"pending confirmations={summary['future_source_reextract_spec_prep_pending_confirmation_count']}, "
                f"legacy-history planning inputs="
                f"{summary['future_source_reextract_spec_prep_legacy_historical_profit_planning_input_count']}."
            ),
            next_action="Use the static visual review pack for manual confirmation, rerun the response gate and future spec prep, then draft only after manual M14 review.",
            waiting_on=["manual_visual_confirmation_response"],
            allowed_now=["manual_review_pack_review", "conditional_spec_prep_review"],
        ),
        blocker_row(
            blocker_id="broker_dry_run_watch_only",
            category="broker_readiness",
            priority="P1",
            state="dry_run_preview_only",
            sequence_rank=60,
            evidence=(
                f"Broker dry-run rows: ready={summary['broker_dry_run_ready_count']}, "
                f"blocked={summary['broker_dry_run_blocked_count']}; broker paper start is disabled."
            ),
            next_action="Keep broker readiness as dry-run engineering preview until internal-sim evidence and blockers are clean.",
            waiting_on=["internal_sim_evidence", "broker_blocker_repair_review"],
            allowed_now=["dry_run_artifact_review"],
        ),
    ]
    return rows


def blocker_row(
    *,
    blocker_id: str,
    category: str,
    priority: str,
    state: str,
    sequence_rank: int,
    evidence: str,
    next_action: str,
    waiting_on: list[str],
    allowed_now: list[str],
) -> dict[str, Any]:
    return {
        "blocker_id": blocker_id,
        "category": category,
        "priority": priority,
        "state": state,
        "sequence_rank": sequence_rank,
        "evidence": evidence,
        "next_action": next_action,
        "waiting_on": waiting_on,
        "allowed_now": allowed_now,
        "excluded_metrics": list(legacy_history_metric_exclusion()["excluded_metric_names"])
        if blocker_id == "legacy_historical_profit_contamination_guardrail"
        else [],
        "can_close_objective_now": False,
        "can_promote_strategy_now": False,
        "can_discard_strategy_now": False,
        "can_activate_parameter_now": False,
        "can_start_broker_paper": False,
        "manual_m12_37_once_allowed": False,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "parameter_mutation": False,
        "legacy_historical_profit_planning_input": False,
    }


def build_row_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    priority_counts = Counter(row["priority"] for row in rows)
    category_counts = Counter(row["category"] for row in rows)
    return {
        "blocker_burndown_row_count": len(rows),
        "p0_blocker_count": priority_counts.get("P0", 0),
        "p1_blocker_count": priority_counts.get("P1", 0),
        "p2_blocker_count": priority_counts.get("P2", 0),
        "priority_counts": dict(sorted(priority_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "objective_closure_allowed_count": sum(1 for row in rows if row["can_close_objective_now"]),
        "strategy_promotion_allowed_count": sum(1 for row in rows if row["can_promote_strategy_now"]),
        "strategy_discard_allowed_count": sum(1 for row in rows if row["can_discard_strategy_now"]),
        "parameter_activation_allowed_count": sum(1 for row in rows if row["can_activate_parameter_now"]),
        "broker_paper_start_allowed_count": sum(1 for row in rows if row["can_start_broker_paper"]),
        "manual_m12_37_once_allowed_count": sum(1 for row in rows if row["manual_m12_37_once_allowed"]),
        "blocker_row_legacy_historical_profit_planning_input_count": sum(
            1 for row in rows if row["legacy_historical_profit_planning_input"]
        ),
    }


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Objective blocker burndown has {summary['blocker_burndown_row_count']} rows "
        f"with P0/P1/P2={summary['p0_blocker_count']}/{summary['p1_blocker_count']}/"
        f"{summary['p2_blocker_count']}. The project is still not complete: "
        f"10-day challenge is {summary['challenge_progress_label']}, "
        f"{summary['approved_internal_sim_strategy_count']} strategies may continue internal simulation, "
        f"but {summary['rescue_no_m13_ledger_evidence_count']} rescue runtimes need first ledger evidence, "
        f"{summary['strategy_evidence_rescue_10_day_ab_gap_count']} rescue A/B gaps remain, "
        f"and {summary['source_visual_question_pending_count']} question plus "
        f"{summary['source_visual_case_pending_count']} case visual confirmations are pending. "
        f"Future source-reextract prep has {summary['future_source_reextract_spec_prep_row_count']} rows, "
        f"{summary['future_source_reextract_spec_prep_unblocked_count']} unblocked, and "
        f"{summary['future_source_reextract_spec_prep_legacy_historical_profit_planning_input_count']} legacy-history planning inputs. "
        "Legacy historical net-profit/history-return dashboard fields are explicitly ignored for planning. "
        "Broker/live, real orders, paper approval, parameter mutation, and manual M12.37 once-mode remain disabled."
    )


def build_burndown_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    metric_policy = payload["legacy_history_metric_exclusion"]
    lines = [
        "# M14 Objective Blocker Burndown",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Objective complete: `{summary['objective_complete']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Blocker rows P0/P1/P2: `{summary['p0_blocker_count']}/{summary['p1_blocker_count']}/{summary['p2_blocker_count']}`",
        f"- Approved internal-sim strategies: `{summary['approved_internal_sim_strategy_count']}` (`{', '.join(summary['approved_internal_sim_strategy_ids'])}`)",
        f"- Rescue first-ledger / 10-day A/B / shadow-review gaps: `{summary['rescue_no_m13_ledger_evidence_count']}/{summary['strategy_evidence_rescue_10_day_ab_gap_count']}/{summary['strategy_evidence_shadow_review_gap_count']}`",
        f"- Visual confirmation pending questions / cases: `{summary['source_visual_question_pending_count']}/{summary['source_visual_case_pending_count']}`",
        f"- Future source-reextract spec prep rows/drafts/unblocked/blocked/pending: `{summary['future_source_reextract_spec_prep_row_count']}/{summary['future_source_reextract_spec_prep_conditional_draft_count']}/{summary['future_source_reextract_spec_prep_unblocked_count']}/{summary['future_source_reextract_spec_prep_blocked_visual_count']}/{summary['future_source_reextract_spec_prep_pending_confirmation_count']}`",
        f"- Legacy history metric planning inputs: `{summary['legacy_historical_profit_planning_input_count']}`",
        "- Boundary: internal simulated accounts only; no broker/live, no real orders, no paper approval, no manual M12.37 once-mode, no parameter mutation.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Legacy Metric Exclusion",
        "",
        f"- Excluded metrics: `{', '.join(metric_policy['excluded_metric_names'])}`",
        f"- Excluded from: `{', '.join(metric_policy['excluded_from_decisions'])}`",
        f"- Reason: {metric_policy['reason']}",
        "",
        "## Blocker Rows",
        "",
    ]
    for row in payload["blocker_rows"]:
        lines.extend(
            [
                f"### {row['priority']} {row['blocker_id']}",
                "",
                f"- Category: `{row['category']}`",
                f"- State: `{row['state']}`",
                f"- Evidence: {row['evidence']}",
                f"- Next action: {row['next_action']}",
                f"- Waiting on: `{', '.join(row['waiting_on']) or 'none'}`",
                f"- Allowed now: `{', '.join(row['allowed_now']) or 'none'}`",
                f"- Strategy promotion / discard allowed: `{row['can_promote_strategy_now']}/{row['can_discard_strategy_now']}`",
                f"- Parameter activation allowed: `{row['can_activate_parameter_now']}`",
                f"- Broker paper start allowed: `{row['can_start_broker_paper']}`",
                f"- Legacy history metric planning input: `{row['legacy_historical_profit_planning_input']}`",
                "",
            ]
        )
    return "\n".join(lines)


def legacy_history_metric_exclusion() -> dict[str, Any]:
    return {
        "legacy_historical_profit_ignored": True,
        "excluded_metric_names": [
            "historical_net_profit",
            "historical_profit_factor",
            "historical_return_percent",
            "历史净利润",
            "历史收益",
        ],
        "excluded_from_decisions": [
            "strategy_promotion",
            "rescue_priority",
            "parameter_activation",
            "broker_readiness",
            "objective_completion",
        ],
        "replacement_evidence_sources": [
            "m13_signal_ledger",
            "m13_account_operation_ledger",
            "m14_objective_completion_audit",
            "m14_strategy_evidence_gap_burndown",
            "m14_project_stage_assessment",
            "m12_47_supervised_fresh_refresh_status",
        ],
        "reason": "The account drilldown historical net-profit/history-return fields can contain old-version contaminated values and must not steer M14 strategy planning.",
    }


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


def priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(priority, 9)


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
