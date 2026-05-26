#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_parameter_shadow_spec.json"


@dataclass(frozen=True, slots=True)
class RescueParameterShadowSpecConfig:
    stage: str
    parameter_experiment_queue_path: Path
    parameter_activation_gate_path: Path
    target_stop_shadow_normalization_path: Path
    broker_blocker_shadow_ab_prep_path: Path
    broker_blocker_rule_shadow_evidence_path: Path
    rescue_external_reference_map_path: Path
    shadow_spec_json_path: Path
    shadow_spec_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescueParameterShadowSpecConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescueParameterShadowSpecConfig(
        stage=str(payload["stage"]),
        parameter_experiment_queue_path=resolve_repo_path(inputs["m14_rescue_parameter_experiment_queue"]),
        parameter_activation_gate_path=resolve_repo_path(inputs["m14_rescue_parameter_activation_gate"]),
        target_stop_shadow_normalization_path=resolve_repo_path(
            inputs["m14_rescue_target_stop_shadow_normalization"]
        ),
        broker_blocker_shadow_ab_prep_path=resolve_repo_path(
            inputs["m14_2_broker_blocker_shadow_ab_prep"]
        ),
        broker_blocker_rule_shadow_evidence_path=resolve_repo_path(
            inputs["m14_2_broker_blocker_rule_shadow_evidence"]
        ),
        rescue_external_reference_map_path=resolve_repo_path(inputs["m14_rescue_external_reference_map"]),
        shadow_spec_json_path=resolve_repo_path(outputs["shadow_spec_json"]),
        shadow_spec_md_path=resolve_repo_path(outputs["shadow_spec_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescueParameterShadowSpecConfig) -> None:
    if config.stage != "M14.rescue_parameter_shadow_spec":
        raise ValueError("M14 rescue parameter shadow spec stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue parameter shadow spec must stay paper/simulated only")
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
            raise ValueError(f"M14 rescue parameter shadow spec cannot enable {key}")


def run_m14_rescue_parameter_shadow_spec(
    config: RescueParameterShadowSpecConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    queue = read_json(config.parameter_experiment_queue_path)
    activation_gate = read_json(config.parameter_activation_gate_path)
    target_stop = read_json(config.target_stop_shadow_normalization_path)
    broker_prep = read_json(config.broker_blocker_shadow_ab_prep_path)
    rule_evidence = read_json(config.broker_blocker_rule_shadow_evidence_path)
    external_map = read_json(config.rescue_external_reference_map_path)

    gate_by_experiment = {
        str(row.get("experiment_row_id", "")): dict(row)
        for row in activation_gate.get("gate_rows", [])
        if row.get("experiment_row_id")
    }
    target_by_strategy = {str(row.get("strategy_id", "")): dict(row) for row in target_stop.get("rows", [])}
    broker_prep_rows = [dict(row) for row in broker_prep.get("rows", [])]
    rule_evidence_rows = [dict(row) for row in rule_evidence.get("rows", [])]
    external_by_strategy = build_external_strategy_map(external_map)

    spec_rows = [
        build_spec_row(
            experiment_row=dict(row),
            gate_row=gate_by_experiment.get(str(row.get("experiment_row_id", "")), {}),
            target_stop_row=target_by_strategy.get(str(row.get("strategy_id", "")), {}),
            broker_prep_row=matching_broker_prep_row(dict(row), broker_prep_rows),
            rule_evidence_row=matching_rule_evidence_row(dict(row), rule_evidence_rows),
            external_row=external_by_strategy.get(str(row.get("strategy_id", "")), {}),
        )
        for row in queue.get("experiment_rows", [])
    ]
    spec_rows.sort(key=lambda row: (row["priority"], row["strategy_id"], row["experiment_family"], row["spec_row_id"]))

    family_counts = Counter(row["experiment_family"] for row in spec_rows)
    state_counts = Counter(row["spec_state"] for row in spec_rows)
    variant_type_counts = Counter(
        variant["variant_type"]
        for row in spec_rows
        for variant in row["candidate_variants"]
    )
    summary = {
        "project_stage": str(queue.get("summary", {}).get("project_stage", "")),
        "fresh_refresh_observed": bool(activation_gate.get("summary", {}).get("fresh_refresh_observed", False)),
        "source_quote": str(activation_gate.get("summary", {}).get("source_quote", "")),
        "source_experiment_row_count": int_or_zero(queue.get("summary", {}).get("experiment_row_count")),
        "activation_gate_row_count": int_or_zero(activation_gate.get("summary", {}).get("gate_row_count")),
        "spec_row_count": len(spec_rows),
        "candidate_variant_count": sum(len(row["candidate_variants"]) for row in spec_rows),
        "ready_for_manual_shadow_review_count": sum(
            1 for row in spec_rows if row["ready_for_manual_shadow_review"]
        ),
        "waiting_for_fresh_refresh_count": sum(1 for row in spec_rows if row["requires_m12_47_fresh_refresh"]),
        "wait_first_ledger_count": state_counts.get("wait_first_ledger_before_parameter_decision", 0),
        "parent_detector_wait_count": state_counts.get("wait_parent_detector_evidence_before_spec", 0),
        "continue_ab_only_count": state_counts.get("continue_ab_collection_no_new_parameter_spec", 0),
        "target_stop_shadow_variant_count": variant_type_counts.get("target_stop_shadow", 0),
        "broker_quantity_cap_variant_count": variant_type_counts.get("broker_quantity_cap_shadow", 0),
        "broker_rule_shadow_variant_count": (
            variant_type_counts.get("broker_exposure_ranker_shadow", 0)
            + variant_type_counts.get("broker_cooldown_quality_shadow", 0)
        ),
        "fresh_recheck_variant_count": variant_type_counts.get("fresh_quote_recheck", 0),
        "parameter_mutation_allowed_count": 0,
        "implementation_mutation_allowed_count": 0,
        "m13_registry_mutation_count": 0,
        "m12_account_specs_mutation_count": 0,
        "broker_readiness_status_mutation_count": 0,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "copy_trading_allowed": False,
        "external_override_allowed": False,
        "spec_state_counts": dict(sorted(state_counts.items())),
        "experiment_family_counts": dict(sorted(family_counts.items())),
        "candidate_variant_type_counts": dict(sorted(variant_type_counts.items())),
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.rescue-parameter-shadow-spec.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_rescue_parameter_experiment_queue": project_path(config.parameter_experiment_queue_path),
            "m14_rescue_parameter_activation_gate": project_path(config.parameter_activation_gate_path),
            "m14_rescue_target_stop_shadow_normalization": project_path(
                config.target_stop_shadow_normalization_path
            ),
            "m14_2_broker_blocker_shadow_ab_prep": project_path(config.broker_blocker_shadow_ab_prep_path),
            "m14_2_broker_blocker_rule_shadow_evidence": project_path(
                config.broker_blocker_rule_shadow_evidence_path
            ),
            "m14_rescue_external_reference_map": project_path(config.rescue_external_reference_map_path),
        },
        "summary": summary,
        "spec_rows": spec_rows,
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
    write_json(config.shadow_spec_json_path, payload)
    config.shadow_spec_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.shadow_spec_md_path.write_text(build_shadow_spec_md(payload), encoding="utf-8")
    return payload


def build_external_strategy_map(external_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = list(external_map.get("rescue_reference_rows", [])) + list(
        external_map.get("broker_blocker_reference_rows", [])
    )
    mapped: dict[str, dict[str, Any]] = {}
    for row in rows:
        strategy_id = str(row.get("strategy_id", ""))
        if strategy_id and strategy_id not in mapped:
            mapped[strategy_id] = dict(row)
    return mapped


def matching_broker_prep_row(experiment_row: dict[str, Any], prep_rows: list[dict[str, Any]]) -> dict[str, Any]:
    strategy_id = str(experiment_row.get("strategy_id", ""))
    dominant_issue = str(experiment_row.get("dominant_issue", ""))
    expected_reason = {
        "max_risk_per_order_exceeded": "max_risk_per_order_exceeded",
        "max_total_exposure_exceeded": "max_total_exposure_exceeded",
        "consecutive_losses_limit": "consecutive_losses_limit",
    }.get(dominant_issue, "")
    for row in prep_rows:
        if str(row.get("strategy_id", "")) != strategy_id:
            continue
        if expected_reason and expected_reason not in list(row.get("source_reason_codes", [])):
            continue
        return dict(row)
    return {}


def matching_rule_evidence_row(experiment_row: dict[str, Any], evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    strategy_id = str(experiment_row.get("strategy_id", ""))
    dominant_issue = str(experiment_row.get("dominant_issue", ""))
    expected_family = {
        "max_total_exposure_exceeded": "portfolio_exposure_ranker",
        "consecutive_losses_limit": "cooldown_quality_veto",
    }.get(dominant_issue, "")
    for row in evidence_rows:
        if str(row.get("strategy_id", "")) != strategy_id:
            continue
        if expected_family and str(row.get("rule_family", "")) != expected_family:
            continue
        return dict(row)
    return {}


def build_spec_row(
    *,
    experiment_row: dict[str, Any],
    gate_row: dict[str, Any],
    target_stop_row: dict[str, Any],
    broker_prep_row: dict[str, Any],
    rule_evidence_row: dict[str, Any],
    external_row: dict[str, Any],
) -> dict[str, Any]:
    experiment_family = str(experiment_row.get("experiment_family", ""))
    gate_state = str(gate_row.get("gate_state", ""))
    candidate_variants = candidate_variants_for(
        experiment_row=experiment_row,
        target_stop_row=target_stop_row,
        broker_prep_row=broker_prep_row,
        rule_evidence_row=rule_evidence_row,
    )
    spec_state = classify_spec_state(experiment_family, gate_state, str(experiment_row.get("status", "")))
    requires_fresh = spec_state in {
        "shadow_spec_prepared_wait_fresh_refresh",
        "fresh_recheck_spec_ready_wait_refresh",
        "wait_first_ledger_before_parameter_decision",
    }
    return {
        "spec_row_id": f"m14-param-spec-{slug(str(experiment_row.get('experiment_row_id', '')))}",
        "experiment_row_id": str(experiment_row.get("experiment_row_id", "")),
        "gate_row_id": str(gate_row.get("gate_row_id", "")),
        "strategy_id": str(experiment_row.get("strategy_id", "")),
        "parent_strategy_id": str(experiment_row.get("parent_strategy_id", "")),
        "runtime_ids": list(experiment_row.get("runtime_ids", [])),
        "priority": str(experiment_row.get("priority", "")),
        "issue_type": str(experiment_row.get("issue_type", "")),
        "dominant_issue": str(experiment_row.get("dominant_issue", "")),
        "experiment_family": experiment_family,
        "candidate_parameter_family": str(experiment_row.get("candidate_parameter_family", "")),
        "candidate_change_scope": str(experiment_row.get("candidate_change_scope", "")),
        "source_experiment_status": str(experiment_row.get("status", "")),
        "activation_gate_state": gate_state,
        "activation_gate_reason": str(gate_row.get("gate_reason", "")),
        "spec_state": spec_state,
        "requires_m12_47_fresh_refresh": requires_fresh,
        "ready_for_manual_shadow_review": bool(gate_row.get("shadow_review_candidate", False)),
        "candidate_variants": candidate_variants,
        "variant_count": len(candidate_variants),
        "acceptance_criteria": acceptance_criteria_for(experiment_row, candidate_variants),
        "external_reference_pattern_ids": list(external_row.get("external_reference_pattern_ids", [])),
        "external_review_lanes": list(
            experiment_row.get("external_review_lanes", []) or external_row.get("local_review_lanes", [])
        ),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
        "implementation_mutation_allowed": False,
        "parameter_mutation_allowed": False,
    }


def classify_spec_state(experiment_family: str, gate_state: str, source_status: str) -> str:
    if experiment_family == "continue_ab_evidence_collection":
        return "continue_ab_collection_no_new_parameter_spec"
    if experiment_family == "ledger_path_mapping_audit":
        return "wait_first_ledger_before_parameter_decision"
    if experiment_family == "parent_detector_timeframe_mapping_review":
        return "wait_parent_detector_evidence_before_spec"
    if gate_state == "ready_for_shadow_parameter_review":
        return "ready_for_manual_shadow_review_no_mutation"
    if experiment_family == "fresh_quote_gate_recheck":
        return "fresh_recheck_spec_ready_wait_refresh"
    if source_status in {"blocked_until_fresh_refresh", "shadow_runtime_wait_first_ledger"}:
        return "shadow_spec_prepared_wait_fresh_refresh"
    return "review_spec_prepared_no_mutation"


def candidate_variants_for(
    *,
    experiment_row: dict[str, Any],
    target_stop_row: dict[str, Any],
    broker_prep_row: dict[str, Any],
    rule_evidence_row: dict[str, Any],
) -> list[dict[str, Any]]:
    family = str(experiment_row.get("experiment_family", ""))
    if family == "fresh_quote_gate_recheck":
        return fresh_quote_variants(experiment_row)
    if family == "target_stop_reward_geometry_shadow":
        return target_stop_variants(target_stop_row)
    if family == "ledger_path_mapping_audit":
        return ledger_mapping_variants(experiment_row)
    if family == "parent_detector_timeframe_mapping_review":
        return parent_detector_variants(experiment_row)
    if family == "quantity_cap_shadow":
        return broker_quantity_cap_variants(broker_prep_row)
    if family == "exposure_ranker_shadow":
        return broker_rule_variants(rule_evidence_row or broker_prep_row, "broker_exposure_ranker_shadow")
    if family == "cooldown_quality_veto_shadow":
        return broker_rule_variants(rule_evidence_row or broker_prep_row, "broker_cooldown_quality_shadow")
    if family == "continue_ab_evidence_collection":
        return continue_ab_variants(experiment_row)
    return manual_review_variants(experiment_row)


def fresh_quote_variants(experiment_row: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = dict(experiment_row.get("source_metrics", {}))
    return [
        {
            "variant_id": "fresh_quote_recheck_no_parameter_change",
            "variant_type": "fresh_quote_recheck",
            "change_summary": "Recheck the existing rescue runtime with fresh Longbridge readonly quotes before changing any detector or threshold.",
            "parameter_values": {
                "quote_source_required": "longbridge_quote_readonly",
                "parameter_change": "none_before_fresh_evidence",
                "eligible_if_fresh_quote_count": int_or_zero(metrics.get("eligible_if_fresh_quote_count")),
            },
            "comparison_baseline": "current_rescue_runtime",
            "required_evidence": [
                "fresh M12.47-owned quote refresh",
                "source-row and signal-count comparison",
            ],
            "parameter_mutation_allowed": False,
        }
    ]


def target_stop_variants(target_stop_row: dict[str, Any]) -> list[dict[str, Any]]:
    if not target_stop_row:
        return [
            {
                "variant_id": "target_stop_shadow_pending_diagnostics",
                "variant_type": "target_stop_shadow",
                "change_summary": "Wait for target/stop diagnostics before choosing a normalized reward geometry.",
                "parameter_values": {"target_stop_policy": "pending_diagnostics"},
                "comparison_baseline": "frozen_rescue_runtime",
                "required_evidence": ["target/stop diagnostics row"],
                "parameter_mutation_allowed": False,
            }
        ]
    return [
        {
            "variant_id": str(target_stop_row.get("best_variant_id", "")),
            "variant_type": "target_stop_shadow",
            "change_summary": "Shadow-test normalized 1.0R target geometry without lowering the frozen runtime min-R threshold.",
            "parameter_values": {
                "shadow_runtime_id": str(target_stop_row.get("best_variant_candidate_runtime_id", "")),
                "target_rule": "entry_plus_1_0r",
                "eligible_candidate_count": int_or_zero(target_stop_row.get("eligible_source_row_count")),
                "best_variant_candidate_count": int_or_zero(target_stop_row.get("best_variant_candidate_count")),
                "current_reward_r_min": str(target_stop_row.get("current_reward_r_min", "")),
                "current_reward_r_max": str(target_stop_row.get("current_reward_r_max", "")),
                "current_reward_ge_1_0_count": int_or_zero(target_stop_row.get("current_reward_ge_1_0_count")),
            },
            "comparison_baseline": "frozen_rescue_runtime",
            "required_evidence": [
                "fresh M12.47-owned refresh",
                "first M13 ledger row for the target/stop shadow runtime",
                "10 rescue A/B trading days before any policy decision",
            ],
            "parameter_mutation_allowed": False,
        }
    ]


def ledger_mapping_variants(experiment_row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "variant_id": "ledger_mapping_audit_no_parameter_change",
            "variant_type": "ledger_mapping_audit",
            "change_summary": "Audit registry, M12 account input, signal ledger, and account ledger mapping before any parameter decision.",
            "parameter_values": {
                "runtime_ids": list(experiment_row.get("runtime_ids", [])),
                "parameter_change": "none",
            },
            "comparison_baseline": "runtime_mapping_contract",
            "required_evidence": ["first M13 signal or account ledger row"],
            "parameter_mutation_allowed": False,
        }
    ]


def parent_detector_variants(experiment_row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "variant_id": "same_timeframe_parent_detector_evidence",
            "variant_type": "parent_detector_review",
            "change_summary": "Require same-timeframe parent detector evidence before remapping or rebuilding the rescue detector.",
            "parameter_values": {
                "parent_strategy_id": str(experiment_row.get("parent_strategy_id", "")),
                "cross_timeframe_remap": "not_allowed_without_separate_review",
            },
            "comparison_baseline": "same_timeframe_parent_detector",
            "required_evidence": ["fresh same-timeframe parent detector source rows"],
            "parameter_mutation_allowed": False,
        }
    ]


def broker_quantity_cap_variants(prep_row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "variant_id": str(prep_row.get("proposed_variant_id", "broker_risk_cap_shadow")),
            "variant_type": "broker_quantity_cap_shadow",
            "change_summary": "Shadow-test the quantity cap that brings per-order risk back to the existing internal limit.",
            "parameter_values": {
                "source_quantity": str(prep_row.get("source_quantity", "")),
                "proposed_quantity": str(prep_row.get("proposed_quantity", "")),
                "source_risk_amount": str(prep_row.get("source_risk_amount", "")),
                "proposed_risk_amount": str(prep_row.get("proposed_risk_amount", "")),
                "proposed_shadow_runtime_id": str(prep_row.get("proposed_shadow_runtime_id", "")),
                "symbol": str(prep_row.get("symbol", "")),
                "timeframe": str(prep_row.get("timeframe", "")),
            },
            "comparison_baseline": "original_blocked_internal_sim_risk_check",
            "required_evidence": [
                "fresh internal-sim dry-run row",
                "risk amount at or below the existing limit",
                "original broker readiness row remains blocked",
            ],
            "parameter_mutation_allowed": False,
        }
    ]


def broker_rule_variants(row: dict[str, Any], variant_type: str) -> list[dict[str, Any]]:
    variant_id = str(row.get("proposed_variant_id", variant_type))
    rule_family = str(row.get("rule_family", "")) or str(row.get("prep_action", ""))
    return [
        {
            "variant_id": variant_id,
            "variant_type": variant_type,
            "change_summary": str(row.get("comparison_contract") or row.get("ab_test_hypothesis") or row.get("next_action", "")),
            "parameter_values": {
                "rule_family": rule_family,
                "shadow_rule_decision": str(row.get("shadow_rule_decision", "")),
                "proposed_shadow_strategy_id": str(row.get("proposed_shadow_strategy_id", "")),
                "source_reason_codes": list(row.get("source_reason_codes", [])),
                "symbol": str(row.get("symbol", "")),
                "timeframe": str(row.get("timeframe", "")),
            },
            "comparison_baseline": "original_blocked_internal_sim_risk_check",
            "required_evidence": [
                "fresh internal-sim rule comparison",
                "no readiness-status mutation",
                "risk halt and exposure guardrails preserved",
            ],
            "parameter_mutation_allowed": False,
        }
    ]


def continue_ab_variants(experiment_row: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = dict(experiment_row.get("source_metrics", {}))
    return [
        {
            "variant_id": "continue_current_rescue_ab_window",
            "variant_type": "ab_evidence_only",
            "change_summary": "Keep collecting the current rescue runtime's own 10-trading-day A/B evidence.",
            "parameter_values": {
                "observed_trading_days_count": int_or_zero(metrics.get("observed_trading_days_count")),
                "remaining_ab_trading_days": int_or_zero(metrics.get("remaining_ab_trading_days")),
                "parameter_change": "none",
            },
            "comparison_baseline": "current_rescue_runtime",
            "required_evidence": ["full 10 rescue A/B trading-day window"],
            "parameter_mutation_allowed": False,
        }
    ]


def manual_review_variants(experiment_row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "variant_id": f"manual_review_{slug(str(experiment_row.get('strategy_id', '')))}",
            "variant_type": "manual_review_only",
            "change_summary": "Manual M14 review must decide whether a later shadow spec is warranted.",
            "parameter_values": {"parameter_change": "none_before_review"},
            "comparison_baseline": "current_artifact_state",
            "required_evidence": ["manual M14 review notes"],
            "parameter_mutation_allowed": False,
        }
    ]


def acceptance_criteria_for(experiment_row: dict[str, Any], variants: list[dict[str, Any]]) -> list[str]:
    criteria = [
        "No broker connection, live execution, real order, paper approval, or manual M12.37 once-mode.",
        "No M13 registry, M12 account-spec, broker-readiness, implementation, or parameter mutation from this spec.",
    ]
    criteria.extend(str(item) for item in experiment_row.get("required_evidence", []))
    for variant in variants:
        criteria.extend(str(item) for item in variant.get("required_evidence", []))
    return sorted(dict.fromkeys(item for item in criteria if item))


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Parameter shadow spec prepared {summary['spec_row_count']} rows and "
        f"{summary['candidate_variant_count']} candidate variants. "
        f"{summary['waiting_for_fresh_refresh_count']} rows still wait for M12.47-owned fresh evidence, "
        f"{summary['target_stop_shadow_variant_count']} target/stop shadow variant and "
        f"{summary['broker_quantity_cap_variant_count'] + summary['broker_rule_shadow_variant_count']} broker-blocker shadow variants are specified. "
        "This is a review/spec artifact only: parameter mutation, implementation mutation, registry/account-spec mutation, "
        "broker readiness mutation, broker/live, real orders, paper approval, and manual M12.37 once-mode remain disabled."
    )


def build_shadow_spec_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Rescue Parameter Shadow Spec",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Project stage: `{summary['project_stage']}`",
        f"- Fresh refresh observed: `{summary['fresh_refresh_observed']}`",
        f"- Quote source: `{summary['source_quote']}`",
        f"- Spec rows: `{summary['spec_row_count']}`",
        f"- Candidate variants: `{summary['candidate_variant_count']}`",
        f"- Waiting for fresh refresh: `{summary['waiting_for_fresh_refresh_count']}`",
        f"- Target/stop shadow variants: `{summary['target_stop_shadow_variant_count']}`",
        f"- Broker quantity/rule shadow variants: `{summary['broker_quantity_cap_variant_count']}/{summary['broker_rule_shadow_variant_count']}`",
        f"- Parameter mutation allowed: `{summary['parameter_mutation_allowed_count']}`",
        "- Boundary: spec/review only; no implementation or parameter mutation, no registry/account-spec/broker-readiness mutation, no broker/live, no manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Spec Rows",
        "",
    ]
    for row in payload["spec_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} / {row['experiment_family']}",
                "",
                f"- State: `{row['spec_state']}`",
                f"- Gate state: `{row['activation_gate_state']}`",
                f"- Candidate parameter family: `{row['candidate_parameter_family']}`",
                f"- Variant count: `{row['variant_count']}`",
                f"- Fresh refresh required: `{row['requires_m12_47_fresh_refresh']}`",
                f"- Ready for manual shadow review: `{row['ready_for_manual_shadow_review']}`",
                "",
                "Variants:",
            ]
        )
        for variant in row["candidate_variants"]:
            lines.extend(
                [
                    f"- `{variant['variant_id']}` / `{variant['variant_type']}`: {variant['change_summary']}",
                ]
            )
        lines.append("")
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
